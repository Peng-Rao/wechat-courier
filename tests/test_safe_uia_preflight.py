from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.diagnostics import UiaDiagnostics
from app.agent.native_driver import SearchCandidate
from tools import safe_uia_preflight
from tools.safe_uia_preflight import (
    PreflightError,
    close_friend_form,
    parse_args,
    run_preflight,
)


class FakeMessageDriver:
    def __init__(self):
        self.closed = False
        self.selected = None

    def bind_window(self):
        return {
            "connected": True,
            "hwnd": 101,
            "pid": 202,
            "version": "4.1.13.65",
            "supported": True,
        }

    def ensure_search_ready(self):
        return True

    def search_contacts(self, target):
        return [
            SearchCandidate(
                display_name="Alice Remark",
                identities=frozenset({"Alice Remark", target}),
                result_type="contact",
                automation_id="search_item_0",
                row_index=0,
                row_depth=3,
                runtime_id=(9, 8, 7),
            )
        ]

    def select_search_result(self, candidate):
        self.selected = candidate

    def current_chat_title(self):
        return "Alice Remark"

    def composer_ready(self):
        return True

    def set_composer_text(self, _text):
        raise AssertionError("message-open must not write text")

    def trigger_send(self):
        raise AssertionError("message-open must not send")

    def send_files(self, _paths):
        raise AssertionError("message-open must not send files")

    def close(self):
        self.closed = True


class RichMessageDriver(FakeMessageDriver):
    def __init__(self):
        super().__init__()
        self._root = SimpleNamespace(
            Name="微信",
            ControlTypeName="WindowControl",
            ClassName="mmui::MainWindow",
            AutomationId="main_window",
            RuntimeId=(1, 2, 3),
            BoundingRectangle=FakeRectangle(1, 2, 801, 602),
            IsOffscreen=False,
            NativeWindowHandle=101,
        )
        self.resolved_control = SimpleNamespace(
            Name="Alice Remark",
            ControlTypeName="ListItemControl",
            ClassName="mmui::SearchContentCellView",
            AutomationId="search_item_0",
            RuntimeId=(9, 8, 7),
            BoundingRectangle=FakeRectangle(30, 40, 330, 90),
            IsOffscreen=False,
            NativeWindowHandle=101,
        )

    def bind_window(self):
        result = super().bind_window()
        result["windowRestore"] = {
            "windowState": "visible",
            "restorable": False,
            "restored": True,
            "window": {
                "hwnd": 101,
                "pid": 202,
                "processPath": "C:/Program Files/Tencent/Weixin.exe",
                "windowClass": "Qt51514QWindowIcon",
                "title": "微信",
                "visible": True,
                "bounds": [0, 0, 820, 640],
            },
            "stages": [],
        }
        return result

    def _resolve_search_candidate(self, _candidate):
        return self.resolved_control


class ExpiringControl:
    def __init__(self):
        self.alive = True

    def _read(self, value):
        if not self.alive:
            raise RuntimeError("UIA_E_ELEMENTNOTAVAILABLE")
        return value

    @property
    def Name(self):
        return self._read("Alice Remark")

    @property
    def ControlTypeName(self):
        return self._read("ListItemControl")

    @property
    def ClassName(self):
        return self._read("mmui::SearchContentCellView")

    @property
    def AutomationId(self):
        return self._read("search_item_0")

    @property
    def RuntimeId(self):
        return self._read((9, 8, 7))

    @property
    def BoundingRectangle(self):
        return self._read(FakeRectangle(30, 40, 330, 90))

    @property
    def IsOffscreen(self):
        return self._read(False)

    @property
    def NativeWindowHandle(self):
        return self._read(101)


class ExpiringControlMessageDriver(RichMessageDriver):
    def __init__(self):
        super().__init__()
        self.resolved_control = ExpiringControl()

    def select_search_result(self, candidate):
        super().select_search_result(candidate)
        self.resolved_control.alive = False


def test_message_open_snapshots_search_control_before_selection_invalidates_it(
    tmp_path,
):
    driver = ExpiringControlMessageDriver()

    run_preflight(
        "message-open",
        target="Alice",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    resolved = [
        entry for entry in entries if entry["action"] == "resolve_exact_contact"
    ]
    assert len(resolved) == 1
    assert resolved[0]["control"]["class"] == "mmui::SearchContentCellView"
    assert resolved[0]["control"]["bounds"] == [30, 40, 330, 90]
    assert resolved[0]["control"]["visible"] is True
    assert entries[-1]["control"] == resolved[0]["control"]


def test_preflight_passes_only_primitive_snapshots_to_logger(tmp_path):
    driver = ExpiringControlMessageDriver()

    class SnapshotDiagnostics(UiaDiagnostics):
        def record(self, **entry):
            assert type(entry.get("control")) is dict
            json.dumps(entry)
            return super().record(**entry)

    run_preflight(
        "message-open", target="Alice",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: SnapshotDiagnostics(log_dir=tmp_path),
    )


def test_preflight_error_window_bounds_are_copied_before_logging(tmp_path):
    driver = RichMessageDriver()
    driver.search_contacts = lambda _target: []

    class SnapshotDiagnostics(UiaDiagnostics):
        def record(self, **entry):
            json.dumps(entry)
            return super().record(**entry)

    with pytest.raises(PreflightError, match="one exact contact"):
        run_preflight(
            "message-open", target="Alice",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: SnapshotDiagnostics(log_dir=tmp_path),
        )


def test_message_open_records_live_window_root_and_search_control_metadata(tmp_path):
    driver = RichMessageDriver()

    run_preflight(
        "message-open",
        target="Alice",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert entries[0]["window"]["class"] == "Qt51514QWindowIcon"
    assert entries[0]["window"]["bounds"] == [0, 0, 820, 640]
    assert entries[0]["window"]["visible"] is True
    assert entries[0]["control"]["type"] == "WindowControl"
    assert entries[0]["control"]["class"] == "mmui::MainWindow"
    assert entries[-1]["control"]["type"] == "ListItemControl"
    assert entries[-1]["control"]["class"] == "mmui::SearchContentCellView"
    assert entries[-1]["control"]["automationId"] == "search_item_0"
    assert entries[-1]["control"]["runtimeId"] == [9, 8, 7]
    assert entries[-1]["control"]["bounds"] == [30, 40, 330, 90]
    assert entries[-1]["control"]["visible"] is True
    assert entries[-1]["control"]["ownerWindow"]["hwnd"] == 101


def test_message_open_error_record_keeps_live_root_diagnostics(tmp_path):
    driver = RichMessageDriver()
    driver.search_contacts = lambda _target: []

    with pytest.raises(PreflightError, match="one exact contact"):
        run_preflight(
            "message-open",
            target="Alice",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
        )

    entry = json.loads(
        (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert entry["outcome"] == "error"
    assert entry["window"]["hwnd"] == 101
    assert entry["window"]["class"] == "mmui::MainWindow"
    assert entry["window"]["bounds"] == [1, 2, 801, 602]
    assert entry["control"]["class"] == "mmui::MainWindow"


def test_cli_exposes_only_the_three_non_destructive_modes():
    assert parse_args(["restore-only"]).mode == "restore-only"
    assert parse_args(["message-open", "--target", "Alice"]).mode == "message-open"
    friend = parse_args(
        [
            "friend-pre-submit",
            "--account",
            "wx-friend-9",
            "--greeting",
            "hello",
            "--remark",
            "note",
        ]
    )
    assert friend.mode == "friend-pre-submit"
    assert vars(friend).get("submit") is None

    with pytest.raises(SystemExit):
        parse_args(["send-helper"])
    with pytest.raises(SystemExit):
        parse_args(
            ["friend-pre-submit", "--account", "wx-friend-9", "--submit"]
        )


def test_preflight_source_has_no_destructive_driver_method_reference():
    source = Path(safe_uia_preflight.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    referenced_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert referenced_attributes.isdisjoint(
        {
            "set_composer_text",
            "trigger_send",
            "send_files",
            "submit_friend_request",
        }
    )


class FakeRestoreDriver:
    def __init__(self):
        self.bind_count = 0
        self.closed = False

    def bind_window(self):
        self.bind_count += 1
        return {
            "connected": True,
            "hwnd": 303,
            "pid": 404,
            "version": "4.1.13.65",
            "supported": True,
        }

    def close(self):
        self.closed = True


@dataclass(frozen=True)
class FakeRectangle:
    left: int
    top: int
    right: int
    bottom: int


class FakeConfirmControl:
    Name = "确定"
    ControlTypeName = "ButtonControl"
    ClassName = "mmui::TextButton"
    AutomationId = "confirm_button"
    RuntimeId = (6, 5, 4)
    BoundingRectangle = FakeRectangle(20, 30, 90, 60)
    IsOffscreen = False
    NativeWindowHandle = 505


class HiddenConfirmControl(FakeConfirmControl):
    IsOffscreen = True


class FakeFriendDriver:
    def __init__(self):
        self.events = []
        self._verify_hwnd = 505

    def bind_window(self):
        self.events.append("bind_window")
        return {
            "connected": True,
            "hwnd": 101,
            "pid": 202,
            "version": "4.1.13.65",
            "supported": True,
        }

    def open_add_friend(self):
        self.events.append("open_add_friend")
        return True

    def set_friend_account(self, account):
        self.events.append(("set_friend_account", account))
        return "value_pattern"

    def search_friend(self, account):
        self.events.append(("search_friend", account))
        return {"account": account, "control": object()}

    def profile_account(self, profile):
        return profile["account"]

    def open_friend_request(self, _profile):
        self.events.append("open_friend_request")
        return True

    def set_friend_fields(self, greeting, remark):
        self.events.append(("set_friend_fields", greeting, remark))
        return {"greeting": greeting, "remark": remark}

    def _wait_control(self, **selector):
        self.events.append(("wait_control", selector))
        return FakeConfirmControl()

    def submit_friend_request(self):
        raise AssertionError("friend-pre-submit must never submit")

    def close(self):
        self.events.append("driver_close")


VERIFY_WINDOW_CLASS = "mmui::VerifyFriendWindow"


class FakeWindowEnvironment:
    def __init__(self, windows):
        self.windows = {hwnd: dict(value) for hwnd, value in windows.items()}
        self.posts = []

    def EnumWindows(self, callback, context):
        for hwnd in list(self.windows):
            callback(hwnd, context)

    def GetWindowThreadProcessId(self, hwnd):
        return 1, self.windows[hwnd]["pid"]

    def IsWindow(self, hwnd):
        return hwnd in self.windows

    def IsWindowVisible(self, hwnd):
        return bool(self.windows[hwnd]["visible"])

    def PostMessage(self, hwnd, message, wparam, lparam):
        self.posts.append((hwnd, message, wparam, lparam))
        if self.windows[hwnd].get("close") == "hide":
            self.windows[hwnd]["visible"] = False
        else:
            del self.windows[hwnd]


class FakeUia:
    def __init__(self, environment):
        self.environment = environment

    def ControlFromHandle(self, hwnd):
        value = self.environment.windows.get(hwnd)
        if value is None:
            return None
        return SimpleNamespace(ClassName=value["uia_class"])


def attach_friend_window_context(driver, environment):
    driver._session = SimpleNamespace(
        pid=202,
        profile=SimpleNamespace(verify_friend_root_class=VERIFY_WINDOW_CLASS),
    )
    driver._uia = FakeUia(environment)


def test_close_friend_form_posts_close_and_verifies_the_window_is_gone():
    windows = FakeWindowEnvironment(
        {
            505: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "destroy",
            }
        }
    )
    driver = FakeFriendDriver()
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is True
    assert windows.posts == [(505, 0x0010, 0, 0)]


def test_close_friend_form_rejects_a_dialog_that_only_becomes_hidden():
    windows = FakeWindowEnvironment(
        {
            505: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "hide",
            }
        }
    )
    driver = FakeFriendDriver()
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is False
    assert driver._verify_hwnd == 505


def test_close_friend_form_rediscovers_missing_verification_handle():
    windows = FakeWindowEnvironment(
        {
            606: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "destroy",
            }
        }
    )
    driver = FakeFriendDriver()
    driver._verify_hwnd = 0
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is True
    assert windows.posts == [(606, 0x0010, 0, 0)]


def test_close_friend_form_never_closes_a_reused_unrelated_handle():
    windows = FakeWindowEnvironment(
        {
            505: {
                "pid": 999,
                "uia_class": "UnrelatedWindow",
                "visible": True,
                "close": "destroy",
            },
            606: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "destroy",
            },
        }
    )
    driver = FakeFriendDriver()
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is True
    assert windows.posts == [(606, 0x0010, 0, 0)]
    assert windows.IsWindow(505) is True


def test_close_friend_form_refuses_ambiguous_matching_windows():
    windows = FakeWindowEnvironment(
        {
            505: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "destroy",
            },
            606: {
                "pid": 202,
                "uia_class": VERIFY_WINDOW_CLASS,
                "visible": True,
                "close": "destroy",
            },
        }
    )
    driver = FakeFriendDriver()
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is False
    assert windows.posts == []


@pytest.mark.parametrize("root_class", [None, ""])
def test_close_friend_form_refuses_incomplete_same_pid_uia_discovery(root_class):
    windows = FakeWindowEnvironment(
        {
            505: {
                "pid": 202,
                "uia_class": root_class,
                "visible": True,
                "close": "destroy",
            }
        }
    )
    driver = FakeFriendDriver()
    attach_friend_window_context(driver, windows)

    closed = close_friend_form(
        driver,
        win32gui_module=windows,
        win32process_module=windows,
        wm_close=0x0010,
        wait_timeout=0,
    )

    assert closed is False
    assert windows.posts == []
    assert driver._verify_hwnd == 505


def test_friend_pre_submit_fills_reads_back_and_closes_at_confirm(tmp_path):
    driver = FakeFriendDriver()

    def close_form(received):
        assert received is driver
        driver.events.append("form_close")
        return True

    result = run_preflight(
        "friend-pre-submit",
        account="wx-friend-9",
        greeting="你好，我是测试",
        remark="备注",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
        form_closer=close_form,
    )

    assert result == {
        "ok": True,
        "mode": "friend-pre-submit",
        "stage": "ready_to_submit",
        "account": {
            "length": 11,
            "hashPrefix": "sha256:750dea2aaf44",
        },
        "fields": {
            "greeting": {
                "length": 7,
                "sha256": "a2589822bf43cb4ae6d773bf796e292906d854eddd6655cc5c47d2527f4b5371",
            },
            "remark": {
                "length": 2,
                "sha256": "daede9881787abe74c94e686be78a4eabc85a09688433027ea55ac583919bc1e",
            },
        },
    }
    assert driver.events == [
        "bind_window",
        "open_add_friend",
        ("set_friend_account", "wx-friend-9"),
        ("search_friend", "wx-friend-9"),
        "open_friend_request",
        ("set_friend_fields", "你好，我是测试", "备注"),
        (
            "wait_control",
            {
                "hwnd": 505,
                "name": "确定",
                "control_type": "ButtonControl",
            },
        ),
        "form_close",
        "driver_close",
    ]
    raw = (tmp_path / "uia-diagnostics.jsonl").read_text(encoding="utf-8")
    assert "wx-friend-9" not in raw
    assert "你好，我是测试" not in raw
    assert "备注" not in raw
    entries = [json.loads(line) for line in raw.splitlines()]
    assert entries[-2]["action"] == "confirm_present"
    assert entries[-1]["action"] == "close_form"
    assert entries[-1]["outcome"] == "success"


def test_friend_pre_submit_does_not_run_form_cleanup_before_form_navigation(tmp_path):
    driver = FakeFriendDriver()
    driver._verify_hwnd = 0

    def impossible_cleanup(_driver):
        raise AssertionError("no friend form can exist before account validation")

    with pytest.raises(PreflightError, match="non-empty account"):
        run_preflight(
            "friend-pre-submit",
            account="",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=impossible_cleanup,
        )

    assert driver.events == ["driver_close"]


def test_friend_pre_submit_rejects_an_offscreen_confirm_control(tmp_path):
    driver = FakeFriendDriver()

    def hidden_confirm(**selector):
        driver.events.append(("wait_control", selector))
        return HiddenConfirmControl()

    driver._wait_control = hidden_confirm

    with pytest.raises(PreflightError, match="Confirm control is not visible"):
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=lambda _driver: True,
        )

    assert driver.events[-1] == "driver_close"


def test_friend_pre_submit_closes_form_and_driver_when_readback_fails(tmp_path):
    driver = FakeFriendDriver()

    def mismatched_fields(greeting, remark):
        driver.events.append(("set_friend_fields", greeting, remark))
        return {"greeting": "wrong", "remark": remark}

    driver.set_friend_fields = mismatched_fields

    def close_form(_driver):
        driver.events.append("form_close")
        return True

    with pytest.raises(PreflightError, match="greeting readback"):
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            greeting="expected",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=close_form,
        )

    assert driver.events[-2:] == ["form_close", "driver_close"]


def test_friend_pre_submit_rediscovers_form_when_open_raises_before_handle_assignment(
    tmp_path,
):
    windows = FakeWindowEnvironment({})
    driver = FakeFriendDriver()
    driver._verify_hwnd = 0
    attach_friend_window_context(driver, windows)

    def open_then_disconnect(_profile):
        windows.windows[606] = {
            "pid": 202,
            "uia_class": VERIFY_WINDOW_CLASS,
            "visible": True,
            "close": "destroy",
        }
        raise RuntimeError("UIA provider disconnected")

    driver.open_friend_request = open_then_disconnect

    def close_discovered_form(value):
        return close_friend_form(
            value,
            win32gui_module=windows,
            win32process_module=windows,
            wm_close=0x0010,
            wait_timeout=0,
        )

    with pytest.raises(RuntimeError, match="provider disconnected"):
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=close_discovered_form,
        )

    assert windows.posts == [(606, 0x0010, 0, 0)]
    assert driver.events[-1] == "driver_close"


def test_friend_pre_submit_treats_form_cleanup_failure_as_an_error(tmp_path):
    driver = FakeFriendDriver()

    with pytest.raises(PreflightError, match="form did not close"):
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=lambda _driver: False,
        )

    assert driver.events[-1] == "driver_close"
    final_entry = json.loads(
        (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert final_entry["stage"] == "friend_pre_submit"
    assert final_entry["action"] == "close_form"
    assert final_entry["outcome"] == "error"


def test_cleanup_error_explicitly_chains_the_primary_preflight_error(tmp_path):
    driver = FakeFriendDriver()

    def mismatched_fields(greeting, remark):
        return {"greeting": "wrong", "remark": remark}

    driver.set_friend_fields = mismatched_fields

    with pytest.raises(PreflightError, match="form did not close") as raised:
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            greeting="expected",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=lambda _driver: False,
        )

    assert isinstance(raised.value.__cause__, PreflightError)
    assert "greeting readback" in str(raised.value.__cause__)


def test_driver_close_error_is_logged_and_chains_the_primary_error(tmp_path):
    driver = FakeFriendDriver()

    def mismatched_fields(greeting, remark):
        return {"greeting": "wrong", "remark": remark}

    def failing_close():
        driver.events.append("driver_close")
        raise RuntimeError("session restore failed")

    driver.set_friend_fields = mismatched_fields
    driver.close = failing_close

    with pytest.raises(RuntimeError, match="session restore failed") as raised:
        run_preflight(
            "friend-pre-submit",
            account="wx-friend-9",
            greeting="expected",
            driver_factory=lambda **_kwargs: driver,
            diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
            form_closer=lambda _driver: True,
        )

    assert isinstance(raised.value.__cause__, PreflightError)
    assert "greeting readback" in str(raised.value.__cause__)
    final_entry = json.loads(
        (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert final_entry["action"] == "driver_close"
    assert final_entry["outcome"] == "error"


def test_restore_only_restores_and_verifies_the_window_then_closes(tmp_path):
    driver = FakeRestoreDriver()

    result = run_preflight(
        "restore-only",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
    )

    assert result == {
        "ok": True,
        "mode": "restore-only",
        "stage": "window_restored",
    }
    assert driver.bind_count == 1
    assert driver.closed is True
    entry = json.loads(
        (tmp_path / "uia-diagnostics.jsonl").read_text(encoding="utf-8")
    )
    assert entry["stage"] == "restore_only"
    assert entry["action"] == "bind_window"
    assert entry["outcome"] == "success"


def test_message_open_verifies_an_exact_chat_without_writing_or_sending(tmp_path):
    driver = FakeMessageDriver()

    result = run_preflight(
        "message-open",
        target="Alice",
        driver_factory=lambda **_kwargs: driver,
        diagnostics_factory=lambda: UiaDiagnostics(log_dir=tmp_path),
    )

    assert result == {
        "ok": True,
        "mode": "message-open",
        "stage": "message_open_verified",
        "contact": {
            "length": 5,
            "hashPrefix": "sha256:3bc51062973c",
        },
    }
    assert driver.selected.display_name == "Alice Remark"
    assert driver.closed is True
    entries = [
        json.loads(line)
        for line in (tmp_path / "uia-diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert entries[-1]["stage"] == "message_open"
    assert entries[-1]["action"] == "verify_open_chat"
    assert entries[-1]["outcome"] == "success"
    assert "Alice" not in (tmp_path / "uia-diagnostics.jsonl").read_text(
        encoding="utf-8"
    )
