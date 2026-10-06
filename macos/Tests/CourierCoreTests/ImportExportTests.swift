import XCTest
import CoreFoundation
@testable import CourierCore

final class ImportExportTests: XCTestCase {
    func testCSVHandlesBOMQuotesNewlinesAndEmptyCells() throws {
        let input = "\u{FEFF}姓名,账号,打招呼语\r\n\"示例,同学\",00123,\"你好\n\"\"欢迎\"\"\"\r\n第二位,wx_b,\r\n"
        let rows = try CSV.parse(input)
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows[1], ["示例,同学", "00123", "你好\n\"欢迎\""])
        XCTAssertEqual(rows[2][2], "")
        XCTAssertEqual(try CSV.parse(CSV.decode(CSV.encode(rows, protectFormulas: false))), rows)
    }
    func testRejectsMalformedCSVAndDuplicateHeadersWithoutPartialImport() {
        XCTAssertThrowsError(try CSV.parse("a,\"unclosed"))
        XCTAssertThrowsError(try CSV.parse("a,\"closed\"junk"))
        XCTAssertThrowsError(try ContactFiles.friendsFromRows([["姓名", "账号", "账号"], ["小明", "a", "b"]]))
        XCTAssertThrowsError(try ContactFiles.friendsFromRows([["备注", "账号"]]))
    }
    func testFriendImportPreservesSourceRowsAndSeparatesSuffix() throws {
        let records = try ContactFiles.friendsFromRows([["姓名", "账号", "打招呼语"], ["", "", ""], ["小明姐姐", " 00123 ", "你好{称呼}"]])
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].sourceRow, 3)
        XCTAssertEqual(records[0].name, "小明")
        XCTAssertEqual(records[0].suffix, "姐姐")
        XCTAssertEqual(records[0].account, "00123")
        XCTAssertFalse(records[0].selected)
    }
    func testContactAliasesAndFormulaProtection() throws {
        let contacts = try ContactFiles.fromRows([["nickname", "remark", "phone", "wechat_id", "alias", "description"], ["昵称", "=1+1", "001234", "wxid_a", "@alias", "原文"]])
        XCTAssertEqual(contacts[0].phone, "001234")
        let csv = try CSV.parse(CSV.decode(CSV.encode([ContactFiles.headers, contacts[0].fields])))
        XCTAssertEqual(csv[1][1], "'=1+1")
        XCTAssertEqual(csv[1][4], "'@alias")
        XCTAssertEqual(contacts[0].remark, "=1+1")
        XCTAssertEqual(CSV.formulaSafe(" \t=SUM(A1)"), "' \t=SUM(A1)")
    }
    func testExcelRoundTripPreservesTextAndFormulaAsLiteral() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("contacts.xlsx")
        let rows = [ContactFiles.headers, ["张三 & 小李", "=SUM(A1)", "00123", "wxid_<x>", "@user", "第一行\n第二行 \"引号\""]]
        try Spreadsheet.write(rows, to: url)
        XCTAssertEqual(try Spreadsheet.readRows(from: url), rows)
    }
    func testGB18030Decode() throws {
        let encoding = String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(CFStringEncoding(CFStringEncodings.GB_18030_2000.rawValue)))
        let input = "姓名,账号\n张三,00123"
        XCTAssertEqual(try CSV.decode(XCTUnwrap(input.data(using: encoding))), input)
    }
    func testWindowsJSONCompatibilityAndStableIndependentRowIdentities() throws {
        let input = Data("""
        [{"nick_name":"同名好友","remark":"=备注","phone":"00123","username":"wxid_a","alias":"abc","description":"原文","category":"friend"},{"nickname":"同名好友","wechatID":"group@chatroom"}]
        """.utf8)
        let contacts = try JSONDecoder().decode([Contact].self, from: input)
        XCTAssertEqual(contacts[0].phone, "00123")
        XCTAssertEqual(contacts[1].category, "group")
        XCTAssertNotEqual(contacts[0].id, contacts[1].id)
        let output = try JSONSerialization.jsonObject(with: JSONEncoder().encode(contacts)) as! [[String: Any]]
        XCTAssertEqual(output[0]["nick_name"] as? String, "同名好友")
        XCTAssertEqual(output[0]["remark"] as? String, "=备注")
        XCTAssertThrowsError(try JSONDecoder().decode([Contact].self, from: Data("[{\"unexpected\":\"x\"}]".utf8)))
    }
}
