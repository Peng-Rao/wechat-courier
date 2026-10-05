import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Dialog {
    id: root
    objectName: "wechatRecoveryDialog"
    property var taskBackend: null

    parent: Overlay.overlay
    modal: true
    dim: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(520, parent ? parent.width - 48 : 520)
    height: 250
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    padding: 0

    background: WxGlassSurface {
        fillColor: WxTheme.clFieldFill
        borderColor: WxTheme.clSurfaceBorder
        radius: WxTheme.radiusLarge
        highlightEnabled: true
    }

    header: Rectangle {
        implicitHeight: 54
        color: WxTheme.clToolbarFill
        border.color: WxTheme.clSurfaceBorder
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.verticalCenter: parent.verticalCenter
            text: "微信自动化需要恢复"
            color: WxTheme.clTextPrimary
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeTitle
            font.bold: true
        }
    }

    contentItem: ColumnLayout {
        spacing: 12
        Item { Layout.preferredHeight: 4 }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            text: root.taskBackend ? root.taskBackend.recoveryDetail : ""
            wrapMode: Text.Wrap
            color: WxTheme.clTextPrimary
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeNormal
            lineHeight: 1.45
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            text: "重启前会释放 UIA 会话。已越过发送或提交边界的项目只会标记为结果未知，不会重复执行。"
            wrapMode: Text.Wrap
            color: WxTheme.clTextHint
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeTiny
            lineHeight: 1.35
        }
        Item { Layout.fillHeight: true }
    }

    footer: Rectangle {
        implicitHeight: 58
        color: WxTheme.clToolbarFill
        border.color: WxTheme.clSurfaceBorder
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 10
            Item { Layout.fillWidth: true }
            WxButton {
                text: "停止任务"
                danger: true
                onClicked: if (root.taskBackend) root.taskBackend.stopRecovery()
            }
            WxButton {
                text: "重启微信并继续"
                primary: true
                onClicked: if (root.taskBackend) root.taskBackend.approveWechatRestart()
            }
        }
    }

    Connections {
        target: root.taskBackend
        function onRecoveryRequiredChanged() {
            if (root.taskBackend && root.taskBackend.recoveryRequired)
                root.open()
            else
                root.close()
        }
    }

    Component.onCompleted: {
        if (root.taskBackend && root.taskBackend.recoveryRequired)
            root.open()
    }
}
