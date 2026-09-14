# -*- coding: utf-8 -*-
"""Win32 API 工具"""
import ctypes
import ctypes.wintypes
import os
import re
import subprocess
import time
from dataclasses import dataclass

import win32gui
import win32con
import win32process
import winreg
from typing import Callable, Literal, Optional

from .exceptions import RegistryError


SW_SHOW = win32con.SW_SHOW
SW_RESTORE = win32con.SW_RESTORE
_WEIXIN_ROOT_EXECUTABLES = frozenset({"weixin.exe", "wechat.exe"})
_WEIXIN_MAIN_WINDOW_TITLES = frozenset({"微信", "weixin", "wechat"})
_PROCESS_TYPE_ARGUMENT = re.compile(r"(?:^|\s)--type(?:=|\s|$)", re.IGNORECASE)
_PROCESS_COMMAND_LINE_INFORMATION = 60
_KEYEVENTF_KEYUP = 0x0002


@dataclass(frozen=True)
class WindowRef:
    """Immutable snapshot of a candidate Weixin top-level window."""

    hwnd: int
    pid: int
    process_path: str
    window_class: str
    title: str
    visible: bool
    bounds: tuple[int, int, int, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "processPath": self.process_path,
            "windowClass": self.window_class,
            "title": self.title,
            "visible": self.visible,
            "bounds": list(self.bounds),
        }


@dataclass(frozen=True)
class WindowRestoreStage:
    """Observed outcome for one attempted restoration mechanism."""

    stage: Literal["direct", "tray", "hotkey"]
    attempted: bool
    succeeded: bool
    detail: str
    window: WindowRef | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "stage": self.stage,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "detail": self.detail,
        }
        if self.window is not None:
            result["window"] = self.window.as_dict()
        return result


@dataclass(frozen=True)
class WindowRestoreResult:
    """Complete, inspectable result of preparing a Weixin window."""

    initial: WindowRef | None
    window: WindowRef | None
    restored: bool
    stages: tuple[WindowRestoreStage, ...] = ()

    @property
    def window_state(self) -> Literal["missing", "hidden", "visible"]:
        if self.window is None:
            return "missing"
        return "visible" if self.window.visible else "hidden"

    @property
    def restorable(self) -> bool:
        return self.window_state == "hidden"

    def as_dict(self) -> dict[str, object]:
        return {
            "windowState": self.window_state,
            "restorable": self.restorable,
            "restored": self.restored,
            "window": self.window.as_dict() if self.window is not None else None,
            "stages": [stage.as_dict() for stage in self.stages],
        }


def ensure_screen_reader_flag() -> bool:
    """
    确保系统级屏幕阅读器标志（SPI_SETSCREENREADER）为开启状态。

    该标志用于告诉当前 Windows 会话“存在屏幕阅读器正在运行”。
    某些 Qt 应用（包括微信 4.x）会在启动时读取这个标志，
    决定是否暴露更完整的辅助功能 / UIAutomation 控件树。

    注意：
        该函数只修正当前系统会话中的辅助功能环境，
        不作为“是否必须重启微信”的判断依据。

    Returns:
        bool: 标志原本为关闭并已开启时返回 True，否则返回 False。
    """
    SPI_GETSCREENREADER = 0x0046
    SPI_SETSCREENREADER = 0x0047
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02

    pvParam = ctypes.wintypes.BOOL()
    ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETSCREENREADER, 0, ctypes.byref(pvParam), 0
    )

    if pvParam.value:
        return False

    ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETSCREENREADER, 1, 0, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
    return True


def check_and_fix_registry() -> Literal["unchanged", "fixed_zero", "created_missing"]:
    """
    检查并修复 UI Automation 的注册表设置。

    检查 HKCU\\SOFTWARE\\Microsoft\\Narrator\\NoRoam 中的 RunningState，
    如果值为 0 则设置为 1。

    Returns:
        Literal["unchanged", "fixed_zero", "created_missing"]:
            "unchanged": RunningState 已存在且无需修改
            "fixed_zero": RunningState 原值为 0，已修复为 1
            "created_missing": RunningState 缺失，已创建为 1
    """
    reg_path = r"SOFTWARE\Microsoft\Narrator\NoRoam"
    key_name = "RunningState"

    try:
        # 打开注册表键
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_path,
            0,
            winreg.KEY_READ | winreg.KEY_WRITE
        )

        try:
            # 读取当前值
            value, _ = winreg.QueryValueEx(key, key_name)

            if value == 0:
                # 设置为 1
                winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
                return "fixed_zero"

            winreg.CloseKey(key)
            return "unchanged"

        except FileNotFoundError:
            # 键不存在，创建并设置为 1
            winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
            return "created_missing"

    except PermissionError as e:
        raise RegistryError(f"访问注册表时权限被拒绝: {e}")
    except Exception as e:
        raise RegistryError(f"访问注册表失败: {e}")


def _get_process_image_name(pid: int) -> str:
    """尽力通过 pid 解析可执行文件完整路径。"""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    query_name = kernel32.QueryFullProcessImageNameW
    query_name.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    query_name.restype = ctypes.c_int

    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return ""

    try:
        size = ctypes.c_uint32(1024)
        buf = ctypes.create_unicode_buffer(1024)
        ok = query_name(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        close_handle(handle)


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.wintypes.USHORT),
        ("MaximumLength", ctypes.wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


def _get_process_command_line(pid: int) -> str | None:
    """Read a process command line without WMI or spawning another process."""
    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    query = ntdll.NtQueryInformationProcess
    query.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    query.restype = ctypes.c_long

    handle = open_process(process_query_limited_information, 0, pid)
    if not handle:
        return None
    try:
        required = ctypes.c_uint32()
        query(
            handle,
            _PROCESS_COMMAND_LINE_INFORMATION,
            None,
            0,
            ctypes.byref(required),
        )
        if required.value < ctypes.sizeof(_UnicodeString):
            return None
        buffer = ctypes.create_string_buffer(required.value)
        status = query(
            handle,
            _PROCESS_COMMAND_LINE_INFORMATION,
            buffer,
            required.value,
            ctypes.byref(required),
        )
        if status != 0:
            return None
        value = ctypes.cast(buffer, ctypes.POINTER(_UnicodeString)).contents
        if not value.Buffer or not value.Length:
            return ""
        return ctypes.wstring_at(value.Buffer, value.Length // ctypes.sizeof(ctypes.c_wchar))
    except Exception:
        return None
    finally:
        close_handle(handle)


def _is_weixin_root_process(process_path: str, command_line: str | None) -> bool:
    executable = os.path.basename(process_path).casefold()
    return bool(
        executable in _WEIXIN_ROOT_EXECUTABLES
        and command_line is not None
        and not _PROCESS_TYPE_ARGUMENT.search(command_line)
    )


def _window_score(ref: WindowRef) -> tuple[int, int, int]:
    """Rank already-verified root-process windows without requiring visibility."""
    left, top, right, bottom = ref.bounds
    width = max(0, right - left)
    height = max(0, bottom - top)
    area = width * height
    text = f"{ref.title} {ref.window_class}".casefold()
    score = 0
    if any(name in text for name in ("微信", "weixin", "wechat")):
        score += 200
    if ref.window_class.startswith("Qt") or "Chrome_WidgetWin" in ref.window_class:
        score += 80
    if width >= 300 and height >= 300:
        score += 100
    elif area == 0:
        score -= 100
    if ref.visible:
        score += 20
    return score, area, -ref.hwnd


def _is_weixin_main_window_candidate(
    window_class: str,
    title: str,
    bounds: tuple[int, int, int, int],
) -> bool:
    class_key = window_class.casefold()
    title_key = title.strip().casefold()
    if "trayiconmessagewindow" in class_key:
        return False
    if title_key not in _WEIXIN_MAIN_WINDOW_TITLES:
        return False
    if not (
        class_key.startswith("chrome_widgetwin")
        or (class_key.startswith("qt") and class_key.endswith("qwindowicon"))
    ):
        return False
    left, top, right, bottom = bounds
    return right - left >= 300 and bottom - top >= 300


def _restorable_window_bounds(
    hwnd: int,
    *,
    current: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Return the normal bounds for a genuinely minimized hidden window.

    Qt moves Weixin's tray-hidden main HWND to ``(-32000, -32000)`` and its
    current rectangle shrinks to the taskbar-icon placeholder.  The normal
    placement remains the only reliable size signal at that point.  Restrict
    this fallback to Windows' minimized show states so an unrelated small
    hidden Weixin window cannot qualify as the main window.
    """

    try:
        _flags, show_command, _minimum, _maximum, normal = (
            win32gui.GetWindowPlacement(hwnd)
        )
        minimized_commands = {
            win32con.SW_SHOWMINIMIZED,
            win32con.SW_MINIMIZE,
            win32con.SW_SHOWMINNOACTIVE,
        }
        if int(show_command) not in minimized_commands:
            return current
        normal_bounds = tuple(int(value) for value in normal)
        if len(normal_bounds) != 4:
            return current
        return normal_bounds
    except Exception:
        return current


def find_wechat_window_refs(
    *,
    pid: int | None = None,
    visible: bool | None = None,
) -> list[WindowRef]:
    """Find all eligible main windows owned by root Weixin processes.

    Root processes are confirmed by executable name and by the absence of a
    ``--type`` child-process argument. Plugin executables, Chromium child
    processes, and the tray callback window are never eligible.
    """
    candidates: list[WindowRef] = []
    process_cache: dict[int, tuple[str, str | None]] = {}

    def _enum_cb(hwnd, _context):
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            window_pid = int(window_pid)
            if not window_pid or (pid is not None and window_pid != pid):
                return True
            process = process_cache.get(window_pid)
            if process is None:
                process = (
                    _get_process_image_name(window_pid),
                    _get_process_command_line(window_pid),
                )
                process_cache[window_pid] = process
            process_path, command_line = process
            if not _is_weixin_root_process(process_path, command_line):
                return True

            window_class = win32gui.GetClassName(hwnd) or ""
            raw_visible = bool(win32gui.IsWindowVisible(hwnd))
            try:
                is_minimized = bool(win32gui.IsIconic(hwnd))
            except Exception:
                is_minimized = False
            # WS_VISIBLE remains set for some minimized Qt windows.  Such an
            # HWND is not usable for UIA until SW_RESTORE succeeds.
            is_visible = raw_visible and not is_minimized
            if visible is not None and is_visible is not visible:
                return True
            try:
                bounds = tuple(int(value) for value in win32gui.GetWindowRect(hwnd))
            except Exception:
                bounds = (0, 0, 0, 0)
            title = win32gui.GetWindowText(hwnd) or ""
            if not _is_weixin_main_window_candidate(
                window_class, title, bounds
            ):
                bounds = _restorable_window_bounds(
                    int(hwnd), current=bounds
                )
            if not _is_weixin_main_window_candidate(
                window_class, title, bounds
            ):
                return True
            candidates.append(
                WindowRef(
                    hwnd=int(hwnd),
                    pid=window_pid,
                    process_path=process_path,
                    window_class=window_class,
                    title=title,
                    visible=is_visible,
                    bounds=bounds,
                )
            )
        except Exception:
            pass
        return True

    win32gui.EnumWindows(_enum_cb, None)
    return sorted(candidates, key=_window_score, reverse=True)


def find_wechat_window_ref(
    *,
    pid: int | None = None,
    visible: bool | None = None,
) -> WindowRef | None:
    """Return the highest-ranked eligible Weixin root window snapshot."""
    candidates = find_wechat_window_refs(pid=pid, visible=visible)
    return candidates[0] if candidates else None


def find_wechat_window() -> Optional[int]:
    """Backward-compatible HWND-only wrapper around root-window discovery."""
    ref = find_wechat_window_ref()
    return ref.hwnd if ref is not None else None


def _show_window_async(hwnd: int, command: int) -> bool:
    return bool(ctypes.windll.user32.ShowWindowAsync(hwnd, command))


def _get_current_thread_id() -> int:
    return int(ctypes.windll.kernel32.GetCurrentThreadId())


def _attach_thread_input(left: int, right: int, attach: bool) -> bool:
    return bool(ctypes.windll.user32.AttachThreadInput(left, right, bool(attach)))


def _foreground_with_thread_handshake(hwnd: int) -> bool:
    """Request foreground activation while temporarily joining input queues."""
    attached: list[tuple[int, int]] = []
    try:
        current_thread = _get_current_thread_id()
        foreground_hwnd = int(win32gui.GetForegroundWindow() or 0)
        foreground_thread = (
            int(win32process.GetWindowThreadProcessId(foreground_hwnd)[0])
            if foreground_hwnd
            else 0
        )
        target_thread = int(win32process.GetWindowThreadProcessId(hwnd)[0])
        for other_thread in (foreground_thread, target_thread):
            pair = (current_thread, other_thread)
            if (
                other_thread
                and other_thread != current_thread
                and pair not in attached
                and _attach_thread_input(current_thread, other_thread, True)
            ):
                attached.append(pair)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
    finally:
        for left, right in reversed(attached):
            try:
                _attach_thread_input(left, right, False)
            except Exception:
                pass


def _restore_from_native_tray(expected_pid: int) -> bool:
    from .tray import restore_wechat_from_native_tray

    return bool(restore_wechat_from_native_tray(expected_pid=expected_pid))


def _send_ctrl_alt_w() -> bool:
    """Send exactly one Ctrl+Alt+W chord."""
    keys = (win32con.VK_CONTROL, win32con.VK_MENU, ord("W"))
    pressed: list[int] = []
    try:
        for key in keys:
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            pressed.append(key)
        return True
    except Exception:
        return False
    finally:
        for key in reversed(pressed):
            try:
                ctypes.windll.user32.keybd_event(key, 0, _KEYEVENTF_KEYUP, 0)
            except Exception:
                pass


def _wait_for_pid_window(
    pid: int,
    *,
    expected_process_path: str,
    visible: bool,
    timeout: float,
    poll_interval: float,
    sleep: Callable[[float], None],
) -> WindowRef | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        ref = find_wechat_window_ref(pid=pid, visible=visible)
        if ref is not None:
            if os.path.normcase(ref.process_path) == os.path.normcase(
                expected_process_path
            ):
                return ref
            # A PID reused by a different installation can never become the
            # original process again. Fail closed without waiting or acting on
            # that window.
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        sleep(min(max(0.0, poll_interval), remaining))


def _restoration_detail(
    action: str,
    action_succeeded: bool,
    visible_ref: WindowRef | None,
    hidden_ref: WindowRef | None,
) -> str:
    if visible_ref is not None:
        return f"{action}; same PID is visible at HWND {visible_ref.hwnd}"
    if hidden_ref is not None:
        return f"{action}; same PID remained hidden at HWND {hidden_ref.hwnd}"
    outcome = "completed" if action_succeeded else "failed"
    return f"{action} {outcome}; same PID window is no longer discoverable"


def restore_wechat_window(
    window: WindowRef | None = None,
    *,
    settle_timeout: float = 0.75,
    poll_interval: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
) -> WindowRestoreResult:
    """Restore one hidden Weixin root window without restarting its process.

    Each mechanism is attempted at most once, in the fixed order direct Win32,
    native tray callback, then Ctrl+Alt+W. A stage succeeds only when a fresh
    discovery finds a visible main window owned by the original PID.
    """
    initial = window if window is not None else find_wechat_window_ref()
    if initial is None:
        return WindowRestoreResult(None, None, False)

    stages: list[WindowRestoreStage] = []
    visible_ref = find_wechat_window_ref(pid=initial.pid, visible=True)
    if visible_ref is not None and (
        os.path.normcase(visible_ref.process_path)
        == os.path.normcase(initial.process_path)
    ):
        return WindowRestoreResult(initial, visible_ref, not initial.visible)
    if visible_ref is not None:
        return WindowRestoreResult(initial, None, False)
    current = find_wechat_window_ref(pid=initial.pid, visible=False)
    if (
        current is None
        or os.path.normcase(current.process_path)
        != os.path.normcase(initial.process_path)
    ):
        return WindowRestoreResult(initial, None, False)

    direct_ok = True
    try:
        _show_window_async(current.hwnd, SW_SHOW)
        _show_window_async(current.hwnd, SW_RESTORE)
        direct_ok = _foreground_with_thread_handshake(current.hwnd)
    except Exception:
        direct_ok = False
    visible_ref = _wait_for_pid_window(
        initial.pid,
        expected_process_path=initial.process_path,
        visible=True,
        timeout=settle_timeout,
        poll_interval=poll_interval,
        sleep=sleep,
    )
    hidden_ref = None
    if visible_ref is None:
        candidate = find_wechat_window_ref(pid=initial.pid, visible=False)
        if candidate is not None and os.path.normcase(
            candidate.process_path
        ) == os.path.normcase(initial.process_path):
            hidden_ref = candidate
    stages.append(
        WindowRestoreStage(
            "direct",
            True,
            visible_ref is not None,
            _restoration_detail(
                "ShowWindowAsync(SW_SHOW/SW_RESTORE) and foreground handshake",
                direct_ok,
                visible_ref,
                hidden_ref,
            ),
            visible_ref or hidden_ref,
        )
    )
    if visible_ref is not None:
        return WindowRestoreResult(initial, visible_ref, True, tuple(stages))
    if hidden_ref is None:
        return WindowRestoreResult(initial, None, False, tuple(stages))
    current = hidden_ref

    try:
        refreshed_hidden = find_wechat_window_ref(pid=initial.pid, visible=False)
        if (
            refreshed_hidden is None
            or os.path.normcase(refreshed_hidden.process_path)
            != os.path.normcase(initial.process_path)
        ):
            stages.append(
                WindowRestoreStage(
                    "tray",
                    False,
                    False,
                    "native tray callback skipped; same PID window is no longer "
                    "discoverable or no longer matches the original process path",
                    None,
                )
            )
            return WindowRestoreResult(initial, None, False, tuple(stages))
        current = refreshed_hidden
        tray_ok = _restore_from_native_tray(initial.pid)
    except Exception:
        tray_ok = False
    visible_ref = _wait_for_pid_window(
        initial.pid,
        expected_process_path=initial.process_path,
        visible=True,
        timeout=settle_timeout,
        poll_interval=poll_interval,
        sleep=sleep,
    )
    hidden_ref = None
    if visible_ref is None:
        candidate = find_wechat_window_ref(pid=initial.pid, visible=False)
        if candidate is not None and os.path.normcase(
            candidate.process_path
        ) == os.path.normcase(initial.process_path):
            hidden_ref = candidate
    stages.append(
        WindowRestoreStage(
            "tray",
            True,
            visible_ref is not None,
            _restoration_detail(
                "native tray callback dispatched" if tray_ok else "native tray callback unavailable",
                tray_ok,
                visible_ref,
                hidden_ref,
            ),
            visible_ref or hidden_ref,
        )
    )
    if visible_ref is not None:
        return WindowRestoreResult(initial, visible_ref, True, tuple(stages))
    if hidden_ref is None:
        return WindowRestoreResult(initial, None, False, tuple(stages))
    current = hidden_ref

    refreshed_hidden = find_wechat_window_ref(pid=initial.pid, visible=False)
    if (
        refreshed_hidden is None
        or os.path.normcase(refreshed_hidden.process_path)
        != os.path.normcase(initial.process_path)
    ):
        stages.append(
            WindowRestoreStage(
                "hotkey",
                False,
                False,
                "global Ctrl+Alt+W skipped; same PID window is no longer "
                "discoverable or no longer matches the original process path",
                None,
            )
        )
        return WindowRestoreResult(initial, None, False, tuple(stages))
    current = refreshed_hidden
    root_pids = {ref.pid for ref in find_wechat_window_refs()}
    if root_pids != {initial.pid}:
        stages.append(
            WindowRestoreStage(
                "hotkey",
                False,
                False,
                "global Ctrl+Alt+W skipped because multiple root PIDs "
                "or a different root PID is present",
                current,
            )
        )
        return WindowRestoreResult(initial, current, False, tuple(stages))

    try:
        hotkey_ok = _send_ctrl_alt_w()
    except Exception:
        hotkey_ok = False
    visible_ref = _wait_for_pid_window(
        initial.pid,
        expected_process_path=initial.process_path,
        visible=True,
        timeout=settle_timeout,
        poll_interval=poll_interval,
        sleep=sleep,
    )
    hidden_ref = None
    if visible_ref is None:
        candidate = find_wechat_window_ref(pid=initial.pid, visible=False)
        if candidate is not None and os.path.normcase(
            candidate.process_path
        ) == os.path.normcase(initial.process_path):
            hidden_ref = candidate
    stages.append(
        WindowRestoreStage(
            "hotkey",
            True,
            visible_ref is not None,
            _restoration_detail(
                "one Ctrl+Alt+W chord sent" if hotkey_ok else "Ctrl+Alt+W chord failed",
                hotkey_ok,
                visible_ref,
                hidden_ref,
            ),
            visible_ref or hidden_ref,
        )
    )
    return WindowRestoreResult(
        initial,
        visible_ref or hidden_ref,
        visible_ref is not None,
        tuple(stages),
    )


def restart_wechat_process(hwnd: int) -> bool:
    """
    重启指定窗口句柄对应的微信进程。

    Args:
        hwnd: 微信窗口句柄

    Returns:
        bool: 重启命令执行成功返回 True
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_path = _get_process_image_name(pid)
        if not exe_path or not os.path.exists(exe_path):
            return False

        # 结束当前进程树
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        time.sleep(1.0)

        # 重新启动微信可执行文件
        subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return True
    except Exception:
        return False


def bring_window_to_front(hwnd: int) -> bool:
    """
    将窗口置于前台，如果已最小化则恢复。

    Args:
        hwnd: 窗口句柄

    Returns:
        bool: 成功时返回 True
    """
    try:
        # 显示窗口
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # 置于前台
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def get_window_title(hwnd: int) -> str:
    """通过句柄获取窗口标题"""
    return win32gui.GetWindowText(hwnd)


def get_window_class(hwnd: int) -> str:
    """通过句柄获取窗口类名"""
    return win32gui.GetClassName(hwnd)


def is_window_visible(hwnd: int) -> bool:
    """检查窗口是否可见"""
    return win32gui.IsWindowVisible(hwnd) != 0


def minimize_window(hwnd: int) -> bool:
    """
    最小化指定窗口。

    Args:
        hwnd: 窗口句柄

    Returns:
        bool: 成功时返回 True
    """
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return True
    except Exception:
        return False
