import SwiftUI
import CourierCore

struct MessageWorkspace: View {
    @Environment(CourierStore.self) private var store
    @AppStorage("interval") private var interval = 1.0
    @State private var previewName = ""
    @State private var confirmRehearsal = false
    @State private var confirmSend = false
    @State private var confirmTest = false

    private var preview: String {
        let name = store.recipients.first(where: { $0.name == previewName })?.name ?? store.recipients.first?.name ?? "好友称呼"
        return (try? Templates.render(store.message, values: ["name": name])) ?? "模板存在未知占位符，请检查"
    }

    var body: some View {
        @Bindable var store = store
        VStack(alignment: .leading, spacing: 20) {
            SectionHeading(title: "每一条，都有专属称呼", subtitle: "编辑名单和消息，用 {name} 插入好友名字。支持本地预览与内容校验。")
            HSplitView {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("收件人").font(.headline)
                        Spacer()
                        Text("\(store.recipients.count) 人").foregroundStyle(.secondary)
                    }
                    Text("每行一个备注或昵称，自动去重").font(.caption).foregroundStyle(.secondary)
                    TextEditor(text: $store.roster).font(.body).padding(6)
                        .scrollContentBackground(.hidden).background(.quaternary.opacity(0.3))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .accessibilityLabel("收件人名单")
                    HStack {
                        Button("导入名单…") { importRoster() }
                        Spacer()
                        Button("清空") { store.roster = "" }.disabled(store.roster.isEmpty)
                    }
                }.frame(minWidth: 180, idealWidth: 220, maxWidth: 280).padding(.trailing, 14)
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text("消息内容").font(.headline)
                        Spacer()
                        Button("插入称呼") { store.message += "{name}" }
                    }
                    TextEditor(text: $store.message).font(.body).padding(8)
                        .scrollContentBackground(.hidden).background(.quaternary.opacity(0.3))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .accessibilityLabel("消息内容")
                    HStack {
                        Text("附件 \(store.attachments.count)").font(.headline)
                        Spacer()
                        Button { addAttachments() } label: { Label("添加附件", systemImage: "paperclip") }
                    }
                    if store.attachments.isEmpty {
                        Text("文件传输助手可发送附件；本地演练仅检查文件是否可读。")
                            .font(.caption).foregroundStyle(.secondary).padding(.vertical, 8)
                    } else {
                        ScrollView {
                            ForEach(store.attachments, id: \.path) { url in
                                HStack {
                                    Image(systemName: "doc").foregroundStyle(.secondary)
                                    Text(url.lastPathComponent).lineLimit(1)
                                    Spacer()
                                    Button { NSWorkspace.shared.open(url) } label: { Image(systemName: "eye") }.help("打开附件")
                                    Button { store.attachments.removeAll { $0 == url } } label: { Image(systemName: "xmark") }.help("移除附件")
                                }.padding(.vertical, 4)
                            }
                        }.frame(maxHeight: 110)
                    }
                }.frame(minWidth: 280).padding(.horizontal, 14)
                VStack(alignment: .leading, spacing: 12) {
                    Text("消息预览").font(.headline)
                    Picker("预览对象", selection: $previewName) {
                        Text("第一位收件人").tag("")
                        ForEach(store.recipients) { Text($0.name).tag($0.name) }
                    }.labelsHidden()
                    ScrollView {
                        VStack(alignment: .trailing, spacing: 12) {
                            if !store.message.isEmpty {
                                Text(preview).textSelection(.enabled).padding(14)
                                    .background(.green.opacity(0.13), in: RoundedRectangle(cornerRadius: 12))
                            }
                            ForEach(store.attachments, id: \.path) { url in
                                Label(url.lastPathComponent, systemImage: "doc.fill").font(.callout)
                                    .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                                    .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
                            }
                        }.frame(maxWidth: .infinity, alignment: .trailing)
                    }
                    Text("预览按输入名单生成，尚未与微信收件人核对。")
                        .font(.caption).foregroundStyle(.secondary)
                }.frame(minWidth: 220, idealWidth: 260, maxWidth: 330).padding(.leading, 14)
            }.disabled(store.running || store.busy)
            Divider()
            HStack {
                Label("实机适配仅开放文件传输助手", systemImage: "checkmark.shield").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("文件传输助手测试…") { confirmTest = true }.disabled(store.running || store.busy)
                Button("开始发送…") { confirmSend = true }
                    .disabled(store.running || store.busy || store.recipients.count != 1 || !FileTransferGuard.isTarget(store.recipients.first?.name ?? ""))
                Button("本地演练…") {
                    do { _ = try store.messageItems(); confirmRehearsal = true }
                    catch { store.error = error.localizedDescription }
                }.buttonStyle(.borderedProminent).disabled(store.running || store.busy)
                    .keyboardShortcut("r", modifiers: [.command, .shift])
            }
        }.padding(24)
        .confirmationDialog("开始本地演练？", isPresented: $confirmRehearsal, titleVisibility: .visible) {
            Button("校验 \(store.recipients.count) 位收件人的内容") {
                do { store.rehearse(kind: .message, items: try store.messageItems(), interval: interval) }
                catch { store.error = error.localizedDescription }
            }
        } message: { Text("冻结当前名单与消息，检查模板和附件。不会操作微信或发送任何内容。") }
        .confirmationDialog("向文件传输助手发送当前内容？", isPresented: $confirmSend, titleVisibility: .visible) {
            Button("发送文字和 \(store.attachments.count) 个附件") { store.sendFileTransfer() }
        } message: { Text("将操作前台微信。发送期间请不要切换、移动窗口或操作鼠标键盘；暂停在两条内容之间生效。核验失败会停止，不会自动重发。") }
        .confirmationDialog("测试文件传输助手？", isPresented: $confirmTest, titleVisibility: .visible) {
            Button("发送新建测试文字和测试文件") { store.testFileTransfer() }
        } message: { Text("只向文件传输助手发送带唯一编号的测试文字和临时文本文件。请先将该会话放在微信左侧可见位置，并清空输入框。") }
    }

    private func importRoster() {
        guard let url = FileService.open(extensions: ["txt", "csv"]) else { return }
        do {
            let text = try CSV.decode(Data(contentsOf: url))
            if url.pathExtension.lowercased() == "csv" {
                let rows = try CSV.parse(text)
                let headers = ["姓名", "昵称", "备注", "name"]
                let values = rows.first?.first.map { headers.contains($0) } == true ? Array(rows.dropFirst()) : rows
                store.roster = values.compactMap(\.first).joined(separator: "\n")
            } else { store.roster = text }
            store.notice = "已导入 \(store.recipients.count) 位收件人"
        } catch { store.error = error.localizedDescription }
    }
    private func addAttachments() {
        let urls = FileService.attachments()
        for url in urls where !store.attachments.contains(url) { store.attachments.append(url) }
    }
}
