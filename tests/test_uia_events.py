from __future__ import annotations

from app.agent.uia_events import UIAEventSubscription


class FakeAutomation:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))

        return call


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
