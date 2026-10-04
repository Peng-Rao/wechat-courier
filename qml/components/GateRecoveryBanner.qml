import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import "../theme"

Rectangle {
    id: root
    property var appBackend: null
    readonly property var agent: appBackend ? appBackend.agent : null
    readonly property var recovery: agent && agent.gateRecovery ? agent.gateRecovery : ({})
    readonly property bool busy: !!(agent && agent.gateRecoveryBusy)
    readonly property bool contactsBusy: !!(appBackend && appBackend.contacts && appBackend.contacts.busy)
    objectName: "gateRecoveryBanner"
    visible: !!(agent && (agent.gateRecoveryActive || agent.reasonCode === "AGENT_ALREADY_RUNNING"))
    implicitHeight: visible ? content.implicitHeight + 16 : 0
    color: WxTheme.clToolbarFill

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8
        Text {
            Layout.fillWidth: true
            text: root.agent ? root.agent.recoveryStatus + "：" + root.agent.detail : ""
            wrapMode: Text.Wrap
            color: WxTheme.clTextSecondary
            font.family: WxTheme.fontFamily
            font.pixelSize: WxTheme.fontSizeTiny
        }
        Button {
            objectName: "gateInspectButton"
            text: "检测恢复"
            enabled: !root.busy && !root.contactsBusy
            onClicked: {
                if (root.agent.connected) root.agent.inspect()
                else root.agent.restart()
            }
        }
        Button {
            objectName: "gateCancelButton"
            text: "取消恢复"
            visible: root.busy
            onClicked: root.agent.cancelGateRecovery()
        }
        Button {
            objectName: "gateDiagnosticsButton"
            text: "导出诊断包"
            onClicked: diagnostics.open()
        }
    }

    FileDialog {
        id: diagnostics
        title: "导出诊断包"
        fileMode: FileDialog.SaveFile
        nameFilters: ["诊断包 (*.zip)"]
        defaultSuffix: "zip"
        onAccepted: {
            if (root.appBackend && root.appBackend.task)
                root.appBackend.task.exportDiagnostics(selectedFile.toString())
        }
    }
}
