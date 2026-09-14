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


def _safe_attr(control: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(control, name)
    except Exception:
        return default
    return default if value is None else value


def describe_control(control: Any) -> str:
    rectangle = _safe_attr(control, "BoundingRectangle", None)
    if rectangle is None:
        bounds = "missing"
    else:
        try:
            bounds = (
                f"({rectangle.left},{rectangle.top},"
                f"{rectangle.right},{rectangle.bottom})"
            )
        except Exception:
            bounds = "unreadable"
    return (
        f"ControlType={_safe_attr(control, 'ControlTypeName')!r}, "
        f"ClassName={_safe_attr(control, 'ClassName')!r}, "
        f"AutomationId={_safe_attr(control, 'AutomationId')!r}, "
        f"enabled={bool(_safe_attr(control, 'IsEnabled', False))}, "
        f"offscreen={bool(_safe_attr(control, 'IsOffscreen', True))}, "
        f"bounds={bounds}"
    )


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
        resolve_control: Callable[[], Any] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        def verified() -> bool:
            return bool(postcondition()) and (
                extra_postcondition is None or bool(extra_postcondition())
            )

        pattern = _pattern(control, getter)
        if pattern is not None:
            try:
                invoked = _call_pattern(pattern, method)
            except Exception:
                invoked = False
            if invoked and self.waiter.wait(
                verified, self.timeout, wake_event=wake_event
            ):
                return ActionResult(method_label)

        fallback_control = control
        if resolve_control is not None:
            try:
                fallback_control = resolve_control()
            except Exception as exc:
                raise ActionVerificationError(
                    f"action={method_label}; control re-resolution failed: {exc}; "
                    f"{describe_control(control)}"
                ) from exc
            if fallback_control is None:
                raise ActionVerificationError(
                    f"action={method_label}; control re-resolution returned no control; "
                    f"{describe_control(control)}"
                )
        try:
            self.click_fallback(fallback_control)
        except Exception as exc:
            raise ActionVerificationError(
                f"action={method_label}; click fallback failed: {exc}; "
                f"{describe_control(fallback_control)}"
            ) from exc
        if self.waiter.wait(verified, self.timeout, wake_event=wake_event):
            return ActionResult("uia_bounds_click")
        condition_label = (
            "postcondition and extra postcondition"
            if extra_postcondition
            else "postcondition"
        )
        raise ActionVerificationError(
            f"action={method_label}; pattern and click did not satisfy the "
            f"{condition_label}; {describe_control(fallback_control)}"
        )

    def invoke(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        resolve_control: Callable[[], Any] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetInvokePattern",
            method="Invoke",
            method_label="invoke_pattern",
            postcondition=postcondition,
            resolve_control=resolve_control,
            extra_postcondition=extra_postcondition,
            wake_event=wake_event,
        )

    def select(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        resolve_control: Callable[[], Any] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetSelectionItemPattern",
            method="Select",
            method_label="selection_item_pattern",
            postcondition=postcondition,
            resolve_control=resolve_control,
            extra_postcondition=extra_postcondition,
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

        try:
            self.replace_text_fallback(control, value)
        except Exception as exc:
            raise ActionVerificationError(
                f"action=set_text; keyboard fallback failed: {exc}; "
                f"{describe_control(control)}"
            ) from exc
        if self.waiter.wait(
            lambda: self.read_text(control) == value,
            self.timeout,
            wake_event=wake_event,
        ):
            return ActionResult("keyboard_fallback")
        raise ActionVerificationError(
            "action=set_text; text input did not match after verified fallback; "
            + describe_control(control)
        )


__all__ = [
    "ActionResult",
    "ActionVerificationError",
    "VerifiedActions",
    "describe_control",
]
