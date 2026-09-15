from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path

import pytest

from app.agent.actions import ActionVerificationError
from app.agent.gate import AccessibilitySafetyError
from app.agent.native_driver import (
    _control_reference,
    FriendSubmitReceipt,
    MessageBubbleSnapshot,
    NativeWeixinDriver,
    RiskControlError,
    SearchCandidate,
    extract_contact_results,
    extract_exact_forward_candidates,
    filter_recent_message_bubbles,
    find_exact_control,
    has_new_forward_confirmation,
    raise_for_risk_controls,
    resolve_friend_form_fields,
)
from app.agent.retry import StaleElementError, WeixinUnresponsiveError
from app.agent.profile import get_weixin_profile, UnsupportedWeixinVersion


@dataclass
class FakeControl:
    Name: str = ""
    ControlTypeName: str = ""
    ClassName: str = ""
    AutomationId: str = ""
    IsEnabled: bool = True
    IsOffscreen: bool = False
    BoundingRectangle: object | None = None


@dataclass(frozen=True)
class FakeRect:
    left: int
    top: int
    right: int
    bottom: int

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "weixin_uia"


def _fixture_controls(name: str) -> list[tuple[FakeControl, int]]:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    controls = []
    for item in payload["controls"]:
        control = FakeControl(
            item["name"],
            item["controlType"],
            item["className"],
            item["automationId"],
            item["enabled"],
            item["offscreen"],
        )
        runtime_id = tuple(item.get("runtimeId", ()))
        control.GetRuntimeId = lambda value=runtime_id: value
        controls.append((control, int(item["depth"])))
    return controls


def test_find_exact_control_requires_all_selector_fields():
    wrong = FakeControl("搜索", "EditControl", "other")
    exact = FakeControl("搜索", "EditControl", "mmui::XValidatorTextEdit")

    found = find_exact_control(
        [(wrong, 2), (exact, 3)],
        name="搜索",
        control_type="EditControl",
        class_name="mmui::XValidatorTextEdit",
    )

    assert found is exact


def test_control_reference_uses_runtime_identity_not_animated_bounds():
    first = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
        BoundingRectangle=FakeRect(10, 10, 110, 30),
    )
    settled = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
        BoundingRectangle=FakeRect(10, 90, 110, 120),
    )
    replacement = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
        BoundingRectangle=FakeRect(10, 90, 110, 120),
    )
    first.GetRuntimeId = lambda: (42, 7)
    settled.GetRuntimeId = lambda: (42, 7)
    replacement.GetRuntimeId = lambda: (42, 8)

    assert _control_reference(first) == _control_reference(settled)
    assert _control_reference(first) != _control_reference(replacement)


def test_contact_results_collect_exact_identities_within_each_row_boundary():
    section = FakeControl("联系人", "CustomControl", "mmui::XTableCell")
    alice = FakeControl(
        "Alice 备注", "ListItemControl", "mmui::SearchContentCellView", "search_item_1"
    )
    nickname = FakeControl("Alice 昵称", "TextControl", "mmui::Label")
    duplicate = FakeControl("Alice 备注", "TextControl", "mmui::Label")
    bob = FakeControl(
        "Bob", "ListItemControl", "mmui::SearchContentCellView", "search_item_2"
    )

    results = extract_contact_results(
        [(section, 1), (alice, 2), (nickname, 3), (duplicate, 3), (bob, 2)]
    )

    assert len(results) == 2
    assert results[0].display_name == "Alice 备注"
    assert results[0].identities == frozenset({"Alice 备注", "Alice 昵称"})
    assert results[0].automation_id == "search_item_1"
    assert results[0].row_index == 0
    assert results[0].result_type == "contact"


def test_contact_results_only_whitelist_file_transfer_function_and_filter_network():
    transfer = FakeControl(
        "文件传输助手",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_function_1",
    )
    other_function = FakeControl(
        "扫一扫",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_function_2",
    )
    network = FakeControl(
        "搜索网络结果",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_web_1",
    )

    results = extract_contact_results(
        [(transfer, 2), (other_function, 2), (network, 2)]
    )

    assert [candidate.display_name for candidate in results] == ["文件传输助手"]
    assert results[0].result_type == "function"


def test_file_transfer_helper_real_xtablecell_row_is_parsed():
    results = extract_contact_results(
        _fixture_controls("file_transfer_nested_identity.json")
    )

    assert len(results) == 1
    assert results[0].display_name == "文件传输助手"
    assert results[0].identities == frozenset({"文件传输助手"})
    assert results[0].result_type == "function"


def test_search_candidate_semantics_ignore_dynamic_runtime_ids():
    first = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 2, (1, 7)
    )
    refreshed = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 2, (9, 99)
    )

    assert first == refreshed
    assert NativeWeixinDriver._candidate_signature([first]) == (
        NativeWeixinDriver._candidate_signature([refreshed])
    )


def test_search_snapshot_keeps_each_candidate_paired_with_its_source_row():
    controls = _fixture_controls("file_transfer_nested_identity.json")
    search_list = FakeControl(AutomationId="search_list")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type(
        "Session",
        (),
        {"profile": type("P", (), {"search_list_automation_id": "search_list"})()},
    )()
    driver._all_nodes = lambda: [(search_list, 1)]
    driver._uia = type(
        "Uia",
        (),
        {"WalkControl": staticmethod(lambda *_args, **_kwargs: controls)},
    )()

    snapshot = driver._search_rows()

    assert len(snapshot) == 1
    assert snapshot[0].candidate.display_name == "文件传输助手"
    assert snapshot[0].control is controls[0][0]


def test_search_waits_for_refreshed_results_instead_of_accepting_old_nonempty_list():
    class SearchEdit(FakeControl):
        value = "old"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class PollingWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(8):
                if predicate():
                    return True
            return False

    old = FakeControl(
        "旧结果", "ListItemControl", "mmui::SearchContentCellView", "search_item_1"
    )
    new = FakeControl(
        "新结果", "ListItemControl", "mmui::SearchContentCellView", "search_item_2"
    )
    search_list = FakeControl(AutomationId="search_list")
    snapshots = iter(
        [[(old, 1)], [(old, 1)], [(new, 1)], [(new, 1)]]
    )

    class Uia:
        @staticmethod
        def WalkControl(*_args, **_kwargs):
            return next(snapshots, [(new, 1)])

    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    driver._waiter = PollingWaiter()
    driver._session = type("Session", (), {"profile": type("P", (), {"search_list_automation_id": "search_list"})()})()
    driver._uia = Uia()
    driver._all_nodes = lambda: [(search_list, 1)]

    results = driver.search_contacts("新结果")

    assert [candidate.display_name for candidate in results] == ["新结果"]
    assert driver._search_edit.value == "新结果"


def test_repeated_search_accepts_identical_candidates_after_clear_transition():
    class SearchEdit(FakeControl):
        value = "Alice"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class PollingWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(6):
                if predicate():
                    return True
            return False

    candidate = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 1, (1, 7)
    )
    snapshots = iter(
        (([candidate], [object()]), None, ([candidate], [object()]), ([candidate], [object()]))
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    driver._waiter = PollingWaiter()
    driver._search_rows = lambda: next(snapshots, ([candidate], [object()]))

    assert driver.search_contacts("Alice") == [candidate]


def test_search_does_not_accept_transient_empty_rows_before_delayed_results():
    class SearchEdit(FakeControl):
        value = "old"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class PollingWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(10):
                if predicate():
                    return True
            return False

    old = SearchCandidate(
        "old", frozenset({"old"}), "contact", "search_item_1", 0, 1, (1, 1)
    )
    alice = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_2", 0, 1, (1, 2)
    )
    snapshots = iter(
        (
            ([old], [object()]),
            ([], []),
            ([], []),
            ([], []),
            ([], []),
            ([alice], [object()]),
            ([alice], [object()]),
        )
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    driver._waiter = PollingWaiter()
    driver._search_rows = lambda: next(snapshots, ([alice], [object()]))

    assert driver.search_contacts("Alice") == [alice]


def test_search_returns_after_stable_empty_result_instead_of_full_timeout(monkeypatch):
    class SearchEdit(FakeControl):
        value = "old"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class ObservingWaiter:
        def __init__(self):
            self.outcomes = []

        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(10):
                if predicate():
                    self.outcomes.append(True)
                    return True
            self.outcomes.append(False)
            return False

    old = SearchCandidate(
        "old", frozenset({"old"}), "contact", "search_item_1", 0, 1
    )
    snapshots = iter((([old], [object()]), ([], [])))
    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    waiter = ObservingWaiter()
    driver._waiter = waiter
    driver._search_rows = lambda: next(snapshots, ([], []))
    clock = iter((0.0, 0.2, 0.55, 0.8, 1.0))
    monkeypatch.setattr(
        "app.agent.native_driver.time.monotonic",
        lambda: next(clock, 1.0),
    )

    assert driver.search_contacts("missing") == []
    assert waiter.outcomes == [True, True]


def test_open_exact_chat_supports_repeated_file_transfer_helper_searches():
    candidate = SearchCandidate(
        "文件传输助手",
        frozenset({"文件传输助手"}),
        "function",
        "search_item_function_1",
        0,
        1,
    )
    class SearchEdit(FakeControl):
        value = "文件传输助手"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class PollingWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(6):
                if predicate():
                    return True
            return False

    selected = []
    snapshots = iter(
        (
            ([candidate], [object()]),
            None,
            ([candidate], [object()]),
            ([candidate], [object()]),
            ([candidate], [object()]),
            None,
            ([candidate], [object()]),
            ([candidate], [object()]),
        )
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    driver._waiter = PollingWaiter()
    driver._search_rows = lambda: next(snapshots, ([candidate], [object()]))
    driver.select_search_result = lambda value: selected.append(value)
    driver.current_chat_title = lambda: "文件传输助手"

    driver._open_exact_chat("文件传输助手")
    driver._open_exact_chat("文件传输助手")

    assert selected == [candidate, candidate]


def test_search_ready_refreshes_a_stale_main_root_before_using_keyboard():
    search_edit = FakeControl(
        "搜索",
        "EditControl",
        "mmui::XValidatorTextEdit",
    )
    stale_root = FakeControl("微信", "WindowControl", "mmui::MainWindow")
    fresh_root = FakeControl("微信", "WindowControl", "mmui::MainWindow")
    sent_keys = []
    stale_root.SendKeys = lambda keys, **_kwargs: sent_keys.append(keys)

    class Uia:
        @staticmethod
        def ControlFromHandle(hwnd):
            assert hwnd == 101
            return fresh_root

    profile = type(
        "Profile",
        (),
        {
            "search_edit_name": "搜索",
            "search_edit_class": "mmui::XValidatorTextEdit",
        },
    )()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 101, "profile": profile})()
    driver._root = stale_root
    driver._uia = Uia()
    driver._ensure_session = lambda: None
    driver.ensure_window_responsive = lambda _hwnd=None: True
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    queried_roots = []

    def find_scoped_controls(**_selector):
        queried_roots.append(driver._root)
        return [search_edit] if driver._root is fresh_root else []

    driver._find_scoped_controls = find_scoped_controls

    assert driver.ensure_search_ready() is True
    assert queried_roots == [stale_root, fresh_root]
    assert driver._search_edit is search_edit
    assert sent_keys == []


def test_search_candidate_click_uses_valid_descendant_when_row_has_no_bounds():
    row = FakeControl(
        "Alice", "ListItemControl", "mmui::SearchContentCellView", "search_item_1"
    )
    child = FakeControl(
        "Alice", "TextControl", "mmui::Label", BoundingRectangle=FakeRect(20, 20, 80, 50)
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    row.GetTopLevelControl = lambda: driver._root
    driver._uia = type(
        "Uia",
        (),
        {
            "WalkControl": staticmethod(lambda *_args, **_kwargs: [(child, 1)]),
            "Click": staticmethod(lambda x, y: clicks.append((x, y))),
        },
    )()
    clicks = []

    driver._click_search_candidate(row)

    assert clicks == [(50, 35)]


def test_click_prefers_the_uia_clickable_point_inside_the_row():
    row = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    row.GetClickablePoint = lambda: (25, 25, True)
    clicks = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicks.append((x, y)))}
    )()

    driver._click_bounds(row)

    assert clicks == [(25, 25)]


def test_click_allows_visible_same_process_secondary_dialog_control(monkeypatch):
    main_root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    dialog_root = FakeControl(
        "验证朋友申请",
        "WindowControl",
        "mmui::VerifyFriendWindow",
        BoundingRectangle=FakeRect(300, 100, 700, 500),
    )
    dialog_root.NativeWindowHandle = 222
    control = FakeControl(
        "确定",
        "ButtonControl",
        "mmui::XButton",
        BoundingRectangle=FakeRect(500, 400, 600, 450),
    )
    control.GetTopLevelControl = lambda: dialog_root
    clicks = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = main_root
    driver._session = type("Session", (), {"pid": 123, "hwnd": 111})()
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicks.append((x, y)))}
    )()
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd == 222)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd == 222)
    monkeypatch.setattr("win32gui.GetForegroundWindow", lambda: 222)
    monkeypatch.setattr("win32gui.WindowFromPoint", lambda _point: 222)
    monkeypatch.setattr("win32gui.GetAncestor", lambda hwnd, _flag: hwnd)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda hwnd: (0, 123)
    )

    driver._click_bounds(control)

    assert clicks == [(550, 425)]


def test_click_foregrounds_live_owner_immediately_before_mouse_injection(monkeypatch):
    import win32gui

    dialog_root = FakeControl(
        "添加朋友",
        "WindowControl",
        "mmui::AddFriendWindow",
        BoundingRectangle=FakeRect(300, 100, 700, 500),
    )
    dialog_root.NativeWindowHandle = 222
    control = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        BoundingRectangle=FakeRect(500, 400, 600, 450),
    )
    control.GetTopLevelControl = lambda: dialog_root
    foreground = {"hwnd": 111}
    calls = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._session = type("Session", (), {"pid": 123, "hwnd": 111})()
    driver._uia = type(
        "Uia",
        (),
        {
            "Click": staticmethod(
                lambda x, y: calls.append(("click", foreground["hwnd"], x, y))
            )
        },
    )()
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 222)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: hwnd == 222)
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: foreground["hwnd"])
    monkeypatch.setattr(win32gui, "WindowFromPoint", lambda _point: 222)
    monkeypatch.setattr(win32gui, "GetAncestor", lambda hwnd, _flag: hwnd)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda hwnd: (0, 123)
    )

    def foreground_owner(hwnd):
        calls.append(("foreground", hwnd))
        foreground["hwnd"] = hwnd
        return True

    monkeypatch.setattr(
        "src.core.win32._foreground_with_thread_handshake", foreground_owner
    )

    driver._click_bounds(control)

    assert calls == [("foreground", 222), ("click", 222, 550, 425)]


def test_click_keeps_owned_qt_popover_passive_and_foregrounds_its_owner(
    monkeypatch,
):
    import win32con
    import win32gui

    popover_root = FakeControl(
        "",
        "WindowControl",
        "mmui::SearchContentPopover",
        BoundingRectangle=FakeRect(-920, 250, -580, 350),
    )
    popover_root.NativeWindowHandle = 222
    control = FakeControl(
        "文件传输助手",
        "ListItemControl",
        "mmui::XTableCell",
        BoundingRectangle=FakeRect(-906, 267, -586, 331),
    )
    control.GetTopLevelControl = lambda: popover_root
    foreground = {"hwnd": 999}
    calls = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(-986, 164, -21, 914))
    driver._session = type("Session", (), {"pid": 123, "hwnd": 111})()
    driver._uia = type(
        "Uia",
        (),
        {
            "Click": staticmethod(
                lambda x, y: calls.append(("click", foreground["hwnd"], x, y))
            )
        },
    )()
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd in {111, 222})
    monkeypatch.setattr(
        win32gui, "IsWindowVisible", lambda hwnd: hwnd in {111, 222}
    )
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: foreground["hwnd"])
    monkeypatch.setattr(
        win32gui,
        "GetClassName",
        lambda hwnd: "Qt51514QWindowToolSaveBits" if hwnd == 222 else "Qt51514QWindowIcon",
    )
    monkeypatch.setattr(
        win32gui,
        "GetWindow",
        lambda hwnd, flag: 111
        if hwnd == 222 and flag == win32con.GW_OWNER
        else 0,
    )
    monkeypatch.setattr(win32gui, "WindowFromPoint", lambda _point: 222)
    monkeypatch.setattr(win32gui, "GetAncestor", lambda hwnd, _flag: hwnd)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda hwnd: (0, 123)
    )

    def foreground_owner(hwnd):
        calls.append(("foreground", hwnd))
        foreground["hwnd"] = hwnd
        return True

    monkeypatch.setattr(
        "src.core.win32._foreground_with_thread_handshake", foreground_owner
    )

    driver._click_bounds(control)

    assert calls == [("foreground", 111), ("click", 111, -746, 299)]


def test_click_refuses_mouse_injection_when_live_owner_cannot_be_foregrounded(
    monkeypatch,
):
    import win32gui

    dialog_root = FakeControl(
        "添加朋友",
        "WindowControl",
        "mmui::AddFriendWindow",
        BoundingRectangle=FakeRect(300, 100, 700, 500),
    )
    dialog_root.NativeWindowHandle = 222
    control = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        BoundingRectangle=FakeRect(500, 400, 600, 450),
    )
    control.GetTopLevelControl = lambda: dialog_root
    clicks = []
    driver = NativeWeixinDriver(gate_backend=object(), timeout=0.01)
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._session = type("Session", (), {"pid": 123, "hwnd": 111})()
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicks.append((x, y)))}
    )()
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 222)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: hwnd == 222)
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 111)
    monkeypatch.setattr(win32gui, "WindowFromPoint", lambda _point: 222)
    monkeypatch.setattr(win32gui, "GetAncestor", lambda hwnd, _flag: hwnd)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda hwnd: (0, 123)
    )
    monkeypatch.setattr(
        "src.core.win32._foreground_with_thread_handshake", lambda _hwnd: False
    )

    with pytest.raises(RuntimeError, match="无法置前"):
        driver._click_bounds(control)

    assert clicks == []


def test_click_rejects_secondary_dialog_from_other_process_with_diagnostics(monkeypatch):
    dialog_root = FakeControl(
        "Other",
        "WindowControl",
        "mmui::VerifyFriendWindow",
        BoundingRectangle=FakeRect(300, 100, 700, 500),
    )
    dialog_root.NativeWindowHandle = 222
    control = FakeControl(
        "确定",
        "ButtonControl",
        "mmui::XButton",
        BoundingRectangle=FakeRect(500, 400, 600, 450),
    )
    control.GetTopLevelControl = lambda: dialog_root
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._session = type("Session", (), {"pid": 123, "hwnd": 111})()
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda _hwnd: True)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda _hwnd: (0, 999)
    )

    with pytest.raises(RuntimeError) as raised:
        driver._click_bounds(control)

    detail = str(raised.value)
    assert "ownerPid=999" in detail
    assert "expectedPid=123" in detail
    assert "ControlType='ButtonControl'" in detail


def test_select_search_result_re_resolves_row_after_pattern_failure():
    stale = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    fresh = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(100, 100, 160, 140),
    )
    stale.GetSelectionItemPattern = lambda: type(
        "Pattern", (), {"Select": staticmethod(lambda **_kwargs: False)}
    )()
    candidate = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 1
    )
    clicked = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._search_query = "Alice"
    snapshots = iter(
        (
            ([candidate], [stale]),
            ([candidate], [fresh]),
            ([candidate], [fresh]),
        )
    )
    driver._search_rows = lambda: next(snapshots, ([candidate], [fresh]))
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicked.append((x, y)))}
    )()
    driver.composer_ready = lambda: bool(clicked)
    driver.current_chat_title = lambda: "Alice" if clicked else ""

    driver.select_search_result(candidate)

    assert clicked == [(130, 120)]


def test_select_uses_one_direct_fresh_row_click_without_reopening_search():
    candidate = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 1
    )
    refreshed = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_9", 0, 1
    )
    stale = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::XTableCell",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    fresh = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::XTableCell",
        "search_item_9",
        BoundingRectangle=FakeRect(100, 100, 160, 140),
    )
    clicks = []
    searches = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._search_query = "Alice"
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    resolutions = iter((stale, fresh))
    driver._resolve_search_candidate = lambda _value: next(resolutions, fresh)
    driver.search_contacts = lambda target: searches.append(target) or [refreshed]
    driver._click_search_candidate = lambda control: clicks.append(control)
    driver.composer_ready = lambda: bool(clicks)
    driver.current_chat_title = lambda: "Alice" if clicks else ""
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()

    driver.select_search_result(candidate)

    assert searches == []
    assert clicks == [fresh]


def test_select_caps_destination_wait_after_one_direct_click():
    candidate = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 1
    )
    row = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    clicked = []
    waits = []
    driver = NativeWeixinDriver(gate_backend=object(), timeout=5.0)
    driver._search_query = "Alice"
    driver._resolve_search_candidate = lambda _candidate: row
    driver._click_search_candidate = lambda control: clicked.append(control)
    driver.composer_ready = lambda: bool(clicked)
    driver.current_chat_title = lambda: "Alice" if clicked else ""

    def bounded_wait(predicate, timeout, **_kwargs):
        waits.append(timeout)
        return predicate()

    driver._wait_for = bounded_wait

    driver.select_search_result(candidate)

    assert clicked == [row]
    assert waits == [pytest.approx(2.0)]


def test_add_friend_navigation_ignores_same_named_top_level_window():
    nodes = _fixture_controls("add_friend_navigation_collision.json")
    clicked = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._walk = lambda _hwnd: (nodes[0][0], nodes)
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    driver._actions = type(
        "Actions",
        (),
        {
            "click": staticmethod(
                lambda control, _postcondition, **_kwargs: clicked.append(control)
            )
        },
    )()

    driver._activate_navigation(1, ("微信",), lambda: False)

    assert clicked == [nodes[1][0]]


def test_select_rejects_new_duplicate_identity_before_fallback_click():
    first = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_1", 0, 1
    )
    duplicate = SearchCandidate(
        "Alice", frozenset({"Alice"}), "contact", "search_item_2", 1, 1
    )
    stale = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    second_row = FakeControl(
        "Alice",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_2",
        BoundingRectangle=FakeRect(90, 20, 150, 50),
    )
    stale.GetSelectionItemPattern = lambda: type(
        "Pattern", (), {"Select": staticmethod(lambda **_kwargs: False)}
    )()
    snapshots = iter(
        (([first], [stale]), ([first, duplicate], [stale, second_row]))
    )
    clicks = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._search_query = "Alice"
    driver._search_rows = lambda: next(
        snapshots, ([first, duplicate], [stale, second_row])
    )
    driver._root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicks.append((x, y)))}
    )()
    driver.composer_ready = lambda: False

    with pytest.raises(RuntimeError, match="唯一|re-resolution"):
        driver.select_search_result(first)

    assert clicks == []


def test_select_accepts_remark_chat_title_for_nickname_query():
    candidate = SearchCandidate(
        "Alice 备注",
        frozenset({"Alice 备注", "Alice 昵称"}),
        "contact",
        "search_item_1",
        0,
        1,
    )
    row = FakeControl(
        "Alice 备注",
        "ListItemControl",
        "mmui::SearchContentCellView",
        "search_item_1",
        BoundingRectangle=FakeRect(20, 20, 80, 50),
    )
    row.GetSelectionItemPattern = lambda: type(
        "Pattern", (), {"Select": staticmethod(lambda **_kwargs: True)}
    )()
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 1000, 800))
    title_bar = FakeControl(ClassName="mmui::ChatTitleBarMasterView")
    title = FakeControl(
        "Alice 备注",
        "TextControl",
        "mmui::XTextView",
        "content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label",
        BoundingRectangle=FakeRect(600, 100, 800, 140),
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._search_query = "Alice 昵称"
    driver._search_rows = lambda: ([candidate], [row])
    driver._root = root
    driver._session = type("Session", (), {"hwnd": 1})()
    driver._walk = lambda _hwnd: (
        root,
        [(root, 0), (title_bar, 1), (title, 2)],
    )
    driver._find_composer = lambda: object()
    driver.composer_ready = lambda: True
    driver._click_search_candidate = lambda _control: None

    driver.select_search_result(candidate)

    assert driver.current_chat_title() == "Alice 备注"


def test_walk_refuses_to_call_uia_when_weixin_is_unresponsive():
    class Backend:
        @staticmethod
        def window_responsive(hwnd, timeout_ms=250):
            assert hwnd == 101
            assert timeout_ms == 250
            return False

    class Uia:
        @staticmethod
        def ControlFromHandle(_hwnd):
            raise AssertionError("UIA must not be called for an unresponsive window")

    driver = NativeWeixinDriver(gate_backend=Backend())
    driver._session = type("Session", (), {"hwnd": 101})()
    driver._uia = Uia()

    with pytest.raises(WeixinUnresponsiveError):
        driver._walk(101)


def test_hot_path_locators_do_not_walk_the_entire_uia_tree():
    for method in (
        NativeWeixinDriver._tree_materialized,
        NativeWeixinDriver._visible_root_bounds,
        NativeWeixinDriver.ensure_search_ready,
        NativeWeixinDriver._search_rows,
        NativeWeixinDriver._find_composer,
        NativeWeixinDriver.current_chat_title,
        NativeWeixinDriver._message_controls,
        NativeWeixinDriver._invoke_once_or_key,
        NativeWeixinDriver._wait_control,
        NativeWeixinDriver._activate_navigation,
        NativeWeixinDriver.set_friend_account,
        NativeWeixinDriver.search_friend,
        NativeWeixinDriver.open_friend_request,
        NativeWeixinDriver.set_friend_fields,
    ):
        source = inspect.getsource(method)
        assert "WalkControl" not in source
        assert "_all_nodes" not in source
        assert "_walk(" not in source


def test_bind_window_does_not_recreate_the_gate_session_for_an_invisible_root(
    monkeypatch,
):
    class Session:
        def __init__(self, hwnd, root):
            self.hwnd = hwnd
            self.pid = hwnd + 100
            self.version = "4.1.13.65"
            self.root = root
            self.closed = False

        def close(self):
            self.closed = True

    invisible = FakeControl(
        IsOffscreen=True, BoundingRectangle=FakeRect(0, 0, 0, 0)
    )
    visible = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    first = Session(1, invisible)
    second = Session(2, visible)
    sessions = iter((first, second))
    driver = NativeWeixinDriver(gate_backend=object())
    driver._ensure_session = lambda: (
        setattr(driver, "_session", next(sessions))
        if driver._session is None
        else None
    )
    driver._walk = lambda _hwnd: (driver._session.root, [])
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    monkeypatch.setattr(driver, "_activate_bound_main_window", lambda _hwnd: True)

    with pytest.raises(RuntimeError, match="可见根边界"):
        driver.bind_window()

    assert first.closed is False


def test_bind_window_restores_an_existing_session_before_reusing_its_uia_root(
    monkeypatch,
):
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))

    @dataclass(frozen=True)
    class Window:
        hwnd: int
        pid: int
        visible: bool

    class RestoreResult:
        window = Window(11, 22, True)

        @staticmethod
        def as_dict():
            return {"restored": True, "windowState": "visible"}

    class Backend:
        def __init__(self):
            self.calls = 0

        def prepare_main_window(self):
            self.calls += 1
            return RestoreResult()

    backend = Backend()
    session = type(
        "Session",
        (),
        {"hwnd": 11, "pid": 22, "version": "4.1.13.65"},
    )()
    driver = NativeWeixinDriver(gate_backend=backend)
    driver._session = session
    driver._root = root
    driver._ensure_session = lambda: None
    driver._walk = lambda _hwnd: (root, [])
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    monkeypatch.setattr(driver, "_activate_bound_main_window", lambda _hwnd: True)
    monkeypatch.setattr(driver, "_bound_main_window_ready", lambda _hwnd: True)

    result = driver.bind_window()

    assert backend.calls == 1
    assert result["windowRestore"]["restored"] is True


def test_bind_window_leaves_transient_initialization_retry_to_the_workflow(monkeypatch):
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    session = type(
        "Session",
        (),
        {"hwnd": 2, "pid": 102, "version": "4.1.13.65"},
    )()
    attempts = []
    cleanups = []
    driver = NativeWeixinDriver(gate_backend=object())

    def ensure():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("ControlFromHandle temporarily failed")
        driver._session = session
        driver._root = root

    driver._ensure_session = ensure
    driver.close = lambda: cleanups.append("close")
    driver._walk = lambda _hwnd: (root, [])
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    monkeypatch.setattr(driver, "_activate_bound_main_window", lambda _hwnd: True)

    with pytest.raises(RuntimeError, match="temporarily failed"):
        driver.bind_window()

    assert attempts == [1]
    assert cleanups == []


def test_bind_window_does_not_retry_unsupported_version(monkeypatch):
    attempts = []
    cleanups = []
    driver = NativeWeixinDriver(gate_backend=object())

    def ensure():
        attempts.append(1)
        raise UnsupportedWeixinVersion("unsupported Weixin version: 4.1.14")

    driver._ensure_session = ensure
    driver.close = lambda: cleanups.append("close")
    monkeypatch.setattr(
        driver, "_activate_bound_main_window",
        lambda _hwnd: pytest.fail("activation must not run"),
    )

    with pytest.raises(UnsupportedWeixinVersion):
        driver.bind_window()

    assert attempts == [1]
    assert cleanups == []


def test_bind_window_does_not_retry_accessibility_gate_safety_error(monkeypatch):
    attempts = []
    driver = NativeWeixinDriver(gate_backend=object())

    def ensure():
        attempts.append(1)
        raise AccessibilitySafetyError("accessibility gate write-back failed")

    driver._ensure_session = ensure
    monkeypatch.setattr(
        driver, "_activate_bound_main_window",
        lambda _hwnd: pytest.fail("activation must not run"),
    )

    with pytest.raises(RuntimeError, match="gate write-back"):
        driver.bind_window()

    assert attempts == [1]


def test_bind_window_never_closes_the_session_for_a_transient_restore_error(
    monkeypatch,
):
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 200, 200))
    session = type(
        "Session",
        (),
        {"hwnd": 2, "pid": 102, "version": "4.1.13.65"},
    )()
    attempts = []
    cleanups = []
    driver = NativeWeixinDriver(gate_backend=object())

    def ensure():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("ControlFromHandle restore race")
        driver._session = session
        driver._root = root

    driver._ensure_session = ensure
    driver.close = lambda: cleanups.append("close")
    driver._walk = lambda _hwnd: (root, [])
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    monkeypatch.setattr(driver, "_activate_bound_main_window", lambda _hwnd: True)

    with pytest.raises(RuntimeError, match="restore race"):
        driver.bind_window()

    assert attempts == [1]
    assert cleanups == []


def test_bind_window_final_activation_error_includes_root_state(monkeypatch):
    root = FakeControl(
        "微信",
        "WindowControl",
        "mmui::MainWindow",
        "main",
        BoundingRectangle=FakeRect(0, 0, 200, 200),
    )
    attempts = []
    driver = NativeWeixinDriver(gate_backend=object())

    def ensure():
        attempts.append(1)
        driver._session = type(
            "Session", (), {"hwnd": 111, "pid": 123, "version": "4.1.13.65"}
        )()
        driver._root = root

    driver._ensure_session = ensure
    driver.close = lambda: setattr(driver, "_session", None)
    monkeypatch.setattr(
        driver, "_activate_bound_main_window",
        lambda _hwnd: (_ for _ in ()).throw(RuntimeError("foreground denied")),
    )

    with pytest.raises(RuntimeError) as raised:
        driver.bind_window()

    detail = str(raised.value)
    assert attempts == [1]
    assert "action=bind_window.activate" in detail
    assert "ControlType='WindowControl'" in detail
    assert "ClassName='mmui::MainWindow'" in detail
    assert "bounds=(0,0,200,200)" in detail


def test_soft_refresh_releases_controls_without_closing_gate_or_com(monkeypatch):
    root = FakeControl(
        "微信",
        "WindowControl",
        "mmui::MainWindow",
        "main",
        BoundingRectangle=FakeRect(0, 0, 200, 200),
    )

    class Session:
        hwnd = 101
        close_calls = 0

        def close(self):
            self.close_calls += 1

    class Subscription:
        close_calls = 0

        def close(self):
            self.close_calls += 1

    class Uia:
        uninitialize_calls = 0

        @staticmethod
        def ControlFromHandle(hwnd):
            assert hwnd == 101
            return root

        @classmethod
        def UninitializeUIAutomationInCurrentThread(cls):
            cls.uninitialize_calls += 1

    session = Session()
    subscription = Subscription()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = session
    driver._uia = Uia()
    driver._uia_initialized = True
    driver._root = object()
    driver._search_edit = object()
    driver._composer = object()
    driver._event_subscription = subscription
    driver._tree_materialized = lambda: True
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args: predicate())}
    )()
    monkeypatch.setattr(
        "app.agent.native_driver.subscribe_uia_events", lambda *_args: None
    )

    generation = driver.soft_refresh_session()

    assert generation == 1
    assert subscription.close_calls == 1
    assert session.close_calls == 0
    assert Uia.uninitialize_calls == 0
    assert driver._root is root
    assert driver._search_edit is None
    assert driver._composer is None


def test_existing_session_rejects_recycled_process_identity():
    session = type(
        "Session",
        (),
        {
            "hwnd": 101,
            "pid": 202,
            "version": "4.1.13.65",
            "process_start_time": "1000",
        },
    )()
    window = type("Window", (), {"hwnd": 101, "pid": 202, "visible": True})()
    prepared = type("Prepared", (), {"window": window})()

    class Backend:
        @staticmethod
        def prepare_main_window():
            return prepared

        @staticmethod
        def process_start_time(_pid):
            return "2000"

    driver = NativeWeixinDriver(gate_backend=Backend())
    driver._session = session

    with pytest.raises(StaleElementError, match="进程实例"):
        driver._prepare_existing_session()


def test_existing_session_rejects_changed_weixin_version():
    session = type(
        "Session",
        (),
        {
            "hwnd": 101,
            "pid": 202,
            "version": "4.1.13.65",
            "process_start_time": "1000",
        },
    )()
    window = type("Window", (), {"hwnd": 101, "pid": 202, "visible": True})()
    prepared = type("Prepared", (), {"window": window})()
    module = type("Module", (), {"path": "Weixin.dll"})()

    class Backend:
        @staticmethod
        def prepare_main_window():
            return prepared

        @staticmethod
        def process_start_time(_pid):
            return "1000"

        @staticmethod
        def find_module(_pid, _name):
            return module

        @staticmethod
        def file_version(_path):
            return "4.1.14.1"

    driver = NativeWeixinDriver(gate_backend=Backend())
    driver._session = session

    with pytest.raises(StaleElementError, match="版本已变化"):
        driver._prepare_existing_session()


def test_chat_title_ignores_matching_text_inside_search_popup_and_requires_composer():
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 1000, 800))
    popup = FakeControl(ClassName="mmui::XPopover")
    search_title = FakeControl(
        "Alice", "TextControl", BoundingRectangle=FakeRect(600, 50, 800, 90)
    )
    chat_title = FakeControl(
        "Alice",
        "TextControl",
        "mmui::XTextView",
        "content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label",
        BoundingRectangle=FakeRect(600, 100, 800, 140),
    )
    title_bar = FakeControl(ClassName="mmui::ChatTitleBarMasterView")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._selected_target = "Alice"
    driver._root = root
    driver._session = type(
        "Session", (), {"hwnd": 1, "profile": type("P", (), {"search_popup_class": "mmui::XPopover", "search_list_automation_id": "search_list"})()}
    )()
    driver._walk = lambda _hwnd: (
        root,
        [(root, 0), (popup, 1), (search_title, 2), (title_bar, 1), (chat_title, 2)],
    )
    driver._find_composer = lambda: object()

    assert driver.current_chat_title() == "Alice"
    driver._find_composer = lambda: None
    assert driver.current_chat_title() == ""


def test_chat_title_rejects_ordinary_matching_label_in_upper_right_quadrant():
    root = FakeControl(BoundingRectangle=FakeRect(0, 0, 1000, 800))
    unrelated = FakeControl(
        "Alice", "TextControl", "mmui::Label", BoundingRectangle=FakeRect(600, 50, 800, 90)
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._selected_target = "Alice"
    driver._root = root
    driver._session = type(
        "Session",
        (),
        {
            "hwnd": 1,
            "profile": type(
                "P",
                (),
                {
                    "search_popup_class": "mmui::XPopover",
                    "search_list_automation_id": "search_list",
                },
            )(),
        },
    )()
    driver._walk = lambda _hwnd: (root, [(root, 0), (unrelated, 1)])
    driver._find_composer = lambda: object()

    assert driver.current_chat_title() == ""


def test_message_verification_requires_a_new_matching_tail_and_empty_composer():
    old = FakeControl("old", "TextControl", "mmui::ChatTextItemView")
    new = FakeControl("hello", "TextControl", "mmui::ChatTextItemView")
    old.GetRuntimeId = lambda: (1, 1)
    new.GetRuntimeId = lambda: (1, 2)
    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = type("W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())})()
    driver._message_controls = lambda: [old, new]
    driver.read_composer_text = lambda: ""
    driver._all_nodes = lambda: []

    assert driver.verify_sent((((1, 1), "old"),), "hello", timeout=0.1) is True

    driver._message_controls = lambda: [old, new, FakeControl("other", "TextControl", "mmui::ChatTextItemView")]
    assert driver.verify_sent((((1, 1), "old"),), "hello", timeout=0.1) is None


def test_send_reuses_the_legacy_single_enter_path_without_button_actions():
    keys = []
    composer = {"text": "hello"}

    class Composer:
        def SendKeys(self, value, **_kwargs):
            keys.append(value)
            composer["text"] = ""

    control = Composer()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver._composer = control
    driver._find_composer = lambda: control
    driver._send_keys = lambda item, keys, **kwargs: item.SendKeys(keys) or item
    driver._find_scoped_controls = lambda **_kwargs: pytest.fail(
        "message sending must not query or activate a send button"
    )
    driver._click_bounds = lambda _control: pytest.fail(
        "message sending must not use coordinates"
    )
    driver.read_composer_text = lambda: composer["text"]
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()

    method = driver.trigger_send()

    assert method == "keyboard_enter"
    assert keys == ["{Enter}"]


def test_destructive_enter_is_never_replayed_when_unverified():
    keys = []

    class Composer:
        def SendKeys(self, value, **_kwargs):
            keys.append(value)

    control = Composer()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver._composer = control
    driver._find_composer = lambda: control
    driver._send_keys = lambda item, keys, **kwargs: item.SendKeys(keys) or item
    driver._click_bounds = lambda _control: pytest.fail(
        "an unverified destructive key must never be replayed with a click"
    )
    driver.read_composer_text = lambda: "hello"
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()

    with pytest.raises(ActionVerificationError, match="Enter"):
        driver.trigger_send()

    assert keys == ["{Enter}"]


def test_message_verification_does_not_reclassify_an_existing_message_as_new_tail():
    hello = FakeControl("hello", "TextControl", "mmui::ChatTextItemView")
    later = FakeControl("later", "TextControl", "mmui::ChatTextItemView")
    hello.GetRuntimeId = lambda: (1, 1)
    later.GetRuntimeId = lambda: (1, 2)
    controls = [hello, later]
    driver = NativeWeixinDriver(gate_backend=object())
    driver._message_controls = lambda: list(controls)
    before = driver.message_snapshot()
    controls[:] = [hello]
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    driver.read_composer_text = lambda: ""
    driver._all_nodes = lambda: []

    assert driver.verify_sent(before, "hello", timeout=0.1) is None


def test_message_verification_requires_explicit_current_composer_empty_readback():
    old = FakeControl("old", "TextControl", "mmui::ChatTextItemView")
    new = FakeControl("hello", "TextControl", "mmui::ChatTextItemView")
    old.GetRuntimeId = lambda: (1, 1)
    new.GetRuntimeId = lambda: (1, 2)
    controls = [old]
    driver = NativeWeixinDriver(gate_backend=object())
    driver._message_controls = lambda: list(controls)
    before = driver.message_snapshot()
    controls.append(new)
    driver._find_composer = lambda: None
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    driver._all_nodes = lambda: []

    assert driver.verify_sent(before, "hello", timeout=0.1) is None

    stale = FakeControl(
        "",
        "EditControl",
        "mmui::ChatInputField",
        "chat_input_field",
        IsOffscreen=True,
        BoundingRectangle=FakeRect(20, 150, 180, 190),
    )
    stale.GetValuePattern = lambda: type("Value", (), {"Value": ""})()
    driver._find_composer = lambda: stale

    assert driver.verify_sent(before, "hello", timeout=0.1) is None


def _bubble_snapshot(
    identity,
    *,
    class_name="mmui::ChatFileItemView",
    names=(),
    order=0,
    outgoing=True,
):
    runtime_id = tuple(identity[-1]) if identity and identity[0] == "runtime" else ()
    return MessageBubbleSnapshot(
        identity=identity,
        runtime_id=runtime_id,
        class_name=class_name,
        automation_id="",
        accessible_names=tuple(names),
        bounds=(500, 100, 700, 160),
        order=order,
        outgoing=outgoing,
    )


def test_attachment_snapshot_reads_filename_from_empty_named_file_bubble_descendants():
    profile = get_weixin_profile("4.1.13.65")
    bubble = FakeControl(
        "",
        "CustomControl",
        "mmui::ChatFileItemView",
        BoundingRectangle=FakeRect(500, 100, 700, 160),
    )
    bubble.GetRuntimeId = lambda: (42, 9)
    filename = FakeControl(
        "report.pdf",
        "TextControl",
        "mmui::XTextView",
        BoundingRectangle=FakeRect(520, 110, 620, 130),
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1, "profile": profile})()
    driver._attachment_snapshot_controls = lambda: (
        FakeRect(100, 50, 750, 500),
        [bubble],
        [bubble, filename],
    )

    snapshot = driver.attachment_snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].accessible_names == ("report.pdf",)
    assert snapshot[0].class_name == "mmui::ChatFileItemView"
    assert snapshot[0].outgoing is True


def test_attachment_snapshot_uses_one_message_subtree_query_for_all_bubbles():
    profile = get_weixin_profile("4.1.13.65")
    message_list = FakeControl(
        AutomationId="chat_message_list",
        BoundingRectangle=FakeRect(100, 50, 750, 500),
    )
    first = FakeControl(
        "",
        "CustomControl",
        "mmui::ChatFileItemView",
        BoundingRectangle=FakeRect(500, 100, 700, 160),
    )
    second = FakeControl(
        "",
        "CustomControl",
        "mmui::ChatFileItemView",
        BoundingRectangle=FakeRect(500, 180, 700, 240),
    )
    first.GetRuntimeId = lambda: (42, 1)
    second.GetRuntimeId = lambda: (42, 2)
    first_name = FakeControl(
        "one.pdf", "TextControl", BoundingRectangle=FakeRect(520, 110, 620, 130)
    )
    second_name = FakeControl(
        "two.pdf", "TextControl", BoundingRectangle=FakeRect(520, 190, 620, 210)
    )
    calls = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1, "profile": profile})()
    driver.ensure_window_responsive = lambda *_args, **_kwargs: None
    driver._message_bubbles = lambda: [first, second]

    def find_controls(**selector):
        calls.append(selector)
        if selector.get("automation_id") == "chat_message_list":
            return [message_list]
        if selector.get("root") is message_list:
            return [first, first_name, second, second_name]
        if selector.get("root") is first:
            return [first_name]
        if selector.get("root") is second:
            return [second_name]
        return []

    driver._find_scoped_controls = find_controls

    snapshot = driver.attachment_snapshot()

    assert [item.accessible_names for item in snapshot] == [
        ("one.pdf",),
        ("two.pdf",),
    ]
    assert len(calls) == 2


def test_attachment_snapshot_does_not_misclassify_full_width_row_as_incoming():
    profile = get_weixin_profile("4.1.13.65")
    message_rect = FakeRect(663, 304, 1288, 822)
    bubble = FakeControl(
        "文件\nv033-attachment-confirmation-20260915.txt\n157B\n微信电脑版",
        "ListItemControl",
        "mmui::ChatBubbleItemView",
        "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
        BoundingRectangle=FakeRect(663, 701, 1288, 822),
    )
    bubble.GetRuntimeId = lambda: (42, 99)
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1, "profile": profile})()
    driver._attachment_snapshot_controls = lambda: (
        message_rect,
        [bubble],
        [bubble],
    )

    snapshot = driver.attachment_snapshot()

    assert snapshot[0].outgoing is None


def test_attachment_verification_accepts_new_outgoing_file_bubble_and_cleared_draft():
    old = _bubble_snapshot(("runtime", (42, 1)), names=("old.pdf",))
    new = _bubble_snapshot(
        ("runtime", (42, 2)), names=("report.pdf",), order=1
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver.attachment_snapshot = lambda: (old, new)
    driver.read_composer_text = lambda: ""
    driver._attachment_draft_visible = lambda _filename: False
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    driver._raise_scoped_risk = lambda **_kwargs: None

    assert driver.verify_attachment_sent(
        (old,), "report.pdf", timeout=0.1, draft_was_visible=True
    ) is True


def test_attachment_verification_accepts_real_full_row_bubble_with_filename_token():
    old = _bubble_snapshot(("runtime", (42, 1)), names=("old.pdf",))
    new = _bubble_snapshot(
        ("runtime", (42, 2)),
        class_name="mmui::ChatBubbleItemView",
        names=("文件\nreport.pdf\n157B\n微信电脑版",),
        order=1,
        outgoing=None,
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver.attachment_snapshot = lambda: (old, new)
    driver.read_composer_text = lambda: ""
    driver._attachment_draft_visible = lambda _filename: False
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    driver._raise_scoped_risk = lambda **_kwargs: None

    assert driver.verify_attachment_sent(
        (old,), "report.pdf", timeout=0.1, draft_was_visible=False
    ) is True


def test_attachment_verification_rejects_new_incoming_file_bubble():
    old = _bubble_snapshot(("runtime", (42, 1)), names=("old.pdf",))
    incoming = _bubble_snapshot(
        ("runtime", (42, 2)), names=("report.pdf",), order=1, outgoing=False
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver.attachment_snapshot = lambda: (old, incoming)
    driver.read_composer_text = lambda: ""
    driver._attachment_draft_visible = lambda _filename: False
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    driver._raise_scoped_risk = lambda **_kwargs: None

    assert driver.verify_attachment_sent(
        (old,), "report.pdf", timeout=0.1, draft_was_visible=True
    ) is None


def test_send_files_uses_attachment_snapshot_and_never_text_name_verification(
    tmp_path, monkeypatch
):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"test")
    composer = object()
    calls = []
    before = (_bubble_snapshot(("runtime", (42, 1))),)
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"hwnd": 1})()
    driver._composer = composer
    driver.attachment_snapshot = lambda: before
    driver.message_snapshot = lambda: pytest.fail(
        "attachments must not rely on outer text-control names"
    )
    driver.verify_sent = lambda *_args, **_kwargs: pytest.fail(
        "attachments need file-bubble verification"
    )
    driver._click_bounds = lambda control: calls.append(("click", control))
    driver._send_keys = lambda control, keys, **_kwargs: (
        calls.append(("keys", keys)) or control
    )
    driver._attachment_draft_visible = lambda _filename: True
    driver._invoke_once_or_key = lambda *_args, **_kwargs: (
        calls.append(("send", "enter")) or "keyboard_enter"
    )

    def verify(before_arg, filename, timeout, *, draft_was_visible):
        assert before_arg == before
        assert filename == "report.pdf"
        assert draft_was_visible is True
        return True

    driver.verify_attachment_sent = verify
    monkeypatch.setattr(
        "src.utils.clipboard_utils.set_files_to_clipboard", lambda _paths: True
    )

    assert driver.send_files((str(path),))[0]["outcome"] == "success"
    assert [entry[0] for entry in calls] == ["click", "keys", "send"]


def test_forward_candidates_require_one_exact_interactive_identity():
    nested_text = FakeControl("Alice", "TextControl", "mmui::Label")
    alice = FakeControl(
        "Alice", "ListItemControl", "mmui::ForwardContactCell", "forward_item_1"
    )
    alice_team = FakeControl(
        "Alice Team", "ListItemControl", "mmui::ForwardContactCell", "forward_item_2"
    )

    assert extract_exact_forward_candidates(
        [(nested_text, 3), (alice, 2), (alice_team, 2)], " Alice "
    ) == [alice]


def test_forward_candidates_preserve_duplicate_rows_with_distinct_runtime_ids():
    first = FakeControl(
        "Alice", "ListItemControl", "mmui::ForwardContactCell", "forward_item_1"
    )
    duplicate = FakeControl(
        "Alice", "ListItemControl", "mmui::ForwardContactCell", "forward_item_1"
    )
    first.GetRuntimeId = lambda: (42, 1)
    duplicate.GetRuntimeId = lambda: (42, 2)

    assert extract_exact_forward_candidates(
        [(first, 2), (duplicate, 2)], "Alice"
    ) == [first, duplicate]


def test_forward_recipient_requires_explicit_selected_state_not_only_empty_search():
    candidate = FakeControl(
        "Alice", "ListItemControl", "mmui::ForwardContactCell", "forward_item_1"
    )
    selection = type("Selection", (), {"IsSelected": False})()
    candidate.GetSelectionItemPattern = lambda: selection
    search = FakeControl("搜索", "EditControl")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._all_nodes = lambda: [(candidate, 2)]
    driver._actions.read_text = lambda _control: ""

    assert driver._forward_recipient_selected("Alice", search) is False

    selection.IsSelected = True

    assert driver._forward_recipient_selected("Alice", search) is True


def test_forward_recipient_rejects_an_additional_selected_recipient():
    target = FakeControl(
        "Alice", "ListItemControl", "mmui::ForwardContactCell", "forward_item_1"
    )
    extra = FakeControl(
        "Bob",
        "ListItemControl",
        "mmui::ForwardContactCell",
        "forward_item_2",
        IsOffscreen=True,
    )
    target.GetSelectionItemPattern = lambda: type(
        "Selection", (), {"IsSelected": True}
    )()
    extra.GetSelectionItemPattern = lambda: type(
        "Selection", (), {"IsSelected": True}
    )()
    search = FakeControl("搜索", "EditControl")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._all_nodes = lambda: [(target, 2), (extra, 2)]

    assert driver._forward_recipient_selected("Alice", search) is False


def test_forward_bundle_revalidates_recipients_immediately_before_send():
    source = inspect.getsource(NativeWeixinDriver.forward_bundle)
    final_send = source[source.index("fresh_send =") :]

    assert final_send.index("self._forward_recipient_selected") < final_send.index(
        "self._invoke_once(fresh_send)"
    )


def test_forward_bundle_does_not_use_pattern_actions_that_can_replay_stale_controls():
    source = inspect.getsource(NativeWeixinDriver.forward_bundle)

    assert "self._actions.invoke(" not in source
    assert "self._actions.select(" not in source


def test_bound_forward_control_is_freshly_resolved_and_clicked_only_once():
    original = FakeControl(
        "合并转发", "ButtonControl", "mmui::XButton", "merge_forward"
    )
    fresh = FakeControl(
        "合并转发", "ButtonControl", "mmui::XButton", "merge_forward"
    )
    original.GetRuntimeId = lambda: (42, 11)
    fresh.GetRuntimeId = lambda: (42, 11)
    calls = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._matching_all_controls = lambda **_selector: [fresh]

    class Actions:
        @staticmethod
        def click(control, postcondition, **kwargs):
            calls.append((control, kwargs["pre_resolve_control"]()))
            assert postcondition() is True

    driver._actions = Actions()

    driver._click_bound_all_control_once(
        original,
        lambda: True,
        name=("合并转发", "合并发送"),
        visible=True,
    )

    assert calls == [(original, fresh)]


def test_forward_bubble_selection_uses_one_fresh_click_without_pattern_replay():
    original = FakeControl(
        "one.pdf", "ListItemControl", "mmui::ChatFileItemView", "file_1"
    )
    fresh = FakeControl(
        "one.pdf", "ListItemControl", "mmui::ChatFileItemView", "file_1"
    )
    original.GetRuntimeId = lambda: (42, 20)
    fresh.GetRuntimeId = lambda: (42, 20)
    selection = type("Selection", (), {"IsSelected": False})()
    fresh.GetSelectionItemPattern = lambda: selection
    calls = []
    driver = NativeWeixinDriver(gate_backend=object())
    driver._resolve_message_bubble = lambda _reference: fresh

    class Actions:
        @staticmethod
        def click(control, postcondition, **kwargs):
            calls.append((control, kwargs["pre_resolve_control"]()))
            selection.IsSelected = True
            assert postcondition() is True

        @staticmethod
        def select(*_args, **_kwargs):
            pytest.fail("forward bubbles must never use a replaying selection action")

    driver._actions = Actions()

    driver._select_forward_bubble(original)

    assert calls == [(fresh, fresh)]


def test_recent_message_bubbles_use_profile_classes_and_keep_order():
    controls = [
        FakeControl("old", "ListItemControl", "mmui::ChatBubbleItemView"),
        FakeControl("ignored", "TextControl", "mmui::Label"),
        FakeControl("one.pdf", "ListItemControl", "mmui::ChatFileItemView"),
        FakeControl("two.pdf", "ListItemControl", "mmui::ChatFileItemView"),
    ]

    assert filter_recent_message_bubbles(
        [(control, 1) for control in controls],
        ("mmui::ChatBubbleItemView", "mmui::ChatFileItemView"),
        2,
    ) == controls[-2:]


def test_forward_confirmation_requires_a_new_forward_record_card():
    existing = FakeControl(
        "普通消息", "ListItemControl", "mmui::ChatTextItemView", "old"
    )
    unrelated = FakeControl(
        "新收到的普通消息", "ListItemControl", "mmui::ChatTextItemView", "new"
    )
    record = FakeControl(
        "Alice 的聊天记录",
        "ListItemControl",
        "mmui::ChatRecordItemView",
        "record",
    )
    before = {
        (existing.Name, existing.ClassName, existing.AutomationId, None)
    }

    assert has_new_forward_confirmation([existing, unrelated], before) is False
    assert has_new_forward_confirmation([existing, unrelated, record], before) is True


def test_forward_confirmation_does_not_treat_moved_existing_record_as_new():
    record = FakeControl(
        "Alice 的聊天记录",
        "ListItemControl",
        "mmui::ChatRecordItemView",
        "record",
        BoundingRectangle=FakeRect(20, 40, 180, 80),
    )
    record.GetRuntimeId = lambda: (42, 7)
    driver = NativeWeixinDriver(gate_backend=object())
    driver._message_controls = lambda: [record]
    before = driver.message_snapshot()

    record.BoundingRectangle = FakeRect(20, 80, 180, 120)

    assert has_new_forward_confirmation([record], before) is False


def test_forward_confirmation_requires_the_new_record_to_be_the_tail():
    old = FakeControl(
        "普通消息", "ListItemControl", "mmui::ChatTextItemView", "old"
    )
    record = FakeControl(
        "Alice 的聊天记录",
        "ListItemControl",
        "mmui::ChatRecordItemView",
        "record",
    )
    later = FakeControl(
        "后到的普通消息",
        "ListItemControl",
        "mmui::ChatTextItemView",
        "later",
    )
    old.GetRuntimeId = lambda: (1, 1)
    record.GetRuntimeId = lambda: (1, 2)
    later.GetRuntimeId = lambda: (1, 3)
    before = ((('runtime', (1, 1)), "普通消息"),)

    assert has_new_forward_confirmation([old, record], before) is True
    assert has_new_forward_confirmation([old, record, later], before) is False


def test_forward_bundle_snapshots_the_target_chat_before_transfer_assistant():
    source = inspect.getsource(NativeWeixinDriver.forward_bundle)

    target_open = source.index('self._open_exact_chat(target)')
    snapshot = source.index('target_snapshot = self.message_snapshot()')
    transfer_open = source.index('self._open_exact_chat("文件传输助手")')

    assert target_open < snapshot < transfer_open


def test_friend_form_fields_are_resolved_by_exact_accessible_names():
    greeting = FakeControl("发送添加朋友申请", "EditControl")
    remark = FakeControl("修改备注", "EditControl")
    fields = resolve_friend_form_fields([(greeting, 3), (remark, 3)])
    assert fields == (greeting, remark)


def test_risk_controls_stop_the_workflow():
    warning = FakeControl("操作频繁，请稍后再试", "TextControl")
    with pytest.raises(RiskControlError, match="操作频繁"):
        raise_for_risk_controls([(warning, 2)])


def test_confirmed_wechat_restart_waits_for_supported_logged_in_window():
    class RecoveryBackend:
        def __init__(self):
            self.terminated = []
            self.started = []

        def process_path(self, pid):
            assert pid == 123
            return r"C:\Program Files\Tencent\Weixin\Weixin.exe"

        def terminate_process(self, pid):
            self.terminated.append(pid)

        def start_process(self, path):
            self.started.append(path)

    backend = RecoveryBackend()
    driver = NativeWeixinDriver(
        gate_backend=backend,
        sleep=lambda _seconds: None,
    )
    inspections = iter(
        [
            {"connected": True, "supported": True, "pid": 123},
            {"connected": False, "supported": False},
            {
                "connected": True,
                "supported": True,
                "pid": 456,
                "version": "4.1.13.65",
                "uiaReady": True,
            },
        ]
    )
    driver.inspect = lambda: next(inspections)
    session_closes = []
    driver._prepare_for_weixin_restart = lambda: session_closes.append("session")
    driver.close = lambda: pytest.fail(
        "restarting Weixin must retain the automation thread COM apartment"
    )
    notices = []

    result = driver.restart_wechat(
        timeout=90,
        emit=lambda method, params: notices.append((method, params)),
    )

    assert backend.terminated == [123]
    assert backend.started == [r"C:\Program Files\Tencent\Weixin\Weixin.exe"]
    assert session_closes == ["session"]
    assert result["version"] == "4.1.13.65"
    assert any(params["status"] == "waiting_login" for _method, params in notices)


def test_wechat_restart_terminates_the_old_process_tree_before_starting():
    events = []

    class RecoveryBackend:
        @staticmethod
        def process_path(_pid):
            return r"C:\Program Files\Tencent\Weixin\Weixin.exe"

        @staticmethod
        def terminate_process_tree(pid):
            events.append(("terminate-tree", pid))

        @staticmethod
        def start_process(path):
            events.append(("start", path))

    driver = NativeWeixinDriver(
        gate_backend=RecoveryBackend(),
        sleep=lambda seconds: events.append(("sleep", seconds)),
    )
    inspections = iter(
        [
            {"connected": True, "supported": True, "pid": 123},
            {
                "connected": True,
                "supported": True,
                "pid": 456,
                "version": "4.1.13.65",
                "uiaReady": True,
            },
        ]
    )
    driver.inspect = lambda: next(inspections)
    driver._prepare_for_weixin_restart = lambda: None

    driver.restart_wechat(timeout=90, emit=lambda *_args: None)

    assert events[:3] == [
        ("terminate-tree", 123),
        ("sleep", 1.0),
        ("start", r"C:\Program Files\Tencent\Weixin\Weixin.exe"),
    ]


def test_restart_handoff_preserves_screen_reader_until_the_new_session_takes_it():
    calls = []

    class Session:
        screen_reader_restore_value = False

        @staticmethod
        def close(*, preserve_screen_reader=False):
            calls.append(preserve_screen_reader)

    driver = NativeWeixinDriver(gate_backend=object())
    driver._lease_checked = True
    driver._session = Session()

    driver._prepare_for_weixin_restart()

    assert calls == [True]
    assert driver._session is None
    assert driver._screen_reader_restore_value is False


def test_new_weixin_session_adopts_the_restart_screen_reader_lease(monkeypatch):
    captured = []

    class Session:
        hwnd = 101

        def __init__(self, *_args, screen_reader_restore_value=None, **_kwargs):
            captured.append(screen_reader_restore_value)

        def __enter__(self):
            return self

    class Uia:
        @staticmethod
        def ControlFromHandle(hwnd):
            assert hwnd == 101
            return object()

    monkeypatch.setattr(
        "app.agent.native_driver.WeixinAccessibilitySession", Session
    )
    driver = NativeWeixinDriver(gate_backend=object())
    driver._lease_checked = True
    driver._uia_initialized = True
    driver._uia = Uia()
    driver._screen_reader_restore_value = False
    driver._wait_for = lambda *_args, **_kwargs: True

    driver._ensure_session()

    assert captured == [False]
    assert driver._screen_reader_restore_value is None
    assert driver._session_generation == 1


def test_soft_refresh_materializes_provider_with_true_broadcast_without_gate_toggle():
    from types import SimpleNamespace

    calls = []
    def broadcast():
        calls.append("broadcast_true")
        return True

    driver = NativeWeixinDriver(gate_backend=SimpleNamespace(
        broadcast_screen_reader_enabled=broadcast))
    driver._session = SimpleNamespace(hwnd=101)
    driver._uia = SimpleNamespace(ControlFromHandle=lambda _: object())
    driver.ensure_window_responsive = lambda *_: None
    driver._tree_materialized = lambda: calls == ["broadcast_true"]
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()

    assert driver.soft_refresh_session() == 1
    assert calls == ["broadcast_true"]


def test_reused_weixin_session_rebroadcasts_before_rebinding_the_uia_tree():
    calls = []

    class Backend:
        @staticmethod
        def broadcast_screen_reader_enabled():
            calls.append("broadcast")
            return True

    class Session:
        hwnd = 101
        pid = 202
        version = "4.1.13.65"

    class Uia:
        @staticmethod
        def ControlFromHandle(hwnd):
            assert hwnd == 101
            calls.append("root")
            return object()

    driver = NativeWeixinDriver(gate_backend=Backend())
    driver._lease_checked = True
    driver._uia_initialized = True
    driver._uia = Uia()
    driver._session = Session()
    driver._wait_for = (
        lambda *_args, **_kwargs: calls.append("wait") or True
    )

    driver._ensure_session()

    assert calls == ["broadcast", "root", "wait"]
    assert driver._session is not None
    assert driver._session_generation == 1


def test_reused_weixin_session_fails_closed_when_rebroadcast_is_rejected():
    class Backend:
        @staticmethod
        def broadcast_screen_reader_enabled():
            return False

    class Session:
        hwnd = 101
        pid = 202
        version = "4.1.13.65"

    driver = NativeWeixinDriver(gate_backend=Backend())
    driver._lease_checked = True
    driver._uia_initialized = True
    driver._session = Session()

    with pytest.raises(AccessibilitySafetyError, match="refresh.*broadcast"):
        driver._ensure_session()


def test_wechat_restart_discovers_the_old_process_without_opening_uia():
    class Module:
        path = "Weixin.dll"

    class RecoveryBackend:
        def __init__(self):
            self.terminated = []

        @staticmethod
        def window_inspection():
            return {"hwnd": 100, "pid": 123, "windowState": "visible"}

        @staticmethod
        def find_module(pid, name):
            assert (pid, name) == (123, "Weixin.dll")
            return Module()

        @staticmethod
        def file_version(_path):
            return "4.1.13.65"

        @staticmethod
        def process_path(pid):
            assert pid == 123
            return r"C:\Program Files\Tencent\Weixin\Weixin.exe"

        def terminate_process(self, pid):
            self.terminated.append(pid)

        @staticmethod
        def start_process(_path):
            pass

    backend = RecoveryBackend()
    driver = NativeWeixinDriver(
        gate_backend=backend,
        sleep=lambda _seconds: None,
    )
    driver.inspect = lambda: {
        "connected": True,
        "supported": True,
        "pid": 456,
        "version": "4.1.13.65",
        "uiaReady": True,
    }
    driver._prepare_for_weixin_restart = lambda: None

    result = driver.restart_wechat(timeout=90, emit=lambda *_args: None)

    assert backend.terminated == [123]
    assert result["pid"] == 456


def test_wechat_restart_waits_until_supported_uia_tree_is_ready():
    class RecoveryBackend:
        def process_path(self, _pid):
            return r"C:\Program Files\Tencent\Weixin\Weixin.exe"

        def terminate_process(self, _pid):
            pass

        def start_process(self, _path):
            pass

    driver = NativeWeixinDriver(
        gate_backend=RecoveryBackend(),
        sleep=lambda _seconds: None,
    )
    inspections = iter(
        [
            {"connected": True, "supported": True, "pid": 123},
            {
                "connected": True,
                "supported": True,
                "uiaReady": False,
                "version": "4.1.13.65",
            },
            {
                "connected": True,
                "supported": True,
                "uiaReady": True,
                "version": "4.1.13.65",
            },
        ]
    )
    driver.inspect = lambda: next(inspections)
    driver._prepare_for_weixin_restart = lambda: None

    result = driver.restart_wechat(timeout=90, emit=lambda *_args: None)

    assert result["uiaReady"] is True


def test_wechat_restart_restores_a_hidden_supported_window_before_waiting_again():
    class RecoveryBackend:
        def process_path(self, _pid):
            return r"C:\Program Files\Tencent\Weixin\Weixin.exe"

        def terminate_process(self, _pid):
            pass

        def start_process(self, _path):
            pass

    driver = NativeWeixinDriver(
        gate_backend=RecoveryBackend(),
        sleep=lambda _seconds: None,
    )
    inspections = iter(
        [
            {"connected": True, "supported": True, "pid": 123},
            {
                "connected": True,
                "supported": True,
                "version": "4.1.13.65",
                "uiaReady": False,
                "windowResponsive": True,
                "restorable": True,
            },
            {
                "connected": True,
                "supported": True,
                "version": "4.1.13.65",
                "uiaReady": True,
                "windowResponsive": True,
                "restorable": False,
            },
        ]
    )
    driver.inspect = lambda: next(inspections)
    driver._prepare_for_weixin_restart = lambda: None
    binds = []
    driver.bind_window = lambda: binds.append("bind") or {"connected": True}

    result = driver.restart_wechat(timeout=90, emit=lambda *_args: None)

    assert binds == ["bind"]
    assert result["uiaReady"] is True


def test_inspection_distinguishes_supported_version_from_uia_readiness(monkeypatch):
    from app.agent.retry import UiaTreeNotReadyError

    class Module:
        path = "Weixin.dll"

    class InspectBackend:
        def find_main_window(self):
            return 100

        def get_window_pid(self, hwnd):
            return 123

        def find_module(self, pid, name):
            return Module()

        def file_version(self, path):
            return "4.1.13.65"

    driver = NativeWeixinDriver(gate_backend=InspectBackend())
    monkeypatch.setattr(
        driver,
        "_ensure_session",
        lambda: (_ for _ in ()).throw(
            UiaTreeNotReadyError("tree has only 2 nodes")
        ),
    )

    inspection = driver.inspect()

    assert inspection["supported"] is True
    assert inspection["uiaReady"] is False
    assert inspection["processDetected"] is True
    assert inspection["versionSupported"] is True
    assert inspection["sessionReady"] is False
    assert inspection["windowResponsive"] is True
    assert inspection["degradedReason"] == "UIA_TREE_NOT_READY_AFTER_REFRESH"
    assert "2 nodes" in inspection["detail"]


def test_inspection_reports_stable_gate_safety_error_code(monkeypatch):
    class Module:
        path = "Weixin.dll"

    class InspectBackend:
        @staticmethod
        def find_main_window():
            return 100

        @staticmethod
        def get_window_pid(_hwnd):
            return 123

        @staticmethod
        def find_module(_pid, _name):
            return Module()

        @staticmethod
        def file_version(_path):
            return "4.1.13.65"

    driver = NativeWeixinDriver(gate_backend=InspectBackend())
    monkeypatch.setattr(
        driver,
        "_ensure_session",
        lambda: (_ for _ in ()).throw(
            AccessibilitySafetyError("gate byte changed")
        ),
    )

    inspection = driver.inspect()

    assert inspection["processDetected"] is True
    assert inspection["versionSupported"] is True
    assert inspection["sessionReady"] is False
    assert inspection["degradedReason"] == "GATE_SAFETY"
    assert "gate byte changed" in inspection["detail"]


def test_inspection_rebinds_when_process_generation_changed_without_resetting_com():
    class Module:
        path = "Weixin.dll"

    class InspectBackend:
        @staticmethod
        def window_inspection():
            return {
                "hwnd": 100,
                "pid": 123,
                "windowState": "visible",
                "restorable": False,
            }

        @staticmethod
        def find_module(_pid, _name):
            return Module()

        @staticmethod
        def file_version(_path):
            return "4.1.13.65"

        @staticmethod
        def process_start_time(_pid):
            return "new-generation"

        @staticmethod
        def window_responsive(_hwnd, timeout_ms=250):
            return timeout_ms == 250

    old_session = type(
        "Session",
        (),
        {
            "hwnd": 100,
            "pid": 123,
            "version": "4.1.13.65",
            "process_start_time": "old-generation",
        },
    )()
    driver = NativeWeixinDriver(gate_backend=InspectBackend())
    driver._session = old_session
    driver._uia_initialized = True
    calls = []

    def close_session():
        calls.append("close-session")
        driver._session = None

    def ensure_session():
        calls.append("ensure-session")
        driver._session = type(
            "Session",
            (),
            {
                "hwnd": 100,
                "pid": 123,
                "version": "4.1.13.65",
                "process_start_time": "new-generation",
            },
        )()

    driver._close_session_resources = close_session
    driver._ensure_session = ensure_session

    inspection = driver.inspect()

    assert inspection["sessionReady"] is True
    assert calls == ["close-session", "ensure-session"]
    assert driver._uia_initialized is True


def test_inspection_reports_hidden_supported_window_as_restorable_without_uia_init():
    class Module:
        path = "Weixin.dll"

    class InspectBackend:
        def window_inspection(self):
            return {
                "hwnd": 100,
                "pid": 123,
                "windowState": "hidden",
                "restorable": True,
                "visible": False,
            }

        def find_module(self, pid, name):
            assert (pid, name) == (123, "Weixin.dll")
            return Module()

        def file_version(self, path):
            assert path == "Weixin.dll"
            return "4.1.13.65"

    driver = NativeWeixinDriver(gate_backend=InspectBackend())
    driver._ensure_session = lambda: pytest.fail(
        "read-only inspection must not build UIA for a hidden window"
    )

    inspection = driver.inspect()

    assert inspection["connected"] is True
    assert inspection["supported"] is True
    assert inspection["uiaReady"] is False
    assert inspection["processDetected"] is True
    assert inspection["versionSupported"] is True
    assert inspection["sessionReady"] is False
    assert inspection["windowState"] == "hidden"
    assert inspection["restorable"] is True


def test_inspection_stops_before_uia_when_weixin_window_is_unresponsive():
    class Module:
        path = "Weixin.dll"

    class InspectBackend:
        @staticmethod
        def window_inspection():
            return {
                "hwnd": 100,
                "pid": 123,
                "windowState": "visible",
                "restorable": False,
                "visible": True,
            }

        @staticmethod
        def find_module(_pid, _name):
            return Module()

        @staticmethod
        def file_version(_path):
            return "4.1.13.65"

        @staticmethod
        def window_responsive(_hwnd, timeout_ms=250):
            assert timeout_ms == 250
            return False

    driver = NativeWeixinDriver(gate_backend=InspectBackend())
    driver._ensure_session = lambda: pytest.fail(
        "UIA session must not start for an unresponsive window"
    )

    inspection = driver.inspect()

    assert inspection["processDetected"] is True
    assert inspection["versionSupported"] is True
    assert inspection["windowResponsive"] is False
    assert inspection["sessionReady"] is False
    assert inspection["degradedReason"] == "WECHAT_UNRESPONSIVE"


def test_friend_search_does_not_treat_the_search_box_as_profile_identity():
    class SearchControl(FakeControl):
        def SendKeys(self, *_args, **_kwargs):
            pass

    search = SearchControl("18896904196", "EditControl")
    add_button = FakeControl("添加到通讯录", "ButtonControl")
    nickname = FakeControl("测试用户", "TextControl")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: add_button
    driver._walk = lambda _hwnd: (None, [(search, 1), (nickname, 2), (add_button, 2)])

    profile = driver.search_friend("18896904196")

    assert profile["account"] == ""


def test_set_friend_account_clears_a_stale_profile_before_new_query():
    class SearchControl(FakeControl):
        pass

    search = SearchControl("搜索", "EditControl", "mmui::XValidatorTextEdit")
    profile_active = {"value": True}
    current_text = {"value": "old-account"}
    writes = []

    class Actions:
        @staticmethod
        def read_text(_control):
            return current_text["value"]

        @staticmethod
        def set_text(_control, value, **_kwargs):
            writes.append(value)
            current_text["value"] = value
            if value == "":
                profile_active["value"] = False
            return type("Result", (), {"method": "value_pattern"})()

    profile = FakeControl(ClassName="mmui::ProfileViewNormal")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: search
    driver._walk = lambda _hwnd: (
        None,
        [(profile, 1)] if profile_active["value"] else [],
    )
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()
    driver._actions = Actions()

    method = driver.set_friend_account("18896904196")

    assert method == "value_pattern"
    assert writes == ["", "18896904196"]
    assert driver._friend_profile_reset_for == "18896904196"


def test_friend_search_reads_the_actual_labeled_profile_identity():
    class SearchControl(FakeControl):
        def SendKeys(self, *_args, **_kwargs):
            pass

    search = SearchControl("18896904196", "EditControl")
    add_button = FakeControl("添加到通讯录", "ButtonControl")
    profile_id = FakeControl("手机号：19170745267", "TextControl")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: add_button
    driver._walk = lambda _hwnd: (None, [(search, 1), (profile_id, 2), (add_button, 2)])

    profile = driver.search_friend("18896904196")

    assert profile["account"] == "19170745267"


def test_friend_search_accepts_exact_query_bound_to_real_unlabeled_profile_card():
    class SearchControl(FakeControl):
        def SendKeys(self, *_args, **_kwargs):
            pass

    account = "18896904196"
    search = SearchControl("搜索", "EditControl", "mmui::XValidatorTextEdit")
    profile_view = FakeControl(ClassName="mmui::ProfileViewNormal")
    profile_view.GetRuntimeId = lambda: (42, 6)
    action_view = FakeControl(
        ClassName="mmui::ProfileActionUi",
        AutomationId="content_v_view.ProfileActionUi",
    )
    add_button = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content_v_view.ProfileActionUi.add_friend_button",
    )
    add_button.GetRuntimeId = lambda: (42, 7)
    stale_same_name_button = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content_v_view.ProfileActionUi.add_friend_button",
    )
    stale_same_name_button.GetRuntimeId = lambda: (99, 1)
    nodes = [
        (profile_view, 5),
        (action_view, 8),
        (add_button, 9),
    ]
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._friend_account = account
    driver._friend_profile_reset_for = account
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: stale_same_name_button
    walk_calls = {"count": 0}

    def walk(_hwnd):
        walk_calls["count"] += 1
        return (None, [] if walk_calls["count"] == 1 else nodes)

    driver._walk = walk
    driver._actions.read_text = lambda control: account if control is search else None

    profile = driver.search_friend(account)

    assert profile["account"] == account
    assert profile["verification"] == "exact_query_profile_card"
    assert profile["control"] is add_button


def test_open_friend_request_refuses_a_changed_profile_button_before_clicking():
    class SearchControl(FakeControl):
        def SendKeys(self, *_args, **_kwargs):
            pass

    account = "18896904196"
    search = SearchControl("搜索", "EditControl", "mmui::XValidatorTextEdit")
    profile_view = FakeControl(ClassName="mmui::ProfileViewNormal")
    profile_view.GetRuntimeId = lambda: (42, 6)
    action_view = FakeControl(ClassName="mmui::ProfileActionUi")
    original = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
    )
    original.GetRuntimeId = lambda: (42, 7)
    replacement = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
    )
    replacement.GetRuntimeId = lambda: (42, 8)
    current_nodes = {"value": []}
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._friend_account = account
    driver._friend_profile_reset_for = account
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: original
    driver._walk = lambda _hwnd: (None, current_nodes["value"])
    driver._actions.read_text = lambda control: account if control is search else None

    current_nodes["value"] = []
    original_send_keys = search.SendKeys

    def show_profile(*args, **kwargs):
        original_send_keys(*args, **kwargs)
        current_nodes["value"] = [
            (profile_view, 5),
            (action_view, 8),
            (original, 9),
        ]

    search.SendKeys = show_profile
    profile = driver.search_friend(account)
    current_nodes["value"] = [(profile_view, 5), (action_view, 8), (replacement, 9)]
    driver._session = type(
        "Session",
        (),
        {
            "pid": 202,
            "profile": type("Profile", (), {"verify_friend_root_class": "verify"})(),
        },
    )()
    driver._process_windows = lambda *_args, **_kwargs: []
    driver._actions.invoke = lambda *_args, **_kwargs: pytest.fail(
        "a changed profile button must be rejected before any UIA action"
    )

    with pytest.raises(RuntimeError, match="资料卡已变化"):
        driver.open_friend_request(profile)


def test_friend_search_requires_the_old_profile_to_be_absent_before_enter():
    class SearchControl(FakeControl):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.entered = False

        def SendKeys(self, *_args, **_kwargs):
            self.entered = True

    account = "18896904196"
    search = SearchControl("搜索", "EditControl", "mmui::XValidatorTextEdit")
    stale_profile = FakeControl(ClassName="mmui::ProfileViewNormal")
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._friend_account = account
    driver._friend_profile_reset_for = account
    driver._add_hwnd = 100
    driver._walk = lambda _hwnd: (None, [(stale_profile, 5)])

    with pytest.raises(RuntimeError, match="搜索前仍有旧好友资料"):
        driver.search_friend(account)

    assert search.entered is False


def test_open_friend_request_rejects_an_existing_verify_form():
    class SearchControl(FakeControl):
        def SendKeys(self, *_args, **_kwargs):
            current_nodes["value"] = profile_nodes

    account = "18896904196"
    search = SearchControl("搜索", "EditControl", "mmui::XValidatorTextEdit")
    profile_view = FakeControl(ClassName="mmui::ProfileViewNormal")
    profile_view.GetRuntimeId = lambda: (42, 6)
    action_view = FakeControl(ClassName="mmui::ProfileActionUi")
    add_button = FakeControl(
        "添加到通讯录",
        "ButtonControl",
        "mmui::XOutlineButton",
        "content.ProfileActionUi.add_friend_button",
    )
    add_button.GetRuntimeId = lambda: (42, 7)
    profile_nodes = [(profile_view, 5), (action_view, 8), (add_button, 9)]
    current_nodes = {"value": []}
    driver = NativeWeixinDriver(gate_backend=object())
    driver._friend_search = search
    driver._friend_account = account
    driver._friend_profile_reset_for = account
    driver._add_hwnd = 100
    driver._wait_control = lambda **_selector: add_button
    driver._walk = lambda _hwnd: (None, current_nodes["value"])
    driver._actions.read_text = lambda control: account if control is search else None
    profile = driver.search_friend(account)
    driver._session = type(
        "Session",
        (),
        {"profile": type("Profile", (), {"verify_friend_root_class": "verify"})()},
    )()
    process_window_calls = []

    def process_windows(_classes, *, visible=True, strict=False):
        process_window_calls.append((visible, strict))
        return [777] if visible is None else []

    driver._process_windows = process_windows
    driver._actions.invoke = lambda *_args, **_kwargs: pytest.fail(
        "an existing verify form must block the profile action"
    )

    with pytest.raises(RuntimeError, match="旧的好友申请表单"):
        driver.open_friend_request(profile)

    assert process_window_calls == [(None, True)]


def test_process_window_strict_scan_rejects_an_unreadable_owned_qt_window(
    monkeypatch,
):
    import win32gui
    import win32process

    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"pid": 202})()
    driver._uia = type(
        "Uia",
        (),
        {
            "ControlFromHandle": staticmethod(
                lambda _hwnd: (_ for _ in ()).throw(RuntimeError("UIA unavailable"))
            )
        },
    )()
    monkeypatch.setattr(win32gui, "EnumWindows", lambda callback, extra: callback(777, extra))
    monkeypatch.setattr(
        win32process, "GetWindowThreadProcessId", lambda _hwnd: (1, 202)
    )
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda _hwnd: False)
    monkeypatch.setattr(win32gui, "GetClassName", lambda _hwnd: "Qt51514QWindowIcon")

    with pytest.raises(RuntimeError, match="无法安全解析同 PID"):
        driver._process_windows(("mmui::VerifyFriendWindow",), visible=None, strict=True)


@pytest.mark.parametrize("class_value", [None, ""])
def test_process_window_strict_scan_rejects_an_empty_uia_root_class(
    monkeypatch, class_value
):
    import win32gui
    import win32process

    root = type("Root", (), {"ClassName": class_value})()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type("Session", (), {"pid": 202})()
    driver._uia = type(
        "Uia", (), {"ControlFromHandle": staticmethod(lambda _hwnd: root)}
    )()
    monkeypatch.setattr(win32gui, "EnumWindows", lambda callback, extra: callback(777, extra))
    monkeypatch.setattr(
        win32process, "GetWindowThreadProcessId", lambda _hwnd: (1, 202)
    )
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda _hwnd: False)
    monkeypatch.setattr(win32gui, "GetClassName", lambda _hwnd: "Qt51514QWindowIcon")

    with pytest.raises(RuntimeError, match="UIA root class"):
        driver._process_windows(("mmui::VerifyFriendWindow",), visible=None, strict=True)


def test_open_add_friend_restores_one_hidden_owned_add_friend_window():
    driver = NativeWeixinDriver(gate_backend=object())
    profile = type("Profile", (), {"add_friend_root_class": "mmui::AddFriendWindow"})()
    driver._session = type("Session", (), {"profile": profile, "hwnd": 100, "pid": 202})()
    driver._ensure_session = lambda: None
    calls = []

    def process_windows(_classes, *, visible=True, strict=False):
        if visible is True:
            return []
        if visible is False:
            return [321]
        return [321]

    driver._process_windows = process_windows
    driver._restore_owned_process_window = (
        lambda hwnd, classes: calls.append((hwnd, classes)) or True
    )

    assert driver.open_add_friend() is True
    assert driver._add_hwnd == 321
    assert calls == [(321, ("mmui::AddFriendWindow",))]


def test_open_add_friend_activates_an_existing_visible_window_before_clicks():
    driver = NativeWeixinDriver(gate_backend=object())
    profile = type("Profile", (), {"add_friend_root_class": "mmui::AddFriendWindow"})()
    driver._session = type("Session", (), {"profile": profile, "hwnd": 100, "pid": 202})()
    driver._ensure_session = lambda: None
    driver._process_windows = lambda _classes, **_kwargs: [321]
    calls = []
    driver._restore_owned_process_window = (
        lambda hwnd, classes: calls.append((hwnd, classes)) or True
    )

    assert driver.open_add_friend() is True
    assert driver._add_hwnd == 321
    assert calls == [(321, ("mmui::AddFriendWindow",))]


def test_open_add_friend_safely_closes_one_leftover_verify_form_first():
    driver = NativeWeixinDriver(gate_backend=object())
    profile = type(
        "Profile",
        (),
        {
            "add_friend_root_class": "mmui::AddFriendWindow",
            "verify_friend_root_class": "mmui::VerifyFriendWindow",
        },
    )()
    driver._session = type(
        "Session", (), {"profile": profile, "hwnd": 100, "pid": 202}
    )()
    driver._ensure_session = lambda: None
    calls = []

    def process_windows(classes, *, visible=True, strict=False):
        if classes == ("mmui::VerifyFriendWindow",):
            calls.append(("scan-verify", visible, strict))
            return [444]
        return [321] if visible is True else []

    driver._process_windows = process_windows

    def cancel():
        calls.append(("cancel", driver._verify_hwnd))
        driver._verify_hwnd = 0
        return True

    driver.cancel_friend_request = cancel
    driver._restore_owned_process_window = lambda _hwnd, _classes: True

    assert driver.open_add_friend() is True
    assert calls[:2] == [
        ("scan-verify", None, True),
        ("cancel", 444),
    ]
    assert driver._add_hwnd == 321


def test_driver_close_retains_gate_session_when_cleanup_needs_retry():
    class RetrySession:
        def __init__(self):
            self.calls = 0

        def close(self):
            self.calls += 1
            if self.calls == 1:
                raise AccessibilitySafetyError("gate restore retry required")

    session = RetrySession()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = session

    with pytest.raises(AccessibilitySafetyError, match="retry required"):
        driver.close()

    assert driver._session is session

    driver.close()

    assert session.calls == 2
    assert driver._session is None


def test_session_enter_failure_keeps_the_gate_session_available_for_cleanup(
    monkeypatch,
):
    instances = []

    class EnterCleanupRetrySession:
        def __init__(self, _backend, **_kwargs):
            self.close_calls = 0
            instances.append(self)

        def __enter__(self):
            # Model WeixinAccessibilitySession attempting its own rollback and
            # failing before __enter__ can return.
            self.close()

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise AccessibilitySafetyError("first gate rollback failed")

    monkeypatch.setattr(
        "app.agent.native_driver.WeixinAccessibilitySession",
        EnterCleanupRetrySession,
    )
    monkeypatch.setattr(
        "src.core.uiautomation.InitializeUIAutomationInCurrentThread",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.core.uiautomation.UninitializeUIAutomationInCurrentThread",
        lambda: None,
    )
    driver = NativeWeixinDriver(gate_backend=object())

    with pytest.raises(AccessibilitySafetyError, match="first gate rollback failed"):
        driver._ensure_session()

    assert instances[0].close_calls == 2
    assert driver._session is None


def test_driver_close_attempts_gate_cleanup_when_subscription_close_fails():
    events = []

    class BrokenSubscription:
        def close(self):
            events.append("subscription")
            raise RuntimeError("subscription cleanup failed")

    class Session:
        def close(self):
            events.append("gate")

    driver = NativeWeixinDriver(gate_backend=object())
    driver._event_subscription = BrokenSubscription()
    driver._session = Session()

    with pytest.raises(RuntimeError, match="subscription cleanup failed"):
        driver.close()

    assert events == ["subscription", "gate"]
    assert driver._session is None


def test_transient_tree_materialization_failure_keeps_one_gate_session(
    monkeypatch,
):
    from app.agent.retry import UiaTreeNotReadyError

    instances = []
    initialization_calls = []

    class LongLivedSession:
        hwnd = 101
        pid = 202
        version = "4.1.13.65"

        def __init__(self, _backend, **_kwargs):
            self.enter_calls = 0
            self.close_calls = 0
            instances.append(self)

        def __enter__(self):
            self.enter_calls += 1
            return self

        def close(self):
            self.close_calls += 1

    root = FakeControl(
        "微信",
        "WindowControl",
        "mmui::MainWindow",
        "main",
        BoundingRectangle=FakeRect(0, 0, 200, 200),
    )
    monkeypatch.setattr(
        "app.agent.native_driver.WeixinAccessibilitySession",
        LongLivedSession,
    )
    monkeypatch.setattr(
        "app.agent.native_driver.restore_gate_lease",
        lambda *_args: {"restored": False},
    )
    monkeypatch.setattr(
        "src.core.uiautomation.InitializeUIAutomationInCurrentThread",
        lambda: initialization_calls.append("com"),
    )
    monkeypatch.setattr(
        "src.core.uiautomation.ControlFromHandle",
        lambda _hwnd: root,
    )
    driver = NativeWeixinDriver(gate_backend=object())
    readiness = iter((False, True))
    driver._wait_for = lambda *_args, **_kwargs: next(readiness)

    with pytest.raises(UiaTreeNotReadyError, match="UIA 控件树未就绪"):
        driver._ensure_session()

    assert len(instances) == 1
    assert instances[0].enter_calls == 1
    assert instances[0].close_calls == 0
    assert driver._session is instances[0]
    assert driver._root is None

    driver._ensure_session()

    assert len(instances) == 1
    assert instances[0].enter_calls == 1
    assert initialization_calls == ["com"]
    assert driver._root is root


def test_driver_keeps_com_alive_until_failed_event_cleanup_can_retry():
    events = []

    class RetrySubscription:
        def __init__(self):
            self.calls = 0

        def close(self):
            self.calls += 1
            events.append(f"subscription-{self.calls}")
            if self.calls == 1:
                raise RuntimeError("subscription cleanup failed")

    class Uia:
        @staticmethod
        def ResetUIAutomationClientInCurrentThread():
            events.append("release-uia")

        @staticmethod
        def UninitializeUIAutomationInCurrentThread():
            events.append("uninitialize-com")

    driver = NativeWeixinDriver(gate_backend=object())
    driver._event_subscription = RetrySubscription()
    driver._uia = Uia()
    driver._uia_initialized = True

    with pytest.raises(RuntimeError, match="subscription cleanup failed"):
        driver.close()

    assert driver._uia_initialized is True
    assert events == ["subscription-1"]

    driver.close()

    assert events == [
        "subscription-1",
        "subscription-2",
        "release-uia",
        "uninitialize-com",
    ]


def test_driver_cleanup_order_releases_proxies_before_gate_and_com():
    events = []

    class Subscription:
        def close(self):
            events.append("cancel-events")

    class Session:
        def close(self):
            events.append("restore-gate")

    class Uia:
        @staticmethod
        def ResetUIAutomationClientInCurrentThread():
            events.append("release-uia")

        @staticmethod
        def UninitializeUIAutomationInCurrentThread():
            events.append("uninitialize-com")

    driver = NativeWeixinDriver(gate_backend=object())
    driver._event_subscription = Subscription()
    driver._session = Session()
    driver._uia = Uia()
    driver._uia_initialized = True
    driver._release_control_proxies = lambda: events.append("release-proxies")

    driver.close()

    assert events == [
        "cancel-events",
        "release-proxies",
        "restore-gate",
        "release-uia",
        "uninitialize-com",
    ]


def test_friend_submit_requires_an_explicit_success_status(monkeypatch):
    class ImmediateWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            return bool(predicate())

    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = ImmediateWaiter()
    driver._verify_hwnd = 0
    driver._add_hwnd = 100
    driver._all_nodes = lambda: [(FakeControl("添加到通讯录", "ButtonControl"), 1)]
    driver._walk = lambda _hwnd: (
        None,
        [(FakeControl("添加到通讯录", "ButtonControl"), 1)],
    )

    assert driver.verify_friend_request(timeout=0.1) is None


def test_friend_submit_accepts_confirm_window_close_with_visible_weixin_owner(
    monkeypatch,
):
    class ImmediateWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            return bool(predicate())

    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = ImmediateWaiter()
    driver._verify_hwnd = 303
    driver._add_hwnd = 100
    driver._session = type("Session", (), {"hwnd": 101, "pid": 202})()
    driver._raise_process_risk = lambda: None
    driver._raise_scoped_risk = lambda **_kwargs: None
    driver._find_scoped_controls = lambda **_kwargs: []
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd != 303)
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    monkeypatch.setattr(
        "win32gui.IsWindowVisible", lambda hwnd: hwnd in {100, 101}
    )

    assert driver.verify_friend_request(timeout=0.1) is True
    assert driver._verify_hwnd == 0


@pytest.mark.parametrize("closed", [{100, 303}, {100}])
def test_friend_verification_does_not_probe_disappeared_dialogs(monkeypatch, closed):
    from types import SimpleNamespace

    # Submit can destroy both the add-friend owner and its confirmation form.
    # A dead HWND fails WM_NULL just like a hung window, but is not a hung main.
    checked = []
    def responsive(hwnd, **_kwargs):
        checked.append(hwnd)
        return hwnd not in closed

    driver = NativeWeixinDriver(gate_backend=SimpleNamespace(window_responsive=responsive))
    driver._session = SimpleNamespace(hwnd=101, pid=202)
    driver._add_hwnd, driver._verify_hwnd = 100, 303
    driver._uia = SimpleNamespace()
    def root(hwnd):
        driver.ensure_window_responsive(hwnd)
        return FakeControl("微信", "WindowControl")
    driver._control_root = root
    monkeypatch.setattr("app.agent.native_driver.subscribe_uia_events", lambda *_: None)
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd not in closed)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd not in closed)
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    driver._raise_process_risk = lambda: driver.ensure_window_responsive(101)
    driver._raise_scoped_risk = lambda hwnd: driver.ensure_window_responsive(hwnd)
    driver._find_scoped_controls = lambda **_kwargs: []

    result = driver.verify_friend_request(timeout=0.01)

    assert result is (True if 303 in closed else None)
    assert not closed.intersection(checked)


@pytest.mark.parametrize("owner_pid", [202, 999])
def test_friend_verification_closed_form_keeps_live_owner_safety(monkeypatch, owner_pid):
    from types import SimpleNamespace

    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = SimpleNamespace(hwnd=101, pid=202)
    driver._verify_hwnd, driver._add_hwnd = 303, 100
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd == 101)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd == 101)
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, owner_pid))
    driver._raise_process_risk = lambda: None
    driver._raise_scoped_risk = lambda **_kwargs: None
    driver._find_scoped_controls = lambda **_kwargs: []
    assert driver.verify_friend_request(0.01) is (True if owner_pid == 202 else None)

    if owner_pid == 202:
        def hung(**_kwargs):
            raise WeixinUnresponsiveError("live owner is unresponsive")
        driver._verify_hwnd = 303
        driver._raise_process_risk = hung
        with pytest.raises(WeixinUnresponsiveError):
            driver.verify_friend_request(0.01)


def test_friend_verification_ignores_success_words_in_main_chat(monkeypatch):
    from types import SimpleNamespace

    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = SimpleNamespace(hwnd=101, pid=202)
    driver._verify_hwnd, driver._add_hwnd = 303, 100
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: True)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    driver._raise_process_risk = lambda: None
    driver._raise_scoped_risk = lambda **_kwargs: None
    driver._find_scoped_controls = lambda hwnd, **_kwargs: [FakeControl("申请已提交")] if hwnd == 101 else []
    assert driver.verify_friend_request(0.01) is None


@pytest.mark.parametrize("stage", ["enumeration", "risk_scan"])
@pytest.mark.parametrize("disappears", [True, False])
def test_process_risk_scan_skips_only_disappeared_auxiliary(monkeypatch, stage, disappears):
    from types import SimpleNamespace

    alive = {101, 100}
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd in alive)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd in alive)
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    monkeypatch.setattr("win32gui.EnumWindows", lambda callback, extra: callback(100, extra))
    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = SimpleNamespace(hwnd=101, pid=202)
    driver._query = object()
    driver._control_root = lambda hwnd: FakeControl("微信", "WindowControl")
    def probe(hwnd):
        if hwnd == 100 and stage == "enumeration":
            if disappears:
                alive.remove(100)
            raise WeixinUnresponsiveError("destroyed during enumeration")
        return True
    driver.ensure_window_responsive = probe
    def risk(hwnd, root):
        if hwnd == 100:
            if disappears:
                alive.remove(100)
            raise WeixinUnresponsiveError("destroyed during risk scan")
    driver._raise_scoped_risk = risk
    if disappears:
        driver._raise_process_risk()
    else:
        with pytest.raises(WeixinUnresponsiveError):
            driver._raise_process_risk()


def test_friend_preflight_closes_the_request_form_with_invoke_pattern(monkeypatch):
    state = {"visible": True}

    class Pattern:
        @staticmethod
        def Invoke(**_kwargs):
            state["visible"] = False
            return True

    cancel = FakeControl("取消", "ButtonControl")
    cancel.GetInvokePattern = lambda: Pattern()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._verify_hwnd = 303
    driver._wait_control = lambda **_selector: cancel
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args: predicate())}
    )()
    monkeypatch.setattr("win32gui.IsWindow", lambda _hwnd: state["visible"])
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda _hwnd: state["visible"])

    assert driver.cancel_friend_request() is True
    assert driver._verify_hwnd == 0


def _friend_submit_fixture(monkeypatch, controls, *, root_class=None, root_pid=202):
    profile = get_weixin_profile("4.1.13.65")
    root = FakeControl(
        "发送添加朋友申请",
        "WindowControl",
        root_class or profile.verify_friend_root_class,
        BoundingRectangle=FakeRect(100, 100, 700, 600),
    )
    root.NativeWindowHandle = 303
    root.ProcessId = root_pid
    root.GetTopLevelControl = lambda: root
    for control in controls:
        control.GetTopLevelControl = lambda owner=root: owner

    driver = NativeWeixinDriver(gate_backend=object())
    driver._session = type(
        "Session",
        (),
        {"hwnd": 101, "pid": 202, "profile": profile},
    )()
    driver._verify_hwnd = 303
    clicks = []
    hit_control = controls[0] if controls else root
    driver._uia = type(
        "Uia",
        (),
        {
            "ControlFromHandle": staticmethod(lambda _hwnd: root),
            "ControlFromPoint": staticmethod(lambda _x, _y: hit_control),
            "Click": staticmethod(lambda x, y: clicks.append((x, y))),
        },
    )()
    driver._process_windows = lambda *_args, **_kwargs: [303]
    driver._find_scoped_controls = lambda **_selector: list(controls)
    driver._raise_scoped_risk = lambda **_selector: None
    driver.ensure_window_responsive = lambda *_args, **_kwargs: None
    driver._prepare_click_window = lambda *_args, **_kwargs: None
    driver._test_submit_clicks = clicks
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd == 303)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda _hwnd: (1, 202)
    )
    return driver, root


def _friend_confirm(*, runtime_id=(42, 1), offscreen=False, enabled=True):
    calls = []

    class Pattern:
        @staticmethod
        def Invoke(**_kwargs):
            calls.append("invoke")
            return True

    control = FakeControl(
        "确定",
        "ButtonControl",
        "mmui::XOutlineButton",
        IsEnabled=enabled,
        IsOffscreen=offscreen,
        BoundingRectangle=FakeRect(500, 520, 580, 560),
    )
    control.GetRuntimeId = lambda: runtime_id
    control.GetInvokePattern = lambda: Pattern()
    return control, calls


def test_friend_submit_uses_one_hit_tested_bounds_click_not_false_invoke(monkeypatch):
    confirm, calls = _friend_confirm()
    driver, _root = _friend_submit_fixture(monkeypatch, [confirm])

    receipt = driver.submit_friend_request()

    assert isinstance(receipt, FriendSubmitReceipt)
    assert receipt.triggered is True
    assert receipt.method == "uia_bounds_click"
    assert driver._test_submit_clicks == [(540, 540)]
    assert calls == []


def test_friend_submit_rejects_a_hit_test_from_another_control_before_click(
    monkeypatch,
):
    confirm, calls = _friend_confirm()
    driver, root = _friend_submit_fixture(monkeypatch, [confirm])
    covered = FakeControl(
        "取消",
        "ButtonControl",
        "mmui::XOutlineButton",
        BoundingRectangle=FakeRect(500, 520, 580, 560),
    )
    covered.GetTopLevelControl = lambda: root
    driver._uia.ControlFromPoint = lambda _x, _y: covered

    with pytest.raises(RuntimeError) as raised:
        driver.submit_friend_request()

    assert getattr(raised.value, "destructive_triggered", "missing") is False
    assert driver._test_submit_clicks == []
    assert calls == []


def test_friend_submit_marks_click_transport_failure_as_unknown(monkeypatch):
    confirm, calls = _friend_confirm()
    driver, _root = _friend_submit_fixture(monkeypatch, [confirm])
    driver._uia.Click = lambda _x, _y: (_ for _ in ()).throw(
        RuntimeError("click transport disconnected")
    )

    with pytest.raises(RuntimeError) as raised:
        driver.submit_friend_request()

    assert getattr(raised.value, "destructive_triggered", "missing") is None
    assert calls == []


def test_friend_submit_rejects_ambiguous_confirm_buttons_without_invoking(
    monkeypatch,
):
    first, first_calls = _friend_confirm(runtime_id=(42, 1))
    second, second_calls = _friend_confirm(runtime_id=(42, 2))
    driver, _root = _friend_submit_fixture(monkeypatch, [first, second])

    with pytest.raises(RuntimeError, match="唯一"):
        driver.submit_friend_request()

    assert first_calls == []
    assert second_calls == []


def test_friend_submit_rejects_offscreen_confirm_without_invoking(monkeypatch):
    confirm, calls = _friend_confirm(offscreen=True)
    driver, _root = _friend_submit_fixture(monkeypatch, [confirm])

    with pytest.raises(RuntimeError, match="不可见"):
        driver.submit_friend_request()

    assert calls == []


@pytest.mark.parametrize(
    ("root_class", "root_pid"),
    [("mmui::MainWindow", 202), ("mmui::VerifyFriendWindow", 999)],
)
def test_friend_submit_rejects_wrong_verification_window_identity(
    monkeypatch, root_class, root_pid
):
    confirm, calls = _friend_confirm()
    driver, _root = _friend_submit_fixture(
        monkeypatch,
        [confirm],
        root_class=root_class,
        root_pid=root_pid,
    )

    with pytest.raises(RuntimeError, match="申请窗口"):
        driver.submit_friend_request()

    assert calls == []


def test_friend_submit_rejects_recycled_confirm_between_resolutions(monkeypatch):
    first, first_calls = _friend_confirm(runtime_id=(42, 1))
    replacement, replacement_calls = _friend_confirm(runtime_id=(42, 2))
    driver, root = _friend_submit_fixture(monkeypatch, [first])
    replacement.GetTopLevelControl = lambda: root
    snapshots = iter(([first], [replacement]))
    driver._find_scoped_controls = lambda **_selector: list(next(snapshots))

    with pytest.raises(RuntimeError, match="变化"):
        driver.submit_friend_request()

    assert first_calls == []
    assert replacement_calls == []


def test_friend_preflight_falls_back_to_window_close_after_false_invoke(
    monkeypatch,
):
    state = {"visible": True}
    actions = []

    class CancelPattern:
        @staticmethod
        def Invoke(**_kwargs):
            actions.append("cancel-invoke")
            return True

    class WindowPattern:
        @staticmethod
        def Close():
            actions.append("window-close")
            state["visible"] = False
            return True

    cancel = FakeControl("取消", "ButtonControl", "mmui::XOutlineButton")
    cancel.GetInvokePattern = lambda: CancelPattern()
    root = FakeControl("发送添加朋友申请", "WindowControl")
    root.GetWindowPattern = lambda: WindowPattern()
    driver = NativeWeixinDriver(gate_backend=object())
    driver._verify_hwnd = 303
    driver._wait_control = lambda **_selector: cancel
    driver._uia = type(
        "Uia", (), {"ControlFromHandle": staticmethod(lambda _hwnd: root)}
    )()
    driver._wait_for = lambda predicate, *_args, **_kwargs: predicate()
    monkeypatch.setattr("win32gui.IsWindow", lambda _hwnd: state["visible"])
    monkeypatch.setattr(
        "win32gui.IsWindowVisible", lambda _hwnd: state["visible"]
    )

    assert driver.cancel_friend_request() is True
    assert actions == ["cancel-invoke", "window-close"]
    assert driver._verify_hwnd == 0


def test_waiter_accepts_a_completed_window_close_before_response_probe():
    class Backend:
        @staticmethod
        def window_responsive(*_args, **_kwargs):
            pytest.fail("a destroyed success handle must not be probed")

    driver = NativeWeixinDriver(gate_backend=Backend())

    assert driver._wait_for(lambda: True, 0.1, hwnd=303) is True


def test_friend_submit_checks_risk_controls_even_after_form_closes():
    class ImmediateWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            return bool(predicate())

    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = ImmediateWaiter()
    driver._verify_hwnd = 0
    driver._add_hwnd = 100
    driver._all_nodes = lambda: [(FakeControl("操作频繁，请稍后再试", "TextControl"), 1)]
    driver._walk = lambda _hwnd: (None, [])

    with pytest.raises(RiskControlError, match="操作频繁"):
        driver.verify_friend_request(timeout=0.1)


def test_friend_submit_accepts_an_explicit_success_status(monkeypatch):
    class ImmediateWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            return bool(predicate())

    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = ImmediateWaiter()
    driver._verify_hwnd = 0
    driver._add_hwnd = 100
    driver._session = type("Session", (), {"hwnd": 101, "pid": 202})()
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: hwnd in {100, 101})
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd in {100, 101})
    monkeypatch.setattr("win32process.GetWindowThreadProcessId", lambda hwnd: (1, 202))
    driver._all_nodes = lambda: []
    driver._walk = lambda _hwnd: (
        None,
        [(FakeControl("朋友申请已发送", "TextControl"), 1)],
    )

    assert driver.verify_friend_request(timeout=0.1) is True
