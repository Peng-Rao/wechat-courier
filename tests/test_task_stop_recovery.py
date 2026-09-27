from __future__ import annotations

import pytest

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.gate import AccessibilitySafetyError
from app.agent.native_driver import WindowBlockedError
from app.agent.profile import UnsupportedWeixinVersion
from app.agent.retry import WeixinUnresponsiveError
from app.agent.runtime import TaskControl
from app.agent.uia_events import EventCleanupError
from app.agent.waiters import ActionDeadlineExceeded
from app.agent.workflows import RiskControlError, WeixinWorkflowEngine
from tests.test_agent_workflows import FakeDriver


class RecoveryDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.search_results = {"Mock": ["Mock"]}
        self.search_available = True
        self.order = []
        self.cleanup_ok = True
        self.inspect_error = None
        self.window = {
            "pid": 123,
            "hwnd": 456,
            "version": "4.1.13.65",
            "sessionGeneration": 1,
            "windowResponsive": True,
            "windowEnabled": True,
            "blockingWindow": None,
        }

    def begin_task(self, kind):
        self.order.append("begin")

    def bind_window(self):
        self.order.append("bind")
        return dict(self.window)

    def ensure_search_ready(self):
        return self.search_available

    def finish_task(self):
        self.order.append("cleanup")
        return {
            "success": self.cleanup_ok,
            "reasonCode": "" if self.cleanup_ok else "CLEANUP_FAILED",
        }

    def diagnostic_snapshot(self):
        return dict(self.window)

    def inspect(self):
        self.order.append("inspect")
        if self.inspect_error is not None:
            raise self.inspect_error
        return {
            **self.window,
            "processDetected": True,
            "versionSupported": True,
            "sessionReady": True,
            "uiaReady": True,
            "restorable": False,
            "degradedReason": "",
            "detail": "ready",
        }


def make_request(kind="message_send", *, task_id="first", count=1, options=None):
    return TaskRequest(
        task_id=task_id,
        kind=kind,
        items=tuple(
            TaskItem(item_id=f"item-{index}", target="Mock", message="mock-only", account="mock_only")
            for index in range(count)
        ),
        options=options or TaskOptions(),
    )


def make_engine(driver, *, sleep=lambda _: None):
    return WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=sleep)


def test_search_failure_then_stop_rechecks_once_and_does_not_replay():
    driver = RecoveryDriver()
    driver.search_available = False
    engine = make_engine(driver)
    initial = engine.inspect()
    control = TaskControl()
    notices = []

    def emit(method, payload):
        notices.append((method, payload))
        if method == "task.event" and payload.get("outcome") == "error":
            control.request_stop()

    result = engine.run(make_request(count=2), control, emit)

    assert result["error"] == 1
    assert result["cleanup"]["success"] is True
    assert result["health"]["sessionReady"] is True
    assert result["health"]["uiaReady"] is True
    assert result["health"]["reasonCode"] == ""
    assert result["health"]["sequence"] > initial["sequence"]
    assert driver.order[-2:] == ["cleanup", "inspect"]
    assert driver.order.count("inspect") == 2
    assert driver.sent == []
    errors = [p for m, p in notices if m == "task.event" and p["outcome"] == "error"]
    assert errors[0]["errorCode"] == "TRANSIENT_UI"
    assert errors[0]["step"] == "search_ready"

    driver.search_available = True
    next_result = engine.run(make_request(task_id="next"), TaskControl(), lambda *_: None)
    assert next_result["success"] == 1
    assert driver.sent == ["mock-only"]


def test_later_account_not_found_does_not_keep_an_earlier_failure_as_health():
    driver = RecoveryDriver()
    attempts = []

    def open_friend():
        attempts.append(True)
        return len(attempts) > 3

    driver.open_add_friend = open_friend
    driver.search_friend = lambda _: None
    engine = make_engine(driver)
    engine.inspect()
    control = TaskControl()
    events = []

    def emit(method, payload):
        if method == "task.event":
            events.append(payload)
            if payload.get("errorCode") == "ACCOUNT_NOT_FOUND":
                control.request_stop()

    result = engine.run(make_request("friend_add", count=2), control, emit)

    assert result["error"] == 2
    assert [e["errorCode"] for e in events if e["outcome"] == "error"] == [
        "TRANSIENT_UI", "ACCOUNT_NOT_FOUND",
    ]
    assert result["health"]["sessionReady"] is True
    assert driver.order.count("inspect") == 2
    assert driver.friend_submit_count == 0


@pytest.mark.parametrize("stop_at", ["before", "retry", "interval", "paused"])
def test_safe_stop_cleans_then_rechecks_without_running_remaining_items(stop_at):
    driver = RecoveryDriver()
    control = TaskControl()
    events = []
    if stop_at == "before":
        control.request_stop()
    elif stop_at == "retry":
        driver.search_available = False
    elif stop_at == "paused":
        control.pause()
        original_finish = driver.finish_task

        def finish_paused():
            control.request_stop()
            return original_finish()

        driver.finish_task = finish_paused

    def emit(method, payload):
        events.append((method, payload))
        if stop_at == "retry" and method == "task.event" and payload.get("retryLevel") == "same_session":
            control.request_stop()
        if stop_at == "interval" and method == "agent.status" and payload.get("status") == "waiting":
            control.request_stop()

    engine = make_engine(driver)
    result = engine.run(
        make_request(count=2, options=TaskOptions(interval_min=1, interval_max=1)),
        control,
        emit,
    )
    assert result["cleanup"]["success"] is True
    assert result["health"]["sessionReady"] is True
    assert driver.order[-2:] == ["cleanup", "inspect"]
    assert driver.order.count("inspect") == 1
    assert len(driver.sent) == (1 if stop_at == "interval" else 0)


@pytest.mark.parametrize("changes,code", [
    ({"windowResponsive": False}, "WECHAT_UNRESPONSIVE"),
    ({"windowEnabled": False}, "WINDOW_DISABLED"),
    ({"blockingWindow": {"hwnd": 789, "pid": 123}}, "WINDOW_BLOCKED"),
])
def test_stop_does_not_call_uia_inspect_on_an_unsafe_window(changes, code):
    driver = RecoveryDriver()
    driver.window.update(changes)
    control = TaskControl()
    control.request_stop()
    result = make_engine(driver).run(make_request(), control, lambda *_: None)

    assert "inspect" not in driver.order
    assert result["health"]["sessionReady"] is False
    assert result["health"]["uiaReady"] is False
    assert result["health"]["reasonCode"] == code
    for key, value in changes.items():
        assert result["health"][key] == value


@pytest.mark.parametrize("error,code", [
    (AccessibilitySafetyError("gate unsafe"), "GATE_SAFETY"),
    (WeixinUnresponsiveError("no response"), "WECHAT_UNRESPONSIVE"),
    (WindowBlockedError("unknown modal"), "WINDOW_BLOCKED"),
    (EventCleanupError("unsubscribe", RuntimeError("failed")), "EVENT_CLEANUP_FAILED"),
    (UnsupportedWeixinVersion("unsupported"), "UNSUPPORTED_VERSION"),
    (RiskControlError("risk"), "RISK_CONTROL"),
])
def test_terminal_safety_failure_is_not_cleared_by_successful_cleanup(error, code):
    driver = RecoveryDriver()

    def fail():
        raise error

    driver.bind_window = fail
    result = make_engine(driver).run(make_request(), TaskControl(), lambda *_: None)

    assert "inspect" not in driver.order
    assert result["health"]["sessionReady"] is False
    assert result["health"]["reasonCode"] == code
    assert driver.sent == []


def test_failed_final_inspect_clears_all_readiness_flags_and_uses_current_reason():
    driver = RecoveryDriver()
    engine = make_engine(driver)
    engine.inspect()
    driver.inspect_error = ActionDeadlineExceeded("inspection exceeded deadline")
    control = TaskControl()
    control.request_stop()
    result = engine.run(make_request(), control, lambda *_: None)

    assert result["outcome"] == "stopped"
    assert result["cleanup"]["success"] is True
    assert result["health"]["sessionReady"] is False
    assert result["health"]["uiaReady"] is False
    assert result["health"]["reasonCode"] == "ACTION_DEADLINE_EXCEEDED"
    assert result["health"]["degradedReason"] == "ACTION_DEADLINE_EXCEEDED"
    assert driver.order.count("inspect") == 2


def test_cleanup_failure_blocks_inspection_and_next_task_without_losing_delivery():
    driver = RecoveryDriver()
    driver.cleanup_ok = False
    engine = make_engine(driver)
    result = engine.run(make_request(), TaskControl(), lambda *_: None)

    assert result["success"] == 1
    assert result["cleanup"]["success"] is False
    assert result["health"]["reasonCode"] == "CLEANUP_FAILED"
    assert "inspect" not in driver.order
    assert engine.run(make_request(task_id="next"), TaskControl(), lambda *_: None)["outcome"] == "error"
    assert driver.sent == ["mock-only"]


def test_unknown_delivery_stays_unknown_after_environment_recovers():
    driver = RecoveryDriver()
    driver.send_verification = None
    result = make_engine(driver).run(make_request(), TaskControl(), lambda *_: None)

    assert result["unknown"] == 1
    assert result["success"] == 0
    assert result["health"]["sessionReady"] is True
    assert driver.sent == ["mock-only"]


@pytest.mark.parametrize("error,code", [
    (RiskControlError("risk after send"), "RISK_CONTROL"),
    (AccessibilitySafetyError("unsafe after send"), "GATE_SAFETY"),
    (EventCleanupError("subscription", RuntimeError("failed")), "EVENT_CLEANUP_FAILED"),
])
def test_post_boundary_safety_failure_blocks_inspection_even_with_unknown_result(error, code):
    driver = RecoveryDriver()

    def verify(*_, **_kwargs):
        raise error

    driver.verify_sent = verify
    result = make_engine(driver).run(make_request(), TaskControl(), lambda *_: None)

    assert result["unknown"] == 1
    assert result["health"]["sessionReady"] is False
    assert result["health"]["reasonCode"] == code
    assert "inspect" not in driver.order
    assert driver.sent == ["mock-only"]


def test_cleanup_exception_retains_classified_environment_reason():
    driver = RecoveryDriver()

    def finish():
        raise EventCleanupError("subscription", RuntimeError("failed"))

    driver.finish_task = finish
    result = make_engine(driver).run(make_request(), TaskControl(), lambda *_: None)

    assert result["success"] == 1
    assert result["cleanup"]["reasonCode"] == "EVENT_CLEANUP_FAILED"
    assert result["health"]["reasonCode"] == "EVENT_CLEANUP_FAILED"
    assert "inspect" not in driver.order


def test_health_watchdog_starts_before_preflight_and_deadline_includes_preflight(monkeypatch):
    from app.agent import waiters

    clock = [0.0]
    monkeypatch.setattr(waiters.time, "monotonic", lambda: clock[0])
    driver = RecoveryDriver()
    notices = []

    def snapshot():
        assert any(p.get("status") == "uia_action_started" and p.get("step") == "health"
                   for method, p in notices if method == "agent.status")
        clock[0] = 14.5
        return dict(driver.window)

    def inspect():
        driver.order.append("inspect")
        clock[0] = 15.1
        waiters.check_action_deadline()

    driver.diagnostic_snapshot = snapshot
    driver.inspect = inspect
    control = TaskControl()
    control.request_stop()
    result = make_engine(driver).run(make_request(), control, lambda m, p: notices.append((m, p)))

    assert result["health"]["reasonCode"] == "ACTION_DEADLINE_EXCEEDED"
    assert result["health"]["sessionReady"] is False
    assert driver.order.count("inspect") == 1
    starts = [p for m, p in notices if m == "agent.status"
              and p.get("status") == "uia_action_started" and p.get("step") == "health"]
    assert len(starts) == 1
