# 联系人页视觉精修验收

日期：2026-10-06。分支：main。产品版本：1.0.0。

## 实施范围

- 仅修改联系人工作区；保持其他模块、共享主题、字体、原生圆角和毛玻璃实现不变。
- 页头 80px，移除常驻“本次会话数据”；数据来源仍可展开，目录检测、手动选择和提交行为保留。
- 工具区在工作区宽度达到 1152px 时单行，否则两行；账号框最大 280px，搜索框最大 480px。切换布局不重新创建控件，不丢失搜索文本。
- 初始读取突出品牌橙色；已有数据时突出导出；禁用主操作回到中性样式。
- 表头和数据行仅保留细横线，悬停反馈覆盖整行。沿用同一份最终列宽、排序、复制和横向滚动；内容可容纳时隐藏滚动条。
- 空表区分未读取、未发现账号、读取中、错误、没有匹配结果和空库。数据来源/清除搜索为显式操作；权限不足仍由原控制器提供管理员读取入口。
- 底栏 56px，只保留阶段、执行耗时及操作。初始计时隐藏，结束后保留；长错误可通过悬停完整查看。
- 重新读取、取消或失败保留已有有效表格，空状态不覆盖已有可见数据。UIA 未就绪不额外阻止联系人读取。

没有修改控制器、模型、RPC、QSettings、读取流程、导出格式或互斥规则。

## 验证结果

- 新增四项 QML 行为测试先观察到失败，再由实现转为通过；涵盖工具区断点、空状态、主次操作、计时和整行悬停。
- 联系人相关 Python、真实控制器及 QML 回归：48 passed，30.14 秒。
- 全量 `python -m pytest -o addopts= -q`：1619 passed，1 skipped，200.51 秒。Agent 测试使用隔离租约路径。
- `python tests/run_qml_tests.py`：203 passed，0 failed。既有离屏字体/销毁警告不影响测试；正式截图加载警告为 0。
- `python -m compileall -q app src scripts tests` 和 `git diff --check` 通过。
- 独立审查发现跨单元格事件顺序可能清除整行高亮；已改为按代理身份记录悬停并在回收/销毁时释放。新增跨列及第 121 行复用测试先失败后通过，最终联系人 QuickTest 58 项通过。
- 全量回归、203 项 QuickTest 及截图在该悬停修正前完成；修正后仅重跑联系人测试，按用户最新要求直接提交、打包，不追加全量验收。
- 真实控制器、临时 QSettings、独立模拟读取进程及文件后台任务联测保留：读取、取消后重读、筛选、排序、复制、三种格式、全部格式及覆盖确认。仅导出筛选中的 10 条虚构数据。

## 正式界面截图

`scripts/verify_contact_ui.py` 加载正式 `qml/main.qml`、真实 BackendController 与联系人控制器。Agent 和联系人读取均替换为假驱动，不连接微信、不访问个人数据目录。

- 100%、150%、200%：实际窗口 DPR 分别断言为 1.0、1.5、2.0，每组 36 张，共 108 张。
- 逻辑尺寸 960×680、1320×880、1920×1080，以及实际最大化；深浅主题、展开/折叠侧栏、毛玻璃开启。
- 状态包含空表、200 条虚构记录、无账号、来源展开、读取中、权限错误、搜索无结果、取消/失败保留数据和长错误。
- 自动检查可见控件边界、相互不重叠、账号/搜索宽度、表格总宽度、滚动条及截图非空；三档均通过，无 QML 加载警告。
- 已查看宽窗口空状态、浅色加载表格、权限错误、150% 来源展开和 200% 最小窗口深色截图。窄表需要横向滚动，不压缩字号或列宽。

## 对照与记录

- [精修前联系人页](../../.artifacts/workspace-layout/native-100-final/contacts-light-1320-expanded.png)
- [精修后联系人页](../../.artifacts/contact-refinement/native-100/loaded-light-1320-expanded.png)
- [宽窗口空状态](../../.artifacts/contact-refinement/native-100/idle-light-1920-collapsed.png)
- [权限错误](../../.artifacts/contact-refinement/native-100/permission-error.png)
- [200% 深色最小窗口](../../.artifacts/contact-refinement/native-200/loaded-dark-960-expanded.png)
- 全量回归：`.artifacts/contact-refinement/pytest.log`
- QuickTest：`.artifacts/contact-refinement/quicktest.log`
- 三档截图报告：`.artifacts/contact-refinement/native-{100,150,200}/report.json`

## 交付边界

界面实施阶段交付源码、截图和验收记录，未读取真实联系人或操作微信。后续按用户最新请求提交并打包，不推送；冻结程序仅核验资源及依赖，不连接真实微信进行安装包验收。
