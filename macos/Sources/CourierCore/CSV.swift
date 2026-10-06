import Foundation
import CoreFoundation

public enum CSV {
    public static func parse(_ input: String) throws -> [[String]] {
        var text = input
        if text.first == "\u{FEFF}" { text.removeFirst() }
        var rows: [[String]] = [], row: [String] = [], field = ""
        var quoted = false, closedQuote = false
        var index = text.startIndex
        func finishField() { row.append(field); field = ""; closedQuote = false }
        func finishRow() { finishField(); rows.append(row); row = [] }
        while index < text.endIndex {
            let char = text[index]
            let next = text.index(after: index)
            if quoted {
                if char == "\"" {
                    if next < text.endIndex && text[next] == "\"" { field.append("\""); index = text.index(after: next); continue }
                    quoted = false; closedQuote = true
                } else { field.append(char) }
            } else if char == "\"" {
                guard field.isEmpty && !closedQuote else { throw CourierError("CSV 引号位置不正确") }
                quoted = true
            } else if char == "," { finishField() }
            else if char == "\r\n" || char == "\n" || char == "\r" { finishRow() }
            else {
                guard !closedQuote else { throw CourierError("CSV 引号后含有无效字符") }
                field.append(char)
            }
            index = next
        }
        guard !quoted else { throw CourierError("CSV 引号未闭合") }
        if !field.isEmpty || !row.isEmpty || closedQuote { finishRow() }
        return rows
    }

    public static func decode(_ data: Data) throws -> String {
        if let text = String(data: data, encoding: .utf8) { return text }
        let gb18030 = String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(CFStringEncoding(CFStringEncodings.GB_18030_2000.rawValue)))
        if let text = String(data: data, encoding: gb18030) { return text }
        throw CourierError("文件编码无效，请使用 UTF-8 或 GB18030")
    }

    public static func encode(_ rows: [[String]], protectFormulas: Bool = true) -> Data {
        let text = rows.map { row in
            row.map { value in
                let safe = protectFormulas ? formulaSafe(value) : value
                return "\"" + safe.replacingOccurrences(of: "\"", with: "\"\"") + "\""
            }.joined(separator: ",")
        }.joined(separator: "\r\n") + "\r\n"
        return Data(("\u{FEFF}" + text).utf8)
    }

    public static func formulaSafe(_ text: String) -> String {
        let first = text.trimmingCharacters(in: .whitespacesAndNewlines).first
        return first.map { "=+-@".contains($0) } == true || text.hasPrefix("\t") || text.hasPrefix("\r") ? "'" + text : text
    }
}

public enum ContactFiles {
    public static let headers = ["昵称", "备注", "手机号", "微信 ID", "微信号", "描述"]
    public static func fromRows(_ rows: [[String]]) throws -> [Contact] {
        guard let headers = rows.first else { throw CourierError("文件为空") }
        guard Set(headers).count == headers.count else { throw CourierError("表头重复") }
        let aliases = [["昵称", "nickname", "nick_name"], ["备注", "remark"], ["手机号", "phone"], ["微信 ID", "微信ID", "wechatID", "wechat_id", "username"], ["微信号", "account", "alias"], ["描述", "detail", "description"]]
        let indices = aliases.map { keys in headers.firstIndex { keys.contains($0) } }
        guard indices[0] != nil || indices[3] != nil || indices[4] != nil else { throw CourierError("需包含昵称、微信 ID 或微信号表头") }
        return rows.dropFirst().filter { $0.contains { !$0.isEmpty } }.map { row in
            let values = indices.map { index -> String in guard let index, index < row.count else { return "" }; return row[index] }
            let categoryIndex = headers.firstIndex(of: "category")
            let category = categoryIndex.flatMap { $0 < row.count ? row[$0] : nil } ?? Contact.inferredCategory(values[3])
            return Contact(nickname: values[0], remark: values[1], phone: values[2], wechatID: values[3], account: values[4], detail: values[5], category: category)
        }
    }
    public static func friendsFromRows(_ rows: [[String]]) throws -> [FriendRecord] {
        guard let headers = rows.first else { throw CourierError("文件为空") }
        guard Set(headers).count == headers.count else { throw CourierError("表头重复") }
        guard let nameIndex = headers.firstIndex(of: "姓名"), let accountIndex = headers.firstIndex(of: "账号") else {
            throw CourierError("好友文件必须包含“姓名”和“账号”表头")
        }
        let greetingIndex = headers.firstIndex(of: "打招呼语")
        return rows.dropFirst().enumerated().filter { $0.element.contains { !$0.isEmpty } }.map { offset, row in
            let value = nameIndex < row.count ? row[nameIndex] : ""
            let (name, suffix) = Templates.splitName(value)
            return FriendRecord(sourceRow: offset + 2, name: name, account: accountIndex < row.count ? row[accountIndex].trimmingCharacters(in: .whitespaces) : "",
                                suffix: suffix, greeting: greetingIndex.flatMap { $0 < row.count ? row[$0] : nil } ?? "")
        }
    }
}
