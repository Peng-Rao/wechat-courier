import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Controls.Basic
import "../theme"

Rectangle {
    id: root

    property var window: null
    property var titleBackend: null
    property var openSettings: null
    property bool settingsEnabled: true
    property bool layoutMenuOpen: false

    readonly property string healthText: !root.titleBackend ? "自动化未就绪"
        : root.titleBackend.agent.reasonCode === "AGENT_ALREADY_RUNNING" ? "其他实例占用"
        : root.titleBackend.agent.gateRecoveryActive && root.titleBackend.agent.recoveryStatus
            ? root.titleBackend.agent.recoveryStatus
        : root.titleBackend.agent.connected === false ? "Agent 离线"
        : root.titleBackend.agent.processDetected && root.titleBackend.agent.versionSupported === false
            ? "微信版本不受支持"
        : root.titleBackend.task && root.titleBackend.task.automationStatus
            ? root.titleBackend.task.automationStatus
        : root.titleBackend.agent.automationReady ? "自动化已就绪"
        : root.titleBackend.agent.processDetected && !root.titleBackend.agent.windowResponsive ? "微信窗口无响应"
        : root.titleBackend.agent.processDetected && (!root.titleBackend.agent.windowEnabled || root.titleBackend.agent.blockingWindow) ? "微信窗口被阻挡"
        : root.titleBackend.agent.canStartTask && !root.titleBackend.agent.sessionReady ? "会话待恢复" : "自动化未就绪"
    readonly property bool healthBlocked: /(离线|无响应|被阻挡|不受支持|占用|失败)/.test(healthText)
    readonly property bool healthRecovering: !healthBlocked && /(恢复|未就绪|登录)/.test(healthText)

    height: 40
    color: WxTheme.clTitleBarBg

    function toggleMaximized() {
        if (!root.window) return
        if (root.window.visibility === Window.Maximized) {
            root.window.showNormal()
        } else {
            root.window.applySnapMode("maximize")
        }
    }

    function requestSettings() {
        if (root.settingsEnabled && root.openSettings) root.openSettings()
    }

    // Bottom divider
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: WxTheme.clGlassDivider
    }

    // System Window Move Handler (native move keeps Windows snap previews stable)
    MouseArea {
        anchors.fill: parent
        anchors.rightMargin: 590

        onPressed: {
            if (root.window && root.window.visibility !== Window.FullScreen) {
                root.window.startSystemMove()
            }
        }

        onDoubleClicked: root.toggleMaximized()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 0
        spacing: 10

        Image {
            objectName: "titlebarBrandLogo"
            Layout.preferredWidth: 22
            Layout.preferredHeight: 22
            source: "../../assets/fuge-logo-64.png"
            fillMode: Image.PreserveAspectFit
            smooth: true
        }

        // Title Text
        Text {
            text: root.window ? root.window.title : "福格微信助手"
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeSmall
            font.bold: true
            color: WxTheme.clTextPrimary
            Layout.fillWidth: true
            elide: Text.ElideRight
        }

        WxButton {
            id: healthTrigger
            objectName: "healthSummaryButton"
            quiet: true
            Layout.preferredWidth: 130
            Layout.maximumWidth: 130
            Layout.preferredHeight: 30
            tooltipText: root.healthText
            onClicked: healthPopup.open()
            contentItem: RowLayout {
                spacing: 8
                Rectangle {
                    width: 7; height: 7; radius: 3.5
                    color: root.healthBlocked ? WxTheme.clDangerNew : root.healthRecovering ? WxTheme.clWarningText
                        : root.titleBackend && root.titleBackend.task && root.titleBackend.task.active
                        ? WxTheme.clPrimary : root.titleBackend && root.titleBackend.agent.automationReady
                            ? WxTheme.clSuccessText : WxTheme.clWarningText
                }
                Text {
                    objectName: "titleAutomationHealth"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                    text: root.healthText
                    color: root.healthBlocked ? WxTheme.clDangerNew : root.healthRecovering ? WxTheme.clWarningText : WxTheme.clTextSecondary
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    font.family: WxTheme.fontFamily
                    font.pixelSize: 12
                }
                WxIcon { iconSource: "../icons/arrow_down.svg"; iconSize: 12; iconColor: WxTheme.clTextSecondary; hoverScale: false }
            }
        }

        Rectangle {
            id: settingsButton
            objectName: "settingsButton"
            Accessible.role: Accessible.Button
            Accessible.name: root.titleBackend && root.titleBackend.task.acceptanceEnabled
                ? "settingsButton" : "设置"
            Accessible.onPressAction: root.requestSettings()
            Layout.preferredWidth: 30
            Layout.preferredHeight: 28
            radius: WxTheme.radiusSmall
            opacity: root.settingsEnabled ? 1.0 : 0.45
            color: root.settingsEnabled && settingsArea.containsMouse
                ? WxTheme.clBgHover : "transparent"

            WxIcon {
                anchors.centerIn: parent
                iconSource: "../icons/settings.svg"
                iconColor: WxTheme.clTextSecondary
                iconSize: 16
            }

            MouseArea {
                id: settingsArea
                objectName: "settingsMouseArea"
                anchors.fill: parent
                enabled: root.settingsEnabled
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.requestSettings()
            }
        }

        // ── Window Controls ──
        RowLayout {
            spacing: 0
            Layout.fillHeight: true

            // 1. Minimize Button
            Rectangle {
                id: minButton
                objectName: "windowMinimizeButton"
                Layout.preferredWidth: 46
                Layout.fillHeight: true
                color: minMouseArea.containsMouse ? WxTheme.clBgHover : "transparent"
                
                Text {
                    anchors.centerIn: parent
                    text: "─"
                    font.family: WxTheme.fontFamily
                    font.pixelSize: 10
                    color: WxTheme.clTextPrimary
                }

                MouseArea {
                    id: minMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (root.window) root.window.showMinimized()
                    }
                }
            }

            // 2. Maximize/Restore Button
            Rectangle {
                id: maxButton
                objectName: "windowMaximizeButton"
                Layout.preferredWidth: 46
                Layout.fillHeight: true
                color: maxMouseArea.containsMouse ? WxTheme.clBgHover : "transparent"
                
                // Draw square maximize box or double boxes for restore
                Rectangle {
                    anchors.centerIn: parent
                    width: 9
                    height: 9
                    color: "transparent"
                    border.color: WxTheme.clTextPrimary
                    border.width: 1
                }

                MouseArea {
                    id: maxMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            root.layoutMenuOpen = !root.layoutMenuOpen
                        } else {
                            root.layoutMenuOpen = false
                            root.toggleMaximized()
                        }
                    }
                }
            }

            // 3. Close Button
            Rectangle {
                id: closeButton
                objectName: "windowCloseButton"
                Layout.preferredWidth: 46
                Layout.fillHeight: true
                color: closeMouseArea.containsMouse ? "#e81123" : "transparent"
                
                Text {
                    anchors.centerIn: parent
                    text: "✕"
                    font.family: WxTheme.fontFamily
                    font.pixelSize: 12
                    color: closeMouseArea.containsMouse ? "#ffffff" : WxTheme.clTextPrimary
                }

                MouseArea {
                    id: closeMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (root.window) root.window.close()
                    }
                }
            }
        }
    }


    Popup {
        id: healthPopup
        objectName: "healthDetailsPopup"
        popupType: Popup.Item
        x: Math.max(8, root.width - width - 150)
        y: root.height + 4
        width: 310
        padding: 16
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 8; color: WxTheme.clBgPrimary; border.color: WxTheme.clBorderStrong }
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: "连接状态"; font.family: WxTheme.fontFamily; font.pixelSize: 14; font.bold: true; color: WxTheme.clTextPrimary }
            Repeater {
                model: [
                    ["Agent", root.titleBackend && root.titleBackend.agent.connected ? "在线" : root.healthText === "其他实例占用" ? root.healthText : "离线"],
                    ["微信版本", !root.titleBackend || !root.titleBackend.agent.processDetected ? "未检测到微信" : root.titleBackend.agent.wechatVersion + (root.titleBackend.agent.versionSupported ? " · 受支持" : " · 不受支持")],
                    ["自动化", root.healthText]
                ]
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Text { text: parent.modelData[0]; font.family: WxTheme.fontFamily; font.pixelSize: 12; color: WxTheme.clTextSecondary; Layout.fillWidth: true }
                    Text { text: parent.modelData[1]; font.family: WxTheme.fontFamily; font.pixelSize: 12; color: WxTheme.clTextPrimary; Layout.maximumWidth: 220; wrapMode: Text.Wrap }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: WxTheme.clBorder }
            Text {
                Layout.fillWidth: true
                text: root.titleBackend ? (root.titleBackend.agent.degradedReason || "") : ""
                visible: text !== ""
                wrapMode: Text.Wrap
                font.family: WxTheme.fontFamily; font.pixelSize: 12; color: WxTheme.clWarningText
            }
        }
    }

    component LayoutMenuButton: Rectangle {
        property string label: ""
        property string description: ""
        property var action

        width: 46
        height: 34
        radius: 6
        color: buttonArea.containsMouse ? WxTheme.clBgHover : "transparent"

        Text {
            anchors.centerIn: parent
            text: label
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeTiny
            font.bold: true
            color: WxTheme.clTextPrimary
        }

        MouseArea {
            id: buttonArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (action) action()
            }
        }

        Rectangle {
            visible: buttonArea.containsMouse
            z: 20
            width: tooltipText.implicitWidth + 16
            height: 24
            radius: 6
            color: WxTheme.clToastBg
            x: parent.width / 2 - width / 2
            y: parent.height + 6

            Text {
                id: tooltipText
                anchors.centerIn: parent
                text: description
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeTiny
                color: WxTheme.clToastText
            }
        }
    }

    Rectangle {
        id: layoutMenu
        z: 500
        visible: root.layoutMenuOpen
        anchors.right: parent.right
        anchors.rightMargin: 46
        y: root.height - 1
        width: 204
        height: 42
        radius: 8
        color: WxTheme.clSurfaceStrong
        border.color: WxTheme.clSurfaceBorder
        border.width: 1

        Row {
            anchors.centerIn: parent
            spacing: 4

            LayoutMenuButton {
                label: "全屏"
                description: "全屏预览"
                action: function() {
                    if (root.window) root.window.enterFullScreenPreview()
                    root.layoutMenuOpen = false
                }
            }

            LayoutMenuButton {
                label: "左半"
                description: "贴左侧"
                action: function() {
                    if (root.window) root.window.applySnapMode("left")
                    root.layoutMenuOpen = false
                }
            }

            LayoutMenuButton {
                label: "右半"
                description: "贴右侧"
                action: function() {
                    if (root.window) root.window.applySnapMode("right")
                    root.layoutMenuOpen = false
                }
            }

            LayoutMenuButton {
                label: "还原"
                description: "居中还原"
                action: function() {
                    if (root.window) root.window.centerAndRestore()
                    root.layoutMenuOpen = false
                }
            }
        }

        MouseArea {
            id: menuMouseArea
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
        }
    }

}
