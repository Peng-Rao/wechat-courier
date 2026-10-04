from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from app.controllers import FriendController
from app.friend_import import load_friend_records
from app.task_models import FriendImportModel


def friend_rows(count):
    return [["姓名", "账号"], *[["示例学生", f"wxid_batch{i:04d}"] for i in range(count)]]


def test_default_import_is_unselected_and_range_limit_rejects_next_row(qapp):
    model = FriendImportModel()
    model.replace_records(load_friend_records(friend_rows(101)))
    assert model.selectedCount == 0
    assert model.selectRange(1, 100)
    assert model.selectedCount == 100
    assert model.setSelected(100, True) is False
    assert len(model.selected_payload()) == 100
    assert model.setSelected(0, True) is True


@pytest.mark.parametrize("limit", [1, 100, 1000])
def test_import_and_select_first_valid_obey_configured_limit(tmp_path, qapp, limit):
    controller = FriendController(QSettings(str(tmp_path / "friends.ini"), QSettings.IniFormat))
    controller.batchLimit = limit
    source = tmp_path / "friends.csv"
    source.write_text("姓名,账号\n" + "\n".join(
        f"示例学生,wxid_batch{i:04d}" for i in range(1001)), encoding="utf-8-sig")
    assert controller.importFile(str(source))
    assert controller.model.selectedCount == 0
    assert controller.model.selectRange(1, limit)
    assert controller.model.selectedCount == limit
    assert controller.model.setSelected(limit, True) is False
    controller.model.setSelected(0, False)
    controller.model.selectFirstValid()
    assert controller.model.selectedCount == limit
    assert len(controller.build_items()) == limit


def test_reducing_limit_preserves_first_selected_rows_without_deleting_data(tmp_path, qapp):
    controller = FriendController(QSettings(str(tmp_path / "friends.ini"), QSettings.IniFormat))
    model = controller.model
    model.replace_records(load_friend_records(friend_rows(8)))
    assert model.selectRange(1, 8)
    model.setSelected(0, False)
    model.setSelected(2, False)
    changes = []
    controller.batchLimitChanged.connect(changes.append)
    controller.batchLimit = 3
    assert [i for i in range(model.count) if model.record_at(i).selected] == [1, 3, 4]
    assert model.count == model.validCount == 8
    assert changes == [3]
    controller.batchLimit = 6
    assert [i for i in range(model.count) if model.record_at(i).selected] == [1, 3, 4]
    model.selectFirstValid()
    assert [i for i in range(model.count) if model.record_at(i).selected] == [0, 1, 2, 3, 4, 5]


def test_invalid_and_duplicate_rows_do_not_consume_selection_limit(tmp_path, qapp):
    controller = FriendController(QSettings(str(tmp_path / "friends.ini"), QSettings.IniFormat))
    controller.batchLimit = 2
    rows = [["姓名", "账号"], ["", "wxid_invalid"], ["示例学生", "wxid_first"],
            ["示例学生", "wxid_first"], ["示例学生", "wxid_second"], ["示例学生", "wxid_third"]]
    controller.model.replace_records(load_friend_records(rows))
    controller.model.selectFirstValid()
    assert [i for i in range(5) if controller.model.record_at(i).selected] == [1, 3]
    assert controller.model.setSelected(4, True) is False


def test_new_valid_manual_row_obeys_limit_without_auto_expanding_selection(tmp_path, qapp):
    controller = FriendController(QSettings(str(tmp_path / "friends.ini"), QSettings.IniFormat))
    controller.batchLimit = 1
    controller.model.replace_records(load_friend_records(friend_rows(1)))
    assert controller.model.selectRange(1, 1)
    row = controller.model.appendEmptyRecord()
    controller.model.setCell(row, "name", "示例学生")
    controller.model.setCell(row, "account", "wxid_manual")
    assert controller.model.record_at(row).valid
    assert not controller.model.record_at(row).selected
    controller.batchLimit = 2
    assert controller.model.selectedCount == 1
    controller.model.selectFirstValid()
    assert controller.model.selectedCount == 2


@pytest.mark.parametrize("stored, expected", [
    (None, 100), (0, 1), (-20, 1), (1001, 1000), (250, 250), ("250", 250),
    ("broken", 100), (True, 100), (2.5, 100),
])
def test_settings_normalization_and_restart_restore_limit(tmp_path, qapp, stored, expected):
    path = str(tmp_path / "friends.ini")
    settings = QSettings(path, QSettings.IniFormat)
    if stored is not None:
        settings.setValue("friends/batchLimit", stored)
    controller = FriendController(settings)
    assert controller.batchLimit == expected
    controller.model.replace_records(load_friend_records(friend_rows(1001)))
    controller.model.selectFirstValid()
    assert controller.model.selectedCount == expected
    controller.batchLimit = 137
    settings.sync()
    restored = FriendController(QSettings(path, QSettings.IniFormat))
    assert restored.batchLimit == 137
    restored.model.replace_records(load_friend_records(friend_rows(150)))
    restored.model.selectFirstValid()
    assert restored.model.selectedCount == 137


def test_unchanged_setting_does_not_emit_and_setter_clamps(tmp_path, qapp):
    settings = QSettings(str(tmp_path / "friends.ini"), QSettings.IniFormat)
    controller = FriendController(settings)
    changed = []
    controller.batchLimitChanged.connect(changed.append)
    controller.batchLimit = 100
    controller.batchLimit = -10
    controller.batchLimit = 2000
    assert changed == [1, 1000]
    assert settings.value("friends/batchLimit", type=int) == 1000
