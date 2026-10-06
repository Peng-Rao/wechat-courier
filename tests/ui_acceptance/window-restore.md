# 最小化恢复显示修复验收

产品：福格微信助手 1.0.0。分支：main。日期：2026-10-06。

## 范围

- Windows 11 原生窗口默认采用 Qt Quick OpenGL，不再强制 `QT_D3D_NO_FLIP=1`。
- 显式渲染后端和非 Windows 原生测试平台保持原选择。
- 窗口重新暴露后合并核验 HWND、恢复材质并请求一次重绘；取消已销毁窗口的回调。
- 重建 HWND 时提前安装非客户区框架，恢复一次原客户端几何；普通最小化、隐藏恢复不改变尺寸。
- 材质失败时使用不透明背景，不修改外观设置；不重建工作区。
- GUI 包显式包含 `Qt6OpenGL.dll` 和 `opengl32sw.dll`，恢复诊断记录实际渲染 API。

## 原故障证据

旧强制 D3D11 路径在 HWND 未改变、窗口 opacity=1 时仍出现颜色发白，静置不能恢复；额外 `update()` 后恢复。移除旧路径或采用 OpenGL 的隔离对照未出现该问题。原始材料保存在 `.artifacts/restore-audit/`。

`QQuickWindow.grabWindow()` 会渲染场景，不能用于修复前的第一份证据。正式门禁先采集实际桌面立即帧和静置帧，比较中性背景、文字和品牌橙色；客户端截图仅在两次桌面比较后采集。不是仅断言截图非空。

参考：[Qt Quick 窗口抓取说明](https://doc.qt.io/qt-6.11/qquickwindow.html#grabWindow)、[Qt Windows 图形后端与软件 OpenGL](https://doc.qt.io/qt-6.11/windows-graphics.html)。

## 验收环境

Windows 11 build 26200，Python 3.12，PySide6/Qt 6.11.1。显示器 1920×1080，系统缩放 125%；软件 OpenGL 另验证等效 150% 缩放。Qt 离屏布局检查使用 200% 缩放。

所有 GUI 数据为虚构数据，控制器连接假 RPC；冻结程序测试暂时移走测试产物中的 Agent，并在 finally 恢复。没有操作真实微信、gate、联系人或发送日志，没有发送或提交申请。只生成隔离冻结验证产物，不发布安装包。

## 执行记录

桌面、软件后端、冻结程序、原生窗口和全量 Python 门禁均已完成。

- 窗口生命周期及关联回归：86 passed。
- 硬件 OpenGL 正式 QML：120 次最小化恢复、24 次隐藏恢复，立即及静置桌面颜色门禁全部通过；覆盖三个工作区、两类监控、设置、深浅主题、毛玻璃开关和折叠侧栏。
- 硬件实际 HWND 重建：客户端逻辑几何和物理图像尺寸不变，背景、文字、品牌色保留率均为 100%，窗口材质可用。
- 软件 OpenGL 正式 QML，实际 DPR=1.5：24 次最小化、24 次隐藏恢复全部通过，加载 `opengl32sw.dll`；实际 HWND 重建逻辑几何一致，立即和静置颜色门禁通过，外边框存在 1 像素取整差。
- 原生材质隔离门禁：OpenGL、alphaBuffer=8、非 layered 窗口；深浅主题及 45/72/90% 透明度通过，底图条纹对比度为启用模糊 0、关闭模糊 93，确认真实模糊而不是简单透明。
- 正式 QML 原生交互门禁：设置弹窗深浅主题及两种尺寸、最大化/还原、全屏/退出、左右 Snap、移动/缩放进入普通布局、标题栏最大化/还原/最小化按钮通过；桌面截图确认圆角仍存在。
- PyInstaller 隔离冻结验证：三个 EXE 的 `win32timezone`、GUI 的两项 OpenGL DLL 检查通过；硬件与软件 OpenGL 各 12 次恢复（含最大化及隐藏），外部桌面颜色门禁通过，实际 API 为 OpenGL，软件场景加载 `opengl32sw.dll`。两次正常退出，QSettings 未变。
- 冻结验证构建指纹：`sha256:fdcea78bef4e38817fca30c6c5d1b75de254740a3c4539fd1819df6158fd7f86`，版本 1.0.0。只生成测试产物，没有制作安装器、修改已安装软件或发布包。
- QML QuickTest：197 passed，0 failed。
- 200% QML smoke：40 张截图，0 warnings。
- Python 编译检查及 `git diff --check` 通过；后者只有现有 CRLF 自动转换提示，无空白错误。
- 最终完整 Python 回归：1617 passed，1 skipped，0 failed，182.22 秒。先前一轮发生过现有 Agent 互斥占用，清理 CLI 返回 5；最终复跑未再阻断。没有为验收停止用户 Agent，也没有绕过互斥或修改该测试的安全规则。
- HWND 重建边界：先前额外检查发现 Qt 缓存边框导致客户端几何漂移，已补充专门回归与一次性几何恢复。连续重建保留首次快照，最大化/全屏快照不得套用至普通窗口；取消和销毁清除待执行恢复。
- 150% DPR 下的 HWND 重建允许最多 1 个物理像素的外边框取整差异；只裁去多出的边缘，不移动或缩放图像，不降低颜色门禁。普通恢复仍要求图像尺寸完全一致；另外独立断言客户端逻辑几何一致。
- 冻结程序截图规则：等待刻意缺失 Agent 的有界重连提示结束后比较，避免提示栏消失引起布局移动被误判为颜色故障。
- 独立代码审查：已修复材质降级、平台选择和两项待恢复几何边界；最终审查无剩余可执行问题。

## 复现命令

```powershell
python -m pytest tests/test_window_shell.py tests/test_package_dependencies.py tests/test_restore_rendering_gate.py tests/test_v3_controllers.py -o addopts= -q
python tests/manual_window_restore_rendering.py --output .artifacts/restore-fix/hardware-complete --cycles 5
$env:QT_OPENGL = 'software'
$env:QT_SCALE_FACTOR = '1.2'
python tests/manual_window_restore_rendering.py --output .artifacts/restore-fix/software-150-complete --cycles 1
Remove-Item Env:QT_OPENGL
Remove-Item Env:QT_SCALE_FACTOR
python tests/manual_window_shell_preview.py --prototype --output .artifacts/restore-fix/native-material
python tests/manual_window_shell_preview.py --output .artifacts/restore-fix/native-controls
python -m PyInstaller --noconfirm --distpath .artifacts/restore-fix/frozen --workpath .artifacts/restore-fix/pyinstaller build/build.spec
python build/verify_package.py .artifacts/restore-fix/frozen/福格微信助手
python tests/manual_frozen_window_restore.py .artifacts/restore-fix/frozen/福格微信助手/福格微信助手.exe --output .artifacts/restore-fix/frozen-hardware-final
python tests/manual_frozen_window_restore.py .artifacts/restore-fix/frozen/福格微信助手/福格微信助手.exe --software --output .artifacts/restore-fix/frozen-software-final
$env:WECHAT_AGENT_GATE_LEASE = Join-Path (Resolve-Path .artifacts/restore-fix).Path 'regression-isolated-gate.json'
python -m pytest -o addopts= -q
Remove-Item Env:WECHAT_AGENT_GATE_LEASE
python tests/run_qml_tests.py
```

原始 JSON、桌面截图、QML 日志和冻结验证产物保存在忽略目录 `.artifacts/restore-fix/`。报告不包含真实业务数据。

已完成的桌面记录：`.artifacts/restore-fix/hardware-complete/report.json`。
软件记录：`.artifacts/restore-fix/software-150-complete/report.json`；原生材质：`.artifacts/restore-fix/native-material/report.json`。
原生交互记录：`.artifacts/restore-fix/native-controls/report.json`。
冻结记录：`.artifacts/restore-fix/frozen-hardware-final/report.json`、`.artifacts/restore-fix/frozen-software-final/report.json`。

全量回归日志：`.artifacts/restore-fix/pytest-complete.log`；QML：`.artifacts/restore-fix/quicktest-complete.log`；200% smoke：`.artifacts/restore-fix/layout-200-final/verification.json`。

结论：本机原故障复现、桌面对照及专项恢复门禁通过，修复源码已完成；现有安装程序未替换，不自动提交、发布安装包或推送。结果不代表对所有显卡和远程桌面环境的普遍保证。

## 关键桌面截图

- [旧 D3D11 静置后仍发白](D:/wechat-courier/.artifacts/restore-audit/idle-restore-5.png)
- [旧路径额外渲染后恢复](D:/wechat-courier/.artifacts/restore-audit/idle-client-after.png)
- [修复后消息监控恢复前](D:/wechat-courier/.artifacts/restore-fix/hardware-complete/message-monitor-dark-glass-0-before.png)
- [修复后立即恢复桌面](D:/wechat-courier/.artifacts/restore-fix/hardware-complete/message-monitor-dark-glass-0-immediate.png)
- [修复后静置桌面](D:/wechat-courier/.artifacts/restore-fix/hardware-complete/message-monitor-dark-glass-0-idle.png)
- [软件 OpenGL 句柄重建后](D:/wechat-courier/.artifacts/restore-fix/software-150-complete/surface-idle.png)
- [真实模糊与原生圆角隔离画面](D:/wechat-courier/.artifacts/restore-fix/native-material/pattern-blur.png)
