# 工作区布局与表格交互验收

日期：2026-10-06。分支：main。产品版本：1.0.0。
视觉基准：`prototypes/fuge-ui/index.html`。

## 实施范围

- 三个编辑工作区使用同一页头组件，分别显示“工作区 / 消息”“工作区 / 好友”“工作区 / 联系人”和完整模块名称。好友页不再显示重复副标题。
- 联系人页采用页头、折叠数据来源、独立账号栏、搜索筛选、表格和紧凑底栏；保留目录检测、手动选择、提权、读取、取消、清空和导出目录入口。
- 导出按钮先打开窗口内确认，显示当前筛选数量和四种格式，再进入原有保存/目录及覆盖确认流程。
- 后缀框单击文字编辑、单击箭头展开。预设立即保存；自定义 Enter/失焦提交、Escape 取消；Tab、中文菜单和任务锁定沿用原行为。
- 好友表格最小内容宽度 1158px，扩展姓名、账号、打招呼语和备注；联系人基础列宽为 130/140/140/238/185/215px。表头、行和单元格使用同一份最终列宽，宽窗口铺满、窄窗口横向滚动。
- 空表的联系人表头使用独立 QML 表头元数据，联系人模型仍为空，不生成虚假联系人行。
- 补齐本地 Lucide 图标及许可证；打包资源收集包含 `.js`，Qt 裁剪规则保留表头使用的 `Qt.labs.qmlmodels`。资源回归验证实际收集与过滤逻辑，本轮没有生成冻结程序。

未修改控制器、RPC、业务模型、QSettings、发送策略、版本、DWM 或原生窗口渲染代码。

## 回归结果

- 全量 `python -m pytest -o addopts= -q`：1619 passed，1 skipped，0 failed，192.91 秒。使用隔离测试租约路径。
- `python tests/run_qml_tests.py`：199 passed，0 failed。
- 真实好友控制器与临时 QSettings：单击后缀、预设、自定义、取消、失焦、Tab、运行锁定、区间及宽度回归；新增 200 行滚动复用验证通过，第 121 行编辑不会修改原第 1 行。
- 联系人实际 QML、BackendController、独立模拟读取进程和后台文件任务联测通过；不连接真实微信。筛选 90 条虚构记录中的 10 条后，CSV/JSON/Excel 及“全部格式”只导出这 10 条，取消及覆盖确认保留。
- 资源与构建规则补充回归：37 passed，1 skipped；包含列宽脚本和表头插件保留断言。
- Python 编译检查和 `git diff --check` 通过，只有 Git 的既有 CRLF 转换提示。
- 独立审查发现的资源清单遗漏已修复，最终没有剩余可执行发现。

QuickTest 在既有主窗口/销毁阶段仍有非失败警告；本轮联系人表头没有类型、角色或布局警告，正式 QML 截图加载警告为 0。

## 界面验收

`scripts/verify_fuge_ui.py` 加载正式 `qml/main.qml`、真实控制器、假 RPC 和虚构数据。Windows 原生渲染截图实际 DPR 分别断言为 1.0、1.5、2.0，不以缩小逻辑窗口代替 DPI 验收。

- 逻辑尺寸：960×680、1320×880、1920×1080；深浅主题、展开/折叠侧栏。
- 三个工作区、两类任务监控、设置和设置内中文菜单。
- 联系人目录展开、导出弹窗；额外检查空表、无搜索结果、好友单行异常、200 行表格和长文本。
- 100% 最终场景 75 张，150% 和 200% 各 64 张，共 203 张场景截图，加载警告均为 0。
- 脚本检查可见操作按钮边界、表格宽度和非空像素；已人工查看联系人宽窗口、最小窗口导出弹窗、200% 深色目录展开、好友异常行及空表截图，未发现重叠或右侧行背景缺口。
- 原生普通/最大化/还原圆角属性及毛玻璃可用性检查通过。原生实现未修改，未执行额外的人工 Snap/拖动验收。
- 软件渲染离屏截图仅用于布局回归，图标视觉验收使用 Windows 原生截图。

## 记录位置

- `.artifacts/workspace-layout/pytest-final.log`
- `.artifacts/workspace-layout/quicktest-final.log`
- `.artifacts/workspace-layout/native-100-final/verification.json`
- `.artifacts/workspace-layout/native-150/verification.json`
- `.artifacts/workspace-layout/native-200/verification.json`
- `.artifacts/workspace-layout/controller-gui/`：独立模拟读取与导出产物。

## 对照截图

- [联系人布局](../../.artifacts/workspace-layout/native-100-final/contacts-light-1320-expanded.png)
- [联系人导出确认](../../.artifacts/workspace-layout/native-100-final/contacts-export-light-960.png)
- [联系人空表](../../.artifacts/workspace-layout/native-100-final/contacts-empty-light.png)
- [好友表格](../../.artifacts/workspace-layout/native-100-final/friends-light-1920-expanded.png)
- [好友单行异常](../../.artifacts/workspace-layout/native-100-final/friends-invalid-light.png)
- [200% 深色目录展开](../../.artifacts/workspace-layout/native-200/contacts-source-dark-960.png)

## 交付边界

本轮交付源码、界面截图和验收记录。没有发送消息、提交好友申请、读取真实联系人，也没有提交、打包或推送。未执行安装包验收；本轮源码验证不替代后续冻结程序的资源检查。
