"""Live UIA preflights that stop before every destructive boundary.

The message path only opens and verifies a chat. The friend path may prepare
and read back a form, but reaching its exact Confirm control is terminal: the
form is cancelled and destroyed during cleanup. No send mode is provided.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent.diagnostics import (
    UiaDiagnostics,
    control_metadata,
    payload_fingerprint,
    redact_identifier,
)
from app.agent.workflows import normalize_identity


class PreflightError(RuntimeError):
    """Raised when a preflight cannot prove its non-destructive checkpoint."""


def close_friend_form(
    driver: Any,
    *,
    win32gui_module: Any = None,
    win32process_module: Any = None,
    wm_close: int | None = None,
    wait_timeout: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Request cancellation of the verification form and verify it closes."""
    if win32gui_module is None:
        import win32gui as win32gui_module
    if win32process_module is None:
        import win32process as win32process_module
    if wm_close is None:
        import win32con

        wm_close = int(win32con.WM_CLOSE)

    session = getattr(driver, "_session", None)
    profile = getattr(session, "profile", None)
    uia = getattr(driver, "_uia", None)
    try:
        expected_pid = int(getattr(session, "pid"))
        expected_class = str(getattr(profile, "verify_friend_root_class"))
    except (AttributeError, TypeError, ValueError):
        return False
    if not expected_pid or not expected_class or uia is None:
        return False

    def is_expected_window(hwnd: int) -> bool:
        if not win32gui_module.IsWindow(hwnd):
            return False
        _thread_id, pid = win32process_module.GetWindowThreadProcessId(hwnd)
        if int(pid) != expected_pid:
            return False
        root = uia.ControlFromHandle(hwnd)
        if root is None:
            raise RuntimeError("UIA root unavailable during friend-form cleanup")
        root_class_value = getattr(root, "ClassName")
        if root_class_value is None or not str(root_class_value).strip():
            raise RuntimeError(
                "UIA root class unavailable during friend-form cleanup"
            )
        return str(root_class_value) == expected_class

    def discover() -> tuple[list[int], bool]:
        handles: list[int] = []
        complete = True

        def collect(hwnd, _context):
            nonlocal complete
            try:
                if is_expected_window(int(hwnd)):
                    handles.append(int(hwnd))
            except Exception:
                complete = False
            return True

        try:
            win32gui_module.EnumWindows(collect, None)
        except Exception:
            return [], False
        return list(dict.fromkeys(handles)), complete

    handles, complete = discover()
    if not complete:
        return False
    if not handles:
        setattr(driver, "_verify_hwnd", 0)
        return True
    if len(handles) != 1:
        return False
    for hwnd in handles:
        try:
            if not is_expected_window(hwnd):
                return False
            win32gui_module.PostMessage(hwnd, wm_close, 0, 0)
        except Exception:
            return False

    def closed() -> bool:
        return all(not win32gui_module.IsWindow(hwnd) for hwnd in handles)

    if closed():
        remaining, rescan_complete = discover()
        if rescan_complete and not remaining:
            setattr(driver, "_verify_hwnd", 0)
            return True
        return False
    deadline = time.monotonic() + max(0.0, wait_timeout)
    while time.monotonic() < deadline:
        sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if closed():
            remaining, rescan_complete = discover()
            if rescan_complete and not remaining:
                setattr(driver, "_verify_hwnd", 0)
                return True
            return False
    return False


def _driver_factory(*, timeout: float):
    from app.agent.native_driver import NativeWeixinDriver

    return NativeWeixinDriver(timeout=timeout)


def _candidate_identities(candidate: Any) -> frozenset[str]:
    identities = getattr(candidate, "identities", ())
    return frozenset(
        normalized
        for value in identities
        if (normalized := normalize_identity(str(value)))
    )


def _candidate_metadata(candidate: Any) -> dict[str, Any]:
    return {
        "name": getattr(candidate, "display_name", ""),
        "type": getattr(candidate, "result_type", ""),
        "class": "",
        "automationId": getattr(candidate, "automation_id", ""),
        "runtimeId": getattr(candidate, "runtime_id", ()),
        "bounds": None,
        "visible": None,
    }


def _root_control(driver: Any) -> Any:
    return getattr(driver, "_root", None)


def _diagnostic_window(driver: Any, binding: Any) -> Any:
    if isinstance(binding, Mapping):
        restore = binding.get("windowRestore")
        if isinstance(restore, Mapping) and isinstance(
            restore.get("window"), Mapping
        ):
            return restore["window"]
    session = getattr(driver, "_session", None)
    restore_result = getattr(session, "window_restore", None)
    as_dict = getattr(restore_result, "as_dict", None)
    if callable(as_dict):
        restored = as_dict()
        if isinstance(restored, Mapping) and isinstance(
            restored.get("window"), Mapping
        ):
            return restored["window"]
    root = _root_control(driver)
    if root is None:
        return binding
    binding_hwnd = binding.get("hwnd") if isinstance(binding, Mapping) else None
    binding_pid = binding.get("pid") if isinstance(binding, Mapping) else None
    return {
        "hwnd": binding_hwnd or getattr(root, "NativeWindowHandle", None),
        "pid": binding_pid or getattr(
            getattr(driver, "_session", None), "pid", None
        ),
        "title": getattr(root, "Name", ""),
        "class": getattr(root, "ClassName", ""),
        "bounds": getattr(root, "BoundingRectangle", None),
        "visible": not bool(getattr(root, "IsOffscreen", True)),
    }


def _diagnostic_candidate_control(driver: Any, candidate: Any) -> Any:
    resolver = getattr(driver, "_resolve_search_candidate", None)
    if callable(resolver):
        try:
            resolved = resolver(candidate)
        except Exception:
            resolved = None
        if resolved is not None:
            return resolved
    return _candidate_metadata(candidate)


def _run_message_open(driver: Any, diagnostics: UiaDiagnostics, target: str):
    if not target.strip():
        raise PreflightError("message-open requires a non-empty target")
    binding = driver.bind_window()
    window = _diagnostic_window(driver, binding)
    diagnostics.record(
        stage="message_open",
        action="bind_window",
        outcome="success",
        window=window,
        control=_root_control(driver),
        owner_window=window,
        contact=target,
    )
    if not driver.ensure_search_ready():
        raise PreflightError("the exact-contact search field is unavailable")
    candidates = driver.search_contacts(target)
    expected = normalize_identity(target)
    exact = [
        candidate
        for candidate in candidates
        if expected in _candidate_identities(candidate)
    ]
    if len(exact) != 1:
        raise PreflightError("message-open requires one exact contact result")
    candidate = exact[0]
    candidate_control = _diagnostic_candidate_control(driver, candidate)
    diagnostics.record(
        stage="message_open",
        action="resolve_exact_contact",
        outcome="success",
        window=window,
        control=candidate_control,
        owner_window=window,
        contact=target,
    )
    driver.select_search_result(candidate)
    title = normalize_identity(driver.current_chat_title())
    if title not in _candidate_identities(candidate):
        raise PreflightError("the opened chat title did not match the exact result")
    if not driver.composer_ready():
        raise PreflightError("the opened chat composer is unavailable")
    diagnostics.record(
        stage="message_open",
        action="verify_open_chat",
        outcome="success",
        window=window,
        control=candidate_control,
        owner_window=window,
        contact=target,
    )
    return {
        "ok": True,
        "mode": "message-open",
        "stage": "message_open_verified",
        "contact": redact_identifier(target),
    }


def _run_restore_only(driver: Any, diagnostics: UiaDiagnostics):
    binding = driver.bind_window()
    window = _diagnostic_window(driver, binding)
    diagnostics.record(
        stage="restore_only",
        action="bind_window",
        outcome="success",
        window=window,
        control=_root_control(driver),
        owner_window=window,
    )
    return {
        "ok": True,
        "mode": "restore-only",
        "stage": "window_restored",
    }


def _run_friend_pre_submit(
    driver: Any,
    diagnostics: UiaDiagnostics,
    *,
    account: str,
    greeting: str | None,
    remark: str,
    form_state: dict[str, bool],
):
    if not account.strip():
        raise PreflightError("friend-pre-submit requires a non-empty account")
    binding = driver.bind_window()
    window = _diagnostic_window(driver, binding)
    diagnostics.record(
        stage="friend_pre_submit",
        action="bind_window",
        outcome="success",
        window=window,
        control=_root_control(driver),
        owner_window=window,
        account=account,
    )
    if not driver.open_add_friend():
        raise PreflightError("the add-friend window did not open")
    driver.set_friend_account(account)
    profile = driver.search_friend(account)
    if profile is None:
        raise PreflightError("the exact friend account was not found")
    if normalize_identity(driver.profile_account(profile)) != normalize_identity(
        account
    ):
        raise PreflightError("the friend profile account did not match exactly")
    form_state["may_exist"] = True
    if not driver.open_friend_request(profile):
        raise PreflightError("the friend request form did not open")
    readback = driver.set_friend_fields(greeting, remark)
    if greeting is not None and readback.get("greeting") != greeting:
        raise PreflightError("the greeting readback did not match")
    if remark and readback.get("remark") != remark:
        raise PreflightError("the remark readback did not match")
    if greeting is not None:
        diagnostics.record(
            stage="friend_pre_submit",
            action="verify_greeting",
            outcome="success",
            window=window,
            account=account,
            payload_text=readback["greeting"],
        )
    if remark:
        diagnostics.record(
            stage="friend_pre_submit",
            action="verify_remark",
            outcome="success",
            window=window,
            account=account,
            payload_text=readback["remark"],
        )
    verify_hwnd = int(getattr(driver, "_verify_hwnd", 0) or 0)
    if not verify_hwnd:
        raise PreflightError("the friend request form handle is unavailable")
    confirm = driver._wait_control(
        hwnd=verify_hwnd,
        name="确定",
        control_type="ButtonControl",
    )
    if control_metadata(confirm)["visible"] is not True:
        raise PreflightError("the exact Confirm control is not visible")
    diagnostics.record(
        stage="friend_pre_submit",
        action="confirm_present",
        outcome="ready",
        window={"hwnd": verify_hwnd},
        control=confirm,
        owner_window={"hwnd": verify_hwnd},
        account=account,
    )
    return {
        "ok": True,
        "mode": "friend-pre-submit",
        "stage": "ready_to_submit",
        "account": redact_identifier(account),
        "fields": {
            "greeting": payload_fingerprint(readback.get("greeting", "")),
            "remark": payload_fingerprint(readback.get("remark", "")),
        },
    }


def run_preflight(
    mode: str,
    *,
    target: str | None = None,
    account: str | None = None,
    greeting: str | None = None,
    remark: str = "",
    timeout: float = 5.0,
    driver_factory: Callable[..., Any] = _driver_factory,
    diagnostics_factory: Callable[[], UiaDiagnostics] = UiaDiagnostics,
    form_closer: Callable[[Any], bool] | None = None,
) -> dict[str, Any]:
    driver = driver_factory(timeout=timeout)
    diagnostics = diagnostics_factory()
    primary_error: Exception | None = None
    friend_form_state = {"may_exist": False}
    try:
        if mode == "restore-only":
            return _run_restore_only(driver, diagnostics)
        if mode == "message-open":
            return _run_message_open(driver, diagnostics, target or "")
        if mode == "friend-pre-submit":
            return _run_friend_pre_submit(
                driver,
                diagnostics,
                account=account or "",
                greeting=greeting,
                remark=remark,
                form_state=friend_form_state,
            )
        raise PreflightError(f"unsupported preflight mode: {mode}")
    except Exception as exc:
        primary_error = exc
        error_window = _diagnostic_window(driver, {})
        diagnostics.record(
            stage=str(mode).replace("-", "_"),
            action="preflight",
            outcome="error",
            window=error_window,
            control=_root_control(driver),
            owner_window=error_window,
            account=account,
            contact=target,
        )
        raise
    finally:
        cleanup_error: Exception | None = None

        def record_cleanup(action: str, outcome: str) -> None:
            nonlocal cleanup_error
            cleanup_window = _diagnostic_window(driver, {})
            try:
                diagnostics.record(
                    stage=str(mode).replace("-", "_"),
                    action=action,
                    outcome=outcome,
                    window=cleanup_window,
                    control=_root_control(driver),
                    owner_window=cleanup_window,
                    account=account,
                )

            except Exception as log_error:
                if cleanup_error is None:
                    cleanup_error = log_error

        if mode == "friend-pre-submit" and (
            friend_form_state["may_exist"]
            or bool(getattr(driver, "_verify_hwnd", 0))
        ):
            closer = form_closer or close_friend_form
            try:
                form_closed = bool(closer(driver))
            except Exception as exc:
                cleanup_error = exc
                record_cleanup("close_form", "error")
            else:
                if form_closed:
                    record_cleanup("close_form", "success")
                else:
                    cleanup_error = PreflightError(
                        "the friend request form did not close"
                    )
                    record_cleanup("close_form", "error")

        try:
            driver.close()
        except Exception as exc:
            if cleanup_error is None:
                cleanup_error = exc
            record_cleanup("driver_close", "error")

        try:
            diagnostics.close()
        except Exception as exc:
            if cleanup_error is None:
                cleanup_error = exc

        if cleanup_error is not None:
            if primary_error is not None:
                raise cleanup_error from primary_error
            raise cleanup_error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    restore = subparsers.add_parser(
        "restore-only",
        help="restore and verify the Weixin main window, then exit",
    )
    restore.add_argument("--timeout", type=float, default=5.0)

    message = subparsers.add_parser(
        "message-open",
        help="open and verify one exact chat without writing any content",
    )
    message.add_argument("--target", required=True)
    message.add_argument("--timeout", type=float, default=5.0)

    friend = subparsers.add_parser(
        "friend-pre-submit",
        help="prepare and read back a friend form, stop at Confirm, then close it",
    )
    friend.add_argument("--account", required=True)
    friend.add_argument("--greeting")
    friend.add_argument("--remark", default="")
    friend.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_preflight(
            args.mode,
            target=getattr(args, "target", None),
            account=getattr(args, "account", None),
            greeting=getattr(args, "greeting", None),
            remark=getattr(args, "remark", ""),
            timeout=args.timeout,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "mode": args.mode,
            "stage": "failed",
            "errorType": type(exc).__name__,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PreflightError",
    "close_friend_form",
    "main",
    "parse_args",
    "run_preflight",
]
