import XCTest
@testable import CourierCore

final class JournalTests: XCTestCase {
    func testRecoveryNeverReplaysCrossedBoundary() {
        let records = [RunRecord(id: UUID(), kind: .message, target: "a", outcome: .working, crossedBoundary: true),
                       RunRecord(id: UUID(), kind: .friend, target: "b", outcome: .working),
                       RunRecord(id: UUID(), kind: .message, target: "c", outcome: .prepared)]
        let recovered = Journal.recover(records)
        XCTAssertEqual(recovered.map(\.outcome), [.unknown, .stopped, .prepared])
        XCTAssertTrue(recovered[0].crossedBoundary)
    }
    func testBoundaryIsDurableAndRejectsSecondSubmission() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let url = folder.appendingPathComponent("runs.json")
        defer { try? FileManager.default.removeItem(at: folder) }
        let id = UUID()
        try Journal.save([RunRecord(id: id, kind: .message, target: "a", outcome: .working)], to: url)
        try Journal.markBoundary(itemID: id, at: url)
        XCTAssertTrue(try Journal.load(from: url)[0].crossedBoundary)
        XCTAssertThrowsError(try Journal.markBoundary(itemID: id, at: url))
        XCTAssertThrowsError(try Journal.markBoundary(itemID: UUID(), at: url))
        XCTAssertEqual(try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? Int, 0o600)
    }
}
