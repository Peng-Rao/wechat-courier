from __future__ import annotations

import pytest

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.runtime import TaskControl
from app.agent.workflows import RiskControlError, WeixinWorkflowEngine


class FakeDriver:
    def __init__(self):
        self.search_results = {}
        self.chat_title = ""
        self.composer = ""
        self.sent = []
        self.send_verification = True
        self.friend_profile = {}
        self.friend_fields = {"greeting": "微信原文", "remark": ""}
        self.friend_submit_count = 0
        self.friend_verification = True
        self.raise_risk = False
        self.closed = False
        self.raise_after_send = None

    def inspect(self):
        return {"connected": True, "version": "4.1.13.65", "supported": True}

    def bind_window(self):
        return self.inspect()

    def ensure_search_ready(self):
        return True

    def search_contacts(self, target):
        return self.search_results.get(target, [])

    def select_search_result(self, candidate):
        self.chat_title = candidate

    def current_chat_title(self):
        return self.chat_title

    def composer_ready(self):
        return True

    def set_composer_text(self, text):
        self.composer = text
        return "value_pattern"

    def read_composer_text(self):
        return self.composer

    def message_snapshot(self):
        return tuple(self.sent)

    def trigger_send(self):
        self.sent.append(self.composer)
        if self.raise_after_send is not None:
            raise self.raise_after_send

    def verify_sent(self, before, expected, timeout):
        return self.send_verification

    def send_files(self, paths):
        return [{"path": path, "outcome": "success"} for path in paths]

    def forward_bundle(self, target, message, paths):
        return {"outcome": "success"}

    def open_add_friend(self):
        if self.raise_risk:
            raise RiskControlError("操作频繁")
        return True

    def set_friend_account(self, account):
        self.friend_account = account

    def search_friend(self, account):
        return self.friend_profile or {"account": account}

    def profile_account(self, profile):
        return profile["account"]

    def open_friend_request(self, profile):
        return True

    def set_friend_fields(self, greeting, remark):
        if greeting is not None:
            self.friend_fields["greeting"] = greeting
        if remark:
            self.friend_fields["remark"] = remark
        return dict(self.friend_fields)

    def submit_friend_request(self):
        self.friend_submit_count += 1

    def verify_friend_request(self, timeout):
        return self.friend_verification

    def close(self):
        self.closed = True


def request(kind, items, options=None):
    return TaskRequest(
        task_id="task-1",
        kind=kind,
        items=tuple(items),
        options=options or TaskOptions(),
    )


def run_engine(driver, task):
    events = []
    result = WeixinWorkflowEngine(driver_factory=lambda: driver).run(
        task,
        TaskControl(),
        lambda method, payload: events.append((method, payload)),
    )
    return result, [payload for method, payload in events if method == "task.event"]


class MemoryJournal:
    def __init__(self):
        self.record = None
        self.marks = []

    def mark(self, **record):
        self.record = dict(record)
        self.marks.append(dict(record))
        return self.record

    def clear(self, **_match):
        self.record = None
        return True


def test_message_requires_one_exact_normalized_search_result():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice Team"]
    item = TaskItem("one", target="Alice", message="hello")

    result, events = run_engine(driver, request("message_send", [item]))

    assert result["error"] == 1
    assert driver.sent == []
    assert events[-1]["outcome"] == "error"
    assert "未找到" in events[-1]["detail"]

    driver = FakeDriver()
    driver.search_results["Alice"] = [" Alice ", "Alice"]
    result, _events = run_engine(driver, request("message_send", [item]))
    assert result["error"] == 1
    assert driver.sent == []


def test_message_checks_title_and_composer_before_triggering_send():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    original_set = driver.set_composer_text

    def corrupt(text):
        original_set(text)
        driver.composer = text + "!"

    driver.set_composer_text = corrupt
    item = TaskItem("one", target="Alice", message="hello")

    result, events = run_engine(driver, request("message_send", [item]))

    assert result["error"] == 1
    assert driver.sent == []
    assert events[-1]["step"] == "content_inserted"


def test_unknown_send_is_never_retried_and_continues_by_default():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"], "Bob": ["Bob"]}
    driver.send_verification = None
    items = [
        TaskItem("one", target="Alice", message="one"),
        TaskItem("two", target="Bob", message="two"),
    ]

    result, events = run_engine(driver, request("message_send", items))

    assert driver.sent == ["one", "two"]
    assert result["unknown"] == 2
    unknown = [event for event in events if event["outcome"] == "unknown"]
    assert [event["itemId"] for event in unknown] == ["one", "two"]


def test_send_boundary_is_journaled_and_known_exception_becomes_unknown():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"]}
    driver.raise_after_send = RuntimeError("UIA provider disconnected")
    journal = MemoryJournal()
    task = request(
        "message_send", [TaskItem("one", target="Alice", message="hello")]
    )
    events = []

    result = WeixinWorkflowEngine(
        driver_factory=lambda: driver,
        journal=journal,
    ).run(
        task,
        TaskControl(),
        lambda method, payload: events.append((method, payload)),
    )

    terminal = [payload for method, payload in events if method == "task.event"][-1]
    assert driver.sent == ["hello"]
    assert journal.marks[0]["boundary"] == "send_triggered"
    assert result["unknown"] == 1
    assert terminal["outcome"] == "unknown"
    assert "不会自动重发" in terminal["detail"]
    assert journal.record is None


def test_abrupt_crash_after_send_boundary_keeps_recovery_record():
    class SimulatedProcessCrash(BaseException):
        pass

    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"]}
    driver.raise_after_send = SimulatedProcessCrash()
    journal = MemoryJournal()
    task = request(
        "message_send", [TaskItem("one", target="Alice", message="hello")]
    )

    with pytest.raises(SimulatedProcessCrash):
        WeixinWorkflowEngine(
            driver_factory=lambda: driver,
            journal=journal,
        ).run(task, TaskControl(), lambda *_args: None)

    assert journal.record["task_id"] == "task-1"
    assert journal.record["item_id"] == "one"
    assert journal.record["boundary"] == "send_triggered"


def test_unknown_policy_can_stop_after_the_destructive_boundary():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"], "Bob": ["Bob"]}
    driver.send_verification = None
    items = [
        TaskItem("one", target="Alice", message="one"),
        TaskItem("two", target="Bob", message="two"),
    ]

    result, _events = run_engine(
        driver,
        request("message_send", items, TaskOptions(unknown_policy="stop")),
    )

    assert driver.sent == ["one"]
    assert result["unknown"] == 1


def test_friend_request_verifies_fields_and_submits_once():
    driver = FakeDriver()
    item = TaskItem(
        "friend-1",
        account="18896904196",
        greeting="你好",
        remark="测试备注",
    )

    result, events = run_engine(driver, request("friend_add", [item]))

    assert result["success"] == 1
    assert driver.friend_submit_count == 1
    assert events[-1]["step"] == "submit_verified"
    assert events[-1]["outcome"] == "success"


def test_friend_unknown_submit_is_not_clicked_again():
    driver = FakeDriver()
    driver.friend_verification = None
    item = TaskItem("friend-1", account="18896904196")

    result, events = run_engine(driver, request("friend_add", [item]))

    assert driver.friend_submit_count == 1
    assert result["unknown"] == 1
    assert events[-1]["outcome"] == "unknown"


def test_risk_control_stops_the_entire_friend_batch():
    driver = FakeDriver()
    driver.raise_risk = True
    items = [
        TaskItem("friend-1", account="18896904196"),
        TaskItem("friend-2", account="19170745267"),
    ]

    result, events = run_engine(driver, request("friend_add", items))

    assert result["error"] == 1
    assert result["done"] == 1
    assert driver.friend_submit_count == 0
    assert "操作频繁" in events[-1]["detail"]
