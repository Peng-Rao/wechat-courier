from __future__ import annotations

import pytest

from app.agent.gate import (
    AccessibilitySafetyError,
    IMAGE_SCN_MEM_WRITE,
    ProcessModule,
    WeixinAccessibilitySession,
    restore_gate_lease,
)
from app.agent.journal import GateLeaseJournal


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

    def find_main_window(self):
        return self.hwnd

    def get_window_pid(self, _hwnd):
        return self.pid

    def process_start_time(self, _pid):
        return self.started

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
    )


def test_gate_lease_is_atomic_and_separate_from_task_safety_journal(tmp_path):
    journal = GateLeaseJournal(tmp_path / "agent-safety.json.gate")
    backend = LeaseBackend()

    record = _stale_lease(journal, backend)

    assert GateLeaseJournal(journal.path).load() == record
    assert record["pid"] == 202
    assert record["sessionGeneration"] == 7


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
    second.close()

    assert backend.memory[backend.address] == 0
    assert backend.screen_reader is False
    assert journal.load() is None
