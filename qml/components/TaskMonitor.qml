import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "taskMonitor"
    property var taskBackend: null
    property var agentBackend: null
    property string taskKind: "message_send"
    property bool logsExpanded: false
    signal requestEdit()
    readonly property bool friendPreflightMode: taskKind === "friend_add"
        && taskBackend && taskBackend.acceptanceEnabled
    readonly property bool canSafeRetry: !!(taskBackend && taskBackend.safeRetryAvailable
        && !taskBackend.active && !taskBackend.cleanupFailed && taskBackend.currentOutcome !== "unknown")
    readonly property bool canDetectRecovery: !!(taskBackend && agentBackend
        && !agentBackend.automationReady && !taskBackend.taskWindowReady && !taskBackend.active)
    readonly property var messageSteps: [
        ["window_bound", "已绑定微信窗口"], ["search_ready", "搜索入口已就绪"],
        ["target_selected", "已选择目标"], ["target_verified", "目标校验通过"],
        ["composer_ready", "输入框已就绪"], ["content_inserted", "内容已写入"],
        ["send_triggered", "已触发发送"], ["send_verified", "发送结果已确认"]
    ]
    readonly property var friendSteps: friendPreflightMode ? [
        ["window_bound", "已绑定微信窗口"], ["add_friend_window_ready", "添加好友窗口已就绪"],
        ["account_inserted", "账号已写入"], ["account_searched", "已搜索账号"],
        ["profile_verified", "资料核对通过"], ["request_form_ready", "申请窗口已就绪"],
        ["fields_verified", "申请内容已核对"], ["preflight_completed", "表单预检已完成"]
    ] : [
        ["window_bound", "已绑定微信窗口"], ["add_friend_window_ready", "添加好友窗口已就绪"],
        ["account_inserted", "账号已写入"], ["account_searched", "已搜索账号"],
        ["profile_verified", "资料核对通过"], ["request_form_ready", "申请窗口已就绪"],
        ["fields_verified", "申请内容已核对"], ["submit_triggered", "已点击确定"],
        ["submit_verified", "提交结果已确认"]
    ]
    readonly property var steps: taskKind === "message_send" ? messageSteps : friendSteps

    function stepIndex(code) {
        for (var i = 0; i < steps.length; ++i) {
            if (steps[i][0] === code) return i
        }
        return -1
    }

    function locateRiskStop() {
        if (!root.taskBackend || !root.taskBackend.riskStopItemId) return
        var items = root.taskBackend.items
        if (!items || typeof items.indexOfItem !== "function") return
        var row = items.indexOfItem(root.taskBackend.riskStopItemId)
        if (row >= 0) Qt.callLater(function() {
            queueList.currentIndex = row
            queueList.positionViewAtIndex(row, ListView.Contain)
        })
    }

    Connections {
        target: root.taskBackend
        ignoreUnknownSignals: true
        function onExecutionStateChanged() { root.locateRiskStop() }
    }
    Component.onCompleted: locateRiskStop()

    Rectangle { anchors.fill: parent; color: WxTheme.clBgPrimary }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: WxTheme.clBgPrimary
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16; anchors.rightMargin: 16
                spacing: 12
                Text {
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    text: taskKind === "message_send" ? "发送队列"
                        : root.friendPreflightMode ? "好友表单预检队列" : "好友申请队列"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeTitle; font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    objectName: "taskElapsedTime"
                    Accessible.role: Accessible.StaticText; Accessible.name: text
                    text: "累计耗时 " + (root.taskBackend && root.taskBackend.elapsedLabel ? root.taskBackend.elapsedLabel : "00:00:00")
                    textFormat: Text.PlainText
                    color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal; font.bold: true
                }
                WxButton {
                    objectName: "taskReturnToEditorButton"
                    Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled ? "taskReturnToEditorButton" : text
                    text: "返回编辑"
                    visible: !!(root.taskBackend && !root.taskBackend.active)
                    onClicked: if (root.taskBackend && !root.taskBackend.active) root.requestEdit()
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 64
            color: WxTheme.clBgPrimary
            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 16; anchors.rightMargin: 16
                anchors.topMargin: 4; anchors.bottomMargin: 8
                spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        objectName: "taskProgressLabel"
                        Accessible.role: Accessible.StaticText; Accessible.name: text
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        text: "处理进度 · 已处理 " + (root.taskBackend ? root.taskBackend.done + " / " + root.taskBackend.total : "0 / 0")
                        textFormat: Text.PlainText
                        color: WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        objectName: "taskProgressPercent"
                        text: root.taskBackend ? Math.round(root.taskBackend.progress * 100) + "%" : "0%"
                        textFormat: Text.PlainText
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; font.bold: true
                    }
                }
                Rectangle {
                    objectName: "taskProgressTrack"
                    Layout.fillWidth: true; Layout.preferredHeight: 4
                    color: WxTheme.clProgressTrack
                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(1, root.taskBackend ? root.taskBackend.progress : 0))
                        height: parent.height; color: WxTheme.clPrimary
                        Behavior on width { NumberAnimation { duration: WxTheme.animProgress } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Text {
                        objectName: "taskResultCounts"
                        Accessible.role: Accessible.StaticText; Accessible.name: text
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        text: root.taskBackend ? "成功 " + root.taskBackend.successCount
                            + " · 失败 " + root.taskBackend.failureCount + " · 未知 " + root.taskBackend.unknownCount
                            + (root.taskBackend.active ? " · 剩余 " : " · 未执行 ")
                            + Math.max(0, root.taskBackend.total - root.taskBackend.done) : "等待任务"
                        textFormat: Text.PlainText
                        color: WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        objectName: "taskIntervalCountdown"
                        Accessible.role: Accessible.StaticText; Accessible.name: text
                        Layout.preferredWidth: Math.min(400, root.width * 0.48); Layout.minimumWidth: 0
                        text: root.taskBackend && root.taskBackend.active
                            ? (root.taskBackend.phase === "paused" ? "已暂停"
                                : root.taskBackend.phase === "pausing" ? "正在安全暂停"
                                : root.taskBackend.phase === "stopping" ? "正在安全停止"
                                : root.taskBackend.waitingRemaining > 0
                                    ? "下一条将在 " + Math.ceil(root.taskBackend.waitingRemaining) + " 秒后开始" : "正在处理当前项目")
                                + (root.taskBackend.intervalLabel ? " · " + root.taskBackend.intervalLabel : "")
                            : "任务已结束" + (root.taskBackend && root.taskBackend.intervalLabel ? " · " + root.taskBackend.intervalLabel : "")
                        textFormat: Text.PlainText
                        color: root.taskBackend && root.taskBackend.active ? WxTheme.clTextPrimary : WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; font.bold: true
                        elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
                    }
                }
            }
        }
        Rectangle {
            visible: !!(root.taskBackend && root.taskBackend.riskStopItemId)
            Layout.fillWidth: true; Layout.preferredHeight: visible ? riskStopText.implicitHeight + 12 : 0
            color: WxTheme.clDangerSoft
            Text {
                id: riskStopText
                objectName: "taskRiskStopLocation"
                Accessible.role: Accessible.StaticText; Accessible.name: text
                anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 16; anchors.verticalCenter: parent.verticalCenter
                text: root.taskBackend && root.taskBackend.riskStopLabel ? root.taskBackend.riskStopLabel : ""
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: WxTheme.clDangerNew
                font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; font.bold: true
            }
        }
        Rectangle {
            visible: !!(root.taskBackend && Object.keys(root.taskBackend.cleanupResult).length > 0)
            Layout.fillWidth: true; Layout.preferredHeight: visible ? cleanupText.implicitHeight + 12 : 0
            color: root.taskBackend && root.taskBackend.cleanupFailed ? WxTheme.clWarningSoft : WxTheme.clBgSecondary
            Text {
                id: cleanupText
                objectName: "taskCleanupStatus"
                Accessible.role: Accessible.StaticText; Accessible.name: text
                anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 16; anchors.verticalCenter: parent.verticalCenter
                text: root.taskBackend ? (root.taskBackend.cleanupFailed ? "任务清理失败" : "任务清理完成")
                    + (root.taskBackend.cleanupResult.reasonCode ? " · " + root.taskBackend.cleanupResult.reasonCode : "")
                    + (root.taskBackend.cleanupResult.detail ? "：" + root.taskBackend.cleanupResult.detail : "") : ""
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: root.taskBackend && root.taskBackend.cleanupFailed ? WxTheme.clWarningText : WxTheme.clTextSecondary
                font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
            }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
            spacing: 0
            Rectangle {
                objectName: "taskQueueSurface"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 0; Layout.minimumHeight: 0
                color: WxTheme.clBgPrimary
                ColumnLayout {
                    anchors.fill: parent; spacing: 0
                    // A common horizontal viewport keeps header and virtualized rows aligned.
                    Flickable {
                        id: queueScroll
                        objectName: "taskQueueScroll"
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
                        contentWidth: Math.max(width, 600); contentHeight: height
                        flickableDirection: Flickable.HorizontalFlick
                        boundsBehavior: Flickable.StopAtBounds; clip: true
                        ScrollBar.horizontal: WxScrollBar {
                            id: queueHorizontalBar
                            objectName: "taskQueueHorizontalScrollBar"
                            policy: ScrollBar.AsNeeded
                        }
                        ColumnLayout {
                            width: queueScroll.contentWidth
                            height: queueScroll.height - (queueHorizontalBar.visible ? 10 : 0)
                            spacing: 0
                            Rectangle {
                                objectName: "taskQueueHeader"
                                Layout.fillWidth: true; Layout.preferredHeight: 40
                                color: WxTheme.clBgSecondary; border.color: WxTheme.clSurfaceBorder
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                    Text { text: "原序号"; textFormat: Text.PlainText; Layout.preferredWidth: 54; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                    Text { text: taskKind === "message_send" ? "好友" : "账号"; textFormat: Text.PlainText; Layout.preferredWidth: 164; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                    Text { text: "当前状态"; textFormat: Text.PlainText; Layout.fillWidth: true; Layout.minimumWidth: 0; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                    Text { objectName: "taskQueueResultHeader"; text: "结果"; textFormat: Text.PlainText; Layout.preferredWidth: 82; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                    Text { text: "耗时"; textFormat: Text.PlainText; Layout.preferredWidth: 64; horizontalAlignment: Text.AlignRight; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                }
                            }
                            ListView {
                                id: queueList
                                objectName: "taskQueueList"
                                Accessible.name: "任务队列"
                                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
                                model: root.taskBackend ? root.taskBackend.items : null
                                clip: true; boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: WxScrollBar {
                                    objectName: "taskQueueVerticalScrollBar"
                                    parent: queueScroll
                                    x: queueScroll.width - width
                                    y: 40
                                    height: queueList.height
                                    z: 2
                                    policy: ScrollBar.AsNeeded
                                }
                                delegate: Rectangle {
                                    id: queueRow
                                    required property int index
                                    required property string itemId
                                    required property int sourceRow
                                    required property string target
                                    required property string detail
                                    required property string result
                                    required property string duration
                                    required property string stepCode
                                    readonly property bool riskStoppedRow: !!(root.taskBackend && root.taskBackend.riskStopItemId === itemId)
                                    objectName: "taskQueueRow-" + index
                                    width: queueList.width; height: 40
                                    color: riskStoppedRow || result === "error" ? WxTheme.clDangerSoft
                                        : result === "unknown" ? WxTheme.clWarningSoft : result === "working" ? WxTheme.clBgSelected
                                        : index % 2 ? WxTheme.clBgSecondary : WxTheme.clBgPrimary
                                    Rectangle { width: 3; height: parent.height; visible: queueRow.riskStoppedRow || queueRow.result === "working"; color: queueRow.riskStoppedRow ? WxTheme.clDangerNew : WxTheme.clPrimary }
                                    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: WxTheme.clSurfaceBorder }
                                    RowLayout {
                                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                        Text {
                                            text: String(queueRow.sourceRow > 0 ? queueRow.sourceRow : queueRow.index + 1).padStart(2, "0")
                                            textFormat: Text.PlainText; Layout.preferredWidth: 54
                                            color: queueRow.riskStoppedRow ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal; elide: Text.ElideRight
                                            maximumLineCount: 1
                                        }
                                        Text {
                                            objectName: "taskQueueTarget-" + queueRow.index
                                            Accessible.role: Accessible.StaticText; Accessible.name: text
                                            text: queueRow.target; textFormat: Text.PlainText; Layout.preferredWidth: 164
                                            elide: Text.ElideRight; color: WxTheme.clTextPrimary
                                            maximumLineCount: 1
                                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal
                                        }
                                        Text {
                                            objectName: "taskQueueDetail-" + queueRow.index
                                            Accessible.role: Accessible.StaticText; Accessible.name: text
                                            text: (queueRow.result === "error" || queueRow.result === "unknown") && root.taskBackend
                                                ? root.taskBackend.stepLabel(queueRow.stepCode, queueRow.result) + (queueRow.detail ? "：" + queueRow.detail : "") : queueRow.detail
                                            textFormat: Text.PlainText; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight
                                            maximumLineCount: 1
                                            color: queueRow.result === "error" ? WxTheme.clDangerNew : queueRow.result === "unknown" ? WxTheme.clWarningText : WxTheme.clTextSecondary
                                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal
                                        }
                                        Rectangle {
                                            objectName: "taskQueueResult-" + queueRow.index
                                            Layout.preferredWidth: 82; Layout.preferredHeight: 24; radius: 4
                                            color: queueRow.result === "success" ? WxTheme.clSuccessSoft
                                                : queueRow.result === "error" ? WxTheme.clDangerSoft : queueRow.result === "unknown" ? WxTheme.clWarningSoft
                                                : queueRow.result === "working" ? WxTheme.clInfoSoft : WxTheme.clNeutralSoft
                                            Text {
                                                anchors.centerIn: parent
                                                text: queueRow.riskStoppedRow ? (root.taskBackend.riskStopKind === "friend_frequency" ? "频繁限制" : "风控停止")
                                                    : queueRow.result === "success" ? (taskKind === "friend_add" ? (root.friendPreflightMode ? "预检完成" : "已提交") : "成功")
                                                    : queueRow.result === "error" ? "异常" : queueRow.result === "unknown" ? "结果未知"
                                                    : queueRow.result === "working" ? "执行中" : queueRow.result === "stopped" ? "已停止" : "等待中"
                                                textFormat: Text.PlainText
                                                color: queueRow.result === "success" ? WxTheme.clSuccessText
                                                    : queueRow.result === "error" ? WxTheme.clDangerNew : queueRow.result === "unknown" ? WxTheme.clWarningText
                                                    : queueRow.result === "working" ? WxTheme.clInfo : WxTheme.clTextSecondary
                                                font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; font.bold: true
                                            }
                                        }
                                        Text {
                                            text: queueRow.duration; textFormat: Text.PlainText; Layout.preferredWidth: 64
                                            color: WxTheme.clTextSecondary
                                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                                            horizontalAlignment: Text.AlignRight; elide: Text.ElideRight
                                            maximumLineCount: 1
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 40
                        color: WxTheme.clBgPrimary; border.color: WxTheme.clSurfaceBorder
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 4
                            WxButton {
                                objectName: "taskLogToggleButton"
                                Accessible.name: "运行日志"
                                text: "运行日志"; iconName: "arrow_down"; quiet: true
                                checkable: true; checked: root.logsExpanded
                                onClicked: root.logsExpanded = !root.logsExpanded
                            }
                            Text { text: String(runtimeLogList.count); textFormat: Text.PlainText; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                            WxButton {
                                objectName: "taskExportDiagnosticsButton"
                                Accessible.name: "导出脱敏诊断包"
                                iconName: "file"; tooltipText: "导出脱敏诊断包"; quiet: true
                                enabled: !!root.taskBackend
                                onClicked: if (root.taskBackend) diagnosticsDialog.open()
                            }
                            WxButton {
                                objectName: "taskExportResultsButton"
                                Accessible.name: "导出任务结果"
                                iconName: "export"; tooltipText: "导出任务结果"; quiet: true
                                enabled: !!root.taskBackend
                                onClicked: if (root.taskBackend) exportDialog.open()
                            }
                        }
                    }
                    ListView {
                        id: runtimeLogList
                        objectName: "taskRuntimeLogList"
                        Accessible.name: "运行日志"
                        visible: root.logsExpanded
                        Layout.fillWidth: true; Layout.preferredHeight: visible ? Math.min(156, root.height * 0.2) : 0
                        model: root.taskBackend ? root.taskBackend.runtimeLogs : null
                        clip: true
                        ScrollBar.vertical: WxScrollBar { objectName: "taskLogScrollBar"; policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            id: logRow
                            required property int index
                            required property string timestamp
                            required property string localTime
                            required property string level
                            required property string message
                            required property string stepCode
                            width: runtimeLogList.width; height: logMessage.implicitHeight + 14
                            color: WxTheme.clBgPrimary
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10
                                Text { text: logRow.localTime; textFormat: Text.PlainText; Layout.preferredWidth: 62; Layout.alignment: Qt.AlignTop; topPadding: 7; color: WxTheme.clTextHint; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                Text { text: logRow.level === "error" ? "异常" : logRow.level === "warning" ? "警告" : "状态"; textFormat: Text.PlainText; Layout.preferredWidth: 32; Layout.alignment: Qt.AlignTop; topPadding: 7; color: logRow.level === "error" ? WxTheme.clDangerNew : logRow.level === "warning" ? WxTheme.clWarningText : WxTheme.clSuccessText; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                Text {
                                    id: logMessage
                                    objectName: "taskLogMessage-" + logRow.index
                                    Accessible.role: Accessible.StaticText; Accessible.name: text
                                    text: logRow.message; textFormat: Text.PlainText
                                    Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                                }
                            }
                        }
                    }
                }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: WxTheme.clSurfaceBorder }
            Rectangle {
                objectName: "taskStatusSidebar"
                Layout.preferredWidth: 220; Layout.minimumWidth: 220; Layout.maximumWidth: 220; Layout.fillHeight: true
                color: WxTheme.clBgSecondary
                ScrollView {
                    id: statusScroll
                    objectName: "taskStatusScroll"
                    anchors.fill: parent; anchors.margins: 12
                    contentWidth: availableWidth
                    ScrollBar.horizontal: WxScrollBar { policy: ScrollBar.AlwaysOff }
                    ScrollBar.vertical: WxScrollBar { policy: ScrollBar.AsNeeded }
                    ColumnLayout {
                        width: statusScroll.availableWidth; spacing: 12
                        Text {
                            Layout.fillWidth: true
                            text: taskKind === "message_send" ? "消息发送状态" : root.friendPreflightMode ? "好友表单预检状态" : "好友申请状态"
                            textFormat: Text.PlainText; color: WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal; font.bold: true
                            elide: Text.ElideRight
                        }
                        ListView {
                            id: stepList
                            objectName: "taskStepList"
                            Layout.fillWidth: true; Layout.preferredHeight: contentHeight
                            interactive: false; model: root.steps
                            delegate: Item {
                                required property int index
                                required property var modelData
                                width: stepList.width; height: 38
                                readonly property int activeIndex: root.stepIndex(root.taskBackend ? root.taskBackend.currentStepCode : "")
                                readonly property bool completed: activeIndex >= 0 && index < activeIndex
                                readonly property bool activeStep: index === activeIndex
                                readonly property bool failedStep: activeStep && root.taskBackend
                                    && (root.taskBackend.currentOutcome === "error" || root.taskBackend.currentOutcome === "unknown")
                                Rectangle {
                                    objectName: "taskStepConnector-" + index
                                    x: 5; y: stepNode.y + stepNode.height / 2; width: 1; height: parent.height
                                    visible: index < root.steps.length - 1
                                    color: completed ? WxTheme.clSuccessText : WxTheme.clSurfaceBorder
                                }
                                Rectangle {
                                    id: stepNode
                                    objectName: "taskStepNode-" + index
                                    x: 0; y: 10; width: 11; height: 11; radius: 6
                                    color: completed ? WxTheme.clSuccessText : failedStep ? WxTheme.clDangerNew : activeStep ? WxTheme.clPrimary : WxTheme.clBgSecondary
                                    border.width: activeStep || !completed ? 2 : 0
                                    border.color: failedStep ? WxTheme.clDangerNew : activeStep ? WxTheme.clPrimary : WxTheme.clTextHint
                                }
                                Text {
                                    anchors.left: parent.left; anchors.leftMargin: 24; anchors.verticalCenter: parent.verticalCenter; anchors.right: parent.right
                                    text: failedStep ? root.taskBackend.currentStepLabel : modelData[1]
                                    textFormat: Text.PlainText
                                    Accessible.role: Accessible.StaticText; Accessible.name: text
                                    elide: Text.ElideRight
                                    maximumLineCount: 1
                                    color: failedStep ? WxTheme.clDangerNew : activeStep || completed ? WxTheme.clTextPrimary : WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; font.bold: activeStep
                                }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: WxTheme.clSurfaceBorder }
                        GridLayout {
                            Layout.fillWidth: true; columns: 2; columnSpacing: 8; rowSpacing: 8
                            Text { text: "Agent 进程"; textFormat: Text.PlainText; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            Text { text: root.agentBackend && root.agentBackend.connected ? "响应正常" : "未连接"; textFormat: Text.PlainText; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight; color: WxTheme.clTextPrimary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            Text { text: "自动化会话"; textFormat: Text.PlainText; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            Text {
                                objectName: "taskSessionHealth"
                                Accessible.role: Accessible.StaticText; Accessible.name: text
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: root.taskBackend && root.taskBackend.automationStatus ? root.taskBackend.automationStatus
                                    : root.agentBackend && root.agentBackend.automationReady ? "已就绪 · 第 " + root.agentBackend.sessionGeneration + " 代"
                                    : root.agentBackend && root.agentBackend.canStartTask ? "会话待恢复" : "未就绪"
                                textFormat: Text.PlainText; color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                                horizontalAlignment: Text.AlignRight; wrapMode: Text.Wrap
                            }
                            Text { text: "微信窗口"; textFormat: Text.PlainText; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            Text {
                                objectName: "taskWindowHealth"
                                Accessible.role: Accessible.StaticText; Accessible.name: text
                                Layout.fillWidth: true; Layout.minimumWidth: 0
                                text: !root.agentBackend || !root.agentBackend.processDetected ? "未连接"
                                    : !root.agentBackend.windowResponsive ? "无响应" : root.taskBackend && root.taskBackend.taskWindowReady ? "任务窗口正常"
                                    : !root.agentBackend.windowEnabled || root.agentBackend.blockingWindow ? "被阻挡"
                                    : root.agentBackend.canStartTask && !root.agentBackend.automationReady ? "待恢复" : "响应正常"
                                textFormat: Text.PlainText
                                color: root.agentBackend && root.agentBackend.windowResponsive
                                    && ((root.taskBackend && root.taskBackend.taskWindowReady) || (root.agentBackend.windowEnabled && !root.agentBackend.blockingWindow))
                                    ? WxTheme.clTextPrimary : WxTheme.clDangerNew
                                font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                                horizontalAlignment: Text.AlignRight; wrapMode: Text.Wrap
                            }
                        }
                        Text {
                            Layout.fillWidth: true; visible: !!(root.taskBackend && root.taskBackend.retryMaxAttempts > 1)
                            text: root.taskBackend ? "重试决策 " + root.taskBackend.retryAttempt + " / " + root.taskBackend.retryMaxAttempts + " · " + root.taskBackend.retryLevel : ""
                            textFormat: Text.PlainText; color: WxTheme.clTextSecondary
                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall; wrapMode: Text.Wrap
                        }
                        Text {
                            visible: !!(root.taskBackend && root.taskBackend.recoveryHint.length > 0); Layout.fillWidth: true
                            text: root.taskBackend ? root.taskBackend.recoveryHint : ""
                            textFormat: Text.PlainText; wrapMode: Text.Wrap; color: WxTheme.clTextSecondary
                            font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall
                        }
                        WxButton {
                            objectName: "taskSafeRetryButton"
                            Accessible.name: text
                            visible: root.canSafeRetry; enabled: root.canSafeRetry; text: "安全重试本条"
                            onClicked: if (root.canSafeRetry) root.taskBackend.retryFailedItem()
                            Layout.fillWidth: true
                        }
                        WxButton {
                            objectName: "taskDetectRecoveryButton"
                            Accessible.name: text
                            visible: !!(root.taskBackend && root.agentBackend && !root.agentBackend.automationReady && !root.taskBackend.taskWindowReady)
                            text: "检测微信恢复"; enabled: root.canDetectRecovery
                            onClicked: if (root.canDetectRecovery) root.taskBackend.detectWechatRecovery()
                            Layout.fillWidth: true
                        }
                        WxButton {
                            objectName: "taskRestartWechatButton"
                            Accessible.name: text
                            visible: !!(root.taskBackend && root.taskBackend.wechatRestartAvailable)
                            enabled: !!(root.taskBackend && !root.taskBackend.active && root.taskBackend.wechatRestartAvailable)
                            text: "重启微信"
                            onClicked: if (enabled && root.taskBackend && !root.taskBackend.active && root.taskBackend.wechatRestartAvailable) root.taskBackend.restartWechatAfterFailure()
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 48
            color: WxTheme.clBgPrimary; border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; spacing: 8
                Text {
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    text: root.taskBackend && root.taskBackend.active
                        ? (taskKind === "message_send" ? "消息群发进行中" : root.friendPreflightMode ? "好友表单预检进行中" : "好友申请提交进行中")
                        : (root.taskBackend && root.taskBackend.phase === "error" ? "任务失败" : "任务已结束")
                    textFormat: Text.PlainText; color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal; font.bold: true; elide: Text.ElideRight
                }
                WxButton {
                    objectName: "taskPauseButton"
                    Accessible.name: text
                    text: root.taskBackend && root.taskBackend.phase === "paused" ? "继续" : "暂停"
                    iconName: root.taskBackend && root.taskBackend.phase === "paused" ? "play" : "pause"
                    enabled: !!(root.taskBackend && root.taskBackend.active && (root.taskBackend.phase === "running" || root.taskBackend.phase === "paused"))
                    onClicked: {
                        if (!root.taskBackend || !root.taskBackend.active) return
                        if (root.taskBackend.phase === "paused") root.taskBackend.resume()
                        else if (root.taskBackend.phase === "running") root.taskBackend.pause()
                    }
                }
                WxButton {
                    objectName: "taskStopButton"
                    Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled ? "taskStopButton" : text
                    text: "停止任务"; iconName: "stop"; danger: true
                    enabled: !!(root.taskBackend && root.taskBackend.active)
                    onClicked: if (root.taskBackend && root.taskBackend.active) root.taskBackend.stop()
                }
            }
        }
    }
    FileDialog {
        id: exportDialog
        objectName: "taskExportResultsDialog"
        title: "导出任务结果"; fileMode: FileDialog.SaveFile
        nameFilters: ["CSV 文件 (*.csv)"]; defaultSuffix: "csv"
        onAccepted: if (root.taskBackend) root.taskBackend.exportResults(selectedFile)
    }
    FileDialog {
        id: diagnosticsDialog
        objectName: "taskExportDiagnosticsDialog"
        title: "导出脱敏诊断包"; fileMode: FileDialog.SaveFile
        nameFilters: ["ZIP 压缩包 (*.zip)"]; defaultSuffix: "zip"
        onAccepted: if (root.taskBackend) root.taskBackend.exportDiagnostics(selectedFile)
    }
}
