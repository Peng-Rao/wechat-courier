import QtQuick
import QtTest
import "../../qml/components"
import "../../qml/theme"

TestCase {
    name: "WxTitleBar"
    when: windowShown
    property int settingsOpenCount: 0

    QtObject {
        id: mockBackend
        property QtObject task: QtObject {
            property bool acceptanceEnabled: false
            property bool taskWindowReady: false
            property string automationStatus: "自动化未就绪"
        }
        property QtObject agent: QtObject {
            property bool connected: false
            property bool processDetected: false
            property bool versionSupported: true
            property bool gateRecoveryActive: false
            property string recoveryStatus: ""
            property string reasonCode: ""
            property bool wechatConnected: false
            property bool wechatSupported: false
            property string wechatVersion: ""
        }
    }

    WxTitleBar {
        id: titleBar
        width: 640
        titleBackend: mockBackend
        openSettings: function() { settingsOpenCount += 1 }
    }

    function init() {
        settingsOpenCount = 0
        titleBar.settingsEnabled = true
        mockBackend.agent.processDetected = false
        mockBackend.agent.versionSupported = true
        mockBackend.agent.gateRecoveryActive = false
        mockBackend.agent.recoveryStatus = ""
    }

    function cleanup() {
        WxTheme.glassEnabled = true
        WxTheme.glassOpacity = 72
    }

    function test_titlebar_height() {
        compare(titleBar.height, 40)
    }

    function test_shared_automation_status() {
        mockBackend.agent.connected = true
        mockBackend.task.automationStatus = "自动化执行中"
        compare(findChild(titleBar, "titleAutomationHealth").text, "自动化执行中")
        mockBackend.task.automationStatus = "微信窗口无响应"
        compare(findChild(titleBar, "titleAutomationHealth").text, "微信窗口无响应")
        mockBackend.task.automationStatus = "自动化未就绪"
        mockBackend.agent.connected = false
    }

    function test_disconnected_agent_overrides_stale_task_health() {
        mockBackend.task.automationStatus = "自动化执行中"
        mockBackend.agent.connected = false
        compare(findChild(titleBar, "titleAutomationHealth").text, "Agent 离线")
        mockBackend.task.automationStatus = "自动化未就绪"
    }

    function test_recovery_is_visible_before_agent_connects() {
        mockBackend.agent.connected = false
        mockBackend.agent.gateRecoveryActive = true
        mockBackend.agent.recoveryStatus = "正在恢复连接"
        compare(findChild(titleBar, "titleAutomationHealth").text, "正在恢复连接")
    }

    function test_unsupported_version_is_a_visible_blocker() {
        mockBackend.agent.connected = true
        mockBackend.agent.processDetected = true
        mockBackend.agent.versionSupported = false
        mockBackend.task.automationStatus = "自动化未就绪"
        var status = findChild(titleBar, "titleAutomationHealth")
        compare(status.text, "微信版本不受支持")
        compare(status.color, WxTheme.clDangerNew)
    }

    function test_long_health_summary_stays_in_native_client_hit_region() {
        mockBackend.agent.connected = true
        mockBackend.task.automationStatus = "正在整理任务窗口"
        var trigger = findChild(titleBar, "healthSummaryButton")
        verify(trigger.mapToItem(titleBar, 0, 0).x >= titleBar.width - 322)
        mockBackend.task.automationStatus = "自动化未就绪"
    }

    function test_titlebar_does_not_change_visual_preferences() {
        compare(WxTheme.glassEnabled, true)
        compare(WxTheme.glassOpacity, 72)
    }

    function test_settings_button_obeys_enabled_state() {
        var settingsArea = findChild(titleBar, "settingsMouseArea")
        verify(settingsArea !== null)

        titleBar.settingsEnabled = false
        compare(settingsArea.enabled, false)
        titleBar.requestSettings()
        compare(settingsOpenCount, 0)

        titleBar.settingsEnabled = true
        compare(settingsArea.enabled, true)
        titleBar.requestSettings()
        compare(settingsOpenCount, 1)
    }
}
