from __future__ import annotations

import json

import pytest

from app.agent.gate import (
    AccessibilitySafetyError,
    IMAGE_SCN_MEM_WRITE,
    ProcessModule,
    WeixinAccessibilitySession,
    restore_legacy_gate_leases,
    restore_gate_lease,
)
from app.agent.journal import GateLeaseJournal, default_gate_lease_path


class LeaseBackend:
    def __init__(self):
        self.hwnd = 101
        self.pid = 202
        self.started = "134000000000000000"
        self.version = "4.1.13.65"
        self.module = ProcessModule(0x10000000, 0x0B000000, "Weixin.dll")
        self.address = self.module.base + 0x0AE2B0C8
        self.memory = {self.address: 0}
        self.screen_reader = False
        self.writes: list[tuple[int, int]] = []
        self.broadcasts = 0

    def process_context(self, pid=None):
        return {"windowsSessionId": 1, "logonId": "123", "logonTime": "456",
                "ownerAgentPid": 909, "ownerAgentStartTime": "789"}

    def process_session_id(self, pid):
        return 1

    def find_main_window(self):
        return self.hwnd

    def get_window_pid(self, _hwnd):
        return self.pid

    def process_start_time(self, _pid):
        return self.started

    def process_exists(self, pid):
        return int(pid) == self.pid

    def find_module(self, _pid, _name):
        return self.module

    def file_version(self, _path):
        return self.version

    def pe_section_for_rva(self, _path, _rva):
        return ".data", IMAGE_SCN_MEM_WRITE

    def open_process(self, _pid):
        return "handle"

    def close_process(self, _handle):
        pass

    def read_byte(self, _handle, address):
        return self.memory.get(address)

    def write_byte(self, _handle, address, value):
        self.writes.append((address, value))
        self.memory[address] = value
        return True

    def get_screen_reader(self):
        return self.screen_reader

    def set_screen_reader(self, enabled):
        self.screen_reader = bool(enabled)
        return True

    def broadcast_screen_reader_enabled(self):
        self.broadcasts += 1
        return self.set_screen_reader(True)


@pytest.mark.parametrize("alive", [True, False])
def test_foreign_windows_session_lease_is_never_restored(tmp_path, alive):
    backend = LeaseBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    record = _stale_lease(journal, backend)
    record["windowsSessionId"] = 2
    journal.path.write_text(json.dumps(record), encoding="utf-8")
    backend.memory[backend.address] = 1
    backend.screen_reader = True
    backend.process_session_id = lambda _: 1
    backend.process_exists = lambda _: alive
    if alive:
        with pytest.raises(AccessibilitySafetyError, match="Windows session"):
            restore_gate_lease(backend, journal)
        assert journal.load() == record
    else:
        restore_gate_lease(backend, journal)
        assert not journal.path.exists()
    assert backend.writes == []
    assert backend.screen_reader is True


def _stale_lease(journal: GateLeaseJournal, backend: LeaseBackend):
    return journal.mark(
        pid=backend.pid,
        process_start_time=backend.started,
        version=backend.version,
        gate_rva=0x0AE2B0C8,
        original_gate=0,
        original_screen_reader=False,
        gate_owned=True,
        screen_reader_owned=True,
        session_generation=7,
        lease_context=backend.process_context(),
    )


def test_gate_lease_is_atomic_and_separate_from_task_safety_journal(tmp_path):
    journal = GateLeaseJournal(tmp_path / "agent-safety.json.gate")
    backend = LeaseBackend()

    record = _stale_lease(journal, backend)

    assert GateLeaseJournal(journal.path).load() == record
    assert record["pid"] == 202
    assert record["sessionGeneration"] == 7


def test_default_gate_lease_path_is_stable_across_gui_processes(
    tmp_path, monkeypatch
):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.delenv("WECHAT_AGENT_GATE_LEASE", raising=False)
    monkeypatch.setenv(
        "WECHAT_AGENT_JOURNAL", str(tmp_path / "random-task-journal.json")
    )

    first = GateLeaseJournal.from_environment()
    monkeypatch.setenv(
        "WECHAT_AGENT_JOURNAL", str(tmp_path / "another-task-journal.json")
    )
    second = GateLeaseJournal.from_environment()

    expected = (
        local_app_data / "WxAuto" / "state" / "weixin-uia-gate-v1.json"
    )
    assert default_gate_lease_path() == expected
    assert first.path == expected
    assert second.path == expected


def test_stale_lease_restores_gate_and_screen_reader_without_uia(tmp_path):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    _stale_lease(journal, backend)
    backend.memory[backend.address] = 1
    backend.screen_reader = True

    result = restore_gate_lease(backend, journal)

    assert result == {"restored": True, "reason": "stale_lease_recovered"}
    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False
    assert journal.load() is None


def test_stale_lease_uses_recorded_pid_when_weixin_has_no_window(tmp_path):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    _stale_lease(journal, backend)
    backend.hwnd = 0
    backend.memory[backend.address] = 1
    backend.screen_reader = True

    result = restore_gate_lease(backend, journal)

    assert result == {"restored": True, "reason": "stale_lease_recovered"}
    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False


def test_changed_weixin_process_is_never_patched_from_an_old_lease(tmp_path):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    _stale_lease(journal, backend)
    backend.pid = 303
    backend.started = "134000000000000999"
    backend.screen_reader = True

    result = restore_gate_lease(backend, journal)

    assert result == {"restored": True, "reason": "process_changed"}
    assert backend.writes == []
    assert backend.screen_reader is False
    assert journal.load() is None


def test_lease_is_preserved_when_a_live_process_identity_cannot_be_verified(
    tmp_path,
):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    _stale_lease(journal, backend)
    backend.memory[backend.address] = 1
    backend.screen_reader = True
    backend.process_exists = lambda _pid: True
    backend.process_start_time = lambda _pid: (_ for _ in ()).throw(
        RuntimeError("access denied")
    )

    with pytest.raises(AccessibilitySafetyError, match="identity"):
        restore_gate_lease(backend, journal)

    assert backend.memory[backend.address] == 1
    assert backend.screen_reader is True
    assert journal.load() is not None


def test_lease_is_preserved_when_the_same_process_reports_another_version(
    tmp_path,
):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    _stale_lease(journal, backend)
    backend.memory[backend.address] = 1
    backend.screen_reader = True
    backend.version = "4.1.13.66"

    with pytest.raises(AccessibilitySafetyError, match="version"):
        restore_gate_lease(backend, journal)

    assert backend.memory[backend.address] == 1
    assert backend.screen_reader is True
    assert journal.load() is not None


def test_live_session_records_ownership_before_mutation_and_clears_on_close(tmp_path):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()

    session = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
        session_generation=3,
    ).__enter__()

    record = journal.load()
    assert record is not None
    assert record["gateOwned"] is True
    assert record["screenReaderOwned"] is True
    assert record["sessionGeneration"] == 3
    assert backend.memory[backend.address] == 1

    session.close()

    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False
    assert journal.load() is None


def test_screen_reader_ownership_transfers_across_a_weixin_process_restart(tmp_path):
    journal = GateLeaseJournal(tmp_path / "gate.json")
    backend = LeaseBackend()
    first = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
        session_generation=1,
    ).__enter__()

    restore_value = first.screen_reader_restore_value
    first.close(preserve_screen_reader=True)

    assert restore_value is False
    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is True
    assert journal.load()["screenReaderOwned"] is True

    backend.pid = 303
    backend.started = "134000000000000999"
    second = WeixinAccessibilitySession(
        backend,
        lease_journal=journal,
        session_generation=2,
        screen_reader_restore_value=restore_value,
    ).__enter__()

    assert journal.load()["pid"] == 303
    assert journal.load()["screenReaderOwned"] is True
    assert backend.broadcasts == 2
    second.close()

    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False
    assert journal.load() is None


def test_invalid_stable_gate_lease_fails_closed_without_deleting_it(tmp_path):
    path = tmp_path / "stable-gate.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(AccessibilitySafetyError, match="invalid gate lease"):
        restore_gate_lease(LeaseBackend(), GateLeaseJournal(path))

    assert path.read_text(encoding="utf-8") == "{}"


def test_legacy_random_gate_lease_is_safely_restored_once(tmp_path):
    legacy_path = (
        tmp_path
        / "wuge-wechat-agent-123-deadbeef-safety.json.gate"
    )
    legacy = GateLeaseJournal(legacy_path)
    backend = LeaseBackend()
    _stale_lease(legacy, backend)
    backend.memory[backend.address] = 1
    backend.screen_reader = True

    restored = restore_legacy_gate_leases(
        backend,
        temp_dir=tmp_path,
        other_agent_pids=lambda: (),
    )

    assert restored == [
        {
            "path": str(legacy_path),
            "reason": "stale_lease_recovered",
        }
    ]
    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False
    assert not legacy_path.exists()


def test_legacy_gate_lease_is_not_touched_while_another_agent_is_alive(
    tmp_path,
):
    legacy_path = (
        tmp_path
        / "wuge-wechat-agent-123-deadbeef-safety.json.gate"
    )
    legacy = GateLeaseJournal(legacy_path)
    backend = LeaseBackend()
    _stale_lease(legacy, backend)
    backend.memory[backend.address] = 1
    backend.screen_reader = True

    with pytest.raises(AccessibilitySafetyError, match="another Agent"):
        restore_legacy_gate_leases(
            backend,
            temp_dir=tmp_path,
            other_agent_pids=lambda: (999,),
        )

    assert backend.writes == []
    assert backend.screen_reader is True
    assert legacy.load() is not None


def test_legacy_gate_lease_is_archived_when_recorded_process_has_exited(
    tmp_path,
):
    legacy_path = (
        tmp_path
        / "wuge-wechat-agent-123-deadbeef-safety.json.gate"
    )
    legacy = GateLeaseJournal(legacy_path)
    backend = LeaseBackend()
    _stale_lease(legacy, backend)
    backend.pid = 303
    backend.started = "134000000000000999"
    backend.screen_reader = True

    restore_legacy_gate_leases(
        backend,
        temp_dir=tmp_path,
        other_agent_pids=lambda: (),
    )

    assert backend.writes == []
    assert backend.screen_reader is False
    assert legacy.load() is None
    assert list((tmp_path / "gate-archive").glob("*.gate"))


def test_old_schema_dead_process_is_archived_without_system_mutation(tmp_path):
    backend = LeaseBackend()
    journal = GateLeaseJournal(tmp_path / "old.json")
    record = _stale_lease(journal, backend)
    for field in ("schemaVersion", "logonId", "logonTime", "ownerAgentPid", "ownerAgentStartTime", "windowsSessionId"):
        record.pop(field, None)
    journal.path.write_text(json.dumps(record), encoding="utf-8")
    backend.pid = 303
    backend.screen_reader = True
    restore_gate_lease(backend, journal)
    assert not journal.path.exists()
    assert backend.writes == []
    assert backend.screen_reader is True


def test_new_login_with_reused_session_number_never_restores_old_system_flag(tmp_path):
    backend = LeaseBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    _stale_lease(journal, backend)
    backend.pid = 303
    backend.screen_reader = True
    backend.process_context = lambda pid=None: {"windowsSessionId": 1, "logonId": "new", "logonTime": "new"}
    restore_gate_lease(backend, journal)
    assert backend.screen_reader is True
    assert backend.writes == []
    assert not journal.path.exists()


def test_v2_lease_records_owner_and_login_before_activation(tmp_path):
    backend = LeaseBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    session = WeixinAccessibilitySession(backend, lease_journal=journal).__enter__()
    try:
        record = journal.load()
        assert record["schemaVersion"] == 2
        assert record["logonId"] == "123"
        assert record["ownerAgentPid"] == 909
    finally:
        session.close()


def test_live_wechat_from_different_login_is_not_patched_even_in_same_windows_session(tmp_path):
    backend = LeaseBackend()
    journal = GateLeaseJournal(tmp_path / "gate.json")
    _stale_lease(journal, backend)
    backend.memory[backend.address] = 1
    original = backend.process_context
    backend.process_context = lambda pid=None: dict(original(), logonId="foreign" if pid == backend.pid else "123")
    with pytest.raises(AccessibilitySafetyError, match="login"):
        restore_gate_lease(backend, journal)
    assert backend.writes == []
    assert journal.path.exists()


def test_invalid_legacy_gate_lease_fails_closed_without_deleting_it(tmp_path):
    legacy_path = (
        tmp_path
        / "wuge-wechat-agent-123-deadbeef-safety.json.gate"
    )
    legacy_path.write_text("{}", encoding="utf-8")

    with pytest.raises(AccessibilitySafetyError, match="invalid legacy"):
        restore_legacy_gate_leases(
            LeaseBackend(),
            temp_dir=tmp_path,
            other_agent_pids=lambda: (),
        )

    assert legacy_path.read_text(encoding="utf-8") == "{}"


def test_legacy_gate_lease_rejects_stringified_ownership_flags(tmp_path):
    legacy_path = (
        tmp_path
        / "wuge-wechat-agent-123-deadbeef-safety.json.gate"
    )
    legacy = GateLeaseJournal(legacy_path)
    backend = LeaseBackend()
    record = _stale_lease(legacy, backend)
    record["gateOwned"] = "false"
    legacy_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(AccessibilitySafetyError, match="invalid legacy"):
        restore_legacy_gate_leases(
            backend,
            temp_dir=tmp_path,
            other_agent_pids=lambda: (),
        )

    assert backend.writes == []
    assert legacy_path.is_file()
