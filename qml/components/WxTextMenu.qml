import QtQuick
import QtQuick.Controls.Basic

WxContextMenu {
    id: root
    objectName: "textEditMenu"
    property var editor: null
    width: 248
    function removeSelection() {
        if (editor && editor.selectedText.length) editor.remove(editor.selectionStart, editor.selectionEnd)
    }
    WxContextMenuItem { text: "撤销"; iconSource: "../icons/undo.svg"; shortcutText: "Ctrl+Z"; enabled: !!root.editor && root.editor.canUndo && !root.editor.readOnly; onTriggered: root.editor.undo() }
    WxContextMenuItem { text: "重做"; iconSource: "../icons/redo.svg"; shortcutText: "Ctrl+Y"; enabled: !!root.editor && root.editor.canRedo && !root.editor.readOnly; onTriggered: root.editor.redo() }
    MenuSeparator { }
    WxContextMenuItem { text: "剪切"; iconSource: "../icons/cut.svg"; shortcutText: "Ctrl+X"; enabled: !!root.editor && root.editor.selectedText.length > 0 && !root.editor.readOnly; onTriggered: root.editor.cut() }
    WxContextMenuItem { text: "复制"; iconSource: "../icons/copy.svg"; shortcutText: "Ctrl+C"; enabled: !!root.editor && root.editor.selectedText.length > 0; onTriggered: root.editor.copy() }
    WxContextMenuItem { text: "粘贴"; iconSource: "../icons/paste.svg"; shortcutText: "Ctrl+V"; enabled: !!root.editor && root.editor.canPaste && !root.editor.readOnly; onTriggered: root.editor.paste() }
    WxContextMenuItem { text: "删除"; iconSource: "../icons/trash.svg"; shortcutText: "Delete"; enabled: !!root.editor && root.editor.selectedText.length > 0 && !root.editor.readOnly; onTriggered: root.removeSelection() }
    MenuSeparator { }
    WxContextMenuItem { text: "全选"; iconSource: "../icons/select_all.svg"; shortcutText: "Ctrl+A"; enabled: !!root.editor && root.editor.length > 0; onTriggered: root.editor.selectAll() }
}
