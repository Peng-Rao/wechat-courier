import QtQuick
import QtQuick.Window
import QtTest
import "../../qml/components"

TestCase {
    name: "TaskMonitorTimeline"
    when: windowShown

    ListModel { id: taskItems }
    ListModel { id: runtimeLogs }

    QtObject {
        id: taskBackend
        property bool acceptanceEnabled: false
        property bool active: false
        property bool cleanupFailed: false
        property var cleanupResult: ({})
        property string currentOutcome: "error"
        property string currentStepCode: "submit_verified"
        property string currentStepLabel: "提交结果校对失败"
        property int done: 1
        property int failureCount: 0
        property var items: taskItems
        property string phase: "error"
        property real progress: 1.0
        property string recoveryHint: ""
        property int retryAttempt: 1
        property string retryLevel: "none"
        property int retryMaxAttempts: 1
        property var runtimeLogs: runtimeLogs
        property bool safeRetryAvailable: false
        property int successCount: 0
        property int total: 1
        property int unknownCount: 1
        property bool wechatRestartAvailable: false
        function detectWechatRecovery() {}
        function exportDiagnostics() { return false }
        function exportResults() { return false }
        function pause() {}
        function restartWechatAfterFailure() { return false }
        function resume() {}
        function retryFailedItem() { return false }
        function stepLabel(code, outcome) { return code }
        function stop() {}
    }

    QtObject {
        id: agentBackend
        property bool automationReady: true
        property string blockingWindow: ""
        property bool canStartTask: true
        property bool connected: true
        property bool processDetected: true
        property int sessionGeneration: 1
        property bool windowEnabled: true
        property bool windowResponsive: true
    }

    Window {
        id: monitorWindow
        width: 1200
        height: 800
        visible: true

        TaskMonitor {
            id: monitor
            anchors.fill: parent
            taskBackend: taskBackend
            agentBackend: agentBackend
            taskKind: "friend_add"
        }
    }

    function node(index) {
        return findChild(monitor, "taskStepNode-" + index)
    }

    function hasText(item, value) {
        if (item.text !== undefined && item.text === value)
            return true
        var children = item.children || []
        for (var i = 0; i < children.length; ++i)
            if (hasText(children[i], value))
                return true
        return false
    }

    function test_stopped_row_does_not_display_waiting() {
        taskItems.append({target: "mock_only", detail: "未执行：任务已结束",
                          result: "stopped", duration: "--", stepCode: "", itemId: "one"})
        tryVerify(function() { return hasText(monitor, "已停止") })
        verify(!hasText(monitor, "等待中"))
        taskItems.clear()
    }

    function connector(index) {
        return findChild(monitor, "taskStepConnector-" + index)
    }

    function test_connectors_run_center_to_center_without_end_overhang() {
        var firstNode = node(0)
        var firstConnector = connector(0)
        var secondNode = node(1)
        verify(firstNode !== null)
        verify(firstConnector !== null)
        verify(secondNode !== null)

        var firstCenter = firstNode.mapToItem(monitor, firstNode.width / 2, firstNode.height / 2)
        var connectorStart = firstConnector.mapToItem(monitor, 0, 0)
        var connectorEnd = firstConnector.mapToItem(monitor, 0, firstConnector.height)
        var secondCenter = secondNode.mapToItem(monitor, secondNode.width / 2, secondNode.height / 2)
        fuzzyCompare(connectorStart.y, firstCenter.y, 0.5)
        fuzzyCompare(connectorEnd.y, secondCenter.y, 0.5)

        var lastIndex = monitor.steps.length - 1
        var penultimateConnector = connector(lastIndex - 1)
        var lastNode = node(lastIndex)
        var penultimateEnd = penultimateConnector.mapToItem(
            monitor, 0, penultimateConnector.height)
        var lastCenter = lastNode.mapToItem(monitor, lastNode.width / 2, lastNode.height / 2)
        fuzzyCompare(penultimateEnd.y, lastCenter.y, 0.5)
        compare(connector(lastIndex).visible, false)
    }
}
