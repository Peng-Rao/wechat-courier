import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Menu {
    id: root
    padding: 5
    margins: 8
    popupType: Popup.Item
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal

    // Custom background with rounded corners and a premium shadow
    background: Rectangle {
        implicitWidth: 220
        color: WxTheme.clBgPrimary
        radius: WxTheme.radiusMedium
        border.color: WxTheme.clBorder
        border.width: 1

        Loader {
            id: shadowLoader
            anchors.fill: parent
            z: -1
            property var shadowTarget: parent
            source: "WxMenuShadow.qml"
        }
    }

    // Enter transition: elegant fade and slight scale-up
    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "scale"
                from: 0.95
                to: 1.0
                duration: WxTheme.animSlow
                easing.type: Easing.OutQuad
            }
            NumberAnimation {
                property: "opacity"
                from: 0.0
                to: 1.0
                duration: WxTheme.animSlow
                easing.type: Easing.OutQuad
            }
        }
    }

    // Exit transition: elegant fade-out
    exit: Transition {
        NumberAnimation {
            property: "opacity"
            from: 1.0
            to: 0.0
            duration: WxTheme.animNormal
            easing.type: Easing.OutQuad
        }
    }
}
