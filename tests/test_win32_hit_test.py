# -*- coding: utf-8 -*-
"""Win32 frameless window hit-test tests."""

from app import win32_helper as wh
import ctypes
from types import SimpleNamespace
import pytest


def test_hit_test_detects_resize_borders():
    metrics = wh.FramelessHitTestMetrics(client_width=960, client_height=780)

    assert wh.hit_test_client_point(2, 2, metrics) == wh.HTTOPLEFT
    assert wh.hit_test_client_point(958, 2, metrics) == wh.HTTOPRIGHT
    assert wh.hit_test_client_point(2, 778, metrics) == wh.HTBOTTOMLEFT
    assert wh.hit_test_client_point(958, 778, metrics) == wh.HTBOTTOMRIGHT
    assert wh.hit_test_client_point(2, 120, metrics) == wh.HTLEFT
    assert wh.hit_test_client_point(958, 120, metrics) == wh.HTRIGHT
    assert wh.hit_test_client_point(120, 2, metrics) == wh.HTTOP
    assert wh.hit_test_client_point(120, 778, metrics) == wh.HTBOTTOM


def test_hit_test_maps_custom_titlebar_regions():
    metrics = wh.FramelessHitTestMetrics(client_width=960, client_height=780)

    assert wh.hit_test_client_point(500, 20, metrics) == wh.HTCAPTION
    assert wh.hit_test_client_point(890, 20, metrics) == wh.HTCLIENT
    assert wh.hit_test_client_point(700, 20, metrics) == wh.HTCLIENT
    assert wh.hit_test_client_point(930, 20, metrics) == wh.HTCLIENT
    assert wh.hit_test_client_point(300, 80, metrics) == wh.HTCLIENT


def test_hit_test_scales_qml_metrics_for_high_dpi():
    metrics = wh.FramelessHitTestMetrics(
        client_width=1920,
        client_height=1560,
        dpi_scale=2.0,
    )

    assert wh.hit_test_client_point(1000, 40, metrics) == wh.HTCAPTION
    assert wh.hit_test_client_point(1780, 40, metrics) == wh.HTCLIENT
    assert wh.hit_test_client_point(1400, 40, metrics) == wh.HTCLIENT


def test_install_api_is_available_without_restoring_native_titlebar():
    assert hasattr(wh, "install_frameless_window_hit_test")
    assert wh.FRAMELESS_SNAP_STYLE_MASK & wh.WS_THICKFRAME
    assert not (wh.FRAMELESS_SNAP_STYLE_MASK & wh.WS_CAPTION)


def test_native_frame_style_keeps_resize_without_duplicate_caption():
    assert not wh.NATIVE_FRAME_STYLE_MASK & wh.WS_CAPTION
    assert wh.NATIVE_FRAME_STYLE_MASK & wh.WS_THICKFRAME
    assert wh.NATIVE_FRAME_STYLE_MASK & wh.WS_MINIMIZEBOX
    assert wh.NATIVE_FRAME_STYLE_MASK & wh.WS_MAXIMIZEBOX


def test_maximized_and_fullscreen_do_not_offer_resize_borders():
    metrics = wh.FramelessHitTestMetrics(960, 680, resizable=False)
    assert wh.hit_test_client_point(959, 20, metrics) == wh.HTCLIENT
    assert wh.hit_test_client_point(2, 2, metrics) == wh.HTCAPTION
    fullscreen = wh.FramelessHitTestMetrics(960, 680, resizable=False, title_bar_height=0)
    assert wh.hit_test_client_point(2, 2, fullscreen) == wh.HTCLIENT


@pytest.mark.parametrize("rounded,expected", [(True, 2), (False, 1)])
def test_corner_preference_uses_dwm_attribute_33(monkeypatch, rounded, expected):
    calls = []
    def set_attribute(hwnd, attribute, value, size):
        calls.append((hwnd.value, attribute.value,
                      ctypes.cast(value, ctypes.POINTER(ctypes.c_int)).contents.value, size))
        return 0
    monkeypatch.setattr(wh, "dwmapi", SimpleNamespace(DwmSetWindowAttribute=set_attribute))
    assert wh.set_window_corner_preference(123, rounded)
    assert calls == [(123, 33, expected, ctypes.sizeof(ctypes.c_int))]


def test_corner_preference_failure_is_nonfatal(monkeypatch):
    monkeypatch.setattr(wh, "dwmapi", None)
    assert not wh.set_window_corner_preference(123, True)
    assert not wh.set_window_corner_preference(0, True)


@pytest.mark.skipif(wh.WNDPROC is None, reason="Windows callback ABI")
def test_native_hook_keeps_qml_buttons_client_and_releases_on_destroy(monkeypatch):
    styles = []
    api = SimpleNamespace(SetWindowPos=lambda *a: 1, IsWindow=lambda *a: True,
                          CallWindowProcW=lambda *a: 42)
    monkeypatch.setattr(wh, "user32", api)
    monkeypatch.setattr(wh, "_GetWindowLongPtr", lambda hwnd, index: 555 if index == wh.GWLP_WNDPROC else wh.WS_THICKFRAME)
    monkeypatch.setattr(wh, "_SetWindowLongPtr", lambda hwnd, index, value: styles.append((index, value)) or 555)
    monkeypatch.setattr(wh, "_hit_test_lparam", lambda *a: wh.HTCLIENT)
    monkeypatch.setattr(wh, "_snap_subclasses", {})
    assert wh.install_native_window_hit_test(123)
    assert not styles[0][1] & wh.WS_CAPTION
    assert wh.install_native_window_hit_test(123)
    callback = wh._snap_subclasses[123][0]
    assert callback(123, wh.WM_NCHITTEST, 0, 0) == wh.HTCLIENT
    started = []
    wh.set_window_interaction_callback(123, lambda: started.append(True))
    callback(123, wh.WM_ENTERSIZEMOVE, 0, 0)
    assert started == [True]
    assert callback(123, wh.WM_NCDESTROY, 0, 0) == 42
    assert 123 not in wh._snap_subclasses
    assert 123 not in wh._interaction_callbacks


@pytest.mark.skipif(wh.WNDPROC is None, reason="Windows callback ABI")
def test_native_frame_clipping_and_maximize_respect_work_area(monkeypatch):
    zoomed = False
    caption = wh.WS_THICKFRAME
    forwarded = []
    def monitor_info(handle, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(wh.MONITORINFO)).contents
        info.rcMonitor = wh.wintypes.RECT(-1920, 0, 0, 1080)
        info.rcWork = wh.wintypes.RECT(-1920, 40, 0, 1080)
        return True
    api = SimpleNamespace(SetWindowPos=lambda *a: 1, IsZoomed=lambda *a: zoomed,
                          MonitorFromWindow=lambda *a: 12, GetMonitorInfoW=monitor_info,
                          CallWindowProcW=lambda *a: forwarded.append(a) or 0)
    monkeypatch.setattr(wh, "user32", api)
    monkeypatch.setattr(wh, "_window_dpi_scale", lambda *a: 1.5)
    monkeypatch.setattr(wh, "native_resize_inset", lambda dpi: 12)
    monkeypatch.setattr(wh, "_GetWindowLongPtr", lambda hwnd, index: 555 if index == wh.GWLP_WNDPROC else caption)
    monkeypatch.setattr(wh, "_SetWindowLongPtr", lambda *a: 555)
    monkeypatch.setattr(wh, "_snap_subclasses", {})
    assert wh.install_native_window_hit_test(123)
    callback = wh._snap_subclasses[123][0]
    rect = wh.wintypes.RECT(0, 0, 960, 680)
    callback(123, wh.WM_NCCALCSIZE, 1, ctypes.addressof(rect))
    assert (rect.left, rect.top, rect.right, rect.bottom) == (1, 1, 959, 679)
    zoomed = True
    rect = wh.wintypes.RECT(-12, -12, 1932, 1052)
    callback(123, wh.WM_NCCALCSIZE, 1, ctypes.addressof(rect))
    assert (rect.left, rect.top, rect.right, rect.bottom) == (0, 0, 1920, 1040)
    caption = 0
    rect = wh.wintypes.RECT(0, 0, 1920, 1080)
    callback(123, wh.WM_NCCALCSIZE, 1, ctypes.addressof(rect))
    assert (rect.left, rect.top, rect.right, rect.bottom) == (0, 0, 1920, 1080)
    info = wh.MINMAXINFO()
    callback(123, wh.WM_GETMINMAXINFO, 0, ctypes.addressof(info))
    assert (info.ptMaxPosition.x, info.ptMaxPosition.y) == (-12, 28)
    assert (info.ptMaxSize.x, info.ptMaxSize.y) == (1944, 1064)
    count = len(forwarded)
    callback(123, wh.WM_NCPAINT, 0, 0)
    assert len(forwarded) == count
    callback(123, wh.WM_NCACTIVATE, 1, 0)
    assert forwarded[-1][-1] == -1


@pytest.mark.skipif(wh.WNDPROC is None, reason="Windows callback ABI")
def test_uninstall_only_restores_our_own_hook(monkeypatch):
    callback = wh.WNDPROC(lambda *a: 0)
    address = ctypes.cast(callback, ctypes.c_void_p).value
    restored = []
    monkeypatch.setattr(wh, "_snap_subclasses", {123: (callback, 555)})
    monkeypatch.setattr(wh, "user32", SimpleNamespace(IsWindow=lambda *a: True))
    monkeypatch.setattr(wh, "_GetWindowLongPtr", lambda *a: address)
    monkeypatch.setattr(wh, "_SetWindowLongPtr", lambda *a: restored.append(a) or address)
    wh.uninstall_window_hit_test(123)
    wh.uninstall_window_hit_test(123)
    assert len(restored) == 1
    assert restored[0][-1] == 555
