import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import Qt.labs.qmlmodels
import "../theme"
import "TableWidths.js" as TableWidths

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
    readonly property var columnNames: ["昵称", "备注", "手机号", "微信 ID", "微信号", "描述"]
    readonly property var columnWidths: TableWidths.expand(
        [130, 140, 140, 238, 185, 215], contactTable.width, 1048, [0, 1, 2, 3, 4, 5])
    readonly property int tableContentWidth: columnWidths.reduce(function(sum, value) { return sum + value }, 0)
    property int sortColumn: -1
    property bool sortAscending: true
    property string pendingExportFormat: "xlsx"
    property var overwritePaths: []
    property bool sourceExpanded: false
    onColumnWidthsChanged: Qt.callLater(root.forceTableLayout)

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
        if (root.visible && contactTable) {
            contactTable.forceLayout()
            contactTable.contentX = Math.min(contactTable.contentX, Math.max(0, root.tableContentWidth - contactTable.width))
        }
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
            exportConfirmDialog.close()
            sourceFolderDialog.close()
            saveDialog.close()
            exportFolderDialog.close()
            overwriteDialog.close()
        }
    }
    onContactsBackendChanged: {
        exportConfirmDialog.close()
        sourceFolderDialog.close()
        saveDialog.close()
        exportFolderDialog.close()
        overwriteDialog.close()
        root.initializeExportFormat()
        Qt.callLater(root.refreshEmptyAccounts)
    }
    onOperationBlockedChanged: {
        if (operationBlocked) {
            exportConfirmDialog.close()
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

    component PlainToolTip: WxToolTip {}

    // Header metadata is independent of empty or filtered contact rows.
    TableModel {
        id: columnHeaderModel
        TableModelColumn { display: "nickname" }
        TableModelColumn { display: "remark" }
        TableModelColumn { display: "phone" }
        TableModelColumn { display: "username" }
        TableModelColumn { display: "alias" }
        TableModelColumn { display: "description" }
        rows: [{nickname: "", remark: "", phone: "", username: "", alias: "", description: ""}]
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        WorkspaceHeader {
            objectName: "contactPageHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            eyebrow: "工作区 / 联系人"
            title: "微信联系人导出"
            titleObjectName: "contactPageTitle"
            Text {
                text: "本次会话数据"
                textFormat: Text.PlainText
                color: WxTheme.clTextSecondary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
            }
            WxButton {
                objectName: "contactSourceToggleButton"
                text: "数据来源"
                iconName: "database"
                tooltipText: "微信数据目录"
                Accessible.name: "微信数据目录"
                checkable: true
                checked: root.sourceExpanded
                onClicked: {
                    sourceField.focus = false
                    root.sourceExpanded = !root.sourceExpanded
                }
            }
        }

        Rectangle {
            objectName: "contactSourcePanel"
            visible: root.sourceExpanded
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 70 : 0
            color: WxTheme.clBgPrimary
            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.bottomMargin: 12
                spacing: 6
                Text {
                    text: "微信数据目录"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    WxTextField {
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
                    WxButton {
                        objectName: "contactDetectDirectoryButton"
                        Accessible.name: text
                        text: "自动检测"
                        tooltipText: "自动检测微信数据目录"
                        enabled: !!root.contactsBackend && !root.busy
                        onClicked: {
                            if (!root.busy && root.contactsBackend) root.contactsBackend.detectSourceDirectory()
                        }
                    }
                    WxButton {
                        objectName: "contactSourceFolderButton"
                        Accessible.name: tooltipText
                        iconName: "folder_open"
                        tooltipText: "选择数据目录"
                        Layout.preferredWidth: 36
                        enabled: !!root.contactsBackend && !root.busy
                        onClicked: {
                            if (!root.busy && root.contactsBackend) sourceFolderDialog.open()
                        }
                    }
                }
            }
        }

        Rectangle {
            objectName: "contactAccountBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.bottomMargin: 12
                spacing: 8
                WxIcon {
                    iconSource: "../icons/user.svg"
                    iconColor: WxTheme.clTextSecondary
                    iconSize: 16
                    hoverScale: false
                }
                WxComboBox {
                    id: accountSelector
                    objectName: "contactAccountSelector"
                    Accessible.name: "微信账号"
                    Layout.preferredWidth: 320
                    Layout.fillWidth: true
                    Layout.maximumWidth: 320
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
                WxButton {
                    objectName: "contactRefreshButton"
                    Accessible.name: "刷新账号"
                    iconName: "refresh"
                    tooltipText: "刷新账号"
                    quiet: true
                    Layout.preferredWidth: 36
                    enabled: !!root.contactsBackend && !root.busy
                    onClicked: {
                        if (root.contactsBackend && !root.busy) root.contactsBackend.refreshAccounts()
                    }
                }
                Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                WxButton {
                    objectName: "contactReadButton"
                    Accessible.name: text
                    text: "读取联系人"
                    iconName: "database"
                    enabled: root.canRead
                    onClicked: {
                        if (root.canRead) root.contactsBackend.readContacts()
                    }
                }
                WxButton {
                    objectName: "contactElevationButton"
                    text: "管理员读取"
                    tooltipText: "以管理员权限读取"
                    Accessible.name: "以管理员权限读取"
                    visible: !!(root.contactsBackend && root.contactsBackend.requiresElevation)
                    enabled: root.canRead && visible
                    onClicked: {
                        if (root.canRead && root.contactsBackend.requiresElevation)
                            root.contactsBackend.readAsAdministrator()
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 12
                Rectangle {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredHeight: 36
                    radius: 6
                    color: WxTheme.clFieldFill
                    border.color: searchField.activeFocus ? WxTheme.clBorderFocus : WxTheme.clBorderStrong
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 4
                        spacing: 8
                        WxIcon {
                            iconSource: "../icons/search.svg"
                            iconColor: WxTheme.clTextSecondary
                            iconSize: 16
                            hoverScale: false
                        }
                        WxTextField {
                            id: searchField
                            objectName: "contactSearchField"
                            Accessible.name: "搜索联系人"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            placeholderText: "搜索昵称、备注、微信号"
                            text: root.contactsBackend ? root.contactsBackend.keyword : ""
                            enabled: !!root.contactsBackend
                            leftPadding: 0
                            rightPadding: 0
                            background: null
                            onTextEdited: {
                                if (root.contactsBackend) root.contactsBackend.keyword = text
                            }
                        }
                        WxButton {
                            objectName: "contactClearSearchButton"
                            iconName: "close"
                            tooltipText: "清除搜索"
                            Accessible.name: tooltipText
                            quiet: true
                            Layout.preferredWidth: 28
                            Layout.preferredHeight: 28
                            enabled: !!root.contactsBackend && searchField.text.length > 0
                            onClicked: {
                                if (root.contactsBackend) root.contactsBackend.keyword = ""
                                searchField.forceActiveFocus()
                            }
                        }
                    }
                }
                WxCheckBox {
                    objectName: "contactSpecialCheckBox"
                    text: "包含特殊账号"
                    Accessible.name: text
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

        Rectangle {
            objectName: "contactTableSurface"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            clip: true
            color: WxTheme.clBgPrimary
            HorizontalHeaderView {
                id: contactHeader
                objectName: "contactHeader"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 40
                clip: true
                syncView: contactTable
                model: columnHeaderModel
                textRole: "display"
                resizableColumns: false
                delegate: Button {
                    id: headerCell
                    required property int column
                    objectName: "contactHeader-" + column
                    implicitWidth: root.columnWidths[column]
                    implicitHeight: 40
                    Accessible.name: root.columnNames[column]
                    enabled: !!root.contactsBackend && !!root.tableModel
                    onClicked: root.sortContacts(column)
                    contentItem: RowLayout {
                        spacing: 6
                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: root.columnNames[headerCell.column]
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
                        color: headerCell.hovered ? WxTheme.clBgHover : WxTheme.clBgSecondary
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
                contentWidth: root.tableContentWidth
                editTriggers: TableView.NoEditTriggers
                columnSpacing: 0
                rowSpacing: 0
                columnWidthProvider: function(column) { return root.columnWidths[column] }
                rowHeightProvider: function(row) { return 40 }
                ScrollBar.vertical: WxScrollBar {
                    objectName: "contactVerticalScrollBar"
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: WxScrollBar {
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
                    implicitHeight: 40
                    color: cellMouse.containsMouse ? WxTheme.clBgSelected
                        : row % 2 ? WxTheme.clRowAlternate : WxTheme.clBgPrimary
                    Accessible.role: Accessible.StaticText
                    Accessible.name: cellValue
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
                        font.pixelSize: WxTheme.fontSizeNormal
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        maximumLineCount: 1
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
            Layout.preferredHeight: 70
            color: WxTheme.clToolbarFill
            border.color: WxTheme.clSurfaceBorder
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 8
                Rectangle {
                    Layout.preferredWidth: 8
                    Layout.preferredHeight: 8
                    radius: 4
                    color: root.contactsBackend && root.contactsBackend.errorMessage
                        ? WxTheme.clDangerNew : root.busy ? WxTheme.clPrimary
                        : root.contactsBackend && root.contactsBackend.totalCount > 0
                            ? WxTheme.clSuccessText : WxTheme.clTextHint
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 4
                    Text {
                        id: statusLabel
                        objectName: "contactStatusLabel"
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: root.contactsBackend
                            ? root.contactsBackend.errorMessage || root.contactsBackend.statusText : "等待读取联系人"
                        textFormat: Text.PlainText
                        color: root.contactsBackend && root.contactsBackend.errorMessage
                            ? WxTheme.clDangerNew : WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        maximumLineCount: 1
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
                        Layout.fillWidth: true
                        text: root.contactsBackend ? "显示 " + root.contactsBackend.visibleCount
                            + " / " + root.contactsBackend.totalCount + " 位联系人" : "当前会话数据"
                        textFormat: Text.PlainText
                        color: WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                }
                Text {
                    objectName: "contactElapsedLabel"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                    text: root.contactsBackend ? root.contactsBackend.elapsedText : ""
                    textFormat: Text.PlainText
                    color: WxTheme.clTextHint
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                }
                WxButton {
                    objectName: "contactCancelButton"
                    Accessible.name: text
                    text: "取消"
                    iconName: "stop"
                    enabled: root.busy
                    visible: root.busy
                    onClicked: {
                        if (root.contactsBackend && root.busy) root.contactsBackend.cancel()
                    }
                }
                WxButton {
                    objectName: "contactClearButton"
                    Accessible.name: tooltipText
                    iconName: "clear_all"
                    tooltipText: "清空联系人"
                    quiet: true
                    Layout.preferredWidth: 36
                    enabled: !!(root.contactsBackend && !root.busy && root.contactsBackend.totalCount > 0)
                    onClicked: {
                        if (enabled && root.contactsBackend && !root.busy) root.contactsBackend.clear()
                    }
                }
                WxButton {
                    objectName: "contactOpenExportFolderButton"
                    Accessible.name: tooltipText
                    iconName: "folder_open"
                    tooltipText: "打开导出目录"
                    quiet: true
                    Layout.preferredWidth: 36
                    enabled: !!(root.contactsBackend && root.contactsBackend.lastExportPaths
                        && root.contactsBackend.lastExportPaths.length > 0)
                    onClicked: {
                        if (enabled && root.contactsBackend) root.contactsBackend.openExportFolder()
                    }
                }
                WxButton {
                    objectName: "contactExportButton"
                    Accessible.name: "导出"
                    text: "导出联系人"
                    iconName: "export"
                    primary: true
                    enabled: root.canExport
                    onClicked: { if (root.canExport) exportConfirmDialog.open() }
                }
            }
        }
    }

    Popup {
        id: exportConfirmDialog
        objectName: "contactExportConfirmDialog"
        parent: root.Overlay.overlay || root
        width: Math.min(420, parent.width - 48)
        height: exportContent.implicitHeight + 40
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        modal: true
        focus: true
        padding: 20
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: WxTheme.clBgPrimary
            border.color: WxTheme.clBorderStrong
            radius: 8
        }
        ColumnLayout {
            id: exportContent
            anchors.fill: parent
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: "导出联系人"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeTitle
                    font.weight: Font.DemiBold
                }
                WxButton {
                    iconName: "close"
                    Accessible.name: "关闭导出"
                    tooltipText: Accessible.name
                    quiet: true
                    Layout.preferredWidth: 36
                    onClicked: exportConfirmDialog.close()
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    objectName: "contactExportCountLabel"
                    text: (root.contactsBackend ? root.contactsBackend.visibleCount : 0) + " 位联系人"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextPrimary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeNormal
                }
                Text {
                    text: "当前筛选结果"
                    textFormat: Text.PlainText
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                }
            }
            Text {
                text: "文件格式"
                textFormat: Text.PlainText
                color: WxTheme.clTextSecondary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
            }
            WxComboBox {
                id: formatSelector
                objectName: "contactFormatSelector"
                Accessible.name: "导出格式"
                Layout.fillWidth: true
                model: ["Excel", "CSV", "JSON", "全部格式"]
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                WxButton {
                    objectName: "contactExportCancelButton"
                    text: "取消"
                    onClicked: exportConfirmDialog.close()
                }
                WxButton {
                    objectName: "contactExportConfirmButton"
                    text: "确认导出"
                    iconName: "export"
                    primary: true
                    enabled: root.canExport
                    onClicked: {
                        if (!root.canExport) return
                        exportConfirmDialog.close()
                        root.requestExport()
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
