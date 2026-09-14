from __future__ import annotations

import ctypes
import threading
from typing import Any

from .retry import AutomationRetryError
from .waiters import check_action_deadline


class EventCleanupError(AutomationRetryError):
    code = "EVENT_CLEANUP_FAILED"

    def __init__(self, subscription, cause):
        super().__init__(f"UIA event retirement failed: {cause}")
        self.subscription = subscription


class UIAEventSubscription:
    """Owns UIA event handlers and removes exactly those handlers on close."""

    def __init__(
        self,
        *,
        api,
        element,
        scope: int,
        structure_handler,
        focus_handler,
        property_handler,
        property_ids: tuple[int, ...],
    ):
        self._api = api
        self._element = element
        self._structure_handler = structure_handler
        self._focus_handler = focus_handler
        self._property_handler = property_handler
        self._closed = False
        self._structure_registered = False
        self._focus_registered = False
        self._property_registered = False
        property_array = (ctypes.c_int * len(property_ids))(*property_ids)
        try:
            check_action_deadline()
            api.AddStructureChangedEventHandler(
                element, scope, None, structure_handler
            )
            self._structure_registered = True
            check_action_deadline()
            api.AddFocusChangedEventHandler(None, focus_handler)
            self._focus_registered = True
            check_action_deadline()
            api.AddPropertyChangedEventHandlerNativeArray(
                element,
                scope,
                None,
                property_handler,
                property_array,
                len(property_ids),
            )
            self._property_registered = True
            check_action_deadline()
        except Exception:
            try:
                self.close()
            except Exception as cleanup_error:
                raise EventCleanupError(self, cleanup_error) from cleanup_error
            raise

    def close(self) -> None:
        if self._closed:
            return
        removals = (
            (
                "_property_registered",
                self._api.RemovePropertyChangedEventHandler,
                (self._element, self._property_handler),
            ),
            (
                "_structure_registered",
                self._api.RemoveStructureChangedEventHandler,
                (self._element, self._structure_handler),
            ),
            (
                "_focus_registered",
                self._api.RemoveFocusChangedEventHandler,
                (self._focus_handler,),
            ),
        )
        errors = []
        for flag_name, remove, arguments in removals:
            if not getattr(self, flag_name):
                continue
            try:
                check_action_deadline()
                remove(*arguments)
            except Exception as exc:
                errors.append(exc)
            else:
                setattr(self, flag_name, False)
        self._closed = not any(
            (
                self._property_registered,
                self._structure_registered,
                self._focus_registered,
            )
        )
        if errors:
            raise EventCleanupError(self, errors[0]) from errors[0]


def subscribe_uia_events(uia_module, root, wake_event: threading.Event):
    """Subscribe when the provider supports events; callers retain polling fallback."""

    import comtypes

    client = uia_module._AutomationClient.instance()
    core = client.UIAutomationCore

    class StructureHandler(comtypes.COMObject):
        _com_interfaces_ = [core.IUIAutomationStructureChangedEventHandler]

        def HandleStructureChangedEvent(self, *_args):
            wake_event.set()
            return 0

    class FocusHandler(comtypes.COMObject):
        _com_interfaces_ = [core.IUIAutomationFocusChangedEventHandler]

        def HandleFocusChangedEvent(self, *_args):
            wake_event.set()
            return 0

    class PropertyHandler(comtypes.COMObject):
        _com_interfaces_ = [core.IUIAutomationPropertyChangedEventHandler]

        def HandlePropertyChangedEvent(self, *_args):
            wake_event.set()
            return 0

    return UIAEventSubscription(
        api=client.IUIAutomation,
        element=root.Element,
        scope=int(core.TreeScope_Subtree),
        structure_handler=StructureHandler(),
        focus_handler=FocusHandler(),
        property_handler=PropertyHandler(),
        property_ids=(
            int(uia_module.PropertyId.NameProperty),
            int(uia_module.PropertyId.ValueValueProperty),
        ),
    )


__all__ = ["EventCleanupError", "UIAEventSubscription", "subscribe_uia_events"]
