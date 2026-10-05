import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Switch {
    id: root
    implicitHeight: 36
    implicitWidth: 40
    opacity: enabled ? 1 : 0.45
    indicator: Rectangle {
        implicitWidth: 36; implicitHeight: 20; radius: 10
        y: (root.height - height) / 2
        color: root.checked ? WxTheme.clPrimary : WxTheme.clSwitchTrackOff
        border.width: root.activeFocus ? 1 : 0; border.color: WxTheme.clBorderFocus
        Rectangle { width: 16; height: 16; radius: 8; y: 2; x: root.checked ? 18 : 2; color: WxTheme.clSwitchThumb; Behavior on x { NumberAnimation { duration: 120 } } }
    }
    contentItem: Text { text: root.text; font.family: WxTheme.fontFamily; font.pixelSize: 14; color: WxTheme.clTextPrimary; leftPadding: root.text ? 44 : 0; verticalAlignment: Text.AlignVCenter }
}
