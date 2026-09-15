from __future__ import annotations

from types import SimpleNamespace

import pytest
import src.core.win32 as win32_module
import app.agent.gate as gate_module

from app.agent.gate import (
    AccessibilitySafetyError,
    IMAGE_SCN_MEM_WRITE,
    NativeGateBackend,
    ProcessModule,
    WeixinAccessibilitySession,
)
from app.agent.journal import GateLeaseJournal
from app.agent.profile import UnsupportedWeixinVersion


def test_agent_discovery_keeps_foreign_session_peers_for_shared_lease_safety(monkeypatch):
    import ctypes

    processes = iter([(101, "wechat-agent.exe"), (202, "wechat-agent.exe"),
                      (303, "wechat-agent.exe"), (404, "Weixin.exe")])

    def next_process(_snapshot, entry):
        try:
            pid, name = next(processes)
        except StopIteration:
            return False
        entry._obj.th32ProcessID = pid
        entry._obj.szExeFile = name
        return True

    kernel = SimpleNamespace(CreateToolhelp32Snapshot=lambda *_: 123,
                             Process32FirstW=next_process, Process32NextW=next_process,
                             CloseHandle=lambda *_: True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel))
    monkeypatch.setattr(gate_module.os, "getpid", lambda: 101)
    backend = NativeGateBackend()
    monkeypatch.setattr(backend, "_require_windows", lambda: None)
    monkeypatch.setattr(backend, "process_session_id", lambda pid: {101: 1, 202: 1, 303: 2}[pid], raising=False)
    assert backend.other_agent_pids() == (202, 303)


def test_locked_agent_ignores_only_same_image_mutex_waiters(monkeypatch, tmp_path):
    import sys
    candidate = tmp_path / "wechat-agent.exe"
    legacy = tmp_path / "old-agent.exe"
    candidate.write_bytes(b"candidate")
    legacy.write_bytes(b"legacy")
    backend = NativeGateBackend()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(candidate))
    monkeypatch.setattr(backend, "other_agent_pids", lambda: (202, 303))
    monkeypatch.setattr(backend, "process_path", lambda pid: str({202: candidate, 303: legacy}[pid]))
    monkeypatch.setattr(backend, "process_session_id", lambda _: 1)
    assert backend.legacy_agent_pids() == (303,)


def test_reused_session_reasserts_drifted_gate_before_broadcast_and_keeps_original_lease(tmp_path):
    backend = FakeGateBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    session = WeixinAccessibilitySession(backend, lease_journal=journal)
    session.__enter__()
    original_lease = journal.load()
    backend.memory[session.gate_address] = 0  # Observed after repeated tray cycles.
    order = []
    write = backend.write_byte
    broadcast = backend.broadcast_screen_reader_enabled
    backend.write_byte = lambda handle, address, value: order.append("write") or write(handle, address, value)
    backend.broadcast_screen_reader_enabled = lambda: order.append(("broadcast", backend.memory[session.gate_address])) or broadcast()
    try:
        session.refresh()
        assert order == ["write", ("broadcast", 1)]
        assert journal.load() == original_lease
    finally:
        session.close()
    assert backend.memory[backend.module.base + 0x0AE2B0C8] == 0
    assert backend.screen_reader is False


def test_refresh_broadcast_failure_rolls_back_original_state_and_clears_lease(tmp_path):
    backend = FakeGateBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    session = WeixinAccessibilitySession(backend, lease_journal=journal)
    session.__enter__()
    backend.memory[session.gate_address] = 0
    backend.broadcast_screen_reader_enabled = lambda: False
    with pytest.raises(AccessibilitySafetyError, match="broadcast"):
        session.refresh()
    assert backend.memory[session.gate_address] == 0
    assert backend.screen_reader is False
    assert journal.load() is None
    assert backend.closed


def test_refresh_and_cleanup_refuse_to_overwrite_unexpected_live_gate(tmp_path):
    backend = FakeGateBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    session = WeixinAccessibilitySession(backend, lease_journal=journal)
    session.__enter__()
    backend.memory[session.gate_address] = 7
    writes_before = list(backend.writes)
    with pytest.raises(AccessibilitySafetyError, match="unexpected gate"):
        session.refresh()
    with pytest.raises(AccessibilitySafetyError, match="unexpected gate"):
        session.close()
    assert backend.writes == writes_before
    assert journal.load() is not None
    assert backend.screen_reader is True
    # Test double only: restore a recognized byte so fixture cleanup can finish.
    backend.memory[session.gate_address] = 1
    session.close()


def test_refresh_and_cleanup_refuse_changed_module_identity(tmp_path):
    backend = FakeGateBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    session = WeixinAccessibilitySession(backend, lease_journal=journal)
    session.__enter__()
    original_module = backend.module
    backend.module = ProcessModule(original_module.base + 4096, original_module.size, original_module.path)
    writes_before = list(backend.writes)
    with pytest.raises(AccessibilitySafetyError, match="module identity"):
        session.refresh()
    with pytest.raises(AccessibilitySafetyError, match="module identity"):
        session.close()
    assert backend.writes == writes_before
    assert journal.load() is not None
    assert backend.screen_reader is True
    backend.module = original_module
    session.close()


class FakeGateBackend:
    def __init__(self):
        self.hwnd = 101
        self.pid = 202
        self.module = ProcessModule(0x10000000, 0x0B000000, "Weixin.dll")
        self.version = "4.1.13.65"
        self.section = (".data", IMAGE_SCN_MEM_WRITE)
        self.memory = {self.module.base + 0x0AE2B0C8: 0}
        self.screen_reader = False
        self.opened = False
        self.closed = False
        self.writes = []
        self.broadcasts = []

    def find_main_window(self):
        return self.hwnd

    def get_window_pid(self, hwnd):
        assert hwnd == self.hwnd
        return self.pid

    def find_module(self, pid, name):
        assert (pid, name) == (self.pid, "Weixin.dll")
        return self.module

    def file_version(self, path):
        return self.version

    def pe_section_for_rva(self, path, rva):
        return self.section

    def open_process(self, pid):
        self.opened = True
        return "handle"

    def close_process(self, handle):
        assert handle == "handle"
        self.closed = True

    def read_byte(self, handle, address):
        return self.memory.get(address)

    def write_byte(self, handle, address, value):
        self.writes.append((address, value))
        self.memory[address] = value
        return True

    def get_screen_reader(self):
        return self.screen_reader

    def set_screen_reader(self, enabled):
        self.screen_reader = enabled
        return True

    def broadcast_screen_reader_enabled(self):
        self.broadcasts.append(True)
        return self.set_screen_reader(True)


def test_invalid_dos_and_pe_headers_are_typed_as_gate_safety_failures(tmp_path):
    invalid_dos = tmp_path / "invalid-dos.dll"
    invalid_dos.write_bytes(b"not a PE image")
    invalid_pe = tmp_path / "invalid-pe.dll"
    image = bytearray(88)
    image[:2] = b"MZ"
    image[0x3C:0x40] = (64).to_bytes(4, "little")
    invalid_pe.write_bytes(image)

    for path, message in (
        (invalid_dos, "invalid DOS header"),
        (invalid_pe, "invalid PE header"),
    ):
        with pytest.raises(AccessibilitySafetyError, match=message):
            NativeGateBackend.pe_section_for_rva(str(path), 0)


def test_accessibility_session_verifies_enables_and_restores_gate():
    backend = FakeGateBackend()

    with WeixinAccessibilitySession(backend) as session:
        assert session.version == "4.1.13.65"
        assert session.profile.chat_input_automation_id == "chat_input_field"
        assert backend.memory[session.gate_address] == 1
        assert backend.screen_reader is True

    assert backend.memory[session.gate_address] == 0
    assert backend.screen_reader is False
    assert backend.closed is True


def test_accessibility_session_writes_gate_before_notifying_screen_reader():
    class OrderedBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.events = []

        def set_screen_reader(self, enabled):
            self.events.append(("screen_reader", enabled))
            return super().set_screen_reader(enabled)

        def write_byte(self, handle, address, value):
            self.events.append(("gate", value))
            return super().write_byte(handle, address, value)

    backend = OrderedBackend()

    with WeixinAccessibilitySession(backend):
        assert backend.events[:2] == [
            ("gate", 1),
            ("screen_reader", True),
        ]


def test_accessibility_session_rebroadcasts_when_screen_reader_is_already_on():
    class NotifyingBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.screen_reader = True
            self.notifications = []

        def set_screen_reader(self, enabled):
            self.notifications.append(enabled)
            return super().set_screen_reader(enabled)

    backend = NotifyingBackend()
    address = backend.module.base + 0x0AE2B0C8
    backend.memory[address] = 1

    with WeixinAccessibilitySession(backend):
        assert backend.writes == [(address, 1)]
        assert backend.broadcasts == [True]
        assert backend.notifications == [True]

    assert backend.memory[address] == 1
    assert backend.screen_reader is True


def test_accessibility_session_rolls_back_gate_when_rebroadcast_fails(tmp_path):
    class FailedBroadcastBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.screen_reader = True

        def broadcast_screen_reader_enabled(self):
            self.broadcasts.append(True)
            return False

    backend = FailedBroadcastBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    address = backend.module.base + 0x0AE2B0C8

    with pytest.raises(AccessibilitySafetyError, match="broadcast"):
        WeixinAccessibilitySession(
            backend,
            lease_journal=journal,
        ).__enter__()

    assert backend.broadcasts == [True]
    assert backend.memory[address] == 0
    assert backend.screen_reader is True
    assert backend.closed is True
    assert journal.load() is None


def test_native_window_responsiveness_uses_bounded_wm_null(monkeypatch):
    calls = []

    def send_message_timeout(*args):
        calls.append(args)
        return 1

    user32 = SimpleNamespace(SendMessageTimeoutW=send_message_timeout)
    monkeypatch.setattr(
        gate_module.ctypes, "windll", SimpleNamespace(user32=user32)
    )

    assert NativeGateBackend.window_responsive(101, timeout_ms=250) is True
    assert calls[0][0:5] == (
        101,
        gate_module.WM_NULL,
        0,
        0,
        gate_module.SMTO_ABORTIFHUNG | gate_module.SMTO_BLOCK,
    )
    assert calls[0][5] == 250


def test_native_screen_reader_notification_broadcasts_the_change(monkeypatch):
    calls = []
    user32 = SimpleNamespace(
        SystemParametersInfoW=lambda *args: calls.append(args) or 1
    )
    monkeypatch.setattr(
        gate_module.ctypes, "windll", SimpleNamespace(user32=user32)
    )

    assert NativeGateBackend().broadcast_screen_reader_enabled() is True

    assert calls == [
        (
            gate_module.SPI_SETSCREENREADER,
            1,
            None,
            gate_module.SPIF_SENDCHANGE,
        )
    ]


def test_native_backend_terminates_the_verified_weixin_process_tree(monkeypatch):
    calls = []
    backend = NativeGateBackend()
    monkeypatch.setattr(backend, "_require_windows", lambda: None)
    monkeypatch.setattr(backend, "process_exists", lambda _pid: False)
    monkeypatch.setattr(
        gate_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    backend.terminate_process_tree(202)

    assert calls[0][0] == ["taskkill", "/PID", "202", "/T", "/F"]
    assert calls[0][1]["timeout"] == 8
    assert calls[0][1]["check"] is False


def test_native_backend_waits_for_the_terminating_tree_to_fully_exit(monkeypatch):
    states = iter((True, True, False))
    backend = NativeGateBackend()
    monkeypatch.setattr(backend, "_require_windows", lambda: None)
    monkeypatch.setattr(backend, "process_exists", lambda _pid: next(states))
    monkeypatch.setattr(
        gate_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    backend.terminate_process_tree(202, wait_seconds=0.5)


def test_native_backend_rejects_a_process_tree_that_remains_alive(monkeypatch):
    backend = NativeGateBackend()
    monkeypatch.setattr(backend, "_require_windows", lambda: None)
    monkeypatch.setattr(backend, "process_exists", lambda _pid: True)
    monkeypatch.setattr(
        gate_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="process tree is still running"):
        backend.terminate_process_tree(202, wait_seconds=0)


def test_accessibility_session_does_not_guess_an_unknown_version():
    backend = FakeGateBackend()
    backend.version = "4.1.14.1"

    with pytest.raises(UnsupportedWeixinVersion):
        WeixinAccessibilitySession(backend).__enter__()

    assert backend.opened is False
    assert backend.writes == []


def test_accessibility_session_requires_a_writable_in_range_gate():
    backend = FakeGateBackend()
    backend.section = (".rdata", 0)
    with pytest.raises(RuntimeError, match="non-writable"):
        WeixinAccessibilitySession(backend).__enter__()
    assert backend.opened is False

    backend = FakeGateBackend()
    backend.module = ProcessModule(0x10000000, 0x1000, "Weixin.dll")
    with pytest.raises(RuntimeError, match="module size"):
        WeixinAccessibilitySession(backend).__enter__()
    assert backend.opened is False


def test_accessibility_session_rejects_an_unexpected_original_byte():
    backend = FakeGateBackend()
    address = backend.module.base + 0x0AE2B0C8
    backend.memory[address] = 7

    with pytest.raises(RuntimeError, match="unexpected gate value"):
        WeixinAccessibilitySession(backend).__enter__()

    assert backend.writes == []
    assert backend.closed is True


def test_cleanup_restores_gate_even_if_screen_reader_restore_fails():
    class CleanupFailureBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self._screen_reader_reads = 0

        def get_screen_reader(self):
            self._screen_reader_reads += 1
            if self._screen_reader_reads > 2:
                raise RuntimeError("screen reader restore failed")
            return super().get_screen_reader()

    backend = CleanupFailureBackend()
    session = WeixinAccessibilitySession(backend).__enter__()

    with pytest.raises(RuntimeError, match="screen reader restore failed"):
        session.close()

    assert backend.memory[session.gate_address] == 0
    assert backend.closed is True


def test_cleanup_restores_gate_before_disabling_screen_reader():
    class OrderedBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.events = []

        def set_screen_reader(self, enabled):
            self.events.append(("screen_reader", enabled))
            return super().set_screen_reader(enabled)

        def write_byte(self, handle, address, value):
            self.events.append(("gate", value))
            return super().write_byte(handle, address, value)

    backend = OrderedBackend()
    session = WeixinAccessibilitySession(backend).__enter__()
    backend.events.clear()

    session.close()

    assert backend.events[:2] == [("gate", 0), ("screen_reader", False)]


def test_cleanup_keeps_screen_reader_enabled_when_gate_restore_fails():
    class GateRestoreFailureBackend(FakeGateBackend):
        fail_restore = True

        def write_byte(self, handle, address, value):
            if value == 0 and self.fail_restore:
                return False
            return super().write_byte(handle, address, value)

    backend = GateRestoreFailureBackend()
    session = WeixinAccessibilitySession(backend).__enter__()

    with pytest.raises(AccessibilitySafetyError, match="restore.*gate"):
        session.close()

    assert backend.screen_reader is True
    assert backend.closed is False

    backend.fail_restore = False
    session.close()

    assert backend.memory[session.gate_address] == 0
    assert backend.screen_reader is False
    assert backend.closed is True


def test_cleanup_retries_screen_reader_restore_after_a_transient_failure():
    class ScreenReaderRetryBackend(FakeGateBackend):
        fail_restore = True

        def set_screen_reader(self, enabled):
            if enabled is False and self.fail_restore:
                return False
            return super().set_screen_reader(enabled)

    backend = ScreenReaderRetryBackend()
    session = WeixinAccessibilitySession(backend).__enter__()

    with pytest.raises(AccessibilitySafetyError, match="screen-reader"):
        session.close()

    assert backend.memory[session.gate_address] == 0
    assert backend.screen_reader is True
    assert session._original_screen_reader is False

    backend.fail_restore = False
    session.close()

    assert backend.screen_reader is False
    assert session._original_screen_reader is None


def test_cleanup_treats_an_exited_process_gate_as_already_gone(tmp_path):
    class ExitedProcessBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.alive = True
            self.started = "original-process"

        def process_exists(self, _pid):
            return self.alive

        def process_start_time(self, _pid):
            return self.started

    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = ExitedProcessBackend()
    session = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
    ).__enter__()
    backend.writes.clear()
    backend.alive = False

    session.close()

    assert backend.writes == []
    assert backend.closed is True
    assert backend.screen_reader is False
    assert journal.load() is None


def test_cleanup_never_writes_to_a_reused_pid(tmp_path):
    class ReusedPidBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.started = "original-process"

        def process_exists(self, _pid):
            return True

        def process_start_time(self, _pid):
            return self.started

    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = ReusedPidBackend()
    session = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
    ).__enter__()
    backend.writes.clear()
    backend.started = "replacement-process"

    session.close()

    assert backend.writes == []
    assert backend.closed is True
    assert backend.screen_reader is False
    assert journal.load() is None


def test_cleanup_fails_closed_when_process_identity_cannot_be_verified(tmp_path):
    class UnknownProcessBackend(FakeGateBackend):
        def process_exists(self, _pid):
            raise RuntimeError("access denied")

    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = UnknownProcessBackend()
    session = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
    ).__enter__()
    backend.writes.clear()

    with pytest.raises(AccessibilitySafetyError, match="identity"):
        session.close()

    assert backend.writes == []
    assert backend.closed is False
    assert backend.screen_reader is True
    assert journal.load() is not None


def _window(*, visible: bool):
    return win32_module.WindowRef(
        hwnd=101,
        pid=202,
        process_path=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        window_class="Chrome_WidgetWin_0",
        title="微信",
        visible=visible,
        bounds=(10, 20, 810, 620),
    )


def test_native_backend_window_inspection_is_read_only_and_json_compatible(
    monkeypatch,
):
    hidden = _window(visible=False)
    monkeypatch.setattr(NativeGateBackend, "_require_windows", lambda self: None)
    monkeypatch.setattr(
        "src.core.win32.find_wechat_window_ref", lambda: hidden
    )
    monkeypatch.setattr(
        "src.core.win32.restore_wechat_window",
        lambda *_args, **_kwargs: pytest.fail("read-only inspection must not restore"),
    )

    result = NativeGateBackend().window_inspection()

    assert result == {
        "hwnd": 101,
        "pid": 202,
        "processPath": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        "windowClass": "Chrome_WidgetWin_0",
        "title": "微信",
        "visible": False,
        "bounds": [10, 20, 810, 620],
        "windowState": "hidden",
        "restorable": True,
    }


def test_native_backend_missing_window_inspection_has_compatible_state_keys(
    monkeypatch,
):
    monkeypatch.setattr(NativeGateBackend, "_require_windows", lambda self: None)
    monkeypatch.setattr("src.core.win32.find_wechat_window_ref", lambda: None)

    result = NativeGateBackend().window_inspection()

    assert result["windowState"] == "missing"
    assert result["restorable"] is False
    assert result["hwnd"] == 0
    assert result["pid"] == 0


def test_native_backend_does_not_restore_after_discovery_reports_missing(
    monkeypatch,
):
    backend = NativeGateBackend()
    monkeypatch.setattr(backend, "discover_main_window", lambda: None)
    monkeypatch.setattr(
        "src.core.win32.restore_wechat_window",
        lambda *_args, **_kwargs: pytest.fail(
            "a missing snapshot must not be reinterpreted as rediscovery"
        ),
    )

    result = backend.prepare_main_window()

    assert result.window_state == "missing"
    assert result.stages == ()


def test_accessibility_session_prepares_window_before_touching_gate_state():
    class PreparingBackend(FakeGateBackend):
        def __init__(self):
            super().__init__()
            self.events = []

        def prepare_main_window(self):
            self.events.append("prepare")
            hidden = _window(visible=False)
            visible = _window(visible=True)
            return win32_module.WindowRestoreResult(
                initial=hidden,
                window=visible,
                restored=True,
                stages=(
                    win32_module.WindowRestoreStage(
                        stage="direct",
                        attempted=True,
                        succeeded=True,
                        detail="same PID visible",
                    ),
                ),
            )

        def find_main_window(self):
            pytest.fail("prepare_main_window supplies the verified window")

        def get_window_pid(self, hwnd):
            pytest.fail("prepare_main_window supplies the verified PID")

        def find_module(self, pid, name):
            self.events.append("find_module")
            return super().find_module(pid, name)

        def open_process(self, pid):
            self.events.append("open_process")
            return super().open_process(pid)

        def write_byte(self, handle, address, value):
            self.events.append("write_gate")
            return super().write_byte(handle, address, value)

    backend = PreparingBackend()

    with WeixinAccessibilitySession(backend) as session:
        assert session.window_restore.restored is True

    assert backend.events[:4] == [
        "prepare",
        "find_module",
        "open_process",
        "write_gate",
    ]


def test_accessibility_session_refuses_gate_access_when_restore_fails():
    class HiddenBackend(FakeGateBackend):
        def prepare_main_window(self):
            hidden = _window(visible=False)
            return win32_module.WindowRestoreResult(
                initial=hidden,
                window=hidden,
                restored=False,
                stages=(
                    win32_module.WindowRestoreStage(
                        stage="direct",
                        attempted=True,
                        succeeded=False,
                        detail="same PID remained hidden",
                    ),
                    win32_module.WindowRestoreStage(
                        stage="tray",
                        attempted=True,
                        succeeded=False,
                        detail="same PID remained hidden",
                    ),
                    win32_module.WindowRestoreStage(
                        stage="hotkey",
                        attempted=True,
                        succeeded=False,
                        detail="same PID remained hidden",
                    ),
                ),
            )

        def find_module(self, pid, name):
            pytest.fail("gate discovery must wait until the window is visible")

    backend = HiddenBackend()

    with pytest.raises(RuntimeError, match="direct.*tray.*hotkey"):
        WeixinAccessibilitySession(backend).__enter__()

    assert backend.opened is False
    assert backend.writes == []
