from __future__ import annotations

import importlib

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy


FIELDS = ("nick_name", "remark", "phone", "username", "alias", "description")
HEADERS = ("\u6635\u79f0", "\u5907\u6ce8", "\u624b\u673a\u53f7", "\u5fae\u4fe1 ID", "\u5fae\u4fe1\u53f7", "\u63cf\u8ff0")


def _module(name):
    try:
        return importlib.import_module(f"app.contacts.{name}")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Contact {name} implementation is missing: {exc}")


def test_normalize_preserves_canonical_text_without_mining_remarks():
    data = _module("data")
    row = dict(zip(FIELDS, (" \u6635\u79f0\U0001f600 ", "phone: 13812345678", "0", "0001", "", "=SUM(1,2)")))
    row.update(local_type=1, is_del=0, verify_flag=0)
    result = data.normalize_contact(row)
    assert data.CONTACT_FIELDS == FIELDS
    assert data.CONTACT_HEADERS == HEADERS
    assert result == {**{key: row[key] for key in FIELDS}, "category": "friend"}
    assert data.normalize_contact({"remark": "13812345678"})["phone"] == ""
    assert data.normalize_contact({"phone": 0, "alias": None})["phone"] == "0"
    assert data.normalize_contact({"phone": 0, "alias": None})["alias"] == ""


@pytest.mark.parametrize("metadata, category", [
    ({"local_type": 1}, "friend"),
    ({"local_type": "1", "is_del": "0", "verify_flag": "0"}, "friend"),
    ({"local_type": 1, "is_del": 1}, "other"),
    ({"local_type": 1, "is_deleted": True}, "other"),
    ({"local_type": 1, "is_delete": 1}, "other"),
    ({"local_type": 1, "delete_flag": "unknown"}, "other"),
    ({"local_type": 1, "verify_flag": 8}, "official"),
    ({"local_type": 1, "verification_flag": 24}, "official"),
    ({"local_type": 1, "verify_flag": "unknown"}, "other"),
    ({"local_type": 0}, "cache"),
    ({"local_type": 3}, "cache"),
    ({"local_type": 2}, "other"),
    ({"local_type": 99}, "other"),
    ({"local_type": "unknown", "type": 3}, "other"),
    ({"type": 3, "is_del": 0}, "friend"),
    ({"type": 0}, "cache"),
    ({"type": 999}, "other"),
    ({}, "other"),
    ({"username": "123@chatroom", "local_type": 1}, "group"),
    ({"username": "gh_12345", "local_type": 1}, "official"),
    ({"username": "filehelper", "local_type": 1}, "system"),
    ({"username": "weixin", "local_type": 1}, "system"),
    ({"username": "x@stranger", "local_type": 1}, "cache"),
    ({"username": "wxid_gh_filehelper_chatroom", "local_type": 1}, "friend"),
])
def test_category_uses_recognized_metadata_and_structural_ids(metadata, category):
    row = {"nick_name": "\u516c\u4f17\u53f7 filehelper \u7fa4\u804a", "remark": "gh_ official system cache"}
    row.update(metadata)
    assert _module("data").normalize_contact(row)["category"] == category


def test_model_is_readonly_six_columns_with_qml_text_role(qapp):
    model = _module("models").ContactTableModel()
    model.replace_records([{"nick_name": "\u4e2d\u6587", "phone": "00123", "local_type": 1}])
    assert model.rowCount() == 1
    assert model.columnCount() == 6
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0
    assert [model.headerData(i, Qt.Horizontal) for i in range(6)] == list(HEADERS)
    header_role = next((key for key, name in model.roleNames().items() if name == b"display"), None)
    assert header_role == Qt.DisplayRole
    assert model.headerData(0, Qt.Horizontal, header_role) == "\u6635\u79f0"
    role = next(key for key, name in model.roleNames().items() if name == b"cellText")
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "\u4e2d\u6587"
    assert model.data(model.index(0, 2), role) == "00123"
    assert model.text(0, 2) == "00123"
    assert model.text(-1, 0) == ""
    assert model.text(0, 6) == ""
    assert model.data(QModelIndex()) is None
    assert model.data(model.index(0, 0), Qt.DecorationRole) is None
    assert not (model.flags(model.index(0, 0)) & Qt.ItemIsEditable)
    assert model.setData(model.index(0, 0), "changed") is False


@pytest.mark.parametrize("field", FIELDS)
def test_keyword_searches_every_text_column_using_unicode_casefold(qapp, field):
    model = _module("models").ContactTableModel()
    model.replace_records([{field: "Stra\u00dfe \u4e2d\u6587", "local_type": 1}, {"local_type": 1}])
    model.set_keyword("STRASSE")
    assert model.visibleCount == 1
    model.set_keyword("\u4e2d\u6587")
    assert model.visibleCount == 1
    model.set_keyword("missing")
    assert model.visibleCount == 0
    model.set_keyword("")
    assert model.visibleCount == 2


def test_model_filters_specials_and_notifies_counts(qapp):
    model = _module("models").ContactTableModel()
    spy = QSignalSpy(model.countsChanged)
    model.replace_records([
        {"nick_name": "Alice", "local_type": 1},
        {"nick_name": "Alice group", "username": "1@chatroom"},
        {"nick_name": "Alice ambiguous"},
    ])
    assert (model.totalCount, model.visibleCount) == (3, 1)
    model.set_include_special(True)
    assert model.visibleCount == 3
    model.set_keyword("group")
    assert (model.totalCount, model.visibleCount) == (3, 1)
    model.set_include_special(False)
    assert model.visibleCount == 0
    model.clear()
    assert (model.totalCount, model.visibleCount) == (0, 0)
    assert spy.count() >= 5
    for name in ("totalCount", "visibleCount"):
        prop = model.metaObject().property(model.metaObject().indexOfProperty(name))
        assert prop.hasNotifySignal()
        assert prop.notifySignal().name() == b"countsChanged"


def test_snapshot_and_replace_freeze_records_and_keep_visible_sort(qapp):
    model = _module("models").ContactTableModel()
    records = [
        {"nick_name": "same", "phone": "2", "username": "first", "local_type": 1},
        {"nick_name": "same", "phone": "10", "username": "second", "local_type": 1},
        {"nick_name": "same", "phone": "001", "username": "third", "local_type": 1},
    ]
    model.replace_records(records)
    records[0]["phone"] = "mutated"
    model.sort(2)
    frozen = model.snapshot()
    assert [row["phone"] for row in frozen] == ["001", "10", "2"]
    model.sort(2, Qt.DescendingOrder)
    assert [row["phone"] for row in model.snapshot()] == ["2", "10", "001"]
    model.sort(0)
    assert [row["username"] for row in model.snapshot()] == ["first", "second", "third"]
    model.set_keyword("second")
    assert [row["username"] for row in model.snapshot()] == ["second"]
    frozen[0]["phone"] = "outside"
    model.clear()
    assert frozen[1]["phone"] == "10"


def test_model_accepts_reader_normalized_records(qapp):
    data = _module("data")
    model = _module("models").ContactTableModel()
    model.replace_records([data.normalize_contact({"username": "wxid_a", "local_type": 1})])
    assert model.visibleCount == 1
    assert model.snapshot()[0]["category"] == "friend"


def test_model_accepts_explicit_reader_category_with_missing_empty_fields(qapp):
    model = _module("models").ContactTableModel()
    model.replace_records([{"username": "wxid_a", "category": "friend"}])
    assert model.snapshot() == [{"nick_name": "", "remark": "", "phone": "", "username": "wxid_a", "alias": "", "description": "", "category": "friend"}]
    model.replace_records([{"username": "wxid_a", "category": "friend", "local_type": 99}])
    assert model.visibleCount == 0


def test_oversized_unrecognized_metadata_is_other_not_a_conversion_error():
    result = _module("data").normalize_contact({"local_type": "9" * 5000})
    assert result["category"] == "other"


def test_mutating_a_snapshot_does_not_mutate_the_current_table(qapp):
    model = _module("models").ContactTableModel()
    model.replace_records([{"nick_name": "original", "local_type": 1}])
    snapshot = model.snapshot()
    snapshot[0]["nick_name"] = "mutated"
    snapshot.clear()
    assert model.text(0, 0) == "original"
    assert model.visibleCount == 1
