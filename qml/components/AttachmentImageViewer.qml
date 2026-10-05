import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Popup {
    id: root
    objectName: "attachmentImageViewer"
    property url sourceUrl: ""
    property string fileName: ""
    width: Math.max(240, Math.min(1100, parent ? parent.width - 48 : 900))
    height: Math.max(200, Math.min(850, parent ? parent.height - 48 : 650))
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    modal: true
    focus: true
    padding: 12
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onClosed: sourceUrl = ""
    background: WxGlassSurface {
        fillColor: WxTheme.clSurfaceStrong
        borderColor: WxTheme.clSurfaceBorder
        radius: WxTheme.radiusMedium
    }
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.fileName
                elide: Text.ElideMiddle
                color: WxTheme.clTextPrimary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeNormal
            }
            WxButton {
                objectName: "closeAttachmentImageButton"
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                Accessible.name: "关闭图片预览"
                quiet: true
                iconName: "close"
                tooltipText: "关闭"
                onClicked: root.close()
            }
        }
        Image {
            id: image
            objectName: "enlargedAttachmentImage"
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: root.sourceUrl
            asynchronous: true
            autoTransform: true
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 2048
            sourceSize.height: 1536
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            visible: image.status === Image.Error
            text: "图片不存在或无法读取"
            color: WxTheme.clDangerNew
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeSmall
        }
    }
}
