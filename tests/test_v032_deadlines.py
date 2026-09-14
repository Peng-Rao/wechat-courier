import pytest

from app.agent import waiters
from app.agent.runtime import AgentRuntime
from tests.test_agent_runtime import RecordingEngine


def test_nested_waits_share_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(waiters.time, "monotonic", lambda: clock[0])
    with pytest.raises(waiters.ActionDeadlineExceeded):
        with waiters.action_deadline(15):
            clock[0] = 14.0
            with waiters.action_deadline(15):
                clock[0] = 15.1
                waiters.DeadlineWaiter().wait(lambda: True, 5)


def test_poll_notices_and_pause_cannot_extend_inflight_deadline(qapp, qtbot):
    runtime = AgentRuntime(engine_factory=RecordingEngine)
    try:
        runtime._forward_notice("agent.status", {"status": "uia_action_started", "actionId": "a"})
        remaining = runtime._action_watchdog.remainingTime()
        qtbot.wait(40)
        runtime._forward_notice("agent.status", {"status": "uia_action_progress", "actionId": "a"})
        assert runtime._action_watchdog.remainingTime() < remaining - 15
        runtime._forward_notice("agent.status", {"status": "uia_action_completed", "actionId": "a"})
        assert not runtime._action_watchdog.isActive()
    finally:
        runtime.close()


def test_successful_cleanup_in_tray_clears_runtime_latch(qapp):
    runtime = AgentRuntime(engine_factory=RecordingEngine)
    try:
        runtime._cleanup_failed = True
        runtime._inspection_callbacks.append(lambda *_: None)
        runtime._inspection_finished({"result": {
            "cleanupComplete": True, "sessionReady": False, "restorable": True,
            "windowEnabled": True, "windowResponsive": True,
        }})
        assert runtime._cleanup_failed is False
        runtime._inspection_callbacks.append(lambda *_: None)
        runtime._inspection_finished({"result": {
            "cleanupComplete": False, "sessionReady": True, "windowEnabled": True,
        }})
        assert runtime._cleanup_failed is True
    finally:
        runtime.close()
