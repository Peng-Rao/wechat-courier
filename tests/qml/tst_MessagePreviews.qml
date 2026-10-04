import QtQuick
import QtQuick.Window
import QtTest
import "../../qml/components" as Components

TestCase {
    name: "MessagePreviews"
    when: windowShown
    width: 1320
    height: 780
    visible: true
    parent: testWindow.contentItem
    Window { id: testWindow; visible: true; width: 1320; height: 780 }

    QtObject {
        id: message
        property string recipientsText: ""
        property string templateText: ""
        property int recipientCount: 1
        property string previewTarget: "文件传输助手"
        property string previewMessage: templateText
        property var filePaths: []
        property var attachmentPreviews: []
        property real intervalMin: 2
        property real intervalMax: 3
        property int openedFile: -1
        function addFile() {}
        function removeFile() {}
        function openAttachment(index) { openedFile = index; return true }
    }
    QtObject {
        id: backend
        property var message: message
        property var task: null
        property var agent: null
    }
    Component {
        id: workspaceComponent
        Components.MessageWorkspace { width: 1320; height: 780; appBackend: backend }
    }
    property var workspace: null
    Component { id: clickSpy; SignalSpy { signalName: "clicked" } }

    function init() {
        message.recipientsText = ""
        message.templateText = ""
        message.attachmentPreviews = []
        message.openedFile = -1
        workspace = createTemporaryObject(workspaceComponent, this)
        verify(workspace !== null)
        wait(20)
    }
    function cleanup() { workspace = null }

    function test_fields_have_independent_scrollbars() {
        var names = []
        for (var i = 0; i < 50; ++i) names.push("好友 " + i)
        message.recipientsText = names.join("\n")
        message.templateText = names.join("\n")
        var recipientsBar = findChild(workspace, "messageRecipientsScrollBar")
        var templateBar = findChild(workspace, "messageTemplateScrollBar")
        verify(recipientsBar !== null)
        verify(templateBar !== null)
        tryVerify(function() { return recipientsBar.size < 1 && templateBar.size < 1 })
        var input = findChild(workspace, "messageRecipientsInput")
        input.forceActiveFocus()
        keyClick(Qt.Key_End, Qt.ControlModifier)
        tryVerify(function() { return recipientsBar.position > 0 })
    }

    function test_files_without_text_are_visible_and_open_on_click() {
        message.attachmentPreviews = [{name: "example.pdf", url: "file:///example.pdf", type: "pdf", isImage: false, sizeLabel: "1 KB", exists: true}]
        var attachment = null
        tryVerify(function() { attachment = findChild(workspace, "previewAttachment-0"); return attachment !== null })
        verify(attachment.visible)
        tryVerify(function() { return attachment.width > 0 && attachment.height > 0 })
        waitForRendering(workspace)
        var clicked = createTemporaryObject(clickSpy, this, {target: attachment})
        mouseClick(attachment, attachment.width / 2, attachment.height / 2)
        compare(clicked.count, 1)
        compare(message.openedFile, 0)
        compare(findChild(workspace, "messageUseForwardSwitch"), null)
    }

    function test_image_opens_in_window_preview_and_escape_closes() {
        message.attachmentPreviews = [{name: "image.svg", url: Qt.resolvedUrl("../../qml/icons/image.svg"), type: "image", isImage: true, sizeLabel: "1 KB", exists: true}]
        var attachment = null
        tryVerify(function() { attachment = findChild(workspace, "previewAttachment-0"); return attachment !== null })
        tryVerify(function() { return attachment.imageAvailable })
        waitForRendering(workspace)
        mouseClick(attachment, attachment.width / 2, attachment.height / 2)
        var viewer = findChild(workspace, "attachmentImageViewer")
        verify(viewer !== null)
        tryCompare(viewer, "opened", true)
        compare(message.openedFile, -1)
        keyClick(Qt.Key_Escape)
        tryCompare(viewer, "opened", false)
    }
}
