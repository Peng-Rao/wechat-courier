# -*- coding: utf-8 -*-
"""BackendController — 应用状态中枢，连接 QML 前端与 wx4py 后端"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property, QStringListModel, QSettings

from .constants import PHASE_IDLE, PHASE_RUNNING, PHASE_PAUSED, PHASE_DONE
from .demo import is_demo_mode
from .models import extract_greeting_name
from .sender_worker import SenderWorker
from . import win32_helper
from .controllers import (
    AgentController,
    FriendController,
    MessageController,
    SettingsController,
    TaskController,
)


class BackendController(QObject):
    """整个应用的状态中枢和命令接收器。

    所有 QML 可访问的状态通过 Qt Property 暴露；
    所有 QML 触发的操作通过 Slot 接收。
    """

    # ═══════════════════════════════════════
    #  信号
    # ═══════════════════════════════════════

    phaseChanged = Signal(str)
    progressValueChanged = Signal(float)
    progressStatusChanged = Signal(str)
    currentFriendChanged = Signal(str)
    previewFriendChanged = Signal(str)
    previewGreetingChanged = Signal(str)
    previewMessageChanged = Signal(str)
    previewFileNamesChanged = Signal(list)
    previewFileCountChanged = Signal(int)
    logEntryAdded = Signal(str, str, str, str)
    fatalErrorChanged = Signal(str)
    demoModeChanged = Signal(bool)
    versionInfoChanged = Signal(str)
    inputsEnabledChanged = Signal(bool)
    friendListTextChanged = Signal(str)
    templateTextChanged = Signal(str)
    useForwardChanged = Signal(bool)
    filePathsChanged = Signal(list)
    fileSizesChanged = Signal(list)
    sendIntervalMinChanged = Signal(float)
    sendIntervalMaxChanged = Signal(float)
    isDarkChanged = Signal(bool)
    glassEnabledChanged = Signal(bool)
    glassOpacityChanged = Signal(int)
    showToast = Signal(str, str)
    previewIndexChanged = Signal(int)

    def __init__(
        self,
        version: str = "0.1.0",
        parent=None,
        settings: QSettings | None = None,
        worker_factory=None,
        agent_client=None,
        auto_start_agent: bool = False,
    ):
        super().__init__(parent)

        # ── 内部状态 ──
        self._phase = PHASE_IDLE
        self._friend_list_text = ""
        self._template_text = ""
        self._use_forward = False
        self._file_paths: list[str] = []
        self._file_sizes: list[str] = []
        self._file_path_model = QStringListModel(self)
        self._progress_value = 0.0
        self._progress_status = "待开始"
        self._current_friend = ""
        self._preview_friend = ""
        self._preview_greeting = ""
        self._preview_message = ""
        self._preview_file_names: list[str] = []
        self._preview_file_count = 0
        self._preview_index = 0
        self._fatal_error = ""
        self._version = version
        self._inputs_enabled = True
        self._demo_mode = is_demo_mode()
        self._settings = settings or QSettings("wx4py", "WeChatCourier", self)
        self._is_dark = self._settings.value("isDark", False, type=bool)
        self._send_interval_min = 2.0
        self._send_interval_max = 3.0
        self._glass_enabled = self._settings.value("visual/glassEnabled", True, type=bool)
        self._glass_opacity = self._clamp_glass_opacity(
            self._settings.value("visual/glassOpacity", 72, type=int)
        )

        # ── 发送状态 ──
        self._worker: SenderWorker | None = None
        self._worker_factory = worker_factory or SenderWorker
        self._prev_phase_for_pause = PHASE_IDLE
        self._send_error_count = 0
        self._send_fatal_error_seen = False

        # v0.3 聚合控制器。旧属性继续保留，供现有调用方平滑迁移。
        self._message_controller = MessageController(self._settings, self)
        self._friends_controller = FriendController(self._settings, self)
        self._settings_controller = SettingsController(self, self._settings, self)
        self._agent_controller = AgentController(agent_client, self)
        self._task_controller = TaskController(
            self._agent_controller,
            self._message_controller,
            self._friends_controller,
            self._settings_controller,
            self,
        )
        if auto_start_agent:
            self._agent_controller.start()

        # 初始化只读属性
        self.demoModeChanged.emit(is_demo_mode())
        self.versionInfoChanged.emit(f"五阿哥微信助手 v{self._version}")

    # ═══════════════════════════════════════
    #  Properties
    # ═══════════════════════════════════════

    # ── phase ──
    def _get_phase(self) -> str:
        return self._phase

    def _set_phase(self, value: str):
        if self._phase != value:
            self._phase = value
            self.phaseChanged.emit(value)

    phase = Property(str, _get_phase, _set_phase, notify=phaseChanged)

    # ── friendListText ──
    def _get_friend_list_text(self) -> str:
        return self._friend_list_text

    def _set_friend_list_text(self, value: str):
        if self._friend_list_text != value:
            self._friend_list_text = value
            self.friendListTextChanged.emit(value)
            if self._fatal_error:
                self._fatal_error = ""
                self.fatalErrorChanged.emit("")
            self._update_preview()

    friendListText = Property(str, _get_friend_list_text, _set_friend_list_text, notify=friendListTextChanged)

    # ── templateText ──
    def _get_template_text(self) -> str:
        return self._template_text

    def _set_template_text(self, value: str):
        if self._template_text != value:
            self._template_text = value
            self.templateTextChanged.emit(value)
            if self._fatal_error:
                self._fatal_error = ""
                self.fatalErrorChanged.emit("")
            self._update_preview()

    templateText = Property(str, _get_template_text, _set_template_text, notify=templateTextChanged)

    # ── useForward ──
    def _get_use_forward(self) -> bool:
        return self._use_forward

    def _set_use_forward(self, value: bool):
        if self._use_forward != value:
            self._use_forward = value
            self.useForwardChanged.emit(value)

    useForward = Property(bool, _get_use_forward, _set_use_forward, notify=useForwardChanged)

    # ── filePaths ──
    def _get_file_paths(self) -> list:
        return list(self._file_paths)

    filePaths = Property(list, _get_file_paths, notify=filePathsChanged)

    # ── filePathModel ──
    def _get_file_path_model(self):
        return self._file_path_model

    filePathModel = Property('QVariant', _get_file_path_model, notify=filePathsChanged)

    # ── fileSizes ──
    def _get_file_sizes(self) -> list:
        return list(self._file_sizes)

    fileSizes = Property(list, _get_file_sizes, notify=fileSizesChanged)

    # ── progressValue ──
    def _get_progress_value(self) -> float:
        return self._progress_value

    progressValue = Property(float, _get_progress_value, notify=progressValueChanged)

    # ── progressStatus ──
    def _get_progress_status(self) -> str:
        return self._progress_status

    progressStatus = Property(str, _get_progress_status, notify=progressStatusChanged)

    # ── currentFriend ──
    def _get_current_friend(self) -> str:
        return self._current_friend

    currentFriend = Property(str, _get_current_friend, notify=currentFriendChanged)

    # ── previewFriend ──
    def _get_preview_friend(self) -> str:
        return self._preview_friend

    previewFriend = Property(str, _get_preview_friend, notify=previewFriendChanged)

    # ── previewGreeting ──
    def _get_preview_greeting(self) -> str:
        return self._preview_greeting

    previewGreeting = Property(str, _get_preview_greeting, notify=previewGreetingChanged)

    # ── previewMessage ──
    def _get_preview_message(self) -> str:
        return self._preview_message

    previewMessage = Property(str, _get_preview_message, notify=previewMessageChanged)

    # ── previewFileNames ──
    def _get_preview_file_names(self) -> list:
        return list(self._preview_file_names)

    previewFileNames = Property(list, _get_preview_file_names, notify=previewFileNamesChanged)

    # ── previewFileCount ──
    def _get_preview_file_count(self) -> int:
        return self._preview_file_count

    previewFileCount = Property(int, _get_preview_file_count, notify=previewFileCountChanged)

    # ── previewIndex ──
    def _get_preview_index(self) -> int:
        return self._preview_index

    def _set_preview_index(self, value: int):
        if self._preview_index != value:
            self._preview_index = value
            self.previewIndexChanged.emit(value)
            self._update_preview()

    previewIndex = Property(int, _get_preview_index, _set_preview_index, notify=previewIndexChanged)

    # ── fatalError ──
    def _get_fatal_error(self) -> str:
        return self._fatal_error

    fatalError = Property(str, _get_fatal_error, notify=fatalErrorChanged)

    # ── versionInfo ──
    def _get_version_info(self) -> str:
        return f"五阿哥微信助手 v{self._version}"

    versionInfo = Property(str, _get_version_info, notify=versionInfoChanged)

    # ── inputsEnabled ──
    def _get_inputs_enabled(self) -> bool:
        return self._inputs_enabled

    inputsEnabled = Property(bool, _get_inputs_enabled, notify=inputsEnabledChanged)

    # ── demoMode ──
    def _get_demo_mode(self) -> bool:
        return self._demo_mode

    demoMode = Property(bool, _get_demo_mode, notify=demoModeChanged)

    # ── sendIntervalMin ──
    def _get_send_interval_min(self) -> float:
        return self._send_interval_min

    def _set_send_interval_min(self, value: float):
        if self._send_interval_min != value:
            self._send_interval_min = value
            self.sendIntervalMinChanged.emit(value)

    sendIntervalMin = Property(float, _get_send_interval_min, _set_send_interval_min, notify=sendIntervalMinChanged)

    # ── sendIntervalMax ──
    def _get_send_interval_max(self) -> float:
        return self._send_interval_max

    def _set_send_interval_max(self, value: float):
        if self._send_interval_max != value:
            self._send_interval_max = value
            self.sendIntervalMaxChanged.emit(value)

    sendIntervalMax = Property(float, _get_send_interval_max, _set_send_interval_max, notify=sendIntervalMaxChanged)

    # ── isDark ──
    def _get_is_dark(self) -> bool:
        return self._is_dark

    def _set_is_dark(self, value: bool):
        if self._is_dark != value:
            self._is_dark = value
            self._settings.setValue("isDark", value)
            self._settings.sync()
            self.isDarkChanged.emit(value)

    isDark = Property(bool, _get_is_dark, _set_is_dark, notify=isDarkChanged)

    # ── glassEnabled ──
    def _get_glass_enabled(self) -> bool:
        return self._glass_enabled

    def _set_glass_enabled(self, value: bool):
        normalized = bool(value)
        if self._glass_enabled != normalized:
            self._glass_enabled = normalized
            self._settings.setValue("visual/glassEnabled", normalized)
            self._settings.sync()
            self.glassEnabledChanged.emit(normalized)

    glassEnabled = Property(bool, _get_glass_enabled, _set_glass_enabled, notify=glassEnabledChanged)

    # ── glassOpacity ──
    def _get_glass_opacity(self) -> int:
        return self._glass_opacity

    def _set_glass_opacity(self, value: int):
        normalized = self._clamp_glass_opacity(value)
        if self._glass_opacity != normalized:
            self._glass_opacity = normalized
            self._settings.setValue("visual/glassOpacity", normalized)
            self._settings.sync()
            self.glassOpacityChanged.emit(normalized)

    glassOpacity = Property(int, _get_glass_opacity, _set_glass_opacity, notify=glassOpacityChanged)

    # ── v0.3 domain facades ──
    message = Property(QObject, lambda self: self._message_controller, constant=True)
    friends = Property(QObject, lambda self: self._friends_controller, constant=True)
    task = Property(QObject, lambda self: self._task_controller, constant=True)
    settings = Property(QObject, lambda self: self._settings_controller, constant=True)
    agent = Property(QObject, lambda self: self._agent_controller, constant=True)

    # ═══════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def _clamp_glass_opacity(value: int) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 72
        return max(45, min(90, numeric))

    # ═══════════════════════════════════════
    #  预览
    # ═══════════════════════════════════════

    def _update_preview(self):
        friends_raw = self._friend_list_text.strip()
        template = self._template_text.strip()
        friends_list = [f.strip() for f in friends_raw.split("\n") if f.strip()]

        has_files = len(self._file_paths) > 0

        if not friends_list or (not template and not has_files):
            self._preview_friend = ""
            self._preview_greeting = ""
            self._preview_message = "请在左侧输入名单和消息模板即可在此预览效果"
            self._preview_file_names = []
            self._preview_file_count = 0
            self.previewFriendChanged.emit("")
            self.previewGreetingChanged.emit("")
            self.previewMessageChanged.emit(self._preview_message)
            self.previewFileNamesChanged.emit([])
            self.previewFileCountChanged.emit(0)
            return

        # Clamp self._preview_index to valid range
        idx = max(0, min(self._preview_index, len(friends_list) - 1))
        if idx != self._preview_index:
            self._preview_index = idx
            self.previewIndexChanged.emit(idx)

        selected_friend = friends_list[idx]
        greeting = extract_greeting_name(selected_friend)
        self._preview_friend = selected_friend
        self._preview_greeting = greeting

        if template:
            try:
                preview_msg = template.format(name=greeting)
                self._preview_message = preview_msg
            except (KeyError, ValueError):
                self._preview_message = "消息模板格式有误，请确保仅使用了 {name} 作为占位符"
        else:
            self._preview_message = ""

        self.previewFriendChanged.emit(self._preview_friend)
        self.previewGreetingChanged.emit(self._preview_greeting)
        self.previewMessageChanged.emit(self._preview_message)

        # 文件预览
        names = [Path(p).name for p in self._file_paths]
        self._preview_file_names = names
        self._preview_file_count = len(names)
        self.previewFileNamesChanged.emit(names)
        self.previewFileCountChanged.emit(len(names))

    # ═══════════════════════════════════════
    #  QML → Python 命令
    # ═══════════════════════════════════════

    @Slot()
    def start_sending(self):
        friends_raw = self._friend_list_text.strip()
        friends_list = [f.strip() for f in friends_raw.split("\n") if f.strip()]
        template = self._template_text.strip()

        # 验证
        if not friends_list:
            self._fatal_error = "好友名单不能为空！"
            self.fatalErrorChanged.emit(self._fatal_error)
            return
        if not template:
            self._fatal_error = "消息模板不能为空！"
            self.fatalErrorChanged.emit(self._fatal_error)
            return

        self._fatal_error = ""
        self.fatalErrorChanged.emit("")
        self._send_error_count = 0
        self._send_fatal_error_seen = False

        # 创建并配置工作线程
        self._worker = self._worker_factory()
        self._worker.friends = friends_list
        self._worker.message_template = template
        self._worker.file_paths = list(self._file_paths)
        self._worker.use_forward = self._use_forward and bool(self._file_paths)

        # 连接信号
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.current_friend.connect(self._on_current_friend)
        self._worker.log_entry.connect(self._on_log_entry)
        self._worker.fatal_error.connect(self._on_fatal_error)
        self._worker.finished.connect(self._on_send_finished)

        # 更新状态
        self._set_phase(PHASE_RUNNING)
        self._set_inputs_enabled(False)
        self._progress_value = 0.0
        self.progressValueChanged.emit(0.0)
        self._progress_status = "运行中"
        self.progressStatusChanged.emit(self._progress_status)

        self._worker.send_interval_min = self._send_interval_min
        self._worker.send_interval_max = self._send_interval_max
        self._worker.start()

    @Slot()
    def pause_sending(self):
        if self._worker:
            self._worker.pause()
            self._prev_phase_for_pause = self._phase
            self._set_phase(PHASE_PAUSED)
            self._progress_status = "已暂停"
            self.progressStatusChanged.emit(self._progress_status)

    @Slot()
    def resume_sending(self):
        if self._worker:
            self._worker.resume()
            self._set_phase(PHASE_RUNNING)
            self._progress_status = "运行中"
            self.progressStatusChanged.emit(self._progress_status)

    @Slot()
    def stop_sending(self):
        if self._worker:
            self._worker.request_stop()
        self._set_phase(PHASE_DONE)
        self._progress_status = "已停止"
        self.progressStatusChanged.emit(self._progress_status)
        self._set_inputs_enabled(True)

    @Slot()
    def reset(self):
        """重置所有状态到 idle。"""
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
        self._worker = None
        self._fatal_error = ""
        self._file_paths = []
        self._file_path_model.removeRows(0, self._file_path_model.rowCount())
        self._file_sizes = []
        self._progress_value = 0.0
        self._progress_status = "待开始"
        self._current_friend = ""
        self._set_phase(PHASE_IDLE)
        self._set_inputs_enabled(True)
        self.progressValueChanged.emit(0.0)
        self.progressStatusChanged.emit("待开始")
        self.currentFriendChanged.emit("")
        self.fatalErrorChanged.emit("")
        self.filePathsChanged.emit([])
        self.fileSizesChanged.emit([])
        self._update_preview()

    @Slot(int, result=str)
    def get_file_size_at(self, index: int) -> str:
        """安全地获取指定索引的文件大小，避免 QML 异步访问越界或类型转换问题。"""
        if 0 <= index < len(self._file_sizes):
            return self._file_sizes[index]
        return ""

    @Slot(str)
    def add_file_path(self, file_url: str):
        """从 QML FileDialog 接收文件路径（file:/// 前缀需移除）。"""
        path = file_url.replace("file:///", "")
        # Windows 下的路径规范化
        if sys.platform == "win32":
            path = path.lstrip("/")
        if path and path not in self._file_paths:
            self._file_paths.append(path)
            row = self._file_path_model.rowCount()
            self._file_path_model.insertRow(row)
            self._file_path_model.setData(self._file_path_model.index(row), path)
            try:
                size = os.path.getsize(path)
                self._file_sizes.append(self._format_size(size))
            except OSError:
                self._file_sizes.append("")
            self.filePathsChanged.emit(list(self._file_paths))
            self.fileSizesChanged.emit(list(self._file_sizes))
            self._update_preview()

    @Slot(int)
    def remove_file_at(self, index: int):
        if 0 <= index < len(self._file_paths):
            self._file_paths.pop(index)
            self._file_path_model.removeRow(index)
            if 0 <= index < len(self._file_sizes):
                self._file_sizes.pop(index)
            self.filePathsChanged.emit(list(self._file_paths))
            self.fileSizesChanged.emit(list(self._file_sizes))
            self._update_preview()

    @Slot(str, str, result=bool)
    def export_logs(self, file_url: str, log_content: str) -> bool:
        """安全地将格式化的日志写入到本地文本文件。"""
        try:
            path = file_url.replace("file:///", "")
            if sys.platform == "win32":
                path = path.lstrip("/")
            
            # Ensure the directory exists
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(log_content)
            return True
        except Exception as e:
            print(f"Error exporting logs: {e}", file=sys.stderr)
            return False

    @Slot(str)
    def open_file(self, file_url: str):
        """打开指定的文件。"""
        try:
            path = file_url.replace("file:///", "")
            if sys.platform == "win32":
                path = path.lstrip("/")
                os.startfile(path)
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.call([opener, path])
        except Exception as e:
            print(f"Error opening file: {e}", file=sys.stderr)

    @Slot(str)
    def open_file_folder(self, file_url: str):
        """打开文件所在的目录，并在 Windows 下尽量选中该文件。"""
        try:
            path = file_url.replace("file:///", "")
            if sys.platform == "win32":
                path = path.lstrip("/")
                windows_path = os.path.normpath(path)
                import subprocess
                subprocess.run(f'explorer /select,"{windows_path}"', shell=True)
            else:
                folder = os.path.dirname(path)
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.call([opener, folder])
        except Exception as e:
            print(f"Error opening file folder: {e}", file=sys.stderr)

    @Slot(str)
    def copy_to_clipboard(self, text: str):
        """将文本复制到系统剪贴板。"""
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app is not None:
                clipboard = QGuiApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(text)
                    return
            print("Clipboard not available: QGuiApplication is not fully initialized", file=sys.stderr)
        except Exception as e:
            print(f"Error copying to clipboard: {e}", file=sys.stderr)

    # ═══════════════════════════════════════
    #  内部 slot（接收 worker 信号）
    # ═══════════════════════════════════════

    @Slot(int, int)
    def _on_progress_updated(self, done: int, total: int):
        pct = (done / total * 100) if total else 0
        self._progress_value = pct
        self.progressValueChanged.emit(pct)

        phase_labels = {
            PHASE_IDLE: "待开始",
            PHASE_RUNNING: "运行中",
            PHASE_PAUSED: "已暂停",
            PHASE_DONE: "已结束",
        }
        status = phase_labels.get(self._phase, self._phase)
        if total:
            status += f"  进度 {done}/{total}"
        self._progress_status = status
        self.progressStatusChanged.emit(status)

    @Slot(str)
    def _on_current_friend(self, friend: str):
        self._current_friend = friend
        self.currentFriendChanged.emit(friend)

    @Slot(str, str, str, str)
    def _on_log_entry(self, friend: str, greeting: str, status: str, detail: str):
        if status != "success":
            self._send_error_count += 1
        self.logEntryAdded.emit(friend, greeting, status, detail)

    @Slot(str)
    def _on_fatal_error(self, error: str):
        self._send_fatal_error_seen = True
        self._fatal_error = error
        self.fatalErrorChanged.emit(error)

    @Slot()
    def _on_send_finished(self):
        was_running = self._phase in (PHASE_RUNNING, PHASE_PAUSED)
        if was_running:
            self._set_phase(PHASE_DONE)
        self._set_inputs_enabled(True)
        self._progress_status = "已结束"
        self.progressStatusChanged.emit(self._progress_status)
        if was_running:
            if self._send_fatal_error_seen:
                self.showToast.emit("发送任务失败！", "error")
            elif self._send_error_count:
                self.showToast.emit("发送任务完成，但存在失败项！", "error")
            else:
                self.showToast.emit("发送任务完成！", "success")

    def _set_inputs_enabled(self, enabled: bool):
        self._inputs_enabled = enabled
        self.inputsEnabledChanged.emit(enabled)

    @Slot(int, bool)
    def updateThemeMode(self, hwnd: int, is_dark: bool):
        """兼容旧 QML 调用：按当前持久化玻璃设置刷新窗口视觉。"""
        self.updateWindowVisuals(hwnd, is_dark, self._glass_enabled, self._glass_opacity)

    @Slot(int, bool, bool, int)
    def updateWindowVisuals(self, hwnd: int, is_dark: bool, glass_enabled: bool, glass_opacity: int):
        """同步 QML 主题与窗口级毛玻璃设置到原生 Windows DWM。"""
        self.glassEnabled = glass_enabled
        self.glassOpacity = glass_opacity
        win32_helper.set_immersive_dark_mode(hwnd, is_dark)
        win32_helper.apply_window_backdrop(
            hwnd,
            is_dark,
            self._glass_enabled,
            self._glass_opacity,
        )

    @Slot()
    def shutdown(self):
        """Stop the v0.3 Agent and any legacy worker during GUI shutdown."""
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
        self._agent_controller.close()
