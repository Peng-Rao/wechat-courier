from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_profile_for_verified_weixin_build_is_exact():
    from app.agent.profile import get_weixin_profile

    profile = get_weixin_profile("4.1.13.65")

    assert profile.gate_rva == 0x0AE2B0C8
    assert profile.main_root_class == "mmui::MainWindow"
    assert profile.search_edit_class == "mmui::XValidatorTextEdit"
    assert profile.search_popup_class == "mmui::XPopover"
    assert profile.search_list_automation_id == "search_list"
    assert profile.chat_input_automation_id == "chat_input_field"
    assert profile.chat_input_class == "mmui::ChatInputField"
    assert profile.add_friend_root_class == "mmui::AddFriendWindow"
    assert profile.verify_friend_root_class == "mmui::VerifyFriendWindow"


def test_unverified_weixin_build_is_rejected():
    from app.agent.profile import UnsupportedWeixinVersion, get_weixin_profile

    with pytest.raises(UnsupportedWeixinVersion, match="4.1.14.1"):
        get_weixin_profile("4.1.14.1")


def test_task_event_serializes_the_stable_rpc_shape():
    from app.agent.contracts import TaskEvent

    timestamp = datetime(2026, 9, 13, 8, 30, tzinfo=timezone.utc)
    event = TaskEvent(
        task_id="task-1",
        item_id="item-2",
        step="target_verified",
        outcome="working",
        detail="目标校验通过",
        done=1,
        total=3,
        timestamp=timestamp,
    )

    assert event.to_payload() == {
        "taskId": "task-1",
        "itemId": "item-2",
        "step": "target_verified",
        "outcome": "working",
        "detail": "目标校验通过",
        "done": 1,
        "total": 3,
        "timestamp": "2026-09-13T08:30:00+00:00",
    }


def test_task_request_rejects_an_unknown_kind():
    from app.agent.contracts import ContractError, TaskRequest

    with pytest.raises(ContractError, match="kind"):
        TaskRequest.from_payload({"taskId": "t", "kind": "unknown", "items": []})


def test_friend_request_item_keeps_optional_fields_nullable():
    from app.agent.contracts import TaskRequest

    request = TaskRequest.from_payload(
        {
            "taskId": "friends-1",
            "kind": "friend_add",
            "items": [
                {
                    "itemId": "row-1",
                    "account": "18896904196",
                    "greeting": None,
                    "remark": "",
                }
            ],
            "options": {"intervalMin": 15, "intervalMax": 30},
        }
    )

    assert request.items[0].account == "18896904196"
    assert request.items[0].greeting is None
    assert request.items[0].remark == ""
    assert request.options.interval_min == 15
    assert request.options.interval_max == 30
