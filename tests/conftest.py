# -*- coding: utf-8 -*-
"""共享 fixtures 与测试工具"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.backend import BackendController
from app.constants import PHASE_IDLE, PHASE_RUNNING, PHASE_PAUSED, PHASE_DONE


class FakeSenderWorker(QObject):
    progress_updated = Signal(int, int)
    current_friend = Signal(str)
    log_entry = Signal(str, str, str, str)
    fatal_error = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.friends = []
        self.message_template = ""
        self.file_paths = []
        self.send_interval_min = 2.0
        self.send_interval_max = 3.0
        self.pause_called = False
        self.resume_called = False
        self.stop_called = False
        self.start_called = False

    def start(self):
        self.start_called = True

    def pause(self):
        self.pause_called = True

    def resume(self):
        self.resume_called = True

    def request_stop(self):
        self.stop_called = True

    def isRunning(self):
        return False

    def wait(self, timeout=0):
        return True


@pytest.fixture(scope="session")
def qapp():
    """确保 Qt Application 全局唯一"""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    yield app


@pytest.fixture
def backend(qapp):
    """创建独立的 BackendController 实例，测试结束后自动清理"""
    ctrl = BackendController(version="0.0.0-test", worker_factory=FakeSenderWorker)
    yield ctrl
    # 清理：停止可能还在运行的 worker，防止 Qt 对象销毁时崩溃
    if ctrl._worker is not None and ctrl._worker.isRunning():
        ctrl._worker.request_stop()
        ctrl._worker.wait(3000)
    ctrl._worker = None


@pytest.fixture
def mock_worker():
    """返回一个可复用的 SenderWorker mock"""
    worker = MagicMock()
    worker.isRunning.return_value = False
    worker.progress_updated = MagicMock()
    worker.current_friend = MagicMock()
    worker.log_entry = MagicMock()
    worker.fatal_error = MagicMock()
    worker.finished = MagicMock()
    return worker


@pytest.fixture
def mock_wechat_client():
    """返回一个可复用的 WeChatClient mock"""
    wx = MagicMock()
    wx.chat_window = MagicMock()
    wx.chat_window.send_to = MagicMock(return_value=True)
    wx.chat_window.send_message_and_file_to = MagicMock(return_value=True)
    wx.disconnect = MagicMock()
    return wx
