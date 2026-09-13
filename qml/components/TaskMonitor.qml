import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    property var taskBackend: null
    property var agentBackend: null
    property string taskKind: "message_send"
    signal requestEdit()

    readonly property var messageSteps: [
        ["window_bound", "已绑定微信窗口"],
        ["search_ready", "搜索入口已就绪"],
        ["target_selected", "已选择目标"],
        ["target_verified", "目标校验通过"],
        ["composer_ready", "输入框已就绪"],
        ["content_inserted", "内容已写入"],
        ["send_triggered", "已触发发送"],
        ["send_verified", "发送结果已确认"]
    ]
    readonly property var friendSteps: [
        ["window_bound", "已绑定微信窗口"],
        ["add_friend_window_ready", "添加好友窗口已就绪"],
        ["account_inserted", "账号已写入"],
        ["account_searched", "已搜索账号"],
        ["profile_verified", "资料核对通过"],
        ["request_form_ready", "申请窗口已就绪"],
        ["fields_verified", "申请内容已核对"],
        ["submit_verified", "提交结果已确认"]
    ]
    readonly property var steps: taskKind === "message_send" ? messageSteps : friendSteps

    function stepIndex(code) {
        for (var i = 0; i < steps.length; ++i) {
            if (steps[i][0] === code) return i
        }
        return -1
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            color: WxTheme.clPanelFill
            border.color: WxTheme.clSurfaceBorder

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 14
                ColumnLayout {
                    spacing: 2
                    Text {
                        text: taskKind === "message_send" ? "发送队列" : "好友申请队列"
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTitle
                        font.bold: true
                    }
                    Text {
                        text: root.taskBackend
                            ? "已处理 " + root.taskBackend.done + " / " + root.taskBackend.total
                            : "等待任务"
                        color: WxTheme.clTextHint
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                    }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredWidth: 190
                    Layout.preferredHeight: 5
                    radius: 3
                    color: WxTheme.clProgressTrack
                    Rectangle {
                        width: parent.width * (root.taskBackend ? root.taskBackend.progress : 0)
                        height: parent.height
                        radius: parent.radius
                        color: WxTheme.clPrimary
                        Behavior on width { NumberAnimation { duration: WxTheme.animProgress } }
                    }
                }
                Text {
                    text: root.taskBackend ? Math.round(root.taskBackend.progress * 100) + "%" : "0%"
                    color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    font.bold: true
                }
                Button {
                    text: "返回编辑"
                    visible: root.taskBackend && !root.taskBackend.active
                    onClicked: root.requestEdit()
                    contentItem: Text {
                        text: parent.text
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: parent.hovered ? WxTheme.clBgHover : WxTheme.clToolbarFill
                        border.color: WxTheme.clSurfaceBorder
                        radius: WxTheme.radiusSmall
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 7

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        color: WxTheme.clToolbarFill
                        border.color: WxTheme.clSurfaceBorder
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            Text { text: "#"; Layout.preferredWidth: 32; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                            Text { text: taskKind === "message_send" ? "好友" : "账号"; Layout.preferredWidth: 190; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                            Text { text: "当前状态"; Layout.fillWidth: true; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                            Text { text: "结果"; Layout.preferredWidth: 90; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                            Text { text: "耗时"; Layout.preferredWidth: 54; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                        }
                    }

                    ListView {
                        id: queueList
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(230, contentHeight)
                        model: root.taskBackend ? root.taskBackend.items : null
                        clip: true
                        delegate: Rectangle {
                            required property int index
                            required property string target
                            required property string detail
                            required property string result
                            required property string duration
                            required property string stepCode
                            width: queueList.width
                            height: 44
                            color: result === "working" ? WxTheme.clBgSelected
                                : (result === "error" || result === "unknown"
                                    ? (WxTheme.isDark ? "#332326" : "#fff2f2") : "transparent")
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 1
                                color: WxTheme.clSurfaceBorder
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                Text {
                                    text: String(index + 1).padStart(2, "0")
                                    Layout.preferredWidth: 32
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                                Text {
                                    text: target
                                    Layout.preferredWidth: 190
                                    elide: Text.ElideRight
                                    color: WxTheme.clTextPrimary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                                Text {
                                    text: detail
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                    color: result === "error" || result === "unknown"
                                        ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                                Rectangle {
                                    Layout.preferredWidth: 82
                                    Layout.preferredHeight: 24
                                    radius: WxTheme.radiusSmall
                                    color: result === "success" ? WxTheme.clSuccessSoft
                                        : result === "error" ? WxTheme.clDangerSoft
                                        : result === "unknown" ? WxTheme.clWarningSoft
                                        : WxTheme.clNeutralSoft
                                    Text {
                                        anchors.centerIn: parent
                                        text: result === "success" ? "成功"
                                            : result === "error" ? "异常"
                                            : result === "unknown" ? "结果未知"
                                            : "等待中"
                                        color: result === "success" ? WxTheme.clSuccessText
                                            : result === "error" ? WxTheme.clDangerNew
                                            : result === "unknown" ? WxTheme.clWarningText
                                            : WxTheme.clTextSecondary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeTiny
                                        font.bold: true
                                    }
                                }
                                Text {
                                    text: duration
                                    Layout.preferredWidth: 54
                                    color: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeTiny
                                    horizontalAlignment: Text.AlignRight
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        color: WxTheme.clToolbarFill
                        border.color: WxTheme.clSurfaceBorder
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: "运行日志"
                            color: WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                        }
                        Button {
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: "导出结果"
                            onClicked: exportDialog.open()
                            contentItem: Text {
                                text: parent.text
                                color: WxTheme.clTextLink
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle { color: "transparent" }
                        }
                    }

                    ListView {
                        id: runtimeLogList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: root.taskBackend ? root.taskBackend.runtimeLogs : null
                        clip: true
                        delegate: Rectangle {
                            required property string timestamp
                            required property string level
                            required property string message
                            required property string stepCode
                            width: runtimeLogList.width
                            height: 34
                            color: "transparent"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 12
                                Text {
                                    text: timestamp.length >= 19 ? timestamp.slice(11, 19) : timestamp
                                    Layout.preferredWidth: 62
                                    color: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamilyLog
                                    font.pixelSize: WxTheme.fontSizeTiny
                                }
                                Text {
                                    text: level === "error" ? "异常" : "状态"
                                    Layout.preferredWidth: 42
                                    color: level === "error" ? WxTheme.clDangerNew : WxTheme.clInfo
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeTiny
                                    font.bold: true
                                }
                                Text {
                                    text: message
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeTiny
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                color: WxTheme.clSurfaceBorder
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 3.7
                color: WxTheme.clPanelFill

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 14
                    Text {
                        text: taskKind === "message_send" ? "消息发送状态" : "好友申请状态"
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeNormal
                        font.bold: true
                    }
                    ListView {
                        id: stepList
                        Layout.fillWidth: true
                        Layout.preferredHeight: contentHeight
                        interactive: false
                        model: root.steps
                        delegate: Item {
                            required property int index
                            required property var modelData
                            width: stepList.width
                            height: 38
                            readonly property int activeIndex: root.stepIndex(root.taskBackend ? root.taskBackend.currentStepCode : "")
                            readonly property bool completed: activeIndex >= 0 && index < activeIndex
                            readonly property bool activeStep: index === activeIndex
                            Rectangle {
                                x: 5
                                y: 0
                                width: 1
                                height: parent.height
                                visible: index < root.steps.length - 1
                                color: completed ? WxTheme.clPrimary : WxTheme.clSurfaceBorder
                            }
                            Rectangle {
                                x: 0
                                y: 10
                                width: 11
                                height: 11
                                radius: 6
                                color: completed ? WxTheme.clPrimary
                                    : activeStep ? WxTheme.clInfo : WxTheme.clPanelFill
                                border.width: activeStep || !completed ? 2 : 0
                                border.color: activeStep ? WxTheme.clInfo : WxTheme.clTextHint
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 3
                                    height: 3
                                    radius: 2
                                    visible: activeStep
                                    color: "white"
                                }
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 24
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData[1]
                                color: activeStep ? WxTheme.clInfo
                                    : completed ? WxTheme.clTextPrimary : WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: activeStep
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 104
                        color: WxTheme.clInfoSoft
                        border.color: WxTheme.clInfoBorder
                        radius: WxTheme.radiusMedium
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 5
                            RowLayout {
                                Text { text: "Agent 进程"; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                                Item { Layout.fillWidth: true }
                                Text { text: root.agentBackend && root.agentBackend.connected ? "响应正常" : "未连接"; color: WxTheme.clTextPrimary; font.pixelSize: WxTheme.fontSizeTiny; font.bold: true }
                            }
                            RowLayout {
                                Text { text: "微信版本"; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                                Item { Layout.fillWidth: true }
                                Text { text: root.agentBackend ? root.agentBackend.wechatVersion : ""; color: WxTheme.clTextPrimary; font.pixelSize: WxTheme.fontSizeTiny; font.bold: true }
                            }
                            RowLayout {
                                Text { text: "结果策略"; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeTiny }
                                Item { Layout.fillWidth: true }
                                Text { text: "未知时不重试"; color: WxTheme.clTextPrimary; font.pixelSize: WxTheme.fontSizeTiny; font.bold: true }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                ColumnLayout {
                    spacing: 1
                    Text {
                        text: root.taskBackend && root.taskBackend.active
                            ? (taskKind === "message_send" ? "消息群发进行中" : "批量加好友进行中")
                            : "任务已结束"
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        font.bold: true
                    }
                    Text {
                        text: "暂停和停止会在安全步骤生效"
                        color: WxTheme.clTextHint
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: root.taskBackend
                        ? "成功与异常结果见队列  ·  剩余 " + Math.max(0, root.taskBackend.total - root.taskBackend.done)
                        : ""
                    color: WxTheme.clTextHint
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeTiny
                }
                Button {
                    text: root.taskBackend && root.taskBackend.phase === "paused" ? "继续" : "暂停"
                    enabled: root.taskBackend && root.taskBackend.active
                    onClicked: {
                        if (root.taskBackend.phase === "paused") root.taskBackend.resume()
                        else root.taskBackend.pause()
                    }
                }
                Button {
                    text: "停止任务"
                    enabled: root.taskBackend && root.taskBackend.active
                    onClicked: root.taskBackend.stop()
                    contentItem: Text {
                        text: parent.text
                        color: parent.enabled ? WxTheme.clDangerNew : WxTheme.clTextHint
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: parent.hovered ? WxTheme.clDangerSoft : "transparent"
                        border.color: WxTheme.clSurfaceBorder
                        radius: WxTheme.radiusSmall
                    }
                }
            }
        }
    }

    FileDialog {
        id: exportDialog
        title: "导出任务结果"
        fileMode: FileDialog.SaveFile
        nameFilters: ["CSV 文件 (*.csv)"]
        defaultSuffix: "csv"
        onAccepted: if (root.taskBackend) root.taskBackend.exportResults(selectedFile)
    }
}
