import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Slider {
    id: root
    implicitWidth: 210
    implicitHeight: WxTheme.controlHeight
    padding: 8
    opacity: enabled ? 1 : 0.45
    background: Rectangle {
        x: root.leftPadding
        y: root.topPadding + (root.availableHeight - height) / 2
        width: root.availableWidth
        height: 4
        radius: 2
        color: WxTheme.clBorderStrong
        Rectangle {
            width: root.position * parent.width
            height: parent.height
            radius: parent.radius
            color: WxTheme.clPrimary
        }
    }
    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + (root.availableHeight - height) / 2
        width: 18
        height: 18
        radius: 9
        color: WxTheme.clBgPrimary
        border.width: root.activeFocus || root.pressed ? 3 : 2
        border.color: WxTheme.clPrimary
    }
}
