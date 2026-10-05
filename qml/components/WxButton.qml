import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Button {
    id: root
    property bool primary: false
    property bool danger: false
    property bool quiet: false
    property string iconName: ""
    property string tooltipText: ""
    implicitHeight: WxTheme.controlHeight
    implicitWidth: Math.max(text === "" ? 36 : 64, contentItem.implicitWidth + leftPadding + rightPadding)
    leftPadding: text === "" ? 8 : 12
    rightPadding: leftPadding
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    readonly property color foreground: primary ? WxTheme.clPrimaryInk : danger ? WxTheme.clDanger : WxTheme.clTextPrimary
    contentItem: RowLayout {
        spacing: 8
        WxIcon {
            visible: root.iconName !== ""
            iconSource: root.iconName === "" ? "" : root.iconName.indexOf("/") >= 0 ? root.iconName : "../icons/" + root.iconName + ".svg"
            iconSize: 16
            iconColor: root.foreground
            hoverScale: false
            Layout.alignment: Qt.AlignVCenter
        }
        Text {
            visible: root.text !== ""
            text: root.text
            font: root.font
            color: root.foreground
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            Layout.fillWidth: true
        }
    }
    background: Rectangle {
        radius: 6
        color: root.primary ? (root.down ? WxTheme.clPrimaryPress : root.hovered ? WxTheme.clPrimaryHover : WxTheme.clPrimary)
            : root.down ? WxTheme.clBgSelected : root.hovered ? WxTheme.clBgHover
            : root.quiet ? "transparent" : WxTheme.clBgPrimary
        border.width: root.quiet && !root.activeFocus ? 0 : 1
        border.color: root.activeFocus ? WxTheme.clBorderFocus : root.primary ? WxTheme.clPrimaryPress : WxTheme.clBorderStrong
        Behavior on color { ColorAnimation { duration: WxTheme.animFast } }
    }
    WxToolTip { text: root.tooltipText; visible: root.hovered && text !== ""; parent: root; y: root.height + 6 }
}
