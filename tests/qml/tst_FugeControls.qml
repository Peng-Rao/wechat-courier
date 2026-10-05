import QtQuick
import QtQuick.Controls.Basic
import QtTest
import "../../qml/components"
import "../../qml/theme"

TestCase {
    id: tests
    name: "FugeControls"
    when: windowShown
    visible: true
    width: 960; height: 680
    WxTextField { id: field; x: 20; y: 20; width: 240; text: "sample" }
    WxSpinInput { id: stepper; x: 20; y: 80; from: 1; to: 1000; value: 100 }
    WxComboBox { id: combo; x: 20; y: 140; model: ["选项一", "选项二"]; editable: true }
    WxButton { id: primary; x: 20; y: 200; primary: true; text: "开始"; iconName: "play" }
    WxComboBox { id: readonlyCombo; x: 20; y: 250; model: ["账号一", "账号二"]; editable: false }

    function cleanup() { field.ContextMenu.menu.close(); combo.popup.close(); readonlyCombo.popup.close(); wait(220); }
    function test_brand_control_dimensions() {
        compare(primary.height, 36)
        compare(field.height, 36)
        compare(stepper.height, 36)
        compare(combo.height, 36)
        compare(primary.foreground, "#252220")
    }
    function test_stepper_mouse_and_keyboard() {
        stepper.value = 100
        mouseClick(stepper.up.indicator, 17, 18)
        compare(stepper.value, 101)
        mouseClick(stepper.down.indicator, 17, 18)
        compare(stepper.value, 100)
        stepper.contentItem.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_2); keyClick(Qt.Key_5); keyClick(Qt.Key_0)
        keyClick(Qt.Key_Tab)
        compare(stepper.value, 250)
    }
    function test_chinese_edit_menu_actions_and_escape() {
        field.text = "sample"
        field.forceActiveFocus()
        field.selectAll()
        field.ContextMenu.menu.popup()
        tryCompare(field.ContextMenu.menu, "opened", true)
        var menu = field.ContextMenu.menu
        compare(menu.itemAt(0).text, "撤销")
        compare(menu.itemAt(4).text, "复制")
        verify(menu.itemAt(4).enabled)
        menu.itemAt(6).triggered()
        compare(field.text, "")
        keyClick(Qt.Key_Escape)
        tryCompare(menu, "opened", false)
    }
    function test_combo_keyboard_selection_and_custom_input() {
        combo.currentIndex = 0
        mouseClick(combo, combo.width - 16, 18)
        tryCompare(combo.popup, "opened", true)
        keyClick(Qt.Key_Down); keyClick(Qt.Key_Return)
        compare(combo.currentIndex, 1)
        combo.contentItem.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_C); keyClick(Qt.Key_U); keyClick(Qt.Key_S)
        compare(combo.editText, "cus")
    }
    function test_readonly_combo_opens_from_its_text_area() {
        mouseClick(readonlyCombo, 30, 18)
        tryCompare(readonlyCombo.popup, "opened", true)
        keyClick(Qt.Key_Down); keyClick(Qt.Key_Return)
        compare(readonlyCombo.currentIndex, 1)
    }
}
