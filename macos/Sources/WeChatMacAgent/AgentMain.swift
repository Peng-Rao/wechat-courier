import Foundation
import CourierCore

@main
enum AgentMain {
    static func main() {
        do {
            guard CommandLine.arguments.dropFirst().first == "--inspect" else {
                throw CourierError("此版本 Agent 仅提供只读环境检测；微信自动化尚未放行")
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
