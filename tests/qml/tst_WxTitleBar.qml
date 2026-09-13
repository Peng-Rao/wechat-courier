import QtQuick
import QtTest
import "../../qml/components"
import "../../qml/theme"

TestCase {
    name: "WxTitleBar"

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
}
