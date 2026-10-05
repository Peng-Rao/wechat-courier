import QtQuick
import QtQuick.Window
import QtTest
import "../../qml/components"

TestCase {
    name: "TaskMonitorTimeline"
    when: windowShown

    ListModel {
        id: taskItems
        function indexOfItem(value) {
            for (var i = 0; i < count; ++i) if (get(i).itemId === value) return i
            return -1
        }
    }
    ListModel { id: runtimeLogs }

    QtObject {
        id: taskBackend
        property bool acceptanceEnabled: false
        property bool active: false
        property string automationStatus: ""
        property bool taskWindowReady: false
        property real waitingRemaining: 0
        property string intervalLabel: "本批间隔 1–5 秒"
        property string elapsedLabel: "01:02:03"
        property string riskStopItemId: ""
        property string riskStopKind: ""
        property string riskStopLabel: ""
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
        property int retryCalls: 0
        property int detectCalls: 0
        property int pauseCalls: 0
        property int resumeCalls: 0
        property int stopCalls: 0
        property string resultsUrl: ""
        property string diagnosticsUrl: ""
        signal executionStateChanged()
        function detectWechatRecovery() { ++detectCalls }
        function exportDiagnostics(url) { diagnosticsUrl = String(url); return false }
        function exportResults(url) { resultsUrl = String(url); return false }
        function pause() { ++pauseCalls }
        function restartWechatAfterFailure() { return false }
        function resume() { ++resumeCalls }
        function retryFailedItem() { ++retryCalls; return false }
        function stepLabel(code, outcome) { return code }
        function stop() { ++stopCalls }
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

    function buttonByText(item, value) {
        if (item.text === value && item.clicked !== undefined)
            return item
        var children = item.children || []
        for (var i = 0; i < children.length; ++i) {
            var found = buttonByText(children[i], value)
            if (found !== null) return found
        }
        return null
    }

    function init() {
        monitorWindow.width = 1200
        monitorWindow.height = 800
        monitor.taskKind = "friend_add"
        monitor.logsExpanded = false
        taskBackend.active = false
        taskBackend.phase = "error"
        taskBackend.currentOutcome = "unknown"
        taskBackend.currentStepCode = "submit_verified"
        taskBackend.cleanupResult = ({})
        taskBackend.cleanupFailed = false
        taskBackend.riskStopItemId = ""
        taskBackend.riskStopLabel = ""
        taskBackend.taskWindowReady = false
        taskBackend.safeRetryAvailable = false
        taskBackend.retryCalls = 0
        taskBackend.detectCalls = 0
        taskBackend.pauseCalls = 0
        taskBackend.resumeCalls = 0
        taskBackend.stopCalls = 0
        taskBackend.resultsUrl = ""
        taskBackend.diagnosticsUrl = ""
        agentBackend.automationReady = true
        agentBackend.canStartTask = true
        taskItems.clear()
        runtimeLogs.clear()
        wait(40)
    }

    function control(name) {
        var item = findChild(monitor, name)
        verify(item !== null, name + " must exist")
        return item
    }

    function test_log_drawer_defaults_collapsed_and_restores_queue_space() {
        var log = control("taskRuntimeLogList")
        var toggle = control("taskLogToggleButton")
        compare(log.visible, false)
        compare(toggle.checked, false)
        var queue = control("taskQueueList")
        var closedHeight = queue.height
        verify(closedHeight > monitor.height * 0.5)
        runtimeLogs.append({timestamp: "2026-10-06T00:00:00Z", localTime: "08:00:00",
                           level: "error", message: "<b>untrusted</b>", stepCode: "submit_verified"})
        mouseClick(toggle, toggle.width / 2, toggle.height / 2)
        tryCompare(log, "visible", true)
        tryVerify(function() { return queue.height < closedHeight })
        compare(control("taskLogMessage-0").text, "<b>untrusted</b>")
        compare(control("taskLogMessage-0").textFormat, Text.PlainText)
        verify(control("taskExportResultsButton").enabled)
        verify(control("taskExportDiagnosticsButton").enabled)
        mouseClick(toggle, toggle.width / 2, toggle.height / 2)
        tryCompare(log, "visible", false)
        tryCompare(queue, "height", closedHeight)
        compare(runtimeLogs.count, 1)
    }

    function test_queue_40px_rows_and_scrolling_share_header_columns() {
        for (var i = 0; i < 80; ++i)
            taskItems.append({target: "<b>mock_" + i + "</b>", detail: "Inert fixture",
                              result: "pending", duration: "--", stepCode: "", itemId: "item_" + i, sourceRow: i + 1})
        wait(80)
        var queue = control("taskQueueList")
        compare(control("taskQueueHeader").height, 40)
        compare(control("taskQueueRow-0").height, 40)
        verify(queue.contentHeight > queue.height)
        compare(control("taskQueueSurface").color.a, 1)
        compare(control("taskQueueRow-0").color.a, 1)
        compare(control("taskQueueTarget-0").textFormat, Text.PlainText)
        monitorWindow.width = 640
        wait(80)
        var scroll = control("taskQueueScroll")
        verify(scroll.contentWidth > scroll.width)
        var verticalBar = control("taskQueueVerticalScrollBar")
        var barLeft = verticalBar.mapToItem(scroll, 0, 0).x
        verify(barLeft >= 0 && barLeft + verticalBar.width <= scroll.width,
               "vertical scrolling must be reachable before horizontal scrolling")
        scroll.contentX = scroll.contentWidth - scroll.width
        wait(50)
        verify(scroll.contentX > 0)
        fuzzyCompare(verticalBar.mapToItem(scroll, 0, 0).x, barLeft, 0.5)
        compare(control("taskQueueHeader").width, control("taskQueueRow-0").width)
        var resultLabel = control("taskQueueResult-0")
        var resultHeader = control("taskQueueResultHeader")
        fuzzyCompare(resultLabel.mapToItem(monitor, 0, 0).x, resultHeader.mapToItem(monitor, 0, 0).x, 1)
    }

    function test_unknown_outcome_guards_even_a_stale_retry_callback() {
        taskBackend.safeRetryAvailable = true
        var retry = control("taskSafeRetryButton")
        compare(retry.visible, false)
        retry.clicked()
        compare(taskBackend.retryCalls, 0)
        taskBackend.currentOutcome = "error"
        taskBackend.cleanupFailed = true
        retry.clicked()
        compare(taskBackend.retryCalls, 0)
        taskBackend.cleanupFailed = false
        tryCompare(retry, "visible", true)
        retry.clicked()
        compare(taskBackend.retryCalls, 1)
        taskBackend.active = true
        retry.clicked()
        compare(taskBackend.retryCalls, 1)
    }

    function test_multiline_queue_target_stays_inside_40px_row() {
        taskItems.append({target: "First line\nSecond line\nThird line", detail: "Status\nDetail\nMore detail",
                          result: "pending", duration: "--", stepCode: "", itemId: "multiline", sourceRow: 1})
        wait(50)
        compare(control("taskQueueTarget-0").lineCount, 1)
        compare(control("taskQueueDetail-0").lineCount, 1)
        compare(control("taskQueueRow-0").height, 40)
        compare(control("taskQueueTarget-0").Accessible.name, "First line\nSecond line\nThird line")
    }

    function test_pause_resume_and_stop_recheck_the_current_phase() {
        var pause = control("taskPauseButton")
        var stop = control("taskStopButton")
        pause.clicked()
        stop.clicked()
        compare(taskBackend.pauseCalls, 0)
        compare(taskBackend.resumeCalls, 0)
        compare(taskBackend.stopCalls, 0)
        taskBackend.active = true
        taskBackend.phase = "running"
        pause.clicked()
        compare(taskBackend.pauseCalls, 1)
        taskBackend.phase = "paused"
        pause.clicked()
        compare(taskBackend.resumeCalls, 1)
        taskBackend.phase = "pausing"
        pause.clicked()
        compare(taskBackend.pauseCalls, 1)
        stop.clicked()
        compare(taskBackend.stopCalls, 1)
    }

    function test_risk_stop_locates_original_row_without_replay() {
        for (var i = 0; i < 80; ++i)
            taskItems.append({target: "mock_" + i, detail: "Risk fixture", result: "stopped",
                              duration: "--", stepCode: "", itemId: "risk_" + i, sourceRow: 101 + i})
        taskBackend.riskStopItemId = "risk_70"
        taskBackend.riskStopKind = "friend_frequency"
        taskBackend.riskStopLabel = "Stopped at original row 171"
        taskBackend.executionStateChanged()
        tryCompare(control("taskQueueList"), "currentIndex", 70)
        tryVerify(function() { return control("taskQueueList").contentY > 0 })
        verify(control("taskQueueRow-70").riskStoppedRow)
        compare(control("taskRiskStopLocation").text, "Stopped at original row 171")
        compare(taskBackend.retryCalls, 0)
        compare(taskBackend.resumeCalls, 0)
    }

    function test_recovery_callback_stays_guarded_during_cleanup() {
        agentBackend.automationReady = false
        taskBackend.active = true
        var detect = control("taskDetectRecoveryButton")
        detect.clicked()
        compare(taskBackend.detectCalls, 0)
        taskBackend.active = false
        detect.clicked()
        compare(taskBackend.detectCalls, 1)
        agentBackend.automationReady = true
        detect.clicked()
        compare(taskBackend.detectCalls, 1)
    }

    function test_export_dialog_acceptance_only_forwards_to_existing_controller() {
        var results = control("taskExportResultsDialog")
        var diagnostics = control("taskExportDiagnosticsDialog")
        results.selectedFile = "file:///D:/inert-results.csv"
        results.accepted()
        compare(taskBackend.resultsUrl, "file:///D:/inert-results.csv")
        diagnostics.selectedFile = "file:///D:/inert-diagnostics.zip"
        diagnostics.accepted()
        compare(taskBackend.diagnosticsUrl, "file:///D:/inert-diagnostics.zip")
        compare(taskBackend.retryCalls, 0)
        compare(taskBackend.stopCalls, 0)
        monitor.taskBackend = null
        results.accepted()
        diagnostics.accepted()
        compare(taskBackend.resultsUrl, "file:///D:/inert-results.csv")
        compare(control("taskExportResultsButton").enabled, false)
        monitor.taskBackend = taskBackend
    }

    function test_compact_monitor_keeps_safety_status_inside_viewport_data() {
        return [
            {tag: "desktop", width: 1200, height: 800},
            {tag: "1320-with-sidebar", width: 1104, height: 800},
            {tag: "960-with-sidebar", width: 744, height: 600},
            {tag: "125-percent", width: 768, height: 544},
            {tag: "150-percent-chrome", width: 640, height: 373}
        ]
    }

    function test_compact_monitor_keeps_safety_status_inside_viewport(data) {
        monitorWindow.width = data.width
        monitorWindow.height = data.height
        taskBackend.active = true
        taskBackend.phase = "running"
        taskBackend.waitingRemaining = 3
        taskBackend.riskStopItemId = "item_1"
        taskBackend.riskStopLabel = "Risk stop at source row 2"
        taskBackend.cleanupResult = ({reasonCode: "fixture", detail: "Cleanup status"})
        taskBackend.cleanupFailed = true
        wait(80)
        for (var name of ["taskElapsedTime", "taskProgressLabel", "taskResultCounts",
                          "taskIntervalCountdown", "taskQueueList", "taskStatusSidebar",
                          "taskRiskStopLocation", "taskCleanupStatus", "taskPauseButton", "taskStopButton"]) {
            var item = control(name)
            var point = item.mapToItem(monitor, 0, 0)
            verify(item.width > 0 && item.height > 0, name + " stable dimensions")
            verify(point.x >= 0 && point.y >= 0, name + " starts inside viewport")
            verify(point.x + item.width <= monitor.width + 1, name + " fits horizontally")
            verify(point.y + item.height <= monitor.height + 1, name + " fits vertically")
        }
        verify(control("taskQueueList").height >= 70)
    }

    function test_recovery_detection_waits_for_task_cleanup_to_finish() {
        agentBackend.automationReady = false
        agentBackend.canStartTask = false
        taskBackend.active = true
        var button = buttonByText(monitor, "检测微信恢复")
        verify(button !== null)
        tryCompare(button, "visible", true)
        compare(button.enabled, false)
        taskBackend.active = false
        tryCompare(button, "enabled", true)
        agentBackend.automationReady = true
        tryCompare(button, "visible", false)
    }

    function test_task_window_health_and_countdown() {
        taskBackend.active = true
        taskBackend.phase = "running"
        taskBackend.taskWindowReady = true
        taskBackend.automationStatus = "自动化执行中"
        agentBackend.windowEnabled = false
        agentBackend.automationReady = false
        taskBackend.waitingRemaining = 2.5
        compare(findChild(monitor, "taskSessionHealth").text, "自动化执行中")
        compare(findChild(monitor, "taskWindowHealth").text, "任务窗口正常")
        compare(findChild(monitor, "taskIntervalCountdown").text, "下一条将在 3 秒后开始 · 本批间隔 1–5 秒")
        compare(buttonByText(monitor, "检测微信恢复").visible, false)
        taskBackend.phase = "paused"
        compare(findChild(monitor, "taskIntervalCountdown").text, "已暂停 · 本批间隔 1–5 秒")
        taskBackend.active = false
        taskBackend.taskWindowReady = false
        taskBackend.automationStatus = ""
        taskBackend.waitingRemaining = 0
        agentBackend.windowEnabled = true
        agentBackend.automationReady = true
    }

    function test_unknown_result_has_no_retry_button_after_environment_recovers() {
        agentBackend.automationReady = false
        agentBackend.canStartTask = false
        var retry = buttonByText(monitor, "安全重试本条")
        verify(retry !== null)
        compare(retry.visible, false)
        agentBackend.automationReady = true
        agentBackend.canStartTask = true
        compare(retry.visible, false)
        compare(taskBackend.unknownCount, 1)
    }

    function test_stopped_row_does_not_display_waiting() {
        taskItems.append({target: "mock_only", detail: "未执行：任务已结束",
                          result: "stopped", duration: "--", stepCode: "", itemId: "one", sourceRow: 8})
        tryVerify(function() { return hasText(monitor, "已停止") })
        verify(!hasText(monitor, "等待中"))
        taskItems.clear()
    }

    function test_both_task_kinds_keep_final_elapsed_and_actual_interval() {
        taskBackend.active = false
        taskBackend.elapsedLabel = "01:02:03"
        for (var kind of ["message_send", "friend_add"]) {
            monitor.taskKind = kind
            compare(findChild(monitor, "taskElapsedTime").text, "累计耗时 01:02:03")
            verify(findChild(monitor, "taskIntervalCountdown").text.indexOf("本批间隔 1–5 秒") >= 0)
        }
        monitor.taskKind = "friend_add"
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
