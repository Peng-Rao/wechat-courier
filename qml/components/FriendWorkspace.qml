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
    readonly property bool contactsBusy: !!(appBackend && appBackend.contacts && appBackend.contacts.busy)
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
    property int currentRow: -1
    property int previewRevision: 0
    readonly property int tableRowHeight: 40
    readonly property var columnWidths: [44, 60, 112, 186, 126, 240, 180, 110]
    readonly property int tableContentWidth: columnWidths.reduce(function(sum, value) { return sum + value }, 0)
    property var activeCellEditor: null
    property var activeTextMenu: null
    property int currentFieldIndex: 0
    readonly property var currentPreview: {
        var revision = previewRevision
        return friendBackend && currentRow >= 0 ? friendBackend.model.preview(currentRow) : ({})
    }

    Connections {
        target: root.friendBackend ? root.friendBackend.model : null
        ignoreUnknownSignals: true
        function onCountsChanged() {
            if (root.currentRow >= root.friendBackend.model.count)
                root.currentRow = root.friendBackend.model.count - 1
            if (root.currentRow < 0 && root.friendBackend.model.count > 0)
                root.currentRow = 0
            ++root.previewRevision
        }
        function onModelReset() {
            root.cancelCellEdit()
            root.currentRow = root.friendBackend.model.count > 0 ? 0 : -1
            ++root.previewRevision
            rangeStart.text = "1"
            rangeEnd.text = String(Math.max(1, Math.min(root.friendBackend.model.count, root.friendBackend.batchLimit)))
            Qt.callLater(function() {
                friendTable.forceLayout()
                if (root.friendBackend && root.friendBackend.model.count > 0)
                    friendTable.positionViewAtRow(0, TableView.Contain)
                else
                    friendTable.contentY = 0
            })
        }
    }
    Component.onCompleted: {
        if (root.friendBackend && root.friendBackend.model.count > 0) root.currentRow = 0
    }

    function insertPlaceholder(value) {
        if (root.interactionLocked || !root.friendBackend) return
        globalGreetingField.insert(globalGreetingField.cursorPosition, value)
        root.friendBackend.defaultGreeting = globalGreetingField.text
        globalGreetingField.forceActiveFocus()
    }

    function startTask() {
        if (root.interactionLocked) return
        if (taskBackend) taskBackend.startFriends()
    }

    function dismissMonitor() {
        root.monitorDismissed = true
        if (root.taskBackend && root.taskBackend.riskStopModelRow >= 0) {
            root.currentRow = root.taskBackend.riskStopModelRow
            Qt.callLater(function() {
                friendTable.forceLayout()
                friendTable.positionViewAtRow(root.currentRow, TableView.Contain)
            })
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

    function requestFriendStart() {
        if (root.interactionLocked || !root.friendSubmitAvailable) return
        root.commitCellEdit()
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
        if (root.interactionLocked) {
            root.cancelCellEdit()
            if (root.activeTextMenu) root.activeTextMenu.close()
            friendContextMenu.close()
            friendSubmitConfirmDialog.close()
        }
    }

    function appendManualRecord() {
        if (root.interactionLocked || !root.friendBackend) return -1
        root.commitCellEdit()
        var row = root.friendBackend.model.appendEmptyRecord()
        if (row >= 0) {
            root.currentRow = row
            Qt.callLater(function() {
                if (root.friendBackend && row < root.friendBackend.model.count) {
                    friendTable.forceLayout()
                    friendTable.positionViewAtRow(row, TableView.Contain)
                }
            })
        }
        return row
    }

    function removeContextRecord() {
        if (root.interactionLocked || !root.friendBackend || root.contextRow < 0)
            return false
        root.cancelCellEdit()
        var removed = root.friendBackend.model.removeRecord(root.contextRow)
        root.contextRow = -1
        return removed
    }

    function clearFriendTable() {
        if (root.interactionLocked || !root.friendBackend
                || root.friendBackend.model.count === 0)
            return false
        friendContextMenu.close()
        root.cancelCellEdit()
        root.contextRow = -1
        return root.friendBackend.model.clearRecords()
    }

    function openTableContextMenu(row) {
        if (root.interactionLocked || !root.friendBackend) return
        root.contextRow = row >= 0 && row < root.friendBackend.model.count ? row : -1
        if (root.contextRow >= 0) root.currentRow = root.contextRow
        friendContextMenu.popup()
    }

    function cancelCellEdit() {
        if (root.activeCellEditor) root.activeCellEditor.cancelEdit()
    }

    function commitCellEdit() {
        if (root.activeCellEditor) root.activeCellEditor.commitEdit()
    }

    function activateEditor(editor, fieldIndex) {
        if (root.interactionLocked) return false
        if (root.activeCellEditor && root.activeCellEditor !== editor)
            root.activeCellEditor.commitEdit()
        root.activeCellEditor = editor
        root.currentRow = editor.modelRow
        root.currentFieldIndex = fieldIndex
        return true
    }

    function moveToEditableCell(row, fieldIndex, direction) {
        if (root.interactionLocked || !root.friendBackend) return
        var position = row * 4 + fieldIndex + direction
        if (position < 0 || position >= root.friendBackend.model.count * 4) return
        var nextRow = Math.floor(position / 4)
        var nextField = position % 4
        root.currentRow = nextRow
        root.currentFieldIndex = nextField
        friendTable.positionViewAtRow(nextRow, TableView.Contain)
        Qt.callLater(function() {
            friendTable.forceLayout()
            var cell = friendTable.itemAtCell(Qt.point(0, nextRow))
            if (cell) {
                var editor = cell.editors[nextField]
                var point = editor.mapToItem(friendTable.contentItem, 0, 0)
                if (point.x < friendTable.contentX) friendTable.contentX = point.x
                else if (point.x + editor.width > friendTable.contentX + friendTable.width)
                    friendTable.contentX = point.x + editor.width - friendTable.width
                editor.beginEdit()
            }
        })
    }

    function openCellTextMenu(editor) {
        if (root.interactionLocked) return
        friendContextMenu.close()
        root.activeTextMenu = editor.ContextMenu.menu
        root.activeTextMenu.popup()
    }

    component FriendCellEditor: WxTextField {
        id: cellEditor
        property int modelRow: -1
        property int fieldIndex: -1
        property string fieldName: ""
        property string committedText: ""
        property bool editing: false
        readOnly: !editing
        enabled: !root.interactionLocked
        selectByMouse: editing
        implicitHeight: 36
        font.family: WxTheme.fontFamily
        font.pixelSize: WxTheme.fontSizeNormal
        color: WxTheme.clTextPrimary
        padding: 8
        onCommittedTextChanged: { if (!editing) text = committedText }
        Component.onCompleted: text = committedText
        Component.onDestruction: { if (root.activeCellEditor === cellEditor) root.activeCellEditor = null }

        function resumeFocus() { forceActiveFocus() }
        function beginEdit() {
            if (!root.activateEditor(cellEditor, fieldIndex)) return
            text = committedText
            editing = true
            forceActiveFocus()
            selectAll()
        }
        function commitEdit() {
            if (!editing) return
            var value = text
            editing = false
            if (root.activeCellEditor === cellEditor) root.activeCellEditor = null
            if (!root.interactionLocked && root.friendBackend && value !== committedText)
                root.friendBackend.model.setCell(modelRow, fieldName, value)
            text = committedText
        }
        function cancelEdit() {
            editing = false
            text = committedText
            if (root.activeCellEditor === cellEditor) root.activeCellEditor = null
        }
        onActiveFocusChanged: {
            if (activeFocus) {
                root.currentRow = modelRow
                root.currentFieldIndex = fieldIndex
            } else if (editing && !cellEditor.ContextMenu.menu.visible) commitEdit()
        }
        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                if (editing) commitEdit()
                else beginEdit()
                event.accepted = true
            } else if (event.key === Qt.Key_Escape && editing) {
                cancelEdit()
                event.accepted = true
            } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
                commitEdit()
                root.moveToEditableCell(modelRow, fieldIndex,
                    event.key === Qt.Key_Backtab || (event.modifiers & Qt.ShiftModifier) ? -1 : 1)
                event.accepted = true
            }
        }
        background: Rectangle {
            color: cellEditor.editing ? WxTheme.clBgPrimary : "transparent"
            border.color: cellEditor.activeFocus ? WxTheme.clBorderFocus : "transparent"
            radius: WxTheme.radiusSmall
        }
        MouseArea {
            anchors.fill: parent
            visible: !cellEditor.editing
            acceptedButtons: Qt.LeftButton
            onClicked: cellEditor.forceActiveFocus()
            onDoubleClicked: cellEditor.beginEdit()
        }
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
                    Layout.preferredHeight: 64
                    color: WxTheme.clBgPrimary

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                text: "自动发送好友申请"
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTitle
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "待添加账号"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                elide: Text.ElideRight
                            }
                        }
                        Item { Layout.fillWidth: true }
                        WxButton {
                            text: "下载模板"
                            iconName: "export"
                            enabled: !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked) templateDialog.open()
                            }
                        }
                        WxButton {
                            objectName: "importFriendsButton"
                            Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                ? "importFriendsButton" : text
                            text: "导入 Excel / CSV"
                            iconName: "excel"
                            enabled: !root.interactionLocked
                            onClicked: {
                                if (!root.interactionLocked) importDialog.open()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    color: WxTheme.clBgPrimary
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
                            Layout.fillWidth: true
                            visible: root.friendBackend && (root.friendBackend.model.importError || root.friendBackend.model.importWarning)
                            text: root.friendBackend ? (root.friendBackend.model.importError || root.friendBackend.model.importWarning) : ""
                            elide: Text.ElideRight
                            WxToolTip { visible: warningHover.containsMouse; text: warningHover.parent.text }
                            MouseArea { id: warningHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            color: root.friendBackend && root.friendBackend.model.importError ? WxTheme.clDangerNew : WxTheme.clWarningText
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeTiny
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            objectName: "friendSelectionCount"
                            text: root.friendBackend
                                ? "已选择 " + root.friendBackend.model.selectedCount + " / " + root.friendBackend.batchLimit
                                : "已选择 0 / 100"
                            color: WxTheme.clTextPrimary
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                        }
                        WxButton {
                            objectName: "clearFriendTableButton"
                            Accessible.name: "清空表格"
                            text: "清空表格"
                            iconName: "trash"
                            tooltipText: "清空表格"
                            quiet: true
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
                    Layout.preferredHeight: width < 720 ? 92 : 48
                    color: WxTheme.clBgPrimary
                    border.color: WxTheme.clSurfaceBorder
                    GridLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        columns: parent.width < 720 ? 4 : 9
                        columnSpacing: 8
                        rowSpacing: 6
                        Text { text: "起始序号"; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeSmall }
                        WxTextField {
                            id: rangeStart
                            objectName: "friendRangeStart"
                            Accessible.name: objectName
                            Layout.preferredWidth: 72
                            text: "1"
                            enabled: !root.interactionLocked
                            validator: IntValidator { bottom: 1; top: 1000000 }
                            selectByMouse: true
                        }
                        Text { text: "结束序号"; color: WxTheme.clTextSecondary; font.pixelSize: WxTheme.fontSizeSmall }
                        WxTextField {
                            id: rangeEnd
                            objectName: "friendRangeEnd"
                            Accessible.name: objectName
                            Layout.preferredWidth: 72
                            text: String(root.friendBackend ? Math.max(1, Math.min(root.friendBackend.model.count, root.friendBackend.batchLimit)) : 1)
                            enabled: !root.interactionLocked
                            validator: IntValidator { bottom: 1; top: 1000000 }
                            selectByMouse: true
                        }
                        WxButton {
                            objectName: "selectFriendRangeButton"
                            Accessible.name: objectName
                            text: "选择区间"
                            iconName: "check"
                            enabled: !!root.friendBackend && !root.interactionLocked
                            onClicked: root.friendBackend.model.selectRange(
                                rangeStart.acceptableInput ? Number(rangeStart.text) : 0,
                                rangeEnd.acceptableInput ? Number(rangeEnd.text) : 0)
                        }
                        WxButton {
                            objectName: "clearFriendSelectionButton"
                            text: "清除选择"
                            quiet: true
                            enabled: !!root.friendBackend && !root.interactionLocked
                            onClicked: root.friendBackend.model.clearSelection()
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.friendBackend ? root.friendBackend.model.selectionError || "" : ""
                            elide: Text.ElideRight
                            color: WxTheme.clDangerNew
                            font.pixelSize: WxTheme.fontSizeSmall
                            WxToolTip { visible: rangeErrorHover.containsMouse && text.length > 0; text: rangeErrorHover.parent.text }
                            MouseArea { id: rangeErrorHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    color: WxTheme.clBgSecondary
                    clip: true
                    Row {
                        objectName: "friendTableHeaderContent"
                        x: -friendTable.contentX
                        height: parent.height
                        spacing: 0
                        Repeater {
                            model: ["选择", "序号", "姓名", "账号", "后缀", "打招呼语", "自动备注", "状态"]
                            Text {
                                required property int index
                                required property string modelData
                                width: root.columnWidths[index]
                                height: 36
                                leftPadding: 8
                                verticalAlignment: Text.AlignVCenter
                                text: modelData
                                color: WxTheme.clTextSecondary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Rectangle { anchors.fill: parent; color: WxTheme.clBgPrimary }
                    TableView {
                        id: friendTable
                        objectName: "friendImportTable"
                        anchors.fill: parent
                        clip: true
                        model: root.friendBackend ? root.friendBackend.model : null
                        columnWidthProvider: function(column) { return root.tableContentWidth }
                        rowHeightProvider: function(row) { return root.tableRowHeight }
                        ScrollBar.horizontal: WxScrollBar { objectName: "friendTableHorizontalScrollBar" }
                        ScrollBar.vertical: WxScrollBar { objectName: "friendTableVerticalScrollBar" }
                        delegate: Rectangle {
                            id: friendRow
                            required property int row
                            required property string itemId
                            required property string account
                            required property string friendName
                            required property string relationshipChoice
                            required property string greeting
                            required property string remark
                            required property bool valid
                            required property string error
                            required property string status
                            required property bool selected
                            readonly property bool riskStoppedRow: !!(root.taskBackend
                                && root.taskBackend.riskStopItemId === itemId
                                && root.taskBackend.riskStopModelRow >= 0)
                            readonly property var editors: [nameEditor, accountEditor, relationshipEditor, greetingEditor]
                            implicitWidth: root.tableContentWidth
                            implicitHeight: root.tableRowHeight
                            color: riskStoppedRow || !valid ? WxTheme.clDangerSoft
                                : selected ? WxTheme.clBgSelected
                                : root.currentRow === row ? WxTheme.clBgHover
                                : row % 2 ? WxTheme.clRowAlternate : WxTheme.clBgPrimary
                            TableView.onPooled: {
                                for (var index = 0; index < editors.length; ++index) editors[index].cancelEdit()
                            }
                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                onClicked: root.currentRow = friendRow.row
                            }
                            Rectangle {
                                width: 3
                                height: parent.height
                                visible: parent.riskStoppedRow
                                color: WxTheme.clDangerNew
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 1
                                color: WxTheme.clSurfaceBorder
                            }
                            Row {
                                anchors.fill: parent
                                spacing: 0
                                WxCheckBox {
                                    objectName: "friendRowCheckBox"
                                    Accessible.name: "选择第 " + (row + 1) + " 行"
                                    width: root.columnWidths[0]
                                    height: root.tableRowHeight
                                    checked: selected
                                    enabled: valid && !root.interactionLocked
                                    onToggled: {
                                        if (!root.interactionLocked && root.friendBackend)
                                            root.friendBackend.model.setSelected(row, checked)
                                    }
                                }
                                Text {
                                    text: String(row + 1).padStart(2, "0")
                                    width: root.columnWidths[1]
                                    height: root.tableRowHeight
                                    leftPadding: 8
                                    verticalAlignment: Text.AlignVCenter
                                    color: riskStoppedRow ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeNormal
                                }
                                FriendCellEditor {
                                    id: nameEditor
                                    objectName: "friendNameField"
                                    Accessible.name: "好友姓名"
                                    width: root.columnWidths[2]
                                    height: 36
                                    y: 2
                                    modelRow: friendRow.row
                                    fieldIndex: 0
                                    fieldName: "name"
                                    committedText: friendName
                                }
                                FriendCellEditor {
                                    id: accountEditor
                                    objectName: "friendAccountField"
                                    Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                        ? "friendAccountField" : "好友账号"
                                    width: root.columnWidths[3]
                                    height: 36
                                    y: 2
                                    modelRow: friendRow.row
                                    fieldIndex: 1
                                    fieldName: "account"
                                    committedText: account
                                }
                                FriendRelationshipSelector {
                                    id: relationshipEditor
                                    objectName: "friendRelationshipSelector"
                                    Accessible.name: "好友后缀"
                                    width: root.columnWidths[4]
                                    height: 36
                                    y: 2
                                    modelRow: friendRow.row
                                    cellMode: true
                                    choice: relationshipChoice
                                    options: root.friendBackend ? root.friendBackend.relationshipOptions : []
                                    enabled: !root.interactionLocked
                                    onActiveFocusChanged: { if (activeFocus) root.currentRow = row }
                                    onEditStarted: root.activateEditor(relationshipEditor, 2)
                                    onEditEnded: { if (root.activeCellEditor === relationshipEditor) root.activeCellEditor = null }
                                    onNavigate: function(direction) { root.moveToEditableCell(row, 2, direction) }
                                    onChosen: function(value) {
                                        if (!root.interactionLocked && root.friendBackend) {
                                            root.currentRow = row
                                            root.friendBackend.model.setCell(row, "relationship", value)
                                        }
                                    }
                                }
                                FriendCellEditor {
                                    id: greetingEditor
                                    objectName: "friendGreetingField"
                                    Accessible.name: "好友打招呼语"
                                    width: root.columnWidths[5]
                                    height: 36
                                    y: 2
                                    modelRow: friendRow.row
                                    fieldIndex: 3
                                    fieldName: "greeting"
                                    committedText: greeting
                                    placeholderText: "使用全局默认值"
                                }
                                WxTextField {
                                    objectName: "friendRemarkField"
                                    Accessible.name: "自动备注"
                                    width: root.columnWidths[6]
                                    height: 36
                                    y: 2
                                    text: remark
                                    readOnly: true
                                    selectByMouse: true
                                    onActiveFocusChanged: { if (activeFocus) root.currentRow = row }
                                    enabled: !root.interactionLocked
                                    color: WxTheme.clTextPrimary
                                    placeholderTextColor: WxTheme.clTextHint
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeNormal
                                    background: Rectangle {
                                        color: parent.activeFocus ? WxTheme.clFieldFill : "transparent"
                                        border.color: parent.activeFocus ? WxTheme.clBorderFocus : "transparent"
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                                Item {
                                    width: root.columnWidths[7]
                                    height: root.tableRowHeight
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: Math.min(parent.width - 12, statusText.implicitWidth + 18)
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
                                            width: parent.width - 12
                                            text: riskStoppedRow ? (root.taskBackend.riskStopKind === "friend_frequency" ? "频繁限制" : "风控停止") : !valid ? error
                                                : status === "working" ? "执行中"
                                                : status === "success"
                                                    ? (root.taskBackend && root.taskBackend.acceptanceEnabled
                                                        ? "预检完成" : "已提交")
                                                : status === "error" ? "执行异常"
                                                : status === "unknown" ? "结果未知"
                                                : status === "stopped" ? "未执行"
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
                                        WxToolTip { visible: statusHover.containsMouse; text: error || statusText.text }
                                        MouseArea {
                                            id: statusHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            acceptedButtons: Qt.NoButton
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
                            if (root.activeCellEditor) {
                                var editor = root.activeCellEditor
                                var editorPosition = editor.mapFromItem(tableContextOverlay, mouse.x, mouse.y)
                                if (editorPosition.x >= 0 && editorPosition.x < editor.width
                                        && editorPosition.y >= 0 && editorPosition.y < editor.height) {
                                    root.openCellTextMenu(editor.fieldIndex === undefined ? editor.contentItem : editor)
                                    return
                                }
                            }
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
                    Layout.preferredHeight: width < 720 ? 168 : 120
                    color: WxTheme.clBgPrimary
                    border.color: WxTheme.clSurfaceBorder
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4
                        GridLayout {
                            Layout.fillWidth: true
                            columns: root.width < 720 ? 2 : 4
                            Text { text: "全局打招呼模板"; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            WxTextField {
                                id: globalGreetingField
                                objectName: "globalFriendGreetingField"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                placeholderText: "例如：{称呼}，您好，我是老师。"
                                text: root.friendBackend ? root.friendBackend.defaultGreeting : ""
                                enabled: !root.interactionLocked
                                onTextEdited: {
                                    if (!root.interactionLocked && root.friendBackend)
                                        root.friendBackend.defaultGreeting = text
                                }
                                color: WxTheme.clTextPrimary
                            }
                            Text { text: "全局后缀"; color: WxTheme.clTextSecondary; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            FriendRelationshipSelector {
                                objectName: "globalRelationshipSelector"
                                Layout.preferredWidth: 150
                                allowGlobal: false
                                choice: root.friendBackend ? (root.friendBackend.defaultRelationship || "无") : "妈妈"
                                options: root.friendBackend ? root.friendBackend.relationshipOptions : []
                                enabled: !root.interactionLocked
                                onChosen: function(value) {
                                    if (!root.interactionLocked && root.friendBackend)
                                        root.friendBackend.defaultRelationship = value
                                }
                            }
                        }
                        RowLayout {
                            Text { text: "占位符"; color: WxTheme.clTextHint; font.family: WxTheme.fontFamily; font.pixelSize: WxTheme.fontSizeSmall }
                            WxButton { text: "{姓名}"; quiet: true; enabled: !root.interactionLocked; onClicked: root.insertPlaceholder(text) }
                            WxButton { text: "{后缀}"; quiet: true; enabled: !root.interactionLocked; onClicked: root.insertPlaceholder(text) }
                            WxButton { objectName: "insertAddressPlaceholder"; text: "{称呼}"; quiet: true; enabled: !root.interactionLocked; onClicked: root.insertPlaceholder(text) }
                        }
                        Text {
                            objectName: "friendContentPreview"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: root.currentRow < 0 ? "未定位记录"
                                : "第 " + (root.currentRow + 1) + " 行预览：" + (root.currentPreview.error
                                    || ("打招呼语：" + (root.currentPreview.greeting == null ? "保留微信原文" : root.currentPreview.greeting || "")
                                        + "    ｜    备注：" + (root.currentPreview.remark || "")))
                            wrapMode: Text.Wrap
                            elide: Text.ElideRight
                            color: root.currentPreview.error ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.family: WxTheme.fontFamily
                            WxToolTip { visible: previewHover.containsMouse; text: previewHover.parent.text }
                            MouseArea { id: previewHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                    }
                }

                Rectangle {
                    id: friendActionBar
                    objectName: "friendActionBar"
                    readonly property bool compact: width < 900
                    Layout.fillWidth: true
                    Layout.preferredHeight: friendActionLayout.implicitHeight + 24
                    color: WxTheme.clBgPrimary
                    border.color: WxTheme.clSurfaceBorder
                    GridLayout {
                        id: friendActionLayout
                        width: parent.width - 32
                        anchors.centerIn: parent
                        columns: friendActionBar.compact ? 1 : 2
                        columnSpacing: 24
                        rowSpacing: 12
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                text: root.taskBackend && root.taskBackend.error ? root.taskBackend.error : "等待开始"
                                color: root.taskBackend && root.taskBackend.error ? WxTheme.clDangerNew : WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: true
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.friendBackend
                                    ? "已选择 " + root.friendBackend.model.selectedCount + " / " + root.friendBackend.batchLimit
                                        + " · 随机间隔 " + root.friendBackend.intervalMin + "–" + root.friendBackend.intervalMax + " 秒"
                                    : "随机间隔 15–30 秒"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                elide: Text.ElideRight
                                WxToolTip { text: parent.text; visible: intervalHover.containsMouse }
                                MouseArea { id: intervalHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: friendActionBar.compact
                            Layout.alignment: Qt.AlignRight
                            spacing: 16
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.preferredWidth: 240
                                spacing: 4
                                Text {
                                    Layout.fillWidth: true
                                    text: root.taskBackend && root.taskBackend.acceptanceEnabled
                                        ? "仅填写并核对表单" : "将实际提交好友申请"
                                    color: WxTheme.clWarningText
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }
                                Text {
                                    Layout.fillWidth: true
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
                                    wrapMode: Text.Wrap
                                }
                            }
                            WxButton {
                                objectName: "startFriendsButton"
                                Layout.alignment: Qt.AlignRight
                                Accessible.name: root.taskBackend && root.taskBackend.acceptanceEnabled
                                    ? "startFriendsButton" : text
                                text: (root.taskBackend && root.taskBackend.acceptanceEnabled
                                    ? "开始表单预检 " : "开始添加好友 ")
                                    + (root.friendBackend ? root.friendBackend.model.selectedCount : 0) + " 人"
                                enabled: root.appBackend && root.appBackend.agent.canStartTask
                                    && !root.interactionLocked
                                    && !root.contactsBusy
                                    && root.friendSubmitAvailable
                                    && root.friendBackend && root.friendBackend.model.selectedCount > 0
                                onClicked: root.requestFriendStart()
                                primary: true
                                iconName: "user_plus"
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
        confirmEnabled: !root.interactionLocked && !root.contactsBusy && root.friendSubmitAvailable
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

    Connections {
        target: root.activeTextMenu
        function onClosed() {
            Qt.callLater(function() {
                if (!root.interactionLocked && root.activeCellEditor)
                    root.activeCellEditor.resumeFocus()
            })
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
