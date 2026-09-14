from __future__ import annotations

import threading

import pytest

from app.agent.actions import ActionVerificationError, VerifiedActions
from app.agent.waiters import DeadlineWaiter


class ImmediateWaiter:
    def wait(self, predicate, timeout, wake_event=None):
        return bool(predicate())


class FakePattern:
    def __init__(self, callback=None, value=""):
        self.callback = callback or (lambda: None)
        self.Value = value
        self.IsReadOnly = False

    def Invoke(self, **_kwargs):
        self.callback()
        return True

    def Select(self, **_kwargs):
        self.callback()
        return True

    def SetValue(self, value, **_kwargs):
        self.Value = value
        self.callback()
        return True


class FakeControl:
    def __init__(self, *, invoke=None, selection=None, value=None, name=""):
        self._invoke = invoke
        self._selection = selection
        self._value = value
        self.Name = name
        self.ControlTypeName = "ListItemControl"
        self.ClassName = "mmui::SearchContentCellView"
        self.AutomationId = "search_item_1"
        self.IsEnabled = True
        self.IsOffscreen = False
        self.BoundingRectangle = None

    def GetInvokePattern(self):
        return self._invoke

    def GetSelectionItemPattern(self):
        return self._selection

    def GetValuePattern(self):
        return self._value


def test_invoke_pattern_is_preferred_when_postcondition_passes():
    state = {"opened": False}
    control = FakeControl(
        invoke=FakePattern(lambda: state.__setitem__("opened", True))
    )
    fallbacks = []
    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda item: fallbacks.append(item),
        replace_text_fallback=lambda item, value: None,
    )

    result = actions.invoke(control, lambda: state["opened"])

    assert result.method == "invoke_pattern"
    assert fallbacks == []


def test_selection_falls_back_only_after_pattern_postcondition_fails():
    state = {"selected": False}
    control = FakeControl(selection=FakePattern())
    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda _item: state.__setitem__("selected", True),
        replace_text_fallback=lambda item, value: None,
    )

    result = actions.select(control, lambda: state["selected"])

    assert result.method == "uia_bounds_click"
    assert result.verified is True


def test_selection_re_resolves_control_before_fallback_click():
    stale = FakeControl(selection=FakePattern(), name="stale")
    fresh = FakeControl(name="fresh")
    clicked = []
    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda item: clicked.append(item.Name),
        replace_text_fallback=lambda item, value: None,
    )

    result = actions.select(
        stale,
        lambda: bool(clicked),
        resolve_control=lambda: fresh,
    )

    assert result.method == "uia_bounds_click"
    assert clicked == ["fresh"]


def test_action_requires_optional_extra_postcondition():
    control = FakeControl(invoke=FakePattern())
    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda _item: None,
        replace_text_fallback=lambda item, value: None,
    )

    with pytest.raises(ActionVerificationError, match="extra postcondition"):
        actions.invoke(control, lambda: True, extra_postcondition=lambda: False)


def test_set_text_uses_value_pattern_and_reads_it_back():
    pattern = FakePattern(value="old")
    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda item: None,
        replace_text_fallback=lambda item, value: None,
    )

    result = actions.set_text(FakeControl(value=pattern), "你好")

    assert result.method == "value_pattern"
    assert pattern.Value == "你好"


def test_set_text_uses_keyboard_fallback_and_still_requires_readback():
    pattern = FakePattern(value="old")

    def replace(_control, value):
        pattern.Value = value

    actions = VerifiedActions(
        waiter=ImmediateWaiter(),
        click_fallback=lambda item: None,
        replace_text_fallback=replace,
    )
    pattern.SetValue = lambda value, **kwargs: False

    result = actions.set_text(FakeControl(value=pattern), "new")
    assert result.method == "keyboard_fallback"

    pattern.Value = "old"
    with pytest.raises(ActionVerificationError) as raised:
        VerifiedActions(
            waiter=ImmediateWaiter(),
            click_fallback=lambda item: None,
            replace_text_fallback=lambda item, value: None,
        ).set_text(FakeControl(value=pattern), "never-applied")
    assert "action=set_text" in str(raised.value)
    assert "ControlType='ListItemControl'" in str(raised.value)
    assert "AutomationId='search_item_1'" in str(raised.value)


def test_deadline_waiter_can_be_woken_by_an_event():
    event = threading.Event()
    state = {"ready": False}

    def make_ready():
        state["ready"] = True
        event.set()

    timer = threading.Timer(0.02, make_ready)
    timer.start()
    try:
        assert DeadlineWaiter(poll_interval=0.2).wait(
            lambda: state["ready"], timeout=0.5, wake_event=event
        )
    finally:
        timer.cancel()
