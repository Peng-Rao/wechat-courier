from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.native_driver import NativeWeixinDriver
from app.agent.runtime import TaskControl
from app.agent.workflows import RiskControlError, WeixinWorkflowEngine
from tests.test_agent_workflows import FakeDriver


class RiskQuery:
    def __init__(self, controls):
        self.controls = controls
        self.calls = []

    def find_all(self, root, **options):
        self.calls.append(options)
        return [control for control in self.controls
                if (options.get("name") is None or control.Name in options["name"])
                and (not options.get("control_types") or control.ControlTypeName in options["control_types"])]


def scoped_driver(hwnd=2):
    warning = SimpleNamespace(Name="你添加好友的操作过于频繁，请稍后再试", ControlTypeName="TextControl", ClassName="mmui::XLabel", AutomationId="risk_tip")
    driver = NativeWeixinDriver.__new__(NativeWeixinDriver)
    driver._session = SimpleNamespace(hwnd=1)
    driver._root = SimpleNamespace(Name="微信", ClassName="mmui::MainWindow", AutomationId="main")
    driver._query = RiskQuery([warning])
    driver.ensure_window_responsive = lambda *args: True
    driver._control_root = lambda *args: driver._root if hwnd == 1 else SimpleNamespace(ClassName="mmui::AddFriendWindow")
    return driver


def test_scoped_frequency_matching_accepts_long_visible_hint():
    driver = scoped_driver()
    with pytest.raises(RiskControlError) as caught:
        driver._raise_scoped_risk(hwnd=2)
    assert getattr(caught.value, "risk_kind", "") == "friend_frequency"
    assert all("name" not in options for options in driver._query.calls)


def test_main_chat_text_does_not_trigger_frequency_stop():
    driver = scoped_driver(hwnd=1)
    driver._raise_scoped_risk(hwnd=1)
    assert not any("TextControl" in options.get("control_types", ()) for options in driver._query.calls)


def test_search_popup_contact_text_is_not_a_risk_hint():
    driver = scoped_driver()
    popup = SimpleNamespace(ClassName="mmui::XPopover", AutomationId="search_list")
    driver._raise_scoped_risk(hwnd=2, root=popup)
    assert not any("TextControl" in options.get("control_types", ()) for options in driver._query.calls)


@pytest.mark.parametrize("action", ["bind_window", "open_add_friend", "set_friend_account",
    "search_friend", "profile_account", "open_friend_request", "set_friend_fields", "cancel_friend_request"])
def test_risk_in_every_preflight_stage_stops_without_retry_or_next_wait(action):
    driver = FakeDriver()
    calls = []
    def blocked(*args, **kwargs):
        calls.append(action)
        error = RiskControlError("添加好友操作过于频繁，请稍后重试")
        error.risk_kind = "friend_frequency"
        raise error
    setattr(driver, action, blocked)
    driver.finish_task = lambda: {"success": False, "reasonCode": "CLEANUP_FAILED"}
    events = []
    request = TaskRequest("risk", "friend_add", (TaskItem("one", account="wxid_first"),
        TaskItem("two", account="wxid_second")), TaskOptions(interval_min=15, interval_max=30))
    result = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None).run(
        request, TaskControl(), lambda method, event: events.append((method, event)))
    risk = [event for method, event in events if method == "task.event" and event.get("errorCode") == "RISK_CONTROL"]
    assert len(risk) == 1 and risk[0]["riskKind"] == "friend_frequency"
    assert calls == [action]
    assert result["done"] == 1 and result["outcome"] == "error"
    assert result["cleanup"]["success"] is False
    assert not any(event.get("status") == "waiting" for _, event in events)
    assert not any(event.get("itemId") == "two" for _, event in events)
    assert driver.friend_submit_count == 0


def test_frequency_during_stale_refresh_keeps_original_category():
    from app.agent.retry import StaleElementError
    driver = FakeDriver()
    def stale():
        raise StaleElementError("proxy stale")
    def blocked():
        error = RiskControlError("操作过于频繁")
        error.risk_kind = "friend_frequency"
        raise error
    driver.bind_window = stale
    driver.soft_refresh_session = blocked
    events = []
    request = TaskRequest("refresh", "friend_add", (TaskItem("one", account="wxid_first"),))
    result = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None).run(
        request, TaskControl(), lambda method, event: events.append((method, event)))
    risk = [event for method, event in events if method == "task.event" and event.get("errorCode") == "RISK_CONTROL"]
    assert result["done"] == 1
    assert risk[-1].get("riskKind") == "friend_frequency"


@pytest.mark.parametrize("triggered", [False, True, None])
def test_frequency_at_submit_stops_batch_and_preserves_boundary(triggered):
    driver = FakeDriver()
    def blocked():
        error = RiskControlError("操作过于频繁，请稍后再试")
        error.risk_kind = "friend_frequency"
        error.destructive_triggered = triggered
        raise error
    driver.submit_friend_request = blocked
    events = []
    request = TaskRequest("submit-risk", "friend_add", (TaskItem("one", account="wxid_first"),
        TaskItem("two", account="wxid_second")), TaskOptions(submit_friend_request=True, interval_min=15, interval_max=30))
    result = WeixinWorkflowEngine(driver_factory=lambda: driver, friend_submit_enabled=True, sleep=lambda _: None).run(
        request, TaskControl(), lambda method, event: events.append((method, event)))
    failures = [event for method, event in events if method == "task.event" and event.get("errorCode") == "RISK_CONTROL"]
    assert result["done"] == 1
    assert len(failures) == 1 and failures[0]["riskKind"] == "friend_frequency"
    assert failures[0]["outcome"] == ("error" if triggered is False else "unknown")
    assert not any(event.get("status") == "waiting" for _, event in events)
    assert not any(event.get("itemId") == "two" for _, event in events)


def test_atomic_safe_point_acknowledges_pause_outside_condition_lock():
    import threading
    control = TaskControl()
    control.pause()
    acknowledged = threading.Event()
    result = []
    def before_wait():
        # RPC must remain able to acquire the condition while UIA cleanup runs.
        stopper = threading.Thread(target=control.request_stop)
        stopper.start()
        stopper.join(1)
        assert not stopper.is_alive()
        acknowledged.set()
    worker = threading.Thread(target=lambda: result.append(control.wait_at_safe_point(before_wait)))
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert acknowledged.is_set()
    assert result == [False]


def test_resume_then_immediate_pause_has_a_new_acknowledgement():
    import threading
    control = TaskControl()
    control.pause()
    acknowledgements = []
    result = []
    def acknowledge():
        acknowledgements.append(len(acknowledgements) + 1)
        control.resume()
        if len(acknowledgements) == 1:
            control.pause()
    worker = threading.Thread(target=lambda: result.append(control.wait_at_safe_point(acknowledge)))
    worker.start()
    worker.join(1)
    if worker.is_alive():
        control.request_stop()
        worker.join(1)
    assert result == [True]
    assert acknowledgements == [1, 2]


def test_frequency_stops_before_next_item_and_preserves_category():
    driver = FakeDriver()
    def blocked():
        error = RiskControlError("你添加好友的操作过于频繁，请稍后再试")
        error.risk_kind = "friend_frequency"
        raise error
    driver.open_add_friend = blocked
    events = []
    request = TaskRequest("task", "friend_add", (TaskItem("one", account="wxid_first"), TaskItem("two", account="wxid_second")), TaskOptions())
    result = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None).run(request, TaskControl(), lambda method, event: events.append((method, event)))
    failures = [event for method, event in events if method == "task.event" and event.get("errorCode") == "RISK_CONTROL"]
    assert result["done"] == 1
    assert driver.friend_submit_count == 0
    assert len(failures) == 1
    assert failures[0].get("riskKind") == "friend_frequency"
    assert not any(event.get("itemId") == "two" for method, event in events if method == "task.event")
    assert not any(event.get("status") == "waiting" for method, event in events)


def test_first_failed_event_reports_preparation_elapsed(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("app.clocks.time.monotonic", lambda: now[0])
    driver = FakeDriver()
    def missing():
        now[0] += 2.5
        return False
    driver.ensure_search_ready = missing
    events = []
    request = TaskRequest("task", "message_send", (TaskItem("one", target="Alice", message="hi"),))
    WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda delay: now.__setitem__(0, now[0] + delay)).run(request, TaskControl(), lambda method, event: events.append((method, event)))
    failures = [event for method, event in events if method == "task.event" and event.get("outcome") == "error"]
    assert failures
    assert failures[0].get("itemElapsedMs", 0) >= 7500
