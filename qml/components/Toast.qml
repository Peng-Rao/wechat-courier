import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root
    anchors.fill: parent
    z: 9999
    
    // Custom visible behavior using opacity to ensure smooth fades
    visible: opacity > 0
    opacity: 0.0
    
    // Properties
    property string text: ""
    property string type: "info" // "info", "success", "error"

    Behavior on opacity {
        NumberAnimation { duration: WxTheme.animSlow }
    }

    Timer {
        id: hideTimer
        interval: 2000
        repeat: false
        onTriggered: {
            root.opacity = 0.0
        }
    }

    // Public API to show toast
    function show(message, toastType) {
        root.text = message
        root.type = toastType || "info"
        root.opacity = 1.0
        hideTimer.restart()
    }

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 80
        anchors.horizontalCenter: parent.horizontalCenter
        
        // Premium capsule/pill layout
        height: Math.max(36, contentLayout.height + WxTheme.spSmall * 2)
        width: Math.min(contentLayout.width + WxTheme.spLarge * 2, root.width - 40)
        
        radius: WxTheme.radiusLarge
        color: WxTheme.clToastBg
        
        // Subtle outline for premium depth
        border.color: "#555555"
        border.width: 1

        Row {
            id: contentLayout
            anchors.centerIn: parent
            spacing: WxTheme.spSmall

            // Beautiful minimal indicator icon
            Text {
                text: {
                    if (root.type === "success") return "●"
                    if (root.type === "error") return "●"
                    return "●"
                }
                color: {
                    if (root.type === "success") return WxTheme.clSuccessText
                    if (root.type === "error") return WxTheme.clDangerNew
                    return "#a0a0a0"
                }
                font.pixelSize: WxTheme.fontSizeSmall
                anchors.verticalCenter: parent.verticalCenter
            }

            Text {
                text: root.text
                color: WxTheme.clToastText
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeNormal
                wrapMode: Text.Wrap
                width: Math.min(implicitWidth, root.width - 100)
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
