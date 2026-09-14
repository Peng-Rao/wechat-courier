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

        function appendEmptyRecord() {
            append({ account: "", greeting: "", remark: "", valid: false,
                     error: "账号不能为空", status: "pending", selected: false })
            return count - 1
        }
        function removeRecord(row) { remove(row); return true }
        function setSelected(row, selected) { setProperty(row, "selected", selected); return true }
        function setCell(row, field, value) { setProperty(row, field, value); return true }
        function selectFirstValid() {}
    }

    QtObject {
        id: friendBackend
        property var model: friendModel
        property string defaultGreeting: ""
        property string defaultRemark: ""
        property real intervalMin: 15
        property real intervalMax: 30
        function importFile() { return false }
        function createTemplate() { return false }
    }
    QtObject {
        id: taskBackend
        property bool active: false
        property string kind: ""
        property string error: ""
        function startFriends() { return false }
    }
    QtObject { id: agentBackend; property bool automationReady: false }
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
    function accountField() { return findChild(workspace, "friendAccountField") }

    function init() {
        workspaceWindow.requestActivate()
        taskBackend.active = false
        friendModel.clear()
        friendModel.append({ account: "wxid_original", greeting: "", remark: "", valid: true,
                             error: "", status: "pending", selected: false })
        wait(100)
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
        friendModel.append({ account: "wxid_second", greeting: "", remark: "", valid: true,
                             error: "", status: "pending", selected: false })
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, 20, Qt.RightButton)
        tryCompare(menu(), "visible", true)
        compare(removeAction().visible, true)
        mouseClick(removeAction(), 10, Math.floor(removeAction().height / 2), Qt.LeftButton)
        tryCompare(friendModel, "count", 1)
        compare(friendModel.get(0).account, "wxid_second")
    }

    function test_active_task_blocks_open_menu_actions_and_callbacks() {
        verify(contextOverlay() !== null)
        mouseClick(contextOverlay(), 30, Math.floor(contextOverlay().height - 20), Qt.RightButton)
        tryCompare(menu(), "visible", true)
        taskBackend.active = true
        tryCompare(addAction(), "enabled", false)
        mouseClick(addAction(), 10, Math.floor(addAction().height / 2), Qt.LeftButton)
        wait(50)
        compare(friendModel.count, 1)
        menu().close()
        tryCompare(menu(), "visible", false)
        mouseClick(contextOverlay(), 30, Math.floor(contextOverlay().height - 20), Qt.RightButton)
        wait(50)
        compare(menu().visible, false)
    }

    function test_left_click_still_edits_account_cell() {
        var field = accountField()
        verify(field !== null)
        verify(field.width > 0 && field.height > 0)
        mouseClick(field, 20, Math.floor(field.height / 2), Qt.LeftButton)
        field.forceActiveFocus()
        tryCompare(field, "activeFocus", true)
        field.text = "wxidedited"
        compare(field.text, "wxidedited")
    }
}
