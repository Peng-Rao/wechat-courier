import QtQuick
import QtQuick.Controls.Basic
import "../theme"

SpinBox {
    id: root
    implicitWidth: 136; implicitHeight: 36
    editable: true
    leftPadding: 36; rightPadding: 36
    font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeNormal
    opacity: enabled ? 1 : 0.5
    contentItem: WxTextField {
        text: root.displayText
        horizontalAlignment: Text.AlignHCenter
        readOnly: !root.editable
        validator: root.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        background: null
    }
    up.indicator: Rectangle {
        x: root.width - width; width: 34; height: root.height; radius: 6
        color: root.up.hovered ? WxTheme.clBgHover : "transparent"
        opacity: root.value < root.to ? 1 : 0.4
        WxIcon { anchors.centerIn: parent; iconSource: "../icons/plus.svg"; iconSize: 16; iconColor: WxTheme.clTextPrimary; hoverScale: false }
    }
    down.indicator: Rectangle {
        x: 0; width: 34; height: root.height; radius: 6
        color: root.down.hovered ? WxTheme.clBgHover : "transparent"
        opacity: root.value > root.from ? 1 : 0.4
        WxIcon { anchors.centerIn: parent; iconSource: "../icons/minus.svg"; iconSize: 16; iconColor: WxTheme.clTextPrimary; hoverScale: false }
    }
    background: Rectangle { radius: 6; color: WxTheme.clFieldFill; border.color: root.activeFocus ? WxTheme.clBorderFocus : WxTheme.clBorderStrong }
}
