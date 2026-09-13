import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    property var appBackend: null
    readonly property var friendBackend: appBackend ? appBackend.friends : null
    readonly property var taskBackend: appBackend ? appBackend.task : null
    property bool monitorVisible: taskBackend && taskBackend.kind === "friend_add"

    function startTask() {
        if (taskBackend && taskBackend.startFriends()) monitorVisible = true
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
                                text: "导入后可直接编辑；每次最多执行 20 条选中记录"
                                color: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "下载模板"
                            onClicked: templateDialog.open()
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
                            text: "＋ 导入 Excel / CSV"
                            enabled: !(root.taskBackend && root.taskBackend.active)
                            onClicked: importDialog.open()
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
                            enabled: root.friendBackend && !(root.taskBackend && root.taskBackend.active)
                            onClicked: root.friendBackend.model.selectFirstValid()
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

                TableView {
                    id: friendTable
                    objectName: "friendImportTable"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
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
                                enabled: valid && !(root.taskBackend && root.taskBackend.active)
                                onToggled: root.friendBackend.model.setSelected(row, checked)
                            }
                            Text {
                                text: String(row + 1).padStart(2, "0")
                                Layout.preferredWidth: 48
                                color: WxTheme.clTextSecondary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                            }
                            TextField {
                                Layout.preferredWidth: 220
                                text: account
                                enabled: !(root.taskBackend && root.taskBackend.active)
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                onEditingFinished: root.friendBackend.model.setCell(row, "account", text)
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
                                enabled: !(root.taskBackend && root.taskBackend.active)
                                color: WxTheme.clTextPrimary
                                placeholderTextColor: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                onEditingFinished: root.friendBackend.model.setCell(row, "greeting", text)
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
                                enabled: !(root.taskBackend && root.taskBackend.active)
                                color: WxTheme.clTextPrimary
                                placeholderTextColor: WxTheme.clTextHint
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                onEditingFinished: root.friendBackend.model.setCell(row, "remark", text)
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
                                        : status === "success" ? WxTheme.clSuccessSoft
                                        : status === "unknown" ? WxTheme.clWarningSoft
                                        : WxTheme.clNeutralSoft
                                    Text {
                                        id: statusText
                                        anchors.centerIn: parent
                                        text: !valid ? error
                                            : status === "success" ? "已提交"
                                            : status === "error" ? "执行异常"
                                            : status === "unknown" ? "结果未知" : "预检通过"
                                        elide: Text.ElideRight
                                        color: !valid || status === "error" ? WxTheme.clDangerNew
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

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 76
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
                            enabled: !(root.taskBackend && root.taskBackend.active)
                            onEditingFinished: root.friendBackend.defaultGreeting = text
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
                            enabled: !(root.taskBackend && root.taskBackend.active)
                            onEditingFinished: root.friendBackend.defaultRemark = text
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
                        Button {
                            objectName: "startFriendsButton"
                            text: "开始添加 " + (root.friendBackend ? root.friendBackend.model.selectedCount : 0) + " 人"
                            enabled: root.appBackend && root.appBackend.agent.automationReady
                                && !(root.taskBackend && root.taskBackend.active)
                                && root.friendBackend && root.friendBackend.model.selectedCount > 0
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
        }

        TaskMonitor {
            taskBackend: root.taskBackend
            agentBackend: root.appBackend ? root.appBackend.agent : null
            taskKind: "friend_add"
            onRequestEdit: root.monitorVisible = false
        }
    }

    FileDialog {
        id: importDialog
        title: "导入好友账号"
        nameFilters: ["Excel / CSV (*.xlsx *.csv)"]
        fileMode: FileDialog.OpenFile
        onAccepted: if (root.friendBackend) root.friendBackend.importFile(selectedFile)
    }

    FileDialog {
        id: templateDialog
        title: "保存好友导入模板"
        nameFilters: ["Excel 文件 (*.xlsx)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "xlsx"
        onAccepted: if (root.friendBackend) root.friendBackend.createTemplate(selectedFile)
    }
}
