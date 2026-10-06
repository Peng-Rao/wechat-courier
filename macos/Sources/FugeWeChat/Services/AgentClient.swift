import Foundation
import CourierCore

enum AgentClient {
    static func inspect() async throws -> EnvironmentReport {
        let executable = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/WeChatMacAgent")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw CourierError("找不到环境检测进程，请使用项目的构建运行脚本启动")
        }
        return try await Task.detached {
            let process = Process(); process.executableURL = executable; process.arguments = ["--inspect"]
            let output = Pipe(); let errors = Pipe()
            process.standardOutput = output; process.standardError = errors
            try process.run()
            // AX calls have individual timeouts; also bound the entire helper process.
            let deadline = Date().addingTimeInterval(10)
            while process.isRunning && Date() < deadline { try await Task.sleep(for: .milliseconds(50)) }
            if process.isRunning {
                process.terminate()
                throw CourierError("微信环境检测超过 10 秒，已停止检测进程")
            }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            guard process.terminationStatus == 0 else {
                throw CourierError(String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self))
            }
            return try JSONDecoder().decode(EnvironmentReport.self, from: data)
        }.value
    }
}
