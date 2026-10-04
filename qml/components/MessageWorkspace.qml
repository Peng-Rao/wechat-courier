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
    readonly property bool ownsTask: !!(
        taskBackend && taskBackend.kind === "message_send"
    )
    property bool monitorDismissed: false
    readonly property bool monitorVisible: root.ownsTask && !root.monitorDismissed

    function dismissMonitor() {
        root.monitorDismissed = true
    }

    function startTask() {
        if (root.interactionLocked) return
        if (taskBackend) taskBackend.startMessage()
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

        Item {
            RowLayout {
                anchors.fill: parent
                anchors.bottomMargin: 62
                spacing: 0

                ScrollView {
                    id: editorScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.width * 0.53
                    Layout.minimumWidth: 360
                    clip: true

                    ColumnLayout {
                        width: editorScroll.availableWidth
                        spacing: 10
                        enabled: !root.interactionLocked

                        Item { Layout.preferredHeight: 4 }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            Text {
                                text: "接收好友"
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTitle
                                font.bold: true
                                color: WxTheme.clTextPrimary
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: root.messageBackend ? root.messageBackend.recipientCount + " 人" : "0 人"
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                color: WxTheme.clTextHint
                            }
                        }

                        ScrollView {
                            id: recipientsScroll
                            Layout.fillWidth: true
                            Layout.preferredHeight: 126
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            contentWidth: availableWidth
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical: ScrollBar {
                                objectName: "messageRecipientsScrollBar"
                                policy: ScrollBar.AsNeeded
                                opacity: 1
                            }
                            background: WxGlassSurface {
                                fillColor: WxTheme.clFieldFill
                                borderColor: recipients.activeFocus ? WxTheme.clBorderFocus : WxTheme.clSurfaceBorder
                                focused: recipients.activeFocus
                            }
                            TextArea {
                            id: recipients
                            objectName: "messageRecipientsInput"
                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "messageRecipientsInput" : "接收人"
                            leftPadding: 12
                            rightPadding: 24
                            topPadding: 10
                            bottomPadding: 10
                            wrapMode: TextEdit.Wrap
                            placeholderText: "每行一个微信好友备注或微信名"
                            text: root.messageBackend ? root.messageBackend.recipientsText : ""
                            color: WxTheme.clTextPrimary
                            placeholderTextColor: WxTheme.clTextHint
                            selectionColor: WxTheme.clPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeNormal
                            onTextChanged: {
                                if (!root.interactionLocked && root.messageBackend
                                        && root.messageBackend.recipientsText !== text)
                                    root.messageBackend.recipientsText = text
                            }
                            background: null
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            Button {
                                text: "插入称呼占位符"
                                onClicked: template.insert(template.cursorPosition, "{name}")
                                contentItem: Text {
                                    text: parent.text
                                    color: WxTheme.clTextLink
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    color: parent.hovered ? WxTheme.clBgSelected : "transparent"
                                    border.color: WxTheme.clSurfaceBorder
                                    radius: WxTheme.radiusSmall
                                }
                            }
                            Text {
                                text: "发送前按好友备注生成称呼"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: "支持 {name}"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                        }

                        Text {
                            text: "消息模板"
                            Layout.leftMargin: 16
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeNormal
                            font.bold: true
                            color: WxTheme.clTextPrimary
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 150
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            contentWidth: availableWidth
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical: ScrollBar {
                                objectName: "messageTemplateScrollBar"
                                policy: ScrollBar.AsNeeded
                                opacity: 1
                            }
                            background: WxGlassSurface {
                                fillColor: WxTheme.clFieldFill
                                borderColor: template.activeFocus ? WxTheme.clBorderFocus : WxTheme.clSurfaceBorder
                                focused: template.activeFocus
                            }
                            TextArea {
                            id: template
                            objectName: "messageTemplateInput"
                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "messageTemplateInput" : "消息内容"
                            leftPadding: 12
                            rightPadding: 24
                            topPadding: 10
                            bottomPadding: 10
                            wrapMode: TextEdit.Wrap
                            placeholderText: "输入要发送的消息内容"
                            text: root.messageBackend ? root.messageBackend.templateText : ""
                            color: WxTheme.clTextPrimary
                            placeholderTextColor: WxTheme.clTextHint
                            selectionColor: WxTheme.clPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeNormal
                            onTextChanged: {
                                if (!root.interactionLocked && root.messageBackend
                                        && root.messageBackend.templateText !== text)
                                    root.messageBackend.templateText = text
                            }
                            background: null
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            Text {
                                text: "附件"
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeNormal
                                font.bold: true
                                color: WxTheme.clTextPrimary
                            }
                            Item { Layout.fillWidth: true }
                            Button {
                                objectName: "messageAddFileButton"
                                Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                    ? "messageAddFileButton" : "选择附件"
                                text: "＋ 选择文件"
                                onClicked: {
                                    if (!root.interactionLocked) messageFileDialog.open()
                                }
                                contentItem: Text {
                                    text: parent.text
                                    color: WxTheme.clTextPrimary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    color: parent.hovered ? WxTheme.clBgHover : WxTheme.clToolbarFill
                                    border.color: WxTheme.clSurfaceBorder
                                    radius: WxTheme.radiusSmall
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            Layout.preferredHeight: Math.max(64, attachmentList.contentHeight)
                            visible: root.messageBackend && root.messageBackend.filePaths.length > 0
                            color: WxTheme.clDropZoneFill
                            border.color: WxTheme.clSurfaceBorder
                            radius: WxTheme.radiusMedium

                            ListView {
                                id: attachmentList
                                anchors.fill: parent
                                model: root.messageBackend ? root.messageBackend.filePaths : []
                                interactive: false
                                delegate: Item {
                                    required property string modelData
                                    required property int index
                                    width: attachmentList.width
                                    height: 42
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 8
                                        WxIcon {
                                            iconSource: "../icons/file.svg"
                                            iconColor: WxTheme.clTextSecondary
                                            iconSize: 16
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.split(/[\\/]/).pop()
                                            elide: Text.ElideMiddle
                                            color: WxTheme.clTextPrimary
                                            font.family: WxTheme.fontFamily
                                            font.pixelSize: WxTheme.fontSizeSmall
                                        }
                                        Button {
                                            implicitWidth: 30
                                            objectName: "messageRemoveFileButton-" + index
                                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                                ? "messageRemoveFileButton-" + index : "移除附件"
                                            implicitHeight: 30
                                            onClicked: {
                                                if (!root.interactionLocked && root.messageBackend)
                                                    root.messageBackend.removeFile(index)
                                            }
                                            contentItem: Text {
                                                text: "×"
                                                color: WxTheme.clTextSecondary
                                                font.pixelSize: 17
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                            background: Rectangle {
                                                color: parent.hovered ? WxTheme.clBgHover : "transparent"
                                                radius: WxTheme.radiusSmall
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 60
                            Layout.leftMargin: 16
                            Layout.rightMargin: 16
                            color: dropMouse.containsMouse ? WxTheme.clBgSelected : WxTheme.clDropZoneFill
                            border.color: dropMouse.containsMouse ? WxTheme.clPrimary : WxTheme.clSurfaceBorder
                            radius: WxTheme.radiusMedium
                            Text {
                                anchors.centerIn: parent
                                text: "＋  拖放文件到这里，或点击选择文件"
                                color: WxTheme.clTextSecondary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
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
                                anchors.fill: parent
                                enabled: !root.interactionLocked
                                onDropped: function(drop) {
                                    if (root.interactionLocked || !root.messageBackend) return
                                    for (var i = 0; i < drop.urls.length; ++i)
                                        root.messageBackend.addFile(drop.urls[i])
                                }
                            }
                        }

                        Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: WxTheme.clSurfaceBorder
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.width * 0.47
                    Layout.minimumWidth: 300

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            color: WxTheme.clToolbarFill
                            border.color: WxTheme.clSurfaceBorder
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 16
                                anchors.verticalCenter: parent.verticalCenter
                                text: "消息预览"
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeNormal
                                font.bold: true
                                color: WxTheme.clTextPrimary
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 16
                                anchors.verticalCenter: parent.verticalCenter
                                text: root.messageBackend && root.messageBackend.recipientCount
                                    ? "预览 1 / " + root.messageBackend.recipientCount : "暂无收件人"
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                color: WxTheme.clTextHint
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 56
                            color: WxTheme.clPanelFill
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 10
                                Rectangle {
                                    width: 34
                                    height: 34
                                    radius: WxTheme.radiusMedium
                                    color: WxTheme.isDark ? "#476477" : "#7b98a9"
                                    Text {
                                        anchors.centerIn: parent
                                        text: "福"
                                        color: "white"
                                        font.bold: true
                                        font.family: WxTheme.fontFamily
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.messageBackend && root.messageBackend.previewTarget
                                            ? root.messageBackend.previewTarget : "等待选择好友"
                                        elide: Text.ElideRight
                                        color: WxTheme.clTextPrimary
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeNormal
                                        font.bold: true
                                    }
                                    Text {
                                        text: "称呼将在发送前核对"
                                        color: WxTheme.clTextHint
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeTiny
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: WxTheme.isDark ? "#171d21" : "#e9eff2"
                            ScrollView {
                                id: previewScroll
                                objectName: "messagePreviewScrollView"
                                anchors.fill: parent
                                clip: true
                                contentWidth: availableWidth
                                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                ColumnLayout {
                                    width: previewScroll.availableWidth
                                    spacing: 14
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        Layout.topMargin: 18
                                        Layout.bottomMargin: 18
                                        text: Qt.formatDateTime(new Date(), "yyyy年M月d日 hh:mm")
                                        color: WxTheme.clTextHint
                                        font.family: WxTheme.fontFamily
                                        font.pixelSize: WxTheme.fontSizeTiny
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.max(70, previewText.implicitHeight + 30)
                                        visible: !!(root.messageBackend && root.messageBackend.previewMessage)
                                        Rectangle {
                                            id: bubble
                                            anchors.right: parent.right
                                            anchors.rightMargin: 56
                                            width: Math.max(80, Math.min(parent.width - 84, 360))
                                            height: parent.height
                                            radius: WxTheme.radiusMedium
                                            color: WxTheme.clBubbleBg
                                            Text {
                                                id: previewText
                                                width: parent.width - 28
                                                x: 14
                                                y: 14
                                                text: root.messageBackend ? root.messageBackend.previewMessage : ""
                                                wrapMode: Text.Wrap
                                                color: WxTheme.isDark ? "#f1f7f2" : "#172217"
                                                font.family: WxTheme.fontFamily
                                                font.pixelSize: WxTheme.fontSizeNormal
                                            }
                                        }
                                        Rectangle {
                                            anchors.top: parent.top
                                            anchors.left: bubble.right
                                            anchors.leftMargin: 10
                                            width: 34; height: 34
                                            radius: WxTheme.radiusMedium
                                            color: WxTheme.isDark ? "#476477" : "#607f91"
                                            Text { anchors.centerIn: parent; text: "我"; color: "white"; font.bold: true; font.family: WxTheme.fontFamily }
                                        }
                                    }
                                    Repeater {
                                        model: root.messageBackend && root.messageBackend.attachmentPreviews
                                            ? root.messageBackend.attachmentPreviews : []
                                        delegate: Item {
                                            required property var modelData
                                            required property int index
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: filePreview.implicitHeight
                                            AttachmentPreview {
                                                id: filePreview
                                                objectName: "previewAttachment-" + index
                                                anchors.right: parent.right
                                                anchors.rightMargin: 56
                                                width: Math.max(80, Math.min(parent.width - 84, 360))
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
                                            Rectangle {
                                                anchors.top: parent.top
                                                anchors.left: filePreview.right
                                                anchors.leftMargin: 10
                                                width: 34; height: 34
                                                radius: WxTheme.radiusMedium
                                                color: WxTheme.isDark ? "#476477" : "#607f91"
                                                Text { anchors.centerIn: parent; text: "我"; color: "white"; font.bold: true; font.family: WxTheme.fontFamily }
                                            }
                                        }
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.max(140, previewScroll.availableHeight - 85)
                                        visible: !(root.messageBackend && (root.messageBackend.previewMessage
                                            || root.messageBackend.attachmentPreviews && root.messageBackend.attachmentPreviews.length))
                                        Column {
                                            anchors.centerIn: parent
                                            spacing: 8
                                            WxIcon { anchors.horizontalCenter: parent.horizontalCenter; iconSource: "../icons/chat_empty.svg"; iconColor: WxTheme.clTextHint; iconSize: 38 }
                                            Text { text: "暂无消息预览"; color: WxTheme.clTextHint; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                                        }
                                    }
                                    Item { Layout.preferredHeight: 16 }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 88
                            color: WxTheme.clToolbarFill
                            border.color: WxTheme.clSurfaceBorder
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                RowLayout {
                                    spacing: 14
                                    Repeater {
                                        model: ["●", "□", "■", "◷"]
                                        Text {
                                            required property string modelData
                                            text: modelData
                                            color: WxTheme.clTextSecondary
                                            font.pixelSize: 13
                                        }
                                    }
                                }
                                Text {
                                    text: "实际发送由独立 Agent 执行并逐项核对结果"
                                    color: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeTiny
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 62
                color: WxTheme.clToolbarFill
                border.color: WxTheme.clSurfaceBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 12

                    Text {
                        text: root.messageBackend
                            ? "随机间隔 " + root.messageBackend.intervalMin + "–" + root.messageBackend.intervalMax + " 秒"
                            : "随机间隔 2–3 秒"
                        color: WxTheme.clTextHint
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTiny
                    }
                    Item { Layout.fillWidth: true }
                    ColumnLayout {
                        spacing: 0
                        Text {
                            text: root.taskBackend && root.taskBackend.error ? root.taskBackend.error : "等待开始"
                            color: root.taskBackend && root.taskBackend.error ? WxTheme.clDangerNew : WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                            Layout.alignment: Qt.AlignRight
                        }
                        Text {
                            text: root.appBackend && root.appBackend.agent && root.appBackend.agent.automationReady
                                ? "微信 4.1.13.65 与 UIA 已就绪"
                                : root.appBackend && root.appBackend.agent && root.appBackend.agent.canStartTask
                                    ? "会话待恢复，开始时恢复窗口" : "请先连接受支持的微信"
                            color: WxTheme.clTextHint
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeTiny
                        }
                    }
                    Button {
                        objectName: "startMessageButton"
                        Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                            ? "startMessageButton" : text
                        text: "开始发送 " + (root.messageBackend ? root.messageBackend.recipientCount : 0) + " 人"
                        enabled: root.appBackend && root.appBackend.agent && root.appBackend.agent.canStartTask
                            && !root.interactionLocked
                            && root.messageBackend && root.messageBackend.recipientCount > 0
                        onClicked: root.startTask()
                        implicitHeight: 38
                        contentItem: Text {
                            text: parent.text
                            color: "white"
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            color: parent.enabled
                                ? (parent.hovered ? WxTheme.clPrimaryHover : WxTheme.clPrimary)
                                : WxTheme.clPrimaryDisabled
                            radius: WxTheme.radiusMedium
                        }
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
        title: "选择要发送的附件"
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            if (root.interactionLocked || !root.messageBackend) return
            for (var i = 0; i < selectedFiles.length; ++i)
                root.messageBackend.addFile(selectedFiles[i])
        }
    }
}
