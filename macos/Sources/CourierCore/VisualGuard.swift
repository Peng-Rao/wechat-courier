import Foundation
import CoreGraphics

public struct ScreenText: Sendable {
    public var text: String
    /// Normalized window coordinates, origin at top left.
    public var box: CGRect
    public init(_ text: String, box: CGRect) { self.text = text; self.box = box }
}

public enum FileTransferGuard {
    public static let names = ["File Transfer", "文件传输助手"]
    public static func isTarget(_ text: String) -> Bool { names.contains(text.trimmingCharacters(in: .whitespacesAndNewlines)) }
    public static func header(_ lines: [ScreenText]) throws -> ScreenText {
        let candidates = lines.filter { $0.box.minX > 0.24 && $0.box.maxY < 0.12 && isTarget($0.text) }
        guard candidates.count == 1 else { throw CourierError("未能唯一核验文件传输助手标题，已停止") }
        return candidates[0]
    }
    public static func sidebar(_ lines: [ScreenText]) throws -> ScreenText {
        let candidates = lines.filter { $0.box.minX > 0.05 && $0.box.maxX < 0.30 && $0.box.minY > 0.10 && isTarget($0.text) }
        guard candidates.count == 1 else { throw CourierError("请将文件传输助手会话放在左侧列表可见位置；不使用模糊匹配") }
        return candidates[0]
    }
    public static func normalized(_ text: String) -> String { text.filter { !$0.isWhitespace } }
    public static func contains(_ text: String, in lines: [ScreenText], region: CGRect) -> Bool {
        let expected = normalized(text)
        guard !expected.isEmpty else { return false }
        let joined = lines.filter { region.contains(CGPoint(x: $0.box.midX, y: $0.box.midY)) }
            .sorted { $0.box.midY < $1.box.midY }.map { normalized($0.text) }.joined()
        return joined.contains(expected)
    }
}

public struct SendRequest: Codable, Sendable {
    public var item: TaskItem
    public var attachment: URL?
    public var journalURL: URL
    public init(item: TaskItem, attachment: URL? = nil, journalURL: URL) {
        self.item = item; self.attachment = attachment; self.journalURL = journalURL
    }
}
