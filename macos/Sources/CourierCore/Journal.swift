import Foundation

public enum Journal {
    public static func save(_ records: [RunRecord], to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(records).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    public static func load(from url: URL) throws -> [RunRecord] {
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        return try JSONDecoder().decode([RunRecord].self, from: Data(contentsOf: url))
    }
    public static func recover(_ records: [RunRecord]) -> [RunRecord] {
        records.map { original in
            var record = original
            if record.outcome == .working {
                record.outcome = record.crossedBoundary ? .unknown : .stopped
                record.detail = record.crossedBoundary ? "上次执行中断，已越过发送/提交边界；不会自动重放" : "上次执行中断，未越过发送/提交边界"
            }
            return record
        }
    }
    public static func markBoundary(itemID: UUID, at url: URL) throws {
        var records = try load(from: url)
        guard let index = records.firstIndex(where: { $0.id == itemID }), records[index].outcome == .working,
              !records[index].crossedBoundary else { throw CourierError("执行日志不允许重复发送或提交") }
        records[index].crossedBoundary = true
        records[index].detail = "即将执行单次发送/提交；中断后标记未知"
        try save(records, to: url)
    }
}
