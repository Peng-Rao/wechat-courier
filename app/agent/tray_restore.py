from __future__ import annotations

import os
import sys

import win32con
import win32gui
import win32process

from src.core import tray as native_tray
from src.core import win32

from .retry import AutomationRetryError, StaleElementError, WeixinUnresponsiveError
from .uia_query import ScopedQueryUnavailable
from .waiters import check_action_deadline


class TrayRestoreError(AutomationRetryError):
    code = "WINDOW_RESTORE_FAILED"


_SHELL_CLASSES = (
    "Shell_TrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
)
_WECHAT_NAMES = ("\u5fae\u4fe1", " \u5fae\u4fe1", "WeChat", " WeChat", "Weixin", " Weixin")
_OVERFLOW_NAMES = ("\u663e\u793a\u9690\u85cf\u7684\u56fe\u6807", "\u663e\u793a\u9690\u85cf\u56fe\u6807", "Show hidden icons")


def _is_windows10() -> bool:
    return 10240 <= sys.getwindowsversion().build < 22000


def restore_hidden_window(initial, *, uia, query, backend, waiter, timeout):
    """Restore Qt through one tray activation, using the caller's COM apartment."""
    check_action_deadline()
    started = str(backend.process_start_time(initial.pid) or "")
    if not started:
        raise StaleElementError("Cannot verify the hidden Weixin process instance")

    def responsive(hwnd):
        check_action_deadline()
        if not backend.window_responsive(hwnd, timeout_ms=250):
            raise WeixinUnresponsiveError("Tray restoration window is unresponsive")
        check_action_deadline()

    def current():
        check_action_deadline()
        refs = win32.find_wechat_window_refs()
        if {ref.pid for ref in refs} != {initial.pid}:
            raise TrayRestoreError("Tray target is missing or multiple Weixin processes exist")
        if str(backend.process_start_time(initial.pid) or "") != started:
            raise StaleElementError("Weixin process changed during tray restoration")
        matches = [ref for ref in refs if ref.visible and win32gui.IsWindowVisible(ref.hwnd)]
        if not matches:
            matches = [ref for ref in refs if ref.hwnd == initial.hwnd]
        ref = matches[0] if len(matches) == 1 else refs[0] if len(refs) == 1 else None
        if (ref is None or os.path.normcase(ref.process_path) != os.path.normcase(initial.process_path)
                or not win32gui.IsWindow(ref.hwnd)
                or int(win32process.GetWindowThreadProcessId(ref.hwnd)[1]) != initial.pid):
            raise StaleElementError("Hidden Weixin window identity changed")
        responsive(ref.hwnd)
        if not win32gui.IsWindowEnabled(ref.hwnd):
            raise TrayRestoreError("Weixin window is blocked during tray restoration")
        return ref

    def hidden():
        return not bool(win32gui.IsWindowVisible(current().hwnd))

    def completed(stage, detail):
        def ready():
            ref = current()
            return ref.visible and bool(win32gui.IsWindowVisible(ref.hwnd))

        if not waiter.wait(ready, timeout) or not ready():
            raise TrayRestoreError("Tray activation did not restore Weixin; refusing another toggle")
        ref = current()
        return win32.WindowRestoreResult(initial, ref, True, (
            win32.WindowRestoreStage(stage, True, True, detail, ref),
        ))

    ref = current()
    if win32gui.IsWindowVisible(ref.hwnd):
        return win32.WindowRestoreResult(initial, ref, False)

    def shell_pid(hwnd):
        check_action_deadline()
        if (not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd)
                or not win32gui.IsWindowEnabled(hwnd)
                or win32gui.GetClassName(hwnd) not in _SHELL_CLASSES):
            raise TrayRestoreError("Explorer tray window changed or became unavailable")
        pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
        if os.path.basename(win32._get_process_image_name(pid)).lower() != "explorer.exe":
            raise TrayRestoreError("Tray window does not belong to Explorer")
        responsive(hwnd)
        return pid

    def buttons(names):
        found = []
        seen_hwnds = set()
        for class_name in _SHELL_CLASSES:
            check_action_deadline()
            hwnd = int(win32gui.FindWindow(class_name, None) or 0)
            if not hwnd or hwnd in seen_hwnds or not win32gui.IsWindowVisible(hwnd):
                continue
            seen_hwnds.add(hwnd)
            pid = shell_pid(hwnd)
            try:
                root = uia.ControlFromHandle(hwnd)
                if int(root.NativeWindowHandle) != hwnd or int(root.ProcessId) != pid:
                    raise TrayRestoreError("Explorer UIA root identity changed")
                responsive(hwnd)
                controls = query.find_all(root, name=names, control_type="ButtonControl", visible=True)
                check_action_deadline()
                found.extend((hwnd, control) for control in controls)
            except AutomationRetryError:
                raise
            except Exception as exc:
                if isinstance(exc.__cause__, AutomationRetryError):
                    raise exc.__cause__
                raise ScopedQueryUnavailable(str(exc)) from exc
        if len(found) > 1:
            raise TrayRestoreError("Ambiguous Explorer tray buttons; refusing activation")
        return found

    def invoke_unique(names):
        found = buttons(names)
        if not found:
            return False
        hwnd, control = found[0]
        pid = shell_pid(hwnd)
        try:
            if (int(control.ProcessId) != pid or str(control.Name) not in names
                    or control.ControlTypeName != "ButtonControl"
                    or not control.IsEnabled or control.IsOffscreen):
                raise TrayRestoreError("Explorer tray button identity or state changed")
            check_action_deadline()
            pattern = control.GetInvokePattern()
            invoke = getattr(pattern, "Invoke", None)
            check_action_deadline()
        except AutomationRetryError:
            raise
        except Exception:
            check_action_deadline()
            return False
        if not callable(invoke):
            return False
        if not hidden():
            return False
        if shell_pid(hwnd) != pid:
            raise TrayRestoreError("Explorer process changed before tray Invoke")
        check_action_deadline()
        try:
            invoke()
        except AutomationRetryError:
            raise
        except Exception as exc:
            raise TrayRestoreError("Tray Invoke outcome is uncertain; refusing fallback") from exc
        check_action_deadline()
        return True

    try:
        if not buttons(_WECHAT_NAMES):
            if invoke_unique(_OVERFLOW_NAMES):
                waiter.wait(lambda: bool(buttons(_WECHAT_NAMES)), timeout)
        if invoke_unique(_WECHAT_NAMES):
            return completed("tray", "Explorer scoped Weixin Button Invoke, once")
    except ScopedQueryUnavailable:
        check_action_deadline()

    if not hidden():
        return completed("tray", "Weixin became visible without another tray activation")
    if _is_windows10():
        try:
            candidates = native_tray._find_wechat_native_tray_buttons()
        except AutomationRetryError:
            raise
        except Exception:
            check_action_deadline()
            candidates = []
        matches = {}
        for button in candidates:
            check_action_deadline()
            if int(win32process.GetWindowThreadProcessId(button.hwnd)[1]) == initial.pid:
                matches[(button.hwnd, button.uid, button.callback_msg)] = button
        if len(matches) > 1:
            raise TrayRestoreError("Ambiguous native Weixin tray registrations")
        if matches:
            hwnd, uid, message = next(iter(matches))
            if not hidden():
                return completed("tray", "Weixin became visible before native callback")
            responsive(hwnd)
            if int(win32process.GetWindowThreadProcessId(hwnd)[1]) != initial.pid:
                raise StaleElementError("Native tray callback owner changed")
            check_action_deadline()
            try:
                win32gui.PostMessage(hwnd, message, uid, win32con.WM_LBUTTONUP)
            except AutomationRetryError:
                raise
            except Exception as exc:
                raise TrayRestoreError("Native tray callback outcome is uncertain") from exc
            return completed("tray", "Single native tray WM_LBUTTONUP callback")

    # Only a freshly verified, still-hidden, sole Weixin instance permits this chord.
    if not hidden():
        return completed("tray", "Weixin became visible before hotkey fallback")
    check_action_deadline()
    win32._send_ctrl_alt_w()
    check_action_deadline()
    return completed("hotkey", "Single Ctrl+Alt+W for verified hidden Weixin")
