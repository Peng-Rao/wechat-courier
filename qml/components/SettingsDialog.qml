import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../theme"

Popup {
    id: root
    property var appBackend: null
    property int sectionIndex: 0
    property string intervalValidation: ""
    readonly property bool interactionLocked: !!(
        appBackend && appBackend.task && appBackend.task.active
    )

    function applyIfUnlocked(callback) {
        if (root.interactionLocked || !root.appBackend) return false
        callback()
        return true
    }

    parent: Overlay.overlay
    modal: true
    focus: true
    enabled: !root.interactionLocked
    closePolicy: Popup.CloseOnEscape
    width: Math.min(820, parent ? parent.width - 48 : 820)
    height: Math.min(620, parent ? parent.height - 48 : 620)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    padding: 1

    onInteractionLockedChanged: {
        if (root.interactionLocked && root.opened) root.close()
    }
    onAboutToHide: {
        friendIntervalMin.commit()
        friendIntervalMax.commit()
    }
    onAboutToShow: {
        friendIntervalMin.reset()
        friendIntervalMax.reset()
        intervalValidation = ""
    }

    Overlay.modal: Rectangle { color: WxTheme.isDark ? "#99070a0d" : "#660e1820" }
    background: Rectangle {
        color: WxTheme.isDark ? "#20282e" : "#f9fbfc"
        border.color: WxTheme.clSurfaceBorder
        radius: WxTheme.radiusLarge
    }

    contentItem: ColumnLayout {
        spacing: 0

        WxRoundedBand {
            objectName: "settingsHeaderBand"
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            fillColor: WxTheme.clToolbarFill
            radius: WxTheme.radiusLarge
            roundBottom: false
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: WxTheme.clSurfaceBorder
            }
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "参数设置"
                color: WxTheme.clTextPrimary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeNormal
                font.bold: true
            }
            Text {
                anchors.right: closeButton.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "修改后自动保存在本机"
                color: WxTheme.clTextHint
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeTiny
            }
            Button {
                id: closeButton
                objectName: "settingsCloseButton"
                Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                    ? "settingsCloseButton" : "关闭设置"
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 34
                implicitHeight: 32
                onClicked: root.close()
                contentItem: Text {
                    text: "×"
                    color: WxTheme.clTextPrimary
                    font.pixelSize: 18
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: parent.hovered ? WxTheme.clBgHover : "transparent"
                    radius: WxTheme.radiusSmall
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 184
                Layout.minimumWidth: 184
                Layout.maximumWidth: 184
                Layout.fillHeight: true
                color: WxTheme.clPanelFill
                border.color: WxTheme.clSurfaceBorder
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 4
                    Repeater {
                        model: ["消息群发", "自动发送好友申请", "自动化与恢复", "外观"]
                        Button {
                            required property int index
                            required property string modelData
                            objectName: "settingsSection" + index
                            Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                                ? objectName : modelData
                            Layout.fillWidth: true
                            implicitHeight: 38
                            onClicked: root.sectionIndex = index
                            contentItem: Text {
                                text: modelData
                                color: root.sectionIndex === index ? WxTheme.clTextPrimary : WxTheme.clTextSecondary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeSmall
                                font.bold: root.sectionIndex === index
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }
                            background: Rectangle {
                                color: root.sectionIndex === index ? WxTheme.clBgSelected
                                    : parent.hovered ? WxTheme.clBgHover : "transparent"
                                radius: WxTheme.radiusSmall
                                Rectangle {
                                    width: 3
                                    height: parent.height - 12
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: WxTheme.clPrimary
                                    visible: root.sectionIndex === index
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        Layout.topMargin: 12
                        Layout.bottomMargin: 8
                        color: WxTheme.clSurfaceBorder
                    }
                    Button {
                        text: "恢复默认设置"
                        enabled: false
                        contentItem: Text {
                            text: parent.text
                            color: WxTheme.clTextHint
                            font.family: WxTheme.fontFamily
                            font.pixelSize: WxTheme.fontSizeSmall
                        }
                        background: Rectangle { color: "transparent" }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                currentIndex: root.sectionIndex
                clip: true

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: parent.width
                        spacing: 0
                        SettingsHeading {
                            title: "消息群发"
                            subtitle: "设置逐个发送的等待区间和附件行为"
                        }
                        SettingsRow {
                            title: "发送间隔"
                            description: "每位好友之间随机等待，降低连续操作风险"
                            RowLayout {
                                TextField {
                                    objectName: "settingsMessageIntervalMin"
                                    Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                                        ? objectName : "最小发送间隔"
                                    Layout.preferredWidth: 72
                                    text: root.appBackend ? root.appBackend.message.intervalMin : "2"
                                    validator: DoubleValidator { bottom: 0; top: 300 }
                                    onEditingFinished: root.applyIfUnlocked(function() {
                                        root.appBackend.message.intervalMin = Number(text)
                                    })
                                }
                                Text { text: "至"; color: WxTheme.clTextHint }
                                TextField {
                                    objectName: "settingsMessageIntervalMax"
                                    Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                                        ? objectName : "最大发送间隔"
                                    Layout.preferredWidth: 72
                                    text: root.appBackend ? root.appBackend.message.intervalMax : "3"
                                    validator: DoubleValidator { bottom: 0; top: 300 }
                                    onEditingFinished: root.applyIfUnlocked(function() {
                                        root.appBackend.message.intervalMax = Number(text)
                                    })
                                }
                                Text { text: "秒"; color: WxTheme.clTextSecondary }
                            }
                        }
                        SettingsRow {
                            objectName: "settingsMessageFuzzySearchRow"
                            title: "模糊搜索（取首个结果）"
                            description: ""
                            Switch {
                                objectName: "settingsMessageFuzzySearch"
                                Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled
                                    ? objectName : "模糊搜索（取首个结果）"
                                checked: root.appBackend ? root.appBackend.message.fuzzySearchEnabled : false
                                enabled: !!root.appBackend && !root.interactionLocked
                                onToggled: root.applyIfUnlocked(function() {
                                    root.appBackend.message.fuzzySearchEnabled = checked
                                })
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: parent.width
                        spacing: 0
                        SettingsHeading {
                            title: "自动发送好友申请"
                            subtitle: "行内为空时才使用这里的默认值"
                        }
                        SettingsRow {
                            title: "每批添加人数"
                            description: "控制单次任务最多选择的人数"
                            SpinBox {
                                objectName: "settingsFriendBatchLimit"
                                Accessible.name: "每批添加人数"
                                implicitWidth: 140
                                from: root.appBackend ? root.appBackend.friends.batchLimitMinimum : 1
                                to: root.appBackend ? root.appBackend.friends.batchLimitMaximum : 1000
                                value: root.appBackend ? root.appBackend.friends.batchLimit : 100
                                editable: true
                                enabled: !root.interactionLocked
                                onValueModified: root.applyIfUnlocked(function() {
                                    root.appBackend.friends.batchLimit = value
                                })
                            }
                        }
                        SettingsRow {
                            title: "默认打招呼语"
                            description: "两处都为空时保留微信申请窗口原文"
                            TextField {
                                width: 360
                                text: root.appBackend ? root.appBackend.friends.defaultGreeting : ""
                                onEditingFinished: root.applyIfUnlocked(function() {
                                    root.appBackend.friends.defaultGreeting = text
                                })
                            }
                        }
                        SettingsRow {
                            title: "默认后缀"
                            description: "仅影响“使用全局”的行；无＝备注只保留姓名"
                            FriendRelationshipSelector {
                                width: 220
                                allowGlobal: false
                                choice: root.appBackend ? (root.appBackend.friends.defaultRelationship || "无") : "妈妈"
                                options: root.appBackend ? root.appBackend.friends.relationshipOptions : []
                                onChosen: function(value) {
                                    root.applyIfUnlocked(function() { root.appBackend.friends.defaultRelationship = value })
                                }
                            }
                        }
                        SettingsRow {
                            title: "请求间隔"
                            description: root.intervalValidation || "每条结束后额外等待，1 至 300 秒"
                            RowLayout {
                                SettingsIntervalField {
                                    id: friendIntervalMin
                                    objectName: "settingsFriendIntervalMin"
                                    Accessible.name: "settingsFriendIntervalMin"
                                    Layout.preferredWidth: 72
                                    savedValue: root.appBackend ? root.appBackend.friends.intervalMin : 15
                                    interactionLocked: root.interactionLocked
                                    onCommitted: function(value) {
                                        root.applyIfUnlocked(function() { root.appBackend.friends.intervalMin = value })
                                        root.intervalValidation = ""
                                    }
                                    onInvalidInput: root.intervalValidation = "请输入 1 至 300 的整数，已恢复保存值"
                                }
                                Text { text: "至"; color: WxTheme.clTextHint }
                                SettingsIntervalField {
                                    id: friendIntervalMax
                                    objectName: "settingsFriendIntervalMax"
                                    Accessible.name: "settingsFriendIntervalMax"
                                    Layout.preferredWidth: 72
                                    savedValue: root.appBackend ? root.appBackend.friends.intervalMax : 30
                                    interactionLocked: root.interactionLocked
                                    onCommitted: function(value) {
                                        root.applyIfUnlocked(function() { root.appBackend.friends.intervalMax = value })
                                        root.intervalValidation = ""
                                    }
                                    onInvalidInput: root.intervalValidation = "请输入 1 至 300 的整数，已恢复保存值"
                                }
                                Text { text: "秒"; color: WxTheme.clTextSecondary }
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: parent.width
                        spacing: 0
                        SettingsHeading {
                            title: "自动化与恢复"
                            subtitle: "破坏性动作一旦触发不会自动重试"
                        }
                        SettingsRow {
                            title: "结果无法确认"
                            description: "发送或提交已触发，但没有可靠后置条件"
                            ComboBox {
                                width: 180
                                model: ["标记未知并继续", "标记未知并停止"]
                                currentIndex: root.appBackend && root.appBackend.settings.unknownPolicy === "stop" ? 1 : 0
                                onActivated: root.applyIfUnlocked(function() {
                                    root.appBackend.settings.unknownPolicy = currentIndex === 1 ? "stop" : "continue"
                                })
                            }
                        }
                        SettingsRow {
                            title: "Agent 自动重启"
                            description: "UIA 卡死或进程异常时的最大重启次数"
                            SpinBox {
                                from: 0
                                to: 2
                                value: root.appBackend ? root.appBackend.settings.agentRestartLimit : 2
                                onValueModified: root.applyIfUnlocked(function() {
                                    root.appBackend.settings.agentRestartLimit = value
                                })
                            }
                        }
                        SettingsRow {
                            title: "微信恢复方式"
                            description: "UIA 仍不可用时如何处理微信客户端"
                            ComboBox {
                                width: 180
                                model: ["弹窗确认", "仅手动处理", "静默重启"]
                                currentIndex: {
                                    if (!root.appBackend) return 0
                                    var mode = root.appBackend.settings.wechatRecoveryMode
                                    return mode === "manual" ? 1 : mode === "silent" ? 2 : 0
                                }
                                onActivated: root.applyIfUnlocked(function() {
                                    root.appBackend.settings.wechatRecoveryMode =
                                        currentIndex === 1 ? "manual" : currentIndex === 2 ? "silent" : "confirm"
                                })
                            }
                        }
                        SettingsRow {
                            title: "登录等待"
                            description: "微信重启后等待用户登录的最长时间"
                            SpinBox {
                                from: 30
                                to: 300
                                stepSize: 10
                                value: root.appBackend ? root.appBackend.settings.loginTimeout : 90
                                onValueModified: root.applyIfUnlocked(function() {
                                    root.appBackend.settings.loginTimeout = value
                                })
                                textFromValue: function(value) { return value + " 秒" }
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: parent.width
                        spacing: 0
                        SettingsHeading {
                            title: "外观"
                            subtitle: "外观设置会自动保存在本机"
                        }
                        SettingsRow {
                            title: "颜色模式"
                            description: "影响窗口、控件和预览区域"
                            RowLayout {
                                Button {
                                    text: "浅色"
                                    onClicked: root.applyIfUnlocked(function() {
                                        WxTheme.isDark = false
                                        root.appBackend.settings.isDark = false
                                    })
                                    background: Rectangle {
                                        color: !WxTheme.isDark ? WxTheme.clBgSelected : "transparent"
                                        border.color: WxTheme.clSurfaceBorder
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                                Button {
                                    text: "深色"
                                    onClicked: root.applyIfUnlocked(function() {
                                        WxTheme.isDark = true
                                        root.appBackend.settings.isDark = true
                                    })
                                    background: Rectangle {
                                        color: WxTheme.isDark ? WxTheme.clBgSelected : "transparent"
                                        border.color: WxTheme.clSurfaceBorder
                                        radius: WxTheme.radiusSmall
                                    }
                                }
                            }
                        }
                        SettingsRow {
                            title: "毛玻璃背景"
                            description: "关闭后回退为普通实色界面"
                            Switch {
                                checked: WxTheme.glassEnabled
                                onToggled: root.applyIfUnlocked(function() {
                                    WxTheme.glassEnabled = checked
                                    root.appBackend.settings.glassEnabled = checked
                                })
                            }
                        }
                        SettingsRow {
                            title: "毛玻璃透明度"
                            description: "拖动滑块或悬停滚轮调整，每格 5%"
                            RowLayout {
                                Slider {
                                    Layout.preferredWidth: 210
                                    from: 45
                                    to: 90
                                    stepSize: 5
                                    wheelEnabled: true
                                    value: WxTheme.glassOpacity
                                    enabled: WxTheme.glassEnabled
                                    onMoved: root.applyIfUnlocked(function() {
                                        WxTheme.glassOpacity = Math.round(value)
                                        root.appBackend.settings.glassOpacity = Math.round(value)
                                    })
                                }
                                Text {
                                    text: WxTheme.glassOpacity + "%"
                                    Layout.preferredWidth: 42
                                    color: WxTheme.clTextPrimary
                                    font.family: WxTheme.fontFamily
                                    font.pixelSize: WxTheme.fontSizeSmall
                                    font.bold: true
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            Layout.leftMargin: 28
                            Layout.rightMargin: 28
                            Layout.topMargin: 18
                            color: WxTheme.clSuccessSoft
                            border.color: WxTheme.clPrimary
                            radius: WxTheme.radiusSmall
                            Text {
                                anchors.fill: parent
                                anchors.margins: 12
                                text: "业务输入框拥有独立可读性下限，不会跟随窗口透明度变得难以辨认。"
                                color: WxTheme.clTextPrimary
                                font.family: WxTheme.fontFamily
                                font.pixelSize: WxTheme.fontSizeTiny
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }

        WxRoundedBand {
            objectName: "settingsFooterBand"
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            fillColor: WxTheme.clToolbarFill
            radius: WxTheme.radiusLarge
            roundTop: false
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: WxTheme.clSurfaceBorder
            }
            Button {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "完成"
                objectName: "settingsDoneButton"
                onClicked: root.close()
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
                    color: parent.hovered ? WxTheme.clPrimaryHover : WxTheme.clPrimary
                    radius: WxTheme.radiusSmall
                }
            }
        }
    }

    component SettingsHeading: Item {
        property string title: ""
        property string subtitle: ""
        Layout.fillWidth: true
        Layout.preferredHeight: 82
        Column {
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Text {
                text: parent.parent.title
                color: WxTheme.clTextPrimary
                font.family: WxTheme.fontFamily
                font.pixelSize: 20
                font.bold: true
            }
            Text {
                text: parent.parent.subtitle
                color: WxTheme.clTextHint
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeTiny
            }
        }
    }

    component SettingsRow: Item {
        id: rowRoot
        property string title: ""
        property string description: ""
        default property alias control: controlHost.data
        Layout.fillWidth: true
        Layout.preferredHeight: 66
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            height: 1
            color: WxTheme.clSurfaceBorder
        }
        Column {
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.right: controlHost.left
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                width: parent.width
                text: rowRoot.title
                elide: Text.ElideRight
                color: WxTheme.clTextPrimary
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
                font.bold: true
            }
            Text {
                width: parent.width
                text: rowRoot.description
                elide: Text.ElideRight
                color: WxTheme.clTextHint
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeTiny
            }
        }
        Item {
            id: controlHost
            anchors.right: parent.right
            anchors.rightMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            width: childrenRect.width
            height: Math.max(34, childrenRect.height)
        }
    }
}
