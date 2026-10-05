import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ScrollBar {
    id: root
    padding: 3
    implicitWidth: 10
    implicitHeight: 10
    minimumSize: 0.08
    contentItem: Rectangle {
        implicitWidth: 4; implicitHeight: 4; radius: 2
        color: root.pressed ? WxTheme.clPrimary : root.hovered ? WxTheme.clTextSecondary : WxTheme.clBorderStrong
    }
}
