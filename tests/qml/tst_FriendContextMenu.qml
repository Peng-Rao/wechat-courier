import QtQuick
import QtQuick.Window
import QtTest
import "../../qml/components"

TestCase {
    name: "FriendContextMenu"
    when: windowShown

    ListModel {
        id: friendModel
        property int validCount: count
        property int selectedCount: 0
        property string importError: ""
        property string importWarning: ""
        function preview(row) { return { greeting: "", remark: "", error: "" } }

        function appendEmptyRecord() {
            append({ friendName: "示例学生", relationshipChoice: "使用全局", account: "", greeting: "", remark: "", valid: false,
                     error: "账号不能为空", status: "pending", selected: false })
            return count - 1
        }
        function removeRecord(row) { remove(row); return true }
        function clearRecords() {
            if (count === 0 && importError === "") return false
            clear()
            importError = ""
            selectedCount = 0
            return true
        }
        function setSelected(row, selected) { setProperty(row, "selected", selected); return true }
        function setCell(row, field, value) { setProperty(row, field, value); return true }
        function selectFirstValid() {}
    }

    QtObject {
        id: friendBackend
        property var model: friendModel
        property string defaultGreeting: ""
        property string defaultRelationship: "妈妈"
        property var relationshipOptions: ["无", "妈妈", "爸爸", "姐姐"]
        property real intervalMin: 15
        property real intervalMax: 30
        property int batchLimit: 100
        function importFile() { return false }
        function createTemplate() { return false }
    }
    QtObject {
        id: taskBackend
        property bool active: false
        property string kind: ""
        property string error: ""
        property bool acceptanceEnabled: false
        property int startCalls: 0
        function startFriends() {
            ++startCalls
            kind = "friend_add"
            active = true
            return true
        }
    }
    QtObject {
        id: agentBackend
        property bool automationReady: true
        property bool canStartTask: true
        property bool friendSubmitEnabled: true
    }
    QtObject {
        id: appBackend
        property var friends: friendBackend
        property var task: taskBackend
        property var agent: agentBackend
    }

    Window {
        id: workspaceWindow
        width: 1000
        height: 700
        visible: true

        FriendWorkspace {
            id: workspace
            anchors.fill: parent
            appBackend: appBackend
        }
    }

    function table() { return findChild(workspace, "friendImportTable") }
    function contextOverlay() { return findChild(workspace, "friendTableContextOverlay") }
    function menu() { return findChild(workspace, "friendContextMenu") }
    function addAction() { return findChild(workspace, "addFriendRowMenuItem") }
    function removeAction() { return findChild(workspace, "removeFriendRowMenuItem") }
    function clearButton() { return findChild(workspace, "clearFriendTableButton") }
    function startButton() { return findChild(workspace, "startFriendsButton") }
    function submitDialog() { return findChild(workspace, "friendSubmitConfirmDialog") }
    function submitConfirmButton() { return findChild(workspace, "friendSubmitConfirmButton") }
    function submitCancelButton() { return findChild(workspace, "friendSubmitCancelButton") }
    function accountField() {
        // TableView may retain pooled delegates with the same objectName.
        var cell = table().itemAtCell(Qt.point(0, 0))
        return cell ? findChild(cell, "friendAccountField") : null
    }
    function init() {
        taskBackend.active = false
        friendBackend.batchLimit = 100
        taskBackend.kind = ""
        taskBackend.startCalls = 0
        taskBackend.acceptanceEnabled = false
        agentBackend.friendSubmitEnabled = true
        workspace.monitorDismissed = false
        if (submitDialog() !== null)
            submitDialog().close()
        menu().close()
        tryCompare(menu(), "visible", false)
        friendModel.clear()
        friendModel.append({ friendName: "示例学生", relationshipChoice: "使用全局", account: "wxid_original", greeting: "", remark: "", valid: true,
                             error: "", status: "pending", selected: false })
        friendModel.selectedCount = 1
        wait(100)
        workspaceWindow.requestActivate()
        tryCompare(workspaceWindow, "active", true)
    }

    function test_batch_limit_labels_follow_settings() {
        var countLabel = findChild(workspace, "friendSelectionCount")
        var selectButton = findChild(workspace, "selectFirstFriendsButton")
        verify(countLabel !== null)
        verify(selectButton !== null)
        friendBackend.batchLimit = 250
        friendModel.selectedCount = 5
        tryCompare(countLabel, "text", "已选择 5 / 250")
        compare(selectButton.text, "选择前 250 条")
        taskBackend.active = true
        verify(!selectButton.enabled)
    }

    function test_start_requires_explicit_confirmation_and_cancel_is_safe() {
        verify(startButton() !== null)
        verify(startButton().enabled)
        mouseClick(startButton(), 20, Math.floor(startButton().height / 2), Qt.LeftButton)
        tryCompare(submitDialog(), "visible", true)
        compare(taskBackend.startCalls, 0)

        verify(submitCancelButton() !== null)
        mouseClick(submitCancelButton(), 20,
                   Math.floor(submitCancelButton().height / 2), Qt.LeftButton)
        tryCompare(submitDialog(), "visible", false)
        compare(taskBackend.startCalls, 0)
    }

    function test_relationship_editors_preview_and_template_tools_exist_and_lock() {
        var cell = table().itemAtCell(Qt.point(0, 0))
        verify(cell !== null)
        var nameField = findChild(cell, "friendNameField")
        var relationship = findChild(cell, "friendRelationshipSelector")
        var remark = findChild(cell, "friendRemarkField")
        var globalRelationship = findChild(workspace, "globalRelationshipSelector")
        var insertButton = findChild(workspace, "insertAddressPlaceholder")
        verify(nameField !== null)
        verify(relationship !== null)
        verify(remark !== null && remark.readOnly)
        verify(globalRelationship !== null)
        verify(insertButton !== null)
        verify(findChild(workspace, "friendContentPreview") !== null)
        taskBackend.active = true
        compare(nameField.enabled, false)
        compare(relationship.enabled, false)
        compare(globalRelationship.enabled, false)
        compare(insertButton.enabled, false)
    }

    function test_confirmation_starts_exactly_one_friend_task() {
        mouseClick(startButton(), 20, Math.floor(startButton().height / 2), Qt.LeftButton)
        tryCompare(submitDialog(), "visible", true)

        verify(submitConfirmButton() !== null)
        mouseClick(submitConfirmButton(), 20,
                   Math.floor(submitConfirmButton().height / 2), Qt.LeftButton)
        tryCompare(submitDialog(), "visible", false)
        compare(taskBackend.startCalls, 1)
        compare(workspace.monitorVisible, true)
    }

    function test_confirmation_rechecks_task_lock_before_starting() {
        mouseClick(startButton(), 20, Math.floor(startButton().height / 2), Qt.LeftButton)
        tryCompare(submitDialog(), "visible", true)
        taskBackend.active = true

        workspace.confirmFriendSubmission()
        compare(taskBackend.startCalls, 0)
    }

    function test_row_right_click_adds_a_row() {
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, 20, Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(workspace.contextRow, 0)
        mouseClick(addAction(), 10, Math.floor(addAction().height / 2), Qt.LeftButton)
        tryCompare(friendModel, "count", 2)
    }

    function test_blank_area_right_click_only_offers_add() {
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, Math.floor(contextOverlay().height - 20), Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(workspace.contextRow, -1)
        compare(removeAction().visible, false)
        mouseClick(addAction(), 10, Math.floor(addAction().height / 2), Qt.LeftButton)
        tryCompare(friendModel, "count", 2)
    }

    function test_row_right_click_deletes_that_row() {
        friendModel.append({ friendName: "示例学生", relationshipChoice: "使用全局", account: "wxid_second", greeting: "", remark: "", valid: true,
                             error: "", status: "pending", selected: false })
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, 20, Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(removeAction().visible, true)
        mouseClick(removeAction(), 10, Math.floor(removeAction().height / 2), Qt.LeftButton)
        tryCompare(friendModel, "count", 1)
        compare(friendModel.get(0).account, "wxid_second")
    }

    function test_clear_button_removes_all_rows_and_is_disabled_while_locked() {
        friendModel.append({ friendName: "示例学生", relationshipChoice: "使用全局", account: "wxid_second", greeting: "", remark: "", valid: true,
                             error: "", status: "pending", selected: false })
        verify(clearButton() !== null)
        verify(clearButton().enabled)

        taskBackend.active = true
        tryCompare(clearButton(), "enabled", false)
        compare(workspace.clearFriendTable(), false)
        compare(friendModel.count, 2)

        taskBackend.active = false
        tryCompare(clearButton(), "enabled", true)
        mouseClick(clearButton(), 10, Math.floor(clearButton().height / 2), Qt.LeftButton)
        tryCompare(friendModel, "count", 0)
        compare(friendModel.selectedCount, 0)
        compare(clearButton().enabled, false)
    }

    function test_active_task_blocks_open_menu_actions_and_callbacks() {
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, 20, Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(workspace.contextRow, 0)
        compare(removeAction().visible, true)
        taskBackend.active = true
        tryCompare(addAction(), "enabled", false)
        tryCompare(removeAction(), "enabled", false)
        mouseClick(addAction(), 10, Math.floor(addAction().height / 2), Qt.LeftButton)
        mouseClick(removeAction(), 10, Math.floor(removeAction().height / 2), Qt.LeftButton)
        wait(50)
        compare(friendModel.count, 1)
        compare(workspace.appendManualRecord(), -1)
        compare(workspace.removeContextRecord(), false)
        compare(friendModel.count, 1)
        menu().close()
        tryCompare(menu(), "visible", false)
        mouseClick(contextOverlay(), 30, Math.floor(contextOverlay().height - 20), Qt.RightButton)
        wait(50)
        compare(menu().visible, false)
    }

    function test_left_click_account_field_establishes_focus() {
        var field = accountField()
        verify(field !== null)
        verify(field.width > 0 && field.height > 0)
        mouseClick(field, 20, Math.floor(field.height / 2), Qt.LeftButton)
        tryCompare(field, "activeFocus", true)
    }

    function test_scrolled_row_menu_deletes_correct_record_and_append_is_visible() {
        verify(contextOverlay() !== null)
        verify(table().height > 46)
        for (var row = friendModel.count; row < 30; ++row) {
            friendModel.append({ friendName: "示例学生", relationshipChoice: "使用全局", account: "wxid_scroll" + row, greeting: "", remark: "",
                                 valid: true, error: "", status: "pending", selected: false })
        }
        wait(100)
        var targetRow = 10
        var targetAccount = friendModel.get(targetRow).account
        table().contentY = targetRow * 46
        wait(100)
        mouseClick(contextOverlay(), 30, 23, Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(workspace.contextRow, targetRow)
        compare(removeAction().visible, true)
        compare(workspace.removeContextRecord(), true)
        compare(workspace.contextRow, -1)
        tryCompare(friendModel, "count", 29)
        for (var index = 0; index < friendModel.count; ++index)
            compare(friendModel.get(index).account === targetAccount, false)

        compare(workspace.appendManualRecord(), 29)
        wait(100)
        var lastRow = friendModel.count - 1
        verify(table().contentY <= lastRow * 46)
        verify(table().contentY + table().height >= (lastRow + 1) * 46)
    }
}
