import SwiftUI
import CourierCore

struct FriendWorkspace: View {
    @Environment(CourierStore.self) private var store
    @AppStorage("defaultSuffix") private var defaultSuffix = "妈妈"
    @AppStorage("defaultGreeting") private var defaultGreeting = "您好，我是{称呼}，请通过我的好友申请。"
    @AppStorage("friendLimit") private var friendLimit = 100
    @AppStorage("interval") private var interval = 1.0
    @State private var rangeFrom = "1"
    @State private var rangeThrough = ""
    @State private var selectedRow: UUID?
    @State private var confirmRehearsal = false

    var body: some View {
        @Bindable var store = store
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading(title: "有条理地准备好友申请", subtitle: "导入姓名与账号，生成备注和打招呼语。当前版本支持计划导出与本地演练。")
                HStack {
                    Button { Task { await store.importFriends() } } label: { Label("导入 CSV / Excel", systemImage: "square.and.arrow.down") }
                    Button { addFriend() } label: { Label("新增", systemImage: "plus") }
                    Button("下载模板…") { Task { await saveTemplate() } }
                    Spacer()
                    Text("已选 \(store.selectedFriends.count) / \(friendLimit)").font(.callout).foregroundStyle(.secondary)
                    TextField("搜索姓名或账号", text: $store.friendQuery).textFieldStyle(.roundedBorder).frame(width: 180)
                }.disabled(store.running || store.busy)
                if store.friends.isEmpty {
                    EmptyWorkspace(title: "准备第一份好友名单", detail: "表头需包含“姓名”和“账号”；“打招呼语”为可选列。导入不会自动勾选。", icon: "person.badge.plus")
                        .frame(height: 230)
                } else {
                    Table(store.filteredFriends, selection: $selectedRow) {
                        TableColumn("选择") { record in
                            Toggle("选择 \(record.name)", isOn: selectedBinding(record))
                                .labelsHidden().disabled(store.friendIssues[record.id] != nil || store.running)
                        }.width(40)
                        TableColumn("序号") { record in Text("\((store.friends.firstIndex { $0.id == record.id } ?? 0) + 1)").foregroundStyle(.secondary) }.width(40)
                        TableColumn("姓名", value: \.name).width(min: 70, ideal: 100)
                        TableColumn("账号", value: \.account).width(min: 100, ideal: 150)
                        TableColumn("后缀") { record in Text(record.suffix ?? "使用全局").foregroundStyle(.secondary) }.width(80)
                        TableColumn("备注预览") { record in
                            Text((try? Templates.friendItem(record, defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting).remark) ?? "—")
                        }.width(min: 100, ideal: 140)
                        TableColumn("状态") { record in
                            Text(store.friendIssues[record.id] ?? "待选").foregroundStyle(store.friendIssues[record.id] == nil ? Color.secondary : Color.red)
                        }.width(90)
                    }.frame(height: 230).contextMenu {
                        Button("删除所选行", role: .destructive) {
                            guard let selectedRow else { return }
                            store.friends.removeAll { $0.id == selectedRow }; self.selectedRow = nil
                        }.disabled(selectedRow == nil || store.running)
                    }
                    if let id = selectedRow, let index = store.friends.firstIndex(where: { $0.id == id }) {
                        FriendRowEditor(record: $store.friends[index], defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting)
                            .disabled(store.running)
                    }
                }
                HStack {
                    Text("选择区间").font(.caption)
                    TextField("起始", text: $rangeFrom).frame(width: 55)
                    Text("–").foregroundStyle(.secondary)
                    TextField("结束", text: $rangeThrough).frame(width: 55)
                    Button("选择") { selectRange() }
                    Button("清除选择") { for index in store.friends.indices { store.friends[index].selected = false } }
                    Spacer()
                    Text("异常 \(store.friendIssues.count) 条").font(.caption).foregroundStyle(.secondary)
                }.textFieldStyle(.roundedBorder).disabled(store.running || store.busy)
                Divider()
                HStack(alignment: .top, spacing: 18) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("全局后缀").font(.caption).foregroundStyle(.secondary)
                        TextField("如：妈妈；输入“无”不追加", text: $defaultSuffix).textFieldStyle(.roundedBorder).frame(width: 150)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        Text("全局打招呼语 · 支持 {姓名}、{后缀}、{称呼}").font(.caption).foregroundStyle(.secondary)
                        TextField("全局打招呼语", text: $defaultGreeting).textFieldStyle(.roundedBorder)
                    }
                }.disabled(store.running)
                HStack {
                    Button("导出申请计划…") {
                        Task { await store.exportFriendPlan(defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting, limit: friendLimit) }
                    }.disabled(store.selectedFriends.isEmpty || store.running || store.busy)
                    Spacer()
                    Button("提交好友申请") {}.disabled(true)
                    Button("本地演练…") {
                        do { _ = try store.friendItems(defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting, limit: friendLimit); confirmRehearsal = true }
                        catch { store.error = error.localizedDescription }
                    }.buttonStyle(.borderedProminent).disabled(store.running || store.busy)
                }
            }.padding(24)
        }
        .onChange(of: friendLimit) { _, value in store.enforceLimit(value) }
        .confirmationDialog("开始好友申请本地演练？", isPresented: $confirmRehearsal, titleVisibility: .visible) {
            Button("校验 \(store.selectedFriends.count) 条申请计划") {
                do { store.rehearse(kind: .friend, items: try store.friendItems(defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting, limit: friendLimit), interval: interval) }
                catch { store.error = error.localizedDescription }
            }
        } message: { Text("将检查选中的账号、备注和打招呼语，不搜索微信或提交好友申请。") }
    }

    private func selectedBinding(_ record: FriendRecord) -> Binding<Bool> {
        Binding(get: { store.friends.first(where: { $0.id == record.id })?.selected ?? false }, set: { value in
            guard let index = store.friends.firstIndex(where: { $0.id == record.id }) else { return }
            if value && store.selectedFriends.count >= friendLimit { store.error = "每批最多选择 \(friendLimit) 人"; return }
            store.friends[index].selected = value
        })
    }
    private func selectRange() {
        do {
            guard let from = Int(rangeFrom), let through = Int(rangeThrough) else { throw CourierError("区间请输入整数") }
            try store.selectRange(from: from, through: through, limit: friendLimit)
        } catch { store.error = error.localizedDescription }
    }
    private func addFriend() {
        let record = FriendRecord(sourceRow: (store.friends.map(\.sourceRow).max() ?? 1) + 1, name: "", account: "")
        store.friends.append(record); selectedRow = record.id
    }
    private func saveTemplate() async {
        do {
            _ = try await FileService.exportRows([["姓名", "账号", "打招呼语"], ["示例学生妈妈", "请替换为微信号或手机号", "您好，我是{称呼}。"]], name: "好友导入模板", format: "csv")
        } catch { store.error = error.localizedDescription }
    }
}

private struct FriendRowEditor: View {
    @Binding var record: FriendRecord
    let defaultSuffix: String
    let defaultGreeting: String
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text("编辑第 \(record.sourceRow) 源行").font(.caption.weight(.medium))
                TextField("姓名", text: $record.name).frame(width: 130)
                TextField("微信号或手机号", text: $record.account).frame(width: 180)
                Picker("后缀", selection: Binding(get: { record.suffix ?? "使用全局" }, set: { record.suffix = $0 == "使用全局" ? nil : $0 })) {
                    Text("使用全局").tag("使用全局")
                    Text("无").tag("无")
                    ForEach(Templates.suffixes, id: \.self) { Text($0).tag($0) }
                    if let suffix = record.suffix, suffix != "无", !Templates.suffixes.contains(suffix) { Text(suffix).tag(suffix) }
                }.frame(width: 140)
                TextField("自定义后缀", text: Binding(get: { record.suffix ?? "" }, set: { record.suffix = $0.isEmpty ? nil : $0 })).frame(width: 110)
            }
            TextField("行内打招呼语（空白时使用全局）", text: $record.greeting)
            Text((try? Templates.friendItem(record, defaultSuffix: defaultSuffix, defaultGreeting: defaultGreeting).message) ?? "请修正姓名、账号或模板")
                .font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }.textFieldStyle(.roundedBorder).padding(12).background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
    }
}
