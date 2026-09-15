# 五阿哥微信助手

面向 Windows 个人微信客户端的批量消息与批量添加好友助手。v0.3.3 候选版使用 PySide6/QML 提供桌面界面，并将所有微信 UI Automation 操作隔离到独立的 `wechat-agent.exe` 进程。

> 当前提交是稳定性修复检查点，不是已通过完整实机验收的正式版。40 次独立 GUI 任务、附件与合并转发、60 分钟混合运行及安装升级门禁尚未全部通过。单元测试和构建成功不代表软件实机稳定性已获确认。

> 当前自动化仅放行经过验证的微信 Windows 客户端 `4.1.13.65`。其他版本可以编辑任务，但不能启动自动化。

## 功能

- 消息群发：逐个精确匹配好友、回读聊天标题和输入内容、发送后核对新增消息。
- 附件发送：支持逐人附件；合并模式会先上传到文件传输助手，再执行真正的多选合并转发。
- 模板称呼：消息中的 `{name}` 会按好友备注生成称呼。
- 批量加好友：导入 XLSX 或 CSV，编辑账号、打招呼语和备注；点击开始后需在危险操作提示中再次确认，才会逐条提交好友申请。
- 中文状态机：执行页显示当前项目、步骤、结果、进度和本次任务运行日志。
- 安全恢复：Agent 卡死或崩溃不拖死 GUI；越过发送或提交边界的项目恢复后只标记为“结果未知”，绝不自动重放。
- 无边框窗口与毛玻璃：浅色/深色模式、玻璃开关和 `45%~90%` 透明度均可在运行中调整。

## 自动化边界

生产 GUI 不再通过 `SenderWorker(QThread)` 调用旧高层发送路径。架构如下：

```text
PySide6 GUI
  -> QProcess + QLocalSocket
  -> Windows Named Pipe / JSON-RPC 2.0
  -> wechat-agent.exe
  -> 专属 COM/UIA 线程
  -> 微信 4.1.13.65
```

- Agent 使用随机 Pipe 名和 256-bit token 完成首包认证，仅允许当前用户访问。
- 按钮优先使用 `InvokePattern`，列表优先使用 `SelectionItemPattern`，输入框优先使用 `ValuePattern` 或 `TextPattern`。
- Pattern 不可用时，才使用 UIA 控件边界中心、剪贴板和键盘；不依赖固定屏幕坐标，也不使用 Computer Use。
- UIA 等待由当前容器的结构、焦点和文本属性事件临时唤醒，并保留 250ms 截止轮询；离开步骤立即退订。
- 搜索目标必须规范化后完全相等且唯一。零条或多条结果都会阻止发送或进入好友表单。
- “发送”和好友申请“确定”都是单次破坏性动作。好友提交同时要求 GUI 明确确认、本次任务携带布尔提交意图、Agent 宣告并启用提交能力；任一条件缺失时只做预检并安全关闭表单。越过边界后若无法可靠确认则标记未知，绝不自动重试。
- 每次 UIA 动作前会用 250ms 响应探针检查微信窗口；无响应时立即停止整批，不再继续查询控件。
- 临时 UI 故障按 400ms、800ms 退避重试；陈旧代理只允许一次 1.6s 软会话刷新。Agent 进程恢复最多两次，间隔 2s、5s。

## 好友导入

XLSX 读取第一个工作表；CSV 支持 UTF-8 BOM 和 GB18030。表头要求：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `账号` | 是 | 微信号或手机号，不接受昵称；空值和重复值标记为异常 |
| `打招呼语` | 否 | 行内为空时使用全局默认；两者都空时保留微信原文 |
| `备注` | 否 | 行内为空时使用全局默认；两者都空时不填写 |

额外列会被忽略。导入后默认选择前 20 条有效记录，任何方式均不能一次选中超过 20 条。验证码、操作频繁、风险提示或账号限制会立即停止整批。正常模式在资料、打招呼语和备注回读一致后点击最终“确定”；提交后无法撤回。设置 `WECHAT_COURIER_ACCEPTANCE=1` 的验收模式和 `tools/safe_uia_preflight.py` 始终停在提交前并安全关闭表单。

## 开发

要求 Windows 10/11、Python 3.10+，以及已登录的微信 `4.1.13.65`。

```powershell
pip install -r requirements-dev.txt
python main.py
pytest -o addopts= -q
```

只读检查当前微信版本和 UIA 健康状态：

```powershell
python -c "from app.agent.native_driver import NativeWeixinDriver; print(NativeWeixinDriver().inspect())"
```

手工好友路径探针固定只填表、不提交；正式 GUI 仅在用户点击开始后再次确认，且匹配 Agent 明确声明提交能力时才允许最终提交：

```powershell
python tests/manual_wechat_uia_probe.py --wechat-id 18896904196 --greeting "你好" --remark "测试备注"
```

## 构建

```powershell
python build/build.py
```

构建输出：

```text
dist/五阿哥微信助手/五阿哥微信助手.exe
dist/五阿哥微信助手/wechat-agent.exe
dist/五阿哥微信助手_Setup.exe
```

安装器会关闭并迁移旧“五阿哥群发助手”，清理旧快捷方式，但保留 `QSettings("wx4py", "WeChatCourier")` 中的外观和任务参数。

## 兼容性

`src.WeChatClient` 的公共导入仍保留，便于旧调用方迁移；v0.3.1 的生产 GUI 不再依赖它执行任务。活动队列和结果不跨 GUI 重启恢复，短期安全日志只用于防止 Agent 重启后重复发送。UIA 诊断采用滚动 JSONL，并可从任务监控页导出脱敏诊断包。

## v0.3.2 Acceptance Harness

`tests/manual_v032_gui_acceptance.py` has four opt-in profiles: `smoke` (six alternating text/preflight tasks), `independent` (exactly 40 alternating tasks, 20 sends + 20 preflights), `soak` (60 minutes), and `delivery` (two text/file tasks, ordinary then merged-forward). Every invocation defaults to plan-only. Each report declares its coverage; no single profile claims the complete v0.3.2 release gate.

Dependencies: Windows 10/11, Python 3.10+, `requirements-dev.txt` (PySide6, pywin32, comtypes, pyperclip, pytest). UIA uses the repository's `src/core/uiautomation.py`; no additional UI automation package or Computer Use is required. Live tests require an interactive, unlocked desktop and logged-in supported WeChat. Close other Courier instances before starting. Do not interact with either application during a run.

Offline validation and a plan-only report (no application launch, desktop actions, or sends):

```powershell
python -m pytest tests/test_v032_acceptance.py -o addopts= -q
python tests/manual_v032_gui_acceptance.py --mode gui --report .artifacts/v032-plan.json
```

The following commands are **live and opt-in**. Run modes sequentially, never concurrently. Do not run until the operator explicitly authorizes sending unique test texts to `文件传输助手` and searching/filling/cancelling the friend form for `18896904196`. No other recipient or friend submission is accepted. Attachments/forwarding require the separate `delivery` profile and `--confirm-delivery`. A smoke run performs six separate one-item tasks: text then friend preflight, each from visible, minimized, and tray-hidden WeChat states. These states concern **WeChat**, not Courier; Courier remains visible for UIA button actions. Closing WeChat must be configured to hide to tray; unexpected exit aborts the run.

```powershell
# The harness sets these flags only in its packaged GUI child process:
# WECHAT_COURIER_ACCEPTANCE=1 and QT_ACCESSIBILITY=1
python tests/manual_v032_gui_acceptance.py --mode gui --profile smoke --gui-exe "dist/五阿哥微信助手/五阿哥微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-smoke.json

# Same cases, repeatedly as independent tasks for 60 minutes; default gap is 60s.
python tests/manual_v032_gui_acceptance.py --mode gui --profile soak --gui-exe "dist/五阿哥微信助手/五阿哥微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-soak.json

# Fixed task count, independent of soak duration: 20 sends + 20 friend preflights.
python tests/manual_v032_gui_acceptance.py --mode gui --profile independent --gui-exe "dist/五阿哥微信助手/五阿哥微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-independent.json

# Explicit delivery authorization; preselect File Transfer Assistant for the read-only baseline.
python tests/manual_v032_gui_acceptance.py --mode gui --profile delivery --gui-exe "dist/五阿哥微信助手/五阿哥微信助手.exe" --execute --confirm-send --confirm-delivery --report .artifacts/v032-gui-delivery.json

# Comparison entrypoints. Neither can substitute for packaged GUI acceptance.
python tests/manual_v032_gui_acceptance.py --mode source --profile smoke --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-source-smoke.json
python tests/manual_v032_gui_acceptance.py --mode rpc --agent-exe "dist/五阿哥微信助手/wechat-agent.exe" --profile smoke --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-rpc-smoke.json
```

For standalone inspection of the accessibility metadata, explicitly launch the packaged GUI with `$env:WECHAT_COURIER_ACCEPTANCE="1"` and `$env:QT_ACCESSIBILITY="1"`; remove those environment variables afterwards. This does not itself authorize task execution. Normal application runs must not expose raw editor/task metadata.

GUI mode uses only UIA to populate the actual editors, open settings, import its generated single-row CSV through the native Open dialog, and invoke Start. It never calls controllers, the Agent RPC, or the workflow engine. Invoke/Value patterns are preferred; unavailable patterns permit a fresh accessible-control-bounds fallback, with input readback. Invoke exceptions are never retried. The sole no-effect exception is non-destructive WeChat tray hiding: after Invoke returns but the window stays visible, the harness revalidates the same close control RuntimeId and main-window owner, then attempts one bounds click and verifies hidden state. Start/send never receive that retry. Message settings must match the canonical defaults (2/3 seconds), friend settings 15/30 seconds, unknown policy `continue`; mismatched pending GUI payloads abort before Start. Settings are inspected, not overwritten.

Delivery generates one fresh, uniquely named ASCII `.txt` per task, containing only a test marker and benign text. Arbitrary paths, changed content, additional files, and unrelated GUI attachments are rejected. GUI mode selects the file with the actual `messageAddFileButton` and native file dialog, verifies attachment readback, and sets `messageUseForwardSwitch` using TogglePattern (bounds fallback only when unavailable). The second task removes only the harness's previous attachment through `messageRemoveFileButton-0`. All sends, including the merged-forward source upload, remain restricted to File Transfer Assistant.

Delivery evidence combines exact single started/completed action pairs from bounded, already-redacted production diagnostics with read-only UIA observations of the selected File Transfer Assistant message list. Text and filename must be absent before the task and each appear exactly once afterwards; merged forwarding additionally requires exactly one new merged card. The source-upload and merged-forward boundaries are distinguished from ordinary text/attachment sends. Missing evidence, repeated actions, duplicate bubbles, or changed runtime build identity fail the profile. The operator must preselect this chat for the baseline; the audit itself does not navigate WeChat. Counts cover the exposed current message-list snapshot, not an unbounded historical/account-wide duplicate audit.

Acceptance-only `Accessible.name` contract:

- `App.qml`: `messageWorkspaceTab`, `friendWorkspaceTab`, `acceptanceEditorState`, `acceptanceTaskState`.
- `MessageWorkspace.qml`: `messageRecipientsInput`, `messageTemplateInput`, `startMessageButton`; delivery also uses `messageAddFileButton`, `messageUseForwardSwitch`, `messageRemoveFileButton-0`.
- `FriendWorkspace.qml`: `importFriendsButton`, `friendAccountField`, `startFriendsButton`.
- `WxTitleBar.qml`: `settingsButton`, exposed as an accessible button with a press action.
- `SettingsDialog.qml`: `settingsMessageIntervalMin`, `settingsMessageIntervalMax`, `settingsCloseButton`.
- `TaskMonitor.qml`: `taskReturnToEditorButton`, `taskStopButton`.

The two state nodes expose JSON through `Accessible.description` / UIA FullDescriptionProperty (30159), read using `GetPropertyValue(30159)`, gated by `task.acceptanceEnabled` (`WECHAT_COURIER_ACCEPTANCE=1`). Only an empty FullDescription falls back to legacy `HelpText`; malformed or oversized JSON fails without fallback, with the same strict JSON parsing and 32 KiB limit. Editor state binds `acceptanceMessageState` or `acceptanceFriendState` and includes `active`, hello-derived `friendSubmitEnabled` (must be boolean false), `kind`, pending `items`, and normalized `options`. Task state binds `acceptanceTaskState` and includes actual `taskId`, `kind`, `active`, `phase`, terminal `outcome`, counts (`done`, `total`, `success`, `error`, `unknown`, `stopped`), `echoedItems`, and bounded event proof (`taskId`, `itemId`, `step`, `outcome`). Success requires a fresh ID, matching item, and `send_verified` or `preflight_completed`; a success label alone is insufficient. Nodes must remain accessible across editor/monitor views. Native Open dialog selectors are filename Edit `AutomationId=1148` and Open Button `AutomationId=1`; missing/ambiguous controls fail closed.

Reports contain a run ID, unique texts, cases, observed window states, per-task evidence, explicit coverage exclusions, source/git fingerprint, and a SHA-256 manifest of the entire supplied package directory. Generated CSV inputs live in a unique run directory beside the report. Keep reports outside the package directory. Event details and unrecognized payload fields are omitted; Win32 window titles are hashed. On a startup/UIA failure, the supervisor records the last requested control and bounded Win32-only diagnostics (up to 24 windows, 100ms response probe each, 3s overall enumeration budget). Defaults: startup deadline 20s, whole-task deadline 120s, UIA tree budget 512 nodes. The 60-minute soak stops after the first unexplained failure; it never retries or replays a failed task. A hung worker is terminated after bounded cleanup, but Courier/Agent may remain running: inspect and stop an active task before any further run. The JSON is checkpointed after each task. Exit code 0 means plan generated or subset passed, 2 means failure; inspect `status` and `coverage`, not the exit code alone.

Success additionally requires actual terminal `cleanup.success=true`, `health.windowEnabled=true`, `health.windowResponsive=true`, `health.sessionReady=true`, and explicit `health.blockingWindow=null`. Counts alone cannot pass. The exact runtime `buildFingerprint` from source build metadata or Agent hello/GUI metadata is retained and must remain identical throughout the run. Missing startup identity prevents dispatch. Failed runs retain bounded phase breadcrumbs and safe traceback file/function/line locations, never source lines or general exception payloads. Known cursor-position-mismatch errors additionally retain only numeric expected/actual points.

The worker requests per-monitor-V2 process/thread DPI awareness before any adapter/Qt/UIA initialization, verifies effective thread awareness, and records `dpiEvidence`. Desktop initialization re-verifies awareness; each bounds click checks it again. The native cursor-position guard remains enabled. A process-awareness access-denied result can be recorded when awareness was already set, but effective thread awareness must still verify as per-monitor V2. No extra toolkit or QGuiApplication is created merely to establish DPI awareness.

## 许可

[MIT License](LICENSE)
