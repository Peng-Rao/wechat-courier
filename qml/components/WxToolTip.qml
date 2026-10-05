import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ToolTip {
    id: root
    delay: 600
    timeout: 5000
    padding: 8
    width: Math.min(360, contentItem.implicitWidth + leftPadding + rightPadding)
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeSmall
    contentItem: Text { text: root.text; textFormat: Text.PlainText; font: root.font; color: WxTheme.clToastText; wrapMode: Text.Wrap }
    background: Rectangle { radius: 4; color: WxTheme.clToastBg }
}
