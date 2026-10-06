import Foundation

public enum Templates {
    public static let suffixes = ["爸爸", "妈妈", "哥哥", "姐姐", "弟弟", "妹妹", "爷爷", "奶奶", "外公", "外婆",
                                  "姥爷", "姥姥", "伯伯", "伯母", "叔叔", "婶婶", "姑姑", "姑父", "舅舅", "舅妈", "姨妈", "姨父", "阿姨"]

    public static func splitName(_ value: String) -> (String, String?) {
        let name = value.trimmingCharacters(in: .whitespacesAndNewlines)
        for suffix in suffixes.sorted(by: { $0.count > $1.count }) where name.hasSuffix(suffix) {
            return (String(name.dropLast(suffix.count)).trimmingCharacters(in: .whitespaces), suffix)
        }
        return (name, nil)
    }

    public static func render(_ template: String, values: [String: String]) throws -> String {
        var output = ""
        var index = template.startIndex
        while index < template.endIndex {
            let character = template[index]
            let next = template.index(after: index)
            if character == "{" {
                if next < template.endIndex && template[next] == "{" {
                    output.append("{"); index = template.index(after: next); continue
                }
                guard let end = template[next...].firstIndex(of: "}") else { throw CourierError("模板缺少右花括号") }
                let key = String(template[next..<end])
                guard let value = values[key] else { throw CourierError("未知占位符 {\(key)}") }
                output += value; index = template.index(after: end)
            } else if character == "}" {
                guard next < template.endIndex && template[next] == "}" else { throw CourierError("模板包含多余右花括号") }
                output.append("}"); index = template.index(after: next)
            } else { output.append(character); index = next }
        }
        return output
    }

    public static func friendItem(_ record: FriendRecord, defaultSuffix: String, defaultGreeting: String) throws -> TaskItem {
        guard !record.name.trimmingCharacters(in: .whitespaces).isEmpty else { throw CourierError("第 \(record.sourceRow) 行姓名为空") }
        guard !record.account.trimmingCharacters(in: .whitespaces).isEmpty else { throw CourierError("第 \(record.sourceRow) 行账号为空") }
        let raw = record.suffix ?? defaultSuffix
        let suffix = raw == "无" ? "" : raw
        let remark = record.name + suffix
        let template = record.greeting.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultGreeting : record.greeting
        let greeting = try render(template, values: ["姓名": record.name, "后缀": suffix, "关系": suffix, "称呼": remark])
        return TaskItem(id: record.id, target: record.account, message: greeting, remark: remark, sourceRow: record.sourceRow)
    }

    public static func recipients(_ input: String) -> [Recipient] {
        var seen = Set<String>()
        return input.components(separatedBy: .newlines).compactMap { value in
            let name = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, seen.insert(name).inserted else { return nil }
            return Recipient(name: name)
        }
    }

    public static func validateFriends(_ records: [FriendRecord]) -> [UUID: String] {
        let counts = Dictionary(grouping: records, by: { $0.account.trimmingCharacters(in: .whitespaces).lowercased() })
        var issues: [UUID: String] = [:]
        for record in records {
            if record.name.trimmingCharacters(in: .whitespaces).isEmpty { issues[record.id] = "姓名为空" }
            else if record.account.trimmingCharacters(in: .whitespaces).isEmpty { issues[record.id] = "账号为空" }
            else if (counts[record.account.trimmingCharacters(in: .whitespaces).lowercased()]?.count ?? 0) > 1 { issues[record.id] = "账号重复" }
        }
        return issues
    }
}
