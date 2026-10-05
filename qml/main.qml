import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "theme"

ApplicationWindow {
    id: root

    width: 1320
    height: 880
    minimumWidth: 960
    minimumHeight: 680
    visible: false
    opacity: 1
    title: "福格微信助手"
    color: "transparent"
    flags: typeof windowShell !== "undefined" ? windowShell.initialWindowFlags
        : Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint

    property rect normalGeometry: Qt.rect(0, 0, 1320, 880)
    property bool _applyingWindowLayout: false
    property string shellLayoutMode: "normal"
    property bool closeAfterContacts: false

    onShellLayoutModeChanged: {
        if (typeof windowShell !== "undefined") windowShell.setLayoutMode(shellLayoutMode)
    }

    function screenGeometry() {
        if (Screen.desktopAvailableWidth > 0 && Screen.desktopAvailableHeight > 0) {
            return Qt.rect(
                Screen.virtualX,
                Screen.virtualY,
                Screen.desktopAvailableWidth,
                Screen.desktopAvailableHeight
            )
        }
        return Qt.rect(Screen.virtualX, Screen.virtualY, Screen.width, Screen.height)
    }

    function initializeWindowGeometry() {
        var geometry = root.screenGeometry()
        var widthMargin = geometry.width > root.minimumWidth ? 32 : 0
        var heightMargin = geometry.height > root.minimumHeight ? 32 : 0
        var targetWidth = Math.max(
            root.minimumWidth,
            Math.min(1320, geometry.width - widthMargin)
        )
        var targetHeight = Math.max(
            root.minimumHeight,
            Math.min(880, geometry.height - heightMargin)
        )

        root._applyingWindowLayout = true
        root.width = Math.round(targetWidth)
        root.height = Math.round(targetHeight)
        root.x = Math.round(geometry.x + Math.max(0, (geometry.width - targetWidth) / 2))
        root.y = Math.round(geometry.y + Math.max(0, (geometry.height - targetHeight) / 2))
        root.normalGeometry = Qt.rect(root.x, root.y, root.width, root.height)
        root._applyingWindowLayout = false

        root.syncWindowVisuals()
        root.show()
    }

    function captureNormalGeometry() {
        if (!root._applyingWindowLayout
                && root.shellLayoutMode === "normal"
                && root.visibility === Window.Windowed
                && root.width >= root.minimumWidth
                && root.height >= root.minimumHeight) {
            root.normalGeometry = Qt.rect(root.x, root.y, root.width, root.height)
        }
    }

    function rememberNormalGeometry() {
        if (root.visibility === Window.Windowed && root.shellLayoutMode === "normal") {
            root.normalGeometry = Qt.rect(root.x, root.y, root.width, root.height)
        }
    }

    function snapRectForMode(mode) {
        var g = root.screenGeometry()
        if (mode === "left") {
            return Qt.rect(g.x, g.y, Math.max(root.minimumWidth, Math.round(g.width / 2)), g.height)
        }
        if (mode === "right") {
            var halfWidth = Math.max(root.minimumWidth, Math.round(g.width / 2))
            return Qt.rect(g.x + g.width - halfWidth, g.y, halfWidth, g.height)
        }
        return Qt.rect(g.x, g.y, g.width, g.height)
    }

    function applyWindowGeometry(rect, updateNormal) {
        root._applyingWindowLayout = true
        root.showNormal()
        root.width = Math.max(root.minimumWidth, Math.round(rect.width))
        root.height = Math.max(root.minimumHeight, Math.round(rect.height))
        root.x = Math.round(rect.x)
        root.y = Math.round(rect.y)
        root._applyingWindowLayout = false
        if (updateNormal !== false) {
            root.shellLayoutMode = "normal"
            root.normalGeometry = Qt.rect(root.x, root.y, root.width, root.height)
        }
    }

    function applySnapMode(mode) {
        if (root.visibility !== Window.Windowed) {
            root.showNormal()
        }
        if (mode === "maximize") {
            root.rememberNormalGeometry()
            root.shellLayoutMode = "maximized"
            root.showMaximized()
            return
        }
        if (mode === "left" || mode === "right") {
            root.rememberNormalGeometry()
            root.shellLayoutMode = mode
            root.applyWindowGeometry(root.snapRectForMode(mode), false)
        }
    }

    function centerAndRestore() {
        var g = root.screenGeometry()
        var targetWidth = Math.max(root.minimumWidth, Math.min(root.normalGeometry.width, g.width - 48))
        var targetHeight = Math.max(root.minimumHeight, Math.min(root.normalGeometry.height, g.height - 48))
        root.applyWindowGeometry(Qt.rect(
            g.x + Math.round((g.width - targetWidth) / 2),
            g.y + Math.round((g.height - targetHeight) / 2),
            targetWidth,
            targetHeight
        ), true)
    }

    function enterFullScreenPreview() {
        if (root.visibility !== Window.FullScreen) {
            root.rememberNormalGeometry()
            root.shellLayoutMode = "fullscreen"
            root.showFullScreen()
        }
    }

    function exitFullScreenPreview() {
        if (root.visibility === Window.FullScreen) {
            root.applyWindowGeometry(root.normalGeometry, true)
        }
    }

    function toggleFullScreenPreview() {
        if (root.visibility === Window.FullScreen) {
            root.exitFullScreenPreview()
        } else {
            root.enterFullScreenPreview()
        }
    }

    onXChanged: captureNormalGeometry()
    onYChanged: captureNormalGeometry()
    onWidthChanged: captureNormalGeometry()
    onHeightChanged: captureNormalGeometry()
    onVisibilityChanged: {
        if (visibility === Window.Maximized) shellLayoutMode = "maximized"
        else if (visibility === Window.FullScreen) shellLayoutMode = "fullscreen"
        else if (visibility === Window.Windowed
                 && (shellLayoutMode === "maximized" || shellLayoutMode === "fullscreen"))
            shellLayoutMode = "normal"
    }

    background: Rectangle {
        color: typeof windowShell !== "undefined" && !windowShell.backdropAvailable
            ? WxTheme.clBgWindow : WxTheme.clWindowTint
        Behavior on color {
            ColorAnimation { duration: WxTheme.animSlow }
        }
    }

    function syncWindowVisuals() {
        if (typeof windowShell !== "undefined" && windowShell) {
            windowShell.applyVisuals(WxTheme.isDark, WxTheme.glassEnabled, WxTheme.glassOpacity)
        }
    }

    // 监听窗口视觉变化，调用后端 Win32 API 动态刷新原生材质
    Connections {
        target: typeof windowShell !== "undefined" ? windowShell : null
        function onInteractiveMoveStarted() {
            if (root.shellLayoutMode === "left" || root.shellLayoutMode === "right")
                root.shellLayoutMode = "normal"
        }
    }

    Connections {
        target: WxTheme
        ignoreUnknownSignals: true
        function onIsDarkChanged() {
            root.syncWindowVisuals()
        }
        function onGlassEnabledChanged() {
            root.syncWindowVisuals()
        }
        function onGlassOpacityChanged() {
            root.syncWindowVisuals()
        }
    }

    // 先读取持久化外观，再在事件循环中按可用工作区显示窗口。
    Component.onCompleted: {
        if (typeof backend !== "undefined" && backend) {
            root.title = backend.versionInfo
            WxTheme.isDark = backend.isDark
            WxTheme.glassEnabled = backend.glassEnabled
            WxTheme.glassOpacity = backend.glassOpacity
        }
        Qt.callLater(root.initializeWindowGeometry)
    }

    Connections {
        target: typeof backend !== "undefined" ? backend : null
        function onVersionInfoChanged() {
            root.title = backend.versionInfo
        }
        function onIsDarkChanged() {
            WxTheme.isDark = backend.isDark
        }
    }

    onClosing: function(closeEvent) {
        if (root.closeAfterContacts) {
            closeEvent.accepted = false
            return
        }
        if (typeof backend !== "undefined" && backend) {
            if ((backend.task && backend.task.active)
                    || (backend.contacts && backend.contacts.busy)
                    || backend.phase === "running" || backend.phase === "paused") {
                closeEvent.accepted = false
                closeConfirmDialog.open()
            }
        }
    }

    // 关闭确认对话框
    ConfirmDialog {
        id: closeConfirmDialog
        message: "任务正在进行中，关闭窗口会请求安全停止并取消联系人读取或导出。是否确认关闭？"
        isDanger: true
        confirmText: "确认关闭"
        cancelText: "取消"
        onConfirmed: {
            if (typeof backend !== "undefined" && backend.contacts && backend.contacts.busy) {
                root.closeAfterContacts = true
                backend.contacts.cancel()
                if (!backend.contacts.busy) Qt.quit()
            } else {
                Qt.quit()
            }
        }
    }

    Connections {
        target: typeof backend !== "undefined" && backend.contacts ? backend.contacts : null
        function onBusyChanged() {
            if (root.closeAfterContacts && !backend.contacts.busy) Qt.quit()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        WxTitleBar {
            id: customTitleBar
            Layout.fillWidth: true
            visible: root.visibility !== Window.FullScreen
            z: 100
            window: root
            titleBackend: typeof backend !== "undefined" ? backend : null
            settingsEnabled: true
            openSettings: function() {
                if (customTitleBar.settingsEnabled) appRoot.openSettings(3)
            }
        }

        App {
            id: appRoot
            objectName: "appRoot"
            Layout.fillWidth: true
            Layout.fillHeight: true
            appBackend: typeof backend !== "undefined" ? backend : null
        }
    }

    Shortcut {
        sequence: "F11"
        onActivated: root.toggleFullScreenPreview()
    }

    Shortcut {
        sequence: "Esc"
        enabled: root.visibility === Window.FullScreen
        onActivated: root.exitFullScreenPreview()
    }

    // 全局 Toast 提示
    Toast {
        id: globalToast
    }

    Connections {
        target: typeof backend !== "undefined" ? backend : null
        function onShowToast(message, type) {
            globalToast.show(message, type)
        }
    }

    component ResizeHandle: MouseArea {
        property int resizeEdges: Qt.LeftEdge

        hoverEnabled: true
        enabled: root.visibility === Window.Windowed
        acceptedButtons: Qt.LeftButton
        z: 9000
        onPressed: {
            if (root.visibility === Window.Windowed) {
                root.shellLayoutMode = "normal"
                root.startSystemResize(resizeEdges)
            }
        }
    }

    ResizeHandle {
        resizeEdges: Qt.LeftEdge
        width: 6
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeHorCursor
    }

    ResizeHandle {
        resizeEdges: Qt.RightEdge
        width: 6
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeHorCursor
    }

    ResizeHandle {
        resizeEdges: Qt.TopEdge
        height: 6
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        cursorShape: Qt.SizeVerCursor
    }

    ResizeHandle {
        resizeEdges: Qt.BottomEdge
        height: 6
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeVerCursor
    }

    ResizeHandle {
        resizeEdges: Qt.LeftEdge | Qt.TopEdge
        width: 10
        height: 10
        anchors.left: parent.left
        anchors.top: parent.top
        cursorShape: Qt.SizeFDiagCursor
    }

    ResizeHandle {
        resizeEdges: Qt.RightEdge | Qt.TopEdge
        width: 10
        height: 10
        anchors.right: parent.right
        anchors.top: parent.top
        cursorShape: Qt.SizeBDiagCursor
    }

    ResizeHandle {
        resizeEdges: Qt.LeftEdge | Qt.BottomEdge
        width: 10
        height: 10
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeBDiagCursor
    }

    ResizeHandle {
        resizeEdges: Qt.RightEdge | Qt.BottomEdge
        width: 10
        height: 10
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeFDiagCursor
    }

    // 启动加载动画遮罩
    Rectangle {
        id: startupLoader
        objectName: "startupLoader"
        anchors.fill: parent
        color: WxTheme.clBgWindow
        z: 10000
        visible: opacity > 0

        Behavior on opacity {
            NumberAnimation { duration: WxTheme.animSlow }
        }

        Column {
            anchors.centerIn: parent
            spacing: WxTheme.spMedium

            Image {
                objectName: "startupBrandLogo"
                anchors.horizontalCenter: parent.horizontalCenter
                width: 96
                height: 96
                source: "../assets/fuge-logo-256.png"
                fillMode: Image.PreserveAspectFit
                smooth: true
            }

            // 微信绿旋转加载环
            BusyIndicator {
                id: busyInd
                anchors.horizontalCenter: parent.horizontalCenter
                running: startupLoader.visible
                contentItem: Item {
                    implicitWidth: 40
                    implicitHeight: 40
                    Rectangle {
                        id: rect
                        anchors.fill: parent
                        color: "transparent"
                        border.color: WxTheme.clPrimary
                        border.width: 3
                        radius: 20
                    }
                    RotationAnimator {
                        target: rect
                        from: 0
                        to: 360
                        duration: 1000
                        running: busyInd.running
                        loops: Animation.Infinite
                    }
                }
            }

            Text {
                text: "福格微信助手"
                anchors.horizontalCenter: parent.horizontalCenter
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeNormal + 2
                font.bold: true
                color: WxTheme.clTextPrimary
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                text: "正在初始化应用..."
                anchors.horizontalCenter: parent.horizontalCenter
                font.family: WxTheme.fontFamily
                font.pixelSize: WxTheme.fontSizeSmall
                color: WxTheme.clTextSecondary
                horizontalAlignment: Text.AlignHCenter
            }
        }

        Timer {
            interval: 800
            running: true
            repeat: false
            onTriggered: {
                startupLoader.opacity = 0.0
            }
        }
    }
}
