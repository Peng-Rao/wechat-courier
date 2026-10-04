from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QImage

from app.agent.contracts import ContractError, TaskOptions
from app.controllers import MessageController
from app.friend_import import load_friend_records
from app.task_models import FriendImportModel, RuntimeLogModel, TaskDisplayItem, TaskItemModel
from tests.test_v3_controllers import make_backend


def records(count=6):
    return load_friend_records([["姓名", "账号"], *[["示例", f"wxid_range_{i:04d}"] for i in range(count)]])


def test_import_and_new_valid_rows_are_not_automatically_selected(tmp_path, qapp):
    source = tmp_path / "friends.csv"
    source.write_text("姓名,账号\n示例,wxid_example\n", encoding="utf-8-sig")
    model = FriendImportModel()
    assert model.importFile(str(source))
    assert model.selectedCount == 0
    row = model.appendEmptyRecord()
    model.setCell(row, "name", "新增")
    model.setCell(row, "account", "wxid_new_entry")
    assert model.record_at(row).valid
    assert not model.record_at(row).selected
    assert not any(record.selected for record in records(101))


def test_range_replaces_selection_and_uses_inclusive_table_rows(qapp):
    model = FriendImportModel()
    data = records()
    data[2].name = ""
    model.replace_records(data)
    model.setSelected(0, True)
    assert hasattr(model, "selectRange"), "range selection is not implemented"
    assert model.selectRange(2, 5)
    assert [i + 1 for i, record in enumerate(model._records) if record.selected] == [2, 4, 5]
    model.clearSelection()
    assert model.selectedCount == 0


@pytest.mark.parametrize("start,end", [(0, 2), (4, 3), (1, 7), (1, 6), (1.5, 2), (True, 2), ("1", 2)])
def test_invalid_or_over_limit_range_keeps_selection(qapp, start, end):
    model = FriendImportModel()
    model.replace_records(records())
    model.set_selection_limit(2)
    model.setSelected(1, True)
    assert hasattr(model, "selectRange"), "range selection is not implemented"
    assert model.selectRange(start, end) is False
    assert model.selectionError
    assert [i for i, record in enumerate(model._records) if record.selected] == [1]


def test_attachment_metadata_uses_decoded_local_urls_and_opens_only_current_files(tmp_path, monkeypatch, qapp):
    controller = MessageController(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    image_path = tmp_path / "图片 100%.png"
    image = QImage(16, 8, QImage.Format_RGB32)
    image.fill(0x00AA44)
    assert image.save(str(image_path))
    document = tmp_path / "文档 #1.txt"
    document.write_text("example", encoding="utf-8")
    controller.addFile(QUrl.fromLocalFile(str(image_path)).toString())
    controller.addFile(QUrl.fromLocalFile(str(document)).toString())
    assert controller.filePaths == [str(image_path), str(document)]
    assert hasattr(controller, "attachmentPreviews"), "attachment previews are not implemented"
    previews = controller.attachmentPreviews
    assert previews[0]["isImage"]
    assert Path(QUrl(previews[0]["url"]).toLocalFile()) == image_path
    assert previews[1]["name"] == document.name
    opened = []
    monkeypatch.setattr("app.controllers.QDesktopServices.openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    assert controller.openAttachment(1)
    assert [Path(value) for value in opened] == [document]
    document.unlink()
    assert not controller.openAttachment(1)
    assert not controller.openAttachment(99)
    assert [Path(value) for value in opened] == [document]


@pytest.mark.parametrize("kind", ["message_send", "friend_add"])
def test_shared_task_clock_pauses_freezes_and_resets(tmp_path, monkeypatch, qapp, kind):
    clock = [100.0]
    monkeypatch.setattr("app.controllers.time.monotonic", lambda: clock[0])
    backend, client = make_backend(tmp_path)
    if kind == "friend_add":
        client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
        backend.friends.model.replace_records(records(2))
        backend.friends.model.setSelected(1, True)
        start = backend.task.startFriends
    else:
        backend.message.recipientsText = "Alice"
        backend.message.templateText = "hello"
        start = backend.task.startMessage
    assert start()
    payload = client.calls[-1][2]
    assert hasattr(backend.task, "elapsedSeconds"), "shared task clock is not implemented"
    clock[0] += 5
    assert backend.task.elapsedSeconds == 5
    backend.task.pause()
    assert backend.task.phase == "pausing"
    clock[0] += 2
    assert backend.task.elapsedSeconds == 7
    client.notificationReceived.emit("agent.status", {"taskId": payload["taskId"], "status": "paused"})
    assert backend.task.phase == "paused"
    clock[0] += 40
    assert backend.task.elapsedSeconds == 7
    backend.task.resume()
    clock[0] += 3
    backend.task.stop()
    clock[0] += 2
    assert backend.task.elapsedSeconds == 12
    client.notificationReceived.emit("task.finished", {"taskId": payload["taskId"], "outcome": "stopped", "done": 0, "total": 1})
    clock[0] += 100
    assert backend.task.elapsedSeconds == 12
    assert backend.task.elapsedLabel == "00:00:12"
    assert start()
    assert backend.task.elapsedSeconds == 0
    backend.shutdown()


def test_logs_display_local_time_but_keep_raw_utc(qapp):
    model = RuntimeLogModel()
    raw = "2026-10-04T07:25:33+00:00"
    model.append_event({"timestamp": raw, "detail": "search failed", "outcome": "error"})
    roles = model.roleNames()
    assert b"localTime" in roles.values(), "local timestamp role is not implemented"
    local_role = next(role for role, name in roles.items() if name == b"localTime")
    assert model.data(model.index(0), local_role) == datetime.fromisoformat(raw).astimezone().strftime("%H:%M:%S")
    assert model.data(model.index(0), model.TimestampRole) == raw
    model.append_event({"timestamp": "invalid"})
    assert model.data(model.index(1), local_role) == "--:--:--"


@pytest.mark.parametrize("offset,expected", [(-5, "20:25:33"), (9, "10:25:33"), (0, "01:25:33")])
def test_log_localization_is_not_hardcoded_to_east_eight(qapp, monkeypatch, offset, expected):
    class LocalDateTime(datetime):
        def astimezone(self, tz=None):
            return super().astimezone(tz or timezone(timedelta(hours=offset)))
    monkeypatch.setattr("app.task_models.datetime", LocalDateTime)
    model = RuntimeLogModel()
    model.append_event({"timestamp": "2026-10-04T01:25:33Z"})
    assert model.data(model.index(0), model.LocalTimeRole) == expected


def test_item_elapsed_includes_preparation_before_first_result_event(qapp):
    model = TaskItemModel()
    model.replace([TaskDisplayItem(target="Alice", item_id="one")])
    model.apply_event({"itemId": "one", "outcome": "error", "step": "account_searched", "itemElapsedMs": 15234.0,
                       "timestamp": datetime.now(timezone.utc).isoformat()})
    assert model._items[0].duration == "15.2s"


@pytest.mark.parametrize("flag", [False, True])
def test_retired_merged_forward_option_is_rejected(flag):
    with pytest.raises(ContractError, match="useForward"):
        TaskOptions.from_payload({"useForward": flag})


def test_frequency_stop_preserves_original_table_position(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.friends.model.replace_records(records(8))
    backend.friends.model.setSelected(5, True)
    assert backend.task.startFriends()
    payload = client.calls[-1][2]
    item = payload["items"][0]
    client.notificationReceived.emit("task.event", {
        "taskId": payload["taskId"], "itemId": item["itemId"], "outcome": "error", "step": "account_searched",
        "done": 1, "total": 1, "errorCode": "RISK_CONTROL", "riskKind": "friend_frequency", "detail": "添加好友过于频繁",
    })
    assert hasattr(backend.task, "riskStopItemId"), "risk stop location is not implemented"
    assert backend.task.riskStopItemId == item["itemId"]
    assert backend.task.riskStopSourceRow == 6
    assert backend.task.items._items[0].source_row == 6
    assert not backend.task.safeRetryAvailable
    client.notificationReceived.emit("task.finished", {"taskId": payload["taskId"], "outcome": "error", "done": 1, "total": 1})
    assert backend.task.riskStopSourceRow == 6
    assert "第 6 条" in backend.task.riskStopLabel
    assert backend.task.riskStopModelRow == 5
    assert backend.friends.model.removeRecord(0)
    assert backend.task.riskStopModelRow == 4
    backend.friends.model.replace_records(records(8))
    assert backend.task.riskStopModelRow == -1
    assert backend.task.riskStopSourceRow == 6
    backend.shutdown()


def test_product_identity_is_one_point_zero():
    from app._version import __version__
    from src._version import __version__ as library_version

    assert __version__ == library_version == "1.0.0"
    root = Path(__file__).resolve().parents[1]
    assert "福格微信助手" in (root / "qml/main.qml").read_text(encoding="utf-8")
    assert "!build/version_info.txt" in (root / ".gitignore").read_text(encoding="utf-8")
    assert (root / "build/version_info.txt").is_file()


def test_risk_disconnect_during_cleanup_never_resumes_remaining_rows(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.friends.model.replace_records(records(2))
    backend.friends.model.selectRange(1, 2)
    assert backend.task.startFriends()
    payload = client.calls[-1][2]
    client.notificationReceived.emit("task.event", {
        "taskId": payload["taskId"], "itemId": payload["items"][0]["itemId"],
        "step": "account_searched", "outcome": "error", "done": 1, "total": 2,
        "errorCode": "RISK_CONTROL", "riskKind": "friend_frequency",
    })
    client.connected = False
    client.connectedChanged.emit(False)
    assert not backend.task.active
    assert not backend.task._restart_scheduled
    assert backend.task.items._items[1].result == "stopped"
    client.connected = True
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.agent.applyInspection({"connected": True, "version": "4.1.13.65", "supported": True, "uiaReady": True})
    backend.task._resume_if_ready()
    assert len([call for call in client.calls if call[1] == "task.start"]) == 1
    assert backend.task.riskStopKind == "friend_frequency"
    backend.shutdown()
