import Foundation

public enum TaskKind: String, Codable, Sendable { case message, friend }
public enum Outcome: String, Codable, Sendable {
    case pending, working, success, prepared, failed, unknown, stopped
    public var title: String {
        switch self {
        case .pending: return "未执行"
        case .working: return "执行中"
        case .success: return "已核验"
        case .prepared: return "预检通过"
        case .failed: return "失败"
        case .unknown: return "结果未知"
        case .stopped: return "已停止"
        }
    }
}

public struct Recipient: Identifiable, Codable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public init(id: UUID = UUID(), name: String) { self.id = id; self.name = name }
}

public struct FriendRecord: Identifiable, Codable, Equatable, Sendable {
    public var id: UUID
    public var sourceRow: Int
    public var name: String
    public var account: String
    public var suffix: String?
    public var greeting: String
    public var selected: Bool
    public init(id: UUID = UUID(), sourceRow: Int, name: String, account: String,
                suffix: String? = nil, greeting: String = "", selected: Bool = false) {
        self.id = id; self.sourceRow = sourceRow; self.name = name; self.account = account
        self.suffix = suffix; self.greeting = greeting; self.selected = selected
    }
}

public struct Contact: Identifiable, Codable, Equatable, Sendable {
    public var id: UUID = UUID()
    public var nickname: String
    public var remark: String
    public var phone: String
    public var wechatID: String
    public var account: String
    public var detail: String
    public var category: String
    public init(nickname: String = "", remark: String = "", phone: String = "",
                wechatID: String = "", account: String = "", detail: String = "", category: String = "friend") {
        self.nickname = nickname; self.remark = remark; self.phone = phone
        self.wechatID = wechatID; self.account = account; self.detail = detail; self.category = category
    }
    public var fields: [String] { [nickname, remark, phone, wechatID, account, detail] }
    private enum Keys: String, CodingKey {
        case nick_name, nickname, remark, phone, username, wechatID, alias, account, description, detail, category
    }
    public init(from decoder: Decoder) throws {
        let data = try decoder.container(keyedBy: Keys.self)
        guard data.contains(.nick_name) || data.contains(.nickname) || data.contains(.username) || data.contains(.wechatID) || data.contains(.alias) || data.contains(.account) else {
            throw CourierError("JSON 联系人需包含昵称、微信 ID 或微信号字段")
        }
        nickname = try data.decodeIfPresent(String.self, forKey: .nick_name) ?? data.decodeIfPresent(String.self, forKey: .nickname) ?? ""
        remark = try data.decodeIfPresent(String.self, forKey: .remark) ?? ""
        phone = try data.decodeIfPresent(String.self, forKey: .phone) ?? ""
        wechatID = try data.decodeIfPresent(String.self, forKey: .username) ?? data.decodeIfPresent(String.self, forKey: .wechatID) ?? ""
        account = try data.decodeIfPresent(String.self, forKey: .alias) ?? data.decodeIfPresent(String.self, forKey: .account) ?? ""
        detail = try data.decodeIfPresent(String.self, forKey: .description) ?? data.decodeIfPresent(String.self, forKey: .detail) ?? ""
        category = try data.decodeIfPresent(String.self, forKey: .category) ?? Self.inferredCategory(wechatID)
    }
    public func encode(to encoder: Encoder) throws {
        var data = encoder.container(keyedBy: Keys.self)
        try data.encode(nickname, forKey: .nick_name); try data.encode(remark, forKey: .remark)
        try data.encode(phone, forKey: .phone); try data.encode(wechatID, forKey: .username)
        try data.encode(account, forKey: .alias); try data.encode(detail, forKey: .description)
        try data.encode(category, forKey: .category)
    }
    public static func inferredCategory(_ id: String) -> String {
        let id = id.lowercased()
        if id.hasSuffix("@chatroom") { return "group" }
        if id.hasPrefix("gh_") { return "official" }
        if id.hasSuffix("@stranger") { return "cache" }
        if ["filehelper", "weixin", "fmessage", "medianote", "newsapp", "notification_messages", "officialaccounts"].contains(id) { return "system" }
        return "friend"
    }
}

public struct TaskItem: Identifiable, Codable, Equatable, Sendable {
    public var id: UUID
    public var target: String
    public var message: String
    public var remark: String
    public var sourceRow: Int?
    public init(id: UUID = UUID(), target: String, message: String, remark: String = "", sourceRow: Int? = nil) {
        self.id = id; self.target = target; self.message = message; self.remark = remark; self.sourceRow = sourceRow
    }
}

public struct EnvironmentReport: Codable, Sendable {
    public var accessibility: Bool
    public var installed: Bool
    public var running: Bool
    public var version: String
    public var controlsAvailable: Bool
    public var detail: String
    public init(accessibility: Bool = false, installed: Bool = false, running: Bool = false,
                version: String = "", controlsAvailable: Bool = false, detail: String = "尚未检测") {
        self.accessibility = accessibility; self.installed = installed; self.running = running
        self.version = version; self.controlsAvailable = controlsAvailable; self.detail = detail
    }
}

public struct RunRecord: Identifiable, Codable, Sendable {
    public var id: UUID
    public var kind: TaskKind
    public var target: String
    public var outcome: Outcome
    public var detail: String
    public var crossedBoundary: Bool
    public var date: Date
    public init(id: UUID, kind: TaskKind, target: String, outcome: Outcome = .pending,
                detail: String = "等待执行", crossedBoundary: Bool = false, date: Date = Date()) {
        self.id = id; self.kind = kind; self.target = target; self.outcome = outcome
        self.detail = detail; self.crossedBoundary = crossedBoundary; self.date = date
    }
}

public struct CourierError: LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}
