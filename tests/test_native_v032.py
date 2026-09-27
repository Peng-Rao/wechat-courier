from types import SimpleNamespace as NS

import pytest

from app.agent.native_driver import NativeWeixinDriver, safe_attr
from app.agent.profile import get_weixin_profile
from app.agent.retry import AutomationRetryError, WeixinUnresponsiveError


def fail(*args, **kwargs):
    pytest.fail("Unexpected external operation")


@pytest.fixture
def driver(monkeypatch):
    profile = get_weixin_profile("4.1.13.65")
    state = dict(hwnd=101, pid=202, windowState="visible", restorable=False,
                 windowEnabled=True, blockingWindow=None)
    backend = NS(
        window_inspection=lambda: dict(state),
        process_start_time=lambda pid: "started",
        find_module=lambda *args: NS(path="mock.dll"),
        file_version=lambda path: profile.version,
        window_responsive=lambda *args, **kwargs: True,
        prepare_main_window=lambda: NS(window=NS(hwnd=state["hwnd"], pid=202, visible=True)),
    )
    result = NativeWeixinDriver(gate_backend=backend, timeout=0.01)
    result._session = NS(hwnd=101, pid=202, version=profile.version,
                         process_start_time="started", profile=profile, close=fail)
    result._uia_initialized = True
    result._lease_checked = True
    result.state = state
    result.roots = []

    def root(hwnd):
        value = NS(ClassName=profile.main_root_class, ControlTypeName="WindowControl",
                   NativeWindowHandle=hwnd, ProcessId=202, IsOffscreen=False,
                   BoundingRectangle=NS(left=0, top=0, right=600, bottom=400))
        result.roots.append(value)
        return value

    result._uia = NS(ControlFromHandle=root)
    result._query = NS(find_all=lambda *args, **kwargs: [NS()])
    result._root = root(101)
    result._waiter = NS(wait=lambda predicate, *args, **kwargs: predicate())
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", lambda *args: None)
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda hwnd: True)
    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", lambda hwnd: True)
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd == result.state["hwnd"])
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr("win32gui.IsWindowEnabled", lambda hwnd: result.state["windowEnabled"])
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: result.state["hwnd"])
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    return result


def test_same_process_hwnd_rebind_retains_gate_lease(driver):
    session = driver._session
    driver.state["hwnd"] = 303
    driver._prepare_existing_session()
    assert driver._session is session
    assert session.hwnd == 303
    assert driver._root is None


def test_verified_task_health_preserves_main_disabled_state_without_uia_queries(driver, monkeypatch):
    driver._uia.ControlFromHandle = fail
    driver._query.find_all = fail
    driver.state.update(windowEnabled=False, blockingWindow={"hwnd": 404, "pid": 202})
    monkeypatch.setattr("win32gui.IsWindowEnabled", lambda hwnd: hwnd == 404)
    health = driver.verified_task_health("friend_request", 404)
    assert health["sessionReady"] and health["taskWindowReady"]
    assert health["windowEnabled"] is False
    assert health["taskWindowRole"] == "friend_request"
    from app.agent.native_driver import WindowBlockedError
    with pytest.raises(WindowBlockedError):
        driver.verified_task_health("friend_search", 303)
    monkeypatch.setattr("win32gui.IsWindowEnabled", lambda hwnd: False)
    with pytest.raises(WindowBlockedError):
        driver.verified_task_health("friend_request", 404)


def test_stop_before_native_bind_keeps_tray_window_restorable_without_creating_session(driver):
    from app.agent.runtime import TaskControl
    from app.agent.workflows import WeixinWorkflowEngine
    from tests.test_task_stop_recovery import make_request

    driver._session = None
    driver._uia.ControlFromHandle = fail
    driver._gate_backend.prepare_main_window = fail
    driver.state.update(windowState="hidden", restorable=True)
    control = TaskControl()
    control.request_stop()
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver)
    initial = engine.inspect()
    result = engine.run(make_request(), control, lambda *_: None)

    assert initial["restorable"] is True
    assert result["cleanup"]["success"] is True
    assert result["health"]["restorable"] is True
    assert result["health"]["windowResponsive"] is True
    assert result["health"]["windowEnabled"] is True
    assert result["health"]["reasonCode"] == ""
    assert result["health"]["sequence"] > initial["sequence"]
    assert driver._session is None


@pytest.mark.parametrize("state,code", [
    ({"windowEnabled": False}, "WINDOW_DISABLED"),
    ({"blockingWindow": {"hwnd": 404, "pid": 202}}, "WINDOW_BLOCKED"),
    ({"responsive": False}, "WECHAT_UNRESPONSIVE"),
])
def test_unbound_native_stop_preflight_rejects_unsafe_discovered_window(driver, state, code):
    from app.agent.runtime import TaskControl
    from app.agent.workflows import WeixinWorkflowEngine
    from tests.test_task_stop_recovery import make_request

    driver._session = None
    driver._uia.ControlFromHandle = fail
    driver._gate_backend.prepare_main_window = fail
    driver._gate_backend.find_module = fail
    driver.state.update(state)
    driver._gate_backend.window_responsive = lambda *_args, **_kwargs: state.get("responsive", True)
    control = TaskControl()
    control.request_stop()
    result = WeixinWorkflowEngine(driver_factory=lambda: driver).run(make_request(), control, lambda *_: None)

    assert result["cleanup"]["success"] is True
    assert result["health"]["sessionReady"] is False
    assert result["health"]["reasonCode"] == code


def test_each_task_bind_gets_fresh_main_root(driver):
    old = driver._root
    driver.bind_window()
    assert driver._root is not old
    previous = driver._root
    driver.bind_window()
    assert driver._root is not previous


def test_bind_main_uses_handshake_when_gui_has_foreground(driver, monkeypatch):
    foreground = [999]
    session = driver._session
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda hwnd: False)
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: foreground[0])

    def handshake(hwnd):
        foreground[0] = hwnd
        return True

    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", handshake)
    assert driver.bind_window()["connected"] is True
    assert foreground[0] == 101
    assert driver._session is session


def test_bind_main_rejects_handshake_true_without_foreground(driver, monkeypatch):
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: 999)
    with pytest.raises(AutomationRetryError) as exc:
        driver.bind_window()
    assert exc.value.code == "TRANSIENT_UI"


@pytest.mark.parametrize("change", ["pid", "start", "hwnd", "disabled", "hung"])
def test_bind_main_revalidates_identity_and_health_after_handshake(driver, monkeypatch, change):
    foreground = [999]
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: foreground[0])

    def handshake(hwnd):
        foreground[0] = hwnd
        if change == "pid":
            monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 909))
        elif change == "start":
            driver._gate_backend.process_start_time = lambda pid: "restarted"
        elif change == "hwnd":
            driver._session.hwnd = 303
        elif change == "disabled":
            driver.state["windowEnabled"] = False
        else:
            driver._gate_backend.window_responsive = lambda *args, **kwargs: False
        return True

    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", handshake)
    with pytest.raises(AutomationRetryError):
        driver.bind_window()


def test_bind_main_rechecks_foreground_after_root_bounds(driver, monkeypatch):
    foreground = [101]
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: foreground[0])

    def visible_bounds():
        foreground[0] = 999
        return True

    driver._visible_root_bounds = visible_bounds
    with pytest.raises(AutomationRetryError) as exc:
        driver.bind_window()
    assert exc.value.code == "TRANSIENT_UI"


@pytest.mark.parametrize("fresh_session", [False, True])
def test_bind_restores_qt_hidden_before_legacy_prepare_using_same_com(driver, monkeypatch, fresh_session):
    from app.agent.gate import NativeGateBackend
    from src.core.win32 import WindowRef, WindowRestoreResult

    backend = NativeGateBackend()
    backend.__dict__.update(vars(driver._gate_backend))
    driver._gate_backend = backend
    initial = WindowRef(101, 202, "mock.exe", "Qt51514QWindowIcon", "Weixin",
                        False, (0, 0, 600, 400))
    backend.discover_main_window = lambda: initial
    visible = [False]
    events = []
    uia, query, session = driver._uia, driver._query, driver._session
    root_factory = uia.ControlFromHandle

    def root(hwnd):
        assert visible[0], "Qt root queried before tray restoration"
        events.append("qt-root")
        return root_factory(hwnd)

    uia.ControlFromHandle = root

    def restore(window, **kwargs):
        assert kwargs["uia"] is uia
        assert kwargs["query"] is query
        events.append("tray")
        visible[0] = True
        restored = WindowRef(101, 202, "mock.exe", "Qt51514QWindowIcon", "Weixin",
                             True, initial.bounds)
        return WindowRestoreResult(window, restored, True)

    def prepare():
        assert visible[0], "Legacy direct ShowWindow path reached while Qt was hidden"
        events.append("prepare")
        return NS(window=NS(hwnd=101, pid=202, visible=True))

    backend.prepare_main_window = prepare
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: visible[0])
    monkeypatch.setattr("app.agent.tray_restore.restore_hidden_window", restore)
    monkeypatch.setattr("src.core.uiautomation.InitializeUIAutomationInCurrentThread", fail)
    monkeypatch.setattr("src.core.uiautomation.UninitializeUIAutomationInCurrentThread", fail)
    if fresh_session:
        driver._session = None
        session.__enter__ = lambda: prepare()
        monkeypatch.setattr("app.agent.native_driver.WeixinAccessibilitySession", lambda *a, **kw: session)
    assert driver.bind_window()["connected"] is True
    assert events[0] == "tray"
    assert events.index("prepare") < events.index("qt-root")
    assert driver._uia is uia
    assert driver._session is session


def test_failed_qt_tray_restore_cannot_reach_direct_prepare_or_qt_root(driver, monkeypatch):
    from app.agent.gate import NativeGateBackend
    from app.agent.tray_restore import TrayRestoreError
    from src.core.win32 import WindowRef

    backend = NativeGateBackend()
    backend.__dict__.update(vars(driver._gate_backend))
    driver._gate_backend = backend
    backend.discover_main_window = lambda: WindowRef(101, 202, "mock.exe", "QtQWindowIcon",
                                                    "Weixin", False, (0, 0, 600, 400))
    backend.prepare_main_window = fail
    driver._uia.ControlFromHandle = fail
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: False)
    monkeypatch.setattr("app.agent.tray_restore.restore_hidden_window", lambda *a, **kw: (
        _ for _ in ()).throw(TrayRestoreError("not restored")))
    with pytest.raises(TrayRestoreError):
        driver.bind_window()


def test_shared_uia_initializer_has_one_matching_shutdown(monkeypatch):
    events = []
    driver = NativeWeixinDriver(gate_backend=NS())
    driver._lease_checked = True
    monkeypatch.setattr("src.core.uiautomation.InitializeUIAutomationInCurrentThread", lambda: events.append("init"))
    monkeypatch.setattr("src.core.uiautomation.UninitializeUIAutomationInCurrentThread", lambda: events.append("uninit"))
    monkeypatch.setattr("src.core.uiautomation.ResetUIAutomationClientInCurrentThread", lambda: events.append("reset"))
    driver._initialize_uia()
    query = driver._query
    driver._initialize_uia()
    assert driver._query is query
    assert events == ["init"]
    driver.close()
    driver.close()
    assert events == ["init", "reset", "uninit"]


def test_inspect_rejects_cached_root_when_fresh_root_is_wrong_role(driver):
    driver._uia.ControlFromHandle = lambda hwnd: NS(ClassName="mmui::AddFriendWindow")
    result = driver.inspect()
    assert result["sessionReady"] is False
    assert result["uiaReady"] is False


@pytest.mark.parametrize("method", ["_tree_materialized", "_visible_root_bounds"])
def test_root_validation_does_not_swallow_unresponsive(driver, method):
    driver._gate_backend.window_responsive = lambda *args, **kwargs: False
    with pytest.raises(WeixinUnresponsiveError):
        getattr(driver, method)()


def test_scoped_query_checks_responsiveness_before_uia(driver):
    driver._gate_backend.window_responsive = lambda *args, **kwargs: False
    driver._query.find_all = fail
    with pytest.raises(WeixinUnresponsiveError):
        driver._find_scoped_controls(hwnd=101, name="mock")


def test_safe_attr_preserves_unresponsive_error():
    class Hung:
        @property
        def Name(self):
            raise WeixinUnresponsiveError("hung")

    with pytest.raises(WeixinUnresponsiveError):
        safe_attr(Hung(), "Name", "")


def test_navigation_checks_postcondition_before_locating_button(driver):
    driver._wait_control = fail
    driver._activate_navigation(101, ("already navigated",), lambda: True)


def test_begin_task_is_pure_bookkeeping(driver):
    driver._gate_backend.window_inspection = fail
    driver._ensure_session = fail
    driver._uia.ControlFromHandle = fail
    driver.begin_task("friend_preflight")
    assert driver._task_kind == "friend_preflight"


def test_diagnostic_snapshot_never_touches_uia_or_process_module(driver, monkeypatch):
    import win32gui
    import win32process

    driver._uia.ControlFromHandle = fail
    driver._ensure_session = fail
    driver._gate_backend.window_inspection = fail
    driver._gate_backend.find_module = fail
    driver._gate_backend.file_version = fail
    driver._root = NS()
    driver._bound_window_role = "mmui::MainWindow"
    monkeypatch.setattr(win32gui, "EnumWindows", fail)
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 101)
    monkeypatch.setattr(win32gui, "IsWindowEnabled", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetWindowRect", lambda hwnd: (0, 0, 600, 400))
    monkeypatch.setattr(win32gui, "GetClassName", lambda hwnd: "QtQWindowIcon")
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 101)
    monkeypatch.setattr(win32gui, "GetWindow", lambda hwnd, flag: 0)
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 202))
    snapshot = driver.diagnostic_snapshot()
    assert snapshot["hwnd"] == 101
    assert snapshot["pid"] == 202
    assert snapshot["windowEnabled"] is True
    assert snapshot["version"] == "4.1.13.65"
    assert snapshot["window"]["foregroundHwnd"] == 101
    assert snapshot["window"]["ownerHwnd"] == 0
    assert snapshot["window"]["role"] == "mmui::MainWindow"


def test_unknown_modal_fails_closed_without_uia_or_foreground(driver, monkeypatch):
    driver.state.update(windowEnabled=False, blockingWindow={"hwnd": 404, "pid": 999})
    driver._uia.ControlFromHandle = fail
    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", fail)
    with pytest.raises(AutomationRetryError) as exc:
        driver.bind_window()
    assert exc.value.code == "WINDOW_BLOCKED"
    assert exc.value.recoverable is False


def test_disabled_window_without_identified_blocker_fails_closed(driver):
    driver.state.update(windowEnabled=False, blockingWindow=None)
    with pytest.raises(AutomationRetryError) as exc:
        driver.bind_window()
    assert exc.value.code == "WINDOW_BLOCKED"


def test_finish_task_returns_structured_unknown_modal_failure(driver):
    driver.begin_task("send")
    driver.state.update(windowEnabled=False, blockingWindow={"hwnd": 404, "pid": 999})
    driver._uia.ControlFromHandle = fail
    result = driver.finish_task()
    assert result["success"] is False
    assert result["reasonCode"] == "WINDOW_BLOCKED"
    assert result["detail"]


def test_finish_task_does_not_close_preexisting_parent(driver):
    driver.begin_task("friend_preflight")
    driver._add_hwnd = 303
    driver._process_windows = lambda *args, **kwargs: []
    driver._uia.ControlFromHandle = fail
    result = driver.finish_task()
    assert result["success"] is True
    assert set(result) == {"success", "reasonCode", "detail"}


def test_finish_task_cancels_form_then_closes_only_owned_parent(driver):
    driver.begin_task("friend_preflight")
    driver._task_owned_add_hwnd = 303
    driver._task_process_identity = (202, "started", "4.1.13.65")
    driver._verify_hwnd = 404
    order = []
    driver._process_windows = lambda classes, **kwargs: (
        [404] if classes == (driver._session.profile.verify_friend_root_class,) else [303]
    )
    driver.cancel_friend_request = lambda: order.append("cancel") or True
    driver._close_task_parent = lambda hwnd: order.append(("close", hwnd)) or True
    result = driver.finish_task()
    assert result["success"] is True
    assert order == ["cancel", ("close", 303)]


def test_finish_task_unresponsive_does_not_attempt_fallback_cleanup(driver):
    driver.begin_task("friend_preflight")
    driver._gate_backend.window_responsive = lambda *args, **kwargs: False
    driver._uia.ControlFromHandle = fail
    result = driver.finish_task()
    assert result["success"] is False
    assert result["reasonCode"] == "WECHAT_UNRESPONSIVE"


@pytest.mark.parametrize("method", ["ensure_search_ready", "composer_ready", "read_composer_text"])
def test_search_and_composer_helpers_preserve_unresponsive(driver, method):
    driver._gate_backend.window_responsive = lambda *args, **kwargs: False
    driver._query.find_all = fail
    with pytest.raises(WeixinUnresponsiveError):
        getattr(driver, method)()


def test_cancel_does_not_fall_back_after_unresponsive(driver):
    driver._verify_hwnd = 404
    driver._wait_control = lambda **kwargs: (_ for _ in ()).throw(WeixinUnresponsiveError("hung"))
    driver._uia.ControlFromHandle = fail
    with pytest.raises(WeixinUnresponsiveError):
        driver.cancel_friend_request()


def test_friend_search_does_not_turn_unresponsive_into_no_match(driver):
    driver._friend_search = NS(SendKeys=lambda *args, **kwargs: None)
    driver._send_keys = lambda control, keys: control
    driver._wait_control = lambda **kwargs: (_ for _ in ()).throw(WeixinUnresponsiveError("hung"))
    driver._raise_scoped_risk = fail
    with pytest.raises(WeixinUnresponsiveError):
        driver.search_friend("account")


def test_friend_navigation_refreshes_main_root_before_retry(driver):
    old = driver._root
    attempts = []
    control = NS()

    def locate(**kwargs):
        attempts.append(driver._root)
        if driver._root is old:
            raise RuntimeError("navigation not ready")
        return control

    driver._wait_control = locate
    driver._actions = NS(click=lambda *args, **kwargs: None)
    driver._activate_navigation(101, ("navigation",), lambda: False)
    assert len(attempts) == 2
    assert attempts[1] is not old


def test_wrong_role_bind_cannot_foreground(driver, monkeypatch):
    driver._uia.ControlFromHandle = lambda hwnd: NS(ClassName="mmui::VerifyFriendWindow")
    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", fail)
    with pytest.raises(RuntimeError):
        driver.bind_window()


def test_inspect_carries_window_blocked_reason(driver):
    driver.state.update(windowEnabled=False, blockingWindow={"hwnd": 404, "pid": 999})
    driver._uia.ControlFromHandle = fail
    result = driver.inspect()
    assert result["degradedReason"] == "WINDOW_BLOCKED"
    assert result["sessionReady"] is False


def test_query_deadline_is_not_swallowed_by_composer(driver):
    from app.agent.waiters import ActionDeadlineExceeded

    driver._query.find_all = lambda *args, **kwargs: (_ for _ in ()).throw(ActionDeadlineExceeded("expired"))
    with pytest.raises(ActionDeadlineExceeded):
        driver.composer_ready()


def test_failed_finish_retains_scope_for_recovery_retry(driver):
    driver.begin_task("friend_preflight")
    driver._task_owned_add_hwnd = 303
    driver._process_windows = lambda *args, **kwargs: []
    attempts = iter((False, True))
    driver._close_task_parent = lambda hwnd: next(attempts)
    first = driver.finish_task()
    assert first["success"] is False
    assert driver._task_owned_add_hwnd == 303
    second = driver.finish_task()
    assert second["success"] is True
    assert driver._task_owned_add_hwnd == 0
    driver.begin_task("friend_preflight")
    assert driver._task_kind == "friend_preflight"


def test_bounds_click_refuses_disabled_main(driver):
    driver.state.update(windowEnabled=False, blockingWindow={"hwnd": 404, "pid": 999})
    root = driver._root
    target = NS(GetTopLevelControl=lambda: root, IsEnabled=True, IsOffscreen=False,
                BoundingRectangle=NS(left=10, top=10, right=30, bottom=30))
    driver._uia.Click = fail
    with pytest.raises(AutomationRetryError) as exc:
        driver._prepare_click_window(root, target, (20, 20))
    assert exc.value.code == "WINDOW_BLOCKED"


def test_begin_task_cannot_forget_failed_parent_cleanup(driver):
    driver.begin_task("friend_preflight")
    driver._task_owned_add_hwnd = 303
    with pytest.raises(AutomationRetryError) as exc:
        driver.begin_task("send")
    assert exc.value.code == "WINDOW_BLOCKED"
    assert driver._task_owned_add_hwnd == 303


def test_navigation_reports_no_action_for_existing_postcondition(driver):
    driver._wait_control = fail
    assert driver._activate_navigation(101, ("existing",), lambda: True) is False


def test_inspect_reports_unresponsive_during_fresh_validation(driver):
    checks = iter((True, False))
    driver._gate_backend.window_responsive = lambda *args, **kwargs: next(checks, False)
    result = driver.inspect()
    assert result["degradedReason"] == "WECHAT_UNRESPONSIVE"
    assert result["windowResponsive"] is False


def test_bounds_change_during_foreground_prevents_mouse_injection(driver, monkeypatch):
    import win32gui
    import win32process

    root = driver._root
    target = NS(GetTopLevelControl=lambda: root, IsEnabled=True, IsOffscreen=False,
                BoundingRectangle=NS(left=10, top=10, right=30, bottom=30))
    driver._uia.Click = fail
    foreground = [999]
    monkeypatch.setattr(win32gui, "GetClassName", lambda hwnd: "QtQWindowIcon")
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 101)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: foreground[0])
    monkeypatch.setattr(win32gui, "WindowFromPoint", lambda point: 101)
    monkeypatch.setattr(win32gui, "GetAncestor", lambda hwnd, flag: hwnd)
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 202))

    def activate(hwnd):
        foreground[0] = hwnd
        target.BoundingRectangle = NS(left=100, top=100, right=130, bottom=130)
        return True

    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", activate)
    with pytest.raises(RuntimeError, match="bounds or foreground changed"):
        driver._click_bounds(target)


def test_native_query_deadline_expires_during_responsiveness_probe(driver, monkeypatch):
    from app.agent.waiters import ActionDeadlineExceeded, action_deadline

    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])

    def responsive(*args, **kwargs):
        now[0] = 2.0
        return True

    driver._gate_backend.window_responsive = responsive
    driver._query.find_all = fail
    driver._root = NS()
    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            driver._find_scoped_controls(hwnd=101)
        now[0] = 0.5


def test_keyboard_fallback_rechecks_deadline_after_focus_click(driver, monkeypatch):
    from app.agent.waiters import ActionDeadlineExceeded, action_deadline

    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])
    monkeypatch.setattr("src.utils.clipboard_utils.set_text_to_clipboard", fail)
    driver._click_bounds = lambda control: now.__setitem__(0, 2.0)
    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            driver._replace_text(NS(SendKeys=fail), "text")
        now[0] = 0.5


def test_keyboard_fallback_rechecks_responsiveness_before_paste(driver, monkeypatch):
    responsive = [True]
    keys = []
    driver._gate_backend.window_responsive = lambda *args, **kwargs: responsive[0]
    driver._click_bounds = lambda control: None
    driver._send_keys = lambda control, value: control.SendKeys(value) or control

    def copy(value):
        responsive[0] = False
        return True

    monkeypatch.setattr("src.utils.clipboard_utils.set_text_to_clipboard", copy)
    with pytest.raises(WeixinUnresponsiveError):
        driver._replace_text(NS(SendKeys=lambda value, **kwargs: keys.append(value)), "text")
    assert keys == ["{Ctrl}a{Delete}"]


@pytest.fixture
def keyboard_driver(driver, monkeypatch):
    import win32gui
    import win32process

    foreground = [999]
    enabled = [True]
    events = []
    owner = driver._root
    owner.IsEnabled = True
    stale = NS(Name="composer", ClassName="edit", ControlTypeName="EditControl",
               AutomationId="input", GetRuntimeId=lambda: (1, 2),
               GetTopLevelControl=lambda: owner, IsEnabled=True, IsOffscreen=False,
               BoundingRectangle=NS(left=10, top=10, right=200, bottom=100))
    fresh = NS(**vars(stale), HasKeyboardFocus=True)
    stale.SetFocus = fail
    stale.SendKeys = fail
    fresh.SetFocus = lambda: events.append("focus")
    fresh.SendKeys = fail
    driver._uia.ControlFromHandle = lambda hwnd: owner
    driver._uia.SendKeys = lambda keys, **kwargs: events.append(("keys", keys, foreground[0]))
    driver._find_scoped_controls = lambda **kwargs: [fresh]
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 101)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "IsWindowEnabled", lambda hwnd: enabled[0])
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: foreground[0])
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 202))

    def activate(hwnd):
        events.append(("foreground", hwnd))
        foreground[0] = hwnd
        return True

    monkeypatch.setattr("src.core.win32._foreground_with_thread_handshake", activate)
    return driver, stale, fresh, foreground, enabled, events


def test_keyboard_re_resolves_target_and_foregrounds_owner(keyboard_driver):
    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    assert driver._send_keys(stale, "{Enter}") is fresh
    assert events == [("foreground", 101), "focus", ("keys", "{Enter}", 101)]


def test_keyboard_refuses_disabled_owner(keyboard_driver):
    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    enabled[0] = False
    with pytest.raises(AutomationRetryError):
        driver._send_keys(stale, "{Enter}")
    assert events == []


def test_keyboard_refuses_foreground_loss_during_set_focus(keyboard_driver):
    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    fresh.SetFocus = lambda: foreground.__setitem__(0, 999)
    with pytest.raises(AutomationRetryError):
        driver._send_keys(stale, "{Enter}")
    assert events == [("foreground", 101), ("foreground", 101)]


def test_keyboard_recovers_one_focus_loss_before_injecting_once(keyboard_driver):
    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    focus_calls = []
    def focus():
        focus_calls.append(1)
        if len(focus_calls) == 1:
            foreground[0] = 999
    fresh.SetFocus = focus
    assert driver._send_keys(stale, "{Enter}") is fresh
    assert len(focus_calls) == 2
    assert [event for event in events if event[0] == "keys"] == [("keys", "{Enter}", 101)]


def test_keyboard_refuses_changed_control_identity(keyboard_driver):
    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    fresh.GetRuntimeId = lambda: (9, 9)
    with pytest.raises(AutomationRetryError):
        driver._send_keys(stale, "{Enter}")
    assert events == []


def test_keyboard_stops_when_focus_exhausts_deadline(keyboard_driver, monkeypatch):
    from app.agent.waiters import ActionDeadlineExceeded, action_deadline

    driver, stale, fresh, foreground, enabled, events = keyboard_driver
    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])
    fresh.SetFocus = lambda: now.__setitem__(0, 2.0)
    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            driver._send_keys(stale, "{Enter}")
        now[0] = 0.5
    assert events == [("foreground", 101)]


def test_wait_subscription_stop_error_never_falls_back_to_polling(driver, monkeypatch):
    error = AutomationRetryError("retired")
    def subscribe(*args):
        raise error
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", subscribe)
    with pytest.raises(AutomationRetryError) as raised:
        driver._wait_for(fail, 1, root=driver._root)
    assert raised.value is error


def test_wait_subscription_ordinary_failure_after_deadline_blocks_polling(driver, monkeypatch):
    from app.agent.waiters import ActionDeadlineExceeded, action_deadline

    now = [0.0]
    monkeypatch.setattr("app.agent.waiters.time.monotonic", lambda: now[0])
    def subscribe(*args):
        now[0] = 2.0
        raise RuntimeError("events unavailable")
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", subscribe)
    with action_deadline(1):
        with pytest.raises(ActionDeadlineExceeded):
            driver._wait_for(fail, 1, root=driver._root)
        now[0] = 0.5


def test_inspect_uses_enriched_native_window_snapshot(driver):
    driver._gate_backend.window_inspection = lambda: dict(hwnd=101, pid=202, windowState="visible")
    snapshots = []
    def snapshot():
        snapshots.append(True)
        return dict(driver.state)
    driver._window_guard_state = snapshot
    result = driver.inspect()
    assert result["sessionReady"] is True
    assert result["windowEnabled"] is True
    assert snapshots == [True]


def test_partial_subscription_is_retained_and_blocks_actions(driver, monkeypatch):
    from app.agent.uia_events import EventCleanupError

    subscription = NS(close=fail)
    error = EventCleanupError(subscription, RuntimeError("partial registration"))
    def subscribe(*args):
        raise error
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", subscribe)
    with pytest.raises(EventCleanupError):
        driver._wait_for(fail, 1, root=driver._root)
    assert driver._event_subscription is subscription
    driver._query.find_all = fail
    with pytest.raises(EventCleanupError):
        driver._find_scoped_controls(hwnd=101)


def test_pending_subscription_must_retire_before_new_wait(driver, monkeypatch):
    from app.agent.uia_events import EventCleanupError

    events = []
    pending = NS(close=lambda: events.append("retire-old"))
    driver._event_subscription = pending
    driver._event_cleanup_error = EventCleanupError(pending, "old error")
    new = NS(close=lambda: events.append("retire-new"))
    def subscribe(*args):
        events.append("subscribe")
        return new
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", subscribe)
    assert driver._wait_for(lambda: events.append("poll") or True, 1, root=driver._root)
    assert events == ["retire-old", "subscribe", "poll", "retire-new"]
    assert driver._event_subscription is None
    assert driver._event_cleanup_error is None


def test_failed_removal_retains_subscription_and_rejects_next_subscription(driver, monkeypatch):
    from app.agent.uia_events import EventCleanupError

    subscription = NS()
    def close():
        raise EventCleanupError(subscription, "remove failed")
    subscription.close = close
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", lambda *args: subscription)
    with pytest.raises(EventCleanupError):
        driver._wait_for(lambda: True, 1, root=driver._root)
    assert driver._event_subscription is subscription
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", fail)
    with pytest.raises(EventCleanupError):
        driver._wait_for(fail, 1, root=driver._root)
