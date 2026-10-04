"""Synthetic files/SQLCipher fixtures only; no live WeChat access."""

import importlib
import hashlib
import json
import os
import sqlite3
import struct
import threading
import time
from pathlib import Path

import pytest

from tests.test_contact_native import FakeProbe, identity


@pytest.fixture
def reader():
    try:
        return importlib.import_module("app.contacts.reader")
    except ModuleNotFoundError:
        pytest.fail("The isolated contact reader has not been implemented")


@pytest.fixture
def snapshot(reader):
    return importlib.import_module("app.contacts.snapshot")


def settings():
    return dict(cancel=threading.Event(), deadline=time.monotonic() + 15,
                progress=lambda stage, done, total: None)


def contact_db(directory, content=b"s" * 16 + b"e" * 4080):
    path = directory / "db_storage" / "contact" / "contact.db"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


def account(db):
    root = db.parents[2] if db.parent.name == "contact" else db.parent
    location = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:16]
    return dict(accountId=root.name + "-" + location, label=root.name,
                contactDb=str(db), directory=str(root))


def test_discover_supports_root_account_and_database_without_process_access(reader, tmp_path):
    root = tmp_path / "xwechat_files"
    db = contact_db(root / "wxid_example")
    expected = [account(db)]
    assert reader.discover_accounts(str(root)) == expected
    assert reader.discover_accounts(str(root / "wxid_example")) == expected
    assert reader.discover_accounts(str(db)) == expected


def test_discover_documents_profile_deduplicates_and_ignores_unrelated_db(reader, tmp_path, monkeypatch):
    profile, documents = tmp_path / "profile", tmp_path / "redirected_documents"
    db1 = contact_db(documents / "xwechat_files" / "wxid_a")
    db2 = contact_db(profile / "xwechat_files" / "wxid_b")
    contact_db(documents / "unrelated" / "wxid_c")
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(reader, "_documents_directory", lambda: documents)
    assert {row["contactDb"] for row in reader.discover_accounts()} == {str(db1), str(db2)}
    monkeypatch.setattr(reader, "_documents_directory", lambda: profile)
    assert reader.discover_accounts() == [account(db2)]


def test_discover_manual_missing_path_has_safe_error(reader, tmp_path):
    with pytest.raises(reader.ContactError) as error:
        reader.discover_accounts(str(tmp_path / "private-missing"))
    assert error.value.code == "DATABASE_INVALID"
    assert "private-missing" not in str(error.value)


def test_snapshot_copies_encrypted_db_and_wal_twice_never_modifies_source(snapshot, tmp_path, monkeypatch):
    source = contact_db(tmp_path / "source")
    wal = source.with_name(source.name + "-wal")
    wal.write_bytes(b"encrypted-wal" * 100)
    before = (source.read_bytes(), wal.read_bytes())
    copies = []
    original = snapshot._copy_set

    def record(*args, **kwargs):
        copies.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshot, "_copy_set", record)
    parent = tmp_path / "snapshots"
    parent.mkdir()
    with snapshot.capture_snapshot(source, parent=parent, **settings()) as db:
        assert db != source
        assert db.read_bytes() == before[0]
        assert db.with_name(db.name + "-wal").read_bytes() == before[1]
        root = db.parents[1]
        metadata = json.loads((root / "owner.json").read_text())
        assert metadata["job"] in root.name
        assert metadata["pid"] == os.getpid()
        assert metadata["ownerSid"]
        assert "key" not in json.dumps(metadata).lower()
    assert len(copies) == 2
    assert not list(parent.iterdir())
    assert (source.read_bytes(), wal.read_bytes()) == before


def test_snapshot_content_churn_stops_after_three_attempts(snapshot, reader, tmp_path, monkeypatch):
    source = contact_db(tmp_path / "source")
    parent = tmp_path / "snapshots"
    parent.mkdir()
    count = 0
    original = snapshot._copy_set

    def churn(*args, **kwargs):
        nonlocal count
        result = original(*args, **kwargs)
        count += 1
        # Same file size, fresh content: stat-only snapshots must not pass.
        source.write_bytes(b"s" * 16 + bytes([count]) * 4080)
        return result

    monkeypatch.setattr(snapshot, "_copy_set", churn)
    with pytest.raises(reader.ContactError) as error:
        with snapshot.capture_snapshot(source, parent=parent, **settings()):
            pytest.fail("A changing source must never be accepted")
    assert error.value.code == "SNAPSHOT_UNSTABLE"
    assert 3 <= count <= 6
    assert not list(parent.iterdir())


@pytest.mark.parametrize("every_attempt", [False, True], ids=["recovers", "three-attempt-limit"])
def test_snapshot_retries_wal_disappearance_after_captured_state(snapshot, reader, tmp_path, monkeypatch, every_attempt):
    source = contact_db(tmp_path / "source")
    original_db = source.read_bytes()
    wal = source.with_name(source.name + "-wal")
    wal.write_bytes(b"synthetic-encrypted-wal")
    parent = tmp_path / "snapshots"
    parent.mkdir()
    original_state = snapshot._source_state
    calls, vanished = 0, 0

    def disappearing_state(path):
        nonlocal calls, vanished
        calls += 1
        if every_attempt and not wal.exists():
            wal.write_bytes(b"synthetic-encrypted-wal")
        state = original_state(path)
        # First state is capture's initial check; the second precedes copying.
        if calls == 2 or (every_attempt and calls % 2 == 0):
            wal.unlink()
            vanished += 1
        return state

    monkeypatch.setattr(snapshot, "_source_state", disappearing_state)
    if every_attempt:
        with pytest.raises(reader.ContactError) as error:
            with snapshot.capture_snapshot(source, parent=parent, **settings()):
                pytest.fail("Repeated WAL disappearance must never yield a snapshot")
        assert error.value.code == "SNAPSHOT_UNSTABLE"
        assert vanished == 3
    else:
        with snapshot.capture_snapshot(source, parent=parent, **settings()) as copied:
            assert copied.read_bytes() == original_db
            assert not copied.with_name(copied.name + "-wal").exists()
        assert vanished == 1
    assert source.read_bytes() == original_db
    assert not list(parent.iterdir())


@pytest.mark.parametrize("kind,code", [("cancel", "CANCELLED"), ("timeout", "TIMEOUT")])
def test_public_read_budget_precedes_native_actions(reader, monkeypatch, kind, code):
    def forbidden():
        pytest.fail("No native actions are allowed once the budget has expired")

    monkeypatch.setattr(reader, "_probe_factory", forbidden)
    kwargs = settings()
    if kind == "cancel":
        kwargs["cancel"].set()
    else:
        kwargs["deadline"] = time.monotonic() - 1
    with pytest.raises(reader.ContactError) as error:
        reader.read_contacts({}, **kwargs)
    assert error.value.code == code


def schema_connection(table="contact", missing=None, casing=False):
    columns = ["username", "nick_name", "remark", "alias", "description",
               "local_type", "verify_flag", "extra_buffer"]
    if missing:
        columns.remove(missing)
    if casing:
        columns = [name.upper() for name in columns]
    conn = sqlite3.connect(":memory:")
    definitions = ",".join('"' + name + '" ' +
                            ("BLOB" if name.lower() == "extra_buffer" else
                             "INTEGER" if name.lower() in {"local_type", "verify_flag"} else "TEXT")
                            for name in columns)
    conn.execute('CREATE TABLE "' + table + '" (' + definitions + ')')
    return conn


@pytest.mark.parametrize("table,missing", [("contacts", None), ("random", None), ("contact", "verify_flag")])
def test_schema_drift_is_rejected_without_guessing(reader, table, missing):
    with schema_connection(table, missing) as conn:
        with pytest.raises(reader.ContactError) as error:
            reader._read_rows(conn, **settings())
    assert error.value.code == "SCHEMA_UNSUPPORTED"


def test_known_casing_normalizes_six_strings_and_retains_categories(reader):
    conn = schema_connection("Contact", casing=True)
    conn.executemany('INSERT INTO "Contact" VALUES (?,?,?,?,?,?,?,?)', [
        ("wxid_one", "Nick", "Call 13800138000", "", None, 1, 0, b""),
        ("room@chatroom", "Room", "", "", "", 2, 0, b""),
        ("gh_official", "Official", "", "", "", 1, 8, b""),
        ("filehelper", "System", "", "", "", 1, 0, b""),
        ("wxid_cache", "Cache", "", "", "", 0, 0, b""),
    ])
    rows = reader._read_rows(conn, **settings())
    assert {row["category"] for row in rows} == {"friend", "group", "official", "system", "cache"}
    assert rows[0]["phone"] == ""
    for row in rows:
        assert all(isinstance(row[name], str) for name in
                   ("nick_name", "remark", "phone", "username", "alias", "description"))
    conn.close()


@pytest.mark.parametrize("blob", [b"", b"\x00", b"\xff" * 20,
                                    b"\x0a\x0b13800138000", b"\x12\x0b13800138000",
                                    b"\x0a\xff\xff\xff\xff\x7f", b"x" * 65537],
                         ids=["empty", "zero-tag", "invalid-varint", "unknown-tag1", "unknown-tag2",
                              "truncated", "oversized"])
def test_phone_decoder_never_guesses_unknown_or_malformed_protobuf(reader, blob):
    assert reader._decode_phone(blob) == ""


def test_cancel_during_row_progress_returns_no_partial_result(reader):
    conn = schema_connection()
    conn.executemany("INSERT INTO contact VALUES (?,?,?,?,?,?,?,?)",
                     [("wxid_" + str(i), "N", "", "", "", 1, 0, b"") for i in range(20)])
    kwargs = settings()
    kwargs["progress"] = lambda *_: kwargs["cancel"].set()
    with pytest.raises(reader.ContactError) as error:
        reader._read_rows(conn, **kwargs)
    assert error.value.code == "CANCELLED"
    conn.close()


def sqlcipher_engine():
    return pytest.importorskip("sqlcipher3.dbapi2", reason="Parent installs sqlcipher3==0.6.3 later")


def encrypted_fixture(tmp_path, *, wal=False, drift=False):
    engine = sqlcipher_engine()
    db = contact_db(tmp_path / "wxid_synthetic", b"")
    key, salt = b"k" * 32, b"s" * 16
    conn = engine.connect(str(db))
    conn.execute('PRAGMA key = "x\'' + key.hex() + salt.hex() + '\'"')
    conn.execute("PRAGMA cipher_compatibility = 4")
    conn.execute("CREATE TABLE " + ("unknown" if drift else "contact") +
                 " (username TEXT, nick_name TEXT, remark TEXT, alias TEXT, description TEXT,"
                 " local_type INTEGER, verify_flag INTEGER, extra_buffer BLOB)")
    conn.commit()
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("INSERT INTO " + ("unknown" if drift else "contact") +
                 " VALUES ('wxid_fake', 'Synthetic', '', 'alias', 'local', 1, 0, X'')")
    conn.commit()
    return db, key, salt, conn


def corrupt_fixture_wal_payload(path, *, retain_checksums):
    """Mutate synthetic ciphertext; checksum rewriting is fixture-only."""
    content = bytearray(path.read_bytes())
    magic, version, page_size = struct.unpack_from(">III", content)
    assert magic in {0x377F0682, 0x377F0683} and version == 3007000
    frame_size = 24 + page_size
    assert 0 < (len(content) - 32) // frame_size <= 16
    assert (len(content) - 32) % frame_size == 0
    content[-page_size // 2] ^= 1
    if retain_checksums:
        byte_order = ">" if magic & 1 else "<"

        def checksum(data, state):
            first, second = state
            for left, right in struct.iter_unpack(byte_order + "II", data):
                first = (first + left + second) & 0xFFFFFFFF
                second = (second + right + first) & 0xFFFFFFFF
            return first, second

        state = checksum(content[:24], (0, 0))
        assert state == struct.unpack_from(">II", content, 24)
        for offset in range(32, len(content), frame_size):
            state = checksum(content[offset:offset + 8], state)
            state = checksum(content[offset + 24:offset + frame_size], state)
            struct.pack_into(">II", content, offset + 16, *state)
    path.write_bytes(content)


def inject_probe(reader, monkeypatch, key, salt):
    native = importlib.import_module("app.contacts.native")
    probe = FakeProbe([identity(native)], ("x'" + key.hex() + salt.hex() + "'").encode())
    monkeypatch.setattr(reader, "_probe_factory", lambda: probe)
    return probe


@pytest.mark.parametrize("wal", [False, True])
def test_synthetic_encrypted_database_and_wal_read_only(reader, tmp_path, monkeypatch, wal):
    db, key, salt, conn = encrypted_fixture(tmp_path, wal=wal)
    try:
        probe = inject_probe(reader, monkeypatch, key, salt)
        source_files = [db] + ([db.with_name(db.name + "-wal")] if wal else [])
        before = {path: path.read_bytes() for path in source_files}
        progress = []
        kwargs = settings()
        kwargs["progress"] = lambda *args: progress.append(args)
        rows = reader.read_contacts(account(db), **kwargs)
        assert rows[0]["username"] == "wxid_fake"
        assert rows[0]["nick_name"] == "Synthetic"
        assert rows[0]["category"] == "friend"
        assert before == {path: path.read_bytes() for path in source_files}
        assert progress and all(isinstance(s, str) and 0 <= d <= t for s, d, t in progress)
        assert any(event[0] == "read" for event in probe.events)
    finally:
        conn.close()


def test_synthetic_wrong_key_has_safe_database_invalid(reader, tmp_path, monkeypatch):
    db, key, salt, conn = encrypted_fixture(tmp_path)
    try:
        inject_probe(reader, monkeypatch, b"w" * 32, salt)
        with pytest.raises(reader.ContactError) as error:
            reader.read_contacts(account(db), **settings())
        assert error.value.code == "DATABASE_INVALID"
        assert key.hex() not in str(error.value)
        assert str(db) not in str(error.value)
    finally:
        conn.close()


@pytest.mark.parametrize("valid_key", [True, False])
def test_extended_memory_literal_is_normalized_and_validated_by_sqlcipher(reader, tmp_path, monkeypatch, valid_key):
    db, key, salt, conn = encrypted_fixture(tmp_path, wal=True)
    try:
        probe = inject_probe(reader, monkeypatch, key, salt)
        candidate = key if valid_key else b"w" * 32
        probe.memory = ("x'" + candidate.hex() + "ab" * 208 + salt.hex() + "'").encode()
        before = db.read_bytes(), db.with_name(db.name + "-wal").read_bytes()
        if valid_key:
            rows = reader.read_contacts(account(db), **settings())
            assert rows[0]["username"] == "wxid_fake"
            assert rows[0]["nick_name"] == "Synthetic"
        else:
            with pytest.raises(reader.ContactError) as error:
                reader.read_contacts(account(db), **settings())
            assert error.value.code == "DATABASE_INVALID"
        assert (db.read_bytes(), db.with_name(db.name + "-wal").read_bytes()) == before
    finally:
        conn.close()


def test_synthetic_encrypted_schema_drift_is_not_key_error(reader, tmp_path, monkeypatch):
    db, key, salt, conn = encrypted_fixture(tmp_path, drift=True)
    try:
        inject_probe(reader, monkeypatch, key, salt)
        with pytest.raises(reader.ContactError) as error:
            reader.read_contacts(account(db), **settings())
        assert error.value.code == "SCHEMA_UNSUPPORTED"
    finally:
        conn.close()


def test_snapshot_acl_is_current_user_only(snapshot, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows ACL verification")
    import win32security

    db = contact_db(tmp_path / "source")
    with snapshot.capture_snapshot(db, parent=tmp_path, **settings()) as copied:
        root = copied.parents[1]
        info = win32security.GetNamedSecurityInfo(str(root), win32security.SE_FILE_OBJECT,
                                                  win32security.OWNER_SECURITY_INFORMATION |
                                                  win32security.DACL_SECURITY_INFORMATION)
        owner = info.GetSecurityDescriptorOwner()
        acl = info.GetSecurityDescriptorDacl()
        assert acl is not None and acl.GetAceCount() == 1
        assert acl.GetAce(0)[2] == owner
        assert info.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED


def test_cleanup_ignores_unknown_and_live_jobs(snapshot, tmp_path):
    unknown = tmp_path / "wechat-contact-unknown"
    unknown.mkdir()
    (unknown / "keep").write_text("untouched")
    db = contact_db(tmp_path / "source")
    with snapshot.capture_snapshot(db, parent=tmp_path, **settings()) as copied:
        assert snapshot.cleanup_leftovers(tmp_path) == 0
        assert copied.is_file()
    assert (unknown / "keep").read_text() == "untouched"


def test_sqlcipher_refuses_any_non_snapshot_before_engine_access(reader, tmp_path, monkeypatch):
    source = contact_db(tmp_path / "source")

    def forbidden():
        pytest.fail("SQLCipher must never open the original contact database")

    monkeypatch.setattr(reader, "_engine", forbidden)
    with pytest.raises(reader.ContactError) as error:
        reader._open_snapshot(source, bytearray(b"k" * 32), b"s" * 16,
                              cancel=threading.Event(), deadline=time.monotonic() + 10)
    assert error.value.code == "ACCESS_DENIED"


def test_snapshot_sqlcipher_is_readonly_query_only_memory_temp(reader, snapshot, tmp_path):
    db, key, salt, fixture_connection = encrypted_fixture(tmp_path)
    try:
        with snapshot.capture_snapshot(db, parent=tmp_path, **settings()) as copied:
            conn = reader._open_snapshot(copied, bytearray(key), salt,
                                         cancel=threading.Event(), deadline=time.monotonic() + 10)
            try:
                assert conn.execute("PRAGMA query_only").fetchone() == (1,)
                assert conn.execute("PRAGMA temp_store").fetchone() == (2,)
                assert conn.execute("PRAGMA cipher_use_hmac").fetchone()[0] in (1, "1")
                with pytest.raises(sqlcipher_engine().DatabaseError):
                    conn.execute("DELETE FROM contact")
            finally:
                conn.close()
    finally:
        fixture_connection.close()


@pytest.mark.parametrize("wal", [False, True])
def test_encrypted_page_hmac_corruption_rejected(reader, tmp_path, monkeypatch, wal):
    db, key, salt, fixture_connection = encrypted_fixture(tmp_path, wal=wal)
    try:
        target = db.with_name(db.name + "-wal") if wal else db
        if wal:
            # Valid SQLite checksums make the engine read the damaged page,
            # so failure exercises SQLCipher HMAC rather than WAL-tail discard.
            corrupt_fixture_wal_payload(target, retain_checksums=True)
        else:
            content = bytearray(target.read_bytes())
            content[-2048] ^= 1
            target.write_bytes(content)
        engine = sqlcipher_engine()
        opened = []

        def record_engine():
            opened.append(True)
            return engine

        monkeypatch.setattr(reader, "_engine", record_engine)
        inject_probe(reader, monkeypatch, key, salt)
        with pytest.raises(reader.ContactError) as error:
            reader.read_contacts(account(db), **settings())
        assert error.value.code == "DATABASE_INVALID"
        assert opened, "Encrypted page faults must be rejected by SQLCipher itself"
    finally:
        fixture_connection.close()


@pytest.mark.parametrize("tail", ["invalid-checksum", "truncated-frame"])
def test_sqlcipher_owns_wal_tail_recovery(reader, tmp_path, monkeypatch, tail):
    db, key, salt, fixture_connection = encrypted_fixture(tmp_path, wal=True)
    try:
        fixture_connection.execute("INSERT INTO contact VALUES "
                                   "('wxid_later', 'Later', '', '', '', 1, 0, X'')")
        fixture_connection.commit()
        wal = db.with_name(db.name + "-wal")
        if tail == "invalid-checksum":
            corrupt_fixture_wal_payload(wal, retain_checksums=False)
        else:
            wal.write_bytes(wal.read_bytes()[:-32])
        before = db.read_bytes(), wal.read_bytes()
        inject_probe(reader, monkeypatch, key, salt)
        rows = reader.read_contacts(account(db), **settings())
        assert [row["username"] for row in rows] == ["wxid_fake"]
        assert (db.read_bytes(), wal.read_bytes()) == before
    finally:
        fixture_connection.close()


@pytest.mark.parametrize("kind,code", [("cancel", "CANCELLED"), ("timeout", "TIMEOUT")])
def test_snapshot_inflight_budget_discards_private_copies(snapshot, reader, tmp_path, kind, code):
    source = contact_db(tmp_path / "source")
    kwargs = settings()

    def stop(*_):
        if kind == "cancel":
            kwargs["cancel"].set()
        else:
            kwargs["deadline"] = time.monotonic() - 1

    # The deadline is a value, so use the shared monotonic clock for its expiry.
    if kind == "timeout":
        original = reader.time.monotonic
        from unittest.mock import patch
        with patch("app.contacts.native.time.monotonic", side_effect=lambda: original() + (100 if kwargs.get("expired") else 0)):
            kwargs["progress"] = lambda *_: kwargs.update(expired=True)
            with pytest.raises(reader.ContactError) as error:
                with snapshot.capture_snapshot(source, parent=tmp_path,
                                               cancel=kwargs["cancel"], deadline=kwargs["deadline"],
                                               progress=kwargs["progress"]):
                    pytest.fail("Expired snapshots must not be published")
    else:
        kwargs["progress"] = stop
        with pytest.raises(reader.ContactError) as error:
            with snapshot.capture_snapshot(source, parent=tmp_path, **kwargs):
                pytest.fail("Cancelled snapshots must not be published")
    assert error.value.code == code
    assert not list(tmp_path.glob("wechat-contact-*"))


def test_cleanup_deletes_only_verified_own_dead_job(snapshot, tmp_path, monkeypatch):
    from app.contacts.native import current_job_identity

    owner = current_job_identity()
    job = "a" * 32
    root = tmp_path / ("wechat-contact-" + job)
    snapshot._private_mkdir(root, owner["ownerSid"])
    marker = dict(owner, kind="contact-snapshot", schemaVersion=1, job=job,
                  pid=2147483000, startTime=123)
    (root / "owner.json").write_text(json.dumps(marker))
    (root / "contact.db").write_bytes(b"encrypted")
    monkeypatch.setattr(snapshot, "process_start_time", lambda _: None)
    assert snapshot.cleanup_leftovers(tmp_path) == 1
    assert not root.exists()


def test_cleanup_never_follows_reparse_tree(snapshot, tmp_path, monkeypatch):
    from app.contacts.native import current_job_identity

    owner = current_job_identity()
    job = "b" * 32
    root = tmp_path / ("wechat-contact-" + job)
    snapshot._private_mkdir(root, owner["ownerSid"])
    marker = dict(owner, kind="contact-snapshot", schemaVersion=1, job=job,
                  pid=2147483000, startTime=123)
    (root / "owner.json").write_text(json.dumps(marker))
    external = tmp_path / "outside"
    external.mkdir()
    (external / "contact.db").write_bytes(b"keep")
    link = root / "first"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Creating a directory link is unavailable")
        import _winapi
        _winapi.CreateJunction(str(external), str(link))
    monkeypatch.setattr(snapshot, "process_start_time", lambda _: None)
    assert snapshot.cleanup_leftovers(tmp_path) == 0
    assert root.exists()
    assert (external / "contact.db").read_bytes() == b"keep"


def test_native_dependency_errors_do_not_escape_public_reader(reader, tmp_path, monkeypatch):
    source = contact_db(tmp_path / "source")

    def failing():
        raise RuntimeError("PRIVATE PATH, KEY, OR SQL")

    monkeypatch.setattr(reader, "_probe_factory", failing)
    with pytest.raises(reader.ContactError) as error:
        reader.read_contacts(account(source), **settings())
    assert error.value.code == "DATABASE_INVALID"
    assert "PRIVATE" not in str(error.value)


def test_process_identity_change_during_sql_discards_rows(reader, tmp_path, monkeypatch):
    db, key, salt, conn = encrypted_fixture(tmp_path)
    try:
        probe = inject_probe(reader, monkeypatch, key, salt)
        kwargs = settings()

        def change(stage, done, total):
            if stage == "contacts":
                native = importlib.import_module("app.contacts.native")
                probe.identities[71] = identity(native, start_time=999)

        kwargs["progress"] = change
        with pytest.raises(reader.ContactError) as error:
            reader.read_contacts(account(db), **kwargs)
        assert error.value.code == "PROCESS_CHANGED"
    finally:
        conn.close()


def test_phone_decodes_only_verified_local_nested_path(reader):
    # field 14 (0x72) -> field 2 (0x12) -> field 1 (0x0a).
    known = b"\x72\x0f\x12\x0d\x0a\x0b13800138000"
    assert reader._decode_phone(known) == "13800138000"
    assert reader._decode_phone(b"\x08\x01" + known + b"\x1a\x03xyz") == "13800138000"
    assert reader._decode_phone(known[:-1]) == ""
    assert reader._decode_phone(known + b"\x00") == ""
    assert reader._decode_phone(known + known) == "13800138000"
    assert reader._decode_phone(b"\x72\x0f\x1a\x0d\x0a\x0b13800138000") == ""
    assert reader._decode_phone(b"\x72\x0f\x12\x0d\x12\x0b13800138000") == ""
    assert reader._decode_phone(b"\x72\x05\x12\x03\x0a\x01\xff") == ""


@pytest.mark.parametrize("level", [1, 2, 14])
def test_repeated_known_phone_fields_are_joined_in_wire_order_without_duplicates(reader, level):
    first, second = b"\x0a\x0b13800138000", b"\x0a\x0b13900139000"
    if level == 1:
        blob = b"\x72\x29\x12\x27" + second + first + second
    elif level == 2:
        blob = b"\x72\x2d" + b"\x12\x0d" + second + b"\x12\x0d" + first + b"\x12\x0d" + second
    else:
        blob = b"\x72\x0f\x12\x0d" + second + b"\x72\x0f\x12\x0d" + first + b"\x72\x0f\x12\x0d" + second
    assert reader._decode_phone(blob) == "13900139000, 13800138000"
    assert reader._decode_phone(blob) == "13900139000, 13800138000"
    assert reader._decode_phone(blob + b"\x72\x01\xff") == ""


def test_repeated_phone_output_and_field_work_are_bounded(reader):
    phone = b"\x72\x0f\x12\x0d\x0a\x0b13800138000"
    assert reader._decode_phone(phone * 65) == ""
    assert reader._decode_phone(phone * 257) == ""


def test_known_camelcase_extra_buf_and_del_flag_aliases(reader):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Contact(UserName TEXT, nickName TEXT, Remark TEXT, Alias TEXT, "
                 "Description TEXT, LocalType INTEGER, VerifyFlag INTEGER, ExtraBuf BLOB, del_flag INTEGER)")
    known = b"\x72\x0f\x12\x0d\x0a\x0b13800138000"
    conn.execute("INSERT INTO Contact VALUES ('wxid_one', 'Nick', '', '', '', 1, 0, ?, 1)", (known,))
    rows = reader._read_rows(conn, **settings())
    assert rows[0]["phone"] == "13800138000"
    assert rows[0]["nick_name"] == "Nick"
    assert rows[0]["category"] == "other"
    conn.close()


@pytest.mark.parametrize("alias", ["ConRemark", "DelFlag"])
def test_verified_reference_remark_and_deletion_aliases(reader, alias):
    conn = schema_connection()
    try:
        if alias == "ConRemark":
            conn.execute("ALTER TABLE contact RENAME COLUMN remark TO ConRemark")
        else:
            conn.execute("ALTER TABLE contact ADD COLUMN DelFlag INTEGER")
        conn.execute("INSERT INTO contact(username,nick_name," +
                     ("ConRemark" if alias == "ConRemark" else "remark") +
                     ",alias,description,local_type,verify_flag,extra_buffer) "
                     "VALUES ('wxid_reference','Nick','Reference remark','','',1,0,X'')")
        if alias == "DelFlag":
            conn.execute("UPDATE contact SET DelFlag=1")
        rows = reader._read_rows(conn, **settings())
        assert rows[0]["remark"] == "Reference remark"
        assert rows[0]["category"] == ("other" if alias == "DelFlag" else "friend")
    finally:
        conn.close()


@pytest.mark.parametrize("collision", ["remark", "deletion"])
def test_reference_alias_collisions_fail_closed(reader, collision):
    conn = schema_connection()
    try:
        if collision == "remark":
            conn.execute("ALTER TABLE contact ADD COLUMN ConRemark TEXT")
        else:
            conn.execute("ALTER TABLE contact ADD COLUMN del_flag INTEGER")
            conn.execute("ALTER TABLE contact ADD COLUMN DelFlag INTEGER")
        with pytest.raises(reader.ContactError) as error:
            reader._read_rows(conn, **settings())
        assert error.value.code == "SCHEMA_UNSUPPORTED"
    finally:
        conn.close()


def test_account_ids_distinguish_same_folder_in_two_roots(reader, tmp_path):
    db1 = contact_db(tmp_path / "first" / "wxid_same")
    db2 = contact_db(tmp_path / "second" / "wxid_same")
    first = reader.discover_accounts(str(db1))[0]
    second = reader.discover_accounts(str(db2))[0]
    assert first["accountId"] != second["accountId"]
    assert first["label"] == second["label"] == "wxid_same"
    assert reader.discover_accounts(str(db1.parent.parent.parent))[0]["accountId"] == first["accountId"]


def test_snapshot_automatically_cleans_dead_own_jobs(snapshot, tmp_path, monkeypatch):
    from app.contacts.native import current_job_identity

    owner = current_job_identity()
    job = "c" * 32
    abandoned = tmp_path / ("wechat-contact-" + job)
    snapshot._private_mkdir(abandoned, owner["ownerSid"])
    marker = dict(owner, kind="contact-snapshot", schemaVersion=1, job=job,
                  pid=2147483000, startTime=123)
    (abandoned / "owner.json").write_text(json.dumps(marker))
    source = contact_db(tmp_path / "source")
    monkeypatch.setattr(snapshot, "process_start_time", lambda pid: None if pid == 2147483000 else owner["startTime"])
    with snapshot.capture_snapshot(source, parent=tmp_path, **settings()) as db:
        assert db.is_file()
        assert not abandoned.exists()


def test_public_read_rechecks_deadline_after_snapshot_cleanup(reader, snapshot, tmp_path, monkeypatch):
    db, key, salt, fixture = encrypted_fixture(tmp_path)
    try:
        inject_probe(reader, monkeypatch, key, salt)
        original_clock = time.monotonic
        original_remove = snapshot._remove_tree
        expired = False

        def remove(*args):
            nonlocal expired
            original_remove(*args)
            expired = True

        monkeypatch.setattr(snapshot.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(snapshot, "_remove_tree", remove)
        monkeypatch.setattr(reader.time, "monotonic", lambda: original_clock() + (100 if expired else 0))
        with pytest.raises(reader.ContactError) as error:
            reader.read_contacts(account(db), **settings())
        assert error.value.code == "TIMEOUT"
        assert not list(tmp_path.glob("wechat-contact-*"))
    finally:
        fixture.close()
