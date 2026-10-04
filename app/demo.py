# -*- coding: utf-8 -*-
"""Demo-mode fallback for environments where WeChat automation cannot load."""

import os
import sys
import time
import traceback

_DEMO_MODE = False


class MockChatWindow:
    def send_to(self, *a, **kw):
        time.sleep(0.3)
        return True

    def send_file_to(self, *a, **kw):
        time.sleep(0.3)
        return True

    def send_message_and_file_to(self, *a, **kw):
        time.sleep(0.3)
        return True


class MockWeChatClient:
    def __init__(self, auto_connect=False):
        self.chat_window = MockChatWindow()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def disconnect(self):
        pass


def _demo_mode_log_paths():
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp_dir:
        yield os.path.join(temp_dir, "demo_mode_reason.log")

    home_dir = os.path.expanduser("~")
    if home_dir:
        yield os.path.join(home_dir, "demo_mode_reason.log")

    app_dir = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv else __file__)),
    )
    yield os.path.join(app_dir, "..", "demo_mode_reason.log")


def _write_import_failure(exc: BaseException) -> None:
    for path in _demo_mode_log_paths():
        try:
            with open(path, "w", encoding="utf-8") as log_file:
                log_file.write(f"WeChatClient import failed: {exc!r}\n\n")
                traceback.print_exc(file=log_file)
        except Exception:
            pass


def _must_raise_import_failure() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


try:
    from src.client import WeChatClient  # noqa: F401
except Exception as _exc:
    _write_import_failure(_exc)
    if _must_raise_import_failure():
        raise

    _DEMO_MODE = True
    WeChatClient = MockWeChatClient  # type: ignore


def is_demo_mode() -> bool:
    return _DEMO_MODE
