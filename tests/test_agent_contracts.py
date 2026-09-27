from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_profile_for_verified_weixin_build_is_exact():
    from app.agent.profile import get_weixin_profile

    profile = get_weixin_profile("4.1.13.65")

    assert profile.gate_rva == 0x0AE2B0C8
    assert profile.main_root_class == "mmui::MainWindow"
    assert profile.search_edit_class == "mmui::XValidatorTextEdit"
    assert profile.chat_message_list_automation_id == "chat_message_list"
    assert "search_edit" in profile.forward_search_automation_ids
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
        "attempt": 1,
        "maxAttempts": 1,
        "retryLevel": "none",
        "retryInMs": 0,
        "recoverable": False,
        "destructiveBoundaryCrossed": False,
        "wechatResponsive": True,
        "errorCode": "",
    }


def test_friend_contract_includes_the_preflight_terminal_step():
    from app.agent.contracts import FRIEND_STEPS

    assert "preflight_completed" in FRIEND_STEPS


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


def test_friend_request_requires_literal_submission_intent_in_options():
    from app.agent.contracts import TaskRequest

    request = TaskRequest.from_payload(
        {
            "taskId": "friends-submit-1",
            "kind": "friend_add",
            "items": [{"itemId": "row-1", "account": "18896904196"}],
            "options": {"submitFriendRequest": True},
        }
    )

    assert request.options.submit_friend_request is True


def test_friend_request_rejects_string_submission_intent():
    from app.agent.contracts import ContractError, TaskRequest

    with pytest.raises(ContractError, match="submitFriendRequest"):
        TaskRequest.from_payload(
            {
                "taskId": "friends-submit-2",
                "kind": "friend_add",
                "items": [{"itemId": "row-1", "account": "18896904196"}],
                "options": {"submitFriendRequest": "true"},
            }
        )


@pytest.mark.parametrize("limit, count", [(1, 1), (100, 100), (1000, 1000)])
def test_friend_batch_contract_accepts_configured_limit(limit, count):
    from app.agent.contracts import TaskRequest

    request = TaskRequest.from_payload({
        "taskId": "batch", "kind": "friend_add",
        "items": [{"itemId": f"row-{i}", "account": f"wxid_batch{i:04d}"} for i in range(count)],
        "options": {"friendBatchLimit": limit},
    })
    assert request.options.friend_batch_limit == limit
    assert len(request.items) == count


@pytest.mark.parametrize("limit", [0, -1, 1001, True, False, 1.5, 100.0, "100", None])
def test_friend_batch_contract_rejects_invalid_rpc_limit(limit):
    from app.agent.contracts import ContractError, TaskRequest

    with pytest.raises(ContractError, match="friendBatchLimit"):
        TaskRequest.from_payload({
            "taskId": "batch", "kind": "friend_add",
            "items": [{"itemId": "one", "account": "wxid_batch0001"}],
            "options": {"friendBatchLimit": limit},
        })


@pytest.mark.parametrize("limit, count", [(1, 2), (100, 101), (1000, 1001)])
def test_friend_batch_contract_rejects_over_limit_items(limit, count):
    from app.agent.contracts import ContractError, TaskRequest

    with pytest.raises(ContractError, match="friendBatchLimit"):
        TaskRequest.from_payload({
            "taskId": "batch", "kind": "friend_add",
            "items": [{"itemId": f"row-{i}", "account": f"wxid_batch{i:04d}"} for i in range(count)],
            "options": {"friendBatchLimit": limit},
        })


def test_legacy_friend_rpc_uses_default_one_hundred_limit():
    from app.agent.contracts import ContractError, TaskRequest

    payload = {"taskId": "batch", "kind": "friend_add", "items": [
        {"itemId": f"row-{i}", "account": f"wxid_batch{i:04d}"} for i in range(100)]}
    assert len(TaskRequest.from_payload(payload).items) == 100
    payload["items"].append({"itemId": "extra", "account": "wxid_extra"})
    with pytest.raises(ContractError, match="friendBatchLimit"):
        TaskRequest.from_payload(payload)
