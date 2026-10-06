import SwiftUI
import CourierCore

struct MonitorView: View {
    @Environment(CourierStore.self) private var store
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            SectionHeading(title: "运行记录", subtitle: "本地演练只校验任务内容，记录与真实发送结果明确区分。")
            HStack(spacing: 36) {
                metric("任务", value: store.runTitle)
                metric("进度", value: "\(store.completed) / \(store.total)")
                metric("累计耗时", value: elapsed)
                Spacer()
                if store.running {
                    Label(store.paused ? "等待暂停" : "执行中", systemImage: store.paused ? "pause.circle.fill" : "play.circle.fill")
                        .foregroundStyle(store.paused ? .orange : .green)
                }
            }.padding(20).background(.quaternary.opacity(0.2), in: RoundedRectangle(cornerRadius: 12))
            if store.total > 0 { ProgressView(value: Double(store.completed), total: Double(store.total)).tint(.orange) }
            if store.records.isEmpty {
                EmptyWorkspace(title: "还没有运行记录", detail: "在消息群发或好友申请工作区开始本地演练，检查名单和最终内容。", icon: "clock.arrow.circlepath")
            } else {
                Table(store.records) {
                    TableColumn("对象", value: \.target).width(min: 100, ideal: 160)
                    TableColumn("状态") { record in
                        Label(record.outcome.title, systemImage: icon(record.outcome)).foregroundStyle(color(record.outcome))
                    }.width(110)
                    TableColumn("时间") { record in Text(record.date.formatted(date: .omitted, time: .standard)).foregroundStyle(.secondary) }.width(90)
                    TableColumn("详情", value: \.detail).width(min: 260, ideal: 420)
                }
            }
            HStack {
                Button("导出运行记录…") { Task { await store.exportRecords() } }.disabled(store.records.isEmpty || store.running)
                Button("清空记录") { store.clearRecords() }.disabled(store.records.isEmpty || store.running)
                Spacer()
                if store.running {
                    Button(store.paused ? "继续" : "暂停") { store.paused.toggle() }
                    Button("停止", role: .destructive) { store.stop() }
                } else {
                    Button("返回编辑") { store.workspace = store.records.first?.kind == .friend ? .friends : .messages }
                }
            }
        }.padding(24)
    }
    private var elapsed: String {
        let seconds = Int(store.elapsed)
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
    private func metric(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).monospacedDigit()
        }
    }
    private func icon(_ outcome: Outcome) -> String {
        switch outcome {
        case .prepared, .success: return "checkmark.circle"
        case .failed: return "xmark.circle"
        case .unknown: return "questionmark.circle"
        case .working: return "ellipsis.circle"
        case .stopped: return "stop.circle"
        case .pending: return "circle.dotted"
        }
    }
    private func color(_ outcome: Outcome) -> Color {
        switch outcome {
        case .prepared, .success: return .green
        case .failed: return .red
        case .unknown: return .orange
        case .working: return .blue
        case .pending, .stopped: return .secondary
        }
    }
}
