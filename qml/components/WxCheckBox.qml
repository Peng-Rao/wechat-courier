import QtQuick
import QtQuick.Controls.Basic
import "../theme"

CheckBox {
    id: root
    implicitHeight: 36
    spacing: 8
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    opacity: enabled ? 1 : 0.45
    indicator: Rectangle {
        implicitWidth: 16; implicitHeight: 16
        x: root.leftPadding; y: (root.height - height) / 2; radius: 3
        color: root.checked ? WxTheme.clPrimary : WxTheme.clBgPrimary
        border.color: root.activeFocus || root.hovered || root.checked ? WxTheme.clPrimary : WxTheme.clBorderStrong
        WxIcon { anchors.centerIn: parent; iconSource: "../icons/check.svg"; iconSize: 12; iconColor: WxTheme.clPrimaryInk; visible: root.checked; hoverScale: false }
    }
    contentItem: Text {
        text: root.text; font: root.font; color: WxTheme.clTextPrimary; verticalAlignment: Text.AlignVCenter
        leftPadding: root.indicator.width + root.spacing
    }
}
