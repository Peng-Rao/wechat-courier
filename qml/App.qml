import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "components"
import "theme"

Rectangle {
    id: root
    objectName: "appRoot"
    property var appBackend: null
    property int workspaceIndex: 0
    readonly property bool interactionLocked: !!(
        appBackend && appBackend.task && appBackend.task.active
    )
    readonly property bool sidebarCollapsed: !!(appBackend && appBackend.settings.sidebarCollapsed)
    color: "transparent"

    // Read-only UIA evidence is exposed only for explicitly opted-in acceptance runs.
    Item {
        width: 1
        height: 1
        visible: !!(root.appBackend && root.appBackend.task.acceptanceEnabled)
        Accessible.role: Accessible.StaticText
        Accessible.name: "acceptanceEditorState"
        Accessible.description: visible ? (root.workspaceIndex === 0
            ? root.appBackend.task.acceptanceMessageStateJson
            : root.workspaceIndex === 1 ? root.appBackend.task.acceptanceFriendStateJson : "") : ""
    }
    Item {
        width: 1
        height: 1
        visible: !!(root.appBackend && root.appBackend.task.acceptanceEnabled)
        Accessible.role: Accessible.StaticText
        Accessible.name: "acceptanceTaskState"
        Accessible.description: visible
            ? root.appBackend.task.acceptanceTaskStateJson : ""
    }

    function openSettings(section) {
        settingsDialog.sectionIndex = section === undefined ? 0 : section
        settingsDialog.open()
    }

    function showActiveTaskWorkspace() {
        if (!root.interactionLocked || !root.appBackend || !root.appBackend.task)
            return
        if (root.appBackend.task.kind === "message_send")
            root.workspaceIndex = 0
        else if (root.appBackend.task.kind === "friend_add")
            root.workspaceIndex = 1
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        GateRecoveryBanner {
            Layout.fillWidth: true
            appBackend: root.appBackend
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            Rectangle {
                objectName: "workspaceSidebar"
                Layout.preferredWidth: root.sidebarCollapsed ? 64 : 216
                Layout.fillHeight: true
                color: WxTheme.clTitleBarBg
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: WxTheme.clBorder }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: root.sidebarCollapsed ? 10 : 12
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 12
                        Text { visible: !root.sidebarCollapsed; text: "工作区"; font.family: WxTheme.fontFamily; font.pixelSize: 12; color: WxTheme.clTextSecondary; Layout.fillWidth: true; leftPadding: 12 }
                        WxButton {
                            objectName: "sidebarCollapseButton"
                            Layout.preferredWidth: root.sidebarCollapsed ? 44 : 36
                            Layout.preferredHeight: 42
                            Accessible.name: root.sidebarCollapsed ? "展开侧栏" : "折叠侧栏"
                            quiet: true; iconName: "panel_left"
                            iconSize: 18
                            tooltipText: Accessible.name
                            onClicked: { if (root.appBackend) root.appBackend.settings.sidebarCollapsed = !root.sidebarCollapsed }
                        }
                    }
                    Repeater {
                        model: ["消息群发", "自动发送好友申请", "微信联系人导出"]
                        WxButton {
                            id: navButton
                            required property int index
                            required property string modelData
                            objectName: index === 0 ? "messageWorkspaceTab" : index === 1 ? "friendWorkspaceTab" : "contactWorkspaceTab"
                            Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled ? objectName : modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            leftPadding: root.sidebarCollapsed ? 0 : 12
                            rightPadding: leftPadding
                            quiet: true
                            tooltipText: root.sidebarCollapsed ? modelData : ""
                            onClicked: root.workspaceIndex = index
                            contentItem: RowLayout {
                                spacing: 10
                                WxIcon { iconSource: "../icons/" + (navButton.index === 0 ? "send" : navButton.index === 1 ? "user_plus" : "users") + ".svg"; iconSize: 18; iconColor: root.workspaceIndex === navButton.index ? WxTheme.clAccentText : WxTheme.clTextSecondary; hoverScale: false; Layout.alignment: Qt.AlignCenter }
                                Text { visible: !root.sidebarCollapsed; text: navButton.modelData; color: root.workspaceIndex === navButton.index ? WxTheme.clAccentText : WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: 14; font.bold: root.workspaceIndex === navButton.index; Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                            background: Rectangle {
                                radius: 6
                                color: root.workspaceIndex === navButton.index ? WxTheme.clBgSelected : navButton.hovered ? WxTheme.clBgHover : "transparent"
                                border.width: navButton.visualFocus ? 1 : 0; border.color: WxTheme.clBorderFocus
                                Rectangle { visible: root.workspaceIndex === navButton.index; width: 3; height: 16; radius: 1; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: WxTheme.clPrimary }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    WxButton {
                        objectName: "sidebarThemeButton"
                        Layout.fillWidth: true; quiet: true
                        Layout.preferredHeight: 42
                        iconSize: 18
                        textAlignment: Text.AlignLeft
                        leftPadding: root.sidebarCollapsed ? 0 : 12
                        rightPadding: leftPadding
                        iconName: WxTheme.isDark ? "sun" : "moon"
                        text: root.sidebarCollapsed ? "" : WxTheme.isDark ? "浅色主题" : "深色主题"
                        tooltipText: root.sidebarCollapsed ? (WxTheme.isDark ? "浅色主题" : "深色主题") : ""
                        onClicked: { if (root.appBackend) { root.appBackend.settings.isDark = !WxTheme.isDark; WxTheme.isDark = root.appBackend.settings.isDark } }
                    }
                    WxButton {
                        objectName: "sidebarSettingsButton"
                        Accessible.name: "参数设置"
                        Layout.fillWidth: true; quiet: true; iconName: "settings"
                        Layout.preferredHeight: 42
                        iconSize: 18
                        textAlignment: Text.AlignLeft
                        leftPadding: root.sidebarCollapsed ? 0 : 12
                        rightPadding: leftPadding
                        text: root.sidebarCollapsed ? "" : "参数设置"
                        tooltipText: root.sidebarCollapsed ? "参数设置" : ""
                        onClicked: root.openSettings(root.interactionLocked ? 3 : root.workspaceIndex === 1 ? 1 : 0)
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: WxTheme.clBorder; Layout.topMargin: 10 }
                    RowLayout {
                        Layout.topMargin: 8
                        Layout.alignment: Qt.AlignHCenter
                        Image { source: "../assets/fuge-logo-64.png"; sourceSize.width: 20; sourceSize.height: 20; Layout.preferredWidth: 18; Layout.preferredHeight: 18; fillMode: Image.PreserveAspectFit }
                        Text { visible: !root.sidebarCollapsed; text: "福格微信助手"; font.family: WxTheme.fontFamily; font.pixelSize: 12; color: WxTheme.clTextHint }
                    }
                }
            }
            Rectangle {
                objectName: "workspaceContentSurface"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                color: WxTheme.clBgWindow
                StackLayout {
                    anchors.fill: parent
                    currentIndex: root.workspaceIndex
                    MessageWorkspace { appBackend: root.appBackend }
                    FriendWorkspace { appBackend: root.appBackend }
                    ContactWorkspace { appBackend: root.appBackend }
                }
            }
        }
    }

    SettingsDialog {
        id: settingsDialog
        objectName: "settingsDialog"
        appBackend: root.appBackend
    }

    Connections {
        target: root.appBackend ? root.appBackend.task : null
        ignoreUnknownSignals: true
        function onActiveChanged() {
            if (root.interactionLocked && settingsDialog.opened) settingsDialog.close()
            root.showActiveTaskWorkspace()
        }
        function onKindChanged() {
            root.showActiveTaskWorkspace()
        }
    }

    RecoveryDialog {
        taskBackend: root.appBackend ? root.appBackend.task : null
    }
}
