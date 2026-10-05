import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "messageWorkspace"
    property var appBackend: null
    readonly property var messageBackend: appBackend ? appBackend.message : null
    readonly property var taskBackend: appBackend ? appBackend.task : null
    readonly property bool interactionLocked: !!(taskBackend && taskBackend.active)
    readonly property bool contactsBusy: !!(appBackend && appBackend.contacts && appBackend.contacts.busy)
    readonly property bool ownsTask: !!(
        taskBackend && taskBackend.kind === "message_send"
    )
    readonly property var attachmentPreviews: messageBackend && messageBackend.attachmentPreviews
        ? messageBackend.attachmentPreviews : []
    property bool monitorDismissed: false
    readonly property bool monitorVisible: root.ownsTask && !root.monitorDismissed

    function dismissMonitor() {
        root.monitorDismissed = true
    }

    function startTask() {
        if (root.interactionLocked) return
        if (taskBackend) taskBackend.startMessage()
    }

    onInteractionLockedChanged: {
        if (interactionLocked) {
            recipients.ContextMenu.menu.close()
            template.ContextMenu.menu.close()
            messageFileDialog.close()
        }
    }

    Connections {
        target: root.taskBackend
        ignoreUnknownSignals: true
        function onActiveChanged() {
            if (root.taskBackend.active && root.ownsTask)
                root.monitorDismissed = false
        }
        function onKindChanged() {
            if (root.taskBackend.active && root.ownsTask)
                root.monitorDismissed = false
        }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: root.monitorVisible ? 1 : 0

        ColumnLayout {
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 22
                Layout.bottomMargin: 18
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "工作区 / 消息"
                        color: WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                    }
                    Text {
                        objectName: "messagePageTitle"
                        text: "消息群发"
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTitle
                        font.weight: Font.DemiBold
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    objectName: "messageSearchMode"
                    text: root.messageBackend && root.messageBackend.fuzzySearchEnabled
                        ? "模糊搜索（取首个结果）" : "精确搜索"
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                }
            }

            ScrollView {
                id: bodyScroll
                objectName: "messageBodyScrollView"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                // Both panes fit beside the expanded sidebar at 960px.
                contentWidth: Math.max(744, availableWidth)
                contentHeight: availableHeight
                ScrollBar.horizontal: WxScrollBar {
                    objectName: "messageBodyHorizontalScrollBar"
                    parent: bodyScroll
                    x: bodyScroll.leftPadding
                    y: bodyScroll.height - height
                    width: bodyScroll.availableWidth
                    policy: ScrollBar.AsNeeded
                    visible: size < 1
                }
                ScrollBar.vertical.policy: ScrollBar.AlwaysOff

                RowLayout {
                    id: columns
                    x: 24
                    width: bodyScroll.contentWidth - 48
                    height: Math.max(1, bodyScroll.availableHeight - 22)
                    spacing: 24

                    ScrollView {
                        id: editorScroll
                        objectName: "messageEditorScrollView"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: (columns.width - columns.spacing) * 0.53
                        Layout.minimumWidth: 0
                        clip: true
                        rightPadding: 12
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ScrollBar.vertical: WxScrollBar {
                            objectName: "messageEditorScrollBar"
                            parent: editorScroll
                            x: editorScroll.mirrored ? 0 : editorScroll.width - width
                            y: editorScroll.topPadding
                            height: editorScroll.availableHeight
                            policy: ScrollBar.AsNeeded
                            visible: size < 1
                        }

                        ColumnLayout {
                            width: editorScroll.availableWidth
                            spacing: 20
                            enabled: !root.interactionLocked

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 7
                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 27
                                    Text {
                                        text: "接收好友"
                                        color: WxTheme.clTextPrimary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeNormal
                                        font.weight: Font.DemiBold
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        objectName: "messageRecipientCount"
                                        text: root.messageBackend ? root.messageBackend.recipientCount + " 人" : "0 人"
                                        color: WxTheme.clTextSecondary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeSmall
                                    }
                                }
                                ScrollView {
                                    id: recipientsScroll
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 128
                                    contentWidth: availableWidth
                                    clip: true
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    ScrollBar.vertical: WxScrollBar {
                                        objectName: "messageRecipientsScrollBar"
                                        parent: recipientsScroll
                                        x: recipientsScroll.mirrored ? 0 : recipientsScroll.width - width
                                        y: recipientsScroll.topPadding
                                        height: recipientsScroll.availableHeight
                                        policy: ScrollBar.AsNeeded
                                        visible: size < 1
                                    }
                                    background: Rectangle {
                                        objectName: "messageRecipientsSurface"
                                        color: WxTheme.clBgPrimary
                                        border.color: recipients.activeFocus ? WxTheme.clBorderFocus : WxTheme.clBorderStrong
                                        radius: WxTheme.radiusMedium
                                    }
                                    WxTextArea {
                                        id: recipients
                                        objectName: "messageRecipientsInput"
                                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                            ? "messageRecipientsInput" : "接收人"
                                        rightPadding: 24
                                        topPadding: 10
                                        bottomPadding: 10
                                        placeholderText: "每行一个微信好友备注或微信名"
                                        text: root.messageBackend ? root.messageBackend.recipientsText : ""
                                        readOnly: root.interactionLocked
                                        onTextChanged: {
                                            if (!root.interactionLocked && root.messageBackend
                                                    && root.messageBackend.recipientsText !== text)
                                                root.messageBackend.recipientsText = text
                                        }
                                        background: null
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 7
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "消息内容"
                                        color: WxTheme.clTextPrimary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeNormal
                                        font.weight: Font.DemiBold
                                    }
                                    Item { Layout.fillWidth: true }
                                    WxButton {
                                        objectName: "insertMessageNamePlaceholder"
                                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                            ? "insertMessageNamePlaceholder" : "插入称呼"
                                        quiet: true
                                        iconName: "text_cursor"
                                        text: "插入称呼"
                                        tooltipText: "插入 {name}"
                                        font.pixelSize: WxTheme.fontSizeSmall
                                        onClicked: {
                                            if (root.interactionLocked) return
                                            template.insert(template.cursorPosition, "{name}")
                                            template.forceActiveFocus()
                                        }
                                    }
                                }
                                ScrollView {
                                    id: templateScroll
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 156
                                    contentWidth: availableWidth
                                    clip: true
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    ScrollBar.vertical: WxScrollBar {
                                        objectName: "messageTemplateScrollBar"
                                        parent: templateScroll
                                        x: templateScroll.mirrored ? 0 : templateScroll.width - width
                                        y: templateScroll.topPadding
                                        height: templateScroll.availableHeight
                                        policy: ScrollBar.AsNeeded
                                        visible: size < 1
                                    }
                                    background: Rectangle {
                                        objectName: "messageTemplateSurface"
                                        color: WxTheme.clBgPrimary
                                        border.color: template.activeFocus ? WxTheme.clBorderFocus : WxTheme.clBorderStrong
                                        radius: WxTheme.radiusMedium
                                    }
                                    WxTextArea {
                                        id: template
                                        objectName: "messageTemplateInput"
                                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                            ? "messageTemplateInput" : "消息内容"
                                        rightPadding: 24
                                        topPadding: 10
                                        bottomPadding: 10
                                        placeholderText: "输入要发送的消息内容"
                                        text: root.messageBackend ? root.messageBackend.templateText : ""
                                        readOnly: root.interactionLocked
                                        onTextChanged: {
                                            if (!root.interactionLocked && root.messageBackend
                                                    && root.messageBackend.templateText !== text)
                                                root.messageBackend.templateText = text
                                        }
                                        background: null
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "附件"
                                        color: WxTheme.clTextPrimary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeNormal
                                        font.weight: Font.DemiBold
                                    }
                                    Item { Layout.fillWidth: true }
                                    WxButton {
                                        objectName: "messageAddFileButton"
                                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                            ? "messageAddFileButton" : "选择附件"
                                        quiet: true
                                        iconName: "file"
                                        text: "添加文件"
                                        font.pixelSize: WxTheme.fontSizeSmall
                                        onClicked: {
                                            if (!root.interactionLocked) messageFileDialog.open()
                                        }
                                    }
                                }

                                ListView {
                                    id: attachmentList
                                    objectName: "messageAttachmentList"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: contentHeight
                                    visible: count > 0
                                    model: root.messageBackend ? root.messageBackend.filePaths : []
                                    interactive: false
                                    spacing: 7
                                    delegate: Rectangle {
                                        required property string modelData
                                        required property int index
                                        readonly property var attachment: root.attachmentPreviews[index] || ({})
                                        width: attachmentList.width
                                        height: 56
                                        radius: WxTheme.radiusMedium
                                        color: WxTheme.clBgPrimary
                                        border.color: WxTheme.clSurfaceBorder
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 8
                                            spacing: 10
                                            Rectangle {
                                                Layout.preferredWidth: 32
                                                Layout.preferredHeight: 34
                                                color: WxTheme.clBgSecondary
                                                radius: WxTheme.radiusSmall
                                                WxIcon {
                                                    anchors.centerIn: parent
                                                    iconSource: "../icons/file.svg"
                                                    iconColor: WxTheme.clTextSecondary
                                                    iconSize: 20
                                                }
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                spacing: 2
                                                Text {
                                                    objectName: "messageAttachmentName-" + index
                                                    Layout.fillWidth: true
                                                    text: attachment.name || modelData.split(/[\\/]/).pop()
                                                    elide: Text.ElideMiddle
                                                    color: WxTheme.clTextPrimary
                                                    font.family: WxTheme.fontFamily
                                                    font.pixelSize: WxTheme.fontSizeSmall
                                                    font.weight: Font.Medium
                                                }
                                                Text {
                                                    objectName: "messageAttachmentMetadata-" + index
                                                    Layout.fillWidth: true
                                                    text: attachment.exists === false ? "文件不可用"
                                                        : [(attachment.type || "文件").toUpperCase(), attachment.sizeLabel || ""].filter(Boolean).join(" · ")
                                                    elide: Text.ElideRight
                                                    color: attachment.exists === false ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                                                    font.family: WxTheme.fontFamily
                                                    font.pixelSize: WxTheme.fontSizeSmall
                                                }
                                            }
                                            WxButton {
                                                objectName: "messageRemoveFileButton-" + index
                                                Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                                    ? "messageRemoveFileButton-" + index : "移除附件"
                                                quiet: true
                                                iconName: "trash"
                                                tooltipText: "移除附件"
                                                onClicked: {
                                                    if (!root.interactionLocked && root.messageBackend)
                                                        root.messageBackend.removeFile(index)
                                                }
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 54
                                    color: dropMouse.containsMouse || attachmentDrop.containsDrag
                                        ? WxTheme.clBgSelected : WxTheme.clBgPrimary
                                    border.color: dropMouse.containsMouse || attachmentDrop.containsDrag
                                        ? WxTheme.clPrimary : WxTheme.clBorderStrong
                                    radius: WxTheme.radiusMedium
                                    RowLayout {
                                        anchors.centerIn: parent
                                        spacing: 7
                                        WxIcon {
                                            iconSource: "../icons/folder_open.svg"
                                            iconColor: WxTheme.clTextSecondary
                                            iconSize: 16
                                        }
                                        Text {
                                            text: "拖入文件或选择附件"
                                            color: WxTheme.clTextSecondary
                                            font.family: WxTheme.fontFamily
                                            font.pixelSize: WxTheme.fontSizeSmall
                                        }
                                    }
                                    MouseArea {
                                        id: dropMouse
                                        anchors.fill: parent
                                        enabled: !root.interactionLocked
                                        hoverEnabled: true
                                        onClicked: {
                                            if (!root.interactionLocked) messageFileDialog.open()
                                        }
                                    }
                                    DropArea {
                                        id: attachmentDrop
                                        anchors.fill: parent
                                        enabled: !root.interactionLocked
                                        onDropped: function(drop) {
                                            if (root.interactionLocked || !root.messageBackend) return
                                            for (var i = 0; i < drop.urls.length; ++i)
                                                root.messageBackend.addFile(drop.urls[i])
                                        }
                                    }
                                }
                            }
                            Item { Layout.preferredHeight: 2 }
                        }
                    }

                    Rectangle {
                        objectName: "messagePreviewPane"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: (columns.width - columns.spacing) * 0.47
                        Layout.minimumWidth: 0
                        color: WxTheme.clBgPrimary
                        border.color: WxTheme.clSurfaceBorder
                        radius: WxTheme.radiusLarge
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 1
                            spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 43
                                Layout.leftMargin: 14
                                Layout.rightMargin: 14
                                Text {
                                    text: "消息预览"
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: root.messageBackend && root.messageBackend.recipientCount
                                        ? "1 / " + root.messageBackend.recipientCount : "暂无收件人"
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: WxTheme.clSurfaceBorder }
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 66
                                Layout.leftMargin: 16
                                Layout.rightMargin: 16
                                spacing: 10
                                Image {
                                    objectName: "defaultBrandAvatar"
                                    Layout.preferredWidth: 36
                                    Layout.preferredHeight: 36
                                    source: "../../assets/fuge-logo-64.png"
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        objectName: "messagePreviewTarget"
                                        Layout.fillWidth: true
                                        text: root.messageBackend && root.messageBackend.previewTarget
                                            ? root.messageBackend.previewTarget : "等待选择好友"
                                        elide: Text.ElideRight
                                        color: WxTheme.clTextPrimary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeNormal
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: "发送前核对会话与内容"
                                        color: WxTheme.clTextSecondary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeSmall
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                color: WxTheme.clBgSecondary
                                ScrollView {
                                    id: previewScroll
                                    objectName: "messagePreviewScrollView"
                                    anchors.fill: parent
                                    clip: true
                                    contentWidth: availableWidth
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    ScrollBar.vertical: WxScrollBar {
                                        objectName: "messagePreviewScrollBar"
                                        parent: previewScroll
                                        x: previewScroll.mirrored ? 0 : previewScroll.width - width
                                        y: previewScroll.topPadding
                                        height: previewScroll.availableHeight
                                        policy: ScrollBar.AsNeeded
                                        visible: size < 1
                                    }
                                    ColumnLayout {
                                        width: previewScroll.availableWidth
                                        spacing: 14
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            Layout.topMargin: 18
                                            Layout.bottomMargin: 10
                                            text: Qt.formatDateTime(new Date(), "yyyy年M月d日 hh:mm")
                                            color: WxTheme.clTextHint
                                            font.family: WxTheme.fontFamily
                                            font.pixelSize: WxTheme.fontSizeSmall
                                        }
                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: previewText.implicitHeight + 28
                                            visible: !!(root.messageBackend && root.messageBackend.previewMessage)
                                            Rectangle {
                                                id: bubble
                                                anchors.right: parent.right
                                                anchors.rightMargin: 52
                                                width: Math.max(80, Math.min(parent.width - 70, 360))
                                                height: parent.height
                                                radius: WxTheme.radiusMedium
                                                color: WxTheme.clBgPrimary
                                                border.color: WxTheme.clSurfaceBorder
                                                Text {
                                                    id: previewText
                                                    objectName: "messagePreviewText"
                                                    width: parent.width - 28
                                                    x: 14
                                                    y: 14
                                                    text: root.messageBackend ? root.messageBackend.previewMessage : ""
                                                    wrapMode: Text.Wrap
                                                    color: WxTheme.clTextPrimary
                                                    font.family: WxTheme.fontFamily
                                                    font.pixelSize: WxTheme.fontSizeNormal
                                                }
                                            }
                                            Image {
                                                anchors.top: parent.top
                                                anchors.left: bubble.right
                                                anchors.leftMargin: 8
                                                width: 29
                                                height: 29
                                                source: "../../assets/fuge-logo-64.png"
                                                fillMode: Image.PreserveAspectFit
                                            }
                                        }
                                        Repeater {
                                            model: root.attachmentPreviews
                                            delegate: Item {
                                                required property var modelData
                                                required property int index
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: filePreview.implicitHeight
                                                AttachmentPreview {
                                                    id: filePreview
                                                    objectName: "previewAttachment-" + index
                                                    anchors.right: parent.right
                                                    anchors.rightMargin: 52
                                                    width: Math.max(80, Math.min(parent.width - 70, 320))
                                                    height: implicitHeight
                                                    attachment: modelData
                                                    fileIndex: index
                                                    onImageRequested: function(source, name) {
                                                        imageViewer.sourceUrl = source
                                                        imageViewer.fileName = name
                                                        imageViewer.open()
                                                    }
                                                    onFileRequested: function(fileIndex) {
                                                        if (root.messageBackend) root.messageBackend.openAttachment(fileIndex)
                                                    }
                                                }
                                                Image {
                                                    anchors.top: parent.top
                                                    anchors.left: filePreview.right
                                                    anchors.leftMargin: 8
                                                    width: 29
                                                    height: 29
                                                    source: "../../assets/fuge-logo-64.png"
                                                    fillMode: Image.PreserveAspectFit
                                                }
                                            }
                                        }
                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: Math.max(140, previewScroll.availableHeight - 85)
                                            visible: !(root.messageBackend && (root.messageBackend.previewMessage
                                                || root.attachmentPreviews.length))
                                            Column {
                                                anchors.centerIn: parent
                                                spacing: 8
                                                WxIcon {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    iconSource: "../icons/chat_empty.svg"
                                                    iconColor: WxTheme.clTextHint
                                                    iconSize: 38
                                                }
                                                Text {
                                                    text: "暂无消息预览"
                                                    color: WxTheme.clTextHint
                                                    font.family: WxTheme.fontFamily
                                                    font.pixelSize: WxTheme.fontSizeSmall
                                                }
                                            }
                                        }
                                        Item { Layout.preferredHeight: 16 }
                                    }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: WxTheme.clSurfaceBorder }
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                Layout.leftMargin: 8
                                Layout.rightMargin: 8
                                text: "逐条发送 · 未确认结果不自动重发"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: WxTheme.clTextSecondary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(70, footerSummary.implicitHeight + 24)
                color: WxTheme.clBgPrimary
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: WxTheme.clSurfaceBorder }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 24
                    anchors.rightMargin: 24
                    spacing: 16
                    Rectangle {
                        Layout.preferredWidth: 7
                        Layout.preferredHeight: 7
                        radius: 4
                        color: root.taskBackend && root.taskBackend.error ? WxTheme.clDangerNew
                            : root.appBackend && root.appBackend.agent && root.appBackend.agent.canStartTask
                                ? WxTheme.clSuccessText : WxTheme.clWarningText
                    }
                    ColumnLayout {
                        id: footerSummary
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            Layout.fillWidth: true
                            text: root.taskBackend && root.taskBackend.error ? root.taskBackend.error
                                : root.appBackend && root.appBackend.agent && root.appBackend.agent.automationReady
                                    ? "准备就绪" : root.appBackend && root.appBackend.agent && root.appBackend.agent.canStartTask
                                        ? "会话待恢复，开始时恢复窗口" : "请先连接受支持的微信"
                            wrapMode: Text.Wrap
                            color: root.taskBackend && root.taskBackend.error ? WxTheme.clDangerNew : WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeNormal
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: (root.messageBackend ? root.messageBackend.recipientCount : 0) + " 位收件人 · 随机间隔 "
                                + (root.messageBackend ? root.messageBackend.intervalMin + "–" + root.messageBackend.intervalMax : "2–3") + " 秒"
                            wrapMode: Text.Wrap
                            color: WxTheme.clTextSecondary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                        }
                    }
                    WxButton {
                        objectName: "startMessageButton"
                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                            ? "startMessageButton" : text
                        primary: true
                        iconName: "send"
                        text: "开始发送 " + (root.messageBackend ? root.messageBackend.recipientCount : 0) + " 人"
                        enabled: root.appBackend && root.appBackend.agent && root.appBackend.agent.canStartTask
                            && !root.interactionLocked
                            && !root.contactsBusy
                            && root.messageBackend && root.messageBackend.recipientCount > 0
                        onClicked: root.startTask()
                    }
                }
            }
        }

        TaskMonitor {
            taskBackend: root.taskBackend
            agentBackend: root.appBackend ? root.appBackend.agent : null
            taskKind: "message_send"
            onRequestEdit: root.dismissMonitor()
        }
    }

    AttachmentImageViewer {
        id: imageViewer
        parent: root
    }

    FileDialog {
        id: messageFileDialog
        objectName: "messageFileDialog"
        title: "选择要发送的附件"
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            if (root.interactionLocked || !root.messageBackend) return
            for (var i = 0; i < selectedFiles.length; ++i)
                root.messageBackend.addFile(selectedFiles[i])
        }
    }
}
