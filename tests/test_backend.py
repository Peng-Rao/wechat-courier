# -*- coding: utf-8 -*-
"""BackendController 单元测试"""

import pytest
from PySide6.QtCore import QSettings

from app.backend import BackendController
from app.constants import PHASE_IDLE, PHASE_RUNNING, PHASE_PAUSED, PHASE_DONE


class TestBackendPhase:
    def test_initial_phase_is_idle(self, backend):
        assert backend.phase == PHASE_IDLE

    def test_set_phase_emits_signal(self, backend, qtbot):
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000) as blocker:
            backend.phase = PHASE_RUNNING
        assert blocker.args == [PHASE_RUNNING]

    def test_set_same_phase_no_emit(self, backend, qtbot):
        backend.phase = PHASE_RUNNING
        with qtbot.assertNotEmitted(backend.phaseChanged, wait=200):
            backend.phase = PHASE_RUNNING


class TestBackendProperties:
    def test_friend_list_text_notify(self, backend, qtbot):
        with qtbot.waitSignal(backend.friendListTextChanged, timeout=1000):
            backend.friendListText = "Alice\nBob"

    def test_template_text_notify(self, backend, qtbot):
        with qtbot.waitSignal(backend.templateTextChanged, timeout=1000):
            backend.templateText = "Hi {name}"


    def test_file_paths_notify_on_add(self, backend, qtbot):
        with qtbot.waitSignal(backend.filePathsChanged, timeout=1000):
            backend.add_file_path("file:///C:/test/doc.pdf")


class TestBackendInputs:
    def test_friend_list_text_triggers_preview(self, backend, qtbot):
        with qtbot.waitSignal(backend.previewMessageChanged, timeout=1000):
            backend.friendListText = "Alice\nBob"
            backend.templateText = "{name}, hi"

    def test_empty_input_no_preview_crash(self, backend):
        # 先设置非空值触发预览，再清空
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.friendListText = ""
        backend.templateText = ""
        assert backend.previewFriend == ""
        assert backend.previewMessage == "请在左侧输入名单和消息模板即可在此预览效果"

    def test_preview_with_placeholder(self, backend):
        backend.friendListText = "王小明"
        backend.templateText = "{name}，你好！"
        assert backend.previewGreeting == "小明"
        assert backend.previewMessage == "小明，你好！"

    def test_preview_without_placeholder(self, backend):
        backend.friendListText = "王小明"
        backend.templateText = "大家好"
        assert backend.previewMessage == "大家好"

    def test_preview_invalid_placeholder(self, backend):
        backend.friendListText = "王小明"
        backend.templateText = "{invalid}"
        assert "格式有误" in backend.previewMessage

    def test_preview_only_files_no_template(self, backend):
        backend.friendListText = "王小明"
        backend.templateText = ""
        backend.add_file_path("file:///C:/test/file1.png")
        assert backend.previewFriend == "王小明"
        assert backend.previewMessage == ""
        assert backend.previewFileNames == ["file1.png"]
        assert backend.previewFileCount == 1

    def test_preview_index_switching(self, backend):
        backend.friendListText = "Alice\nBob\nCharlie"
        backend.templateText = "Hi {name}"
        assert backend.previewIndex == 0
        assert backend.previewFriend == "Alice"
        assert backend.previewMessage == "Hi Alice"

        backend.previewIndex = 1
        assert backend.previewFriend == "Bob"
        assert backend.previewMessage == "Hi Bob"

        backend.previewIndex = 2
        assert backend.previewFriend == "Charlie"
        assert backend.previewMessage == "Hi Charlie"

        # Out of bounds clamping check
        backend.previewIndex = 10
        assert backend.previewIndex == 2
        assert backend.previewFriend == "Charlie"

        # Shrinking list clamps index
        backend.friendListText = "Alice"
        assert backend.previewIndex == 0
        assert backend.previewFriend == "Alice"

    def test_friend_list_text_clears_fatal_error(self, backend, qtbot):
        backend.friendListText = ""
        backend.templateText = ""
        backend.start_sending()
        assert backend.fatalError != ""
        with qtbot.waitSignal(backend.fatalErrorChanged, timeout=1000):
            backend.friendListText = "Alice"
        assert backend.fatalError == ""

    def test_template_text_clears_fatal_error(self, backend, qtbot):
        backend.friendListText = ""
        backend.templateText = ""
        backend.start_sending()
        assert backend.fatalError != ""
        with qtbot.waitSignal(backend.fatalErrorChanged, timeout=1000):
            backend.templateText = "Hello"
        assert backend.fatalError == ""


class TestBackendStartValidation:
    def test_start_with_empty_friends(self, backend):
        backend.friendListText = ""
        backend.templateText = "hello"
        backend.start_sending()
        assert backend.phase == PHASE_IDLE
        assert "不能为空" in backend.fatalError

    def test_start_with_empty_template(self, backend):
        backend.friendListText = "Alice"
        backend.templateText = ""
        backend.start_sending()
        assert backend.phase == PHASE_IDLE
        assert "不能为空" in backend.fatalError

    def test_start_clears_previous_fatal_error(self, backend):
        backend.friendListText = ""
        backend.templateText = ""
        backend.start_sending()
        assert backend.fatalError != ""
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        # 致命错误应在成功启动后被清除
        assert backend.fatalError == ""


class TestBackendStartSending:
    def test_start_sending_transitions_to_running(self, backend, qtbot):
        backend.friendListText = "Alice\nBob"
        backend.templateText = "Hello {name}"
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000):
            backend.start_sending()
        assert backend.phase == PHASE_RUNNING
        assert backend.inputsEnabled is False
        assert backend.progressValue == 0.0

    def test_start_sending_creates_worker(self, backend):
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        assert backend._worker is not None
        assert backend._worker.friends == ["Alice"]
        assert backend._worker.message_template == "Hi"


class TestBackendPauseResume:
    def test_pause_transitions_to_paused(self, backend, qtbot):
        backend.friendListText = "Alice\nBob"
        backend.templateText = "Hi"
        backend.start_sending()
        worker = backend._worker
        worker.pause = lambda: None
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000):
            backend.pause_sending()
        assert backend.phase == PHASE_PAUSED
        assert backend.progressStatus == "已暂停"

    def test_resume_transitions_to_running(self, backend, qtbot):
        backend.friendListText = "Alice\nBob"
        backend.templateText = "Hi"
        backend.start_sending()
        worker = backend._worker
        worker.pause = lambda: None
        worker.resume = lambda: None
        backend.pause_sending()
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000):
            backend.resume_sending()
        assert backend.phase == PHASE_RUNNING
        assert backend.progressStatus == "运行中"


class TestBackendStop:
    def test_stop_transitions_to_done(self, backend, qtbot):
        backend.friendListText = "Alice\nBob"
        backend.templateText = "Hi"
        backend.start_sending()
        worker = backend._worker
        worker.request_stop = lambda: None
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000):
            backend.stop_sending()
        assert backend.phase == PHASE_DONE
        assert backend.inputsEnabled is True


class TestBackendFileManagement:
    def test_add_file_path(self, backend):
        backend.add_file_path("file:///C:/Users/test/hello.pdf")
        assert len(backend.filePaths) == 1
        assert backend.filePaths[0] == "C:/Users/test/hello.pdf"
        assert len(backend.fileSizes) == 1

    def test_add_file_path_windows(self, backend):
        """Windows 路径应去掉 file:/// 前缀和首字母斜杠"""
        backend.add_file_path("file:///D:/docs/report.pdf")
        assert backend.filePaths[0] == "D:/docs/report.pdf"

    def test_add_duplicate_file(self, backend):
        backend.add_file_path("file:///C:/test/doc.pdf")
        backend.add_file_path("file:///C:/test/doc.pdf")
        assert len(backend.filePaths) == 1

    def test_remove_file(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        backend.add_file_path("file:///C:/test/b.pdf")
        backend.remove_file_at(0)
        assert len(backend.filePaths) == 1
        assert backend.filePaths[0] == "C:/test/b.pdf"
        assert len(backend.fileSizes) == 1

    def test_remove_invalid_index(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        backend.remove_file_at(99)
        assert len(backend.filePaths) == 1

    def test_get_file_size_at(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        # 由于路径不存在，大小应该获取返回默认的空字符串，但位置有效
        assert backend.get_file_size_at(0) == ""
        # 越界获取应安全返回空字符串
        assert backend.get_file_size_at(99) == ""
        assert backend.get_file_size_at(-1) == ""

    def test_reset_clears_files(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        backend.add_file_path("file:///C:/test/b.pdf")
        backend.reset()
        assert len(backend.filePaths) == 0
        assert len(backend.fileSizes) == 0

    def test_file_path_model_is_string_list_model(self, backend):
        from PySide6.QtCore import QStringListModel
        assert isinstance(backend.filePathModel, QStringListModel)

    def test_file_path_model_row_count(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        backend.add_file_path("file:///C:/test/b.pdf")
        assert backend.filePathModel.rowCount() == 2

    def test_file_path_model_remove_row(self, backend):
        backend.add_file_path("file:///C:/test/a.pdf")
        backend.add_file_path("file:///C:/test/b.pdf")
        backend.remove_file_at(0)
        assert backend.filePathModel.rowCount() == 1
        assert backend.filePathModel.data(backend.filePathModel.index(0)) == "C:/test/b.pdf"


class TestBackendReset:
    def test_reset_restores_idle(self, backend):
        backend.friendListText = "Alice"
        backend.templateText = "Hi {name}"
        backend.phase = PHASE_RUNNING
        backend.reset()
        assert backend.phase == PHASE_IDLE
        assert backend.fatalError == ""
        assert backend.inputsEnabled is True
        assert backend.progressValue == 0.0

    def test_reset_stops_running_worker(self, backend):
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        assert backend._worker is not None
        backend.reset()
        assert backend._worker is None


class TestBackendSignals:
    def test_log_entry_added_signal(self, backend, qtbot):
        with qtbot.waitSignal(backend.logEntryAdded, timeout=1000):
            backend._on_log_entry("Alice", "Alice", "success", "仅文本")

    def test_fatal_error_changed_signal(self, backend, qtbot):
        with qtbot.waitSignal(backend.fatalErrorChanged, timeout=1000):
            backend._on_fatal_error("连接失败")

    def test_progress_updated_signal(self, backend, qtbot):
        backend.phase = PHASE_RUNNING
        with qtbot.waitSignal(backend.progressValueChanged, timeout=1000):
            backend._on_progress_updated(3, 10)
        assert backend.progressValue == 30.0

    def test_current_friend_signal(self, backend, qtbot):
        with qtbot.waitSignal(backend.currentFriendChanged, timeout=1000):
            backend._on_current_friend("Alice")
        assert backend.currentFriend == "Alice"

    def test_send_finished_transitions_to_done(self, backend, qtbot):
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        with qtbot.waitSignal(backend.phaseChanged, timeout=1000):
            backend._on_send_finished()
        assert backend.phase == PHASE_DONE
        assert backend.inputsEnabled is True

    def test_send_finished_after_error_log_shows_error_toast(self, backend, qtbot):
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        backend._on_log_entry("Alice", "Alice", "error", "发送失败")

        with qtbot.waitSignal(backend.showToast, timeout=1000) as blocker:
            backend._on_send_finished()

        assert blocker.args == ["发送任务完成，但存在失败项！", "error"]

    def test_send_finished_after_fatal_error_shows_error_toast(self, backend, qtbot):
        backend.friendListText = "Alice"
        backend.templateText = "Hi"
        backend.start_sending()
        backend._on_fatal_error("连接失败")

        with qtbot.waitSignal(backend.showToast, timeout=1000) as blocker:
            backend._on_send_finished()

        assert blocker.args == ["发送任务失败！", "error"]


class TestBackendPhase3:
    def test_send_intervals(self, backend, qtbot):
        # Default values
        assert backend.sendIntervalMin == 2.0
        assert backend.sendIntervalMax == 3.0

        # Change min interval
        with qtbot.waitSignal(backend.sendIntervalMinChanged, timeout=1000) as blocker:
            backend.sendIntervalMin = 5.0
        assert backend.sendIntervalMin == 5.0
        assert blocker.args == [5.0]

        # Change max interval
        with qtbot.waitSignal(backend.sendIntervalMaxChanged, timeout=1000) as blocker:
            backend.sendIntervalMax = 10.0
        assert backend.sendIntervalMax == 10.0
        assert blocker.args == [10.0]

    def test_export_logs_success(self, backend, tmp_path):
        log_file = tmp_path / "test_export_logs.txt"
        log_url = f"file:///{log_file.as_posix()}"
        content = "test log content string"
        
        success = backend.export_logs(log_url, content)
        assert success is True
        assert log_file.exists()
        assert log_file.read_text(encoding="utf-8") == content

    def test_export_logs_invalid_path_returns_false(self, backend):
        # Using a completely invalid path that cannot be written to
        invalid_url = "file:///invalid_drive_letter_xyz:/nonexistent/dir/file.txt"
        success = backend.export_logs(invalid_url, "content")
        assert success is False

    def test_open_file_safely(self, backend, monkeypatch):
        import sys
        opened_paths = []
        if sys.platform == "win32":
            import os
            monkeypatch.setattr(os, "startfile", lambda path: opened_paths.append(path))
        else:
            import subprocess
            monkeypatch.setattr(subprocess, "call", lambda args: opened_paths.append(args[1]))

        backend.open_file("file:///d:/some/path/file.txt")
        assert len(opened_paths) == 1
        assert "file.txt" in opened_paths[0].replace("\\", "/")

    def test_open_file_folder_safely(self, backend, monkeypatch):
        import sys
        run_args = []
        if sys.platform == "win32":
            import subprocess
            monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: run_args.append(cmd))
        else:
            import subprocess
            monkeypatch.setattr(subprocess, "call", lambda args: run_args.append(args[1]))

        backend.open_file_folder("file:///d:/some/path/file.txt")
        assert len(run_args) == 1

    def test_copy_to_clipboard(self, backend, monkeypatch):
        # Mock QGuiApplication.clipboard to prevent native access violation in headless environments
        from PySide6.QtGui import QGuiApplication
        copied_text = []
        class MockClipboard:
            def setText(self, text):
                copied_text.append(text)
        
        monkeypatch.setattr(QGuiApplication, "clipboard", lambda: MockClipboard())
        backend.copy_to_clipboard("test clip content")
        assert copied_text == ["test clip content"]


class TestBackendWindowVisualSettings:
    def _settings(self, tmp_path):
        return QSettings(str(tmp_path / "visual.ini"), QSettings.IniFormat)

    def test_glass_defaults_when_settings_are_empty(self, qapp, tmp_path):
        backend = BackendController(version="0.0.0-test", settings=self._settings(tmp_path))

        assert backend.glassEnabled is True
        assert backend.glassOpacity == 72

    def test_theme_mode_is_loaded_from_previous_session(self, qapp, tmp_path):
        settings = self._settings(tmp_path)
        settings.setValue("isDark", True)
        settings.sync()

        backend = BackendController(version="0.0.0-test", settings=settings)

        assert backend.isDark is True

    def test_theme_mode_is_persisted_and_emits_signal(self, qapp, tmp_path, qtbot):
        settings = self._settings(tmp_path)
        backend = BackendController(version="0.0.0-test", settings=settings)

        with qtbot.waitSignal(backend.isDarkChanged, timeout=1000) as blocker:
            backend.isDark = True

        assert blocker.args == [True]
        assert settings.value("isDark", False, type=bool) is True

    def test_glass_enabled_is_persisted_and_emits_signal(self, qapp, tmp_path, qtbot):
        settings = self._settings(tmp_path)
        backend = BackendController(version="0.0.0-test", settings=settings)

        with qtbot.waitSignal(backend.glassEnabledChanged, timeout=1000) as blocker:
            backend.glassEnabled = False

        assert blocker.args == [False]
        assert settings.value("visual/glassEnabled", True, type=bool) is False

    def test_glass_opacity_is_clamped_persisted_and_emits_signal(self, qapp, tmp_path, qtbot):
        settings = self._settings(tmp_path)
        backend = BackendController(version="0.0.0-test", settings=settings)

        with qtbot.waitSignal(backend.glassOpacityChanged, timeout=1000) as low_blocker:
            backend.glassOpacity = 10
        assert low_blocker.args == [45]
        assert backend.glassOpacity == 45
        assert settings.value("visual/glassOpacity", 0, type=int) == 45

        with qtbot.waitSignal(backend.glassOpacityChanged, timeout=1000) as high_blocker:
            backend.glassOpacity = 95
        assert high_blocker.args == [90]
        assert backend.glassOpacity == 90
        assert settings.value("visual/glassOpacity", 0, type=int) == 90

    def test_glass_settings_are_loaded_from_previous_session(self, qapp, tmp_path):
        settings = self._settings(tmp_path)
        settings.setValue("visual/glassEnabled", False)
        settings.setValue("visual/glassOpacity", 83)
        settings.sync()

        backend = BackendController(version="0.0.0-test", settings=settings)

        assert backend.glassEnabled is False
        assert backend.glassOpacity == 83

    def test_update_theme_mode_remains_backward_compatible(self, backend, monkeypatch):
        calls = []

        def fake_update(hwnd, is_dark, glass_enabled, glass_opacity):
            calls.append((hwnd, is_dark, glass_enabled, glass_opacity))
            return True

        monkeypatch.setattr("app.backend.win32_helper.apply_window_backdrop", fake_update)

        backend.glassEnabled = False
        backend.glassOpacity = 66
        backend.updateThemeMode(1234, True)

        assert calls == [(1234, True, False, 66)]
