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

    function openSettings(section) {
        if (root.interactionLocked) return
        settingsDialog.sectionIndex = section === undefined ? 0 : section
        settingsDialog.open()
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
                    model: ["消息群发", "批量加好友"]
                    Button {
                        required property int index
                        required property string modelData
                        objectName: index === 0 ? "messageWorkspaceTab" : "friendWorkspaceTab"
                        Layout.preferredWidth: index === 0 ? 92 : 116
                        Layout.fillHeight: true
                        enabled: !root.interactionLocked
                        onClicked: {
                            if (!root.interactionLocked) root.workspaceIndex = index
                        }
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

                Rectangle {
                    Layout.preferredHeight: 28
                    Layout.preferredWidth: versionText.implicitWidth + 20
                    radius: WxTheme.radiusSmall
                    color: root.appBackend && root.appBackend.agent.wechatSupported
                        ? WxTheme.clSuccessSoft : WxTheme.clWarningSoft
                    border.color: root.appBackend && root.appBackend.agent.wechatSupported
                        ? WxTheme.clSuccessBorder : WxTheme.clWarningBorder
                    Text {
                        id: versionText
                        anchors.centerIn: parent
                        text: root.appBackend && root.appBackend.agent.wechatVersion
                            ? "微信 " + root.appBackend.agent.wechatVersion
                                + (root.appBackend.agent.wechatSupported ? " 已验证" : " 不受支持")
                            : "等待检测微信"
                        color: root.appBackend && root.appBackend.agent.wechatSupported
                            ? WxTheme.clSuccessText : WxTheme.clWarningText
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.workspaceIndex

            MessageWorkspace { appBackend: root.appBackend }
            FriendWorkspace { appBackend: root.appBackend }
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
        }
    }

    RecoveryDialog {
        taskBackend: root.appBackend ? root.appBackend.task : null
    }
}
