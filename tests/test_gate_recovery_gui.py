from __future__ import annotations

from app.agent.client import AgentClient
from tests.test_v3_controllers import make_backend


def test_idle_crash_reserves_exactly_one_reconnect(qapp, tmp_path):
    client = AgentClient(gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path)
    client._start_gate_recovery_async = lambda: None
    client._capture_process_stderr = lambda: None
    client._state = "connected"
    client._on_process_finished(70, None)
    assert client._pending_start_after_recovery
    client._pending_start_after_recovery = False
    client._state = "connected"
    client._on_process_finished(70, None)
    assert not client._pending_start_after_recovery
    client.close()


def test_active_task_does_not_get_idle_reconnect_budget(qapp, tmp_path):
    client = AgentClient(gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path)
    client._task_active = True
    client._start_gate_recovery_async = lambda: None
    client._capture_process_stderr = lambda: None
    client._state = "connected"
    client._on_process_finished(70, None)
    assert not client._pending_start_after_recovery
    client.close()


def test_gate_recovery_status_blocks_start_and_filters_stale_health(qapp, tmp_path):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection({"sequence": 10, "agentInstanceId": "a", "gateRecovery": {
        "stage": "restarting", "reasonCode": "GATE_RESTARTING", "attempt": 1},
        "sessionReady": False, "reasonCode": "GATE_RESTARTING"})
    assert backend.task.automationStatus == "正在重启微信"
    assert backend.agent.gateRecoveryActive
    assert not backend.agent.canStartTask
    backend.agent.applyInspection({"sequence": 9, "agentInstanceId": "a", "sessionReady": True})
    assert backend.task.automationStatus == "正在重启微信"
    backend.agent.applyInspection({"sequence": 11, "agentInstanceId": "a", "processDetected": True,
        "versionSupported": True, "sessionReady": True, "windowResponsive": True,
        "windowEnabled": True, "gateRecovery": {"stage": "completed", "reasonCode": ""}})
    assert backend.agent.canStartTask
    assert backend.task.automationStatus == "自动化已就绪"
    assert not backend.task.active
    backend.shutdown()


def test_recovery_buttons_use_gate_scope_without_task_acknowledgement(qapp, tmp_path):
    backend, client = make_backend(tmp_path)
    backend.agent.cancelGateRecovery()
    assert client.calls[-1][1:] == ("recovery.approve", {"scope": "gate", "decision": "stop"})
    backend.shutdown()


def test_queued_reconnect_cannot_restart_after_gui_close(qapp, qtbot, tmp_path):
    client = AgentClient(gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path)
    starts = []
    client.start = lambda: starts.append(True)
    client._state = "disconnected"
    class Process:
        def deleteLater(self):
            pass
    process = Process()
    client._recovery_process = process
    client._pending_start_after_recovery = True
    client._finish_gate_recovery(process, successful=True)
    client.close()
    qtbot.wait(20)
    assert starts == []


def test_offline_recovery_does_not_disable_manual_detection(qapp, tmp_path):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection({"gateRecovery": {"stage": "awaiting_login"}})
    client.connectedChanged.emit(False)
    assert not backend.agent.gateRecoveryBusy
    assert backend.agent.recoveryStatus == "恢复连接已断开"
    backend.shutdown()
