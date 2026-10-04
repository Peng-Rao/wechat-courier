import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtCore
import "../theme"

Rectangle {
    id: root

    property var panelBackend: null

    // 统计数据
    property int successCount: 0
    property int failureCount: 0
    property int elapsedTime: 0

    color: WxTheme.clSurface

    // 格式化时间辅助函数
    function formatTime(secs) {
        var m = Math.floor(secs / 60)
        var s = secs % 60
        return m.toString().padStart(2, "0") + ":" + s.toString().padStart(2, "0")
    }

    Timer {
        id: elapsedTimer
        interval: 1000
        repeat: true
        onTriggered: root.elapsedTime += 1
    }

    // ── 日志数据模型 ──
    ListModel {
        id: logModelList
    }

    // ── 监听 backend 的 logEntryAdded 信号 ──
    Connections {
        target: panelBackend
        ignoreUnknownSignals: true

        function onLogEntryAdded(friend, greeting, status, detail) {
            var now = new Date()
            var ts = now.getHours().toString().padStart(2, "0") + ":"
                   + now.getMinutes().toString().padStart(2, "0") + ":"
                   + now.getSeconds().toString().padStart(2, "0")
            logModelList.append({
                "friendName": friend,
                "status": status,
                "detail": detail,
                "timestamp": ts
            })

            if (status === "success") {
                root.successCount += 1
            } else if (status === "error") {
                root.failureCount += 1
            }
        }
    }

    // ── 监听 backend 的 phase 变化 ──
    Connections {
        target: panelBackend
        ignoreUnknownSignals: true

        function onPhaseChanged(phase) {
            if (phase === "idle") {
                logModelList.clear()
                root.successCount = 0
                root.failureCount = 0
                root.elapsedTime = 0
                elapsedTimer.stop()
            } else if (phase === "running") {
                elapsedTimer.start()
            } else if (phase === "paused") {
                elapsedTimer.stop()
            } else if (phase === "done") {
                elapsedTimer.stop()
            }
        }
    }

    // ── 日志导出对话框 ──
    FileDialog {
        id: exportFileDialog
        title: "选择日志导出路径"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Text files (*.txt)"]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: {
            if (panelBackend) {
                var logLines = []
                logLines.push("=== 福格微信助手发送日志 ===")
                logLines.push("任务完成状态: " + (panelBackend.progressStatus.indexOf("停止") === -1 && panelBackend.progressStatus.indexOf("错误") === -1 ? "全部完成" : "用户中止/未完成"))
                logLines.push("成功数: " + root.successCount + " 人")
                logLines.push("失败数: " + root.failureCount + " 人")
                logLines.push("总耗时: " + root.formatTime(root.elapsedTime))
                logLines.push("附加文件: " + (panelBackend ? panelBackend.filePaths.join(", ") : "无"))
                logLines.push("--------------------------------")
                for (var i = 0; i < logModelList.count; i++) {
                    var item = logModelList.get(i)
                    logLines.push("[" + item.timestamp + "] 好友: " + item.friendName + " | 状态: " + (item.status === "success" ? "成功" : "失败") + " | 详情: " + item.detail)
                }
                var formattedLogs = logLines.join("\n")

                var success = panelBackend.export_logs(exportFileDialog.selectedFile.toString(), formattedLogs)
                if (success) {
                    panelBackend.showToast("日志导出成功！", "success")
                } else {
                    panelBackend.showToast("日志导出失败！", "error")
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── 顶部统计行 (36px) ──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            color: WxTheme.clSurfaceStrong

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: WxTheme.spLarge
                anchors.rightMargin: WxTheme.spLarge
                spacing: WxTheme.spLarge

                // 成功数
                RowLayout {
                    spacing: 4
                    WxIcon {
                        iconSource: "../icons/success.svg"
                        iconSize: 14
                        hoverScale: false
                    }
                    Text {
                        text: root.successCount + " 人成功"
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        color: WxTheme.clLogOk
                    }
                }

                // 失败数
                RowLayout {
                    spacing: 4
                    WxIcon {
                        iconSource: "../icons/error.svg"
                        iconSize: 14
                        hoverScale: false
                    }
                    Text {
                        text: root.failureCount + " 人失败"
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        color: root.failureCount > 0 ? WxTheme.clLogErr : WxTheme.clTextHint
                    }
                }

                // 耗时
                RowLayout {
                    spacing: 4
                    WxIcon {
                        iconSource: "../icons/clock.svg"
                        iconSize: 14
                        hoverScale: false
                    }
                    Text {
                        text: root.formatTime(root.elapsedTime)
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        color: WxTheme.clTextSecondary
                    }
                }

                Item { Layout.fillWidth: true }

                // 进度百分比
                Text {
                    text: (panelBackend ? panelBackend.progressValue : 0) + "%"
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    font.bold: true
                    color: WxTheme.clPrimary
                }
            }
        }

        // ── 进度条 (4px) ──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 4
            color: WxTheme.clProgressTrack

            Rectangle {
                height: parent.height
                width: parent.width * (panelBackend ? panelBackend.progressValue / 100.0 : 0)
                color: WxTheme.clPrimary
                radius: 2

                Behavior on width {
                    NumberAnimation {
                        duration: WxTheme.animProgress
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }

        // ── 日志列表 ──
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: WxTheme.clSurface
            clip: true

            EmptyState {
                anchors.centerIn: parent
                visible: logListView.count === 0
                Layout.preferredHeight: 120
                iconSource: "../icons/logs_empty.svg"
                title: "暂无实时日志"
                subtitle: "发送任务启动后将在此实时输出进度详情"
            }

            ListView {
                id: logListView
                anchors.fill: parent
                anchors.margins: WxTheme.spSmall
                clip: true
                model: logModelList
                spacing: 4
                visible: count > 0

                onCountChanged: {
                    if (logModelList.count > 0) {
                        positionViewAtEnd()
                    }
                }

                delegate: LogItem {
                    width: logListView.width
                    friendName: model.friendName || ""
                    status: model.status || "success"
                    detail: model.detail || ""
                    timestamp: model.timestamp || ""
                    itemBackend: root.panelBackend
                }
            }
        }

        // ── 完成摘要（仅 done 阶段）──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: panelBackend && panelBackend.phase === "done" ? 44 : 0
            visible: panelBackend && panelBackend.phase === "done"
            color: WxTheme.clSurfaceStrong
            border.width: 1
            border.color: WxTheme.clGlassDivider

            Behavior on Layout.preferredHeight {
                NumberAnimation { duration: WxTheme.animSlow; easing.type: Easing.OutCubic }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: WxTheme.spLarge
                anchors.rightMargin: WxTheme.spLarge
                spacing: WxTheme.spMedium

                Text {
                    text: "已完成  发送 " + (root.successCount + root.failureCount) + " 人，成功 " + root.successCount + " / 失败 " + root.failureCount
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    color: WxTheme.clTextSecondary
                }

                Item { Layout.fillWidth: true }

                Button {
                    id: exportBtn
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    implicitHeight: 28
                    implicitWidth: 84

                    contentItem: RowLayout {
                        anchors.centerIn: parent
                        spacing: 4
                        WxIcon {
                            iconSource: "../icons/export.svg"
                            iconSize: 14
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Text {
                            text: "导出日志"
                            font: exportBtn.font
                            color: WxTheme.clTextPrimary
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }

                    background: Rectangle {
                        radius: WxTheme.radiusSmall
                        color: exportBtn.pressed ? WxTheme.clGlassDivider : (exportBtn.hovered ? WxTheme.clBgHover : "transparent")
                        border.width: 1
                        border.color: WxTheme.clBorder
                    }

                    onClicked: exportFileDialog.open()
                }
            }
        }
    }
}
