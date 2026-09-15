import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "friendWorkspace"
    property var appBackend: null
    readonly property var friendBackend: appBackend ? appBackend.friends : null
    readonly property var taskBackend: appBackend ? appBackend.task : null
    readonly property bool interactionLocked: !!(taskBackend && taskBackend.active)
    readonly property bool friendSubmitAvailable: !!(
        taskBackend && taskBackend.acceptanceEnabled
        || appBackend && appBackend.agent
            && appBackend.agent.friendSubmitEnabled === true
    )
    readonly property bool ownsTask: !!(
        taskBackend && taskBackend.kind === "friend_add"
    )
    property bool monitorDismissed: false
    readonly property bool monitorVisible: root.ownsTask && !root.monitorDismissed
    property int contextRow: -1

    function startTask() {
        if (root.interactionLocked) return
        if (taskBackend) taskBackend.startFriends()
    }

    function dismissMonitor() {
        root.monitorDismissed = true
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

    function requestFriendStart() {
        if (root.interactionLocked || !root.friendSubmitAvailable) return
        if (root.taskBackend && root.taskBackend.acceptanceEnabled) {
            root.startTask()
            return
        }
        friendSubmitConfirmDialog.open()
    }

    function confirmFriendSubmission() {
        if (root.interactionLocked || !root.friendSubmitAvailable
                || !root.taskBackend || root.taskBackend.acceptanceEnabled)
            return
        root.startTask()
    }

    onInteractionLockedChanged: {
        if (root.interactionLocked)
            friendSubmitConfirmDialog.close()
    }

    function appendManualRecord() {
        if (root.interactionLocked || !root.friendBackend) return -1
        var row = root.friendBackend.model.appendEmptyRecord()
        if (row >= 0) {
            Qt.callLater(function() {
                if (root.friendBackend && row < root.friendBackend.model.count)
                    friendTable.positionViewAtRow(row, TableView.Contain)
            })
        }
        return row
    }

    function removeContextRecord() {
        if (root.interactionLocked || !root.friendBackend || root.contextRow < 0)
            return false
        var removed = root.friendBackend.model.removeRecord(root.contextRow)
        root.contextRow = -1
        return removed
    }

    function clearFriendTable() {
        if (root.interactionLocked || !root.friendBackend
                || root.friendBackend.model.count === 0)
            return false
        friendContextMenu.close()
        root.contextRow = -1
        return root.friendBackend.model.clearRecords()
    }

    function openTableContextMenu(row) {
        if (root.interactionLocked || !root.friendBackend) return
        root.contextRow = row >= 0 && row < root.friendBackend.model.count ? row : -1
        friendContextMenu.popup()
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: root.monitorVisible ? 1 : 0

        Item {
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 70
                    color: WxTheme.clPanelFill
                    border.color: WxTheme.clSurfaceBorder

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 10
                        ColumnLayout {
                            spacing: 2
                            Text {
                                text: "待添加账号"
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTitle
                                font.bold: true
                            }
                            Text {
                                text: "可导入或右键新增/删除，单元格可直接编辑；每次最多执行 20 条选中记录"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "下载模板"
                            enabled: !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked) templateDialog.open()
                            }
                            contentItem: Text {
                                text: parent.text
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                color: parent.hovered ? WxTheme.clBgHover : WxTheme.clToolbarFill
                                border.color: WxTheme.clSurfaceBorder
                                radius: WxTheme.radiusSmall
                            }
                        }
                        Button {
                            objectName: "importFriendsButton"
                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "importFriendsButton" : text
                            text: "＋ 导入 Excel / CSV"
                            enabled: !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked) importDialog.open()
                            }
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
                                radius: WxTheme.radiusSmall
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    color: WxTheme.clToolbarFill
                    border.color: WxTheme.clSurfaceBorder
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 16
                        Text {
                            text: root.friendBackend
                                ? "共 " + root.friendBackend.model.count + " 条"
                                    + "    有效 " + root.friendBackend.model.validCount
                                    + "    异常 " + (root.friendBackend.model.count - root.friendBackend.model.validCount)
                                : "尚未导入"
                            color: WxTheme.clTextSecondary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeTiny
                        }
                        Text {
                            visible: root.friendBackend && root.friendBackend.model.importError
                            text: root.friendBackend ? root.friendBackend.model.importError : ""
                            color: WxTheme.clDangerNew
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeTiny
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: root.friendBackend
                                ? "已选择 " + root.friendBackend.model.selectedCount + " / 20" : "已选择 0 / 20"
                            color: WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                        }
                        Button {
                            text: "选择前 20 条"
                            enabled: root.friendBackend && !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked && root.friendBackend)
                                    root.friendBackend.model.selectFirstValid()
                            }
                        }
                        Button {
                            objectName: "clearFriendTableButton"
                            text: "清空表格"
                            enabled: root.friendBackend && root.friendBackend.model.count > 0
                                && !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked) root.clearFriendTable()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 38
                    color: WxTheme.clToolbarFill
                    border.color: WxTheme.clSurfaceBorder
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 0
                        Text { text: "选择"; Layout.preferredWidth: 54; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                        Text { text: "序号"; Layout.preferredWidth: 48; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                        Text { text: "账号"; Layout.preferredWidth: 220; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                        Text { text: "打招呼语"; Layout.fillWidth: true; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                        Text { text: "备注"; Layout.preferredWidth: 180; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                        Text { text: "状态"; Layout.preferredWidth: 110; color: WxTheme.clTextHint; font.pixelSize: WxTheme.fontSizeTiny }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    TableView {
                        id: friendTable
                        objectName: "friendImportTable"
                        anchors.fill: parent
                        clip: true
                        model: root.friendBackend ? root.friendBackend.model : null
                        columnWidthProvider: function(column) { return width }
                        rowHeightProvider: function(row) { return 46 }
                        delegate: Rectangle {
                            required property int row
                            required property string account
                            required property string greeting
                            required property string remark
                            required property bool valid
                            required property string error
                            required property string status
                            required property bool selected
                            implicitWidth: friendTable.width
                            implicitHeight: 46
                            color: !valid ? WxTheme.clDangerSoft
                                : selected ? (row % 2 ? WxTheme.clRowAlternate : "transparent")
                                : "transparent"
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 1
                                color: WxTheme.clSurfaceBorder
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 0
                                CheckBox {
                                    Layout.preferredWidth: 54
                                    checked: selected
                                    enabled: valid && !root.interactionLocked
                                    onToggled: {
                                        if (!root.interactionLocked && root.friendBackend)
                                            root.friendBackend.model.setSelected(row, checked)
                                    }
                                }
                                Text {
                                    text: String(row + 1).padStart(2, "0")
                                    Layout.preferredWidth: 48
                                    color: WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                }
                                TextField {
                                    objectName: "friendAccountField"
                                    Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                        ? "friendAccountField" : "好友账号"
                                    Layout.preferredWidth: 220
                                    readonly property int modelRow: parent.parent.row
                                    text: account
                                    enabled: !root.interactionLocked
                                    color: WxTheme.clTextPrimary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    onEditingFinished: {
                                        if (!root.interactionLocked && root.friendBackend)
                                            root.friendBackend.model.setCell(modelRow, "account", text)
                                    }
                                    background: Rectangle {
                                        color: parent.activeFocus ? WxTheme.clFieldFill : "transparent"
                                        border.color: parent.activeFocus ? WxTheme.clBorderFocus : "transparent"
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                                TextField {
                                    Layout.fillWidth: true
                                    text: greeting
                                    placeholderText: "使用全局默认值"
                                    enabled: !root.interactionLocked
                                    color: WxTheme.clTextPrimary
                                    placeholderTextColor: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    onEditingFinished: {
                                        if (!root.interactionLocked && root.friendBackend)
                                            root.friendBackend.model.setCell(row, "greeting", text)
                                    }
                                    background: Rectangle {
                                        color: parent.activeFocus ? WxTheme.clFieldFill : "transparent"
                                        border.color: parent.activeFocus ? WxTheme.clBorderFocus : "transparent"
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                                TextField {
                                    Layout.preferredWidth: 180
                                    text: remark
                                    placeholderText: "使用全局默认值"
                                    enabled: !root.interactionLocked
                                    color: WxTheme.clTextPrimary
                                    placeholderTextColor: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    onEditingFinished: {
                                        if (!root.interactionLocked && root.friendBackend)
                                            root.friendBackend.model.setCell(row, "remark", text)
                                    }
                                    background: Rectangle {
                                        color: parent.activeFocus ? WxTheme.clFieldFill : "transparent"
                                        border.color: parent.activeFocus ? WxTheme.clBorderFocus : "transparent"
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                                Item {
                                    Layout.preferredWidth: 110
                                    Layout.fillHeight: true
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: Math.min(100, statusText.implicitWidth + 18)
                                        height: 24
                                        radius: WxTheme.radiusSmall
                                        color: !valid ? WxTheme.clDangerSoft
                                            : status === "working" ? WxTheme.clInfoSoft
                                            : status === "success" ? WxTheme.clSuccessSoft
                                            : status === "unknown" ? WxTheme.clWarningSoft
                                            : WxTheme.clNeutralSoft
                                        Text {
                                            id: statusText
                                            anchors.centerIn: parent
                                            text: !valid ? error
                                                : status === "working" ? "执行中"
                                                : status === "success"
                                                    ? (root.taskBackend && root.taskBackend.acceptanceEnabled
                                                        ? "预检完成" : "已提交")
                                                : status === "error" ? "执行异常"
                                                : status === "unknown" ? "结果未知"
                                                : (root.taskBackend && root.taskBackend.acceptanceEnabled
                                                    ? "预检通过" : "待提交")
                                            elide: Text.ElideRight
                                            color: !valid || status === "error" ? WxTheme.clDangerNew
                                                : status === "working" ? WxTheme.clInfo
                                                : status === "success" ? WxTheme.clSuccessText
                                                : status === "unknown" ? WxTheme.clWarningText
                                                : WxTheme.clTextSecondary
                                            font.family: WxTheme.fontFamily
                                            font.pixelSize: WxTheme.fontSizeTiny
                                            font.bold: true
                                        }
                                    }
                                }
                            }
                        }
                    }

                    MouseArea {
                        id: tableContextOverlay
                        objectName: "friendTableContextOverlay"
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        enabled: !root.interactionLocked
                        z: 10
                        onClicked: function(mouse) {
                            var contentPosition = friendTable.contentItem.mapFromItem(
                                tableContextOverlay, mouse.x, mouse.y)
                            var cell = friendTable.cellAtPosition(
                                contentPosition.x, contentPosition.y)
                            root.openTableContextMenu(cell.y)
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 88
                    color: WxTheme.clToolbarFill
                    border.color: WxTheme.clSurfaceBorder
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 14
                        ColumnLayout {
                            spacing: 2
                            Text {
                                text: "全局默认值"
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: true
                            }
                            Text {
                                text: "行内为空时使用；两处均为空则保留微信原文"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                        }
                        TextField {
                            Layout.preferredWidth: 300
                            placeholderText: "默认打招呼语"
                            text: root.friendBackend ? root.friendBackend.defaultGreeting : ""
                            enabled: !root.interactionLocked
                            onEditingFinished: {
                                if (!root.interactionLocked && root.friendBackend)
                                    root.friendBackend.defaultGreeting = text
                            }
                            color: WxTheme.clTextPrimary
                            background: WxGlassSurface {
                                fillColor: WxTheme.clFieldFill
                                focused: parent.activeFocus
                            }
                        }
                        TextField {
                            Layout.preferredWidth: 150
                            placeholderText: "默认备注"
                            text: root.friendBackend ? root.friendBackend.defaultRemark : ""
                            enabled: !root.interactionLocked
                            onEditingFinished: {
                                if (!root.interactionLocked && root.friendBackend)
                                    root.friendBackend.defaultRemark = text
                            }
                            color: WxTheme.clTextPrimary
                            background: WxGlassSurface {
                                fillColor: WxTheme.clFieldFill
                                focused: parent.activeFocus
                            }
                        }
                        Item { Layout.fillWidth: true }
                        ColumnLayout {
                            spacing: 1
                            Text {
                                text: root.taskBackend && root.taskBackend.error ? root.taskBackend.error : "等待开始"
                                color: root.taskBackend && root.taskBackend.error ? WxTheme.clDangerNew : WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: true
                                Layout.alignment: Qt.AlignRight
                            }
                            Text {
                                text: root.friendBackend
                                    ? "随机间隔 " + root.friendBackend.intervalMin + "–" + root.friendBackend.intervalMax + " 秒"
                                    : "随机间隔 15–30 秒"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                        }
                        ColumnLayout {
                            spacing: 1
                            Text {
                                text: root.taskBackend && root.taskBackend.acceptanceEnabled
                                    ? "仅填写并核对表单" : "将实际提交好友申请"
                                color: WxTheme.clWarningText
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: true
                                Layout.alignment: Qt.AlignRight
                            }
                            Text {
                                text: root.taskBackend && root.taskBackend.acceptanceEnabled
                                    ? "验收模式不会点击最终确定"
                                    : !root.friendSubmitAvailable
                                        ? "Agent 提交能力不可用"
                                        : root.appBackend && root.appBackend.agent.canStartTask
                                            && !root.appBackend.agent.automationReady
                                            ? "会话待恢复 · 确认后将逐条提交"
                                            : "确认后将逐条提交，提交后无法撤回"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                Layout.alignment: Qt.AlignRight
                            }
                        }
                        Button {
                            objectName: "startFriendsButton"
                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "startFriendsButton" : text
                            text: (root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "开始表单预检 " : "开始添加好友 ")
                                + (root.friendBackend ? root.friendBackend.model.selectedCount : 0) + " 人"
                            enabled: root.appBackend && root.appBackend.agent.canStartTask
                                && !root.interactionLocked
                                && root.friendSubmitAvailable
                                && root.friendBackend && root.friendBackend.model.selectedCount > 0
                            onClicked: root.requestFriendStart()
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
        }

        TaskMonitor {
            taskBackend: root.taskBackend
            agentBackend: root.appBackend ? root.appBackend.agent : null
            taskKind: "friend_add"
            onRequestEdit: root.dismissMonitor()
        }
    }

    ConfirmDialog {
        id: friendSubmitConfirmDialog
        objectName: "friendSubmitConfirmDialog"
        z: 1000
        message: "即将向选中的 "
            + (root.friendBackend ? root.friendBackend.model.selectedCount : 0)
            + " 个账号实际提交好友申请。提交后无法撤回，请确认账号和申请内容无误。"
        confirmText: "确认提交"
        cancelText: "取消"
        isDanger: true
        confirmEnabled: !root.interactionLocked && root.friendSubmitAvailable
        confirmButtonObjectName: "friendSubmitConfirmButton"
        cancelButtonObjectName: "friendSubmitCancelButton"
        onConfirmed: root.confirmFriendSubmission()
    }

    WxContextMenu {
        id: friendContextMenu
        objectName: "friendContextMenu"

        WxContextMenuItem {
            objectName: "addFriendRowMenuItem"
            text: "新增一行"
            enabled: !root.interactionLocked
            onTriggered: root.appendManualRecord()
        }

        MenuSeparator {
            visible: root.contextRow >= 0
            height: visible ? implicitHeight : 0
            background: Rectangle {
                implicitHeight: 1
                color: WxTheme.clDivider
            }
        }

        WxContextMenuItem {
            objectName: "removeFriendRowMenuItem"
            text: "删除此行"
            iconSource: "../icons/trash.svg"
            iconColor: WxTheme.clDangerNew
            hoverIconColor: WxTheme.clDangerNewHover
            visible: root.contextRow >= 0
            height: visible ? implicitHeight : 0
            enabled: !root.interactionLocked
            onTriggered: root.removeContextRecord()
        }
    }

    FileDialog {
        id: importDialog
        title: "导入好友账号"
        nameFilters: ["Excel / CSV (*.xlsx *.csv)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (!root.interactionLocked && root.friendBackend)
                root.friendBackend.importFile(selectedFile)
        }
    }

    FileDialog {
        id: templateDialog
        title: "保存好友导入模板"
        nameFilters: ["Excel 文件 (*.xlsx)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "xlsx"
        onAccepted: {
            if (!root.interactionLocked && root.friendBackend)
                root.friendBackend.createTemplate(selectedFile)
        }
    }
}
