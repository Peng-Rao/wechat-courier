import QtQuick
import QtQuick.Controls.Basic
import "../theme"

WxComboBox {
    id: control
    property string choice: "使用全局"
    property var options: []
    property bool allowGlobal: true
    property bool cellMode: false
    property bool editing: false
    property int modelRow: -1
    readonly property var textMenu: contentItem.ContextMenu.menu
    signal chosen(string value)
    signal editStarted()
    signal editEnded()
    signal navigate(int direction)
    editable: !cellMode || editing
    selectTextByMouse: true
    model: {
        var values = allowGlobal ? ["使用全局"].concat(options) : [].concat(options)
        if (values.indexOf("无") < 0) values.push("无")
        if (choice && values.indexOf(choice) < 0) values.push(choice)
        return values
    }
    currentIndex: model.indexOf(choice || "无")
    function resumeFocus() { contentItem.forceActiveFocus() }
    function beginEdit() {
        if (!enabled) return
        editStarted()
        editing = true
        editText = choice || "无"
        contentItem.forceActiveFocus()
        contentItem.selectAll()
    }
    function commitEdit(value) {
        if (cellMode && !editing) return
        var result = value === undefined ? editText.trim() || "无" : value
        var changed = result !== (choice || "无")
        editing = false
        popup.close()
        if (enabled && changed) chosen(result)
        editText = choice || "无"
        editEnded()
    }
    function cancelEdit() {
        editing = false
        popup.close()
        editText = choice || "无"
        editEnded()
    }
    function handleKey(event) {
        if (event.key === Qt.Key_Escape) {
            cancelEdit()
            event.accepted = true
        } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
            commitEdit()
            if (cellMode) {
                navigate(event.key === Qt.Key_Backtab || (event.modifiers & Qt.ShiftModifier) ? -1 : 1)
                event.accepted = true
            }
        } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !popup.visible) {
            if (cellMode && !editing) beginEdit()
            else commitEdit()
            event.accepted = true
        }
    }
    onActivated: { if (enabled) commitEdit(currentText) }
    onAccepted: { if (enabled) commitEdit() }
    onChoiceChanged: { if (!editing) editText = choice || "无" }
    onEnabledChanged: { if (!enabled) cancelEdit() }
    Keys.priority: Keys.BeforeItem
    Keys.onPressed: function(event) { handleKey(event) }
    onActiveFocusChanged: {
        if (!activeFocus && !popup.visible && !(textMenu && textMenu.visible)) {
            Qt.callLater(function() {
                if (!control.activeFocus && !control.popup.visible && !(control.textMenu && control.textMenu.visible))
                    control.commitEdit()
            })
        }
    }
    contentItem: WxTextField {
        text: control.editable ? control.editText : control.displayText
        readOnly: control.cellMode && !control.editing
        selectByMouse: !readOnly
        leftPadding: 8
        rightPadding: 0
        font: control.font
        background: null
        onTextEdited: control.editText = text
        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) { control.handleKey(event) }
    }
    MouseArea {
        anchors.fill: parent
        z: 2
        visible: control.cellMode && !control.editing
        acceptedButtons: Qt.LeftButton
        onClicked: control.forceActiveFocus()
        onDoubleClicked: control.beginEdit()
    }
    implicitHeight: 36
    background: Rectangle {
        radius: WxTheme.radiusSmall
        color: control.cellMode && !control.editing ? "transparent" : WxTheme.clFieldFill
        border.color: control.activeFocus ? WxTheme.clBorderFocus
            : control.cellMode && !control.editing ? "transparent" : WxTheme.clBorderStrong
    }
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    palette.text: WxTheme.clTextPrimary
    palette.buttonText: WxTheme.clTextPrimary
    palette.base: WxTheme.clFieldFill
    palette.button: WxTheme.clFieldFill
}
