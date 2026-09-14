from types import SimpleNamespace as NS

import pytest

from app.agent.actions import VerifiedActions, _call_pattern
from app.agent.retry import AutomationRetryError, WeixinUnresponsiveError
from app.agent.waiters import ActionDeadlineExceeded, action_deadline


@pytest.fixture
def action_state(monkeypatch):
    events = []
    actions = VerifiedActions(
        waiter=NS(wait=lambda predicate, *args, **kwargs: predicate()),
        click_fallback=lambda *args: events.append("click"),
        replace_text_fallback=lambda *args: events.append("keyboard"),
    )
    monkeypatch.setattr(
        "app.agent.actions.describe_control",
        lambda control: events.append("describe") or "control",
    )
    return actions, events


@pytest.mark.parametrize("error_type", [AutomationRetryError, WeixinUnresponsiveError, ActionDeadlineExceeded])
@pytest.mark.parametrize("stage", [
    "invoke_getter", "invoke_pattern", "select_getter", "select_pattern",
    "invoke_pre_resolve", "invoke_resolve", "invoke_source", "invoke_fallback",
    "click_pre_resolve", "click_fallback", "set_getter", "set_readonly",
    "set_pattern", "set_fallback", "read_getter", "read_value", "read_range",
])
def test_stop_error_propagates_without_fallback_or_description(action_state, error_type, stage):
    actions, events = action_state
    error = error_type("stop now")

    def stop(*args, **kwargs):
        raise error

    class StopProperty:
        def __getattr__(self, name):
            raise error

    control = NS(GetInvokePattern=lambda: None, GetSelectionItemPattern=lambda: None,
                 GetValuePattern=lambda: None,
                 GetTextPattern=lambda: events.append("text_pattern"))
    kwargs = {}
    method = stage.split("_")[0]
    if stage == "invoke_getter":
        control.GetInvokePattern = stop
    elif stage == "invoke_pattern":
        control.GetInvokePattern = lambda: NS(Invoke=stop)
    elif stage == "select_getter":
        control.GetSelectionItemPattern = stop
    elif stage == "select_pattern":
        control.GetSelectionItemPattern = lambda: NS(Select=stop)
    elif stage.endswith("pre_resolve"):
        kwargs["pre_resolve_control"] = stop
    elif stage == "invoke_resolve":
        kwargs["resolve_control"] = stop
    elif stage == "invoke_source":
        control.GetInvokePattern = lambda: NS(Invoke=lambda **kwargs: False)
        kwargs["source_present"] = stop
    elif stage in {"invoke_fallback", "click_fallback"}:
        actions.click_fallback = stop
    elif stage in {"set_getter", "read_getter"}:
        control.GetValuePattern = stop
    elif stage in {"set_readonly", "read_value"}:
        control.GetValuePattern = lambda: StopProperty()
    elif stage == "set_pattern":
        control.GetValuePattern = lambda: NS(IsReadOnly=False, SetValue=stop)
    elif stage == "set_fallback":
        actions.replace_text_fallback = stop
    elif stage == "read_range":
        control.GetTextPattern = lambda: StopProperty()

    with pytest.raises(error_type) as raised:
        if method == "read":
            actions.read_text(control)
        elif method == "set":
            actions.set_text(control, "new")
        else:
            getattr(actions, method)(control, lambda: True, **kwargs)
    assert raised.value is error
    assert events == []


@pytest.mark.parametrize("method", ["invoke", "select", "click", "set_text", "read_text"])
def test_expired_deadline_prevents_any_control_access(action_state, monkeypatch, method):
    actions, events = action_state
    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])

    class Untouchable:
        def __getattr__(self, name):
            events.append(name)
            return lambda: None

    with action_deadline(1):
        now[0] = 2.0
        with pytest.raises(ActionDeadlineExceeded):
            if method == "read_text":
                actions.read_text(Untouchable())
            elif method == "set_text":
                actions.set_text(Untouchable(), "value")
            else:
                getattr(actions, method)(Untouchable(), lambda: True)
        now[0] = 0.5
    assert events == []


@pytest.mark.parametrize("method", ["invoke", "select", "click", "set_text", "read_text"])
def test_deadline_expiring_during_resolution_prevents_fallback(action_state, monkeypatch, method):
    actions, events = action_state
    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])

    def expire():
        now[0] = 2.0
        return None

    control = NS(GetInvokePattern=expire, GetSelectionItemPattern=expire,
                 GetValuePattern=expire, GetTextPattern=lambda: events.append("text_pattern"))
    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            if method == "read_text":
                actions.read_text(control)
            elif method == "set_text":
                actions.set_text(control, "new")
            elif method == "click":
                actions.click(control, lambda: True, pre_resolve_control=lambda: expire() or control)
            else:
                getattr(actions, method)(control, lambda: True)
        now[0] = 0.5
    assert events == []


def test_signature_fallback_rechecks_deadline(monkeypatch):
    now = [0.0]
    attempts = []
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])

    def invoke(**kwargs):
        attempts.append(kwargs)
        now[0] = 2.0
        raise TypeError("signature rejected after deadline")

    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            _call_pattern(NS(Invoke=invoke), "Invoke")
        now[0] = 0.5
    assert attempts == [{"waitTime": 0}]
