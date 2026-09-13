from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.native_driver import (
    NativeWeixinDriver,
    RiskControlError,
    extract_contact_results,
    extract_exact_forward_candidates,
    filter_recent_message_bubbles,
    find_exact_control,
    has_new_forward_confirmation,
    raise_for_risk_controls,
    resolve_friend_form_fields,
)


@dataclass
class FakeControl:
    Name: str = ""
    ControlTypeName: str = ""
    ClassName: str = ""
    AutomationId: str = ""
    IsEnabled: bool = True


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


def test_contact_results_only_include_materialized_search_items():
    section = FakeControl("联系人", "CustomControl", "mmui::XTableCell")
    alice = FakeControl(
        "Alice", "ListItemControl", "mmui::SearchContentCellView", "search_item_1"
    )
    function = FakeControl(
        "搜索网络结果", "ListItemControl", "mmui::SearchContentCellView", "search_item_function_1"
    )

    assert extract_contact_results([(section, 1), (alice, 2), (function, 2)]) == [
        ("Alice", alice)
    ]


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
