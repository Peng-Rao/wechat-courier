"""Read-only native policy tests. No test opens a real WeChat process."""

import importlib
import threading
import time
from dataclasses import replace

import pytest


def test_native_module_is_available():
    assert importlib.util.find_spec("app.contacts.native") is not None, "Read-only native core is missing"


@pytest.fixture
def native():
    try:
        return importlib.import_module("app.contacts.native")
    except ModuleNotFoundError:
        pytest.fail("The isolated contact native reader has not been implemented")


def identity(native, **changes):
    values = dict(pid=71, start_time=12345, session_id=3, sid="S-1-5-21-1",
                  path=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
                  version="4.1.13.65")
    values.update(changes)
    return native.ProcessIdentity(**values)


class FakeProbe:
    def __init__(self, identities, memory=b"", *, sid="S-1-5-21-1", session=3):
        self.identities = {item.pid: item for item in identities}
        self.memory = memory
        self.sid, self.session = sid, session
        self.events = []
        self.change_after_read = None
        self.denied = set()
        self.short_reads = False

    def current_identity(self):
        return self.sid, self.session

    def process_ids(self):
        return list(self.identities)

    def inspect(self, pid, handle=None):
        self.events.append(("inspect", pid, handle))
        if pid in self.denied:
            raise PermissionError("SECRET OS DETAIL")
        return self.identities[pid]

    def open_memory(self, pid):
        self.events.append(("open", pid))
        return pid

    def close_memory(self, handle):
        self.events.append(("close", handle))

    def memory_regions(self, handle):
        yield 4096, len(self.memory)

    def read_memory(self, handle, address, size):
        self.events.append(("read", address, size))
        offset = address - 4096
        result = self.memory[offset:offset + (min(size, 7) if self.short_reads else size)]
        if self.change_after_read:
            self.identities[handle] = self.change_after_read
        return result


def budget():
    return dict(cancel=threading.Event(), deadline=time.monotonic() + 15)


def test_matching_processes_uses_sid_session_path_and_exact_version(native):
    good = identity(native)
    probe = FakeProbe([
        good,
        identity(native, pid=72, sid="S-1-5-21-2"),
        identity(native, pid=73, session_id=4),
        identity(native, pid=74, path=r"C:\not-weixin.exe"),
        identity(native, pid=75, version="4.1.13.66"),
        identity(native, pid=76),
    ])
    result = native.matching_processes(probe, **budget())
    assert [item.pid for item in result] == [71, 76]
    assert not any(event[0] == "open" for event in probe.events)


@pytest.mark.parametrize("change", [
    {"pid": 99}, {"start_time": 12346}, {"sid": "S-1-5-21-2"},
    {"session_id": 4}, {"path": r"C:\elsewhere\Weixin.exe"},
    {"version": "4.1.13.66"},
])
def test_identity_change_prevents_scan(native, change):
    initial = identity(native)
    probe = FakeProbe([initial])
    probe.identities[71] = replace(initial, **change)
    with pytest.raises(native.ContactError) as error:
        list(native.candidate_keys(probe, initial, b"s" * 16, **budget()))
    assert error.value.code == "PROCESS_CHANGED"
    assert not any(event[0] == "read" for event in probe.events)


@pytest.mark.parametrize("encoding", ["ascii", "utf-16-le"])
def test_salt_bound_hex_keys_cross_chunks_without_unbounded_reads(native, encoding):
    salt = bytes(range(16))
    key = bytes(range(32))
    token = ("x'" + key.hex() + salt.hex() + "'").encode(encoding)
    wrong = ("x'" + (b"q" * 32).hex() + (b"z" * 16).hex() + "'").encode(encoding)
    probe = FakeProbe([identity(native)], b"a" * 31 + token + wrong + token)
    result = [bytes(value) for value in native.candidate_keys(
        probe, identity(native), salt, chunk_size=64, **budget())]
    assert result == [key]
    assert max(event[2] for event in probe.events if event[0] == "read") <= 64
    assert probe.events[-1] == ("close", 71)
    assert sum(event[0] == "inspect" for event in probe.events) >= 3


def test_short_reads_do_not_skip_candidate_bytes(native):
    salt, key = b"s" * 16, b"k" * 32
    probe = FakeProbe([identity(native)], ("x'" + key.hex() + salt.hex() + "'").encode())
    probe.short_reads = True
    assert [bytes(value) for value in native.candidate_keys(
        probe, identity(native), salt, chunk_size=64, **budget())] == [key]


@pytest.mark.parametrize("encoding", ["ascii", "utf-16-le"])
@pytest.mark.parametrize("hex_length,chunk_size", [(128, 64), (192, 257), (512, 1), (512, 64)])
def test_extended_quoted_keys_match_late_salt_across_bounded_chunks(native, encoding, hex_length, chunk_size):
    salt, key = b"s" * 16, b"k" * 32
    literal = "X'" + key.hex() + "ab" * ((hex_length - 96) // 2) + salt.hex().upper() + "'"
    probe = FakeProbe([identity(native)], b"padding" + literal.encode(encoding))
    keys = [bytes(value) for value in native.candidate_keys(
        probe, identity(native), salt, chunk_size=chunk_size, **budget())]
    assert keys == [key]
    assert max(event[2] for event in probe.events if event[0] == "read") <= chunk_size
    assert probe.events[-1] == ("close", 71)


@pytest.mark.parametrize("encoding", ["ascii", "utf-16-le"])
@pytest.mark.parametrize("kind", ["unquoted", "odd", "nonhex", "oversized", "unaligned-salt", "salt-in-key"])
def test_malformed_or_unassociated_quoted_keys_are_not_candidates(native, encoding, kind):
    salt, key = b"s" * 16, b"k" * 32
    payload = key.hex() + salt.hex()
    if kind == "odd":
        payload += "a"
    elif kind == "nonhex":
        payload = key.hex() + "zz" + salt.hex()
    elif kind == "oversized":
        payload = key.hex() + "ab" * 209 + salt.hex()
    elif kind == "unaligned-salt":
        payload = key.hex() + "a" + salt.hex() + "b"
    elif kind == "salt-in-key":
        payload = salt.hex() * 2 + "ab" * 16
    literal = payload if kind == "unquoted" else "x'" + payload + "'"
    probe = FakeProbe([identity(native)], literal.encode(encoding))
    assert list(native.candidate_keys(probe, identity(native), salt, chunk_size=64, **budget())) == []


def test_identity_changed_after_memory_read_never_releases_key(native):
    salt, key = b"s" * 16, b"k" * 32
    probe = FakeProbe([identity(native)], ("x'" + key.hex() + salt.hex() + "'").encode())
    probe.change_after_read = identity(native, start_time=99999)
    with pytest.raises(native.ContactError) as error:
        list(native.candidate_keys(probe, identity(native), salt, **budget()))
    assert error.value.code == "PROCESS_CHANGED"
    assert probe.events[-1] == ("close", 71)


def test_query_access_denied_is_safe_and_does_not_request_memory(native):
    probe = FakeProbe([identity(native)])
    probe.denied.add(71)
    with pytest.raises(native.ContactError) as error:
        native.matching_processes(probe, **budget())
    assert error.value.code == "ACCESS_DENIED"
    assert "SECRET" not in str(error.value)
    assert not any(event[0] == "open" for event in probe.events)


@pytest.mark.parametrize("kind,code", [("cancel", "CANCELLED"), ("timeout", "TIMEOUT")])
def test_scan_budget_checked_before_process_access(native, kind, code):
    settings = budget()
    if kind == "cancel":
        settings["cancel"].set()
    else:
        settings["deadline"] = time.monotonic() - 1
    probe = FakeProbe([identity(native)])
    with pytest.raises(native.ContactError) as error:
        list(native.candidate_keys(probe, identity(native), b"s" * 16, **settings))
    assert error.value.code == code
    assert probe.events == []


def test_no_matching_logged_in_process_is_login_required(native):
    with pytest.raises(native.ContactError) as error:
        native.matching_processes(FakeProbe([]), **budget())
    assert error.value.code == "LOGIN_REQUIRED"


def test_only_current_user_unsupported_build_reports_unsupported(native):
    with pytest.raises(native.ContactError) as error:
        native.matching_processes(FakeProbe([identity(native, version="4.1.13.66")]), **budget())
    assert error.value.code == "UNSUPPORTED_VERSION"


def test_win32_adapter_opens_only_query_or_query_read_handles(native):
    class Kernel:
        def __init__(self):
            self.calls = []

        def OpenProcess(self, rights, inherit, pid):
            self.calls.append((rights, inherit, pid))
            return 123

    kernel = Kernel()
    probe = native.Win32Probe(kernel=kernel)
    assert probe._open_process(71, memory=False) == 123
    assert probe.open_memory(71) == 123
    assert kernel.calls == [(0x1000, False, 71), (0x0410, False, 71)]


def test_scanning_large_region_bounds_full_identity_inspections(native):
    salt, key = b"s" * 16, b"k" * 32
    token = ("x'" + key.hex() + salt.hex() + "'").encode()
    probe = FakeProbe([identity(native)], b"a" * (1024 * 1024) + token)

    def inspect_handle(pid, handle):
        probe.events.append(("inspect-handle", pid, handle))
        return probe.identities[pid]

    probe.inspect_handle = inspect_handle
    assert [bytes(value) for value in native.candidate_keys(
        probe, identity(native), salt, chunk_size=4096, **budget())] == [key]
    assert sum(event[0] == "read" for event in probe.events) > 250
    assert sum(event[0] == "inspect" for event in probe.events) <= 4
    assert any(event[0] == "inspect-handle" for event in probe.events)


def test_windows_token_access_denied_maps_to_permission_error(native, monkeypatch):
    import pywintypes
    import win32security

    def denied(*_):
        raise pywintypes.error(5, "OpenProcessToken", "PRIVATE OS DETAIL")

    monkeypatch.setattr(win32security, "OpenProcessToken", denied)
    with pytest.raises(PermissionError) as error:
        native._token_sid(123)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("code,error_type", [
    (5, PermissionError), (6, ProcessLookupError), (87, ProcessLookupError),
    (1168, ProcessLookupError), (123, OSError),
])
def test_windows_token_errors_are_classified_without_raw_details(native, monkeypatch, code, error_type):
    import pywintypes
    import win32security

    def failing(*_):
        raise pywintypes.error(code, "OpenProcessToken", "PRIVATE OS DETAIL")

    monkeypatch.setattr(win32security, "OpenProcessToken", failing)
    with pytest.raises(error_type) as error:
        native._token_sid(123)
    assert type(error.value) is error_type
    assert "PRIVATE" not in str(error.value)
    assert "OpenProcessToken" not in str(error.value)


def test_token_access_denied_is_public_access_denied(native, monkeypatch):
    import pywintypes
    import win32security

    def denied(*_):
        raise pywintypes.error(5, "OpenProcessToken", "PRIVATE OS DETAIL")

    monkeypatch.setattr(win32security, "OpenProcessToken", denied)
    probe = FakeProbe([identity(native)])
    probe.inspect = lambda *_: native._token_sid(123)
    with pytest.raises(native.ContactError) as error:
        native.matching_processes(probe, **budget())
    assert error.value.code == "ACCESS_DENIED"
    assert "PRIVATE" not in str(error.value)
