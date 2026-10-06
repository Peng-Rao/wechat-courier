import AppKit
import ApplicationServices
import CourierCore

/// Bounded snapshots; no chat content is included in diagnostics.
struct AccessibilityTree {
    let root: AXUIElement
    init() throws {
        guard AXIsProcessTrusted() else { throw CourierError("辅助功能未授权，请打开系统设置授权福格微信助手") }
        guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: AccessibilityInspector.bundleID).first else {
            throw CourierError("微信未运行")
        }
        root = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 0.3)
        // Querying focus is a standard accessibility entry point for custom UI frameworks.
        _ = value(root, kAXFocusedUIElementAttribute)
    }
    func value(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
        var result: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, attribute as CFString, &result) == .success ? result : nil
    }
    func text(_ element: AXUIElement, _ attribute: String) -> String { value(element, attribute) as? String ?? "" }
    func nodes(from element: AXUIElement? = nil) -> [AXUIElement] {
        var result: [AXUIElement] = []
        let deadline = Date().addingTimeInterval(3)
        func walk(_ node: AXUIElement, _ depth: Int) {
            guard depth <= 40, result.count < 1200, Date() < deadline else { return }
            guard !result.contains(where: { CFEqual($0, node) }) else { return }
            result.append(node)
            AXUIElementSetMessagingTimeout(node, 0.15)
            for child in value(node, kAXChildrenAttribute) as? [AXUIElement] ?? [] { walk(child, depth + 1) }
        }
        walk(element ?? root, 0)
        return result
    }
    func diagnostic() -> [String: String] {
        let all = nodes()
        let counts = Dictionary(grouping: all, by: { text($0, kAXRoleAttribute) }).mapValues(\.count)
        var report = counts.mapValues(String.init)
        for attribute in ["AXManualAccessibility", "AXEnhancedUserInterface"] {
            var settable = DarwinBoolean(false)
            let status = AXUIElementIsAttributeSettable(root, attribute as CFString, &settable)
            report[attribute] = "status=\(status.rawValue), settable=\(settable.boolValue)"
        }
        report["nodeCount"] = String(all.count)
        report["chatHeader"] = String(all.contains { text($0, kAXIdentifierAttribute) == "big_title_line_h_view" })
        report["messageList"] = String(all.contains { text($0, kAXIdentifierAttribute) == "chat_message_list" })
        return report
    }
}
