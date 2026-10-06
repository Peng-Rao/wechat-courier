import Foundation
import CourierCore

enum AgentClient {
    static func visualCheck() async throws { _ = try await run(arguments: ["--visual-check"], timeout: 20) }
    static func send(_ request: SendRequest) async throws -> RunRecord {
        let data = try await run(arguments: ["--send-file-transfer"], input: JSONEncoder().encode(request), timeout: 45)
        return try JSONDecoder().decode(RunRecord.self, from: data)
    }
    private static func run(arguments: [String], input: Data? = nil, timeout: TimeInterval) async throws -> Data {
        let executable = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/WeChatMacAgent")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else { throw CourierError("找不到微信适配进程，请使用构建运行脚本") }
        let process = Process(); process.executableURL = executable; process.arguments = arguments
        let output = Pipe(), errors = Pipe(), stdin = Pipe()
        process.standardOutput = output; process.standardError = errors; process.standardInput = stdin
        try process.run()
        if let input { stdin.fileHandleForWriting.write(input) }
        try stdin.fileHandleForWriting.close()
        do {
            let deadline = Date().addingTimeInterval(timeout)
            while process.isRunning {
                try Task.checkCancellation()
                guard Date() < deadline else { throw CourierError("微信操作超时，已停止；请核验运行记录") }
                try await Task.sleep(for: .milliseconds(50))
            }
        } catch {
            if process.isRunning { process.terminate() }
            // Reap before reading the journal; an interrupted helper must never
            // race the app's recovery write.
            await Task.detached {
                let deadline = Date().addingTimeInterval(2)
                while process.isRunning && Date() < deadline { try? await Task.sleep(for: .milliseconds(50)) }
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                process.waitUntilExit()
            }.value
            if !Task.isCancelled {
                let diagnostic = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                throw CourierError(error.localizedDescription + "\n" + diagnostic.suffix(500))
            }
            throw error
        }
        guard process.terminationStatus == 0 else {
            throw CourierError(String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self))
        }
        return output.fileHandleForReading.readDataToEndOfFile()
    }
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
