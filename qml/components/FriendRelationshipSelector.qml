import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ComboBox {
    id: control
    property string choice: "使用全局"
    property var options: []
    property bool allowGlobal: true
    signal chosen(string value)
    editable: true
    selectTextByMouse: true
    model: {
        var values = allowGlobal ? ["使用全局"].concat(options) : [].concat(options)
        if (values.indexOf("无") < 0) values.push("无")
        if (choice && values.indexOf(choice) < 0) values.push(choice)
        return values
    }
    currentIndex: model.indexOf(choice || "无")
    onActivated: { if (enabled) chosen(currentText) }
    onAccepted: { if (enabled) chosen(editText.trim() || "无") }
    onEnabledChanged: { if (!enabled) popup.close() }
    ToolTip.visible: hovered
    ToolTip.text: "可选择后缀，也可输入自定义后缀后按回车；无＝不追加后缀文字"
    font.pixelSize: WxTheme.fontSizeSmall
    palette.text: WxTheme.clTextPrimary
    palette.buttonText: WxTheme.clTextPrimary
    palette.base: WxTheme.clFieldFill
    palette.button: WxTheme.clFieldFill
}
