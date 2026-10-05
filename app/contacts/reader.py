"""Snapshot-only, exact-version local contact reader."""

from __future__ import annotations

import ctypes
import hashlib
import os
import threading
import time
from pathlib import Path
from .diagnostics import ReadDiagnostics
from typing import Callable

from .data import normalize_contact
from .native import (ContactError, Win32Probe, candidate_keys, check_budget,
                     matching_processes, verified_path, verify_process)
from .snapshot import capture_snapshot, validate_snapshot


_probe_factory = Win32Probe
_MAX_EXTRA = 65536
_MAX_PHONES = 64
_MAX_ROWS = 200000
_MAX_TEXT = 1024 * 1024
_MAX_OUTPUT = 64 * 1024 * 1024
_COLUMN_ALIASES = {
    "username": {"username"},
    "nick_name": {"nick_name", "nickname"},
    "remark": {"remark", "conremark"},
    "alias": {"alias"},
    "description": {"description"},
    "local_type": {"local_type", "localtype"},
    "verify_flag": {"verify_flag", "verifyflag"},
    "extra_buffer": {"extra_buffer", "extrabuffer", "extrabuf"},
}


def _documents_directory() -> Path:
    if os.name != "nt":
        return Path.home() / "Documents"
    # CSIDL_PERSONAL follows Documents redirection, without COM or UIA.
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    function = shell.SHGetFolderPathW
    function.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                         ctypes.c_uint32, ctypes.c_wchar_p]
    function.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    if function(None, 5, None, 0, buffer) != 0:
        raise ContactError("ACCESS_DENIED")
    return verified_path(buffer.value)


def _database_locations(directory: Path):
    return (directory / "db_storage" / "contact" / "contact.db",
            directory / "contact" / "contact.db", directory / "contact.db")


def _account_for_database(db: Path) -> dict:
    db = verified_path(db)
    if not db.is_file() or db.name.lower() != "contact.db":
        raise ContactError("DATABASE_INVALID")
    if db.parent.name.lower() == "contact" and db.parent.parent.name.lower() == "db_storage":
        directory = db.parents[2]
    elif db.parent.name.lower() == "contact":
        directory = db.parents[1]
    else:
        directory = db.parent
    directory = verified_path(directory)
    location = hashlib.sha256(os.path.normcase(str(directory)).encode("utf-8")).hexdigest()[:16]
    return {"accountId": directory.name + "-" + location, "label": directory.name,
            "contactDb": str(db), "directory": str(directory)}


def discover_accounts(directory: str = "") -> list[dict]:
    """Discover bounded, known local layouts, without any process access."""
    try:
        if directory:
            roots = [verified_path(directory)]
        else:
            roots = [_documents_directory() / "xwechat_files"]
            profile = os.environ.get("USERPROFILE", "")
            if profile:
                roots.append(verified_path(profile, missing=True) / "xwechat_files")
        found = {}
        for root in roots:
            if not root.exists():
                continue
            root = verified_path(root)
            if root.is_file():
                row = _account_for_database(root)
                found[os.path.normcase(row["contactDb"])] = row
                continue
            candidates = list(_database_locations(root))
            with os.scandir(root) as children:
                for index, child in enumerate(children):
                    if index >= 10000:
                        raise ContactError("DATABASE_INVALID")
                    if child.is_dir(follow_symlinks=False):
                        try:
                            child_path = verified_path(child.path)
                        except ContactError as error:
                            if error.code == "ACCESS_DENIED":
                                continue
                            raise
                        candidates.extend(_database_locations(child_path))
            for db in candidates:
                if db.is_file():
                    row = _account_for_database(db)
                    found[os.path.normcase(row["contactDb"])] = row
        return sorted(found.values(), key=lambda item: (item["accountId"].casefold(), item["contactDb"]))
    except ContactError:
        raise
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except Exception:
        raise ContactError("DATABASE_INVALID") from None


def _validate_account(account: dict) -> Path:
    if not isinstance(account, dict):
        raise ContactError("DATABASE_INVALID")
    if not all(isinstance(account.get(field), str) and account[field]
               for field in ("accountId", "contactDb", "directory")):
        raise ContactError("DATABASE_INVALID")
    discovered = _account_for_database(Path(account["contactDb"]))
    root = verified_path(account["directory"])
    if root != Path(discovered["directory"]) or account["accountId"] != discovered["accountId"]:
        raise ContactError("DATABASE_INVALID")
    return Path(discovered["contactDb"])


def _protobuf_bytes_fields(data: memoryview, wanted: int):
    """Validate a bounded local message and select repeated known fields."""
    position, fields = 0, 0
    selected = []

    def varint():
        nonlocal position
        result = 0
        for shift in range(0, 70, 7):
            if position >= len(data):
                raise ValueError
            byte = data[position]
            position += 1
            if shift == 63 and byte > 1:
                raise ValueError
            result |= (byte & 127) << shift
            if not byte & 128:
                return result
        raise ValueError

    while position < len(data):
        fields += 1
        if fields > 256:
            raise ValueError
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if not 0 < number < 2 ** 29:
            raise ValueError
        if number == wanted and wire != 2:
            raise ValueError
        if wire == 0:
            varint()
        elif wire in {1, 5}:
            position += 8 if wire == 1 else 4
        elif wire == 2:
            size = varint()
            end = position + size
            if end > len(data):
                raise ValueError
            if number == wanted:
                selected.append(data[position:end])
            position = end
        else:
            raise ValueError
        if position > len(data):
            raise ValueError
    return selected


def _decode_phone(extra_buffer) -> str:
    """Only 4.1.13.65's local extra_buffer path 14 -> 2 -> 1, never remarks."""
    if not isinstance(extra_buffer, (bytes, bytearray, memoryview)) or len(extra_buffer) > _MAX_EXTRA:
        return ""
    messages = [memoryview(extra_buffer)]
    try:
        for field in (14, 2, 1):
            messages = [selected for message in messages
                        for selected in _protobuf_bytes_fields(message, field)]
            if not messages or len(messages) > _MAX_PHONES:
                return ""
        phones, seen = [], set()
        for selected in messages:
            if len(selected) > 256:
                return ""
            phone = bytes(selected).decode("utf-8").strip()
            if any(ord(char) < 32 or ord(char) == 127 for char in phone):
                return ""
            if phone and phone not in seen:
                seen.add(phone)
                phones.append(phone)
        return ", ".join(phones)
    except (ValueError, IndexError, UnicodeDecodeError):
        return ""


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _read_rows(connection, *, cancel, deadline, progress) -> list[dict]:
    check_budget(cancel, deadline)
    try:
        tables = connection.execute("SELECT name, type, sql FROM sqlite_master WHERE lower(name) = 'contact'").fetchall()
        if len(tables) != 1 or tables[0][1] != "table" or not tables[0][2]:
            raise ContactError("SCHEMA_UNSUPPORTED")
        table = tables[0][0]
        if tables[0][2].lstrip().upper().startswith("CREATE VIRTUAL"):
            raise ContactError("SCHEMA_UNSUPPORTED")
        info = connection.execute("PRAGMA table_info(" + _quoted(table) + ")").fetchall()
        columns = {}
        for canonical, aliases in _COLUMN_ALIASES.items():
            matched = [row for row in info if row[1].casefold() in aliases]
            expected_type = "BLOB" if canonical == "extra_buffer" else (
                "INTEGER" if canonical in {"local_type", "verify_flag"} else "TEXT")
            if len(matched) != 1 or matched[0][2].upper() != expected_type:
                raise ContactError("SCHEMA_UNSUPPORTED")
            columns[canonical] = matched[0][1]
        names = list(columns)
        selections = [_quoted(columns[name]) for name in names]
        # Avoid allocating arbitrarily large, unrecognized local protobuf blobs.
        extra = _quoted(columns["extra_buffer"])
        selections[-1] = f"CASE WHEN typeof({extra}) = 'blob' AND length({extra}) <= {_MAX_EXTRA} THEN {extra} ELSE NULL END"
        deletion = [row for row in info if row[1].casefold() in {"delete_flag", "deleteflag", "del_flag", "delflag"}]
        if deletion:
            if len(deletion) != 1 or deletion[0][2].upper() != "INTEGER":
                raise ContactError("SCHEMA_UNSUPPORTED")
            names.append("delete_flag")
            selections.append(_quoted(deletion[0][1]))
        total = connection.execute("SELECT count(*) FROM " + _quoted(table)).fetchone()[0]
        if total > _MAX_ROWS:
            raise ContactError("DATABASE_INVALID")
        progress("contacts", 0, total)
        check_budget(cancel, deadline)
        cursor = connection.execute("SELECT " + ",".join(selections) + " FROM " + _quoted(table))
        result, output_size = [], 0
        while True:
            check_budget(cancel, deadline)
            batch = cursor.fetchmany(128)
            if not batch:
                break
            for values in batch:
                check_budget(cancel, deadline)
                row = dict(zip(names, values))
                for name in ("username", "nick_name", "remark", "alias", "description"):
                    value = row[name]
                    if value is not None and (not isinstance(value, str) or len(value) > _MAX_TEXT):
                        raise ContactError("DATABASE_INVALID")
                row["phone"] = _decode_phone(row.pop("extra_buffer"))
                contact = normalize_contact(row)
                output_size += sum(len(value.encode("utf-8")) for value in contact.values())
                if output_size > _MAX_OUTPUT or len(result) >= _MAX_ROWS:
                    raise ContactError("DATABASE_INVALID")
                result.append(contact)
            progress("contacts", len(result), total)
        check_budget(cancel, deadline)
        return result
    except ContactError:
        raise
    except Exception:
        check_budget(cancel, deadline)
        raise ContactError("DATABASE_INVALID") from None


def _engine():
    try:
        from sqlcipher3 import dbapi2
        return dbapi2
    except ImportError:
        raise ContactError("DATABASE_INVALID") from None


class _InvalidKey(Exception):
    pass


def _open_snapshot(db, key, salt, *, cancel, deadline):
    check_budget(cancel, deadline)
    connection = None
    try:
        # Never immutable=1: that can omit WAL transactions. The copy's own SHM
        # can be rebuilt, but the encrypted DB is always opened mode=ro.
        db = validate_snapshot(db)
        engine = _engine()
        connection = engine.connect(db.as_uri() + "?mode=ro", uri=True, timeout=0, cached_statements=0)
        connection.set_progress_handler(lambda: int(cancel.is_set() or time.monotonic() >= deadline), 1000)
        connection.execute("PRAGMA cipher_log_level = NONE")
        connection.execute('PRAGMA key = "x\'' + key.hex() + salt.hex() + '\'"')
        connection.execute("PRAGMA cipher_compatibility = 4")
        connection.execute("PRAGMA cipher_memory_security = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        version = connection.execute("PRAGMA cipher_version").fetchone()
        hmac = connection.execute("PRAGMA cipher_use_hmac").fetchone()
        if not version or tuple(int(part) for part in version[0].split(".")[:2]) < (4, 5) or not hmac or str(hmac[0]) != "1":
            raise ContactError("DATABASE_INVALID")
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except engine.DatabaseError as error:
            check_budget(cancel, deadline)
            # Only failed initial decryption rejects a key, not I/O or setup.
            if getattr(error, "sqlite_errorcode", 0) & 0xFF == engine.SQLITE_NOTADB:
                raise _InvalidKey() from None
            raise ContactError("DATABASE_INVALID") from None
        check_budget(cancel, deadline)
        try:
            integrity = connection.execute("PRAGMA cipher_integrity_check").fetchone()
            if integrity is not None and integrity != ("ok",):
                raise ContactError("DATABASE_INVALID")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ContactError("DATABASE_INVALID")
        except (ContactError, PermissionError):
            raise
        except Exception:
            check_budget(cancel, deadline)
            raise ContactError("DATABASE_INVALID") from None
        check_budget(cancel, deadline)
        return connection
    except (ContactError, _InvalidKey):
        if connection is not None:
            connection.close()
        raise
    except PermissionError:
        if connection is not None:
            connection.close()
        check_budget(cancel, deadline)
        raise ContactError("ACCESS_DENIED") from None
    except Exception:
        if connection is not None:
            connection.close()
        check_budget(cancel, deadline)
        raise ContactError("DATABASE_INVALID") from None


def read_contacts(account: dict, *, cancel: threading.Event, deadline: float,
                  progress: Callable[[str, int, int], None], diagnostics=None) -> list[dict]:
    """Read contacts under a monotonic budget; emit no partial results or keys."""
    check_budget(cancel, deadline)
    diagnostics = diagnostics if diagnostics is not None else ReadDiagnostics()
    notify = progress

    def progress(stage, done=0, total=0):
        diagnostics.stage = stage
        notify(stage, done, total)

    try:
        source = _validate_account(account)
        probe = _probe_factory()
        processes = matching_processes(probe, cancel=cancel, deadline=deadline)
        diagnostics.processCount = len(processes)
        progress("process", 0, len(processes))
        check_budget(cancel, deadline)
        result = None
        successful_process = None
        with capture_snapshot(source, cancel=cancel, deadline=deadline, progress=progress) as db:
            with db.open("rb") as encrypted:
                salt = encrypted.read(16)
            if len(salt) != 16 or salt == b"SQLite format 3\0":
                raise ContactError("DATABASE_INVALID")
            found_candidate = False
            for index, process in enumerate(processes):
                check_budget(cancel, deadline)
                verify_process(probe, process)
                diagnostics.processesChecked += 1
                progress("keys", index, len(processes))
                keys = candidate_keys(probe, process, salt, cancel=cancel, deadline=deadline,
                                      diagnostics=diagnostics)
                try:
                    for key in keys:
                        found_candidate = True
                        verify_process(probe, process)
                        progress("validating", index, len(processes))
                        try:
                            connection = _open_snapshot(db, key, salt, cancel=cancel, deadline=deadline)
                        except _InvalidKey:
                            progress("keys", index, len(processes))
                            continue
                        diagnostics.validatedCount += 1
                        try:
                            rows = _read_rows(connection, cancel=cancel, deadline=deadline, progress=progress)
                            verify_process(probe, process)
                            check_budget(cancel, deadline)
                            result, successful_process = rows, process
                            break
                        finally:
                            connection.close()
                finally:
                    keys.close()
                verify_process(probe, process)
                if result is not None:
                    break
            if result is None:
                raise ContactError("KEY_VALIDATION_FAILED" if found_candidate else "KEY_NOT_FOUND")
        check_budget(cancel, deadline)
        verify_process(probe, successful_process)
        progress("complete", len(result), len(result))
        check_budget(cancel, deadline)
        verify_process(probe, successful_process)
        return result
    except ContactError:
        raise
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except Exception:
        check_budget(cancel, deadline)
        raise ContactError("DATABASE_INVALID") from None
