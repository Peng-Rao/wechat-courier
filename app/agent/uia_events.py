from __future__ import annotations

import ctypes
import threading
from typing import Any


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
        property_array = (ctypes.c_int * len(property_ids))(*property_ids)
        try:
            api.AddStructureChangedEventHandler(
                element, scope, None, structure_handler
            )
            api.AddFocusChangedEventHandler(None, focus_handler)
            api.AddPropertyChangedEventHandlerNativeArray(
                element,
                scope,
                None,
                property_handler,
                property_array,
                len(property_ids),
            )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        removals = (
            (
                self._api.RemovePropertyChangedEventHandler,
                (self._element, self._property_handler),
            ),
            (
                self._api.RemoveStructureChangedEventHandler,
                (self._element, self._structure_handler),
            ),
            (self._api.RemoveFocusChangedEventHandler, (self._focus_handler,)),
        )
        for remove, arguments in removals:
            try:
                remove(*arguments)
            except Exception:
                pass


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


__all__ = ["UIAEventSubscription", "subscribe_uia_events"]
