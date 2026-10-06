import XCTest
@testable import CourierCore

final class TemplatesTests: XCTestCase {
    func testRosterTrimsAndDeduplicatesWithoutSubstringMatching() {
        XCTAssertEqual(Templates.recipients(" 张三 \n张三\n张三妈妈\r\n\n李四").map(\.name), ["张三", "张三妈妈", "李四"])
    }
    func testEscapedBracesAndUnknownTemplateFields() throws {
        XCTAssertEqual(try Templates.render("你好{name}，{{name}}", values: ["name": "张三"]), "你好张三，{name}")
        for template in ["{unknown}", "{name", "name}", "{name:2}", "{name!r}"] {
            XCTAssertThrowsError(try Templates.render(template, values: ["name": "张三"]))
        }
    }
    func testFriendTemplatePriorityAndNoSuffix() throws {
        let record = FriendRecord(sourceRow: 2, name: "小明", account: "wx_a", suffix: "无", greeting: "{姓名}/{后缀}/{称呼}/{关系}")
        let item = try Templates.friendItem(record, defaultSuffix: "妈妈", defaultGreeting: "全局")
        XCTAssertEqual(item.remark, "小明")
        XCTAssertEqual(item.message, "小明//小明/")
        let global = try Templates.friendItem(FriendRecord(sourceRow: 3, name: "小李", account: "wx_b"), defaultSuffix: "姐姐", defaultGreeting: "您好{称呼}")
        XCTAssertEqual(global.message, "您好小李姐姐")
    }
    func testDuplicateAndMissingFriendAccountsAreInvalid() {
        let records = [FriendRecord(sourceRow: 2, name: "a", account: "WX_A"), FriendRecord(sourceRow: 3, name: "b", account: "wx_a"), FriendRecord(sourceRow: 4, name: "", account: ""), FriendRecord(sourceRow: 5, name: "c", account: "wx_c")]
        let issues = Templates.validateFriends(records)
        XCTAssertEqual(issues.count, 3)
        XCTAssertNil(issues[records[3].id])
    }
}
