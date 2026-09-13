import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../theme"

Rectangle {
    id: root

    property var window: null
    property var titleBackend: null
    property var openSettings: null
    property bool layoutMenuOpen: false

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

        // Title Text
        Text {
            text: root.window ? root.window.title : "五阿哥微信助手"
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeSmall
            font.bold: true
            color: WxTheme.clTextPrimary
            Layout.fillWidth: true
            elide: Text.ElideRight
        }

        RowLayout {
            visible: root.width >= 980 && root.titleBackend && root.titleBackend.agent
            spacing: 14

            RowLayout {
                spacing: 6
                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: root.titleBackend && root.titleBackend.agent.connected
                        ? WxTheme.clInfo : WxTheme.clTextHint
                }
                Text {
                    text: root.titleBackend && root.titleBackend.agent.connected
                        ? "Agent 在线" : "Agent 离线"
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeTiny
                }
            }

            RowLayout {
                spacing: 6
                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: root.titleBackend && root.titleBackend.agent.wechatSupported
                        ? WxTheme.clPrimary : WxTheme.clWarningText
                }
                Text {
                    text: root.titleBackend && root.titleBackend.agent.wechatConnected
                        ? "微信 " + root.titleBackend.agent.wechatVersion : "微信未连接"
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeTiny
                }
            }
        }

        Rectangle {
            id: settingsButton
            Layout.preferredWidth: 30
            Layout.preferredHeight: 28
            radius: WxTheme.radiusSmall
            color: settingsArea.containsMouse ? WxTheme.clBgHover : "transparent"

            WxIcon {
                anchors.centerIn: parent
                iconSource: "../icons/settings.svg"
                iconColor: WxTheme.clTextSecondary
                iconSize: 16
            }

            MouseArea {
                id: settingsArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (root.openSettings) root.openSettings()
            }
        }

        // ── Window Controls ──
        RowLayout {
            spacing: 0
            Layout.fillHeight: true

            // 1. Minimize Button
            Rectangle {
                id: minButton
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
