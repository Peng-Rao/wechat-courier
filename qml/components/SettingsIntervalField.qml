import QtQuick
import QtQuick.Controls.Basic

WxTextField {
    id: root
    property real savedValue: 15
    property bool interactionLocked: false
    property bool dirty: false
    signal committed(int value)
    signal invalidInput()
    text: String(savedValue)
    enabled: !interactionLocked
    validator: IntValidator { bottom: 1; top: 300 }
    selectByMouse: true

    function reset() {
        dirty = false
        text = String(savedValue)
    }

    function commit() {
        if (interactionLocked) { reset(); return }
        if (!dirty && text === String(savedValue)) return
        if (!/^[0-9]+$/.test(text) || Number(text) < 1 || Number(text) > 300) {
            reset()
            invalidInput()
            return
        }
        committed(Number(text))
        reset()
    }

    onSavedValueChanged: { if (!dirty) text = String(savedValue) }
    onTextEdited: dirty = true
    onEditingFinished: commit()
    Keys.onReturnPressed: function(event) { commit(); event.accepted = true }
    Keys.onEnterPressed: function(event) { commit(); event.accepted = true }
    onActiveFocusChanged: { if (!activeFocus) commit() }
    onInteractionLockedChanged: { if (interactionLocked) reset() }
}
