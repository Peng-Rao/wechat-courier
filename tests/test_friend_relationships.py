from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from app.controllers import FriendController
from app.friend_import import FriendImportError, load_friend_records
from app.task_models import FriendImportModel


def model_with_names(*names):
    model = FriendImportModel()
    model.replace_records(load_friend_records(
        [["姓名", "账号"], *[[name, f"wxid_person{i}"] for i, name in enumerate(names)]]
    ))
    model.selectFirstValid()
    return model


def test_required_name_header_rejects_old_template():
    with pytest.raises(FriendImportError, match="姓名"):
        load_friend_records([["账号"], ["wxid_person1"]])


def test_duplicate_headers_are_rejected():
    with pytest.raises(FriendImportError, match="重复.*姓名"):
        load_friend_records([["姓名", "账号", "姓名"], ["张三", "wxid_person1", "李四"]])


def test_import_suffix_and_none_have_distinct_global_behavior(qapp):
    model = model_with_names("示例学生妈妈", "李明", "王五")
    assert model.record_at(0).name == "示例学生"
    assert model.setCell(2, "relationship", "无")
    model.set_defaults("{称呼}，你好！{姓名}/{关系}", "姐姐")
    assert [row["remark"] for row in model.selected_payload()] == ["示例学生妈妈", "李明姐姐", "王五"]
    assert model.selected_payload()[2]["greeting"] == "王五，你好！王五/"
    model.set_defaults("{称呼}", "")
    assert [row["remark"] for row in model.selected_payload()] == ["示例学生妈妈", "李明", "王五"]


def test_manual_relationship_wins_over_suffix_and_supports_custom(qapp):
    model = model_with_names("示例学生妈妈")
    model.setCell(0, "relationship", "班主任")
    model.setCell(0, "name", "李明爸爸")
    assert model.record_at(0).name == "李明"
    assert model.selected_payload()[0]["remark"] == "李明班主任"
    model.setCell(0, "relationship", "使用全局")
    model.set_defaults("", "哥哥")
    assert model.selected_payload()[0]["remark"] == "李明哥哥"


@pytest.mark.parametrize("template", ["{未知}", "{姓名", "姓名}", "{姓名!r}", "{姓名:>10}", "{姓名.__class__}", "{}"])
def test_bad_templates_block_only_affected_rows(qapp, template):
    model = model_with_names("张三", "李四")
    model.setCell(1, "greeting", "{称呼}你好")
    model.set_defaults(template, "妈妈")
    assert not model.record_at(0).valid
    assert "打招呼语" in model.record_at(0).error
    assert model.record_at(1).valid
    assert [r["account"] for r in model.selected_payload()] == ["wxid_person1"]


def test_preview_and_frozen_payload_share_rendering(qapp):
    model = model_with_names("张三")
    model.set_defaults("{称呼}您好", "奶奶")
    preview = model.preview(0)
    payload = model.selected_payload()
    assert preview["greeting"] == payload[0]["greeting"] == "张三奶奶您好"
    assert preview["remark"] == payload[0]["remark"] == "张三奶奶"
    model.setCell(0, "relationship", "无")
    assert model.preview(0)["remark"] == "张三"
    assert payload[0]["remark"] == "张三奶奶"
    model.set_defaults("", "")
    assert model.selected_payload()[0]["greeting"] is None


def test_invalid_rows_include_source_line_and_remain_editable(qapp):
    model = model_with_names("妈妈", "李四")
    assert not model.record_at(0).valid
    assert "第 2 行" in model.record_at(0).error
    assert "姓名" in model.record_at(0).error
    model.setCell(0, "name", "张三")
    assert model.record_at(0).valid
    model.setCell(1, "account", "wxid_person0")
    assert "第 3 行" in model.record_at(1).error
    assert "重复" in model.record_at(1).error
    model.removeRecord(0)
    assert model.record_at(0).valid


def test_global_relationship_persists_without_replacing_existing_greeting(tmp_path, qapp):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("friends/defaultGreeting", "旧的自定义问候")
    settings.setValue("friends/defaultRemark", "旧备注不能再用")
    controller = FriendController(settings)
    assert controller.defaultRelationship == "妈妈"
    assert controller.defaultGreeting == "旧的自定义问候"
    controller.defaultRelationship = "无"
    reloaded = FriendController(settings)
    reloaded.model.replace_records(load_friend_records([["姓名", "账号"], ["张三", "wxid_person1"]]))
    assert reloaded.model.selectRange(1, 1)
    assert reloaded.build_items()[0]["remark"] == "张三"
    assert reloaded.build_items()[0]["greeting"] == "旧的自定义问候"


def test_import_warning_and_transactional_failure(tmp_path, qapp):
    model = model_with_names("已有姓名")
    csv = tmp_path / "friends.csv"
    csv.write_text('姓名,账号,备注\n张三,wxid_person1,不应使用\n', encoding="utf-8-sig")
    assert model.importFile(str(csv))
    assert "备注" in model.importWarning and "忽略" in model.importWarning
    assert model.preview(0)["remark"] == "张三妈妈"
    csv.write_text('姓名,账号\n"损坏,wxid_person2', encoding="utf-8-sig")
    assert not model.importFile(str(csv))
    assert model.record_at(0).name == "张三"
    assert model.importError


def test_download_template_contains_required_columns(tmp_path, qapp):
    controller = FriendController(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    output = tmp_path / "template.xlsx"
    assert controller.createTemplate(str(output))
    rows = load_friend_records(output)
    assert rows and all(r.valid and r.name for r in rows)


@pytest.mark.parametrize("relation", ["爸爸", "妈妈", "哥哥", "姐姐", "弟弟", "妹妹", "爷爷", "奶奶", "外公", "外婆", "姥爷", "姥姥", "伯伯", "伯母", "叔叔", "婶婶", "姑姑", "姑父", "舅舅", "舅妈", "姨妈", "姨父", "阿姨"])
def test_each_builtin_suffix_is_split_once_and_never_accumulates(qapp, relation):
    model = model_with_names("示例学生" + relation)
    assert model.record_at(0).name == "示例学生"
    assert model.record_at(0).relationship == relation
    for _ in range(3):
        model.set_defaults("{姓名}-{关系}-{称呼}", "爸爸")
        assert model.preview(0)["remark"] == "示例学生" + relation
    assert model.setCell(0, "relationship", "无")
    assert model.preview(0)["remark"] == "示例学生"


def test_explicit_global_manual_choice_survives_later_name_suffix(qapp):
    model = model_with_names("示例学生妈妈")
    model.setCell(0, "relationship", "使用全局")
    model.setCell(0, "name", "另一学生姐姐")
    model.set_defaults("{称呼}", "奶奶")
    assert model.preview(0)["remark"] == "另一学生奶奶"


def test_manual_name_is_required_and_valid_row_remains_unselected(qapp):
    model = FriendImportModel()
    row = model.appendEmptyRecord()
    model.setCell(row, "account", "wxid_valid1")
    assert not model.record_at(row).valid
    assert not model.record_at(row).selected
    model.setCell(row, "name", "示例学生")
    assert not model.record_at(row).selected
    assert not model.setCell(row, "remark", "不可手改")
    assert model.preview(row)["remark"] == "示例学生妈妈"


def test_csv_preserves_quoted_multiline_greeting(tmp_path):
    csv = tmp_path / "multiline.csv"
    csv.write_text('姓名,账号,打招呼语\n示例学生,wxid_person1,"{称呼}您好，\n我是老师"\n', encoding="utf-8-sig", newline="\n")
    assert load_friend_records(csv)[0].greeting == "{称呼}您好，\n我是老师"


@pytest.mark.parametrize("contents", [b"not-an-xlsx", b"PK\x03\x04broken"])
def test_damaged_excel_preserves_existing_table(tmp_path, qapp, contents):
    model = model_with_names("已有学生")
    path = tmp_path / "bad.xlsx"
    path.write_bytes(contents)
    assert not model.importFile(str(path))
    assert "XLSX" in model.importError
    assert model.record_at(0).name == "已有学生"


def test_file_urls_with_spaces_work_for_import_and_template(tmp_path, qapp):
    from PySide6.QtCore import QUrl
    controller = FriendController(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    path = tmp_path / "示例 名单.xlsx"
    url = QUrl.fromLocalFile(str(path)).toString(QUrl.FullyEncoded)
    assert controller.createTemplate(url)
    assert path.exists()
    assert controller.importFile(url)
    assert controller.model.validCount == 2


def test_range_selection_uses_actual_global_template_validation(tmp_path, qapp):
    model = FriendImportModel()
    model.set_defaults("{未知}", "妈妈")
    path = tmp_path / "mixed.csv"
    lines = ["姓名,账号,打招呼语"]
    lines += [f"示例学生,wxid_person{i}," for i in range(20)]
    lines += ["有效学生,wxid_lastperson,{称呼}您好"]
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    assert model.importFile(str(path))
    assert model.selectedCount == 0
    assert model.selectRange(1, 21)
    assert model.validCount == model.selectedCount == 1
    assert model.selected_payload()[0]["account"] == "wxid_lastperson"


def test_appending_blank_row_uses_correct_line_number_and_current_template(qapp):
    model = model_with_names("示例学生", "另一学生")
    model.set_defaults("{未知}", "妈妈")
    row = model.appendEmptyRecord()
    assert "第 3 行" in model.preview(row)["error"]
    assert "打招呼语" in model.preview(row)["error"]


def test_task_request_contains_rendered_snapshot_not_live_template(tmp_path, qapp):
    from tests.test_v3_controllers import make_backend
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.friends.model.replace_records(load_friend_records(
        [["姓名", "账号"], ["示例学生", "mock_only_001"]]))
    backend.friends.defaultGreeting = "{称呼}您好"
    backend.friends.defaultRelationship = "姐姐"
    assert backend.friends.model.selectRange(1, 1)
    assert backend.task.startFriends()
    payload = next(params for _, method, params in reversed(client.calls) if method == "task.start")
    assert payload["items"][0]["greeting"] == "示例学生姐姐您好"
    assert payload["items"][0]["remark"] == "示例学生姐姐"
    backend.friends.defaultRelationship = "无"
    backend.friends.defaultGreeting = "后来修改"
    assert payload["items"][0]["greeting"] == "示例学生姐姐您好"
    assert payload["items"][0]["remark"] == "示例学生姐姐"


def test_suffix_placeholder_and_legacy_alias_share_custom_and_empty_values(qapp):
    model = model_with_names("示例学生")
    model.setCell(0, "relationship", "家长代表")
    model.set_defaults("{姓名}/{后缀}/{关系}/{称呼}", "妈妈")
    assert model.preview(0)["greeting"] == "示例学生/家长代表/家长代表/示例学生家长代表"
    model.setCell(0, "relationship", "无")
    assert model.preview(0)["greeting"] == "示例学生///示例学生"
