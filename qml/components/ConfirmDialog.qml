import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import QtQuick.Effects
import "../theme"

Rectangle {
    id: root

    // 公共接口
    property string message: ""
    property string confirmText: "确认"
    property string cancelText: "取消"
    property bool isDanger: false
    property bool confirmEnabled: true
    property string confirmButtonObjectName: ""
    property string cancelButtonObjectName: ""

    signal confirmed()
    signal cancelled()

    // 内部状态
    property bool _opened: false

    anchors.fill: parent
    color: "#80000000"
    visible: _opened
    opacity: _opened ? 1 : 0

    Behavior on opacity {
        NumberAnimation { duration: WxTheme.animNormal }
    }

    // 点击遮罩取消
    MouseArea {
        anchors.fill: parent
        onClicked: root.close()
    }

    // 对话框卡片
    Rectangle {
        id: card
        width: Math.min(parent.width - 80, 400)
        height: contentLayout.implicitHeight + 60
        anchors.centerIn: parent
        color: WxTheme.clBgPrimary
        radius: WxTheme.radiusLarge

        // 阴影
        Rectangle {
            anchors.fill: parent
            color: WxTheme.clShadow
            opacity: WxTheme.shadowOpacityMedium
            radius: parent.radius
            z: -1
            anchors.horizontalCenterOffset: 0
            anchors.verticalCenterOffset: WxTheme.shadowOffsetY
        }

        ColumnLayout {
            id: contentLayout
            anchors.fill: parent
            anchors.margins: WxTheme.spLarge
            spacing: WxTheme.spMedium

            Text {
                text: root.message
                textFormat: Text.PlainText
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeNormal
                color: WxTheme.clTextPrimary
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: WxTheme.spMedium

                WxButton {
                    objectName: root.cancelButtonObjectName
                    text: root.cancelText
                    onClicked: {
                        root.cancelled()
                        root.close()
                    }

                }

                WxButton {
                    objectName: root.confirmButtonObjectName
                    text: root.confirmText
                    enabled: root.confirmEnabled
                    primary: !root.isDanger
                    danger: root.isDanger
                    onClicked: {
                        root.confirmed()
                        root.close()
                    }

                }
            }
        }

        // 弹出动画
        scale: root._opened ? 1 : 0.9
        Behavior on scale {
            NumberAnimation {
                duration: WxTheme.animSlow
                easing.type: Easing.OutBack
            }
        }
    }

    function open() {
        _opened = true
    }

    function close() {
        _opened = false
    }
}
