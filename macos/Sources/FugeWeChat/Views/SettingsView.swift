import SwiftUI
import AppKit

struct SettingsView: View {
    @Environment(CourierStore.self) private var store
    @AppStorage("appearance") private var appearance = "system"
    @AppStorage("interval") private var interval = 1.0
    @AppStorage("friendLimit") private var friendLimit = 100
    @AppStorage("defaultSuffix") private var defaultSuffix = "妈妈"
    @AppStorage("defaultGreeting") private var defaultGreeting = "您好，我是{称呼}，请通过我的好友申请。"

    var body: some View {
        Form {
            Section("外观") {
                Picker("主题", selection: $appearance) {
                    Text("跟随系统").tag("system")
                    Text("浅色").tag("light")
                    Text("深色").tag("dark")
                }
            }
            Section("本地演练") {
                HStack {
                    Text("记录间隔")
                    Spacer()
                    Text("\(interval, specifier: "%.1f") 秒").foregroundStyle(.secondary)
                }
                Slider(value: $interval, in: 0...10, step: 0.5)
                Text("仅控制本地演练节奏；暂停期间不计时。").font(.caption).foregroundStyle(.secondary)
            }
            Section("好友申请") {
                Stepper("每批添加人数：\(friendLimit)", value: $friendLimit, in: 1...1000)
                TextField("默认后缀", text: $defaultSuffix)
                TextField("默认打招呼语", text: $defaultGreeting)
            }.disabled(store.running)
            Section("微信适配") {
                LabeledContent("当前客户端", value: store.environment.version.isEmpty ? "未检测" : store.environment.version)
                LabeledContent("辅助功能权限", value: store.environment.accessibility ? "已授权" : "未授权")
                Text(store.environment.detail).font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("打开辅助功能设置") {
                        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") { NSWorkspace.shared.open(url) }
                    }
                    Button("重新检测") { Task { await store.checkEnvironment() } }.disabled(store.checking)
                }
                Text("由你在系统设置中决定是否授权本应用。当前基础版不会执行真实发送、好友提交或读取微信数据库。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.formStyle(.grouped).padding(12).frame(width: 530, height: 650)
            .onChange(of: friendLimit) { _, limit in store.enforceLimit(limit) }
    }
}
