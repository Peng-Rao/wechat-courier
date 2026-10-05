import QtQuick
import QtQuick.Controls.Basic
import "../theme"

ComboBox {
    id: root
    implicitWidth: 180
    implicitHeight: WxTheme.controlHeight
    leftPadding: 10; rightPadding: 32
    font.family: WxTheme.fontFamily
    font.pixelSize: WxTheme.fontSizeNormal
    opacity: enabled ? 1 : 0.5
    onEnabledChanged: if (!enabled) popup.close()
    contentItem: WxTextField {
        enabled: root.editable
        opacity: 1
        leftPadding: 0; rightPadding: 0
        text: root.editable ? root.editText : root.displayText
        readOnly: !root.editable
        autoScroll: root.editable
        validator: root.validator
        inputMethodHints: root.inputMethodHints
        background: null
        onTextEdited: root.editText = text
    }
    indicator: WxIcon {
        x: root.width - width - 10; y: (root.height - height) / 2
        iconSize: 16; iconSource: "../icons/arrow_down.svg"; iconColor: WxTheme.clTextSecondary; hoverScale: false
    }
    background: Rectangle { radius: 6; color: WxTheme.clFieldFill; border.color: root.activeFocus ? WxTheme.clBorderFocus : root.hovered ? WxTheme.clTextSecondary : WxTheme.clBorderStrong }
    delegate: ItemDelegate {
        width: root.width
        height: 36
        text: root.textRole ? (Array.isArray(root.model) ? modelData[root.textRole] : model[root.textRole]) : modelData
        font: root.font
        highlighted: root.highlightedIndex === index
        contentItem: Text { text: parent.text; font: parent.font; color: WxTheme.clTextPrimary; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { radius: 4; color: parent.highlighted ? WxTheme.clBgSelected : parent.hovered ? WxTheme.clBgHover : "transparent" }
    }
    popup: Popup {
        y: root.height + 4; width: root.width; padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        background: Rectangle { radius: 6; color: WxTheme.clBgPrimary; border.color: WxTheme.clBorderStrong }
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: WxScrollBar { }
        }
    }
}
