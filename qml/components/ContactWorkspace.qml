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
    property var hoveredCell: null
    readonly property int hoveredRow: hoveredCell ? hoveredCell.row : -1
    readonly property bool wideToolbar: width >= 1152
    readonly property string emptyState: {
        if (contactsBackend && contactsBackend.visibleCount > 0) return ""
        if (contactsBackend && contactsBackend.totalCount > 0) return "filtered"
        if (busy) return "loading"
        if (accounts.length === 0) return "no_account"
        if (contactsBackend && contactsBackend.errorMessage) return "error"
        if (contactsBackend && contactsBackend.phase === "ready") return "empty"
        return "idle"
    }
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
        else root.hoveredCell = null
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
            root.hoveredCell = null
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

        Item {
            objectName: "contactPageHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            readonly property string eyebrow: "工作区 / 联系人"
            RowLayout {
                anchors.fill: parent
                anchors.margins: 16
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 4
                    Text {
                        text: "工作区 / 联系人"
                        textFormat: Text.PlainText
                        color: WxTheme.clTextSecondary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeSmall
                    }
                    Text {
                        objectName: "contactPageTitle"
                        Layout.fillWidth: true
                        text: "微信联系人导出"
                        textFormat: Text.PlainText
                        color: WxTheme.clTextPrimary
                        font.family: WxTheme.fontFamily
                        font.pixelSize: WxTheme.fontSizeTitle
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                }
                WxButton {
                    objectName: "contactSourceToggleButton"
                    text: "数据来源"
                    iconName: "database"
                    tooltipText: "微信数据目录"
                    Accessible.name: "微信数据目录"
                    quiet: true
                    checkable: true
                    checked: root.sourceExpanded
                    onClicked: {
                        sourceField.focus = false
                        root.sourceExpanded = !root.sourceExpanded
                    }
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

        Item {
            objectName: "contactToolbar"
            Layout.fillWidth: true
            Layout.preferredHeight: root.wideToolbar ? 60 : 108
            GridLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.topMargin: 12
                anchors.bottomMargin: 12
                columns: root.wideToolbar ? 3 : 2
                columnSpacing: 16
                rowSpacing: 12
                RowLayout {
                    objectName: "contactAccountBar"
                    Layout.row: 0
                    Layout.column: 0
                    Layout.minimumWidth: 164
                    Layout.maximumWidth: 324
                    Layout.preferredWidth: 324
                    Layout.fillWidth: true
                    spacing: 8
                    WxComboBox {
                        id: accountSelector
                        objectName: "contactAccountSelector"
                        Accessible.name: "微信账号"
                        Layout.fillWidth: true
                        Layout.preferredWidth: 280
                        Layout.maximumWidth: 280
                        Layout.minimumWidth: 120
                        model: root.accounts
                        textRole: "label"
                        valueRole: "accountId"
                        currentIndex: root.accountIndex()
                        enabled: !!root.contactsBackend && !root.busy
                        contentItem: Text {
                            text: accountSelector.displayText
                            textFormat: Text.PlainText
                            font: accountSelector.font
                            color: WxTheme.clTextPrimary
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        PlainToolTip {
                            objectName: "contactAccountToolTip"
                            text: accountSelector.displayText
                            visible: accountSelector.hovered && text.length > 0
                        }
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
                }
                RowLayout {
                    Layout.row: 0
                    Layout.column: root.wideToolbar ? 2 : 1
                    Layout.alignment: Qt.AlignRight
                    spacing: 8
                    WxButton {
                        objectName: "contactReadButton"
                        Accessible.name: text
                        text: "读取联系人"
                        iconName: "database"
                        primary: root.canRead && !(root.contactsBackend && root.contactsBackend.totalCount > 0)
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
                RowLayout {
                    Layout.row: root.wideToolbar ? 0 : 1
                    Layout.column: root.wideToolbar ? 1 : 0
                    Layout.columnSpan: root.wideToolbar ? 1 : 2
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 12
                    Rectangle {
                        objectName: "contactSearchContainer"
                        Layout.fillWidth: true
                        Layout.maximumWidth: 480
                        Layout.minimumWidth: 120
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
                    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
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
                            font.weight: Font.Medium
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
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: WxTheme.clDivider
                        }
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
                    visible: contactTable.contentHeight > contactTable.height + 1
                }
                ScrollBar.horizontal: WxScrollBar {
                    objectName: "contactHorizontalScrollBar"
                    policy: ScrollBar.AsNeeded
                    visible: contactTable.contentWidth > contactTable.width + 1
                }
                delegate: Rectangle {
                    id: cell
                    required property int row
                    required property int column
                    required property var model
                    TableView.onPooled: if (root.hoveredCell === cell) root.hoveredCell = null
                    Component.onDestruction: if (root && root.hoveredCell === cell) root.hoveredCell = null
                    readonly property string cellValue: model && model.cellText !== undefined
                        ? String(model.cellText) : model && model.display !== undefined ? String(model.display) : ""
                    objectName: "contactCell-" + row + "-" + column
                    implicitWidth: root.columnWidths[column]
                    implicitHeight: 40
                    color: root.hoveredRow === row ? WxTheme.clBgHover
                        : row % 2 ? WxTheme.clRowAlternate : WxTheme.clBgPrimary
                    Accessible.role: Accessible.StaticText
                    Accessible.name: cellValue
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: WxTheme.clDivider
                    }
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
                        onEntered: root.hoveredCell = cell
                        onExited: if (root.hoveredCell === cell) root.hoveredCell = null
                        onDoubleClicked: {
                            if (root.contactsBackend && root.tableModel && !root.operationBlocked)
                                root.contactsBackend.copyCell(cell.row, cell.column)
                        }
                    }
                }
            }
            ColumnLayout {
                objectName: "contactEmptyState"
                anchors.centerIn: contactTable
                width: Math.min(440, contactTable.width - 48)
                spacing: 12
                visible: root.emptyState !== ""
                BusyIndicator {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    visible: root.emptyState === "loading"
                    running: visible
                }
                WxIcon {
                    Layout.alignment: Qt.AlignHCenter
                    visible: root.emptyState !== "loading"
                    iconSource: root.emptyState === "filtered" ? "../icons/search.svg"
                        : root.emptyState === "no_account" ? "../icons/users.svg" : "../icons/database.svg"
                    iconColor: WxTheme.clTextHint
                    iconSize: 32
                    hoverScale: false
                }
                Text {
                    objectName: "contactEmptyTitle"
                    Layout.fillWidth: true
                    text: root.emptyState === "filtered" ? "没有匹配的联系人"
                        : root.emptyState === "loading" ? "正在读取联系人"
                        : root.emptyState === "no_account" ? "未发现账号"
                        : root.emptyState === "error" ? "读取失败"
                        : root.emptyState === "empty" ? "暂无联系人" : "尚未读取联系人"
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    color: WxTheme.clTextSecondary
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeNormal
                }
                Text {
                    id: emptyDetail
                    objectName: "contactEmptyDetail"
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: root.contactsBackend && root.emptyState === "loading" ? root.contactsBackend.statusText
                        : root.contactsBackend && (root.emptyState === "error" || root.emptyState === "no_account")
                            ? root.contactsBackend.errorMessage : ""
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    color: WxTheme.clTextHint
                    font.family: WxTheme.fontFamily
                    font.pixelSize: WxTheme.fontSizeSmall
                    PlainToolTip { text: emptyDetail.text; visible: emptyDetailHover.containsMouse && text.length > 0 }
                    MouseArea { id: emptyDetailHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
                WxButton {
                    objectName: "contactEmptyActionButton"
                    Layout.alignment: Qt.AlignHCenter
                    text: root.emptyState === "no_account" ? "数据来源" : "清除搜索"
                    visible: root.emptyState === "no_account"
                        || (root.emptyState === "filtered" && !!root.contactsBackend && root.contactsBackend.keyword.length > 0)
                    onClicked: {
                        if (root.emptyState === "no_account") root.sourceExpanded = true
                        else if (root.contactsBackend) root.contactsBackend.keyword = ""
                    }
                }
            }
        }

        Rectangle {
            objectName: "contactFooter"
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            color: WxTheme.clToolbarFill
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: WxTheme.clDivider
            }
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
                }
                Text {
                    objectName: "contactElapsedLabel"
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                    text: root.contactsBackend ? root.contactsBackend.elapsedText : ""
                    visible: !!root.contactsBackend && (root.busy || root.contactsBackend.phase !== "idle")
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
                    primary: root.canExport
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
