# 福格微信助手

面向 Windows 个人微信客户端的批量消息与批量添加好友助手。1.0.0 使用 PySide6/QML 提供桌面界面，并将所有微信 UI Automation 操作隔离到独立的 `wechat-agent.exe` 进程。

> 当前代码是 1.0.0 修复检查点，不是已通过完整实机验收的正式包。40 次独立 GUI 任务、普通附件、60 分钟混合运行及安装升级门禁尚未全部通过。单元测试和构建成功不代表软件实机稳定性已获确认。

> 当前自动化仅放行经过验证的微信 Windows 客户端 `4.1.13.65`。其他版本可以编辑任务，但不能启动自动化。

## 功能

- 消息群发：默认逐个精确匹配好友；可在“参数设置 → 消息群发”开启“模糊搜索（取首个结果）”，按微信结果顺序选第一个有效会话。两种模式均回读聊天标题和输入内容，并保持发送防重复规则。
- 附件发送：仅逐人发送普通附件；预览按顺序显示文字和所有附件，图片可在窗口内放大，其他文件通过系统关联程序打开。旧转发选项 `useForward` 会被 RPC 契约明确拒绝。
- 编辑与计时：名单、模板和消息预览独立滚动；两类任务均显示单调时钟累计耗时，暂停停表，包含重试、等待和清理，结束保留耗时。
- 模板称呼：消息中的 `{name}` 会按好友备注生成称呼。
- 自动发送好友申请：导入 XLSX 或 CSV，编辑姓名、账号、逐行后缀和打招呼语，自动生成备注；点击开始后需在危险操作提示中再次确认，才会逐条提交好友申请。
- 中文状态机：执行页显示当前项目、步骤、结果、进度和本次任务运行日志。
- 安全恢复：Agent 卡死或崩溃不拖死 GUI；越过发送或提交边界的项目恢复后只标记为“结果未知”，绝不自动重放。
- 无边框窗口与毛玻璃：浅色/深色模式、玻璃开关和 `45%~90%` 透明度均可在运行中调整。

已知限制：[图片发送结果核验待修复](docs/issues/image-delivery-verification.md)。目前图片发送触发成功且输入框清空后，界面显示成功；尚不代表送达已核验。普通文件、文本核验及防重复发送机制保持不变。

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
- 消息搜索默认要求规范化后完全相等且唯一；模糊开关默认关闭，开启后始终取微信返回的第一个有效会话，不优先选择后面的精确匹配。点击前重新核对结果，聊天标题仍必须与实际所选对象匹配；无结果不发送。`{name}` 和消息预览仍按输入名单生成，不自动替换为匹配对象的名字。
- 好友申请不支持模糊搜索，必须使用完整微信号或手机号并核对资料。消息模糊搜索设置不会改变好友查询或提交规则。
- “发送”和好友申请“确定”都是单次破坏性动作。好友提交同时要求 GUI 明确确认、本次任务携带布尔提交意图、Agent 宣告并启用提交能力；任一条件缺失时只做预检并安全关闭表单。越过边界后若无法可靠确认则标记未知，绝不自动重试。
- 每次 UIA 动作前会用 250ms 响应探针检查微信窗口；无响应时立即停止整批，不再继续查询控件。
- 临时 UI 故障按 400ms、800ms 退避重试；陈旧代理只允许一次 1.6s 软会话刷新。Agent 进程恢复最多两次，间隔 2s、5s。

## 异常退出后的恢复

助手启动时先连接独立 Agent，再处理上次异常退出遗留的 gate 租约；恢复期间可以编辑任务，但不能启动。原微信已退出或 PID 被复用时，遗留记录会安全归档，不会写入新进程的内存。跨 Windows 登录不得按旧记录修改当前屏幕阅读器状态；仍存活但身份无法确认的进程保持阻断。

原进程仍存在且原值可核实时自动回滚。租约损坏或记录冲突时，仅对唯一确认、版本受支持且属于当前登录的微信自动重启一次；需要登录确认时由用户完成，默认等待 90 秒，沿用设置中的登录超时。重启次数在关闭前持久化，重开助手不会对同一未完成故障再次重启。真实存活的其他 Agent、权限错误或无法确认的进程身份仍会阻断。

顶栏和恢复提示区显示具体阶段，提供“取消恢复”“检测恢复”“导出诊断包”。已超时或取消的登录等待不会在重开助手后再次自动执行。恢复只修复环境，不继续旧任务、不清除发送或提交边界、不自动重发。已用过一次重启仍未恢复时，请手动处理微信后检测恢复，不要直接删除租约文件。诊断包包含租约分类、进程身份和归档元数据。

## 好友导入

XLSX 读取第一个工作表；CSV 支持 UTF-8 BOM 和 GB18030。表头要求：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `姓名` | 是 | 姓名末尾已带内置后缀时自动拆分一次；空姓名标记为异常 |
| `账号` | 是 | 微信号或手机号，不接受昵称；空值和重复值标记为异常 |
| `打招呼语` | 否 | 行内优先，支持 `{姓名}`、`{后缀}`、`{称呼}`；行内为空时使用全局模板，两者都空时保留微信原文 |

旧模板需补充“姓名”列。旧“备注”列存在时会提示已忽略，备注统一自动生成。缺列、重复表头、文件损坏等导入失败不会覆盖当前表格；行级错误显示来源行号，允许修正但不可执行。

每行后缀可选“使用全局”“无”、内置后缀或输入自定义后缀后按回车。全局初始为“妈妈”，可在表格下方或设置中修改并保存；只影响“使用全局”的行。“无”明确表示不追加后缀文字。内置后缀支持爸爸、妈妈、哥哥、姐姐、弟弟、妹妹、爷爷、奶奶、外公、外婆、姥爷、姥姥、伯伯、伯母、叔叔、婶婶、姑姑、姑父、舅舅、舅妈、姨妈、姨父、阿姨。

例如“示例学生姐姐”导入后拆成姓名“示例学生”和后缀“姐姐”；自动备注及 `{称呼}` 均为“示例学生姐姐”。改为“无”后，备注及 `{称呼}` 为“示例学生”，`{后缀}` 为空。点击行内编辑区域可看最终内容预览；占位符按钮插入全局模板，不覆盖行内打招呼语。未知占位符或格式错误会阻止受影响行执行。任务开始时固定最终内容并锁定编辑。`{关系}` 作为 `{后缀}` 的兼容别名继续可用。

额外列会被忽略。导入和新增记录均不自动勾选。输入“起始序号”和“结束序号”后选择区间，序号按当前表格从 1 开始并包含两端，跳过异常行；成功时替换原选择。非法、无有效记录或有效条数超限的区间会被拒绝并保留原选择，也可手动勾选或清除选择。

每批默认最多选择 100 条有效记录，可在“参数设置 → 自动发送好友申请 → 每批添加人数”设置为 1–1000 人。降低上限时保留表格顺序前 N 条已选记录，提高上限不会自动勾选。任务开始后冻结选择、源行号、内容和参数，并锁定编辑；未选记录仍保留。

验证码、操作或好友申请频繁、风控和账号限制会立即停止整批，无重试或后续等待。监控页高亮停止账号及原表序号，返回编辑页仍定位该记录，其余条目显示未执行。已触发但未能核对的结果保持未知，不重发。运行日志将 UTC 时间按系统本地时区显示，诊断数据保留 UTC。

正常模式在资料、打招呼语和备注回读一致后点击最终“确定”；提交后无法撤回。设置 `WECHAT_COURIER_ACCEPTANCE=1` 的验收模式和 `tools/safe_uia_preflight.py` 始终停在提交前并安全关闭表单。内置和用户自定义打招呼语不随品牌更名改写。

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
dist/福格微信助手/福格微信助手.exe
dist/福格微信助手/wechat-agent.exe
dist/福格微信助手_Setup.exe
```

安装器兼容旧“五阿哥微信助手”和“五阿哥群发助手”：仅处理注册信息和产品可执行文件共同确认的旧安装及快捷方式，保留未知文件与 `QSettings("wx4py", "WeChatCourier")` 外观和任务参数。本轮仅修改构建配置，不生成安装包。

## 兼容性

`src.WeChatClient` 的公共导入仍保留，便于旧调用方迁移；v0.3.1 的生产 GUI 不再依赖它执行任务。活动队列和结果不跨 GUI 重启恢复，短期安全日志只用于防止 Agent 重启后重复发送。UIA 诊断采用滚动 JSONL，并可从任务监控页导出脱敏诊断包。

## 1.0.0 Acceptance Harness

`tests/manual_v032_gui_acceptance.py` keeps its historical filename and has four opt-in profiles: `smoke` (six alternating text/preflight tasks), `independent` (exactly 40 alternating tasks, 20 sends + 20 preflights), `soak` (60 minutes), and `delivery` (two independent text/file tasks). Every invocation defaults to plan-only. Reports use acceptance version 1.0.0 and declare their coverage; no single profile claims the complete release gate.

Dependencies: Windows 10/11, Python 3.10+, `requirements-dev.txt` (PySide6, pywin32, comtypes, pyperclip, pytest). UIA uses the repository's `src/core/uiautomation.py`; no additional UI automation package or Computer Use is required. Live tests require an interactive, unlocked desktop and logged-in supported WeChat. Close other Courier instances before starting. Do not interact with either application during a run.

Offline validation and a plan-only report (no application launch, desktop actions, or sends):

```powershell
python -m pytest tests/test_v032_acceptance.py -o addopts= -q
python tests/manual_v032_gui_acceptance.py --mode gui --report .artifacts/v032-plan.json
```

For development without packaging, `--mode gui --gui-source` launches the real QML GUI and real Named Pipe Agent using a temporary settings file. It drives the same accessible controls as packaged GUI mode; it is not the direct-workflow `source` mode. This preserves user settings, but does not certify an installer or packaged binaries. Live authorization flags are still required.

The following commands are **live and opt-in**. Run modes sequentially, never concurrently. Do not run until the operator explicitly authorizes sending unique test texts to `文件传输助手` and searching/filling/cancelling the friend form for `18896904196`. No other recipient or friend submission is accepted. Attachments require the separate `delivery` profile and `--confirm-delivery`. A smoke run performs six separate one-item tasks: text then friend preflight, each from visible, minimized, and tray-hidden WeChat states. These states concern **WeChat**, not Courier; Courier remains visible for UIA button actions. Closing WeChat must be configured to hide to tray; unexpected exit aborts the run.

```powershell
# The harness sets these flags only in its packaged GUI child process:
# WECHAT_COURIER_ACCEPTANCE=1 and QT_ACCESSIBILITY=1
python tests/manual_v032_gui_acceptance.py --mode gui --profile smoke --gui-exe "dist/福格微信助手/福格微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-smoke.json

# Same cases, repeatedly as independent tasks for 60 minutes; default gap is 60s.
python tests/manual_v032_gui_acceptance.py --mode gui --profile soak --gui-exe "dist/福格微信助手/福格微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-soak.json

# Fixed task count, independent of soak duration: 20 sends + 20 friend preflights.
python tests/manual_v032_gui_acceptance.py --mode gui --profile independent --gui-exe "dist/福格微信助手/福格微信助手.exe" --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-gui-independent.json

# Explicit delivery authorization; preselect File Transfer Assistant for the read-only baseline.
python tests/manual_v032_gui_acceptance.py --mode gui --profile delivery --gui-exe "dist/福格微信助手/福格微信助手.exe" --execute --confirm-send --confirm-delivery --report .artifacts/v032-gui-delivery.json

# Comparison entrypoints. Neither can substitute for packaged GUI acceptance.
python tests/manual_v032_gui_acceptance.py --mode source --profile smoke --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-source-smoke.json
python tests/manual_v032_gui_acceptance.py --mode rpc --agent-exe "dist/福格微信助手/wechat-agent.exe" --profile smoke --execute --confirm-send --confirm-friend-preflight --report .artifacts/v032-rpc-smoke.json
```

For standalone inspection of the accessibility metadata, explicitly launch the packaged GUI with `$env:WECHAT_COURIER_ACCEPTANCE="1"` and `$env:QT_ACCESSIBILITY="1"`; remove those environment variables afterwards. This does not itself authorize task execution. Normal application runs must not expose raw editor/task metadata.

GUI mode uses only UIA to populate the actual editors, open settings, import its generated single-row CSV through the native Open dialog, and invoke Start. It never calls controllers, the Agent RPC, or the workflow engine. Invoke/Value patterns are preferred; unavailable patterns permit a fresh accessible-control-bounds fallback, with input readback. Invoke exceptions are never retried. The sole no-effect exception is non-destructive WeChat tray hiding: after Invoke returns but the window stays visible, the harness revalidates the same close control RuntimeId and main-window owner, then attempts one bounds click and verifies hidden state. Start/send never receive that retry. Message settings must match the canonical defaults (2/3 seconds), friend settings 15/30 seconds, unknown policy `continue`; mismatched pending GUI payloads abort before Start. Settings are inspected, not overwritten.

Delivery generates one fresh, uniquely named ASCII `.txt` per task, containing only a test marker and benign text. Arbitrary paths, changed content, additional files, and unrelated GUI attachments are rejected. GUI mode selects the file with the actual `messageAddFileButton` and native file dialog and verifies attachment readback. The second task removes only the harness's previous attachment through `messageRemoveFileButton-0`. All text and ordinary attachment sends remain restricted to File Transfer Assistant.

Delivery evidence combines exact single started/completed action pairs from bounded, already-redacted production diagnostics with read-only UIA observations of the selected File Transfer Assistant message list. Text and filename must be absent before the task and each appear exactly once afterwards. Missing evidence, repeated actions, duplicate bubbles, or changed runtime build identity fail the profile. The operator must preselect this chat for the baseline; the audit itself does not navigate WeChat. Counts cover the exposed current message-list snapshot, not an unbounded historical/account-wide duplicate audit. Evidence retains UTC timestamps, per-item monotonic elapsed milliseconds and risk categories without copying private log details.

Acceptance-only `Accessible.name` contract:

- `App.qml`: `messageWorkspaceTab`, `friendWorkspaceTab`, `acceptanceEditorState`, `acceptanceTaskState`.
- `MessageWorkspace.qml`: `messageRecipientsInput`, `messageTemplateInput`, `startMessageButton`; delivery also uses `messageAddFileButton`, `messageRemoveFileButton-0`.
- `FriendWorkspace.qml`: `importFriendsButton`, `friendAccountField`, `friendRangeStart`, `friendRangeEnd`, `selectFriendRangeButton`, `startFriendsButton`. Import leaves all rows unselected; the harness selects its one-row range explicitly.
- `WxTitleBar.qml`: `settingsButton`, exposed as an accessible button with a press action.
- `SettingsDialog.qml`: `settingsMessageIntervalMin`, `settingsMessageIntervalMax`, `settingsCloseButton`.
- `TaskMonitor.qml`: `taskReturnToEditorButton`, `taskStopButton`.

The two state nodes expose JSON through `Accessible.description` / UIA FullDescriptionProperty (30159), read using `GetPropertyValue(30159)`, gated by `task.acceptanceEnabled` (`WECHAT_COURIER_ACCEPTANCE=1`). Only an empty FullDescription falls back to legacy `HelpText`; malformed or oversized JSON fails without fallback, with the same strict JSON parsing and 32 KiB limit. Editor state binds `acceptanceMessageState` or `acceptanceFriendState` and includes `active`, hello-derived `friendSubmitEnabled` (must be boolean false), `kind`, pending `items`, and normalized `options`. Friend options include the integer `friendBatchLimit`; canonical live acceptance requires its default value of 100. Task state binds `acceptanceTaskState` and includes actual `taskId`, `kind`, `active`, `phase`, terminal `outcome`, counts (`done`, `total`, `success`, `error`, `unknown`, `stopped`), `echoedItems`, and bounded event proof (`taskId`, `itemId`, `step`, `outcome`). Success requires a fresh ID, matching item, and `send_verified` or `preflight_completed`; a success label alone is insufficient. Nodes must remain accessible across editor/monitor views. Native Open dialog selectors are filename Edit `AutomationId=1148` and Open Button `AutomationId=1`; missing/ambiguous controls fail closed.

Reports contain a run ID, unique texts, cases, observed window states, per-task evidence, explicit coverage exclusions, source/git fingerprint, and a SHA-256 manifest of the entire supplied package directory. Generated CSV inputs live in a unique run directory beside the report. Keep reports outside the package directory. Event details and unrecognized payload fields are omitted; Win32 window titles are hashed. On a startup/UIA failure, the supervisor records the last requested control and bounded Win32-only diagnostics (up to 24 windows, 100ms response probe each, 3s overall enumeration budget). Defaults: startup deadline 20s, whole-task deadline 120s, UIA tree budget 512 nodes. The 60-minute soak stops after the first unexplained failure; it never retries or replays a failed task. A hung worker is terminated after bounded cleanup, but Courier/Agent may remain running: inspect and stop an active task before any further run. The JSON is checkpointed after each task. Exit code 0 means plan generated or subset passed, 2 means failure; inspect `status` and `coverage`, not the exit code alone.

Success additionally requires actual terminal `cleanup.success=true`, `health.windowEnabled=true`, `health.windowResponsive=true`, `health.sessionReady=true`, and explicit `health.blockingWindow=null`. Counts alone cannot pass. The exact runtime `buildFingerprint` from source build metadata or Agent hello/GUI metadata is retained and must remain identical throughout the run. Missing startup identity prevents dispatch. Failed runs retain bounded phase breadcrumbs and safe traceback file/function/line locations, never source lines or general exception payloads. Known cursor-position-mismatch errors additionally retain only numeric expected/actual points.

The worker requests per-monitor-V2 process/thread DPI awareness before any adapter/Qt/UIA initialization, verifies effective thread awareness, and records `dpiEvidence`. Desktop initialization re-verifies awareness; each bounds click checks it again. The native cursor-position guard remains enabled. A process-awareness access-denied result can be recorded when awareness was already set, but effective thread awareness must still verify as per-monitor V2. No extra toolkit or QGuiApplication is created merely to establish DPI awareness.

## 许可

[MIT License](LICENSE)
