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
        property QtObject agent: QtObject {
            property bool connected: false
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
    }

    function cleanup() {
        WxTheme.glassEnabled = true
        WxTheme.glassOpacity = 72
    }

    function test_titlebar_height() {
        compare(titleBar.height, 40)
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
