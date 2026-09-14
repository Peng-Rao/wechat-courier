from __future__ import annotations

from app.friend_import import load_friend_records
from app.task_models import FriendImportModel, TaskDisplayItem, TaskItemModel


def _event(
    step: str, outcome: str, timestamp: str, item_id: str = "item-1"
) -> dict:
    return {
        "itemId": item_id,
        "step": step,
        "outcome": outcome,
        "detail": step,
        "timestamp": timestamp,
    }


def test_task_item_stays_working_until_terminal_step_and_records_duration(qapp):
    model = TaskItemModel()
    model.replace([TaskDisplayItem(target="Alice", item_id="item-1")])

    model.apply_event(
        _event("window_bound", "success", "2026-09-14T00:00:00+00:00")
    )

    item = model._items[0]
    assert item.result == "working"
    assert item.duration == "--"

    model.apply_event(
        _event("send_verified", "success", "2026-09-14T00:00:01.25+00:00")
    )

    assert item.result == "success"
    assert item.duration == "1.2s"


def test_friend_import_status_stays_working_until_submit_is_verified(qapp):
    model = FriendImportModel()
    model.replace_records(
        load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", "测试"]]
        )
    )

    model.apply_event(
        _event(
            "window_bound",
            "success",
            "2026-09-14T00:00:00+00:00",
            "row-2",
        )
    )
    assert model.record_at(0).status == "working"

    model.apply_event(
        _event(
            "submit_verified",
            "success",
            "2026-09-14T00:00:01+00:00",
            "row-2",
        )
    )
    assert model.record_at(0).status == "success"


def test_friend_preflight_completed_is_a_terminal_success(qapp):
    model = FriendImportModel()
    model.replace_records(
        load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", "测试"]]
        )
    )

    model.apply_event(
        _event(
            "preflight_completed",
            "success",
            "2026-09-14T00:00:01+00:00",
            "row-2",
        )
    )

    assert model.record_at(0).status == "success"
