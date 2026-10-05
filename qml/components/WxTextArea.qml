import QtQuick
import QtQuick.Controls.Basic
import "../theme"

TextArea {
    id: root
    padding: 12
    selectByMouse: true
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    color: WxTheme.clTextPrimary
    placeholderTextColor: WxTheme.clTextHint
    selectionColor: WxTheme.clBgSelected
    selectedTextColor: WxTheme.clTextPrimary
    wrapMode: TextEdit.Wrap
    opacity: enabled ? 1 : 0.5
    background: Rectangle { radius: 6; color: WxTheme.clFieldFill; border.color: root.activeFocus ? WxTheme.clBorderFocus : WxTheme.clBorderStrong }
    ContextMenu.menu: WxTextMenu { editor: root }
}
