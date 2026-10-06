import XCTest
import CourierCore
@testable import FugeWeChat

final class CourierStoreTests: XCTestCase {
    @MainActor
    func testInvalidRangePreservesSelectionAndLowerLimitKeepsFirstRows() throws {
        let url = temporaryJournal()
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CourierStore(journalURL: url)
        store.friends = (1...4).map { FriendRecord(sourceRow: $0 + 1, name: "name\($0)", account: "account\($0)") }
        try store.selectRange(from: 1, through: 3, limit: 3)
        let ids = store.selectedFriends.map(\.id)
        XCTAssertThrowsError(try store.selectRange(from: 0, through: 4, limit: 3))
        XCTAssertThrowsError(try store.selectRange(from: 1, through: 4, limit: 3))
        XCTAssertEqual(store.selectedFriends.map(\.id), ids)
        store.enforceLimit(2)
        XCTAssertEqual(store.selectedFriends.map(\.id), Array(ids.prefix(2)))
        store.enforceLimit(4)
        XCTAssertEqual(store.selectedFriends.count, 2)
    }

    @MainActor
    func testRehearsalPauseStopsClockAndStopDoesNotCompleteRemainingItems() async throws {
        let url = temporaryJournal()
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CourierStore(journalURL: url)
        let items = [TaskItem(target: "测试甲", message: "你好"), TaskItem(target: "测试乙", message: "你好")]
        store.rehearse(kind: .message, items: items, interval: 1)
        try await Task.sleep(for: .milliseconds(150))
        store.paused = true
        let before = store.elapsed
        try await Task.sleep(for: .milliseconds(350))
        XCTAssertEqual(store.elapsed, before, accuracy: 0.01)
        XCTAssertEqual(store.completed, 0)
        store.stop()
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertFalse(store.running)
        XCTAssertFalse(store.paused)
        XCTAssertEqual(store.records.map(\.outcome), [.stopped, .pending])
        XCTAssertTrue(store.records.allSatisfy { !$0.crossedBoundary })
    }

    @MainActor
    func testRehearsalNeverReportsRealSuccessAndUsesFrozenTargets() async throws {
        let url = temporaryJournal()
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let store = CourierStore(journalURL: url)
        store.roster = "原始收件人"
        store.message = "您好{name}"
        store.rehearse(kind: .message, items: try store.messageItems(), interval: 0)
        store.roster = "后来修改的人"
        try await Task.sleep(for: .milliseconds(700))
        XCTAssertFalse(store.running)
        XCTAssertEqual(store.records.map(\.target), ["原始收件人"])
        XCTAssertEqual(store.records.map(\.outcome), [.prepared])
        XCTAssertFalse(store.records[0].crossedBoundary)
        XCTAssertEqual(try Journal.load(from: url).map(\.outcome), [.prepared])
    }

    private func temporaryJournal() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathComponent("runs.json")
    }
}
