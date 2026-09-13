# 五阿哥微信助手

面向 Windows 个人微信客户端的批量消息与好友申请助手。v0.3.0 使用 PySide6/QML 提供桌面界面，并将所有微信 UI Automation 操作隔离到独立的 `wechat-agent.exe` 进程。

> 当前自动化仅放行经过验证的微信 Windows 客户端 `4.1.13.65`。其他版本可以编辑任务，但不能启动自动化。

## 功能

- 消息群发：逐个精确匹配好友、回读聊天标题和输入内容、发送后核对新增消息。
- 附件发送：支持逐人附件；合并模式会先上传到文件传输助手，再执行真正的多选合并转发。
- 模板称呼：消息中的 `{name}` 会按好友备注生成称呼。
- 批量加好友：导入 XLSX 或 CSV，编辑账号、打招呼语和备注后执行预检。
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
- UIA 等待由结构、焦点和文本属性事件唤醒，并保留 200ms 截止轮询。
- 搜索目标必须规范化后完全相等且唯一。零条或多条结果都会阻止发送或提交。
- “发送”和好友申请“确定”均为单次破坏性动作。触发后无法可靠确认时标记未知，默认继续下一项，不会自动重试。

## 好友导入

XLSX 读取第一个工作表；CSV 支持 UTF-8 BOM 和 GB18030。表头要求：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `账号` | 是 | 微信号或手机号，不接受昵称；空值和重复值标记为异常 |
| `打招呼语` | 否 | 行内为空时使用全局默认；两者都空时保留微信原文 |
| `备注` | 否 | 行内为空时使用全局默认；两者都空时不填写 |

额外列会被忽略。导入后默认选择前 20 条有效记录，任何方式均不能一次选中超过 20 条。验证码、操作频繁、风险提示或账号限制会立即停止整批。

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

手工好友路径探针默认只填表、不提交；只有显式传入 `--submit` 才会点击“确定”：

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

`src.WeChatClient` 的公共导入仍保留，便于旧调用方迁移；v0.3.0 的生产 GUI 不再依赖它执行任务。活动队列和结果不跨 GUI 重启恢复，短期安全日志只用于防止 Agent 重启后重复发送或重复提交。

## 许可

[MIT License](LICENSE)
