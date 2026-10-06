import SwiftUI
import Observation
import CourierCore

enum Workspace: String, CaseIterable, Identifiable {
    case messages, friends, contacts, monitor
    var id: Self { self }
    var title: String {
        switch self {
        case .messages: return "消息群发"
        case .friends: return "好友申请"
        case .contacts: return "联系人"
        case .monitor: return "运行记录"
        }
    }
    var icon: String {
        switch self {
        case .messages: return "paperplane"
        case .friends: return "person.badge.plus"
        case .contacts: return "person.crop.rectangle.stack"
        case .monitor: return "clock.arrow.circlepath"
        }
    }
}

@MainActor @Observable
final class CourierStore {
    var workspace: Workspace? = .messages
    var roster = ""
    var message = ""
    var attachments: [URL] = []
    var friends: [FriendRecord] = []
    var contacts: [Contact] = []
    var contactQuery = ""
    var includeSpecial = false
    var friendQuery = ""
    var environment = EnvironmentReport()
    var checking = false
    var busy = false
    var error: String?
    var notice = ""
    var records: [RunRecord] = []
    var running = false
    var paused = false
    var elapsed: TimeInterval = 0
    var completed = 0
    var total = 0
    var runTitle = "尚无运行任务"
    @ObservationIgnored private var runTask: Task<Void, Never>?
    @ObservationIgnored private let journalURL: URL

    init(journalURL: URL? = nil) {
        self.journalURL = journalURL ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("FugeWeChatMac/runs.json")
        do {
            records = Journal.recover(try Journal.load(from: self.journalURL))
            if !records.isEmpty {
                total = records.count
                completed = records.filter { $0.outcome == .prepared || $0.outcome == .success }.count
                runTitle = "上次运行记录"
                try Journal.save(records, to: self.journalURL)
            }
        } catch { self.error = "无法读取上次运行日志：\(error.localizedDescription)" }
    }

    var recipients: [Recipient] { Templates.recipients(roster) }
    var friendIssues: [UUID: String] { Templates.validateFriends(friends) }
    var selectedFriends: [FriendRecord] { friends.filter(\.selected) }
    var filteredFriends: [FriendRecord] {
        let query = friendQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        return friends.filter { query.isEmpty || ($0.name + " " + $0.account).localizedCaseInsensitiveContains(query) }
    }
    var visibleContacts: [Contact] {
        contacts.filter { (includeSpecial || $0.category == "friend") &&
            (contactQuery.isEmpty || $0.fields.contains { $0.localizedCaseInsensitiveContains(contactQuery) }) }
    }
    var currentRecord: RunRecord? { records.last(where: { $0.outcome == .working }) }

    func checkEnvironment() async {
        guard !checking else { return }
        checking = true; defer { checking = false }
        do { environment = try await AgentClient.inspect() }
        catch { environment.detail = error.localizedDescription }
    }

    func messageItems() throws -> [TaskItem] {
        guard !recipients.isEmpty else { throw CourierError("请先输入收件人，每行一个名字") }
        guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !attachments.isEmpty else {
            throw CourierError("请输入消息或添加附件")
        }
        for url in attachments where !FileManager.default.isReadableFile(atPath: url.path) {
            throw CourierError("附件已移除或不可读：\(url.lastPathComponent)")
        }
        return try recipients.map { recipient in
            TaskItem(id: recipient.id, target: recipient.name, message: try Templates.render(message, values: ["name": recipient.name]))
        }
    }

    func friendItems(defaultSuffix: String, defaultGreeting: String, limit: Int) throws -> [TaskItem] {
        guard !selectedFriends.isEmpty else { throw CourierError("请先勾选好友记录") }
        guard selectedFriends.count <= limit else { throw CourierError("所选记录超过每批 \(limit) 人上限") }
        if let invalid = selectedFriends.first(where: { friendIssues[$0.id] != nil }) {
            throw CourierError("第 \(invalid.sourceRow) 行：\(friendIssues[invalid.id] ?? "记录无效")")
        }
        return try selectedFriends.map { try Templates.friendItem($0, defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting) }
    }

    func selectRange(from: Int, through: Int, limit: Int) throws {
        guard from >= 1, through >= from, through <= friends.count else { throw CourierError("选择区间无效，请按当前表格序号输入") }
        let ids = Set(friends[(from - 1)...(through - 1)].filter { friendIssues[$0.id] == nil }.map(\.id))
        guard !ids.isEmpty else { throw CourierError("区间内没有有效记录") }
        guard ids.count <= limit else { throw CourierError("区间超过每批 \(limit) 人上限") }
        for index in friends.indices { friends[index].selected = ids.contains(friends[index].id) }
    }

    func enforceLimit(_ limit: Int) {
        var count = 0
        for index in friends.indices where friends[index].selected {
            count += 1
            if count > limit { friends[index].selected = false }
        }
    }

    func importFriends() async {
        guard let url = FileService.open(extensions: ["csv", "xlsx"]) else { return }
        busy = true; defer { busy = false }
        do {
            let result = try await Task.detached { try ContactFiles.friendsFromRows(Spreadsheet.readRows(from: url)) }.value
            friends = result; notice = "已导入 \(result.count) 条记录，默认未勾选"
        } catch { self.error = error.localizedDescription }
    }

    func importContacts() async {
        guard let url = FileService.open(extensions: ["csv", "xlsx", "json"]) else { return }
        busy = true; defer { busy = false }
        do {
            let result = try await Task.detached {
                if url.pathExtension.lowercased() == "json" {
                    return try JSONDecoder().decode([Contact].self, from: Data(contentsOf: url))
                }
                return try ContactFiles.fromRows(Spreadsheet.readRows(from: url))
            }.value
            contacts = result; notice = "已导入 \(result.count) 位联系人"
        } catch { self.error = error.localizedDescription }
    }

    func exportContacts(format: String, snapshot: [Contact]) async {
        guard !snapshot.isEmpty else { return }
        busy = true; defer { busy = false }
        do {
            if format == "json" {
                guard let url = FileService.save(name: "微信联系人.json", extension: "json") else { return }
                try await Task.detached {
                    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                    try encoder.encode(snapshot).write(to: url, options: .atomic)
                }.value
                notice = "已导出 \(snapshot.count) 位联系人"
            } else if try await FileService.exportRows([ContactFiles.headers] + snapshot.map(\.fields), name: "微信联系人", format: format) {
                notice = "已导出 \(snapshot.count) 位联系人"
            }
        } catch { self.error = error.localizedDescription }
    }

    func exportFriendPlan(defaultSuffix: String, defaultGreeting: String, limit: Int) async {
        do {
            let items = try friendItems(defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting, limit: limit)
            let rows = [["原始行号", "账号", "备注", "打招呼语"]] + items.map { [String($0.sourceRow ?? 0), $0.target, $0.remark, $0.message] }
            if try await FileService.exportRows(rows, name: "好友申请计划", format: "csv") { notice = "已导出 \(items.count) 条申请计划" }
        } catch { self.error = error.localizedDescription }
    }

    func rehearse(kind: TaskKind, items: [TaskItem], interval: Double) {
        guard !running else { return }
        running = true; paused = false; elapsed = 0; completed = 0; total = items.count
        runTitle = kind == .message ? "消息群发 · 本地演练" : "好友申请 · 本地演练"
        records = items.map { RunRecord(id: $0.id, kind: kind, target: $0.target) }
        workspace = .monitor
        guard persist() else { running = false; return }
        runTask = Task { [weak self] in
            guard let self else { return }
            for index in self.records.indices {
                guard await self.waitActive(seconds: 0) else { break }
                self.records[index].outcome = .working
                self.records[index].detail = "检查冻结后的内容与收件人（本地，不操作微信）"
                guard self.persist() else { break }
                guard await self.waitActive(seconds: 0.25) else { break }
                self.records[index].outcome = .prepared
                self.records[index].detail = "本地校验通过；未发送消息、附件或好友申请"
                self.records[index].date = Date(); self.completed += 1
                guard self.persist() else { break }
                if index < self.records.count - 1, !(await self.waitActive(seconds: max(0, interval))) { break }
            }
            for index in self.records.indices where self.records[index].outcome == .working {
                self.records[index].outcome = .stopped; self.records[index].detail = "演练已停止，未操作微信"
            }
            self.running = false; self.paused = false; self.runTask = nil
            _ = self.persist()
        }
    }

    private func waitActive(seconds: TimeInterval) async -> Bool {
        var remaining = seconds
        repeat {
            if Task.isCancelled { return false }
            let wasPaused = paused
            let start = ContinuousClock.now
            do { try await Task.sleep(for: .milliseconds(100)) } catch { return false }
            if !wasPaused && !paused {
                let duration = start.duration(to: .now)
                let delta = Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
                elapsed += delta; remaining -= delta
            }
        } while paused || remaining > 0
        return !Task.isCancelled
    }
    func stop() { runTask?.cancel() }
    func clearRecords() {
        guard !running else { return }
        records = []; completed = 0; total = 0; elapsed = 0; runTitle = "尚无运行任务"; _ = persist()
    }
    private func persist() -> Bool {
        do { try Journal.save(records, to: journalURL); return true }
        catch { self.error = "日志保存失败，演练停止：\(error.localizedDescription)"; return false }
    }
    func exportRecords() async {
        do {
            let rows = [["时间", "对象", "状态", "详情"]] + records.map {
                [$0.date.formatted(date: .numeric, time: .standard), $0.target, $0.outcome.title, $0.detail]
            }
            if try await FileService.exportRows(rows, name: "本地演练记录", format: "csv") { notice = "运行记录已导出" }
        } catch { self.error = error.localizedDescription }
    }
}
