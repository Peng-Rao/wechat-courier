from __future__ import annotations

import csv

import pytest
from openpyxl import Workbook

from app.friend_import import FriendImportError, FriendRecord, load_friend_records
from app.task_models import FriendImportModel


def write_csv(path, rows, encoding="utf-8-sig"):
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows(rows)


def test_csv_import_supports_bom_and_gb18030(tmp_path):
    rows = [
        ["账号", "打招呼语", "备注", "忽略列"],
        ["18896904196", "你好", "测试一", "x"],
        ["wxid_test01", "", "测试二", "y"],
    ]
    utf8_path = tmp_path / "friends-utf8.csv"
    gb_path = tmp_path / "friends-gb.csv"
    write_csv(utf8_path, rows)
    write_csv(gb_path, rows, encoding="gb18030")

    assert [row.account for row in load_friend_records(utf8_path)] == [
        "18896904196",
        "wxid_test01",
    ]
    assert [row.account for row in load_friend_records(gb_path)] == [
        "18896904196",
        "wxid_test01",
    ]


def test_xlsx_import_reads_first_sheet_and_preserves_numeric_phone(tmp_path):
    path = tmp_path / "friends.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["账号", "打招呼语", "备注"])
    sheet.append([18896904196, "你好", "手机号"])
    other = workbook.create_sheet("ignored")
    other.append(["账号"])
    other.append(["19170745267"])
    workbook.save(path)

    records = load_friend_records(path)

    assert len(records) == 1
    assert records[0].account == "18896904196"


def test_import_requires_account_header_and_rejects_unknown_formats(tmp_path):
    path = tmp_path / "missing.csv"
    write_csv(path, [["手机号", "备注"], ["18896904196", "x"]])
    with pytest.raises(FriendImportError, match="账号"):
        load_friend_records(path)

    unknown = tmp_path / "friends.txt"
    unknown.write_text("账号", encoding="utf-8")
    with pytest.raises(FriendImportError, match="CSV 或 XLSX"):
        load_friend_records(unknown)


def test_model_marks_invalid_and_duplicate_accounts_and_selects_first_20(qapp):
    rows = [["账号", "打招呼语", "备注"]]
    rows.extend([[f"wxid_valid{i:02d}", "", ""] for i in range(22)])
    rows.extend([["wxid_valid00", "duplicate", ""], ["张三", "", ""]])

    model = FriendImportModel()
    model.replace_records(load_friend_records(rows))

    assert model.count == 24
    assert model.validCount == 22
    assert model.selectedCount == 20
    assert model.record_at(22).valid is False
    assert "重复" in model.record_at(22).error
    assert model.record_at(23).valid is False
    assert "微信号或手机号" in model.record_at(23).error


def test_editing_an_account_revalidates_duplicates(qapp):
    model = FriendImportModel()
    model.replace_records(
        load_friend_records(
            [
                ["账号", "打招呼语", "备注"],
                ["wxid_first1", "", ""],
                ["wxid_second", "", ""],
            ]
        )
    )

    assert model.setCell(1, "account", "wxid_first1")
    assert model.record_at(1).valid is False
    assert "重复" in model.record_at(1).error

    assert model.setCell(1, "account", "19170745267")
    assert model.record_at(1).valid is True


def test_selected_payload_applies_row_then_global_then_preserve_defaults(qapp):
    model = FriendImportModel()
    model.replace_records(
        load_friend_records(
            [
                ["账号", "打招呼语", "备注"],
                ["wxid_first1", "行内问候", "行内备注"],
                ["wxid_second", "", ""],
            ]
        )
    )

    payload = model.selected_payload("全局问候", "全局备注")
    assert payload[0]["greeting"] == "行内问候"
    assert payload[0]["remark"] == "行内备注"
    assert payload[1]["greeting"] == "全局问候"
    assert payload[1]["remark"] == "全局备注"

    payload = model.selected_payload("", "")
    assert payload[1]["greeting"] is None
    assert payload[1]["remark"] == ""


def test_manual_rows_are_blank_invalid_and_have_unique_ids(qapp):
    model = FriendImportModel()

    first_row = model.appendEmptyRecord()
    second_row = model.appendEmptyRecord()

    assert (first_row, second_row) == (0, 1)
    first = model.record_at(first_row)
    second = model.record_at(second_row)
    assert first.item_id.startswith("manual-")
    assert second.item_id.startswith("manual-")
    assert first.item_id != second.item_id
    assert (first.account, first.greeting, first.remark) == ("", "", "")
    assert first.valid is False
    assert first.error == "账号不能为空"
    assert first.selected is False
    assert (model.count, model.validCount, model.selectedCount) == (2, 0, 0)


def test_manual_row_auto_selects_only_when_it_first_becomes_valid(qapp):
    model = FriendImportModel()
    row = model.appendEmptyRecord()

    assert model.setCell(row, "account", "张三")
    assert model.record_at(row).selected is False

    assert model.setCell(row, "account", "wxid_manual1")
    assert model.record_at(row).valid is True
    assert model.record_at(row).selected is True

    assert model.setSelected(row, False)
    assert model.setCell(row, "account", "wxid_manual2")
    assert model.record_at(row).selected is False


def test_manual_row_stays_unselected_when_twenty_rows_are_already_selected(qapp):
    rows = [["账号", "打招呼语", "备注"]]
    rows.extend([[f"wxid_limit{i:02d}", "", ""] for i in range(20)])
    model = FriendImportModel()
    model.replace_records(load_friend_records(rows))

    row = model.appendEmptyRecord()
    assert model.setCell(row, "account", "wxid_overlimit")

    assert model.record_at(row).valid is True
    assert model.record_at(row).selected is False
    assert model.selectedCount == 20


def test_removing_a_row_revalidates_the_remaining_duplicate(qapp):
    model = FriendImportModel()
    model.replace_records(
        load_friend_records(
            [
                ["账号", "打招呼语", "备注"],
                ["wxid_first1", "", ""],
                ["wxid_second", "", ""],
            ]
        )
    )
    assert model.setCell(1, "account", "wxid_first1")
    assert model.record_at(1).valid is False

    assert model.removeRecord(0) is True

    assert model.count == 1
    assert model.record_at(0).account == "wxid_first1"
    assert model.record_at(0).valid is True
    assert model.record_at(0).error == ""
    assert model.record_at(0).selected is False
    assert model.removeRecord(-1) is False
    assert model.removeRecord(1) is False


def test_replacing_records_clears_pending_manual_auto_selection(qapp):
    model = FriendImportModel()
    row = model.appendEmptyRecord()
    manual_id = model.record_at(row).item_id
    model.replace_records(
        [
            FriendRecord(
                item_id=manual_id,
                account="",
                valid=False,
                error="账号不能为空",
            )
        ]
    )

    assert model.setCell(0, "account", "wxid_imported")

    assert model.record_at(0).valid is True
    assert model.record_at(0).selected is False
