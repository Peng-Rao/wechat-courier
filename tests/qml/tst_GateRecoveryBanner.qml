import QtQuick
import QtQuick.Window
import QtTest
import "../../qml/components"

TestCase {
    name: "GateRecoveryBanner"
    when: windowShown
    QtObject {
        id: agentMock
        property bool connected: true
        property bool gateRecoveryActive: true
        property bool gateRecoveryBusy: true
        property string reasonCode: "GATE_RESTARTING"
        property string recoveryStatus: "正在重启微信"
        property string detail: "正在恢复异常退出后的自动化连接"
        property var gateRecovery: ({stage: "restarting", attempt: 1})
        property int cancelled: 0
        property int inspections: 0
        function inspect() { inspections++ }
        function restart() { inspections++ }
        function cancelGateRecovery() { cancelled++ }
    }
    QtObject { id: backend; property var agent: agentMock }
    Window {
        id: testWindow
        width: 960
        height: 680
        visible: true
        GateRecoveryBanner { id: banner; width: parent.width; appBackend: backend }
    }
    function test_controls_and_minimum_width() {
        var cancel = findChild(banner, "gateCancelButton")
        var inspect = findChild(banner, "gateInspectButton")
        var exportButton = findChild(banner, "gateDiagnosticsButton")
        verify(cancel.visible)
        verify(!inspect.enabled)
        verify(exportButton.x + exportButton.width <= banner.width)
        mouseClick(cancel)
        compare(agentMock.cancelled, 1)
        agentMock.gateRecovery = {stage: "blocked", attempt: 1}
        agentMock.gateRecoveryBusy = false
        tryCompare(inspect, "enabled", true)
        mouseClick(inspect)
        compare(agentMock.inspections, 1)
        agentMock.gateRecoveryActive = false
        agentMock.gateRecovery = {stage: "completed"}
        agentMock.reasonCode = ""
        tryCompare(banner, "visible", false)
    }
}
