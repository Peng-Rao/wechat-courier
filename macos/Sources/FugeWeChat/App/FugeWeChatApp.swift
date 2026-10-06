import SwiftUI
import AppKit

@main
struct FugeWeChatApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var store = CourierStore()
    @AppStorage("appearance") private var appearance = "system"

    var body: some Scene {
        WindowGroup("福格微信助手 · macOS", id: "main") {
            ContentView()
                .environment(store)
                .preferredColorScheme(appearance == "dark" ? .dark : appearance == "light" ? .light : nil)
        }
        .defaultSize(width: 1180, height: 780)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("工作区") {
                ForEach(Array(Workspace.allCases.enumerated()), id: \.element) { index, workspace in
                    Button(workspace.title) { store.workspace = workspace }
                        .keyboardShortcut(KeyEquivalent(Character(String(index + 1))), modifiers: .command)
                }
            }
            CommandMenu("任务") {
                Button(store.paused ? "继续演练" : "暂停演练") { store.paused.toggle() }
                    .keyboardShortcut("p", modifiers: [.command, .shift]).disabled(!store.running)
                Button("停止演练") { store.stop() }
                    .keyboardShortcut(".", modifiers: .command).disabled(!store.running)
                Divider()
                Button("检测微信环境") { Task { await store.checkEnvironment() } }.disabled(store.checking)
            }
        }
        Settings { SettingsView().environment(store) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // No external operation is performed by the foundation release.
        .terminateNow
    }
}
