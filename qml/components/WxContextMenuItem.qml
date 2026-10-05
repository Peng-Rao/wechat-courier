import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../theme"

MenuItem {
    id: root

    property string iconSource: ""
    property color iconColor: WxTheme.clTextSecondary
    property color hoverIconColor: WxTheme.clPrimary
    property string shortcutText: ""

    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    implicitHeight: 34
    opacity: enabled ? 1 : 0.4

    contentItem: RowLayout {
        spacing: WxTheme.spSmall
        anchors.fill: parent
        anchors.leftMargin: WxTheme.spMedium
        anchors.rightMargin: WxTheme.spMedium

        // 图标占位区：无论有无图标都固定留出 22px 宽度，保证文字对齐
        Item {
            Layout.preferredWidth: 22
            Layout.fillHeight: true

            WxIcon {
                id: prefixIcon
                anchors.centerIn: parent
                iconSource: root.iconSource
                iconSize: 14
                iconColor: root.highlighted ? root.hoverIconColor : root.iconColor
                visible: root.iconSource !== ""
                hoverScale: false
            }
        }

        Text {
            text: root.text
            font: root.font
            color: root.highlighted ? WxTheme.clAccentText : WxTheme.clTextPrimary
            Layout.fillWidth: true
            verticalAlignment: Text.AlignVCenter

            Behavior on color {
                ColorAnimation { duration: WxTheme.animFast }
            }
        }

        Text {
            text: root.shortcutText
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeTiny
            color: WxTheme.clTextHint
            visible: root.shortcutText !== ""
            horizontalAlignment: Text.AlignRight
            verticalAlignment: Text.AlignVCenter
        }
    }

    background: Rectangle {
        color: root.highlighted ? WxTheme.clBgSelected : root.hovered ? WxTheme.clBgHover : "transparent"
        radius: WxTheme.radiusSmall

        Behavior on color {
            ColorAnimation { duration: WxTheme.animFast }
        }
    }
}
