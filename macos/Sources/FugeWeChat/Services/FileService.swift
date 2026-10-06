import AppKit
import UniformTypeIdentifiers
import CourierCore

@MainActor
enum FileService {
    static func open(extensions: [String]) -> URL? {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = extensions.compactMap { UTType(filenameExtension: $0) }
        panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        return panel.runModal() == .OK ? panel.url : nil
    }
    static func attachments() -> [URL] {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        return panel.runModal() == .OK ? panel.urls : []
    }
    static func save(name: String, extension ext: String) -> URL? {
        let panel = NSSavePanel(); panel.nameFieldStringValue = name
        panel.allowedContentTypes = [UTType(filenameExtension: ext) ?? .data]
        panel.canCreateDirectories = true
        return panel.runModal() == .OK ? panel.url : nil
    }
    static func exportRows(_ rows: [[String]], name: String, format: String) async throws -> Bool {
        guard let url = save(name: name + "." + format, extension: format) else { return false }
        try await Task.detached {
            if format == "xlsx" { try Spreadsheet.write(rows, to: url) }
            else { try CSV.encode(rows).write(to: url, options: .atomic) }
        }.value
        return true
    }
}
