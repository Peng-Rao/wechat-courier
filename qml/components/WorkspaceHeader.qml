import QtQuick
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    property string eyebrow: ""
    property string title: ""
    property string titleObjectName: ""
    default property alias actions: actionRow.data
    implicitHeight: Math.max(heading.implicitHeight, actionRow.implicitHeight) + 40

    data: RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        spacing: 16
        ColumnLayout {
            id: heading
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 4
            Text {
                text: root.eyebrow
                textFormat: Text.PlainText
                color: WxTheme.clTextSecondary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
            }
            Text {
                objectName: root.titleObjectName
                Layout.fillWidth: true
                text: root.title
                textFormat: Text.PlainText
                color: WxTheme.clTextPrimary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeTitle
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
        }
        RowLayout { id: actionRow; spacing: 8 }
    }
}
