"""Contacts workspace structure; runtime behavior lives in the QML tests."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "qml" / "components" / "ContactWorkspace.qml"


def source():
    assert WORKSPACE.is_file(), "ContactWorkspace.qml has not been implemented"
    return WORKSPACE.read_text(encoding="utf-8")


def test_contacts_workspace_exposes_stable_automation_names():
    qml = source()
    for name in (
        "contactWorkspace", "contactReadButton", "contactAccountSelector",
        "contactSearchField", "contactSpecialCheckBox", "contactTable",
        "contactExportButton", "contactCancelButton",
    ):
        assert f'objectName: "{name}"' in qml


def test_contacts_table_is_read_only_and_uses_the_controller_model_role():
    qml = source()
    assert "TableView {" in qml
    assert "HorizontalHeaderView {" in qml
    assert "cellText" in qml
    assert "TableView.NoEditTriggers" in qml
    assert "ScrollBar.vertical:" in qml
    assert "ScrollBar.horizontal:" in qml
    assert "onDoubleClicked:" in qml
    assert "copyCell(" in qml
    assert ".sort(" in qml
    assert "setCell(" not in qml
    assert "editDelegate:" not in qml


def test_contacts_export_uses_controller_overwrite_confirmation():
    qml = source()
    assert "FileDialog.SaveFile" in qml
    assert "FileDialog.DontConfirmOverwrite" in qml
    assert "FolderDialog {" in qml
    assert 'model: ["Excel", "CSV", "JSON", "全部格式"]' in qml
    assert "onOverwriteRequested(" in qml
    assert "ConfirmDialog {" in qml
    assert ".confirmOverwrite()" in qml
    assert ".exportContacts(format, String(targetUrl), false)" in qml
    assert ".openExportFolder()" in qml


def test_contacts_availability_is_owned_by_contacts_not_uia_health():
    qml = source()
    assert "appBackend.contacts" in qml
    assert "contactsBackend.canRead" in qml
    assert "contactsBackend.operationBlocked" in qml
    assert "contactsBackend.requiresElevation" in qml
    assert "以管理员权限读取" in qml
    assert ".readAsAdministrator()" in qml
    assert ".readContacts()" in qml
    assert ".refreshAccounts()" in qml
    assert ".cancel()" in qml
    assert ".clear()" in qml
    for forbidden in (
        "appBackend.agent", "appBackend.task", "automationReady", "uiaReady",
        "windowResponsive", "startSystemMove", "startSystemResize", "WxRoundedBand",
    ):
        assert forbidden not in qml
    assert "Component.onCompleted:" in qml
    assert "Qt.callLater(root.refreshEmptyAccounts)" in qml
    assert "directoryPath" not in qml
    assert "decodeURIComponent" not in qml
    assert "sourceDirectory = String(selectedFolder)" in qml


def test_contacts_reuses_theme_and_existing_icons_without_large_radii():
    qml = source()
    assert 'import "../theme"' in qml
    assert "WxIcon {" in qml
    assert "WxTheme.clToolbarFill" in qml
    assert "WxTheme.clFieldFill" in qml
    assert "Layout.minimumWidth: 0" in qml
    assert not re.search(r"WxTheme\.\w+\s*=(?!=)", qml)
    for value in re.findall(r"\bradius:\s*([^\n]+)", qml):
        assert value.strip() in {"WxTheme.radiusSmall", "WxTheme.radiusMedium", "4", "6", "8"}
    icon_names = re.findall(r'iconName: "([a-z_]+)"', qml)
    assert icon_names
    for name in icon_names:
        assert (ROOT / "qml" / "icons" / f"{name}.svg").is_file(), name


def test_contacts_has_pure_qml_behavior_tests():
    qml_test = (ROOT / "tests" / "qml" / "tst_ContactWorkspace.qml").read_text(encoding="utf-8")
    assert 'name: "ContactWorkspace"' in qml_test
    assert "ContactWorkspace {" in qml_test
    assert "signal overwriteRequested(var listPaths)" in qml_test
    assert "TableModel {" in qml_test
    assert "test_busy_locks_sources_but_not_loaded_filters" in qml_test
    assert "test_null_controller_and_null_model_are_safe" in qml_test
    assert "test_overwrite_requires_explicit_confirmation" in qml_test
    assert "test_compact_layout" in qml_test


def test_directory_commits_on_edit_completion_and_format_is_controller_read_only():
    qml = source()
    field_start = qml.index('objectName: "contactSourceField"')
    field_end = qml.index('objectName: "contactSourceFolderButton"')
    field = qml[field_start:field_end]
    assert "onEditingFinished:" in field
    assert "onAccepted:" in field
    assert "onTextEdited:" not in field
    assert "contactsBackend.exportFormat" in qml
    assert '["xlsx", "csv", "json", "all"]' in qml
    assert not re.search(r"contactsBackend\.exportFormat\s*=(?!=)", qml)


def test_model_layout_refresh_is_deferred_and_event_driven_without_polling():
    qml = source()
    assert "target: root.tableModel || null" in qml
    assert "function onModelReset()" in qml
    assert "Qt.callLater(root.forceTableLayout)" in qml
    assert "contactTable.forceLayout()" in qml
    assert "onTableModelChanged:" in qml
    assert "onVisibleChanged:" in qml
    assert "Timer {" not in qml
    assert "setInterval" not in qml


def test_contact_text_and_tooltips_never_interpret_external_markup():
    qml = source()
    text_blocks = re.findall(r"\bText\s*\{([^{}]*)\}", qml)
    assert text_blocks
    for block in text_blocks:
        assert "textFormat: Text.PlainText" in block
    assert 'objectName: "contactCellToolTip-"' in qml
    assert "ToolTip.text: \"复制单元格: \"" not in qml
    copy_handler = re.search(r"onDoubleClicked:\s*\{([^}]*)\}", qml).group(1)
    assert "!root.operationBlocked" in copy_handler
