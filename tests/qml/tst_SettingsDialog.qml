import QtQuick
import QtTest
import "../../qml/components"

TestCase {
    name: "SettingsDialog"
    when: windowShown
    width: 960
    height: 680

    QtObject {
        id: mockTask
        property bool active: false
    }

    QtObject {
        id: mockMessage
        property real intervalMin: 2
        property real intervalMax: 3
        property bool useForward: false
    }

    QtObject {
        id: mockFriends
        property string defaultGreeting: ""
        property string defaultRelationship: "妈妈"
        property var relationshipOptions: ["无", "妈妈", "爸爸", "姐姐"]
        property int intervalMin: 15
        property int intervalMax: 30
        property int batchLimit: 100
        property int batchLimitMinimum: 1
        property int batchLimitMaximum: 1000
    }

    QtObject {
        id: mockSettings
        property string unknownPolicy: "continue"
        property int agentRestartLimit: 2
        property string wechatRecoveryMode: "confirm"
        property int loginTimeout: 90
        property bool isDark: false
        property bool glassEnabled: true
        property int glassOpacity: 72
    }

    QtObject {
        id: mockBackend
        property var task: mockTask
        property var message: mockMessage
        property var friends: mockFriends
        property var settings: mockSettings
    }

    SettingsDialog {
        id: settingsDialog
        appBackend: mockBackend
    }

    function init() {
        mockTask.active = false
        mockMessage.intervalMin = 2
        mockFriends.batchLimit = 100
        settingsDialog.sectionIndex = 0
        settingsDialog.open()
        tryCompare(settingsDialog, "opened", true)
    }

    function cleanup() {
        mockTask.active = false
        settingsDialog.close()
    }

    function test_starting_task_does_not_commit_focused_dirty_field() {
        var intervalField = findChild(settingsDialog, "settingsMessageIntervalMin")
        verify(intervalField !== null)
        intervalField.forceActiveFocus()
        tryCompare(intervalField, "activeFocus", true)
        intervalField.text = "99"

        mockTask.active = true

        tryCompare(settingsDialog, "opened", false)
        compare(mockMessage.intervalMin, 2)
    }

    function test_unlocked_field_still_commits_on_focus_loss() {
        var intervalField = findChild(settingsDialog, "settingsMessageIntervalMin")
        verify(intervalField !== null)
        intervalField.forceActiveFocus()
        tryCompare(intervalField, "activeFocus", true)
        intervalField.text = "7"

        settingsDialog.close()

        compare(mockMessage.intervalMin, 7)
    }

    function test_friend_batch_limit_steps_and_commits_typed_value() {
        settingsDialog.sectionIndex = 1
        var control = findChild(settingsDialog, "settingsFriendBatchLimit")
        verify(control !== null)
        compare(control.value, 100)
        compare(control.from, 1)
        compare(control.to, 1000)
        verify(control.editable)
        tryCompare(control, "visible", true)
        wait(50)
        mouseClick(control.up.indicator, control.up.indicator.width / 2,
                   control.up.indicator.height / 2)
        compare(control.value, 101)
        compare(mockFriends.batchLimit, 101)
        mouseClick(control.down.indicator, control.down.indicator.width / 2,
                   control.down.indicator.height / 2)
        compare(control.value, 100)
        compare(mockFriends.batchLimit, 100)
        control.contentItem.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_2)
        keyClick(Qt.Key_5)
        keyClick(Qt.Key_0)
        keyClick(Qt.Key_Tab)
        tryCompare(mockFriends, "batchLimit", 250)
        mockFriends.batchLimit = 75
        tryCompare(control, "value", 75)
    }

    function test_friend_batch_limit_button_boundaries() {
        settingsDialog.sectionIndex = 1
        var control = findChild(settingsDialog, "settingsFriendBatchLimit")
        verify(control !== null)
        tryCompare(control, "visible", true)
        mockFriends.batchLimit = 1
        tryCompare(control, "value", 1)
        mouseClick(control.down.indicator, control.down.indicator.width / 2,
                   control.down.indicator.height / 2)
        compare(mockFriends.batchLimit, 1)
        mockFriends.batchLimit = 1000
        tryCompare(control, "value", 1000)
        mouseClick(control.up.indicator, control.up.indicator.width / 2,
                   control.up.indicator.height / 2)
        compare(mockFriends.batchLimit, 1000)
    }

    function test_task_start_does_not_commit_dirty_batch_limit() {
        settingsDialog.sectionIndex = 1
        var control = findChild(settingsDialog, "settingsFriendBatchLimit")
        verify(control !== null)
        tryCompare(control, "visible", true)
        wait(50)
        control.contentItem.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_2)
        keyClick(Qt.Key_5)
        keyClick(Qt.Key_0)
        mockTask.active = true
        tryCompare(settingsDialog, "opened", false)
        compare(mockFriends.batchLimit, 100)
        verify(!control.enabled)
    }

    function test_friend_interval_editor_accepts_one_second() {
        var intervalField = findChild(settingsDialog, "settingsFriendIntervalMin")
        verify(intervalField !== null)
        compare(intervalField.validator.bottom, 1)
        intervalField.forceActiveFocus()
        tryCompare(intervalField, "activeFocus", true)
        intervalField.text = "1"

        settingsDialog.close()

        compare(mockFriends.intervalMin, 1)
    }
}
