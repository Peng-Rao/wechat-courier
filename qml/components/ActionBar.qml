import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    property var barBackend: null
    signal startSendRequested()

    height: WxTheme.actionBarHeight
    color: WxTheme.clToolbarFill

    // 顶部分隔线
    Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: WxTheme.clSurfaceBorder
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: WxTheme.spLarge
        anchors.rightMargin: WxTheme.spLarge
        spacing: WxTheme.spMedium

        // ── 左侧配置 ──
        RowLayout {
            spacing: WxTheme.spSmall

            Text {
                text: "间隔"
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
                color: WxTheme.clTextSecondary
                leftPadding: WxTheme.spSmall
            }

            WxSpinBox {
                id: minSpin
                from: 0
                to: 60
                value: barBackend ? Math.round(barBackend.sendIntervalMin) : 2
                enabled: barBackend ? barBackend.inputsEnabled : false
                onValueModified: function(newValue) {
                    if (barBackend) {
                        barBackend.sendIntervalMin = newValue
                        if (barBackend.sendIntervalMax < newValue) {
                            barBackend.sendIntervalMax = newValue
                        }
                    }
                }
            }

            Text {
                text: "~"
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
                color: WxTheme.clTextSecondary
            }

            WxSpinBox {
                id: maxSpin
                from: 0
                to: 60
                value: barBackend ? Math.round(barBackend.sendIntervalMax) : 3
                enabled: barBackend ? barBackend.inputsEnabled : false
                onValueModified: function(newValue) {
                    if (barBackend) {
                        barBackend.sendIntervalMax = newValue
                        if (barBackend.sendIntervalMin > newValue) {
                            barBackend.sendIntervalMin = newValue
                        }
                    }
                }
            }

            Text {
                text: "秒"
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
                color: WxTheme.clTextSecondary
            }
        }

        Item { Layout.fillWidth: true }

        // ── 右侧按钮 ──
    ActionButtons {
        btnBackend: barBackend
        onStartRequested: {
            var hasError = false
            if (!barBackend || barBackend.friendListText.trim() === "") {
                barBackend.showToast("请输入接收好友名单", "warning")
                hasError = true
            }
            if (!barBackend || barBackend.templateText.trim() === "") {
                barBackend.showToast("请输入消息模板", "warning")
                hasError = true
            }
            if (hasError) return
            root.startSendRequested()
        }
    }
}
}
