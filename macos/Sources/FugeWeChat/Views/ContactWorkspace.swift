import SwiftUI
import CourierCore

struct ContactWorkspace: View {
    @Environment(CourierStore.self) private var store
    @State private var selection = Set<UUID>()
    @State private var sortOrder = [KeyPathComparator(\Contact.nickname)]
    private var sorted: [Contact] { store.visibleContacts.sorted(using: sortOrder) }

    var body: some View {
        @Bindable var store = store
        VStack(alignment: .leading, spacing: 18) {
            SectionHeading(title: "让联系人数据更好用", subtitle: "导入已有联系人文件，在本机筛选、排序并导出。微信本地数据库读取仍在适配中。")
            HStack {
                Button { Task { await store.importContacts() } } label: { Label("导入联系人…", systemImage: "square.and.arrow.down") }
                Button("读取微信联系人") {}.disabled(true).help("Mac 微信数据库读取尚未实现")
                Spacer()
                Menu {
                    Button("CSV（UTF-8）") { let snapshot = sorted; Task { await store.exportContacts(format: "csv", snapshot: snapshot) } }
                    Button("JSON") { let snapshot = sorted; Task { await store.exportContacts(format: "json", snapshot: snapshot) } }
                    Button("Excel") { let snapshot = sorted; Task { await store.exportContacts(format: "xlsx", snapshot: snapshot) } }
                } label: { Label("导出筛选结果", systemImage: "square.and.arrow.up") }
                .disabled(store.visibleContacts.isEmpty || store.busy)
            }.disabled(store.busy)
            HStack {
                TextField("搜索昵称、备注、手机号或微信号", text: $store.contactQuery)
                    .textFieldStyle(.roundedBorder).frame(maxWidth: 400)
                Toggle("包含特殊账号", isOn: $store.includeSpecial)
                Spacer()
                Text("\(store.visibleContacts.count) / \(store.contacts.count) 位联系人").font(.callout).foregroundStyle(.secondary)
            }
            if store.contacts.isEmpty {
                EmptyWorkspace(title: "导入一份联系人文件", detail: "支持 CSV、JSON、Excel。手机号只显示导入文件中的已有字段，不从备注推测。", icon: "person.crop.rectangle.stack")
            } else if sorted.isEmpty {
                EmptyWorkspace(title: "没有匹配的联系人", detail: "调整关键词或开启“包含特殊账号”后重试。", icon: "magnifyingglass")
            } else {
                Table(sorted, selection: $selection, sortOrder: $sortOrder) {
                    TableColumn("昵称", value: \.nickname).width(min: 90, ideal: 120)
                    TableColumn("备注", value: \.remark).width(min: 90, ideal: 120)
                    TableColumn("手机号", value: \.phone).width(min: 100, ideal: 120)
                    TableColumn("微信 ID", value: \.wechatID).width(min: 100, ideal: 140)
                    TableColumn("微信号", value: \.account).width(min: 90, ideal: 130)
                    TableColumn("描述", value: \.detail).width(min: 100, ideal: 160)
                }.contextMenu {
                    Button("复制联系人") { copySelection() }.disabled(selection.isEmpty)
                    Button("加入群发名单") { useSelection() }.disabled(selection.isEmpty || store.running)
                }
            }
            Divider()
            HStack {
                Label("只导出当前筛选结果；号码和账号以文本保存", systemImage: "checkmark.shield")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("加入群发名单") { useSelection() }.disabled(selection.isEmpty || store.running)
                Button("清空联系人") { store.contacts = []; selection = [] }.disabled(store.contacts.isEmpty || store.busy)
            }
        }.padding(24)
    }
    private func copySelection() {
        let rows = sorted.filter { selection.contains($0.id) }.map { $0.fields.joined(separator: "\t") }
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(rows.joined(separator: "\n"), forType: .string)
        store.notice = "已复制 \(rows.count) 位联系人"
    }
    private func useSelection() {
        let names = sorted.filter { selection.contains($0.id) }.map { $0.remark.isEmpty ? $0.nickname : $0.remark }.filter { !$0.isEmpty }
        let existing = store.roster.trimmingCharacters(in: .whitespacesAndNewlines)
        store.roster = ([existing] + names).filter { !$0.isEmpty }.joined(separator: "\n")
        store.workspace = .messages; store.notice = "已加入 \(names.count) 位收件人，请核对备注或昵称"
    }
}
