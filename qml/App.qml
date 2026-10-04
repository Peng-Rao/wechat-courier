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
        if (root.interactionLocked) return
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

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 6

                Repeater {
                    model: ["消息群发", "自动发送好友申请", "微信联系人导出"]
                    Button {
                        required property int index
                        required property string modelData
                        objectName: index === 0 ? "messageWorkspaceTab" : index === 1 ? "friendWorkspaceTab" : "contactWorkspaceTab"
                        Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                            ? objectName : modelData
                        Layout.preferredWidth: index === 0 ? 100 : index === 1 ? 160 : 144
                        Layout.fillHeight: true
                        onClicked: root.workspaceIndex = index
                        contentItem: Text {
                            text: modelData
                            color: root.workspaceIndex === index
                                ? WxTheme.clTextPrimary
                                : (parent.enabled ? WxTheme.clTextSecondary : WxTheme.clTextHint)
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall + (root.workspaceIndex === index ? 1 : 0)
                            font.bold: root.workspaceIndex === index
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Item {
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                height: 3
                                color: WxTheme.clPrimary
                                visible: root.workspaceIndex === index
                            }
                        }
                    }
                }
                Item { Layout.fillWidth: true }
            }
        }

        GateRecoveryBanner {
            Layout.fillWidth: true
            appBackend: root.appBackend
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.workspaceIndex

            MessageWorkspace { appBackend: root.appBackend }
            FriendWorkspace { appBackend: root.appBackend }
            ContactWorkspace { appBackend: root.appBackend }
        }
    }

    SettingsDialog {
        id: settingsDialog
        appBackend: root.appBackend
        enabled: !root.interactionLocked
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
