import Foundation
#if canImport(FoundationXML)
import FoundationXML
#endif

/// Uses the system archive tools; no external package or Office installation is required.
public enum Spreadsheet {
    public static func readRows(from url: URL) throws -> [[String]] {
        if url.pathExtension.lowercased() == "csv" { return try CSV.parse(CSV.decode(Data(contentsOf: url))) }
        guard url.pathExtension.lowercased() == "xlsx" else { throw CourierError("请选择 CSV 或 XLSX 文件") }
        let workbookData = try archiveEntry("xl/workbook.xml", at: url)
        let workbook = WorkbookParser(); try parse(workbookData, delegate: workbook)
        guard let relationID = workbook.firstSheetID else { throw CourierError("Excel 没有工作表") }
        let relations = RelationParser(); try parse(archiveEntry("xl/_rels/workbook.xml.rels", at: url), delegate: relations)
        guard let target = relations.targets[relationID], !target.contains(".."), !target.contains(":") else {
            throw CourierError("Excel 工作表路径无效")
        }
        let path = target.hasPrefix("/") ? String(target.dropFirst()) : "xl/" + target
        let strings = SharedStringParser()
        // sharedStrings is optional for inline-string workbooks.
        let entries = try runArchive(["-Z1", url.path])
        if String(decoding: entries, as: UTF8.self).components(separatedBy: .newlines).contains("xl/sharedStrings.xml") {
            try parse(archiveEntry("xl/sharedStrings.xml", at: url), delegate: strings)
        }
        let sheet = SheetParser(sharedStrings: strings.values)
        try parse(archiveEntry(path, at: url), delegate: sheet)
        if let failure = sheet.failure { throw CourierError(failure) }
        return sheet.rows
    }

    public static func write(_ rows: [[String]], to destination: URL) throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        func put(_ text: String, _ path: String) throws {
            let url = folder.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(text.utf8).write(to: url)
        }
        try put("""
        <?xml version="1.0" encoding="UTF-8"?>
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>
        """, "[Content_Types].xml")
        try put("""
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>
        """, "_rels/.rels")
        try put("""
        <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="联系人" sheetId="1" r:id="rId1"/></sheets></workbook>
        """, "xl/workbook.xml")
        try put("""
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>
        """, "xl/_rels/workbook.xml.rels")
        let cells = rows.enumerated().map { rowIndex, row in
            let values = row.enumerated().map { columnIndex, value in
                "<c r=\"\(columnName(columnIndex))\(rowIndex + 1)\" t=\"inlineStr\"><is><t xml:space=\"preserve\">\(escape(value))</t></is></c>"
            }.joined()
            return "<row r=\"\(rowIndex + 1)\">\(values)</row>"
        }.joined()
        let lastColumn = columnName(max(0, (rows.first?.count ?? 1) - 1))
        try put("""
        <?xml version="1.0" encoding="UTF-8"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>\(cells)</sheetData><autoFilter ref="A1:\(lastColumn)\(max(1, rows.count))"/></worksheet>
        """, "xl/worksheets/sheet1.xml")
        let archive = folder.appendingPathComponent("result.xlsx")
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/zip")
        process.currentDirectoryURL = folder
        process.arguments = ["-q", "-r", archive.path, "[Content_Types].xml", "_rels", "xl"]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try process.run(); process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw CourierError("Excel 文件打包失败") }
        try Data(contentsOf: archive).write(to: destination, options: .atomic)
    }

    private static func archiveEntry(_ name: String, at url: URL) throws -> Data {
        try runArchive(["-p", url.path, name])
    }
    private static func runArchive(_ arguments: [String]) throws -> Data {
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip"); process.arguments = arguments
        let output = Pipe(); process.standardOutput = output; process.standardError = FileHandle.nullDevice
        try process.run()
        var data = Data()
        let deadline = Date().addingTimeInterval(10)
        // Bound decompression to avoid loading an untrusted archive without a limit.
        while true {
            let chunk = output.fileHandleForReading.readData(ofLength: 65_536)
            if chunk.isEmpty { break }
            data.append(chunk)
            if data.count > 32 * 1024 * 1024 || Date() > deadline {
                process.terminate(); output.fileHandleForReading.closeFile(); process.waitUntilExit()
                throw CourierError("Excel 读取超时或超过 32 MB 上限")
            }
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw CourierError("Excel 文件损坏或缺少工作表") }
        return data
    }
    private static func parse(_ data: Data, delegate: XMLParserDelegate) throws {
        let parser = XMLParser(data: data); parser.delegate = delegate
        parser.shouldResolveExternalEntities = false
        guard parser.parse() else { throw CourierError("Excel XML 无效：\(parser.parserError?.localizedDescription ?? "未知错误")") }
    }
    private static func columnName(_ index: Int) -> String {
        var number = index + 1, result = ""
        while number > 0 { number -= 1; result = String(UnicodeScalar(65 + number % 26)!) + result; number /= 26 }
        return result
    }
    private static func escape(_ text: String) -> String {
        String(text.unicodeScalars.filter { $0.value == 9 || $0.value == 10 || $0.value == 13 || $0.value >= 32 })
            .replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }
}

private final class WorkbookParser: NSObject, XMLParserDelegate {
    var firstSheetID: String?
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String]) {
        if elementName == "sheet" && firstSheetID == nil { firstSheetID = attributes["r:id"] }
    }
}
private final class RelationParser: NSObject, XMLParserDelegate {
    var targets: [String: String] = [:]
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String]) {
        if elementName == "Relationship", attributes["TargetMode"] != "External", let id = attributes["Id"], let target = attributes["Target"] { targets[id] = target }
    }
}
private final class SharedStringParser: NSObject, XMLParserDelegate {
    var values: [String] = [], current = "", inText = false
    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String]) {
        if name == "si" { current = "" }; if name == "t" { inText = true }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { if inText { current += string } }
    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName qName: String?) {
        if name == "t" { inText = false }; if name == "si" { values.append(current) }
    }
}
private final class SheetParser: NSObject, XMLParserDelegate {
    let sharedStrings: [String]
    var rows: [[String]] = [], row: [String] = [], column = 0, cellType = "", value = "", inValue = false
    var failure: String?
    var cellCount = 0
    init(sharedStrings: [String]) { self.sharedStrings = sharedStrings }
    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String]) {
        if name == "row" {
            row = []
            if let number = attributes["r"].flatMap(Int.init) {
                guard number <= 100_000 else { failure = "Excel 超过 100000 行上限"; parser.abortParsing(); return }
                while rows.count < number - 1 { rows.append([]) }
            }
        }
        if name == "c" {
            column = 0; value = ""; cellType = attributes["t"] ?? ""
            let reference = attributes["r"] ?? "A"
            for char in reference.uppercased() {
                guard let scalar = char.unicodeScalars.first, (65...90).contains(scalar.value) else { break }
                column = column * 26 + Int(scalar.value) - 64
                if column > 256 { failure = "Excel 超过 256 列读取上限"; parser.abortParsing(); return }
            }
            column = max(0, column - 1)
        }
        if name == "v" || name == "t" { inValue = true }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { if inValue { value += string } }
    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName qName: String?) {
        if name == "v" || name == "t" { inValue = false }
        if name == "c" {
            cellCount += max(0, column + 1 - row.count)
            guard cellCount <= 2_000_000 else { failure = "Excel 超过 200 万单元格读取上限"; parser.abortParsing(); return }
            while row.count <= column { row.append("") }
            if cellType == "s" {
                if let index = Int(value), sharedStrings.indices.contains(index) { row[column] = sharedStrings[index] }
                else { failure = "Excel 共享字符串索引无效" }
            } else { row[column] = value }
        }
        if name == "row" { rows.append(row) }
    }
}
