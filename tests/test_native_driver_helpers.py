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
from app.agent.profile import UnsupportedWeixinVersion


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


def test_search_returns_empty_only_after_bounded_no_match_wait():
    class SearchEdit(FakeControl):
        value = "old"

    class Actions:
        @staticmethod
        def set_text(control, value, **_kwargs):
            control.value = value

        @staticmethod
        def read_text(control):
            return control.value

    class ExhaustingWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            for _ in range(5):
                if predicate():
                    return True
            return False

    old = SearchCandidate(
        "old", frozenset({"old"}), "contact", "search_item_1", 0, 1
    )
    snapshots = iter((([old], [object()]), ([], [])))
    driver = NativeWeixinDriver(gate_backend=object())
    driver.ensure_search_ready = lambda: True
    driver._search_edit = SearchEdit()
    driver._actions = Actions()
    driver._waiter = ExhaustingWaiter()
    driver._search_rows = lambda: next(snapshots, ([], []))

    assert driver.search_contacts("missing") == []


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


def test_select_reopens_search_once_when_pattern_hides_results_without_navigation():
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
    driver._resolve_search_candidate = lambda value: (
        stale if value is candidate else fresh
    )
    driver._search_candidate_present = lambda _candidate: False
    driver._actions = type(
        "Actions",
        (),
        {
            "select": staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    ActionVerificationError("source disappeared")
                )
            )
        },
    )()
    driver.search_contacts = lambda target: searches.append(target) or [refreshed]
    driver._click_search_candidate = lambda control: clicks.append(control)
    driver.composer_ready = lambda: bool(clicks)
    driver.current_chat_title = lambda: "Alice" if clicks else ""
    driver._waiter = type(
        "W", (), {"wait": staticmethod(lambda predicate, *_args, **_kwargs: predicate())}
    )()

    driver.select_search_result(candidate)

    assert searches == ["Alice"]
    assert clicks == [fresh]


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

    driver.select_search_result(candidate)

    assert driver.current_chat_title() == "Alice 备注"


def test_bind_window_rebinds_once_when_first_root_is_invisible(monkeypatch):
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
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda _hwnd: True)

    result = driver.bind_window()

    assert result["hwnd"] == 2
    assert first.closed is True


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
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda _hwnd: True)

    result = driver.bind_window()

    assert backend.calls == 1
    assert result["windowRestore"]["restored"] is True


def test_bind_window_retries_initialization_exception_with_one_cleanup(monkeypatch):
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
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda _hwnd: True)

    result = driver.bind_window()

    assert result["hwnd"] == 2
    assert attempts == [1, 2]
    assert cleanups == ["close"]


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
        "src.core.win32.bring_window_to_front",
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
        "src.core.win32.bring_window_to_front",
        lambda _hwnd: pytest.fail("activation must not run"),
    )

    with pytest.raises(RuntimeError, match="gate write-back"):
        driver.bind_window()

    assert attempts == [1]


def test_bind_window_retries_transient_error_even_when_message_mentions_restore(
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
    monkeypatch.setattr("src.core.win32.bring_window_to_front", lambda _hwnd: True)

    result = driver.bind_window()

    assert result["hwnd"] == 2
    assert attempts == [1, 2]
    assert cleanups == ["close"]


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
        "src.core.win32.bring_window_to_front",
        lambda _hwnd: (_ for _ in ()).throw(RuntimeError("foreground denied")),
    )

    with pytest.raises(RuntimeError) as raised:
        driver.bind_window()

    detail = str(raised.value)
    assert attempts == [1, 1]
    assert "action=bind_window.activate" in detail
    assert "ControlType='WindowControl'" in detail
    assert "ClassName='mmui::MainWindow'" in detail
    assert "bounds=(0,0,200,200)" in detail


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
    notices = []

    result = driver.restart_wechat(
        timeout=90,
        emit=lambda method, params: notices.append((method, params)),
    )

    assert backend.terminated == [123]
    assert backend.started == [r"C:\Program Files\Tencent\Weixin\Weixin.exe"]
    assert result["version"] == "4.1.13.65"
    assert any(params["status"] == "waiting_login" for _method, params in notices)


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

    result = driver.restart_wechat(timeout=90, emit=lambda *_args: None)

    assert result["uiaReady"] is True


def test_inspection_distinguishes_supported_version_from_uia_readiness(monkeypatch):
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
        lambda: (_ for _ in ()).throw(RuntimeError("tree has only 2 nodes")),
    )

    inspection = driver.inspect()

    assert inspection["supported"] is True
    assert inspection["uiaReady"] is False
    assert "2 nodes" in inspection["detail"]


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
    assert inspection["windowState"] == "hidden"
    assert inspection["restorable"] is True


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
        def __init__(self, _backend):
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


def test_friend_submit_accepts_an_explicit_success_status():
    class ImmediateWaiter:
        def wait(self, predicate, *_args, **_kwargs):
            return bool(predicate())

    driver = NativeWeixinDriver(gate_backend=object())
    driver._waiter = ImmediateWaiter()
    driver._verify_hwnd = 0
    driver._add_hwnd = 100
    driver._all_nodes = lambda: []
    driver._walk = lambda _hwnd: (
        None,
        [(FakeControl("朋友申请已发送", "TextControl"), 1)],
    )

    assert driver.verify_friend_request(timeout=0.1) is True
