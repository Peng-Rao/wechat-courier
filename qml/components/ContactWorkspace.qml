import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "contactWorkspace"
    property var appBackend: null
    readonly property var contactsBackend: appBackend ? appBackend.contacts || null : null
    readonly property bool busy: !!(contactsBackend && contactsBackend.busy)
    readonly property bool operationBlocked: !!(contactsBackend && contactsBackend.operationBlocked)
    readonly property bool canRead: !!(contactsBackend && contactsBackend.canRead && !busy)
    readonly property bool canExport: !!(contactsBackend && !busy && !operationBlocked && contactsBackend.visibleCount > 0)
    readonly property var accounts: contactsBackend ? contactsBackend.accounts || [] : []
    readonly property var tableModel: contactsBackend ? contactsBackend.model || null : null
    readonly property var columnWidths: [180, 180, 160, 200, 180, 240]
    property int sortColumn: -1
    property bool sortAscending: true
    property string pendingExportFormat: "xlsx"
    property var overwritePaths: []

    function accountIndex() {
        if (!contactsBackend) return -1
        for (var i = 0; i < accounts.length; ++i) {
            if (accounts[i].accountId === contactsBackend.selectedAccountId) return i
        }
        return -1
    }

    function refreshEmptyAccounts() {
        if (root.contactsBackend && !root.busy && root.accounts.length === 0)
            root.contactsBackend.refreshAccounts()
    }

    function commitSourceDirectory() {
        if (root.contactsBackend && !root.busy && sourceField.text !== root.contactsBackend.sourceDirectory)
            root.contactsBackend.sourceDirectory = sourceField.text
    }

    function initializeExportFormat() {
        if (!root.contactsBackend || !formatSelector) return
        var index = ["xlsx", "csv", "json", "all"].indexOf(root.contactsBackend.exportFormat)
        formatSelector.currentIndex = Math.max(0, index)
    }

    // Qt.callLater coalesces reset, binding and visibility events into one pass.
    function forceTableLayout() {
        if (root.visible && contactTable) contactTable.forceLayout()
    }

    Component.onCompleted: {
        root.initializeExportFormat()
        Qt.callLater(root.refreshEmptyAccounts)
        Qt.callLater(root.forceTableLayout)
    }

    onTableModelChanged: Qt.callLater(root.forceTableLayout)
    onVisibleChanged: {
        if (visible) Qt.callLater(root.forceTableLayout)
    }

    function requestExport() {
        if (!canExport) return
        pendingExportFormat = ["xlsx", "csv", "json", "all"][formatSelector.currentIndex]
        if (pendingExportFormat === "all") {
            exportFolderDialog.open()
        } else {
            saveDialog.defaultSuffix = pendingExportFormat
            saveDialog.nameFilters = pendingExportFormat === "xlsx" ? ["Excel (*.xlsx)"]
                : pendingExportFormat === "csv" ? ["CSV (*.csv)"] : ["JSON (*.json)"]
            saveDialog.open()
        }
    }

    function exportTo(format, targetUrl) {
        if (!canExport || !String(targetUrl)) return
        contactsBackend.exportContacts(format, String(targetUrl), false)
    }

    function sortContacts(column) {
        if (!contactsBackend || !tableModel) return
        sortAscending = sortColumn === column ? !sortAscending : true
        sortColumn = column
        contactsBackend.sort(column, sortAscending)
    }

    function overwriteMessage() {
        var lines = ["以下文件已存在，是否覆盖？"]
        for (var i = 0; i < Math.min(overwritePaths.length, 3); ++i) {
            var path = String(overwritePaths[i])
            lines.push(path.length > 72 ? "..." + path.slice(-69) : path)
        }
        if (overwritePaths.length > 3) lines.push("另有 " + (overwritePaths.length - 3) + " 个文件")
        return lines.join("\n")
    }

    onBusyChanged: {
        if (busy) {
            sourceFolderDialog.close()
            saveDialog.close()
            exportFolderDialog.close()
            overwriteDialog.close()
        }
    }
    onContactsBackendChanged: {
        sourceFolderDialog.close()
        saveDialog.close()
        exportFolderDialog.close()
        overwriteDialog.close()
        root.initializeExportFormat()
        Qt.callLater(root.refreshEmptyAccounts)
    }
    onOperationBlockedChanged: {
        if (operationBlocked) {
            saveDialog.close()
            exportFolderDialog.close()
            overwriteDialog.close()
        }
    }

    Connections {
        target: root.contactsBackend || null
        ignoreUnknownSignals: true
        function onOverwriteRequested(listPaths) {
            if (!root.canExport || !listPaths || !listPaths.length) return
            root.overwritePaths = listPaths
            overwriteDialog.open()
        }
    }

    Connections {
        target: root.tableModel || null
        ignoreUnknownSignals: true
        function onModelReset() {
            Qt.callLater(root.forceTableLayout)
        }
    }

    component PlainToolTip: ToolTip {
        id: tooltip
        contentItem: Text {
            text: tooltip.text
            textFormat: Text.PlainText
            font: tooltip.font
            color: tooltip.palette.toolTipText
            wrapMode: Text.Wrap
        }
    }

    component CommandButton: Button {
        id: command
        property string iconName: ""
        property string tooltip: ""
        property bool primary: false
        implicitHeight: 32
        implicitWidth: Math.max(32, commandContent.implicitWidth + 20)
        leftPadding: 10
        rightPadding: 10
        font.family: WxTheme.fontFamily
        font.pixelSize: WxTheme.fontSizeSmall
        Accessible.name: text || tooltip
        PlainToolTip {
            visible: command.hovered && command.tooltip.length > 0
            text: command.tooltip
        }
        contentItem: RowLayout {
            id: commandContent
            spacing: 6
            WxIcon {
                visible: command.iconName.length > 0
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
                iconSize: 16
                iconSource: command.iconName ? "../icons/" + command.iconName + ".svg" : ""
                iconColor: command.primary ? "white" : WxTheme.clTextSecondary
                hoverScale: false
            }
            Text {
                visible: command.text.length > 0
                text: command.text
                textFormat: Text.PlainText
                font: command.font
                color: !command.enabled ? WxTheme.clTextHint
                    : command.primary ? "white" : WxTheme.clTextPrimary
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
            }
        }
        background: Rectangle {
            radius: WxTheme.radiusSmall
            color: command.primary
                ? (!command.enabled ? WxTheme.clPrimaryDisabled
                    : command.down ? WxTheme.clPrimaryPress
                    : command.hovered ? WxTheme.clPrimaryHover : WxTheme.clPrimary)
                : command.hovered && command.enabled ? WxTheme.clBgHover : WxTheme.clToolbarFill
            border.color: command.primary ? "transparent" : WxTheme.clSurfaceBorder
        }
    }

    component WorkspaceField: TextField {
        id: field
        implicitHeight: 32
        font.family: WxTheme.fontFamily
        font.pixelSize: WxTheme.fontSizeSmall
        color: WxTheme.clTextPrimary
        placeholderTextColor: WxTheme.clTextHint
        selectByMouse: true
        background: Rectangle {
            radius: WxTheme.radiusSmall
            color: WxTheme.clFieldFill
            border.color: field.activeFocus ? WxTheme.clBorderFocus : WxTheme.clSurfaceBorder
        }
    }

    component WorkspaceCombo: ComboBox {
        id: combo
        implicitHeight: 32
        font.family: WxTheme.fontFamily
        font.pixelSize: WxTheme.fontSizeSmall
        contentItem: Text {
            leftPadding: 10
            rightPadding: 12
            text: combo.displayText
            textFormat: Text.PlainText
            font: combo.font
            color: combo.enabled ? WxTheme.clTextPrimary : WxTheme.clTextHint
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: WxTheme.radiusSmall
            color: WxTheme.clFieldFill
            border.color: combo.activeFocus ? WxTheme.clBorderFocus : WxTheme.clSurfaceBorder
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    WorkspaceField {
                        id: sourceField
                        objectName: "contactSourceField"
                        Accessible.name: "微信数据目录"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        placeholderText: "微信数据目录"
                        text: root.contactsBackend ? root.contactsBackend.sourceDirectory : ""
                        enabled: !!root.contactsBackend && !root.busy
                        onEditingFinished: root.commitSourceDirectory()
                        onAccepted: root.commitSourceDirectory()
                    }
                    CommandButton {
                        objectName: "contactSourceFolderButton"
                        iconName: "folder_open"
                        tooltip: "选择数据目录"
                        Layout.preferredWidth: 32
                        enabled: !!root.contactsBackend && !root.busy
                        onClicked: {
                            if (root.contactsBackend && !root.busy) sourceFolderDialog.open()
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    WorkspaceCombo {
                        id: accountSelector
                        objectName: "contactAccountSelector"
                        Accessible.name: "微信账号"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitWidth: 180
                        model: root.accounts
                        textRole: "label"
                        valueRole: "accountId"
                        currentIndex: root.accountIndex()
                        enabled: !!root.contactsBackend && !root.busy
                        onActivated: function(index) {
                            if (root.contactsBackend && !root.busy && index >= 0 && index < root.accounts.length)
                                root.contactsBackend.selectedAccountId = root.accounts[index].accountId
                        }
                    }
                    CommandButton {
                        objectName: "contactRefreshButton"
                        text: "刷新账号"
                        enabled: !!root.contactsBackend && !root.busy
                        onClicked: {
                            if (root.contactsBackend && !root.busy) root.contactsBackend.refreshAccounts()
                        }
                    }
                    CommandButton {
                        objectName: "contactReadButton"
                        text: "读取联系人"
                        iconName: "file"
                        primary: true
                        enabled: root.canRead
                        onClicked: {
                            if (root.canRead) root.contactsBackend.readContacts()
                        }
                    }
                    CommandButton {
                        objectName: "contactElevationButton"
                        text: "以管理员权限读取"
                        visible: !!(root.contactsBackend && root.contactsBackend.requiresElevation)
                        enabled: root.canRead && visible
                        onClicked: {
                            if (root.canRead && root.contactsBackend.requiresElevation)
                                root.contactsBackend.readAsAdministrator()
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 12
                WorkspaceField {
                    objectName: "contactSearchField"
                    Accessible.name: "搜索联系人"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    placeholderText: "搜索联系人"
                    text: root.contactsBackend ? root.contactsBackend.keyword : ""
                    enabled: !!root.contactsBackend
                    onTextEdited: {
                        if (root.contactsBackend) root.contactsBackend.keyword = text
                    }
                }
                CheckBox {
                    objectName: "contactSpecialCheckBox"
                    text: "包含特殊账号"
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    palette.windowText: WxTheme.clTextPrimary
                    checked: !!(root.contactsBackend && root.contactsBackend.includeSpecial)
                    enabled: !!root.contactsBackend
                    onToggled: {
                        if (root.contactsBackend) root.contactsBackend.includeSpecial = checked
                    }
                }
                Text {
                    objectName: "contactCountLabel"
                    text: root.contactsBackend
                        ? root.contactsBackend.visibleCount + " / " + root.contactsBackend.totalCount : "0 / 0"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    Accessible.name: "显示 / 总数"
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            clip: true
            HorizontalHeaderView {
                id: contactHeader
                objectName: "contactHeader"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 34
                clip: true
                syncView: contactTable
                textRole: "display"
                delegate: Button {
                    id: headerCell
                    required property int column
                    required property var model
                    objectName: "contactHeader-" + column
                    implicitWidth: root.columnWidths[column]
                    implicitHeight: 34
                    enabled: !!root.contactsBackend && !!root.tableModel
                    onClicked: root.sortContacts(column)
                    contentItem: RowLayout {
                        spacing: 6
                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: headerCell.model && headerCell.model.display !== undefined
                                ? String(headerCell.model.display) : ""
                            textFormat: Text.PlainText
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                            font.bold: true
                            color: WxTheme.clTextSecondary
                            elide: Text.ElideRight
                        }
                        WxIcon {
                            visible: root.sortColumn === headerCell.column
                            iconSource: "../icons/arrow_down.svg"
                            iconColor: WxTheme.clTextSecondary
                            iconSize: 12
                            rotation: root.sortAscending ? 180 : 0
                            hoverScale: false
                        }
                    }
                    background: Rectangle {
                        color: headerCell.hovered ? WxTheme.clBgHover : WxTheme.clToolbarFill
                        border.color: WxTheme.clSurfaceBorder
                    }
                }
            }
            TableView {
                id: contactTable
                objectName: "contactTable"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: contactHeader.bottom
                anchors.bottom: parent.bottom
                clip: true
                model: root.tableModel
                editTriggers: TableView.NoEditTriggers
                columnSpacing: 0
                rowSpacing: 0
                columnWidthProvider: function(column) { return root.columnWidths[column] }
                rowHeightProvider: function(row) { return 34 }
                ScrollBar.vertical: ScrollBar {
                    objectName: "contactVerticalScrollBar"
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: ScrollBar {
                    objectName: "contactHorizontalScrollBar"
                    policy: ScrollBar.AsNeeded
                }
                delegate: Rectangle {
                    id: cell
                    required property int row
                    required property int column
                    required property var model
                    readonly property string cellValue: model && model.cellText !== undefined
                        ? String(model.cellText) : model && model.display !== undefined ? String(model.display) : ""
                    objectName: "contactCell-" + row + "-" + column
                    implicitWidth: root.columnWidths[column]
                    implicitHeight: 34
                    color: cellMouse.containsMouse ? WxTheme.clBgSelected
                        : row % 2 ? WxTheme.clRowAlternate : WxTheme.clPanelFill
                    border.color: WxTheme.clSurfaceBorder
                    Text {
                        objectName: "contactCellText-" + cell.row + "-" + cell.column
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        text: cell.cellValue
                        textFormat: Text.PlainText
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    PlainToolTip {
                        objectName: "contactCellToolTip-" + cell.row + "-" + cell.column
                        visible: cellMouse.containsMouse && cell.cellValue.length > 0
                        text: "复制单元格: " + cell.cellValue
                    }
                    MouseArea {
                        id: cellMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onDoubleClicked: {
                            if (root.contactsBackend && root.tableModel && !root.operationBlocked)
                                root.contactsBackend.copyCell(cell.row, cell.column)
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    BusyIndicator {
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        visible: root.busy
                        running: root.busy
                    }
                    Text {
                        id: statusLabel
                        objectName: "contactStatusLabel"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: root.contactsBackend
                            ? root.contactsBackend.errorMessage || root.contactsBackend.statusText : ""
                        textFormat: Text.PlainText
                        color: root.contactsBackend && root.contactsBackend.errorMessage
                            ? WxTheme.clDangerNew : WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        elide: Text.ElideRight
                        PlainToolTip {
                            visible: statusHover.containsMouse && statusLabel.text.length > 0
                            text: statusLabel.text
                        }
                        MouseArea {
                            id: statusHover
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                        }
                    }
                    Text {
                        objectName: "contactElapsedLabel"
                        text: root.contactsBackend ? root.contactsBackend.elapsedText : ""
                        textFormat: Text.PlainText
                        color: WxTheme.clTextHint
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                    }
                    CommandButton {
                        objectName: "contactCancelButton"
                        text: "取消"
                        iconName: "stop"
                        enabled: root.busy
                        onClicked: {
                            if (root.contactsBackend && root.busy) root.contactsBackend.cancel()
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    CommandButton {
                        objectName: "contactClearButton"
                        iconName: "clear_all"
                        tooltip: "清空联系人"
                        Layout.preferredWidth: 32
                        enabled: !!(root.contactsBackend && !root.busy && root.contactsBackend.totalCount > 0)
                        onClicked: {
                            if (enabled && root.contactsBackend && !root.busy) root.contactsBackend.clear()
                        }
                    }
                    CommandButton {
                        objectName: "contactOpenExportFolderButton"
                        iconName: "folder_open"
                        tooltip: "打开导出目录"
                        Layout.preferredWidth: 32
                        enabled: !!(root.contactsBackend && root.contactsBackend.lastExportPaths
                            && root.contactsBackend.lastExportPaths.length > 0)
                        onClicked: {
                            if (enabled && root.contactsBackend) root.contactsBackend.openExportFolder()
                        }
                    }
                    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                    WorkspaceCombo {
                        id: formatSelector
                        objectName: "contactFormatSelector"
                        Accessible.name: "导出格式"
                        Layout.preferredWidth: 130
                        model: ["Excel", "CSV", "JSON", "全部格式"]
                    }
                    CommandButton {
                        objectName: "contactExportButton"
                        text: "导出"
                        iconName: "export"
                        primary: true
                        enabled: root.canExport
                        onClicked: root.requestExport()
                    }
                }
            }
        }
    }

    FolderDialog {
        id: sourceFolderDialog
        objectName: "contactSourceFolderDialog"
        title: "选择微信数据目录"
        onAccepted: {
            if (root.contactsBackend && !root.busy && String(selectedFolder))
                root.contactsBackend.sourceDirectory = String(selectedFolder)
        }
    }
    FileDialog {
        id: saveDialog
        objectName: "contactSaveDialog"
        title: "导出联系人"
        fileMode: FileDialog.SaveFile
        options: FileDialog.DontConfirmOverwrite
        defaultSuffix: "xlsx"
        nameFilters: ["Excel (*.xlsx)"]
        onAccepted: root.exportTo(root.pendingExportFormat, selectedFile)
    }
    FolderDialog {
        id: exportFolderDialog
        objectName: "contactExportFolderDialog"
        title: "选择联系人导出目录"
        onAccepted: root.exportTo("all", selectedFolder)
    }
    ConfirmDialog {
        id: overwriteDialog
        objectName: "contactOverwriteDialog"
        z: 20
        message: root.overwriteMessage()
        confirmText: "覆盖"
        confirmButtonObjectName: "contactOverwriteConfirmButton"
        cancelButtonObjectName: "contactOverwriteCancelButton"
        isDanger: true
        confirmEnabled: root.canExport && root.overwritePaths.length > 0
        onConfirmed: {
            if (root.canExport && root.overwritePaths.length > 0)
                root.contactsBackend.confirmOverwrite()
        }
        onVisibleChanged: {
            if (!visible) root.overwritePaths = []
        }
    }
}
