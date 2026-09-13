import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../theme"

Rectangle {
    id: root

    property var window: null
    property var titleBackend: null
    property var openSettings: null
    property double _lastOpacityToast: 0
    property bool layoutMenuOpen: false

    height: 40
    color: WxTheme.clTitleBarBg

    function clampOpacity(value) {
        return Math.max(45, Math.min(90, Math.round(value)))
    }

    function setGlassEnabled(enabled) {
        WxTheme.glassEnabled = enabled
        if (root.titleBackend) {
            root.titleBackend.glassEnabled = enabled
        }
    }

    function setGlassOpacity(value, showToast) {
        var normalized = clampOpacity(value)
        if (WxTheme.glassOpacity === normalized) return

        WxTheme.glassOpacity = normalized
        if (root.titleBackend) {
            root.titleBackend.glassOpacity = normalized
            var now = Date.now()
            if (showToast && now - root._lastOpacityToast > 300) {
                root.titleBackend.showToast("毛玻璃透明度 " + normalized + "%", "info")
                root._lastOpacityToast = now
            }
        }
    }

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

        // ── Window visual controls ──
        RowLayout {
            id: visualControls
            spacing: 8
            Layout.fillHeight: true

            Rectangle {
                id: glassControl
                Layout.preferredWidth: 124
                Layout.preferredHeight: 28
                radius: 14
                color: glassArea.containsMouse ? WxTheme.clBgHover : WxTheme.clSurfaceStrong
                border.width: 1
                border.color: glassArea.containsMouse ? WxTheme.clPrimary : WxTheme.clBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 6

                    Rectangle {
                        Layout.preferredWidth: 28
                        Layout.preferredHeight: 16
                        radius: 8
                        color: WxTheme.glassEnabled ? WxTheme.clPrimary : WxTheme.clSwitchTrackOff

                        Rectangle {
                            width: 12
                            height: 12
                            radius: 6
                            y: 2
                            x: WxTheme.glassEnabled ? 14 : 2
                            color: WxTheme.clSwitchThumb

                            Behavior on x {
                                NumberAnimation { duration: WxTheme.animNormal; easing.type: Easing.OutQuad }
                            }
                        }
                    }

                    Text {
                        text: "毛玻璃"
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                        color: WxTheme.clTextPrimary
                    }

                    Text {
                        text: WxTheme.glassOpacity + "%"
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                        color: WxTheme.glassEnabled ? WxTheme.clPrimary : WxTheme.clTextHint
                        Layout.alignment: Qt.AlignRight
                    }
                }

                MouseArea {
                    id: glassArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.setGlassEnabled(!WxTheme.glassEnabled)
                    onWheel: function(wheel) {
                        var step = wheel.angleDelta.y > 0 ? 5 : -5
                        root.setGlassOpacity(WxTheme.glassOpacity + step, true)
                        wheel.accepted = true
                    }
                }

                Rectangle {
                    visible: glassArea.containsMouse
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
                        text: "滚轮调整透明度"
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                        color: WxTheme.clToastText
                    }
                }
            }

            Rectangle {
                id: themeToggleBtn
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                radius: 14
                color: themeArea.containsMouse ? WxTheme.clBgHover : WxTheme.clSurfaceStrong
                border.color: WxTheme.clBorder
                border.width: 1

                scale: themeArea.containsMouse ? 1.08 : 1.0
                Behavior on scale {
                    NumberAnimation { duration: WxTheme.animNormal; easing.type: Easing.OutQuad }
                }

                WxIcon {
                    id: themeIcon
                    anchors.centerIn: parent
                    iconSource: WxTheme.isDark ? "../icons/sun.svg" : "../icons/moon.svg"
                    iconColor: WxTheme.isDark ? WxTheme.clWarning : WxTheme.clTextSecondary
                    hoverColor: WxTheme.clPrimary
                    iconSize: 16
                    hoverScale: false
                }

                MouseArea {
                    id: themeArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        themeIcon.rotation += 360
                        WxTheme.isDark = !WxTheme.isDark
                        if (root.titleBackend) root.titleBackend.isDark = WxTheme.isDark
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

    Connections {
        target: root.titleBackend
        ignoreUnknownSignals: true

        function onGlassEnabledChanged() {
            WxTheme.glassEnabled = root.titleBackend.glassEnabled
        }

        function onGlassOpacityChanged() {
            WxTheme.glassOpacity = root.clampOpacity(root.titleBackend.glassOpacity)
        }
    }
}
