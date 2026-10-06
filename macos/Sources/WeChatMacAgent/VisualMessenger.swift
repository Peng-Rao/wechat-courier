import AppKit
import ApplicationServices
import ScreenCaptureKit
import Vision
import Darwin
import CourierCore

@MainActor
final class VisualMessenger {
    struct Snapshot { let window: SCWindow; let lines: [ScreenText]; let image: CGImage }
    private let chat = CGRect(x: 0.28, y: 0.12, width: 0.72, height: 0.665)
    private let editor = CGRect(x: 0.28, y: 0.79, width: 0.68, height: 0.14)

    func snapshot(verifyText: String? = nil, in verificationRegion: CGRect? = nil) async throws -> Snapshot {
        guard CGPreflightScreenCaptureAccess() else { throw CourierError("屏幕录制未授权，请在系统设置中开启 FugeWeChat 后重新启动") }
        guard AXIsProcessTrusted() else { throw CourierError("辅助功能未授权") }
        guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: AccessibilityInspector.bundleID).first,
              app.isActive else { throw CourierError("微信不在前台，已停止操作") }
        FileHandle.standardError.write(Data("stage: shareable windows\n".utf8))
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        let windows = content.windows.filter { $0.owningApplication?.processID == app.processIdentifier && $0.windowLayer == 0 && $0.frame.width > 650 && $0.frame.height > 450 }
        guard windows.count == 1 else { throw CourierError("微信主窗口不唯一或尺寸过小，请关闭其他微信窗口") }
        let window = windows[0]
        let config = SCStreamConfiguration()
        config.width = Int(window.frame.width * 2); config.height = Int(window.frame.height * 2)
        config.showsCursor = false
        FileHandle.standardError.write(Data("stage: capture\n".utf8))
        let image = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: window), configuration: config)
        let request = VNRecognizeTextRequest()
        // The initial verified profile is WeChat 4.1.13 with English UI.
        // Recognition failures stop the task instead of guessing coordinates.
        request.recognitionLevel = .fast; request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = false
        FileHandle.standardError.write(Data("stage: recognize\n".utf8))
        try VNImageRequestHandler(cgImage: image).perform([request])
        func lines(_ request: VNRecognizeTextRequest, confidence: Float) -> [ScreenText] {
            (request.results ?? []).compactMap { observation -> ScreenText? in
                guard let candidate = observation.topCandidates(1).first, candidate.confidence >= confidence else { return nil }
                let box = observation.boundingBox
                return ScreenText(candidate.string, box: CGRect(x: box.minX, y: 1 - box.maxY, width: box.width, height: box.height))
            }
        }
        var result = lines(request, confidence: 0.3)
        var regions = [CGRect(x: 0.24, y: 0, width: 0.76, height: 0.12)]
        if let verificationRegion { regions.append(verificationRegion) }
        // Only the identity strip and payload region need accurate recognition.
        // Process Chinese payloads locally within their region, avoiding the
        // expensive multilingual pass over the entire desktop window.
        for region in regions {
            let accurate = VNRecognizeTextRequest()
            accurate.recognitionLevel = .accurate; accurate.usesLanguageCorrection = false
            accurate.recognitionLanguages = verifyText?.unicodeScalars.contains(where: { $0.value > 127 }) == true ? ["en-US", "zh-Hans"] : ["en-US"]
            let pixels = CGRect(x: region.minX * Double(image.width), y: region.minY * Double(image.height),
                                width: region.width * Double(image.width), height: region.height * Double(image.height)).integral
            guard let crop = image.cropping(to: pixels) else { throw CourierError("无法截取核验区域") }
            try VNImageRequestHandler(cgImage: crop).perform([accurate])
            result.removeAll { region.contains(CGPoint(x: $0.box.midX, y: $0.box.midY)) }
            result += lines(accurate, confidence: 0.6).map { line in
                ScreenText(line.text, box: CGRect(x: region.minX + line.box.minX * region.width, y: region.minY + line.box.minY * region.height,
                                                 width: line.box.width * region.width, height: line.box.height * region.height))
            }
        }
        return Snapshot(window: window, lines: result, image: image)
    }

    func prepare() async throws -> Snapshot {
        let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: AccessibilityInspector.bundleID)
        let version = url.flatMap(Bundle.init(url:))?.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        guard version == "4.1.13" else { throw CourierError("当前视觉布局适配仅支持微信 4.1.13，其他版本需重新验收") }
        guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: AccessibilityInspector.bundleID).first else { throw CourierError("请打开微信并登录") }
        app.activate(options: [])
        try await Task.sleep(for: .milliseconds(400))
        var shot = try await snapshot()
        let identities = shot.lines.filter { FileTransferGuard.isTarget($0.text) }.map { "\($0.box)" }.joined(separator: ",")
        FileHandle.standardError.write(Data("stage: target bounds \(identities)\n".utf8))
        if (try? FileTransferGuard.header(shot.lines)) == nil {
            let row = try FileTransferGuard.sidebar(shot.lines)
            try click(row.box, in: shot)
            try await Task.sleep(for: .milliseconds(600))
            shot = try await snapshot()
        }
        _ = try FileTransferGuard.header(shot.lines)
        return shot
    }

    func send(_ request: SendRequest) async throws -> RunRecord {
        guard FileTransferGuard.isTarget(request.item.target) else { throw CourierError("当前适配仅开放文件传输助手") }
        let lockPath = request.journalURL.path + ".lock"
        let lock = open(lockPath, O_WRONLY | O_CREAT | O_EXLOCK | O_NONBLOCK | O_NOFOLLOW, 0o600)
        guard lock >= 0 else { throw CourierError("已有微信发送进程正在使用日志，或日志目录不可写") }
        defer { close(lock) }
        var records = try Journal.load(from: request.journalURL)
        guard let index = records.firstIndex(where: { $0.id == request.item.id }), records[index].kind == .message,
              records[index].target == request.item.target, records[index].outcome == .working,
              !records[index].crossedBoundary else { throw CourierError("任务已执行或日志状态不允许发送") }
        let pasteboard = NSPasteboard.general
        let original = (pasteboard.pasteboardItems ?? []).map { item in item.types.compactMap { type in item.data(forType: type).map { (type, $0) } } }
        var ownedChange: Int?
        defer {
            if ownedChange == pasteboard.changeCount {
                pasteboard.clearContents()
                let items = original.map { entries in let item = NSPasteboardItem(); entries.forEach { item.setData($0.1, forType: $0.0) }; return item }
                pasteboard.writeObjects(items)
            }
        }
        do {
            let label = request.attachment?.lastPathComponent ?? request.item.message
            guard !label.isEmpty, label.count <= 240 else { throw CourierError("当前视觉核验支持 1–240 字符的文字或文件名") }
            let initial = try await prepare()
            guard !FileTransferGuard.contains(label, in: initial.lines, region: chat) else { throw CourierError("会话中已存在相同内容，为避免重复发送已停止") }
            let draftLines = initial.lines.filter { editor.contains(CGPoint(x: $0.box.midX, y: $0.box.midY)) }
            guard draftLines.isEmpty, try editorIsBlank(initial.image) else { throw CourierError("输入区已有内容或处于语音模式，请手动清空并切换文字输入后重试") }
            // The 4.1.13 layout is checked by title and Send button before clicking.
            guard initial.lines.contains(where: { ["Send", "发送"].contains($0.text) && $0.box.minX > 0.85 && $0.box.minY > 0.92 }) else {
                throw CourierError("未识别到微信文字输入区和发送按钮，已停止")
            }
            try click(CGRect(x: 0.55, y: 0.84, width: 0.01, height: 0.01), in: initial)
            pasteboard.clearContents()
            if let file = request.attachment {
                guard file.isFileURL, FileManager.default.isReadableFile(atPath: file.path) else { throw CourierError("附件不可读") }
                guard pasteboard.writeObjects([file as NSURL]) else { throw CourierError("附件未能写入剪贴板") }
                ownedChange = pasteboard.changeCount
                // Some clients send pasted files immediately. Treat paste as the boundary.
                try await verifySameWindow(initial)
                try Journal.markBoundary(itemID: request.item.id, at: request.journalURL)
                try key(9, flags: .maskCommand)
                try await Task.sleep(for: .milliseconds(800))
                let dialog = try await snapshot()
                if FileTransferGuard.contains(label, in: dialog.lines, region: CGRect(x: 0.25, y: 0.18, width: 0.65, height: 0.65)) {
                    let buttons = dialog.lines.filter { ["Send", "发送"].contains($0.text) && $0.box.midX < 0.9 && $0.box.midY > 0.25 && $0.box.midY < 0.9 }
                    guard buttons.count == 1 else { throw CourierError("附件确认按钮不唯一，结果待人工核验") }
                    _ = try FileTransferGuard.header(dialog.lines)
                    try click(buttons[0].box, in: dialog)
                }
            } else {
                guard pasteboard.setString(request.item.message, forType: .string) else { throw CourierError("文字未能写入剪贴板") }
                ownedChange = pasteboard.changeCount
                try key(9, flags: .maskCommand)
                try await Task.sleep(for: .milliseconds(350))
                let draft = try await snapshot(verifyText: label, in: editor)
                _ = try FileTransferGuard.header(draft.lines)
                guard FileTransferGuard.contains(label, in: draft.lines, region: editor) else { throw CourierError("输入内容与冻结消息不符，未发送") }
                guard draft.window.windowID == initial.window.windowID, draft.window.frame == initial.window.frame else { throw CourierError("窗口已改变，未发送") }
                let sendButtons = draft.lines.filter { ["Send", "发送"].contains($0.text) && $0.box.minX > 0.85 && $0.box.minY > 0.92 }
                guard sendButtons.count == 1 else { throw CourierError("发送按钮不唯一，未发送") }
                try Journal.markBoundary(itemID: request.item.id, at: request.journalURL)
                try click(sendButtons[0].box, in: draft)
            }
            var verified = false
            for _ in 0..<8 {
                try await Task.sleep(for: .milliseconds(600))
                let result = try await snapshot(verifyText: label, in: chat)
                _ = try FileTransferGuard.header(result.lines)
                guard result.window.windowID == initial.window.windowID, result.window.frame == initial.window.frame else { throw CourierError("窗口改变，结果待核验") }
                if FileTransferGuard.contains(label, in: result.lines, region: chat),
                   !FileTransferGuard.contains(label, in: result.lines, region: editor) { verified = true; break }
            }
            guard verified else { throw CourierError("未在会话中核验到新内容；不会自动重发") }
            records = try Journal.load(from: request.journalURL)
            guard records.indices.contains(index), records[index].id == request.item.id else { throw CourierError("发送日志已被其他任务替换，请人工核验") }
            records[index].outcome = .success; records[index].detail = "已在文件传输助手窗口核验新内容；不代表服务端送达回执"
        } catch {
            records = try Journal.load(from: request.journalURL)
            guard records.indices.contains(index), records[index].id == request.item.id else { throw CourierError("发送日志已被其他任务替换，请人工核验") }
            records[index].outcome = records[index].crossedBoundary ? .unknown : .failed
            records[index].detail = error.localizedDescription
        }
        records[index].date = Date()
        try Journal.save(records, to: request.journalURL)
        return records[index]
    }

    private func verifySameWindow(_ previous: Snapshot) async throws {
        let current = try await snapshot()
        _ = try FileTransferGuard.header(current.lines)
        guard current.window.windowID == previous.window.windowID, current.window.frame == previous.window.frame else { throw CourierError("微信窗口已移动或切换，已停止") }
    }
    private func click(_ box: CGRect, in shot: Snapshot) throws {
        guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == AccessibilityInspector.bundleID else { throw CourierError("微信失去前台焦点，已停止") }
        let frame = shot.window.frame
        let point = CGPoint(x: frame.minX + box.midX * frame.width, y: frame.minY + box.midY * frame.height)
        for type in [CGEventType.leftMouseDown, .leftMouseUp] {
            guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left) else { throw CourierError("无法生成鼠标事件") }
            event.post(tap: .cghidEventTap)
        }
    }
    private func key(_ code: CGKeyCode, flags: CGEventFlags) throws {
        guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == AccessibilityInspector.bundleID else { throw CourierError("微信失去前台焦点，已停止") }
        for down in [true, false] {
            guard let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down) else { throw CourierError("无法生成键盘事件") }
            event.flags = flags; event.post(tap: .cghidEventTap)
        }
    }

    private func editorIsBlank(_ image: CGImage) throws -> Bool {
        let region = CGRect(x: editor.minX + 0.01, y: editor.minY + 0.015, width: editor.width - 0.02, height: editor.height - 0.02)
        let pixels = CGRect(x: region.minX * Double(image.width), y: region.minY * Double(image.height),
                            width: region.width * Double(image.width), height: region.height * Double(image.height)).integral
        guard let crop = image.cropping(to: pixels) else { throw CourierError("无法核验输入区是否为空") }
        let width = crop.width, height = crop.height
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        try bytes.withUnsafeMutableBytes { buffer in
            guard let context = CGContext(data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                          space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                throw CourierError("无法核验输入区像素")
            }
            context.draw(crop, in: CGRect(x: 0, y: 0, width: width, height: height))
        }
        // Flat input background must dominate. Any text/image pixels cause a
        // refusal, including languages the fast recognizer cannot understand.
        var colors: [Int: Int] = [:]
        for offset in stride(from: 0, to: bytes.count, by: 4) {
            let color = (Int(bytes[offset]) << 16) | (Int(bytes[offset + 1]) << 8) | Int(bytes[offset + 2])
            colors[color, default: 0] += 1
        }
        guard let background = colors.max(by: { $0.value < $1.value })?.key else { return false }
        let reference = [(background >> 16) & 255, (background >> 8) & 255, background & 255]
        for offset in stride(from: 0, to: bytes.count, by: 4) {
            if (0..<3).contains(where: { abs(Int(bytes[offset + $0]) - reference[$0]) > 12 }) { return false }
        }
        return true
    }
}
