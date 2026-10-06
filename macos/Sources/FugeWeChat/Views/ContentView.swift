import SwiftUI

struct ContentView: View {
    @Environment(CourierStore.self) private var store

    var body: some View {
        @Bindable var store = store
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 10) {
                    if let url = Bundle.main.url(forResource: "fuge-logo", withExtension: "png"),
                       let image = NSImage(contentsOf: url) {
                        Image(nsImage: image).resizable().scaledToFit().frame(width: 32, height: 32)
                    } else { Image(systemName: "paperplane.fill").foregroundStyle(.orange).font(.title2) }
                    VStack(alignment: .leading, spacing: 3) {
                        Text("福格微信助手").font(.headline)
                        Text("macOS · 基础版 0.1").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.horizontal, 14).padding(.top, 18)
                List(Workspace.allCases, selection: $store.workspace) { workspace in
                    Label(workspace.title, systemImage: workspace.icon).tag(workspace)
                }.listStyle(.sidebar)
                VStack(alignment: .leading, spacing: 8) {
                    Label(store.running ? "本地演练进行中" : "自动化适配中", systemImage: store.running ? "play.circle" : "wrench.and.screwdriver")
                        .font(.caption).foregroundStyle(.secondary)
                    SettingsLink { Label("参数设置", systemImage: "gearshape") }
                        .buttonStyle(.plain)
                }.padding(16)
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 260)
        } detail: {
            VStack(spacing: 0) {
                EnvironmentBanner()
                Group {
                    switch store.workspace ?? .messages {
                    case .messages: MessageWorkspace()
                    case .friends: FriendWorkspace()
                    case .contacts: ContactWorkspace()
                    case .monitor: MonitorView()
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                Divider()
                HStack {
                    Text(store.notice.isEmpty ? "内容在本机处理 · 当前版本不执行真实发送或申请" : store.notice)
                        .lineLimit(1)
                    Spacer()
                    if store.busy { ProgressView().controlSize(.small) }
                    Text("macOS 14+")
                }.font(.caption).foregroundStyle(.secondary).padding(.horizontal, 20).padding(.vertical, 9)
            }
            .navigationTitle((store.workspace ?? .messages).title)
            .toolbar {
                ToolbarItem { Button { Task { await store.checkEnvironment() } } label: { Label("检测微信", systemImage: "arrow.clockwise") }.disabled(store.checking) }
                ToolbarItem { SettingsLink { Image(systemName: "gearshape") } }
            }
        }
        .frame(minWidth: 1000, minHeight: 650)
        .task { await store.checkEnvironment() }
        .alert("操作未完成", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
            Button("知道了", role: .cancel) { store.error = nil }
        } message: { Text(store.error ?? "") }
    }
}

private struct EnvironmentBanner: View {
    @Environment(CourierStore.self) private var store
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "info.circle").foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 3) {
                    Text("微信自动化尚未放行").font(.callout.weight(.medium))
                    Text(store.checking ? "正在检测微信环境…" : store.environment.detail)
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 12)
                if !store.environment.version.isEmpty { Text("微信 \(store.environment.version)").font(.caption).foregroundStyle(.secondary) }
            }
            .padding(.horizontal, 20).padding(.vertical, 12).background(.orange.opacity(0.06))
            Divider()
        }.fixedSize(horizontal: false, vertical: true)
    }
}

struct SectionHeading: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.title2.weight(.semibold))
            Text(subtitle).font(.callout).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct EmptyWorkspace: View {
    let title: String
    let detail: String
    let icon: String
    var body: some View {
        ContentUnavailableView(title, systemImage: icon, description: Text(detail))
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
