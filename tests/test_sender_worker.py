# -*- coding: utf-8 -*-
"""SenderWorker 单元测试"""

from unittest.mock import MagicMock, patch

import pytest

from app.sender_worker import SenderWorker
from app.models import SendResult


@pytest.fixture
def worker():
    """创建一个未启动的 SenderWorker"""
    w = SenderWorker()
    w.friends = ["Alice", "Bob"]
    w.message_template = "Hello {name}"
    w.file_paths = []
    return w


class TestWorkerControl:
    def test_pause_sets_flag(self, worker):
        worker.pause()
        assert worker._pause_flag is True

    def test_resume_clears_flag(self, worker):
        worker.pause()
        worker.resume()
        assert worker._pause_flag is False

    def test_request_stop_sets_flag(self, worker):
        worker.request_stop()
        assert worker._stop_flag is True
        assert worker._pause_flag is False  # stop 同时解除暂停


class TestProcessOneFriendTextOnly:
    def test_success_text_only(self, worker, mock_wechat_client):
        result = worker._process_one_friend(mock_wechat_client, "王小明")
        assert isinstance(result, SendResult)
        assert result.friend == "王小明"
        assert result.greeting == "小明"
        assert result.status == "success"
        assert "仅文本" in result.detail
        mock_wechat_client.chat_window.send_to.assert_called_once_with(
            "王小明", "Hello 小明", target_type="contact"
        )

    def test_success_without_placeholder(self, worker, mock_wechat_client):
        worker.message_template = "Fixed message"
        result = worker._process_one_friend(mock_wechat_client, "Alice")
        assert result.status == "success"
        mock_wechat_client.chat_window.send_to.assert_called_once_with(
            "Alice", "Fixed message", target_type="contact"
        )

    def test_invalid_placeholder_fallback(self, worker, mock_wechat_client):
        worker.message_template = "Hi {invalid}"
        result = worker._process_one_friend(mock_wechat_client, "Alice")
        assert result.status == "success"
        # 应原样发送模板，不崩溃
        mock_wechat_client.chat_window.send_to.assert_called_once_with(
            "Alice", "Hi {invalid}", target_type="contact"
        )

    def test_exception_returns_error(self, worker, mock_wechat_client):
        mock_wechat_client.chat_window.send_to.side_effect = RuntimeError("窗口未找到")
        result = worker._process_one_friend(mock_wechat_client, "Alice")
        assert result.status == "error"
        assert "窗口未找到" in result.detail

    def test_false_return_is_reported_as_error(self, worker, mock_wechat_client):
        mock_wechat_client.chat_window.send_to.return_value = False

        result = worker._process_one_friend(mock_wechat_client, "Alice")

        assert result.status == "error"
        assert "发送失败" in result.detail


class TestProcessOneFriendWithFiles:
    def test_success_with_files(self, worker, mock_wechat_client):
        worker.file_paths = ["C:/test.pdf"]
        result = worker._process_one_friend(mock_wechat_client, "Alice")
        assert result.status == "success"
        assert "每人重复上传" in result.detail
        mock_wechat_client.chat_window.send_message_and_file_to.assert_called_once()

    def test_file_send_false_return_is_reported_as_error(self, worker, mock_wechat_client):
        worker.file_paths = ["C:/test.pdf"]
        mock_wechat_client.chat_window.send_message_and_file_to.return_value = False

        result = worker._process_one_friend(mock_wechat_client, "Alice")

        assert result.status == "error"
        assert "发送失败" in result.detail


class TestWorkerSignals:
    def test_progress_updated_emitted(self, worker, qtbot):
        with qtbot.waitSignal(worker.progress_updated, timeout=1000):
            worker.progress_updated.emit(1, 10)

    def test_current_friend_emitted(self, worker, qtbot):
        with qtbot.waitSignal(worker.current_friend, timeout=1000):
            worker.current_friend.emit("Alice")

    def test_log_entry_emitted(self, worker, qtbot):
        with qtbot.waitSignal(worker.log_entry, timeout=1000):
            worker.log_entry.emit("Alice", "Alice", "success", "仅文本")

    def test_fatal_error_emitted(self, worker, qtbot):
        with qtbot.waitSignal(worker.fatal_error, timeout=1000):
            worker.fatal_error.emit("连接失败")

    def test_finished_emitted(self, worker, qtbot):
        with qtbot.waitSignal(worker.finished, timeout=1000):
            worker.finished.emit()
