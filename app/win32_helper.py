# -*- coding: utf-8 -*-
"""Windows Native DWM Visual Controller Module

Provides helper functions using ctypes to apply Windows 10/11 Acrylic/Mica effects
and immersive dark-mode titlebars to the native PySide6 window frame.
"""

import sys
import ctypes
from dataclasses import dataclass

# Only expose active bindings on Windows
if sys.platform == "win32":
    try:
        from ctypes import wintypes
        dwmapi = ctypes.WinDLL("dwmapi")
        user32 = ctypes.WinDLL("user32")
    except Exception as e:
        print(f"[win32_helper] Failed to load Win32 DLLs: {e}")
        dwmapi = None
        user32 = None
else:
    dwmapi = None
    user32 = None


WM_NCHITTEST = 0x0084
WM_NCDESTROY = 0x0082
WM_NCCALCSIZE = 0x0083
WM_NCPAINT = 0x0085
WM_NCACTIVATE = 0x0086
WM_GETMINMAXINFO = 0x0024
WM_ENTERSIZEMOVE = 0x0231

HTCLIENT = 1
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCAPTION = 2
HTMAXBUTTON = 9

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4

WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
FRAMELESS_SNAP_STYLE_MASK = (
    WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
)
NATIVE_FRAME_STYLE_MASK = FRAMELESS_SNAP_STYLE_MASK
WS_EX_LAYERED = 0x00080000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

TITLE_BAR_HEIGHT = 40
TITLE_BAR_DRAG_RIGHT_MARGIN = 322
CAPTION_BUTTON_WIDTH = 46
RESIZE_BORDER_WIDTH = 8


@dataclass(frozen=True)
class FramelessHitTestMetrics:
    client_width: int
    client_height: int
    dpi_scale: float = 1.0
    title_bar_height: int = TITLE_BAR_HEIGHT
    drag_right_margin: int = TITLE_BAR_DRAG_RIGHT_MARGIN
    caption_button_width: int = CAPTION_BUTTON_WIDTH
    resize_border_width: int = RESIZE_BORDER_WIDTH
    resizable: bool = True


def _scaled(value: int, scale: float) -> int:
    return max(1, int(round(value * max(scale, 0.1))))


def hit_test_client_point(x: int, y: int, metrics: FramelessHitTestMetrics) -> int:
    """Map a client-area point to a Win32 hit-test code for the custom shell."""
    width = int(metrics.client_width)
    height = int(metrics.client_height)
    scale = float(metrics.dpi_scale or 1.0)
    border = _scaled(metrics.resize_border_width, scale) if metrics.resizable else 0
    title_height = _scaled(metrics.title_bar_height, scale) if metrics.title_bar_height else 0
    drag_right_margin = _scaled(metrics.drag_right_margin, scale)

    on_left = x < border
    on_right = x >= width - border
    on_top = y < border
    on_bottom = y >= height - border

    if on_top and on_left:
        return HTTOPLEFT
    if on_top and on_right:
        return HTTOPRIGHT
    if on_bottom and on_left:
        return HTBOTTOMLEFT
    if on_bottom and on_right:
        return HTBOTTOMRIGHT
    if on_left:
        return HTLEFT
    if on_right:
        return HTRIGHT
    if on_top:
        return HTTOP
    if on_bottom:
        return HTBOTTOM

    if y < title_height:
        drag_right = max(0, width - drag_right_margin)
        if x < drag_right:
            return HTCAPTION

    return HTCLIENT


_snap_subclasses: dict[int, tuple[object, int]] = {}
_interaction_callbacks: dict[int, object] = {}


def set_window_interaction_callback(hwnd_val: int, callback) -> None:
    _interaction_callbacks[int(hwnd_val)] = callback


if sys.platform == "win32" and user32:
    class MINMAXINFO(ctypes.Structure):
        _fields_ = [(name, wintypes.POINT) for name in (
            "ptReserved", "ptMaxSize", "ptMaxPosition", "ptMinTrackSize", "ptMaxTrackSize")]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    _GetWindowLongPtr = (
        user32.GetWindowLongPtrW
        if ctypes.sizeof(ctypes.c_void_p) == 8
        else user32.GetWindowLongW
    )
    _SetWindowLongPtr = (
        user32.SetWindowLongPtrW
        if ctypes.sizeof(ctypes.c_void_p) == 8
        else user32.SetWindowLongW
    )
    _GetWindowLongPtr.restype = ctypes.c_ssize_t
    _GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    _SetWindowLongPtr.restype = ctypes.c_ssize_t
    _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    if hasattr(user32, "GetDpiForWindow"):
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = ctypes.c_uint
    if dwmapi and hasattr(dwmapi, "DwmDefWindowProc"):
        dwmapi.DwmDefWindowProc.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            ctypes.POINTER(LRESULT),
        ]
        dwmapi.DwmDefWindowProc.restype = wintypes.BOOL
else:
    WNDPROC = None

# DWM Window Attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

# Windows 11 System Backdrop Types (DWMWA_SYSTEMBACKDROP_TYPE)
DWMSBT_AUTO = 0
DWMSBT_DISABLE = 1
DWMSBT_MICA = 2        # Mica style (wallpaper colored)
DWMSBT_ACRYLIC = 3     # Acrylic frosted glass style (wallpaper + behind window)
DWMSBT_TABBED = 4      # Mica Alt style

# Windows 10 undocumented Accent Policy structures
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_int),
        ("AnimationId", ctypes.c_int)
    ]

class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t)
    ]

# Windows 10 Composition Attributes
WCA_ACCENT_POLICY = 19

# Windows 10 Accent States
ACCENT_DISABLED = 0
ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


def set_immersive_dark_mode(hwnd_val: int, enabled: bool) -> bool:
    """Forcibly set native window frame border and titlebar to Dark Mode or Light Mode.

    Supports both Windows 11 (attribute 20) and Windows 10 builds (attributes 20 & 19).
    """
    if not dwmapi or hwnd_val is None or hwnd_val == 0:
        return False
    try:
        value = ctypes.c_int(1 if enabled else 0)
        
        # Try modern Windows 11 and Windows 10 20H1+ (attribute 20)
        hr20 = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd_val),
            ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        
        # Try older Windows 10 builds (attribute 19)
        hr19 = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd_val),
            ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1),
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        
        return hr20 == 0 or hr19 == 0
    except Exception as e:
        print(f"[win32_helper] DwmSetWindowAttribute immersive dark failed: {e}")
        return False


def set_window_backdrop_win11(hwnd_val: int, backdrop_type: int) -> bool:
    """Set the modern Windows 11 transparency backdrop effect (Mica or Acrylic)."""
    if not dwmapi or hwnd_val is None or hwnd_val == 0:
        return False
    try:
        value = ctypes.c_int(backdrop_type)
        hr = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd_val),
            ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        return hr == 0
    except Exception as e:
        print(f"[win32_helper] DwmSetWindowAttribute backdrop failed: {e}")
        return False


def set_window_corner_preference(hwnd_val: int, rounded: bool) -> bool:
    if not dwmapi or not hwnd_val:
        return False
    try:
        value = ctypes.c_int(DWMWCP_ROUND if rounded else DWMWCP_DONOTROUND)
        return dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd_val), ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value), ctypes.sizeof(value),
        ) == 0
    except (OSError, AttributeError, TypeError, ValueError):
        return False


def extend_native_frame(hwnd_val: int) -> bool:
    """Make the transparent Qt client participate in the DWM backdrop."""
    if not dwmapi or not hwnd_val:
        return False
    try:
        margins = (ctypes.c_int * 4)(-1, -1, -1, -1)
        return dwmapi.DwmExtendFrameIntoClientArea(
            ctypes.c_void_p(hwnd_val), ctypes.byref(margins)) == 0
    except (OSError, AttributeError, TypeError, ValueError):
        return False


def _opacity_to_alpha(opacity_percent: int) -> int:
    try:
        opacity = int(opacity_percent)
    except (TypeError, ValueError):
        opacity = 72
    opacity = max(45, min(90, opacity))
    return int(round(255 * opacity / 100))


def _argb(alpha: int, red: int, green: int, blue: int) -> int:
    """Return Windows AccentPolicy color formatted as AABBGGRR."""
    return ((alpha & 0xff) << 24) | ((blue & 0xff) << 16) | ((green & 0xff) << 8) | (red & 0xff)


def _set_accent_policy(hwnd_val: int, accent_state: int, gradient_color: int = 0) -> bool:
    if not user32 or hwnd_val is None or hwnd_val == 0:
        return False
    accent = ACCENT_POLICY()
    accent.AccentState = accent_state
    accent.AccentFlags = 2 if accent_state == ACCENT_ENABLE_ACRYLICBLURBEHIND else 0
    accent.GradientColor = gradient_color
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = ctypes.addressof(accent)
    data.SizeOfData = ctypes.sizeof(accent)

    hr = user32.SetWindowCompositionAttribute(hwnd_val, ctypes.byref(data))
    return hr != 0


def disable_window_backdrop(hwnd_val: int) -> bool:
    """Disable native backdrop effects while keeping the window usable."""
    if sys.platform != "win32" or hwnd_val is None or hwnd_val == 0:
        return False

    win11_ok = False
    try:
        win_version = sys.getwindowsversion()
        if win_version.major == 10 and win_version.build >= 22000:
            win11_ok = set_window_backdrop_win11(hwnd_val, DWMSBT_DISABLE)
    except Exception as e:
        print(f"[win32_helper] disable Win11 backdrop failed: {e}")

    win10_ok = False
    try:
        win10_ok = _set_accent_policy(hwnd_val, ACCENT_DISABLED)
    except Exception as e:
        print(f"[win32_helper] disable Win10 accent failed: {e}")

    return win11_ok or win10_ok


def set_window_backdrop_win10(hwnd_val: int, is_dark: bool, opacity_percent: int = 72) -> bool:
    """Apply native Acrylic frosted glass effect on Windows 10 using undocumented user32 APIs."""
    try:
        alpha = _opacity_to_alpha(opacity_percent)

        # Color formatted as AABBGGRR in hex
        # Windows 10 Acrylic needs an alpha tint for readability.
        if is_dark:
            gradient_color = _argb(alpha, 0x16, 0x19, 0x1c)
        else:
            gradient_color = _argb(alpha, 0xff, 0xff, 0xff)

        return _set_accent_policy(hwnd_val, ACCENT_ENABLE_ACRYLICBLURBEHIND, gradient_color)
    except Exception as e:
        print(f"[win32_helper] SetWindowCompositionAttribute Win10 Acrylic failed: {e}")
        return False


def apply_window_backdrop(hwnd_val: int, is_dark: bool, enabled: bool = True, opacity_percent: int = 72) -> bool:
    """Apply or disable the native window backdrop based on user visual settings."""
    if sys.platform != "win32" or hwnd_val is None or hwnd_val == 0:
        return False
    if not enabled:
        return disable_window_backdrop(hwnd_val)
    try:
        win_version = sys.getwindowsversion()
        # Windows 11 starts at build 22000
        if win_version.major == 10 and win_version.build >= 22000:
            # Windows 11 style
            return set_window_backdrop_win11(hwnd_val, DWMSBT_ACRYLIC)
        else:
            # Windows 10 style
            return set_window_backdrop_win10(hwnd_val, is_dark, opacity_percent)
    except Exception as e:
        print(f"[win32_helper] apply_window_backdrop failed: {e}")
        return False


def apply_acrylic_effect(hwnd_val: int, is_dark: bool) -> bool:
    """Backward-compatible wrapper for existing callers."""
    return apply_window_backdrop(hwnd_val, is_dark, True, 72)


def _window_dpi_scale(hwnd_val: int) -> float:
    if not user32 or not hasattr(user32, "GetDpiForWindow"):
        return 1.0
    try:
        dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd_val))
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


def native_resize_inset(dpi: int) -> int:
    if not user32:
        return 0
    if hasattr(user32, "GetSystemMetricsForDpi"):
        return user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi)
    return user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)


def _client_metrics(hwnd_val: int) -> FramelessHitTestMetrics | None:
    if not user32:
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd_val), ctypes.byref(rect)):
        return None
    style = _GetWindowLongPtr(wintypes.HWND(hwnd_val), GWL_STYLE)
    has_frame = bool(style & WS_THICKFRAME)
    return FramelessHitTestMetrics(
        client_width=rect.right - rect.left,
        client_height=rect.bottom - rect.top,
        dpi_scale=_window_dpi_scale(hwnd_val),
        resizable=has_frame and not bool(user32.IsZoomed(wintypes.HWND(hwnd_val))),
        title_bar_height=TITLE_BAR_HEIGHT if has_frame else 0,
    )


def _screen_point_from_lparam(lparam: int) -> tuple[int, int]:
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return x, y


def _hit_test_lparam(hwnd_val: int, lparam: int) -> int:
    metrics = _client_metrics(hwnd_val)
    if metrics is None:
        return HTCLIENT

    x, y = _screen_point_from_lparam(int(lparam))
    point = wintypes.POINT(x, y)
    if not user32.ScreenToClient(wintypes.HWND(hwnd_val), ctypes.byref(point)):
        return HTCLIENT
    return hit_test_client_point(point.x, point.y, metrics)


def _enable_snap_styles(hwnd_val: int, native_frame: bool = False) -> None:
    if not user32:
        return
    hwnd = wintypes.HWND(hwnd_val)
    style = _GetWindowLongPtr(hwnd, GWL_STYLE)
    if not style:
        return
    new_style = (style | FRAMELESS_SNAP_STYLE_MASK) & ~WS_CAPTION
    if new_style == style:
        return
    _SetWindowLongPtr(hwnd, GWL_STYLE, new_style)
    user32.SetWindowPos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def _install_window_hit_test(hwnd_val: int, native_frame: bool) -> bool:
    if sys.platform != "win32" or not user32 or not WNDPROC:
        return False
    if not hwnd_val:
        return False

    hwnd_int = int(hwnd_val)
    if hwnd_int in _snap_subclasses:
        return True

    _enable_snap_styles(hwnd_int, native_frame)
    previous_proc = _GetWindowLongPtr(wintypes.HWND(hwnd_int), GWLP_WNDPROC)
    if not previous_proc:
        return False

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_ENTERSIZEMOVE:
            callback = _interaction_callbacks.get(int(hwnd))
            if callback is not None:
                callback()
        if native_frame and msg == WM_GETMINMAXINFO:
            result = user32.CallWindowProcW(ctypes.c_void_p(previous_proc), hwnd, msg, wparam, lparam)
            monitor = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
            if user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor)):
                info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
                inset = native_resize_inset(round(_window_dpi_scale(hwnd) * 96))
                info.ptMaxPosition.x = monitor.rcWork.left - monitor.rcMonitor.left - inset
                info.ptMaxPosition.y = monitor.rcWork.top - monitor.rcMonitor.top - inset
                info.ptMaxSize.x = monitor.rcWork.right - monitor.rcWork.left + 2 * inset
                info.ptMaxSize.y = monitor.rcWork.bottom - monitor.rcWork.top + 2 * inset
            return result
        if native_frame and msg == WM_NCPAINT:
            return 0
        if native_frame and msg == WM_NCACTIVATE:
            return user32.CallWindowProcW(ctypes.c_void_p(previous_proc), hwnd, msg, wparam, -1)
        if native_frame and msg == WM_NCCALCSIZE and wparam:
            rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
            style = _GetWindowLongPtr(hwnd, GWL_STYLE)
            # One native pixel gives DWM a border without painting a caption.
            inset = 1 if style & WS_THICKFRAME else 0
            if style & WS_THICKFRAME and user32.IsZoomed(hwnd):
                dpi = round(_window_dpi_scale(hwnd) * 96)
                inset = native_resize_inset(dpi)
            rect.left += inset
            rect.top += inset
            rect.right -= inset
            rect.bottom -= inset
            return 0
        if msg == WM_NCHITTEST:
            own_result = _hit_test_lparam(int(hwnd), int(lparam))
            # Caption buttons belong to QML, not to the invisible native caption.
            if native_frame or own_result == HTCLIENT:
                return own_result
            dwm_result = LRESULT(0)
            try:
                if (
                    dwmapi
                    and hasattr(dwmapi, "DwmDefWindowProc")
                    and dwmapi.DwmDefWindowProc(hwnd, msg, wparam, lparam, ctypes.byref(dwm_result))
                    and dwm_result.value != HTCLIENT
                ):
                    if dwm_result.value == HTMAXBUTTON:
                        return HTCLIENT
                    return dwm_result.value
            except Exception:
                pass
            return own_result

        result = user32.CallWindowProcW(
            ctypes.c_void_p(previous_proc),
            hwnd,
            msg,
            wparam,
            lparam,
        )
        if msg == WM_NCDESTROY:
            _snap_subclasses.pop(int(hwnd), None)
            _interaction_callbacks.pop(int(hwnd), None)
        return result

    callback = WNDPROC(wnd_proc)
    installed_previous = _SetWindowLongPtr(
        wintypes.HWND(hwnd_int),
        GWLP_WNDPROC,
        ctypes.cast(callback, ctypes.c_void_p).value,
    )
    if not installed_previous:
        return False

    _snap_subclasses[hwnd_int] = (callback, installed_previous)
    if native_frame:
        user32.SetWindowPos(wintypes.HWND(hwnd_int), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    return True


def install_frameless_window_hit_test(hwnd_val: int) -> bool:
    """Compatibility bridge for the original transparent frameless shell."""
    return _install_window_hit_test(hwnd_val, native_frame=False)


def install_native_window_hit_test(hwnd_val: int) -> bool:
    """Keep native frame capabilities while using QML caption controls."""
    return _install_window_hit_test(hwnd_val, native_frame=True)


def uninstall_window_hit_test(hwnd_val: int) -> None:
    _interaction_callbacks.pop(int(hwnd_val), None)
    entry = _snap_subclasses.get(int(hwnd_val))
    if not entry or not user32:
        return
    callback, previous_proc = entry
    hwnd = ctypes.c_void_p(hwnd_val)
    if user32.IsWindow(hwnd):
        current = _GetWindowLongPtr(hwnd, GWLP_WNDPROC)
        if current != ctypes.cast(callback, ctypes.c_void_p).value:
            # Another subclass may still call ours; retain its callback until NCDESTROY.
            return
        _SetWindowLongPtr(hwnd, GWLP_WNDPROC, previous_proc)
    _snap_subclasses.pop(int(hwnd_val), None)
