import QtQuick
import QtTest
import "../../qml/components"

TestCase {
    name: "SettingsDialog"
    when: windowShown

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
        property string defaultRemark: ""
        property int intervalMin: 15
        property int intervalMax: 30
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
