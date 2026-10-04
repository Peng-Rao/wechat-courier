# -*- coding: utf-8 -*-
"""发送工作线程 — 在独立 QThread 中执行批量发送"""

from PySide6.QtCore import QThread, Signal

from .demo import WeChatClient, is_demo_mode
from .models import FriendItem, SendResult, extract_greeting_name


class SenderWorker(QThread):
    """在独立线程中执行批量发送，通过 Signal 与主线程通信。"""

    # ── 信号 ──
    progress_updated = Signal(int, int)       # done, total
    current_friend = Signal(str)              # 正在处理的好友名
    log_entry = Signal(str, str, str, str)    # friend, greeting, status, detail
    fatal_error = Signal(str)                 # 致命错误
    finished = Signal()                       # 发送完成（无论成功/失败）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pause_flag = False
        self._stop_flag = False

        # 输入快照（由 BackendController 在启动前设置）
        self.friends: list[str] = []
        self.message_template: str = ""
        self.file_paths: list[str] = []
        self.send_interval_min: float = 2.0
        self.send_interval_max: float = 3.0

    # ── 控制 API（主线程调用） ──

    def pause(self):
        self._pause_flag = True

    def resume(self):
        self._pause_flag = False

    def request_stop(self):
        self._stop_flag = True
        self.resume()

    # ── QThread 入口 ──

    def run(self):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            self._run_inner()
        finally:
            pythoncom.CoUninitialize()
            self.finished.emit()

    def _run_inner(self):
        total = len(self.friends)

        # 1. 连接微信
        try:
            if is_demo_mode():
                wx = WeChatClient(auto_connect=True)
            else:
                wx = WeChatClient(auto_connect=True)
        except Exception as e:
            self.fatal_error.emit(f"微信客户端连接失败: {e}。请确认微信已登录、未被其他程序占用。")
            return

        # 逐好友发送
        for idx, friend in enumerate(self.friends):
            # 检查停止
            if self._stop_flag:
                break

            # 检查暂停（忙等待，100ms 间隔）
            while self._pause_flag and not self._stop_flag:
                self.msleep(100)

            if self._stop_flag:
                break

            # 随机延迟，支持高频轮询以便即时响应停止/暂停
            if idx > 0:
                import random
                sleep_dur = random.uniform(self.send_interval_min, self.send_interval_max)
                slept = 0.0
                while slept < sleep_dur and not self._stop_flag:
                    while self._pause_flag and not self._stop_flag:
                        self.msleep(100)
                    if self._stop_flag:
                        break
                    self.msleep(100)
                    slept += 0.1

            if self._stop_flag:
                break

            # 更新进度
            self.progress_updated.emit(idx, total)
            self.current_friend.emit(friend)

            # 处理单个好友
            result = self._process_one_friend(wx, friend)
            self.log_entry.emit(
                result.friend, result.greeting, result.status, result.detail,
            )

        # 发射最终进度
        final_done = min(idx + 1, total) if not self._stop_flag else idx
        self.progress_updated.emit(final_done, total)

        # 4. 清理
        try:
            wx.disconnect()
        except Exception:
            pass

    def _process_one_friend(self, wx, friend: str) -> SendResult:
        greeting = extract_greeting_name(friend)
        try:
            final_message = self.message_template.format(name=greeting)
        except (KeyError, ValueError):
            final_message = self.message_template

        try:
            if self.file_paths:
                ok = wx.chat_window.send_message_and_file_to(
                    friend, final_message, self.file_paths, target_type="contact",
                )
                if ok is not True:
                    raise RuntimeError("发送失败（详见日志）")
                detail = f"文件 {len(self.file_paths)} 个（每人重复上传）"
            else:
                ok = wx.chat_window.send_to(friend, final_message, target_type="contact")
                if ok is not True:
                    raise RuntimeError("发送失败（详见日志）")
                detail = "仅文本"

            return SendResult(friend, greeting, "success", detail)
        except Exception as e:
            return SendResult(friend, greeting, "error", f"错误：{e}")
