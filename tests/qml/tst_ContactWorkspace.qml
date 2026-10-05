import QtQuick
import QtQuick.Window
import QtQuick.Dialogs
import Qt.labs.qmlmodels
import QtTest
import "../../qml/components"

TestCase {
    id: testCase
    name: "ContactWorkspace"
    when: windowShown
    visible: true
    width: host.width
    height: host.height

    property var workspace: null
    readonly property var contacts: mockContacts

    TableModel {
        id: contactsModel
        TableModelColumn { display: "id" }
        TableModelColumn { display: "account" }
        TableModelColumn { display: "nickname" }
        TableModelColumn { display: "remark" }
        TableModelColumn { display: "kind" }
        TableModelColumn { display: "source" }
    }

    SignalSpy {
        id: modelResetSpy
        target: contactsModel
        signalName: "modelReset"
    }

    QtObject {
        id: mockContacts
        property var accounts: [
            {accountId: "first", label: "First account", directory: "D:/first"},
            {accountId: "second", label: "Second account", directory: "D:/second"}
        ]
        property string selectedAccountId: "first"
        property string sourceDirectory: "D:/first"
        property var model: null
        property string keyword: ""
        property bool includeSpecial: false
        property int totalCount: 0
        property int visibleCount: 0
        property bool busy: false
        property bool canRead: true
        property bool operationBlocked: false
        property string phase: "idle"
        property string statusText: "Ready"
        property string errorMessage: ""
        property string elapsedText: "00:00"
        property bool requiresElevation: false
        property var lastExportPaths: []
        property string exportFormat: "xlsx"
        property int refreshCalls: 0
        property int detectCalls: 0
        property int readCalls: 0
        property int elevationCalls: 0
        property int cancelCalls: 0
        property int clearCalls: 0
        property int confirmCalls: 0
        property int openFolderCalls: 0
        property var sorts: []
        property var copies: []
        property var exports: []
        signal overwriteRequested(var listPaths)
        function refreshAccounts() { ++refreshCalls }
        function detectSourceDirectory() { ++detectCalls; sourceDirectory = "D:/detected/xwechat_files" }
        function readContacts() { ++readCalls }
        function readAsAdministrator() { ++elevationCalls }
        function cancel() { ++cancelCalls }
        function clear() { ++clearCalls }
        function sort(column, ascending) { sorts = sorts.concat([{column: column, ascending: ascending}]) }
        function copyCell(row, column) { copies = copies.concat([{row: row, column: column}]) }
        function exportContacts(format, targetUrl, overwrite) {
            exports = exports.concat([{format: format, targetUrl: targetUrl, overwrite: overwrite}])
        }
        function confirmOverwrite() { ++confirmCalls }
        function openExportFolder() { ++openFolderCalls }
    }

    QtObject {
        id: backend
        property var contacts: mockContacts
        property var agent: ({automationReady: false, uiaReady: false, windowResponsive: false})
    }

    Item {
        id: host
        width: 960
        height: 680
    }

    Component {
        id: workspaceComponent
        ContactWorkspace { anchors.fill: parent }
    }

    function control(name) {
        var item = findChild(workspace, name)
        verify(item !== null, name + " must exist")
        return item
    }

    function click(name) {
        host.Window.window.requestActivate()
        wait(20)
        var item = control(name)
        mouseClick(item, item.width / 2, item.height / 2, Qt.LeftButton)
    }

    function typeText(text) {
        host.Window.window.requestActivate()
        wait(20)
        for (var i = 0; i < text.length; ++i) keyClick(text.charAt(i))
    }

    function loadRows(count) {
        var rows = []
        for (var i = 0; i < count; ++i)
            rows.push({id: "wxid_" + i, account: "account_" + i, nickname: "Contact " + i,
                       remark: "Remark " + i, kind: "friend", source: "Local " + i})
        contactsModel.rows = rows
        contacts.model = contactsModel
        contacts.totalCount = count
        contacts.visibleCount = count
        wait(40)
    }

    function init() {
        host.width = 960
        host.height = 680
        contacts.accounts = [
            {accountId: "first", label: "First account", directory: "D:/first"},
            {accountId: "second", label: "Second account", directory: "D:/second"}
        ]
        contacts.selectedAccountId = "first"
        contacts.sourceDirectory = "D:/first"
        contacts.model = null
        contacts.keyword = ""
        contacts.includeSpecial = false
        contacts.totalCount = 0
        contacts.visibleCount = 0
        contacts.busy = false
        contacts.canRead = true
        contacts.operationBlocked = false
        contacts.phase = "idle"
        contacts.statusText = "Ready"
        contacts.errorMessage = ""
        contacts.elapsedText = "00:00"
        contacts.requiresElevation = false
        contacts.lastExportPaths = []
        contacts.exportFormat = "xlsx"
        contacts.refreshCalls = 0
        contacts.detectCalls = 0
        contacts.readCalls = 0
        contacts.elevationCalls = 0
        contacts.cancelCalls = 0
        contacts.clearCalls = 0
        contacts.confirmCalls = 0
        contacts.openFolderCalls = 0
        contacts.sorts = []
        contacts.copies = []
        contacts.exports = []
        contactsModel.rows = []
        workspace = createTemporaryObject(workspaceComponent, host, {appBackend: backend})
        verify(workspace !== null)
        wait(40)
        // Keep chooser tests inside Qt; never open an operating-system dialog.
        control("contactSaveDialog").options = FileDialog.DontConfirmOverwrite | FileDialog.DontUseNativeDialog
        control("contactSourceFolderDialog").options = FolderDialog.DontUseNativeDialog
        control("contactExportFolderDialog").options = FolderDialog.DontUseNativeDialog
        modelResetSpy.clear()
    }

    function cleanup() {
        control("contactSaveDialog").close()
        control("contactSourceFolderDialog").close()
        control("contactExportFolderDialog").close()
        control("contactOverwriteDialog").close()
        workspace = null
    }

    function test_null_controller_and_null_model_are_safe() {
        compare(control("contactTable").model, null)
        compare(control("contactCountLabel").text, "0 / 0")
        workspace.appBackend = null
        wait(20)
        compare(control("contactTable").model, null)
        compare(control("contactReadButton").enabled, false)
        compare(control("contactExportButton").enabled, false)
        compare(control("contactAccountSelector").count, 0)
        compare(control("contactCancelButton").enabled, false)
    }

    function test_smoke_backend_without_contacts_is_safe() {
        workspace.appBackend = ({agent: backend.agent})
        compare(workspace.contactsBackend, null)
        compare(control("contactTable").model, null)
        compare(control("contactReadButton").enabled, false)
    }

    function test_read_uses_canRead_not_uia_health() {
        verify(control("contactReadButton").enabled)
        click("contactReadButton")
        compare(contacts.readCalls, 1)
        contacts.canRead = false
        tryCompare(control("contactReadButton"), "enabled", false)
        click("contactReadButton")
        compare(contacts.readCalls, 1)
        compare(contacts.elevationCalls, 0)
    }

    function test_busy_locks_sources_but_not_loaded_filters() {
        loadRows(2)
        contacts.busy = true
        wait(20)
        for (var name of ["contactReadButton", "contactRefreshButton", "contactSourceField",
                          "contactSourceFolderButton", "contactDetectDirectoryButton",
                          "contactAccountSelector", "contactExportButton"])
            compare(control(name).enabled, false, name)
        verify(control("contactSearchField").enabled)
        verify(control("contactSpecialCheckBox").enabled)
        verify(control("contactTable").enabled)
        verify(control("contactCancelButton").enabled)
        click("contactCancelButton")
        compare(contacts.cancelCalls, 1)
        contacts.busy = false
        tryCompare(control("contactCancelButton"), "enabled", false)
        click("contactCancelButton")
        compare(contacts.cancelCalls, 1)
    }

    function test_automation_blocks_export_but_keeps_loaded_view_and_filters() {
        loadRows(2)
        contacts.operationBlocked = true
        tryCompare(control("contactExportButton"), "enabled", false)
        verify(control("contactSearchField").enabled)
        verify(control("contactSpecialCheckBox").enabled)
        verify(control("contactTable").enabled)
        click("contactSearchField")
        keyClick(Qt.Key_A, Qt.ControlModifier)
        typeText("loaded")
        tryCompare(contacts, "keyword", "loaded")
        click("contactSpecialCheckBox")
        tryCompare(contacts, "includeSpecial", true)
        workspace.exportTo("csv", "file:///D:/blocked.csv")
        compare(contacts.exports.length, 0)
        contacts.operationBlocked = false
        tryCompare(control("contactExportButton"), "enabled", true)
    }

    function test_empty_controller_discovers_accounts_once_without_reading() {
        workspace.appBackend = null
        contacts.accounts = []
        workspace.appBackend = backend
        tryCompare(contacts, "refreshCalls", 1)
        compare(contacts.readCalls, 0)
        compare(contacts.elevationCalls, 0)
        wait(30)
        compare(contacts.refreshCalls, 1)
    }

    function test_empty_controller_discovers_on_component_completion() {
        workspace.destroy()
        contacts.accounts = []
        workspace = createTemporaryObject(workspaceComponent, host, {appBackend: backend})
        verify(workspace !== null)
        tryCompare(contacts, "refreshCalls", 1)
        wait(30)
        compare(contacts.refreshCalls, 1)
        compare(contacts.readCalls, 0)
    }

    function test_search_and_special_filter_stay_synchronized_while_busy() {
        loadRows(2)
        contacts.keyword = "initial"
        tryCompare(control("contactSearchField"), "text", "initial")
        contacts.busy = true
        click("contactSearchField")
        tryCompare(control("contactSearchField"), "activeFocus", true)
        keyClick(Qt.Key_A, Qt.ControlModifier)
        typeText("needle")
        tryCompare(contacts, "keyword", "needle")
        click("contactSpecialCheckBox")
        tryCompare(contacts, "includeSpecial", true)
        contacts.keyword = "external"
        contacts.includeSpecial = false
        tryCompare(control("contactSearchField"), "text", "external")
        tryCompare(control("contactSpecialCheckBox"), "checked", false)
    }

    function test_account_selection_tracks_ids_and_refresh_does_not_read() {
        var selector = control("contactAccountSelector")
        compare(selector.currentIndex, 0)
        selector.activated(1)
        compare(contacts.selectedAccountId, "second")
        contacts.selectedAccountId = "first"
        tryCompare(selector, "currentIndex", 0)
        contacts.accounts = [contacts.accounts[1], contacts.accounts[0]]
        tryCompare(selector, "currentIndex", 1)
        click("contactRefreshButton")
        compare(contacts.refreshCalls, 1)
        compare(contacts.readCalls, 0)
        contacts.busy = true
        selector.activated(0)
        compare(contacts.selectedAccountId, "first")
        contacts.selectedAccountId = "missing"
        tryCompare(selector, "currentIndex", -1)
    }

    function test_source_field_and_folder_url_forward_controller_input() {
        contacts.sourceDirectory = "D:/external"
        tryCompare(control("contactSourceField"), "text", "D:/external")
        click("contactSourceField")
        tryCompare(control("contactSourceField"), "activeFocus", true)
        keyClick(Qt.Key_A, Qt.ControlModifier)
        typeText("D:/edited")
        compare(contacts.sourceDirectory, "D:/external")
        keyClick(Qt.Key_Return)
        tryCompare(contacts, "sourceDirectory", "D:/edited")
        var dialog = control("contactSourceFolderDialog")
        click("contactSourceFolderButton")
        tryCompare(dialog, "visible", true)
        dialog.selectedFolder = "file:///D:/wechat-courier"
        compare(String(dialog.selectedFolder), "file:///D:/wechat-courier")
        dialog.accepted()
        compare(contacts.sourceDirectory, "file:///D:/wechat-courier")
        contacts.busy = true
        dialog.selectedFolder = "file:///D:/blocked"
        dialog.accepted()
        compare(contacts.sourceDirectory, "file:///D:/wechat-courier")
    }

    function test_auto_detect_updates_directory_without_reading() {
        click("contactDetectDirectoryButton")
        compare(contacts.detectCalls, 1)
        tryCompare(control("contactSourceField"), "text", "D:/detected/xwechat_files")
        compare(contacts.readCalls, 0)
        contacts.busy = true
        tryCompare(control("contactDetectDirectoryButton"), "enabled", false)
        click("contactDetectDirectoryButton")
        compare(contacts.detectCalls, 1)
    }

    function test_source_commits_only_when_editing_finishes() {
        click("contactSourceField")
        keyClick(Qt.Key_A, Qt.ControlModifier)
        typeText("D:/finished")
        compare(contacts.sourceDirectory, "D:/first")
        click("contactSearchField")
        tryCompare(contacts, "sourceDirectory", "D:/finished")
    }

    function test_source_commit_callbacks_are_guarded_while_busy() {
        click("contactSourceField")
        keyClick(Qt.Key_A, Qt.ControlModifier)
        typeText("D:/blocked")
        contacts.busy = true
        var field = control("contactSourceField")
        field.accepted()
        field.editingFinished()
        compare(contacts.sourceDirectory, "D:/first")
    }

    function test_saved_export_format_initializes_without_overwriting_user_choice_data() {
        return [
            {tag: "xlsx", format: "xlsx", index: 0},
            {tag: "csv", format: "csv", index: 1},
            {tag: "json", format: "json", index: 2},
            {tag: "all", format: "all", index: 3},
            {tag: "unknown", format: "unsupported", index: 0}
        ]
    }

    function test_saved_export_format_initializes_without_overwriting_user_choice(data) {
        workspace.appBackend = null
        contacts.exportFormat = data.format
        workspace.appBackend = backend
        var combo = control("contactFormatSelector")
        tryCompare(combo, "currentIndex", data.index)
        combo.currentIndex = (data.index + 1) % 4
        combo.activated(combo.currentIndex)
        contacts.exportFormat = "xlsx"
        wait(30)
        compare(combo.currentIndex, (data.index + 1) % 4)
        compare(contacts.exportFormat, "xlsx")
    }

    function test_format_labels_fit_at_130_pixels_data() {
        return [
            {tag: "excel", index: 0, label: "Excel"},
            {tag: "csv", index: 1, label: "CSV"},
            {tag: "json", index: 2, label: "JSON"},
            {tag: "all", index: 3, label: "全部格式"}
        ]
    }

    function test_format_labels_fit_at_130_pixels(data) {
        var combo = control("contactFormatSelector")
        combo.currentIndex = data.index
        wait(40)
        compare(combo.width, 130)
        compare(combo.contentItem.text, data.label)
        compare(combo.contentItem.truncated, false, data.label + " must remain readable")
    }

    function test_elevation_is_explicit_and_only_offered_when_required() {
        var elevated = control("contactElevationButton")
        compare(elevated.visible, false)
        contacts.requiresElevation = true
        tryCompare(elevated, "visible", true)
        compare(contacts.elevationCalls, 0)
        click("contactElevationButton")
        compare(contacts.elevationCalls, 1)
        contacts.busy = true
        tryCompare(elevated, "enabled", false)
        click("contactElevationButton")
        compare(contacts.elevationCalls, 1)
        contacts.busy = false
        contacts.canRead = false
        tryCompare(elevated, "enabled", false)
    }

    function test_table_headers_sort_ascending_then_descending() {
        loadRows(2)
        compare(control("contactTable").columns, 6)
        click("contactHeader-2")
        compare(contacts.sorts.length, 1)
        compare(contacts.sorts[0].column, 2)
        compare(contacts.sorts[0].ascending, true)
        click("contactHeader-2")
        compare(contacts.sorts[1].ascending, false)
        contacts.busy = true
        click("contactHeader-1")
        compare(contacts.sorts[2].column, 1)
        compare(contacts.sorts[2].ascending, true)
    }

    function test_double_click_copies_the_read_only_cell() {
        loadRows(2)
        var cell = control("contactCell-0-2")
        compare(control("contactCellText-0-2").text, "Contact 0")
        mouseDoubleClickSequence(cell, cell.width / 2, cell.height / 2, Qt.LeftButton)
        compare(contacts.copies.length, 1)
        compare(contacts.copies[0].row, 0)
        compare(contacts.copies[0].column, 2)
        compare(contactsModel.getRow(0).nickname, "Contact 0")
    }

    function test_contact_cell_and_tooltip_render_untrusted_text_literally() {
        loadRows(1)
        var label = control("contactCellText-0-2")
        compare(label.textFormat, Text.PlainText)
        var cell = control("contactCell-0-2")
        var tooltip = null
        for (var item of cell.data) {
            if (item.objectName === "contactCellToolTip-0-2") tooltip = item
        }
        verify(tooltip !== null)
        compare(tooltip.contentItem.textFormat, Text.PlainText)
        var malicious = '<img src="http://example.invalid/contact.png">'
        contactsModel.setRow(0, {id: "wxid_0", account: "account_0", nickname: malicious,
                                remark: "Remark 0", kind: "friend", source: "Local 0"})
        tryCompare(label, "text", malicious)
        compare(tooltip.text, "复制单元格: " + malicious)
        mouseMove(cell, cell.width / 2, cell.height / 2)
        tryCompare(tooltip, "visible", true)
        compare(tooltip.contentItem.text, "复制单元格: " + malicious)
        compare(tooltip.contentItem.textFormat, Text.PlainText)
    }

    function test_automation_blocks_cell_copy_without_disabling_the_view() {
        loadRows(2)
        var cell = control("contactCell-0-2")
        contacts.operationBlocked = true
        mouseDoubleClickSequence(cell, cell.width / 2, cell.height / 2, Qt.LeftButton)
        compare(contacts.copies.length, 0)
        verify(control("contactTable").enabled)
        verify(control("contactSearchField").enabled)
        verify(control("contactSpecialCheckBox").enabled)
        contacts.operationBlocked = false
        mouseDoubleClickSequence(cell, cell.width / 2, cell.height / 2, Qt.LeftButton)
        compare(contacts.copies.length, 1)
        compare(contacts.copies[0].row, 0)
        compare(contacts.copies[0].column, 2)
    }

    function test_scrolled_cell_copy_uses_the_visible_model_coordinates() {
        loadRows(60)
        var table = control("contactTable")
        verify(table.contentHeight > table.height)
        verify(table.contentWidth > table.width)
        table.contentY = 20 * 34
        table.contentX = table.contentWidth - table.width
        wait(60)
        var cell = control("contactCell-20-5")
        mouseDoubleClickSequence(cell, cell.width / 2, cell.height / 2, Qt.LeftButton)
        compare(contacts.copies.length, 1)
        compare(contacts.copies[0].row, 20)
        compare(contacts.copies[0].column, 5)
    }

    function test_model_reset_populates_rows_and_scrollbars_without_window_frames() {
        contacts.model = contactsModel
        wait(40)
        var table = control("contactTable")
        compare(table.rows, 0)
        verify(modelResetSpy.valid)
        var window = host.Window.window
        var wasVisible = window.visible
        try {
            // Suspend automatic rendering, as in the native frame-delivery stall.
            window.visible = false
            loadRows(80)
            verify(modelResetSpy.count > 0)
            compare(table.model, contactsModel)
            tryCompare(table, "rows", 80, 1000)
            compare(table.columns, 6)
            compare(table.contentHeight, 2720)
            verify(control("contactVerticalScrollBar").size < 1)
            verify(control("contactHorizontalScrollBar").size < 1)
            verify(control("contactSearchField").enabled)
            verify(control("contactSpecialCheckBox").enabled)
            verify(control("contactExportButton").enabled)
            contacts.operationBlocked = true
            compare(control("contactExportButton").enabled, false)
            verify(control("contactSearchField").enabled)
            verify(control("contactSpecialCheckBox").enabled)
            loadRows(0)
            tryCompare(table, "rows", 0, 1000)
            compare(table.contentHeight, 0)
        } finally {
            window.visible = wasVisible
            wait(40)
        }
    }

    function test_export_formats_data() {
        return [
            {tag: "excel", index: 0, format: "xlsx", target: "file:///D:/contacts%20list.xlsx", expected: "file:///D:/contacts list.xlsx"},
            {tag: "csv", index: 1, format: "csv", target: "file:///D:/contacts.csv", expected: "file:///D:/contacts.csv"},
            {tag: "json", index: 2, format: "json", target: "file:///D:/contacts.json", expected: "file:///D:/contacts.json"},
            {tag: "all", index: 3, format: "all", target: "file:///D:/export%20folder", expected: "file:///D:/export folder"}
        ]
    }

    function test_export_formats(data) {
        loadRows(2)
        control("contactFormatSelector").currentIndex = data.index
        click("contactExportButton")
        var dialog = control(data.index === 3 ? "contactExportFolderDialog" : "contactSaveDialog")
        tryCompare(dialog, "visible", true)
        if (data.index === 3)
            dialog.selectedFolder = data.target
        else {
            compare(dialog.fileMode, FileDialog.SaveFile)
            verify((dialog.options & FileDialog.DontConfirmOverwrite) !== 0)
            dialog.selectedFile = data.target
        }
        // The format belongs to this save request, even if the combo changes.
        control("contactFormatSelector").currentIndex = (data.index + 1) % 4
        dialog.accepted()
        compare(contacts.exports.length, 1)
        compare(contacts.exports[0].format, data.format)
        compare(contacts.exports[0].targetUrl, data.expected)
        compare(contacts.exports[0].overwrite, false)
    }

    function test_export_is_disabled_for_empty_filter_and_busy_acceptance() {
        compare(control("contactExportButton").enabled, false)
        loadRows(2)
        contacts.visibleCount = 0
        tryCompare(control("contactExportButton"), "enabled", false)
        contacts.visibleCount = 2
        click("contactExportButton")
        var dialog = control("contactSaveDialog")
        tryCompare(dialog, "visible", true)
        contacts.busy = true
        dialog.selectedFile = "file:///D:/blocked.xlsx"
        dialog.accepted()
        compare(contacts.exports.length, 0)
    }

    function test_overwrite_requires_explicit_confirmation() {
        loadRows(2)
        var dialog = control("contactOverwriteDialog")
        contacts.overwriteRequested(["D:/contacts.xlsx", "D:/contacts.csv"])
        tryCompare(dialog, "visible", true)
        verify(dialog.message.indexOf("contacts.xlsx") >= 0)
        verify(dialog.message.indexOf("contacts.csv") >= 0)
        compare(contacts.confirmCalls, 0)
        compare(contacts.exports.length, 0)
        click("contactOverwriteConfirmButton")
        compare(contacts.confirmCalls, 1)
        tryCompare(dialog, "visible", false)
    }

    function test_overwrite_cancel_and_busy_transition_never_confirm() {
        loadRows(2)
        contacts.overwriteRequested(["D:/contacts.json"])
        tryCompare(control("contactOverwriteDialog"), "visible", true)
        click("contactOverwriteCancelButton")
        compare(contacts.confirmCalls, 0)
        contacts.overwriteRequested(["D:/contacts.json"])
        contacts.busy = true
        tryCompare(control("contactOverwriteDialog"), "visible", false)
        control("contactOverwriteDialog").confirmed()
        compare(contacts.confirmCalls, 0)
    }

    function test_automation_blocks_open_chooser_and_overwrite_callbacks() {
        loadRows(2)
        click("contactExportButton")
        var save = control("contactSaveDialog")
        tryCompare(save, "visible", true)
        contacts.operationBlocked = true
        save.selectedFile = "file:///D:/blocked.xlsx"
        save.accepted()
        compare(contacts.exports.length, 0)
        contacts.operationBlocked = false
        contacts.overwriteRequested(["D:/contacts.xlsx"])
        var overwrite = control("contactOverwriteDialog")
        tryCompare(overwrite, "visible", true)
        contacts.operationBlocked = true
        tryCompare(control("contactOverwriteConfirmButton"), "enabled", false)
        overwrite.confirmed()
        compare(contacts.confirmCalls, 0)
    }

    function test_status_counts_elapsed_error_and_export_folder_follow_controller() {
        contacts.totalCount = 120
        contacts.visibleCount = 18
        contacts.statusText = "Complete"
        contacts.elapsedText = "00:12"
        tryCompare(control("contactCountLabel"), "text", "18 / 120")
        tryCompare(control("contactStatusLabel"), "text", "Complete")
        tryCompare(control("contactElapsedLabel"), "text", "00:12")
        contacts.errorMessage = "Read failed"
        tryCompare(control("contactStatusLabel"), "text", "Read failed")
        contacts.errorMessage = ""
        tryCompare(control("contactStatusLabel"), "text", "Complete")
        compare(control("contactOpenExportFolderButton").enabled, false)
        contacts.lastExportPaths = ["D:/contacts.json"]
        tryCompare(control("contactOpenExportFolderButton"), "enabled", true)
        contacts.busy = true
        click("contactOpenExportFolderButton")
        compare(contacts.openFolderCalls, 1)
    }

    function test_clear_is_a_guarded_explicit_command() {
        loadRows(2)
        click("contactClearButton")
        compare(contacts.clearCalls, 1)
        contacts.busy = true
        tryCompare(control("contactClearButton"), "enabled", false)
        click("contactClearButton")
        compare(contacts.clearCalls, 1)
    }

    function test_compact_layout_data() {
        return [
            {tag: "960x680", width: 960, height: 680, minimumTableHeight: 150},
            {tag: "125-percent-dpi", width: 768, height: 544, minimumTableHeight: 150},
            {tag: "150-percent-dpi", width: 640, height: 453, minimumTableHeight: 150},
            {tag: "150-percent-dpi-with-app-chrome", width: 640, height: 373, minimumTableHeight: 100}
        ]
    }

    function test_compact_layout(data) {
        loadRows(60)
        contacts.requiresElevation = true
        contacts.busy = true
        contacts.sourceDirectory = "D:/" + new Array(100).join("long directory/")
        contacts.statusText = new Array(200).join("status ")
        contacts.accounts = [{accountId: "first", label: new Array(100).join("long account "), directory: "D:/first"}]
        host.width = data.width
        host.height = data.height
        wait(100)
        var names = ["contactSourceField", "contactSourceFolderButton", "contactDetectDirectoryButton",
                     "contactAccountSelector",
                     "contactRefreshButton", "contactReadButton", "contactElevationButton",
                     "contactSearchField", "contactSpecialCheckBox", "contactCountLabel", "contactTable",
                     "contactStatusLabel", "contactElapsedLabel", "contactCancelButton",
                     "contactFormatSelector", "contactExportButton"]
        for (var name of names) {
            var item = control(name)
            var point = item.mapToItem(host, 0, 0)
            verify(item.width > 0 && item.height > 0, name + " needs stable dimensions")
            verify(point.x >= 0 && point.y >= 0, name + " starts inside the viewport")
            verify(point.x + item.width <= host.width + 1, name + " fits horizontally")
            verify(point.y + item.height <= host.height + 1, name + " fits vertically")
        }
        var table = control("contactTable")
        verify(table.height >= data.minimumTableHeight)
        verify(table.contentWidth > table.width)
        verify(table.contentHeight > table.height)
        var read = control("contactReadButton")
        var elevation = control("contactElevationButton")
        verify(read.mapToItem(workspace, read.width, 0).x <= elevation.mapToItem(workspace, 0, 0).x)
        var status = control("contactStatusLabel")
        var elapsed = control("contactElapsedLabel")
        verify(status.mapToItem(workspace, status.width, 0).x <= elapsed.mapToItem(workspace, 0, 0).x)
    }
}
