import AppKit
import ApplicationServices
import CourierCore

struct AccessibilityInspector {
    static let bundleID = "com.tencent.xinWeChat"
    func inspect() -> EnvironmentReport {
        let installedURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: Self.bundleID)
        let version = installedURL.flatMap(Bundle.init(url:))?.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        let application = NSRunningApplication.runningApplications(withBundleIdentifier: Self.bundleID).first
        let trusted = AXIsProcessTrusted()
        var report = EnvironmentReport(accessibility: trusted, installed: installedURL != nil,
                                       running: application != nil, version: version)
        guard installedURL != nil else { report.detail = "未找到 Mac 微信，请先安装官方客户端"; return report }
        guard let application else { report.detail = "微信未运行，请打开微信并登录后重新检测"; return report }
        guard trusted else { report.detail = "辅助功能未授权，请在系统设置中授权福格微信助手后重新检测"; return report }
        let root = AXUIElementCreateApplication(application.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 1)
        var windows: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(root, kAXWindowsAttribute as CFString, &windows)
        guard result == .success, let windows = windows as? [AXUIElement], !windows.isEmpty else {
            report.detail = "无法读取微信窗口（\(result.rawValue)），请确认微信已登录且窗口可见"; return report
        }
        var visited = 0, editable = 0, buttons = 0
        let deadline = Date().addingTimeInterval(4)
        func walk(_ element: AXUIElement, depth: Int) {
            guard depth < 16, visited < 600, Date() < deadline else { return }
            visited += 1
            AXUIElementSetMessagingTimeout(element, 0.2)
            var role: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &role) == .success {
                let role = role as? String ?? ""
                if role == kAXTextFieldRole || role == kAXTextAreaRole { editable += 1 }
                if role == kAXButtonRole { buttons += 1 }
            }
            var children: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &children) == .success,
               let children = children as? [AXUIElement] {
                for child in children { walk(child, depth: depth + 1) }
            }
        }
        for window in windows { walk(window, depth: 0) }
        report.controlsAvailable = editable > 0 && buttons > 3
        report.detail = report.controlsAvailable
            ? "可读取微信控件；当前真实发送仅开放文件传输助手测试"
            : "微信未暴露聊天控件；文件传输助手采用屏幕识别测试，需屏幕录制授权"
        return report
    }
}
