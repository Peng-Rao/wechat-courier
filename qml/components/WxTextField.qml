import QtQuick
import QtQuick.Controls.Basic
import "../theme"

TextField {
    id: root
    implicitHeight: WxTheme.controlHeight
    implicitWidth: 180
    leftPadding: 10
    rightPadding: 10
    selectByMouse: true
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    color: WxTheme.clTextPrimary
    placeholderTextColor: WxTheme.clTextHint
    selectionColor: WxTheme.clBgSelected
    selectedTextColor: WxTheme.clTextPrimary
    opacity: enabled ? 1 : 0.5
    background: Rectangle {
        radius: 6
        color: WxTheme.clFieldFill
        border.color: root.activeFocus ? WxTheme.clBorderFocus : root.hovered ? WxTheme.clTextSecondary : WxTheme.clBorderStrong
    }
    ContextMenu.menu: WxTextMenu { editor: root }
}
