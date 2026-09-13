from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .waiters import DeadlineWaiter


class ActionVerificationError(RuntimeError):
    """Raised when neither a UIA pattern nor its fallback changes UI state."""


@dataclass(frozen=True)
class ActionResult:
    method: str
    verified: bool = True


def _pattern(control: Any, getter_name: str):
    try:
        return getattr(control, getter_name)()
    except Exception:
        return None


def _call_pattern(pattern: Any, method_name: str, *args) -> bool:
    method = getattr(pattern, method_name)
    try:
        result = method(*args, waitTime=0)
    except TypeError:
        result = method(*args)
    return result is not False


class VerifiedActions:
    """Pattern-first UIA actions with mandatory postcondition checks."""

    def __init__(
        self,
        *,
        click_fallback: Callable[[Any], None],
        replace_text_fallback: Callable[[Any, str], None],
        waiter: DeadlineWaiter | None = None,
        timeout: float = 2.0,
    ):
        self.waiter = waiter or DeadlineWaiter()
        self.click_fallback = click_fallback
        self.replace_text_fallback = replace_text_fallback
        self.timeout = timeout

    def _activate(
        self,
        control: Any,
        *,
        getter: str,
        method: str,
        method_label: str,
        postcondition: Callable[[], bool],
        wake_event=None,
    ) -> ActionResult:
        pattern = _pattern(control, getter)
        if pattern is not None:
            try:
                invoked = _call_pattern(pattern, method)
            except Exception:
                invoked = False
            if invoked and self.waiter.wait(
                postcondition, self.timeout, wake_event=wake_event
            ):
                return ActionResult(method_label)

        self.click_fallback(control)
        if self.waiter.wait(postcondition, self.timeout, wake_event=wake_event):
            return ActionResult("uia_bounds_click")
        raise ActionVerificationError(
            f"{method_label} and UIA-bounds click did not satisfy the postcondition"
        )

    def invoke(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetInvokePattern",
            method="Invoke",
            method_label="invoke_pattern",
            postcondition=postcondition,
            wake_event=wake_event,
        )

    def select(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetSelectionItemPattern",
            method="Select",
            method_label="selection_item_pattern",
            postcondition=postcondition,
            wake_event=wake_event,
        )

    @staticmethod
    def read_text(control: Any) -> str | None:
        value_pattern = _pattern(control, "GetValuePattern")
        if value_pattern is not None:
            try:
                return str(value_pattern.Value)
            except Exception:
                pass
        text_pattern = _pattern(control, "GetTextPattern")
        if text_pattern is not None:
            try:
                document_range = text_pattern.DocumentRange
                return str(document_range.GetText(-1))
            except Exception:
                pass
        return None

    def set_text(self, control: Any, value: str, *, wake_event=None) -> ActionResult:
        pattern = _pattern(control, "GetValuePattern")
        if pattern is not None:
            try:
                read_only = bool(pattern.IsReadOnly)
            except Exception:
                read_only = True
            if not read_only:
                try:
                    changed = _call_pattern(pattern, "SetValue", value)
                except Exception:
                    changed = False
                if changed and self.waiter.wait(
                    lambda: self.read_text(control) == value,
                    self.timeout,
                    wake_event=wake_event,
                ):
                    return ActionResult("value_pattern")

        self.replace_text_fallback(control, value)
        if self.waiter.wait(
            lambda: self.read_text(control) == value,
            self.timeout,
            wake_event=wake_event,
        ):
            return ActionResult("keyboard_fallback")
        raise ActionVerificationError("text input did not match after verified fallback")


__all__ = ["ActionResult", "ActionVerificationError", "VerifiedActions"]
