import QtQuick
import QtQuick.Window
import QtTest
import "../../qml" as Courier

TestCase {
    name: "WorkspaceTaskOwnership"
    when: windowShown

    ListModel { id: taskItems }
    ListModel { id: runtimeLogs }
    ListModel {
        id: friendModel
        property int validCount: count
        property int selectedCount: count
        property string importError: ""
        property string importWarning: ""
        function preview(row) { return { greeting: "", remark: "", error: "" } }
        function appendEmptyRecord() { return -1 }
        function clearRecords() { clear(); selectedCount = 0; return true }
        function removeRecord() { return false }
        function selectFirstValid() {}
        function setCell() { return false }
        function setSelected() { return false }
    }

    QtObject {
        id: messageBackend
        property var filePaths: []
        property real intervalMax: 3
        property real intervalMin: 2
        property string previewMessage: "hello"
        property string previewTarget: "文件传输助手"
        property int recipientCount: 1
        property string recipientsText: "文件传输助手"
        property string templateText: "hello"
        property bool useForward: false
        function addFile() {}
        function removeFile() {}
    }

    QtObject {
        id: friendBackend
        property string defaultGreeting: "你好"
        property string defaultRelationship: "妈妈"
        property var relationshipOptions: ["无", "妈妈", "爸爸", "姐姐"]
        property real intervalMax: 30
        property real intervalMin: 15
        property int batchLimit: 100
        property int batchLimitMinimum: 1
        property int batchLimitMaximum: 1000
        property var model: friendModel
        function createTemplate() { return false }
        function importFile() { return false }
    }

    QtObject {
        id: settingsBackend
        property int agentRestartLimit: 2
        property int glassOpacity: 72
        property bool glassEnabled: true
        property bool isDark: true
        property int loginTimeout: 90
        property string unknownPolicy: "continue"
        property string wechatRecoveryMode: "confirm"
    }

    QtObject {
        id: agentBackend
        property bool automationReady: true
        property string blockingWindow: ""
        property bool canStartTask: true
        property bool connected: true
        property bool friendSubmitEnabled: true
        property bool processDetected: true
        property int sessionGeneration: 1
        property bool windowEnabled: true
        property bool windowResponsive: true
    }

    QtObject {
        id: taskBackend
        property bool acceptanceEnabled: false
        property string acceptanceFriendStateJson: "{}"
        property string acceptanceMessageStateJson: "{}"
        property string acceptanceTaskStateJson: "{}"
        property bool active: false
        property bool cleanupFailed: false
        property var cleanupResult: ({})
        property string currentOutcome: "pending"
        property string currentStepCode: ""
        property string currentStepLabel: "等待任务开始"
        property int done: 0
        property string error: ""
        property int failureCount: 0
        property var items: taskItems
        property string kind: ""
        property string phase: "idle"
        property real progress: 0
        property string recoveryHint: ""
        property int retryAttempt: 1
        property string retryLevel: "none"
        property int retryMaxAttempts: 1
        property var runtimeLogs: runtimeLogs
        property bool safeRetryAvailable: false
        property int successCount: 0
        property int total: 0
        property int unknownCount: 0
        property bool wechatRestartAvailable: false
        function detectWechatRecovery() {}
        function exportDiagnostics() { return false }
        function exportResults() { return false }
        function pause() {}
        function restartWechatAfterFailure() { return false }
        function resume() {}
        function retryFailedItem() { return false }
        function startFriends() {
            kind = "friend_add"
            active = true
            return true
        }
        function startMessage() {
            kind = "message_send"
            active = true
            return true
        }
        function stepLabel(code) { return code }
        function stop() {}
    }

    QtObject {
        id: appBackend
        property var agent: agentBackend
        property var friends: friendBackend
        property var message: messageBackend
        property var settings: settingsBackend
        property var task: taskBackend
    }

    Window {
        id: appWindow
        width: 1200
        height: 800
        visible: true

        Courier.App {
            id: app
            anchors.fill: parent
            appBackend: appBackend
        }
    }

    function messageWorkspace() { return findChild(app, "messageWorkspace") }
    function friendWorkspace() { return findChild(app, "friendWorkspace") }

    function init() {
        taskBackend.active = false
        taskBackend.kind = ""
        app.workspaceIndex = 0
        wait(20)
        if (messageWorkspace() !== null) messageWorkspace().monitorDismissed = false
        if (friendWorkspace() !== null) friendWorkspace().monitorDismissed = false
    }

    function test_completed_logs_stay_only_on_the_owning_workspace() {
        var messages = messageWorkspace()
        var friends = friendWorkspace()
        verify(messages !== null)
        verify(friends !== null)

        messages.startTask()
        compare(messages.monitorVisible, true)
        taskBackend.active = false
        taskBackend.kind = "friend_add"
        wait(20)

        compare(messages.monitorVisible, false)
        compare(friends.monitorVisible, true)

        app.workspaceIndex = 0
        compare(messages.monitorVisible, false)
        app.workspaceIndex = 1
        compare(friends.monitorVisible, true)
        friends.dismissMonitor()
        compare(friends.monitorVisible, false)
    }

    function test_active_task_forces_owner_tab_and_resets_dismissal() {
        var messages = messageWorkspace()
        verify(messages !== null)
        taskBackend.kind = "message_send"
        messages.dismissMonitor()
        compare(messages.monitorVisible, false)
        app.workspaceIndex = 1

        taskBackend.active = true
        tryCompare(app, "workspaceIndex", 0)
        compare(messages.monitorVisible, true)

        taskBackend.active = false
        taskBackend.kind = "friend_add"
        app.workspaceIndex = 0
        taskBackend.active = true
        tryCompare(app, "workspaceIndex", 1)
    }
}
