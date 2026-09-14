# -*- coding: utf-8 -*-
"""WeChat window discovery and restore regression tests."""

from dataclasses import FrozenInstanceError

import pytest

import src.core.window as window_module
import src.core.win32 as win32_module
import src.core.tray as tray_module
from src.core.exceptions import WeChatNotFoundError
from src.core.window import WeChatWindow


def _window(
    *,
    hwnd=101,
    pid=202,
    visible=False,
    window_class="Chrome_WidgetWin_0",
    title="微信",
    bounds=(10, 20, 810, 620),
):
    return win32_module.WindowRef(
        hwnd=hwnd,
        pid=pid,
        process_path=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        window_class=window_class,
        title=title,
        visible=visible,
        bounds=bounds,
    )


def test_window_ref_is_an_immutable_snapshot():
    ref = _window()

    with pytest.raises(FrozenInstanceError):
        ref.visible = True


def test_discovery_selects_hidden_root_window_and_rejects_plugins_and_tray(
    monkeypatch,
):
    windows = {
        11: {
            "pid": 301,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"Weixin.exe" --type=renderer --plugin-name=contacts',
            "class": "Chrome_WidgetWin_0",
            "title": "微信",
            "visible": True,
            "bounds": (0, 0, 1200, 900),
        },
        12: {
            "pid": 302,
            "path": r"C:\Program Files\Tencent\Weixin\WeixinAppEx.exe",
            "command": '"WeixinAppEx.exe"',
            "class": "Qt51514QWindowIcon",
            "title": "微信",
            "visible": True,
            "bounds": (0, 0, 1200, 900),
        },
        13: {
            "pid": 303,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"C:\\Program Files\\Tencent\\Weixin\\Weixin.exe"',
            "class": "WxTrayIconMessageWindow",
            "title": "微信",
            "visible": False,
            "bounds": (0, 0, 0, 0),
        },
        14: {
            "pid": 303,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"C:\\Program Files\\Tencent\\Weixin\\Weixin.exe"',
            "class": "Chrome_WidgetWin_0",
            "title": "微信",
            "visible": False,
            "bounds": (10, 20, 810, 620),
        },
        15: {
            "pid": 404,
            "path": r"C:\Other\QtHelper.exe",
            "command": '"QtHelper.exe"',
            "class": "Qt51514QWindowIcon",
            "title": "微信",
            "visible": True,
            "bounds": (0, 0, 1600, 1000),
        },
        16: {
            "pid": 303,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"C:\\Program Files\\Tencent\\Weixin\\Weixin.exe"',
            "class": "Qt51514WxTrayIconMessageWindowClass",
            "title": "微信",
            "visible": False,
            "bounds": (0, 0, 1900, 1200),
        },
        17: {
            "pid": 303,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"C:\\Program Files\\Tencent\\Weixin\\Weixin.exe"',
            "class": "Qt51514QWindowIcon",
            "title": "添加朋友",
            "visible": True,
            "bounds": (0, 0, 420, 650),
        },
        18: {
            "pid": 303,
            "path": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            "command": '"C:\\Program Files\\Tencent\\Weixin\\Weixin.exe"',
            "class": "SoPY_Status",
            "title": "",
            "visible": True,
            "bounds": (0, 0, 900, 100),
        },
    }

    def enum_windows(callback, context):
        for hwnd in windows:
            callback(hwnd, context)

    monkeypatch.setattr(win32_module.win32gui, "EnumWindows", enum_windows)
    monkeypatch.setattr(
        win32_module.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (9000 + hwnd, windows[hwnd]["pid"]),
    )
    monkeypatch.setattr(
        win32_module,
        "_get_process_image_name",
        lambda pid: next(item["path"] for item in windows.values() if item["pid"] == pid),
    )
    monkeypatch.setattr(
        win32_module,
        "_get_process_command_line",
        lambda pid: next(
            item["command"] for item in windows.values() if item["pid"] == pid
        ),
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetClassName",
        lambda hwnd: windows[hwnd]["class"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetWindowText",
        lambda hwnd: windows[hwnd]["title"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "IsWindowVisible",
        lambda hwnd: windows[hwnd]["visible"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetWindowRect",
        lambda hwnd: windows[hwnd]["bounds"],
    )

    assert win32_module.find_wechat_window_ref() == win32_module.WindowRef(
        hwnd=14,
        pid=303,
        process_path=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        window_class="Chrome_WidgetWin_0",
        title="微信",
        visible=False,
        bounds=(10, 20, 810, 620),
    )
    assert win32_module.find_wechat_window() == 14
    assert win32_module.find_wechat_window_refs(pid=303) == [
        win32_module.WindowRef(
            hwnd=14,
            pid=303,
            process_path=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            window_class="Chrome_WidgetWin_0",
            title="微信",
            visible=False,
            bounds=(10, 20, 810, 620),
        )
    ]


def test_discovery_uses_normal_bounds_for_a_hidden_minimized_main_window(
    monkeypatch,
):
    windows = {
        21: {
            "pid": 303,
            "class": "Qt51514QWindowIcon",
            "title": "微信",
            # Qt can leave WS_VISIBLE set while the native window is iconic at
            # the taskbar placeholder coordinates.
            "visible": True,
            "iconic": True,
            "bounds": (-32000, -32000, -31840, -31972),
            "placement": (
                0,
                win32_module.win32con.SW_SHOWMINIMIZED,
                (-32000, -32000),
                (-1, -1),
                (-1211, 157, -246, 907),
            ),
        },
        22: {
            "pid": 303,
            "class": "Qt51514QWindowIcon",
            "title": "Weixin",
            "visible": False,
            "iconic": False,
            "bounds": (872, 405, 1048, 604),
            "placement": (0, win32_module.win32con.SW_SHOWNORMAL, (-1, -1), (-1, -1), (872, 405, 1048, 604)),
        },
    }

    monkeypatch.setattr(
        win32_module.win32gui,
        "EnumWindows",
        lambda callback, context: [callback(hwnd, context) for hwnd in windows],
    )
    monkeypatch.setattr(
        win32_module.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (9000 + hwnd, windows[hwnd]["pid"]),
    )
    monkeypatch.setattr(
        win32_module,
        "_get_process_image_name",
        lambda _pid: r"D:\Weixin\Weixin.exe",
    )
    monkeypatch.setattr(
        win32_module,
        "_get_process_command_line",
        lambda _pid: r'"D:\Weixin\Weixin.exe"',
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetClassName",
        lambda hwnd: windows[hwnd]["class"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetWindowText",
        lambda hwnd: windows[hwnd]["title"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "IsWindowVisible",
        lambda hwnd: windows[hwnd]["visible"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "IsIconic",
        lambda hwnd: windows[hwnd]["iconic"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetWindowRect",
        lambda hwnd: windows[hwnd]["bounds"],
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "GetWindowPlacement",
        lambda hwnd: windows[hwnd]["placement"],
    )

    assert win32_module.find_wechat_window_ref() == win32_module.WindowRef(
        hwnd=21,
        pid=303,
        process_path=r"D:\Weixin\Weixin.exe",
        window_class="Qt51514QWindowIcon",
        title="微信",
        visible=False,
        bounds=(-1211, 157, -246, 907),
    )


def test_restore_uses_direct_then_tray_then_one_hotkey_and_verifies_same_pid(
    monkeypatch,
):
    initial = _window()
    restored_ref = _window(hwnd=909, visible=True)
    calls = []
    state = {"visible": False}

    monkeypatch.setattr(
        win32_module,
        "_show_window_async",
        lambda hwnd, command: calls.append(("show", hwnd, command)),
    )
    monkeypatch.setattr(
        win32_module,
        "_foreground_with_thread_handshake",
        lambda hwnd: calls.append(("foreground", hwnd)) or True,
    )
    monkeypatch.setattr(
        win32_module,
        "_restore_from_native_tray",
        lambda expected_pid: calls.append(("tray", expected_pid)) or True,
    )

    def hotkey():
        calls.append(("hotkey",))
        state["visible"] = True
        return True

    monkeypatch.setattr(win32_module, "_send_ctrl_alt_w", hotkey)

    def find_ref(*, pid=None, visible=None):
        assert pid == initial.pid
        if visible is True:
            return restored_ref if state["visible"] else None
        if visible is False:
            return None if state["visible"] else initial
        return restored_ref if state["visible"] else initial

    monkeypatch.setattr(win32_module, "find_wechat_window_ref", find_ref)
    monkeypatch.setattr(win32_module, "find_wechat_window_refs", lambda: [initial])

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is True
    assert result.window == restored_ref
    assert [(stage.stage, stage.succeeded) for stage in result.stages] == [
        ("direct", False),
        ("tray", False),
        ("hotkey", True),
    ]
    assert calls == [
        ("show", initial.hwnd, win32_module.SW_SHOW),
        ("show", initial.hwnd, win32_module.SW_RESTORE),
        ("foreground", initial.hwnd),
        ("tray", initial.pid),
        ("hotkey",),
    ]


def test_restore_revalidates_hwnd_ownership_before_direct_show(monkeypatch):
    initial = _window(hwnd=101, pid=202)
    fresh_hidden = _window(hwnd=303, pid=202)
    fresh_visible = _window(hwnd=303, pid=202, visible=True)
    calls = []
    state = {"visible": False}

    def show(hwnd, command):
        calls.append(("show", hwnd, command))
        if hwnd == fresh_hidden.hwnd and command == win32_module.SW_RESTORE:
            state["visible"] = True

    monkeypatch.setattr(win32_module, "_show_window_async", show)
    monkeypatch.setattr(
        win32_module,
        "_foreground_with_thread_handshake",
        lambda hwnd: calls.append(("foreground", hwnd)) or True,
    )
    monkeypatch.setattr(
        win32_module,
        "_restore_from_native_tray",
        lambda _pid: pytest.fail("fresh direct restore should have succeeded"),
    )
    monkeypatch.setattr(
        win32_module,
        "_send_ctrl_alt_w",
        lambda: pytest.fail("fresh direct restore should have succeeded"),
    )

    def find_ref(*, pid=None, visible=None):
        assert pid == initial.pid
        if visible is True:
            return fresh_visible if state["visible"] else None
        if visible is False:
            return None if state["visible"] else fresh_hidden
        return fresh_visible if state["visible"] else fresh_hidden

    monkeypatch.setattr(win32_module, "find_wechat_window_ref", find_ref)

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is True
    assert result.window == fresh_visible
    assert calls == [
        ("show", fresh_hidden.hwnd, win32_module.SW_SHOW),
        ("show", fresh_hidden.hwnd, win32_module.SW_RESTORE),
        ("foreground", fresh_hidden.hwnd),
    ]


def test_restore_revalidates_even_an_initially_visible_snapshot(monkeypatch):
    initial = _window(hwnd=101, pid=202, visible=True)
    fresh_visible = _window(hwnd=303, pid=202, visible=True)
    monkeypatch.setattr(
        win32_module,
        "find_wechat_window_ref",
        lambda *, pid=None, visible=None: (
            fresh_visible if pid == initial.pid and visible is True else None
        ),
    )
    monkeypatch.setattr(
        win32_module,
        "_show_window_async",
        lambda *_args: pytest.fail("an already-visible fresh window needs no restore"),
    )

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is False
    assert result.window == fresh_visible


def test_restore_rejects_a_reused_pid_with_a_different_process_path(monkeypatch):
    initial = _window(hwnd=101, pid=202)
    reused = win32_module.WindowRef(
        hwnd=303,
        pid=202,
        process_path=r"D:\OtherInstall\Weixin.exe",
        window_class=initial.window_class,
        title=initial.title,
        visible=True,
        bounds=initial.bounds,
    )
    monkeypatch.setattr(
        win32_module,
        "find_wechat_window_ref",
        lambda *, pid=None, visible=None: (
            reused if pid == initial.pid and visible is True else None
        ),
    )
    monkeypatch.setattr(
        win32_module,
        "_show_window_async",
        lambda *_args: pytest.fail("a mismatched process path must never be touched"),
    )

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is False
    assert result.window is None


@pytest.mark.parametrize("replacement_stage", ["direct", "tray", "hotkey"])
def test_restore_rejects_path_changed_after_each_restore_action(
    monkeypatch, replacement_stage
):
    initial = _window(hwnd=101, pid=202)
    reused_visible = win32_module.WindowRef(
        hwnd=303,
        pid=initial.pid,
        process_path=r"D:\OtherInstall\Weixin.exe",
        window_class=initial.window_class,
        title=initial.title,
        visible=True,
        bounds=initial.bounds,
    )
    reused_hidden = win32_module.WindowRef(
        hwnd=303,
        pid=initial.pid,
        process_path=reused_visible.process_path,
        window_class=initial.window_class,
        title=initial.title,
        visible=False,
        bounds=initial.bounds,
    )
    state = {"stage": "initial"}

    def show(_hwnd, command):
        if command == win32_module.SW_RESTORE and replacement_stage == "direct":
            state["stage"] = "direct"

    def tray(_pid):
        if replacement_stage == "tray":
            state["stage"] = "tray"
        return True

    def hotkey():
        if replacement_stage == "hotkey":
            state["stage"] = "hotkey"
        return True

    def find_ref(*, pid=None, visible=None):
        assert pid == initial.pid
        if state["stage"] == replacement_stage:
            return reused_visible if visible is True else reused_hidden
        return initial if visible is False else None

    monkeypatch.setattr(win32_module, "_show_window_async", show)
    monkeypatch.setattr(
        win32_module, "_foreground_with_thread_handshake", lambda _hwnd: True
    )
    monkeypatch.setattr(win32_module, "_restore_from_native_tray", tray)
    monkeypatch.setattr(win32_module, "_send_ctrl_alt_w", hotkey)
    monkeypatch.setattr(win32_module, "find_wechat_window_ref", find_ref)
    monkeypatch.setattr(win32_module, "find_wechat_window_refs", lambda: [initial])

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is False
    assert result.window is None
    assert result.stages[-1].stage == replacement_stage
    assert result.stages[-1].succeeded is False


def test_restore_skips_global_hotkey_when_another_root_weixin_pid_exists(
    monkeypatch,
):
    initial = _window(hwnd=101, pid=202)
    competitor = _window(hwnd=404, pid=505)

    monkeypatch.setattr(win32_module, "_show_window_async", lambda *_args: None)
    monkeypatch.setattr(
        win32_module, "_foreground_with_thread_handshake", lambda _hwnd: False
    )
    monkeypatch.setattr(win32_module, "_restore_from_native_tray", lambda _pid: False)
    monkeypatch.setattr(
        win32_module,
        "_send_ctrl_alt_w",
        lambda: pytest.fail("a global hotkey may restore the competing Weixin PID"),
    )
    monkeypatch.setattr(
        win32_module, "find_wechat_window_refs", lambda: [initial, competitor]
    )

    def find_ref(*, pid=None, visible=None):
        assert pid == initial.pid
        return initial if visible is False else None

    monkeypatch.setattr(win32_module, "find_wechat_window_ref", find_ref)

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is False
    assert result.window == initial
    assert result.stages[-1].stage == "hotkey"
    assert result.stages[-1].attempted is False
    assert "multiple root PIDs" in result.stages[-1].detail


def test_native_tray_restore_posts_only_to_the_expected_weixin_pid(monkeypatch):
    expected = tray_module._TrayButton(
        toolbar_hwnd=1,
        index=0,
        id_command=10,
        dw_data=20,
        hwnd=101,
        uid=30,
        callback_msg=40,
        exe_path=r"C:\Weixin\Weixin.exe",
        title="微信",
        class_name="WxTrayIconMessageWindow",
    )
    other = tray_module._TrayButton(
        toolbar_hwnd=1,
        index=1,
        id_command=11,
        dw_data=21,
        hwnd=202,
        uid=31,
        callback_msg=41,
        exe_path=r"C:\Weixin\Weixin.exe",
        title="微信",
        class_name="WxTrayIconMessageWindow",
    )
    posts = []
    monkeypatch.setattr(
        tray_module, "_find_wechat_native_tray_buttons", lambda: [other, expected]
    )
    monkeypatch.setattr(
        tray_module.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (1, 505 if hwnd == other.hwnd else 202),
    )
    monkeypatch.setattr(
        tray_module.win32gui,
        "PostMessage",
        lambda *args: posts.append(args),
    )
    monkeypatch.setattr(tray_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        tray_module,
        "_is_wechat_main_window_visible",
        lambda expected_pid=None: expected_pid == 202,
    )

    assert tray_module.restore_wechat_from_native_tray(
        wait_after_event=0, expected_pid=202
    ) is True
    assert posts == [
        (
            expected.hwnd,
            expected.callback_msg,
            expected.uid,
            tray_module.TRAY_RESTORE_EVENTS[0][1],
        )
    ]


def test_restore_does_not_send_hotkey_if_same_pid_hidden_window_disappears(
    monkeypatch,
):
    initial = _window()
    hidden_checks = iter([initial, initial, None])

    monkeypatch.setattr(win32_module, "_show_window_async", lambda *_args: None)
    monkeypatch.setattr(
        win32_module, "_foreground_with_thread_handshake", lambda _hwnd: True
    )
    monkeypatch.setattr(win32_module, "_restore_from_native_tray", lambda _pid: True)
    monkeypatch.setattr(
        win32_module,
        "_send_ctrl_alt_w",
        lambda: pytest.fail("hotkey requires a confirmed hidden window for the same PID"),
    )

    def find_ref(*, pid=None, visible=None):
        assert pid == initial.pid
        if visible is True:
            return None
        if visible is False:
            return next(hidden_checks)
        return None

    monkeypatch.setattr(win32_module, "find_wechat_window_ref", find_ref)

    result = win32_module.restore_wechat_window(initial, settle_timeout=0)

    assert result.restored is False
    assert result.window is None
    assert [stage.stage for stage in result.stages] == ["direct", "tray"]
    assert "no longer" in result.stages[-1].detail


def test_foreground_handshake_attaches_and_always_detaches_input_threads(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(win32_module.win32gui, "GetForegroundWindow", lambda: 88)
    monkeypatch.setattr(
        win32_module.win32process,
        "GetWindowThreadProcessId",
        lambda hwnd: (22, 1) if hwnd == 77 else (33, 2),
    )
    monkeypatch.setattr(win32_module, "_get_current_thread_id", lambda: 11)
    monkeypatch.setattr(
        win32_module,
        "_attach_thread_input",
        lambda left, right, attach: calls.append(("attach", left, right, attach)) or True,
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "BringWindowToTop",
        lambda hwnd: calls.append(("top", hwnd)),
    )
    monkeypatch.setattr(
        win32_module.win32gui,
        "SetForegroundWindow",
        lambda hwnd: calls.append(("foreground", hwnd)),
    )

    assert win32_module._foreground_with_thread_handshake(77) is True
    assert calls == [
        ("attach", 11, 33, True),
        ("attach", 11, 22, True),
        ("top", 77),
        ("foreground", 77),
        ("attach", 11, 22, False),
        ("attach", 11, 33, False),
    ]


def test_activate_hidden_window_uses_win32_fallback_after_tray_restore_fails(monkeypatch):
    manager = WeChatWindow()
    fallback_calls = []
    visibility = iter([False, True])

    monkeypatch.setattr(manager, "_restore_via_tray_icon", lambda: False)
    monkeypatch.setattr(window_module, "is_window_visible", lambda hwnd: next(visibility, True))
    monkeypatch.setattr(
        window_module,
        "bring_window_to_front",
        lambda hwnd: fallback_calls.append(hwnd) or True,
    )

    assert manager._activate_hwnd(12345) is True
    assert fallback_calls == [12345]


def test_connect_stops_when_wechat_window_stays_invisible(monkeypatch):
    manager = WeChatWindow()

    monkeypatch.setattr(window_module, "check_and_fix_registry", lambda: "unchanged")
    monkeypatch.setattr(window_module, "ensure_screen_reader_flag", lambda: False)
    monkeypatch.setattr(window_module, "find_wechat_window", lambda: 12345)
    monkeypatch.setattr(WeChatWindow, "_activate_hwnd", lambda self, hwnd: False)
    monkeypatch.setattr(window_module, "is_window_visible", lambda hwnd: False)
    monkeypatch.setattr(window_module, "get_window_class", lambda hwnd: "Qt51514QWindowIcon")
    monkeypatch.setattr(WeChatWindow, "_try_click_login_button", lambda self, hwnd: False)
    monkeypatch.setattr(
        window_module,
        "UIAWrapper",
        lambda hwnd: pytest.fail("connect() should not initialize UIA for an invisible window"),
    )

    with pytest.raises(WeChatNotFoundError, match="不可见|无法恢复"):
        manager.connect()
