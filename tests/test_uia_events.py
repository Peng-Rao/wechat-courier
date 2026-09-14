from __future__ import annotations

import pytest

from app.agent import uia_events, waiters
from app.agent.uia_events import UIAEventSubscription


class FakeAutomation:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))

        return call


def test_partial_registration_cleanup_failure_retains_subscription():
    class BrokenAutomation(FakeAutomation):
        def AddFocusChangedEventHandler(self, *_args):
            raise RuntimeError("registration failed")

        def RemoveStructureChangedEventHandler(self, *_args):
            raise RuntimeError("retirement failed")

    with pytest.raises(RuntimeError) as raised:
        UIAEventSubscription(
            api=BrokenAutomation(), element="root", scope=4,
            structure_handler="structure", focus_handler="focus",
            property_handler="property", property_ids=(30005,),
        )
    error = raised.value
    assert getattr(error, "code", None) == "EVENT_CLEANUP_FAILED"
    assert error.recoverable is False
    assert error.subscription._structure_registered


def test_event_registration_does_not_continue_after_shared_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(waiters.time, "monotonic", lambda: clock[0])

    class SlowAutomation(FakeAutomation):
        def AddStructureChangedEventHandler(self, *_args):
            self.calls.append(("structure", _args))
            clock[0] = 16.0

    api = SlowAutomation()
    with pytest.raises(RuntimeError) as raised:
        with waiters.action_deadline():
            UIAEventSubscription(
                api=api, element="root", scope=4,
                structure_handler="structure", focus_handler="focus",
                property_handler="property", property_ids=(30005,),
            )
    assert getattr(raised.value, "code", None) == "EVENT_CLEANUP_FAILED"
    assert [name for name, _ in api.calls] == ["structure"]
    # The owner can retire the retained handler in a fresh cleanup deadline.
    with waiters.action_deadline():
        raised.value.subscription.close()
    assert api.calls[-1][0] == "RemoveStructureChangedEventHandler"


def test_uia_event_subscription_adds_and_removes_all_wake_handlers():
    api = FakeAutomation()
    handlers = [object(), object(), object()]
    subscription = UIAEventSubscription(
        api=api,
        element="root-element",
        scope=4,
        structure_handler=handlers[0],
        focus_handler=handlers[1],
        property_handler=handlers[2],
        property_ids=(30005, 30045),
    )

    assert [name for name, _args in api.calls[:3]] == [
        "AddStructureChangedEventHandler",
        "AddFocusChangedEventHandler",
        "AddPropertyChangedEventHandlerNativeArray",
    ]

    subscription.close()
    subscription.close()

    assert [name for name, _args in api.calls[3:]] == [
        "RemovePropertyChangedEventHandler",
        "RemoveStructureChangedEventHandler",
        "RemoveFocusChangedEventHandler",
    ]


def test_partial_subscription_removes_only_handlers_that_were_registered():
    class PartialAutomation(FakeAutomation):
        def AddFocusChangedEventHandler(self, *_args):
            self.calls.append(("AddFocusChangedEventHandler", _args))
            raise RuntimeError("focus registration failed")

    api = PartialAutomation()

    try:
        UIAEventSubscription(
            api=api,
            element="root-element",
            scope=4,
            structure_handler="structure",
            focus_handler="focus",
            property_handler="property",
            property_ids=(30005,),
        )
    except RuntimeError as exc:
        assert "focus registration failed" in str(exc)
    else:
        raise AssertionError("partial registration should fail")

    assert [name for name, _args in api.calls] == [
        "AddStructureChangedEventHandler",
        "AddFocusChangedEventHandler",
        "RemoveStructureChangedEventHandler",
    ]


def test_subscription_retries_only_a_handler_that_failed_to_unregister():
    class RetryAutomation(FakeAutomation):
        def __init__(self):
            super().__init__()
            self.property_removals = 0

        def RemovePropertyChangedEventHandler(self, *args):
            self.calls.append(("RemovePropertyChangedEventHandler", args))
            self.property_removals += 1
            if self.property_removals == 1:
                raise RuntimeError("provider busy")

    api = RetryAutomation()
    subscription = UIAEventSubscription(
        api=api,
        element="root-element",
        scope=4,
        structure_handler="structure",
        focus_handler="focus",
        property_handler="property",
        property_ids=(30005,),
    )

    try:
        subscription.close()
    except RuntimeError as exc:
        assert "provider busy" in str(exc)
    else:
        raise AssertionError("failed removal must remain observable")

    subscription.close()
    removals = [name for name, _args in api.calls if name.startswith("Remove")]
    assert removals == [
        "RemovePropertyChangedEventHandler",
        "RemoveStructureChangedEventHandler",
        "RemoveFocusChangedEventHandler",
        "RemovePropertyChangedEventHandler",
    ]
