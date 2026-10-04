from __future__ import annotations

import json
import threading

import pytest

from app.agent.journal import GateLeaseJournal, SafetyJournal
from tests.test_gate_lease import LeaseBackend, _stale_lease


class RestartBackend(LeaseBackend):
    def __init__(self):
        super().__init__()
        self.alive = True
        self.events = []
        self.logged_in = True

    def legacy_agent_pids(self):
        return ()

    def process_exists(self, pid):
        return self.alive and pid == self.pid

    def verified_wechat_process(self):
        if not self.alive:
            return None
        return {"pid": self.pid, "processStartTime": self.started,
                "processPath": "Weixin.exe", "version": self.version, "hwnd": self.hwnd}

    def request_close(self, candidate):
        self.events.append("close")
        self.alive = False

    def terminate_process_tree(self, pid, **kwargs):
        self.events.append("kill")
        self.alive = False

    def start_process(self, path):
        self.events.append("start")
        self.pid = 303
        self.started = "new-process"
        self.alive = True

    def window_inspection(self):
        return {"hwnd": self.hwnd, "pid": self.pid, "windowClass": "mmui::MainWindow" if self.logged_in else "mmui::LoginWindow"}

    def window_responsive(self, hwnd):
        return True


def manager(tmp_path, backend, **kwargs):
    from app.agent.gate_recovery import GateRecoveryManager
    return GateRecoveryManager(backend, journal=GateLeaseJournal(tmp_path / "gate.json"),
                               temp_dir=tmp_path, **kwargs)


def test_corrupt_lease_restart_is_win32_only_and_keeps_task_boundary(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    safety = SafetyJournal(tmp_path / "task.json")
    boundary = safety.mark(task_id="t", kind="message_send", item_id="i", boundary="send", item_index=0)
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert result["attempt"] == 1
    assert backend.events == ["close", "start"]
    assert backend.writes == []
    assert backend.broadcasts == 0
    assert safety.load() == boundary
    assert not (tmp_path / "gate.json").exists()


def test_cli_cleanup_never_restarts_on_corrupt_evidence(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{", encoding="utf-8")
    result = manager(tmp_path, backend, allow_restart=False).run(threading.Event(), lambda state: None)
    assert result["stage"] == "blocked"
    assert backend.events == []
    assert (tmp_path / "gate.json").exists()


def test_restart_reservation_survives_crash_before_close(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")

    def crash(state):
        if state["stage"] == "restarting":
            raise SystemExit("injected Agent crash")

    with pytest.raises(SystemExit):
        manager(tmp_path, backend).run(threading.Event(), crash)
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["reasonCode"] == "GATE_RESTART_LIMIT"
    assert backend.events == []


def test_no_partial_restore_when_another_record_is_corrupt(tmp_path):
    backend = RestartBackend()
    valid = GateLeaseJournal(tmp_path / "wuge-wechat-agent-123-safety.json.gate")
    _stale_lease(valid, backend)
    backend.memory[backend.address] = 1
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    result = manager(tmp_path, backend, allow_restart=False).run(threading.Event(), lambda state: None)
    assert result["stage"] == "blocked"
    assert backend.writes == []
    assert valid.path.exists()


def test_conflicting_originals_restart_once_without_writing_gate(tmp_path):
    backend = RestartBackend()
    first = GateLeaseJournal(tmp_path / "gate.json")
    _stale_lease(first, backend)
    second = GateLeaseJournal(tmp_path / "wuge-wechat-agent-123-safety.json.gate")
    record = _stale_lease(second, backend)
    record["originalGate"] = 1
    second.path.write_text(json.dumps(record), encoding="utf-8")
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.writes == []
    assert backend.events == ["close", "start"]


def test_orphan_tmp_without_wechat_is_archived_without_restart(tmp_path):
    backend = RestartBackend()
    backend.alive = False
    (tmp_path / "gate.json.tmp").write_text("half-written", encoding="utf-8")
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.events == []
    assert list((tmp_path / "gate-archive").glob("*.tmp"))


def test_live_agent_blocks_even_corrupt_lease(tmp_path):
    backend = RestartBackend()
    backend.legacy_agent_pids = lambda: (999,)
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["reasonCode"] == "AGENT_ALREADY_RUNNING"
    assert backend.events == []


def test_login_timeout_is_bounded_and_not_restarted_on_relaunch(tmp_path):
    backend = RestartBackend()
    backend.logged_in = False
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    result = manager(tmp_path, backend, login_timeout=0.02).run(threading.Event(), lambda state: None)
    assert result["reasonCode"] == "GATE_LOGIN_TIMEOUT"
    assert backend.events == ["close", "start"]
    recovered = manager(tmp_path, backend, login_timeout=0.02)
    recovered._wait_login = lambda reservation: pytest.fail("relaunch must not restart expired login waiting")
    next_result = recovered.run(threading.Event(), lambda state: None)
    assert next_result["reasonCode"] == "GATE_LOGIN_TIMEOUT"
    assert backend.events == ["close", "start"]


def test_cancel_recovery_does_not_restart_or_delete_evidence(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    stop = threading.Event()
    stop.set()
    result = manager(tmp_path, backend).run(stop, lambda state: None)
    assert result["reasonCode"] == "GATE_RECOVERY_CANCELLED"
    assert backend.events == []
    next_result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert next_result["reasonCode"] == "GATE_RECOVERY_CANCELLED"
    assert backend.events == []


def test_manual_restart_after_cancel_before_first_attempt_clears_without_auto_restart(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    stop = threading.Event()
    stop.set()
    manager(tmp_path, backend).run(stop, lambda state: None)
    backend.pid = 303
    backend.started = "manual-after-cancel"
    result = manager(tmp_path, backend, allow_restart=False).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.events == []


def test_cancel_before_any_lease_does_not_block_future_clean_login(tmp_path):
    backend = RestartBackend()
    backend.alive = False
    stop = threading.Event()
    stop.set()
    assert manager(tmp_path, backend).run(stop, lambda state: None)["reasonCode"] == "GATE_RECOVERY_CANCELLED"
    backend.alive = True
    assert manager(tmp_path, backend).run(threading.Event(), lambda state: None)["stage"] == "completed"
    assert backend.events == []


def test_permission_error_is_not_treated_as_corruption(tmp_path, monkeypatch):
    backend = RestartBackend()
    lease = GateLeaseJournal(tmp_path / "gate.json")
    _stale_lease(lease, backend)
    monkeypatch.setattr(GateLeaseJournal, "archive", lambda *a, **kw: (_ for _ in ()).throw(PermissionError("denied")))
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "blocked"
    assert backend.events == []


def test_manual_restart_after_interrupted_reservation_unblocks_without_second_restart(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    def crash(state):
        if state["stage"] == "restarting":
            raise SystemExit()
    with pytest.raises(SystemExit):
        manager(tmp_path, backend).run(threading.Event(), crash)
    backend.pid = 303
    backend.started = "manually-restarted"
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.events == []


def test_invalid_restart_reservation_cannot_reset_budget(tmp_path):
    backend = RestartBackend()
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    (tmp_path / "gate.json.recovery.json").write_text('{"attempt":0,"recoveryId":"x"}', encoding="utf-8")
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["reasonCode"] == "GATE_RECOVERY_BLOCKED"
    assert backend.events == []


def test_manual_login_after_timeout_recovers_using_read_only_detection(tmp_path):
    backend = RestartBackend()
    backend.logged_in = False
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    manager(tmp_path, backend, login_timeout=0.01).run(threading.Event(), lambda state: None)
    backend.logged_in = True
    result = manager(tmp_path, backend, allow_restart=False).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.events == ["close", "start"]


def test_unsupported_version_never_closes_or_restarts_wechat(tmp_path):
    backend = RestartBackend()
    backend.version = "4.1.13.66"
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    result = manager(tmp_path, backend).run(threading.Event(), lambda state: None)
    assert result["stage"] == "blocked"
    assert backend.events == []


def test_cancel_while_awaiting_login_does_not_repeat_restart(tmp_path):
    backend = RestartBackend()
    backend.logged_in = False
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    stop = threading.Event()
    def cancel(state):
        if state["stage"] == "awaiting_login":
            stop.set()
    result = manager(tmp_path, backend).run(stop, cancel)
    assert result["reasonCode"] == "GATE_RECOVERY_CANCELLED"
    assert backend.events == ["close", "start"]
    reservation = json.loads((tmp_path / "gate.json.recovery.json").read_text(encoding="utf-8"))
    assert reservation["phase"] == "cancelled"
    recovered = manager(tmp_path, backend)
    recovered._wait_login = lambda record: pytest.fail("cancelled login waiting must not restart")
    next_result = recovered.run(threading.Event(), lambda state: None)
    assert next_result["reasonCode"] == "GATE_RECOVERY_CANCELLED"
    backend.logged_in = True
    assert manager(tmp_path, backend, allow_restart=False).run(threading.Event(), lambda state: None)["stage"] == "completed"
    assert backend.events == ["close", "start"]


def test_wechat_dll_still_loading_is_bounded_login_wait_not_restart_failure(tmp_path):
    from app.agent.gate import WechatStartupPending
    backend = RestartBackend()
    original = backend.verified_wechat_process
    reads = []
    def candidate():
        reads.append(True)
        if backend.pid == 303 and len(reads) < 4:
            raise WechatStartupPending("DLL not loaded yet")
        return original()
    backend.verified_wechat_process = candidate
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    result = manager(tmp_path, backend, login_timeout=1).run(threading.Event(), lambda state: None)
    assert result["stage"] == "completed"
    assert backend.events == ["close", "start"]
