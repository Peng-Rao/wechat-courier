import QtQuick
import QtQuick.Controls.Basic
import "../theme"

Button {
    id: root
    property var attachment: ({})
    property int fileIndex: -1
    readonly property bool imageAvailable: !!attachment.isImage && attachment.exists !== false && thumbnail.status !== Image.Error
    signal imageRequested(url source, string name)
    signal fileRequested(int index)

    implicitWidth: 320
    implicitHeight: imageAvailable ? 200 : WxTheme.chatFileCardHeight
    padding: 0
    hoverEnabled: true
    Accessible.name: (imageAvailable ? "预览图片 " : "打开附件 ") + (attachment.name || "")
    ToolTip.visible: hovered
    ToolTip.text: attachment.name || ""
    onClicked: {
        if (imageAvailable) imageRequested(attachment.url, attachment.name || "")
        else fileRequested(fileIndex)
    }
    background: Rectangle {
        color: WxTheme.clPanelFill
        radius: WxTheme.radiusMedium
        border.color: root.hovered ? WxTheme.clBorderFocus : WxTheme.clSurfaceBorder
    }
    contentItem: Item {
        Image {
            id: thumbnail
            objectName: "attachmentThumbnail"
            anchors.fill: parent
            anchors.margins: 6
            visible: root.imageAvailable
            source: root.attachment.isImage ? root.attachment.url || "" : ""
            asynchronous: true
            autoTransform: true
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 640
            sourceSize.height: 480
        }
        WxChatFileCard {
            anchors.fill: parent
            visible: !root.imageAvailable
            fileName: root.attachment.name || ""
            fileSize: root.attachment.exists === false ? "文件不可用" : root.attachment.sizeLabel || ""
            fileType: root.attachment.type || "other"
        }
    }
}
