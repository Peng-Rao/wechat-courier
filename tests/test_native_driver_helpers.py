from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.native_driver import (
    RiskControlError,
    extract_contact_results,
    find_exact_control,
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


def test_friend_form_fields_are_resolved_by_exact_accessible_names():
    greeting = FakeControl("发送添加朋友申请", "EditControl")
    remark = FakeControl("修改备注", "EditControl")
    fields = resolve_friend_form_fields([(greeting, 3), (remark, 3)])
    assert fields == (greeting, remark)


def test_risk_controls_stop_the_workflow():
    warning = FakeControl("操作频繁，请稍后再试", "TextControl")
    with pytest.raises(RiskControlError, match="操作频繁"):
        raise_for_risk_controls([(warning, 2)])
