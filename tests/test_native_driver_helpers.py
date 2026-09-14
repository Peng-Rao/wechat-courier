from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.native_driver import (
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
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: hwnd == 222)
    monkeypatch.setattr(
        "win32process.GetWindowThreadProcessId", lambda hwnd: (0, 123)
    )

    driver._click_bounds(control)

    assert clicks == [(550, 425)]


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
    resolved = iter((stale, fresh))
    driver._resolve_search_candidate = lambda _candidate: next(resolved)
    driver._uia = type(
        "Uia", (), {"Click": staticmethod(lambda x, y: clicked.append((x, y)))}
    )()
    driver.composer_ready = lambda: bool(clicked)
    driver.current_chat_title = lambda: "Alice" if clicked else ""

    driver.select_search_result(candidate)

    assert clicked == [(130, 120)]


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
        raise RuntimeError("accessibility gate write-back failed")

    driver._ensure_session = ensure
    monkeypatch.setattr(
        "src.core.win32.bring_window_to_front",
        lambda _hwnd: pytest.fail("activation must not run"),
    )

    with pytest.raises(RuntimeError, match="gate write-back"):
        driver.bind_window()

    assert attempts == [1]


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
