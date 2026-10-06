# 福格微信助手 1.0.0 界面验收

日期：2026-10-06。视觉基准：`prototypes/fuge-ui/index.html`。

## 范围

- 正式 PySide6/QML，未使用 WebView 或浏览器运行时。
- 品牌橙色、深浅主题、共享控件、中文菜单和 216/64px 侧栏。
- 三个工作区、真实模型编辑、监控、设置及任务锁定。
- 仅新增 `ui/sidebarCollapsed` 偏好；产品版本、原有设置键和业务契约不变。
- 未修改 `app/window_shell.py` 或 `app/win32_helper.py`。

## 回归结果

- `python -m pytest -o addopts= -q`：1573 通过，1 跳过。
- QML QuickTest：197 通过，0 失败。
- Python 编译检查、`git diff --check`：通过。
- 真实控制器与临时 QSettings 联测：菜单动作、下拉框文字区点击、侧栏持久化、编辑草稿、运行锁定、计时及工作区切换。
- 审查发现的三项问题已修复：业务设置草稿残留、非编辑下拉框吞点击、健康摘要进入原生命中拖动区。均有回归验证。

## 正式 QML 截图

由 `scripts/verify_fuge_ui.py` 加载 `qml/main.qml`，使用真实控制器、假 RPC 和虚构数据生成。

- 逻辑尺寸：960×680、1320×880。
- Windows 实际设备倍率：1.0、1.5、2.0；脚本断言实际 DPR，不以环境变量名称代替验证。
- 覆盖深浅主题、展开/折叠侧栏、三个工作区、设置、设置之上的中文菜单、两类任务监控，共 120 张 QML 截图。
- 各倍率均完成非空像素、可见操作按钮边界及资源加载检查；生产 QML 加载警告为 0。
- 长名单、200 行好友表、多附件及联系人横向滚动使用虚构数据；正文不因窗口宽度而缩小。
- Windows DWM 圆角属性：普通窗口 2、最大化 1、还原 2；毛玻璃接口返回可用。拖动、缩放与 Snap 沿用原生实现和既有回归测试，未另行执行人工拖动验收。

截图和机器可读报告保存在 `.artifacts/fuge-ui-100/`、`.artifacts/fuge-ui-150/`、`.artifacts/fuge-ui-200/`；每个目录的 `verification.json` 对应本轮实际渲染。

## 关键截图

- [普通窗口原生圆角](../../.artifacts/fuge-ui-100/native-rounded-frame.png)
- [原生玻璃窗口](../../.artifacts/fuge-ui-100/native-glass-frame.png)
- [消息群发](../../.artifacts/fuge-ui-100/messages-light-1320-expanded.png)
- [好友申请](../../.artifacts/fuge-ui-100/friends-light-960-expanded.png)
- [联系人导出](../../.artifacts/fuge-ui-100/contacts-light-960-expanded.png)
- [设置与中文菜单](../../.artifacts/fuge-ui-100/settings-menu-light-960.png)

## 边界

未发送消息、提交好友申请或读取真实联系人，未提交、打包或推送。截图仅验证界面，不代表对真实微信业务重新验收。QuickTest 的模拟对象及销毁阶段仍有非失败警告；正式 QML 截图流程没有对应警告。

## 2026-10-06 排列修正

- 好友编辑页底栏改为左侧状态、人数与间隔，右侧提交提醒与启动按钮；可用宽度不足 900px 时分成两行，保留提交确认和错误提示。
- 侧栏所有操作按钮统一为 42px 高、18px 图标；折叠时共用中心线，展开时导航、主题和设置共用图标及文字起点。鼠标点击不再残留键盘焦点边框。
- 新增真实 QML 几何回归，覆盖 960×680 / 1320×880、展开 / 折叠、深 / 浅主题。界面相关测试通过；QuickTest 197 通过。
- `scripts/verify_fuge_ui.py --output .artifacts/ui-alignment`：40 张正式 QML 截图，实际 DPR 1.25，加载警告 0；已检查好友页大窗口和最小窗口截图。
- 全量 Python 首轮：1581 通过、1 跳过、3 失败。表格新增行测试原先在滚动动画结束前断言，改为有界等待可见后重跑通过。原有会话清理测试隔离本机租约后通过；生产 Gate 恢复 CLI 测试因本机已运行 Agent 的互斥锁退出，未关闭用户实例或操作微信来绕过。
- 编译检查及 `git diff --check` 通过。本轮未改发送、附件、Gate 或原生窗口逻辑，未执行真实微信操作。
