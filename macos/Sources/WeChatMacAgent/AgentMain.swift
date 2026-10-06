import Foundation
import AppKit
import ApplicationServices
import CourierCore

@main
enum AgentMain {
    @MainActor static func main() async {
        do {
            _ = NSApplication.shared
            NSApp.setActivationPolicy(.prohibited)
            if CommandLine.arguments.dropFirst().first == "--visual-check" {
                guard CGPreflightScreenCaptureAccess() else {
                    CGRequestScreenCaptureAccess()
                    throw CourierError("请开启屏幕录制权限后重新启动助手")
                }
                _ = try await VisualMessenger().prepare()
                FileHandle.standardOutput.write(Data("{\"ready\":true}\n".utf8)); return
            }
            if CommandLine.arguments.dropFirst().first == "--send-file-transfer" {
                FileHandle.standardError.write(Data("stage: request\n".utf8))
                let request = try JSONDecoder().decode(SendRequest.self, from: FileHandle.standardInput.readDataToEndOfFile())
                FileHandle.standardError.write(Data("stage: decoded\n".utf8))
                let record = try await VisualMessenger().send(request)
                FileHandle.standardOutput.write(try JSONEncoder().encode(record)); return
            }
            if CommandLine.arguments.dropFirst().first == "--diagnose" {
                let tree = try AccessibilityTree()
                let data = try JSONEncoder().encode(tree.diagnostic())
                FileHandle.standardOutput.write(data + Data([10])); return
            }
            guard CommandLine.arguments.dropFirst().first == "--inspect" else {
                throw CourierError("支持 --inspect、--diagnose、--visual-check 和 --send-file-transfer")
            }
            let report = AccessibilityInspector().inspect()
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(report)
            FileHandle.standardOutput.write(data + Data([10]))
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
            exit(1)
        }
    }
}
