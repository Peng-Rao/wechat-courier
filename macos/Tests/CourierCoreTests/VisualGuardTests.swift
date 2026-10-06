import XCTest
import CoreGraphics
@testable import CourierCore

final class VisualGuardTests: XCTestCase {
    func testSidebarSearchAndMessageCannotImpersonateHeader() throws {
        let sidebar = ScreenText("File Transfer", box: CGRect(x: 0.10, y: 0.3, width: 0.09, height: 0.02))
        let search = ScreenText("File Transfer", box: CGRect(x: 0.10, y: 0.02, width: 0.09, height: 0.02))
        let bubble = ScreenText("File Transfer", box: CGRect(x: 0.50, y: 0.35, width: 0.09, height: 0.02))
        XCTAssertThrowsError(try FileTransferGuard.header([sidebar, search, bubble]))
        XCTAssertEqual(try FileTransferGuard.sidebar([sidebar, search, bubble]).text, "File Transfer")
        let header = ScreenText("文件传输助手", box: CGRect(x: 0.30, y: 0.03, width: 0.10, height: 0.02))
        XCTAssertEqual(try FileTransferGuard.header([sidebar, header]).text, "文件传输助手")
        XCTAssertThrowsError(try FileTransferGuard.header([header, header]))
        XCTAssertThrowsError(try FileTransferGuard.sidebar([sidebar, sidebar]))
        XCTAssertFalse(FileTransferGuard.isTarget("File Transfer (2)"))
        XCTAssertFalse(FileTransferGuard.isTarget("File Transfer Group"))
    }
    func testVerificationExcludesDraftAndHandlesWrappedLines() {
        let lines = [ScreenText("test ABC", box: CGRect(x: 0.6, y: 0.4, width: 0.2, height: 0.02)),
                     ScreenText("123", box: CGRect(x: 0.6, y: 0.43, width: 0.2, height: 0.02)),
                     ScreenText("draft", box: CGRect(x: 0.4, y: 0.85, width: 0.2, height: 0.02))]
        let region = CGRect(x: 0.28, y: 0.12, width: 0.72, height: 0.63)
        XCTAssertTrue(FileTransferGuard.contains("test ABC123", in: lines, region: region))
        XCTAssertFalse(FileTransferGuard.contains("draft", in: lines, region: region))
        XCTAssertFalse(FileTransferGuard.contains("", in: lines, region: region))
    }
}
