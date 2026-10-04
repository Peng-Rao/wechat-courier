"""Stable encrypted DB/WAL snapshots with private ownership and safe cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .native import (ContactError, check_budget, current_job_identity,
                     process_start_time, verified_path)


PREFIX = "wechat-contact-"
_JOB_NAME = re.compile(r"wechat-contact-([0-9a-f]{32})\Z")
_MAX_FILE = 512 * 1024 * 1024
_CHUNK = 1024 * 1024
_ALLOWED_FILES = {"owner.json", "contact.db", "contact.db-wal", "contact.db-shm"}


def _private_mkdir(path: Path, sid: str) -> None:
    # Apply the protected ACL at creation, before encrypted content is written.
    verified_path(path, missing=True)
    if os.name == "nt":
        import pywintypes
        import win32file
        import win32security
        descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f"O:{sid}D:P(A;OICI;FA;;;{sid})", win32security.SDDL_REVISION_1)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        win32file.CreateDirectory(str(path), attributes)
    else:
        path.mkdir(mode=0o700)


def _private_owner(path: Path, sid: str) -> bool:
    verified_path(path)
    if os.name != "nt":
        return path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077
    import win32security
    descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
                                                    win32security.OWNER_SECURITY_INFORMATION |
                                                    win32security.DACL_SECURITY_INFORMATION)
    if win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) != sid:
        return False
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None or acl.GetAceCount() != 1:
        return False
    ace = acl.GetAce(0)
    return (ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE and
            win32security.ConvertSidToStringSid(ace[2]) == sid and
            bool(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED))


def _file_state(path: Path):
    try:
        info = verified_path(path).stat()
        if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= _MAX_FILE:
            raise ContactError("DATABASE_INVALID")
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    except FileNotFoundError:
        return None
    except ContactError as error:
        if error.code == "DATABASE_INVALID" and not path.exists():
            return None
        raise


def _source_state(source: Path):
    db = _file_state(source)
    if db is None or db[2] < 16:
        raise ContactError("DATABASE_INVALID")
    return (db, _file_state(source.with_name(source.name + "-wal")))


def _copy_set(source: Path, target: Path, *, cancel, deadline, progress):
    before = _source_state(source)
    fingerprints = []
    total = sum(item[2] for item in before if item is not None)
    done = 0
    for suffix, expected in zip(("", "-wal"), before):
        check_budget(cancel, deadline)
        if expected is None:
            fingerprints.append(None)
            continue
        origin = source.with_name(source.name + suffix)
        try:
            origin = verified_path(origin)
        except ContactError as error:
            if suffix == "-wal" and error.code == "DATABASE_INVALID" and not origin.exists():
                raise ContactError("SNAPSHOT_UNSTABLE") from None
            raise
        destination = verified_path(target / ("contact.db" + suffix), missing=True)
        digest = hashlib.sha256()
        with origin.open("rb") as incoming, destination.open("xb") as outgoing:
            if os.name != "nt":
                os.chmod(destination, 0o600)
            opened = os.fstat(incoming.fileno())
            # CPython 3.12 Windows stat uses creation time for st_ctime while
            # fstat uses change time. Compare the portable identity fields here;
            # full source state and content hashes still gate both copies.
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != expected[:4]:
                raise ContactError("SNAPSHOT_UNSTABLE")
            remaining = expected[2]
            while remaining:
                check_budget(cancel, deadline)
                data = incoming.read(min(_CHUNK, remaining))
                if not data:
                    raise ContactError("SNAPSHOT_UNSTABLE")
                outgoing.write(data)
                digest.update(data)
                remaining -= len(data)
                done += len(data)
                progress("snapshot", done, total)
                check_budget(cancel, deadline)
            if incoming.read(1):
                raise ContactError("SNAPSHOT_UNSTABLE")
        fingerprints.append((expected[2], digest.digest()))
    after = _source_state(source)
    if before != after:
        raise ContactError("SNAPSHOT_UNSTABLE")
    return after, tuple(fingerprints)


def _remove_tree(path: Path, parent: Path) -> None:
    """Delete only an already identified job, never following a reparse tree."""
    root = verified_path(path)
    boundary = verified_path(parent)
    if root.parent != boundary or not _JOB_NAME.fullmatch(root.name):
        raise ContactError("ACCESS_DENIED")
    files, directories = [], []

    def inspect(directory: Path, depth=0):
        if depth > 1:
            raise ContactError("ACCESS_DENIED")
        verified_path(directory)
        directories.append(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                child = verified_path(Path(entry.path))
                if os.path.commonpath([str(root), str(child)]) != str(root):
                    raise ContactError("ACCESS_DENIED")
                if entry.is_dir(follow_symlinks=False):
                    if child.name not in {"first", "second"}:
                        raise ContactError("ACCESS_DENIED")
                    inspect(child, depth + 1)
                elif entry.is_file(follow_symlinks=False) and child.name in _ALLOWED_FILES:
                    files.append(child)
                else:
                    raise ContactError("ACCESS_DENIED")
                if len(files) > 16 or len(directories) > 3:
                    raise ContactError("ACCESS_DENIED")

    inspect(root)
    # Recheck each absolute path immediately before removal; do not use rmtree.
    for file in files:
        verified_path(file).unlink()
    for directory in reversed(directories):
        verified_path(directory).rmdir()


def cleanup_leftovers(parent: Path, *, cancel=None, deadline=None) -> int:
    """Only own, privately ACLed, definitely dead jobs are eligible for removal.

    Permission failures, missing metadata, PID reuse ambiguity, and reparse
    points all fail closed. Live jobs owned by concurrent readers are retained.
    """
    parent = verified_path(parent)
    owner = current_job_identity()["ownerSid"]
    cleaned = 0
    for path in parent.iterdir():
        if cancel is not None:
            check_budget(cancel, deadline)
        match = _JOB_NAME.fullmatch(path.name)
        if not match:
            continue
        try:
            path = verified_path(path)
            if not _private_owner(path, owner):
                continue
            marker = verified_path(path / "owner.json")
            if marker.stat().st_size > 2048:
                continue
            metadata = json.loads(marker.read_text(encoding="ascii"))
            if (metadata.get("schemaVersion") != 1 or metadata.get("kind") != "contact-snapshot"
                    or metadata.get("ownerSid") != owner or metadata.get("job") != match[1]
                    or type(metadata.get("pid")) is not int or metadata["pid"] <= 0
                    or type(metadata.get("startTime")) is not int or metadata["startTime"] <= 0):
                continue
            current = process_start_time(metadata["pid"])
            if current is not None and current == metadata["startTime"]:
                continue
            _remove_tree(path, parent)
            cleaned += 1
        except Exception:
            continue
    return cleaned


def validate_snapshot(db: Path) -> Path:
    """SQLCipher may open only this job's ACL-verified encrypted copy."""
    db = verified_path(db)
    root = db.parents[1]
    match = _JOB_NAME.fullmatch(root.name)
    if not match or db.parent.name != "second" or db.name != "contact.db":
        raise ContactError("ACCESS_DENIED")
    try:
        owner = current_job_identity()
        if not _private_owner(root, owner["ownerSid"]) or not _private_owner(db.parent, owner["ownerSid"]):
            raise ContactError("ACCESS_DENIED")
        marker = verified_path(root / "owner.json")
        if marker.stat().st_size > 2048:
            raise ContactError("ACCESS_DENIED")
        metadata = json.loads(marker.read_text(encoding="ascii"))
        if (metadata.get("schemaVersion") != 1 or metadata.get("kind") != "contact-snapshot"
                or metadata.get("job") != match[1]
                or any(metadata.get(field) != owner[field] for field in ("ownerSid", "pid", "startTime"))):
            raise ContactError("ACCESS_DENIED")
        return db
    except ContactError:
        raise
    except Exception:
        raise ContactError("ACCESS_DENIED") from None


@contextmanager
def capture_snapshot(source: Path, *, cancel, deadline, progress, parent: Path | None = None):
    check_budget(cancel, deadline)
    source = verified_path(source)
    parent = verified_path(parent if parent is not None else Path(tempfile.gettempdir()))
    cleanup_leftovers(parent, cancel=cancel, deadline=deadline)
    check_budget(cancel, deadline)
    job = current_job_identity()
    job.update(schemaVersion=1, kind="contact-snapshot", job=uuid.uuid4().hex)
    root = parent / (PREFIX + job["job"])
    created = False
    try:
        _private_mkdir(root, job["ownerSid"])
        created = True
        if not _private_owner(root, job["ownerSid"]):
            raise ContactError("ACCESS_DENIED")
        with (root / "owner.json").open("x", encoding="ascii") as marker:
            json.dump(job, marker, separators=(",", ":"))
        if os.name != "nt":
            os.chmod(root / "owner.json", 0o600)
        for attempt in range(3):
            check_budget(cancel, deadline)
            initial = _source_state(source)
            for name in ("first", "second"):
                target = root / name
                _private_mkdir(target, job["ownerSid"])
            try:
                first = _copy_set(source, root / "first", cancel=cancel, deadline=deadline, progress=progress)
                second = _copy_set(source, root / "second", cancel=cancel, deadline=deadline, progress=progress)
                stable = first == second and initial == _source_state(source) == first[0]
            except ContactError as error:
                if error.code != "SNAPSHOT_UNSTABLE":
                    raise
                stable = False
            except FileNotFoundError:
                stable = False
            check_budget(cancel, deadline)
            if stable:
                db = verified_path(root / "second" / "contact.db")
                yield db
                return
            for name in ("first", "second"):
                target = verified_path(root / name)
                for file in target.iterdir():
                    if file.name not in {"contact.db", "contact.db-wal"}:
                        raise ContactError("ACCESS_DENIED")
                    verified_path(file).unlink()
                verified_path(target).rmdir()
        raise ContactError("SNAPSHOT_UNSTABLE")
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except OSError:
        raise ContactError("DATABASE_INVALID") from None
    finally:
        if created:
            # If cleanup cannot prove safety, leave the identifiable encrypted job.
            try:
                _remove_tree(root, parent)
            except (ContactError, OSError):
                pass
