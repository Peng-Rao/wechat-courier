from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from app.agent.retry import AutomationRetryError, WeixinUnresponsiveError
from app.agent.uia_query import ScopedQueryUnavailable
from app.agent.waiters import ActionDeadlineExceeded, action_deadline
from src.core.win32 import WindowRef


@pytest.fixture
def tray(monkeypatch):
    from app.agent import tray_restore as module

    initial = WindowRef(101, 202, r"C:\Weixin\Weixin.exe", "Qt51514QWindowIcon",
                        "Weixin", False, (0, 0, 600, 400))
    state = NS(window=initial, visible=False, enabled=True, started="started",
               foreground=999, overflow=False, windows10=False)
    events = []
    taskbar = NS(NativeWindowHandle=301, ProcessId=302)
    overflow = NS(NativeWindowHandle=401, ProcessId=302)
    controls = {301: [], 401: []}

    def button(name, invoke):
        return NS(Name=name, ProcessId=302, ControlTypeName="ButtonControl",
                  IsEnabled=True, IsOffscreen=False,
                  GetInvokePattern=lambda: NS(Invoke=invoke) if invoke else None)

    def show_overflow():
        events.append("overflow")
        state.overflow = True

    def restore():
        events.append("invoke")
        state.visible = True

    controls[301] = [button("显示隐藏的图标", show_overflow)]
    controls[401] = [button(" 微信", restore)]

    def find_window(class_name, title):
        return {"Shell_TrayWnd": 301,
                "TopLevelWindowForOverflowXamlIsland": 401 if state.overflow else 0}.get(class_name, 0)

    def visible(hwnd):
        return state.visible if hwnd == state.window.hwnd else hwnd == 301 or state.overflow

    def from_handle(hwnd):
        assert hwnd in (301, 401), "Qt root must not be queried during tray restoration"
        events.append(("root", hwnd))
        return taskbar if hwnd == 301 else overflow

    def find_all(root, **selector):
        events.append(("query", root.NativeWindowHandle))
        return [c for c in controls[root.NativeWindowHandle]
                if c.Name in selector["name"]]

    def no_input(*args, **kwargs):
        pytest.fail("Unexpected input or broad desktop operation")

    monkeypatch.setattr(module.win32gui, "FindWindow", find_window)
    monkeypatch.setattr(module.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(module.win32gui, "IsWindowVisible", visible)
    monkeypatch.setattr(module.win32gui, "IsWindowEnabled", lambda hwnd: state.enabled if hwnd == state.window.hwnd else True)
    monkeypatch.setattr(module.win32gui, "GetClassName", lambda hwnd: (
        "Shell_TrayWnd" if hwnd == 301 else "TopLevelWindowForOverflowXamlIsland"))
    monkeypatch.setattr(module.win32process, "GetWindowThreadProcessId", lambda hwnd: (
        1, state.window.pid if hwnd == state.window.hwnd else 302))
    monkeypatch.setattr(module.win32, "_get_process_image_name", lambda pid: r"C:\Windows\explorer.exe")
    monkeypatch.setattr(module.win32, "find_wechat_window_refs", lambda: [replace(state.window, visible=state.visible)])
    monkeypatch.setattr(module.win32gui, "ShowWindow", no_input)
    monkeypatch.setattr(module.win32, "_show_window_async", no_input)
    monkeypatch.setattr(module.win32gui, "EnumWindows", no_input)
    monkeypatch.setattr(module.win32, "_send_ctrl_alt_w", no_input)
    monkeypatch.setattr(module, "_is_windows10", lambda: state.windows10)
    monkeypatch.setattr(module.native_tray, "_find_wechat_native_tray_buttons", lambda: [])
    monkeypatch.setattr(module.win32gui, "PostMessage", no_input)
    backend = NS(process_start_time=lambda pid: state.started,
                 window_responsive=lambda *args, **kwargs: True)
    waiter = NS(wait=lambda predicate, *args, **kwargs: predicate())
    uia = NS(ControlFromHandle=from_handle)
    query = NS(find_all=find_all)

    def run():
        return module.restore_hidden_window(initial, uia=uia, query=query,
                                            backend=backend, waiter=waiter, timeout=0.01)

    return NS(module=module, initial=initial, state=state, events=events,
              controls=controls, button=button, backend=backend, run=run, query=query)


def test_hidden_restore_invokes_overflow_and_unique_wechat_once(tray):
    result = tray.run()
    assert result.window.hwnd == 101
    assert result.window.pid == 202
    assert result.restored is True
    assert tray.events.count("overflow") == tray.events.count("invoke") == 1
    assert {e[1] for e in tray.events if isinstance(e, tuple) and e[0] == "root"} == {301, 401}


def test_already_visible_does_not_touch_explorer(tray):
    tray.state.visible = True
    assert tray.run().restored is False
    assert tray.events == []


def test_duplicate_wechat_icons_fail_without_any_target_input(tray):
    tray.controls[401].append(tray.button("微信", lambda: pytest.fail("ambiguous invoke")))
    with pytest.raises(AutomationRetryError) as exc:
        tray.run()
    assert exc.value.recoverable is False
    assert "invoke" not in tray.events


def test_no_invoke_uses_only_verified_hidden_hotkey(tray, monkeypatch):
    tray.controls[401] = [tray.button(" 微信", None)]

    def hotkey():
        tray.events.append("hotkey")
        tray.state.visible = True
        return True

    monkeypatch.setattr(tray.module.win32, "_send_ctrl_alt_w", hotkey)
    assert tray.run().restored is True
    assert tray.events.count("hotkey") == 1
    assert "invoke" not in tray.events


def test_invoke_without_restoration_never_repeats_or_falls_back(tray):
    tray.controls[401] = [tray.button(" 微信", lambda: tray.events.append("invoke"))]
    with pytest.raises(AutomationRetryError) as exc:
        tray.run()
    assert exc.value.recoverable is False
    assert tray.events.count("invoke") == 1


def test_invoke_exception_is_uncertain_and_never_falls_back(tray):
    def invoke():
        tray.events.append("invoke")
        raise RuntimeError("provider failed after dispatch")

    tray.controls[401] = [tray.button(" 微信", invoke)]
    with pytest.raises(AutomationRetryError):
        tray.run()
    assert tray.events.count("invoke") == 1


@pytest.mark.parametrize("error", [ActionDeadlineExceeded, WeixinUnresponsiveError])
def test_query_stop_error_cannot_fall_back(tray, error):
    tray.query.find_all = lambda *a, **kw: (_ for _ in ()).throw(error("stop"))
    with pytest.raises(error):
        tray.run()
    assert "overflow" not in tray.events


def test_expired_deadline_prevents_all_operations(tray):
    with pytest.raises(ActionDeadlineExceeded), action_deadline(0):
        tray.run()
    assert tray.events == []


def test_unresponsive_shell_is_checked_before_uia_root(tray):
    tray.backend.window_responsive = lambda hwnd, **kw: hwnd == 101
    with pytest.raises(AutomationRetryError):
        tray.run()
    assert tray.events == []


def test_same_process_new_hwnd_is_accepted_after_tray_invoke(tray):
    def invoke():
        tray.events.append("invoke")
        tray.state.window = replace(tray.initial, hwnd=102)
        tray.state.visible = True

    tray.controls[401] = [tray.button(" 微信", invoke)]
    assert tray.run().window.hwnd == 102


def test_restoration_uses_new_visible_hwnd_when_old_hidden_hwnd_still_exists(tray, monkeypatch):
    restored = replace(tray.initial, hwnd=102, visible=True)

    def refs():
        return [tray.initial, restored] if tray.state.visible else [tray.initial]

    monkeypatch.setattr(tray.module.win32, "find_wechat_window_refs", refs)
    monkeypatch.setattr(tray.module.win32process, "GetWindowThreadProcessId", lambda hwnd: (
        1, 202 if hwnd in (101, 102) else 302))
    monkeypatch.setattr(tray.module.win32gui, "IsWindowVisible", lambda hwnd: (
        tray.state.visible if hwnd == 102 else False if hwnd == 101 else hwnd == 301 or tray.state.overflow))
    assert tray.run().window.hwnd == 102


def test_deadline_expiring_in_pattern_getter_prevents_invoke_and_fallback(tray):
    from app.agent.waiters import _deadline

    target = tray.controls[401][0]
    get_pattern = target.GetInvokePattern

    def pattern():
        _deadline.set(0)
        return get_pattern()

    target.GetInvokePattern = pattern
    with action_deadline():
        with pytest.raises(ActionDeadlineExceeded):
            tray.run()
        _deadline.set(None)
    assert "invoke" not in tray.events


def test_native_callback_preserves_stop_error(tray, monkeypatch):
    tray.state.windows10 = True
    tray.controls[301] = []
    monkeypatch.setattr(tray.module.native_tray, "_find_wechat_native_tray_buttons", lambda: [
        NS(hwnd=101, uid=7, callback_msg=1025)])
    monkeypatch.setattr(tray.module.win32gui, "PostMessage", lambda *a: (
        _ for _ in ()).throw(ActionDeadlineExceeded("expired")))
    with pytest.raises(ActionDeadlineExceeded):
        tray.run()


@pytest.mark.parametrize("change", ["pid", "start", "disabled"])
def test_restoration_rejects_changed_identity_or_disabled_window(tray, change):
    def invoke():
        tray.state.visible = True
        if change == "pid":
            tray.state.window = replace(tray.initial, pid=909)
        elif change == "start":
            tray.state.started = "restarted"
        else:
            tray.state.enabled = False

    tray.controls[401] = [tray.button(" 微信", invoke)]
    with pytest.raises(AutomationRetryError):
        tray.run()


def test_degraded_uia_windows10_uses_one_native_callback(tray, monkeypatch):
    tray.state.windows10 = True
    tray.query.find_all = lambda *a, **kw: (_ for _ in ()).throw(ScopedQueryUnavailable("no UIA"))
    monkeypatch.setattr(tray.module.native_tray, "_find_wechat_native_tray_buttons", lambda: [
        NS(hwnd=101, uid=7, callback_msg=1025)])

    def post(*args):
        tray.events.append(("callback", args))
        tray.state.visible = True

    monkeypatch.setattr(tray.module.win32gui, "PostMessage", post)
    assert tray.run().restored is True
    assert sum(e[0] == "callback" for e in tray.events if isinstance(e, tuple)) == 1
    assert "invoke" not in tray.events


def test_native_callback_without_restore_cannot_send_hotkey(tray, monkeypatch):
    tray.state.windows10 = True
    tray.controls[301] = []
    monkeypatch.setattr(tray.module.native_tray, "_find_wechat_native_tray_buttons", lambda: [
        NS(hwnd=101, uid=7, callback_msg=1025)])
    monkeypatch.setattr(tray.module.win32gui, "PostMessage", lambda *a: tray.events.append("callback"))
    with pytest.raises(AutomationRetryError):
        tray.run()
    assert tray.events.count("callback") == 1


def test_hotkey_refused_when_other_wechat_process_exists(tray, monkeypatch):
    tray.controls[301] = []
    monkeypatch.setattr(tray.module.win32, "find_wechat_window_refs", lambda: [
        tray.initial, replace(tray.initial, hwnd=505, pid=606)])
    with pytest.raises(AutomationRetryError):
        tray.run()
    assert "invoke" not in tray.events
