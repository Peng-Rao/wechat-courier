from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .retry import AutomationRetryError
from .waiters import DeadlineWaiter, check_action_deadline


class ActionVerificationError(RuntimeError):
    """Raised when neither a UIA pattern nor its fallback changes UI state."""


@dataclass(frozen=True)
class ActionResult:
    method: str
    verified: bool = True


def _pattern(control: Any, getter_name: str):
    check_action_deadline()
    try:
        getter = getattr(control, getter_name)
        check_action_deadline()
        pattern = getter()
        check_action_deadline()
        return pattern
    except AutomationRetryError:
        raise
    except Exception:
        check_action_deadline()
        return None


def _call_pattern(pattern: Any, method_name: str, *args) -> bool:
    check_action_deadline()
    method = getattr(pattern, method_name)
    check_action_deadline()
    try:
        result = method(*args, waitTime=0)
    except TypeError:
        check_action_deadline()
        result = method(*args)
    check_action_deadline()
    return result is not False


def _safe_attr(control: Any, name: str, default: Any = "") -> Any:
    check_action_deadline()
    try:
        value = getattr(control, name)
        check_action_deadline()
    except AutomationRetryError:
        raise
    except Exception:
        check_action_deadline()
        return default
    return default if value is None else value


def describe_control(control: Any) -> str:
    check_action_deadline()
    rectangle = _safe_attr(control, "BoundingRectangle", None)
    if rectangle is None:
        bounds = "missing"
    else:
        try:
            bounds = (
                f"({rectangle.left},{rectangle.top},"
                f"{rectangle.right},{rectangle.bottom})"
            )
        except AutomationRetryError:
            raise
        except Exception:
            check_action_deadline()
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
        pre_resolve_control: Callable[[], Any] | None = None,
        resolve_control: Callable[[], Any] | None = None,
        source_present: Callable[[], bool] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        check_action_deadline()
        if pre_resolve_control is not None:
            try:
                fresh_control = pre_resolve_control()
                check_action_deadline()
            except AutomationRetryError:
                raise
            except Exception as exc:
                check_action_deadline()
                raise ActionVerificationError(
                    f"action={method_label}; pre-action control re-resolution "
                    f"failed: {exc}; {describe_control(control)}"
                ) from exc
            if fresh_control is None:
                raise ActionVerificationError(
                    f"action={method_label}; pre-action control re-resolution "
                    f"returned no control; {describe_control(control)}"
                )
            control = fresh_control

        def verified() -> bool:
            check_action_deadline()
            result = bool(postcondition())
            check_action_deadline()
            if result and extra_postcondition is not None:
                result = bool(extra_postcondition())
                check_action_deadline()
            return result

        pattern = _pattern(control, getter)
        pattern_attempted = False
        if pattern is not None:
            pattern_attempted = True
            try:
                invoked = _call_pattern(pattern, method)
            except AutomationRetryError:
                raise
            except Exception:
                check_action_deadline()
                invoked = False
            if invoked and self.waiter.wait(
                verified, self.timeout, wake_event=wake_event
            ):
                return ActionResult(method_label)

        if pattern_attempted and source_present is not None:
            try:
                check_action_deadline()
                still_present = bool(source_present())
                check_action_deadline()
            except AutomationRetryError:
                raise
            except Exception as exc:
                check_action_deadline()
                raise ActionVerificationError(
                    f"action={method_label}; source-presence check failed: {exc}; "
                    f"{describe_control(control)}"
                ) from exc
            if not still_present:
                if self.waiter.wait(verified, self.timeout, wake_event=wake_event):
                    return ActionResult(f"{method_label}_transition")
                raise ActionVerificationError(
                    f"action={method_label}; source control disappeared but target "
                    f"state was not established; {describe_control(control)}"
                )

        fallback_control = control
        if resolve_control is not None:
            try:
                check_action_deadline()
                fallback_control = resolve_control()
                check_action_deadline()
            except AutomationRetryError:
                raise
            except Exception as exc:
                check_action_deadline()
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
            check_action_deadline()
            self.click_fallback(fallback_control)
            check_action_deadline()
        except AutomationRetryError:
            raise
        except Exception as exc:
            check_action_deadline()
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
        pre_resolve_control: Callable[[], Any] | None = None,
        resolve_control: Callable[[], Any] | None = None,
        source_present: Callable[[], bool] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetInvokePattern",
            method="Invoke",
            method_label="invoke_pattern",
            postcondition=postcondition,
            pre_resolve_control=pre_resolve_control,
            resolve_control=resolve_control,
            source_present=source_present,
            extra_postcondition=extra_postcondition,
            wake_event=wake_event,
        )

    def select(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        pre_resolve_control: Callable[[], Any] | None = None,
        resolve_control: Callable[[], Any] | None = None,
        source_present: Callable[[], bool] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        return self._activate(
            control,
            getter="GetSelectionItemPattern",
            method="Select",
            method_label="selection_item_pattern",
            postcondition=postcondition,
            pre_resolve_control=pre_resolve_control,
            resolve_control=resolve_control,
            source_present=source_present,
            extra_postcondition=extra_postcondition,
            wake_event=wake_event,
        )

    def click(
        self,
        control: Any,
        postcondition: Callable[[], bool],
        *,
        pre_resolve_control: Callable[[], Any] | None = None,
        extra_postcondition: Callable[[], bool] | None = None,
        wake_event=None,
    ) -> ActionResult:
        """Perform one bounds click on a freshly resolved control.

        This deliberately has no automatic replay path. It is used for known
        false-positive InvokePattern controls where a real click is required.
        """
        check_action_deadline()
        if pre_resolve_control is not None:
            try:
                fresh_control = pre_resolve_control()
                check_action_deadline()
            except AutomationRetryError:
                raise
            except Exception as exc:
                check_action_deadline()
                raise ActionVerificationError(
                    "action=uia_bounds_click; pre-action control re-resolution "
                    f"failed: {exc}; {describe_control(control)}"
                ) from exc
            if fresh_control is None:
                raise ActionVerificationError(
                    "action=uia_bounds_click; pre-action control re-resolution "
                    f"returned no control; {describe_control(control)}"
                )
            control = fresh_control
        try:
            check_action_deadline()
            self.click_fallback(control)
            check_action_deadline()
        except AutomationRetryError:
            raise
        except Exception as exc:
            check_action_deadline()
            raise ActionVerificationError(
                f"action=uia_bounds_click failed: {exc}; {describe_control(control)}"
            ) from exc

        def verified() -> bool:
            check_action_deadline()
            result = bool(postcondition())
            check_action_deadline()
            if result and extra_postcondition is not None:
                result = bool(extra_postcondition())
                check_action_deadline()
            return result

        if self.waiter.wait(verified, self.timeout, wake_event=wake_event):
            return ActionResult("uia_bounds_click")
        raise ActionVerificationError(
            "action=uia_bounds_click did not satisfy its postcondition; "
            + describe_control(control)
        )

    @staticmethod
    def read_text(control: Any) -> str | None:
        value_pattern = _pattern(control, "GetValuePattern")
        if value_pattern is not None:
            try:
                value = str(value_pattern.Value)
                check_action_deadline()
                return value
            except AutomationRetryError:
                raise
            except Exception:
                check_action_deadline()
                pass
        text_pattern = _pattern(control, "GetTextPattern")
        if text_pattern is not None:
            try:
                document_range = text_pattern.DocumentRange
                check_action_deadline()
                value = str(document_range.GetText(-1))
                check_action_deadline()
                return value
            except AutomationRetryError:
                raise
            except Exception:
                check_action_deadline()
                pass
        return None

    def set_text(self, control: Any, value: str, *, wake_event=None) -> ActionResult:
        pattern = _pattern(control, "GetValuePattern")
        if pattern is not None:
            try:
                read_only = bool(pattern.IsReadOnly)
                check_action_deadline()
            except AutomationRetryError:
                raise
            except Exception:
                check_action_deadline()
                read_only = True
            if not read_only:
                try:
                    changed = _call_pattern(pattern, "SetValue", value)
                except AutomationRetryError:
                    raise
                except Exception:
                    check_action_deadline()
                    changed = False
                if changed and self.waiter.wait(
                    lambda: self.read_text(control) == value,
                    self.timeout,
                    wake_event=wake_event,
                ):
                    return ActionResult("value_pattern")

        try:
            check_action_deadline()
            self.replace_text_fallback(control, value)
            check_action_deadline()
        except AutomationRetryError:
            raise
        except Exception as exc:
            check_action_deadline()
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
