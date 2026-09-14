from __future__ import annotations

import threading

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
        self.sent_files = []
        self.forward_preparations = 0
        self.forward_targets = []
        self.search_calls = 0
        self.fail_search_once = False

    def inspect(self):
        return {"connected": True, "version": "4.1.13.65", "supported": True}

    def bind_window(self):
        return self.inspect()

    def ensure_search_ready(self):
        return True

    def search_contacts(self, target):
        self.search_calls += 1
        if self.fail_search_once and self.search_calls == 1:
            raise RuntimeError("UIA provider disconnected")
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
        self.sent_files.append(tuple(paths))
        return [{"path": path, "outcome": "success"} for path in paths]

    def forward_bundle(self, target, message, paths):
        self.forward_targets.append((target, message, tuple(paths)))
        return {"outcome": "success"}

    def prepare_forward_bundle(self, paths):
        self.forward_preparations += 1
        return {"outcome": "success", "count": len(paths)}

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


def test_message_retries_the_safe_location_chain_once_before_send():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    driver.fail_search_once = True

    result, events = run_engine(
        driver,
        request("message_send", [TaskItem("one", target="Alice", message="hello")]),
    )

    assert result["success"] == 1
    assert driver.search_calls == 2
    assert driver.sent == ["hello"]
    assert len([event for event in events if event["step"] == "send_triggered"]) == 1


def test_message_maps_repeated_search_exception_to_search_step():
    driver = FakeDriver()
    driver.search_contacts = lambda _target: (_ for _ in ()).throw(
        RuntimeError("UIA provider disconnected")
    )

    result, events = run_engine(
        driver,
        request("message_send", [TaskItem("one", target="Alice", message="hello")]),
    )

    assert result["error"] == 1
    assert events[-1]["step"] == "target_selected"
    assert "search_contacts" in events[-1]["detail"]
    assert driver.sent == []


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


def test_send_boundary_remains_until_gui_acknowledges_terminal_event():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"]}
    journal = MemoryJournal()
    control = TaskControl(require_result_ack=True)
    terminal_seen = threading.Event()
    finished = threading.Event()

    def emit(method, payload):
        if method == "task.event" and payload["step"] == "send_verified":
            terminal_seen.set()

    def run():
        WeixinWorkflowEngine(
            driver_factory=lambda: driver,
            journal=journal,
        ).run(
            request(
                "message_send",
                [TaskItem("one", target="Alice", message="hello")],
            ),
            control,
            emit,
        )
        finished.set()

    worker = threading.Thread(target=run)
    worker.start()
    assert terminal_seen.wait(1)
    assert journal.record["boundary"] == "send_triggered"
    assert finished.is_set() is False

    control.acknowledge_result("one")
    worker.join(1)

    assert finished.is_set() is True
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


def test_forward_source_is_uploaded_once_then_merged_for_each_target():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"], "Bob": ["Bob"]}
    task = request(
        "message_send",
        [
            TaskItem("one", target="Alice", message="note one"),
            TaskItem("two", target="Bob", message="note two"),
        ],
        TaskOptions(use_forward=True, file_paths=("one.pdf", "two.pdf")),
    )

    result, _events = run_engine(driver, task)

    assert result["success"] == 2
    assert driver.forward_preparations == 1
    assert [target for target, _message, _paths in driver.forward_targets] == [
        "Alice",
        "Bob",
    ]
    assert driver.sent == []


def test_forward_source_upload_is_journaled_before_the_driver_call():
    class SimulatedProcessCrash(BaseException):
        pass

    driver = FakeDriver()
    driver.prepare_forward_bundle = lambda _paths: (_ for _ in ()).throw(
        SimulatedProcessCrash()
    )
    journal = MemoryJournal()
    task = request(
        "message_send",
        [TaskItem("one", target="Alice", message="note")],
        TaskOptions(use_forward=True, file_paths=("one.pdf",)),
    )

    with pytest.raises(SimulatedProcessCrash):
        WeixinWorkflowEngine(
            driver_factory=lambda: driver,
            journal=journal,
        ).run(task, TaskControl(), lambda *_args: None)

    assert journal.record["boundary"] == "forward_source_upload"


def test_unknown_forward_source_preparation_is_reported_as_unknown():
    driver = FakeDriver()
    driver.prepare_forward_bundle = lambda _paths: {
        "outcome": "unknown",
        "detail": "源文件上传结果未知",
    }
    task = request(
        "message_send",
        [TaskItem("one", target="Alice", message="note")],
        TaskOptions(use_forward=True, file_paths=("one.pdf",)),
    )

    result, events = run_engine(driver, task)

    assert result["unknown"] == 1
    assert result["error"] == 0
    assert events[-1]["step"] == "send_verified"
    assert events[-1]["outcome"] == "unknown"


def test_attachment_only_item_does_not_trigger_an_empty_text_send():
    driver = FakeDriver()
    driver.search_results = {"Alice": ["Alice"]}
    task = request(
        "message_send",
        [TaskItem("one", target="Alice", message="")],
        TaskOptions(file_paths=("report.pdf",)),
    )

    result, events = run_engine(driver, task)

    assert result["success"] == 1
    assert driver.sent == []
    assert driver.sent_files == [("report.pdf",)]
    assert events[-1]["detail"] == "1 个附件已确认"


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


def test_friend_bind_failure_is_the_only_error_reported_as_window_bound():
    driver = FakeDriver()
    driver.bind_window = lambda: (_ for _ in ()).throw(RuntimeError("hidden"))

    result, events = run_engine(
        driver, request("friend_add", [TaskItem("friend-1", account="18896904196")])
    )

    assert result["error"] == 1
    assert events[-1]["step"] == "window_bound"
    assert "bind_window" in events[-1]["detail"]


def test_friend_navigation_exception_maps_to_its_actual_step():
    driver = FakeDriver()
    driver.open_add_friend = lambda: (_ for _ in ()).throw(RuntimeError("detached"))

    result, events = run_engine(
        driver, request("friend_add", [TaskItem("friend-1", account="18896904196")])
    )

    assert result["error"] == 1
    assert events[-1]["step"] == "add_friend_window_ready"
    assert "open_add_friend" in events[-1]["detail"]
