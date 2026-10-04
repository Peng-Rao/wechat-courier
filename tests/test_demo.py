# -*- coding: utf-8 -*-
"""演示模式测试"""

from unittest.mock import patch

from app.demo import is_demo_mode, MockWeChatClient


class TestDemoMode:
    def test_is_demo_mode_returns_bool(self):
        # 返回值取决于 src.WeChatClient 是否可导入
        result = is_demo_mode()
        assert isinstance(result, bool)

    @patch("app.demo._DEMO_MODE", True)
    def test_is_demo_mode_true_when_flag_set(self):
        assert is_demo_mode() is True

    @patch("app.demo._DEMO_MODE", False)
    def test_is_demo_mode_false_when_flag_unset(self):
        assert is_demo_mode() is False


class TestMockWeChatClient:
    def test_mock_client_has_chat_window(self):
        wx = MockWeChatClient(auto_connect=False)
        assert hasattr(wx, "chat_window")

    def test_mock_send_to(self):
        wx = MockWeChatClient(auto_connect=False)
        # 不应抛出异常
        wx.chat_window.send_to("Alice", "Hello")



    def test_mock_disconnect(self):
        wx = MockWeChatClient(auto_connect=False)
        wx.disconnect()

    def test_mock_context_manager(self):
        wx = MockWeChatClient(auto_connect=False)
        with wx as client:
            assert client is wx
