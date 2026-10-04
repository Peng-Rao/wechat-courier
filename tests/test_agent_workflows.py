from __future__ import annotations

import threading

import pytest

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.gate import AccessibilitySafetyError
from app.agent.native_driver import SearchCandidate
from app.agent.profile import UnsupportedWeixinVersion
from app.agent.runtime import TaskControl
from app.agent.retry import UiaTreeNotReadyError, WeixinUnresponsiveError
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
        self.friend_cancel_count = 0
        self.friend_verification = True
        self.raise_risk = False
        self.closed = False
        self.raise_after_send = None
        self.sent_files = []
        self.search_calls = 0
        self.fail_search_once = False
        self.soft_refresh_count = 0
        self.response_checks = 0

    def inspect(self):
        return {"connected": True, "version": "4.1.13.65", "supported": True}

    def bind_window(self):
        return self.inspect()

    def ensure_window_responsive(self):
        self.response_checks += 1
        return True

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

    def cancel_friend_request(self):
        self.friend_cancel_count += 1
        return True

    def soft_refresh_session(self):
        self.soft_refresh_count += 1

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
    result = WeixinWorkflowEngine(
        driver_factory=lambda: driver,
        friend_submit_enabled=True,
    ).run(
        task,
        TaskControl(),
        lambda method, payload: events.append((method, payload)),
    )
    return result, [payload for method, payload in events if method == "task.event"]


@pytest.mark.parametrize("limit", [100, 1000])
def test_friend_preflight_executes_entire_configured_batch_with_fake_driver(limit):
    driver = FakeDriver()
    task = TaskRequest.from_payload({
        "taskId": "batch", "kind": "friend_add",
        "items": [{"itemId": f"row-{i}", "account": f"wxid_batch{i:04d}",
                   "greeting": "hello", "remark": "test"} for i in range(limit)],
        "options": {"friendBatchLimit": limit},
    })
    result, events = run_engine(driver, task)
    assert result["success"] == result["done"] == limit
    assert result["error"] == result["unknown"] == 0
    completed = [e for e in events if e["step"] == "preflight_completed" and e["outcome"] == "success"]
    assert len({e["itemId"] for e in completed}) == limit
    assert driver.friend_submit_count == 0
    assert driver.friend_cancel_count == limit


def test_engine_reuses_one_driver_for_inspection_and_tasks_until_closed():
    created = []

    def factory():
        driver = FakeDriver()
        driver.search_results["Alice"] = ["Alice"]
        created.append(driver)
        return driver

    engine = WeixinWorkflowEngine(driver_factory=factory)

    assert engine.inspect()["connected"] is True
    result = engine.run(
        request(
            "message_send",
            [TaskItem("one", target="Alice", message="hello")],
        ),
        TaskControl(),
        lambda *_args: None,
    )
    assert engine.inspect()["connected"] is True

    assert result["success"] == 1
    assert len(created) == 1
    assert created[0].closed is False

    engine.close()

    assert created[0].closed is True


def test_cleanup_false_receipt_is_logged_as_failure_without_leaking_detail(tmp_path):
    import json
    from app.agent.diagnostics import UiaDiagnostics

    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    driver.finish_task = lambda: {"success": False, "reasonCode": "WINDOW_BLOCKED",
                                  "detail": "private contact 18896904196"}
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver, diagnostics=diagnostics)
    result = engine.run(request("message_send", [TaskItem("one", target="Alice", message="hello")]),
                        TaskControl(), lambda *_: None)
    diagnostics.close()
    assert result["cleanup"]["success"] is False
    raw = (tmp_path / "uia-diagnostics.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in raw.splitlines()]
    finish = [entry for entry in entries if entry["action"] == "finish_task"
              and entry["outcome"] != "started"][-1]
    assert finish["outcome"] == "error"
    assert finish["error"]["code"] == "WINDOW_BLOCKED"
    assert finish["postcondition"] is False
    assert finish["result"]["success"] is False
    assert "18896904196" not in raw
    assert "private contact" not in raw


def test_engine_records_privacy_safe_action_metrics_and_retry_decisions():
    class RecordingDiagnostics:
        def __init__(self):
            self.entries = []

        def record(self, **entry):
            self.entries.append(entry)

    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    driver.fail_search_once = True
    diagnostics = RecordingDiagnostics()
    engine = WeixinWorkflowEngine(
        driver_factory=lambda: driver,
        diagnostics=diagnostics,
        sleep=lambda _seconds: None,
    )

    result = engine.run(
        request(
            "message_send",
            [TaskItem("one", target="Alice", message="private message")],
        ),
        TaskControl(),
        lambda *_args: None,
    )

    assert result["success"] == 1
    search_actions = [
        entry for entry in diagnostics.entries
        if entry.get("action") == "search_contacts"
        and entry.get("outcome") != "started"
    ]
    assert [entry["outcome"] for entry in search_actions] == ["error", "success"]
    assert all("duration_ms" in entry for entry in search_actions)
    retry_events = [
        entry for entry in diagnostics.entries
        if entry.get("outcome") == "retry"
    ]
    assert retry_events[0]["retry_level"] == "session_refresh"
    assert retry_events[0]["contact"] == "Alice"
    assert all("private message" not in repr(entry) for entry in diagnostics.entries)


def test_weixin_unresponsive_stops_batch_without_touching_the_next_item():
    driver = FakeDriver()
    calls = 0

    def unresponsive_bind():
        nonlocal calls
        calls += 1
        raise WeixinUnresponsiveError("window stopped responding")

    driver.bind_window = unresponsive_bind
    result, events = run_engine(
        driver,
        request(
            "message_send",
            [
                TaskItem("one", target="Alice", message="hello"),
                TaskItem("two", target="Bob", message="hello"),
            ],
        ),
    )

    assert calls == 1
    assert result["done"] == 1
    assert events[-1]["errorCode"] == "WECHAT_UNRESPONSIVE"
    assert events[-1]["wechatResponsive"] is False


def test_weixin_unresponsive_before_send_snapshot_keeps_its_type_and_stops_batch():
    class SnapshotUnresponsiveDriver(FakeDriver):
        def ensure_window_responsive(self):
            self.response_checks += 1
            if self.response_checks == 8:
                raise WeixinUnresponsiveError("window stopped responding")
            return True

    driver = SnapshotUnresponsiveDriver()
    driver.search_results = {"Alice": ["Alice"], "Bob": ["Bob"]}

    result, events = run_engine(
        driver,
        request(
            "message_send",
            [
                TaskItem("one", target="Alice", message="one"),
                TaskItem("two", target="Bob", message="two"),
            ],
        ),
    )

    assert result["done"] == 1
    assert driver.sent == []
    assert events[-1]["itemId"] == "one"
    assert events[-1]["errorCode"] == "WECHAT_UNRESPONSIVE"
    assert events[-1]["wechatResponsive"] is False


def test_weixin_unresponsive_after_send_marks_unknown_and_stops_batch():
    class VerificationUnresponsiveDriver(FakeDriver):
        def verify_sent(self, before, expected, timeout):
            raise WeixinUnresponsiveError("window stopped responding")

    driver = VerificationUnresponsiveDriver()
    driver.search_results = {"Alice": ["Alice"], "Bob": ["Bob"]}

    result, events = run_engine(
        driver,
        request(
            "message_send",
            [
                TaskItem("one", target="Alice", message="one"),
                TaskItem("two", target="Bob", message="two"),
            ],
        ),
    )

    assert result["done"] == 1
    assert result["unknown"] == 1
    assert driver.sent == ["one"]
    assert events[-1]["itemId"] == "one"
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["errorCode"] == "WECHAT_UNRESPONSIVE"
    assert events[-1]["destructiveBoundaryCrossed"] is True
    assert events[-1]["wechatResponsive"] is False


@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (UnsupportedWeixinVersion("unsupported"), "UNSUPPORTED_VERSION"),
        (AccessibilitySafetyError("unsafe gate"), "GATE_SAFETY"),
        (
            UiaTreeNotReadyError("accessibility broadcast did not materialize tree"),
            "UIA_TREE_NOT_READY_AFTER_REFRESH",
        ),
    ],
)
def test_non_retryable_session_safety_failures_stop_the_batch(
    failure, error_code
):
    driver = FakeDriver()
    calls = 0

    def fail_bind():
        nonlocal calls
        calls += 1
        raise failure

    driver.bind_window = fail_bind
    result, events = run_engine(
        driver,
        request(
            "message_send",
            [
                TaskItem("one", target="Alice", message="hello"),
                TaskItem("two", target="Bob", message="hello"),
            ],
        ),
    )

    assert calls == 1
    assert result["done"] == 1
    assert events[-1]["errorCode"] == error_code
    assert events[-1]["recoverable"] is False


def test_gate_failure_during_stale_session_refresh_stops_the_batch():
    class RefreshGateFailureDriver(FakeDriver):
        def search_contacts(self, target):
            self.search_calls += 1
            raise RuntimeError("UIA provider disconnected")

        def soft_refresh_session(self):
            self.soft_refresh_count += 1
            raise AccessibilitySafetyError("gate changed during refresh")

    driver = RefreshGateFailureDriver()

    result, events = run_engine(
        driver,
        request(
            "message_send",
            [
                TaskItem("one", target="Alice", message="one"),
                TaskItem("two", target="Bob", message="two"),
            ],
        ),
    )

    assert result["done"] == 1
    assert driver.soft_refresh_count == 1
    assert events[-1]["itemId"] == "one"
    assert events[-1]["errorCode"] == "GATE_SAFETY"
    assert events[-1]["recoverable"] is False


def test_risk_control_has_stable_error_code_and_stops_friend_batch():
    driver = FakeDriver()
    driver.raise_risk = True

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [
                TaskItem("one", account="18800000001"),
                TaskItem("two", account="18800000002"),
            ],
        ),
    )

    assert result["done"] == 1
    assert events[-1]["errorCode"] == "RISK_CONTROL"
    assert events[-1]["recoverable"] is False


def test_send_boundary_events_are_explicitly_non_retryable():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]

    _result, events = run_engine(
        driver,
        request(
            "message_send",
            [TaskItem("one", target="Alice", message="hello")],
        ),
    )

    triggered = next(event for event in events if event["step"] == "send_triggered")
    verified = next(event for event in events if event["step"] == "send_verified")
    assert triggered["destructiveBoundaryCrossed"] is True
    assert verified["destructiveBoundaryCrossed"] is True
    assert triggered["recoverable"] is False


def test_unconfirmed_send_uses_stable_unknown_result_code():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    driver.send_verification = None

    result, events = run_engine(
        driver,
        request(
            "message_send",
            [TaskItem("one", target="Alice", message="hello")],
        ),
    )

    terminal = events[-1]
    assert result["unknown"] == 1
    assert terminal["outcome"] == "unknown"
    assert terminal["errorCode"] == "RESULT_UNKNOWN"
    assert terminal["destructiveBoundaryCrossed"] is True
    assert terminal["recoverable"] is False


def test_every_pre_boundary_action_and_send_trigger_check_window_response():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]
    order = []
    original_response_check = driver.ensure_window_responsive
    original_snapshot = driver.message_snapshot
    original_trigger = driver.trigger_send

    def response_check():
        order.append("responsive")
        return original_response_check()

    def snapshot():
        order.append("snapshot")
        return original_snapshot()

    def trigger():
        order.append("trigger")
        return original_trigger()

    driver.ensure_window_responsive = response_check
    driver.message_snapshot = snapshot
    driver.trigger_send = trigger

    result, _events = run_engine(
        driver,
        request(
            "message_send",
            [TaskItem("one", target="Alice", message="hello")],
        ),
    )

    assert result["success"] == 1
    snapshot_index = order.index("snapshot")
    trigger_index = order.index("trigger")
    assert order[snapshot_index - 1] == "responsive"
    assert order[trigger_index - 1] == "responsive"
    assert driver.response_checks >= 9


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


def test_friend_tasks_default_to_verified_form_preflight_without_submit():
    driver = FakeDriver()
    journal = MemoryJournal()
    events = []
    engine = WeixinWorkflowEngine(
        driver_factory=lambda: driver,
        journal=journal,
    )

    result = engine.run(
        request(
            "friend_add",
            [
                TaskItem(
                    "friend-1",
                    account="18896904196",
                    greeting="你好",
                    remark="测试备注",
                )
            ],
        ),
        TaskControl(),
        lambda method, payload: events.append((method, payload)),
    )
    task_events = [payload for method, payload in events if method == "task.event"]

    assert result["success"] == 1
    assert driver.friend_submit_count == 0
    assert driver.friend_cancel_count == 1
    assert journal.marks == []
    assert task_events[-1]["step"] == "preflight_completed"
    assert task_events[-1]["detail"] == "表单预检完成，未提交好友申请"


def test_submission_capability_alone_never_crosses_boundary_without_task_intent():
    driver = FakeDriver()

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [TaskItem("friend-1", account="18896904196")],
        ),
    )

    assert result["success"] == 1
    assert driver.friend_submit_count == 0
    assert driver.friend_cancel_count == 1
    assert events[-1]["step"] == "preflight_completed"


def test_non_boolean_internal_submission_intent_fails_closed():
    driver = FakeDriver()

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [TaskItem("friend-1", account="18896904196")],
            TaskOptions(submit_friend_request=1),
        ),
    )

    assert result["success"] == 1
    assert driver.friend_submit_count == 0
    assert driver.friend_cancel_count == 1
    assert events[-1]["step"] == "preflight_completed"


def test_non_boolean_engine_submission_capability_fails_closed():
    driver = FakeDriver()
    notices = []
    engine = WeixinWorkflowEngine(
        driver_factory=lambda: driver,
        friend_submit_enabled="yes",
    )

    result = engine.run(
        request(
            "friend_add",
            [TaskItem("friend-1", account="18896904196")],
            TaskOptions(submit_friend_request=True),
        ),
        TaskControl(),
        lambda method, payload: notices.append((method, payload)),
    )
    events = [payload for method, payload in notices if method == "task.event"]

    assert result["success"] == 1
    assert driver.friend_submit_count == 0
    assert driver.friend_cancel_count == 1
    assert events[-1]["step"] == "preflight_completed"


def test_friend_preflight_uses_layered_retry_before_opening_the_form():
    driver = FakeDriver()
    calls = []

    def eventually_open():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("control not ready")
        return True

    driver.open_add_friend = eventually_open
    events = []
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver)

    result = engine.run(
        request(
            "friend_add",
            [TaskItem("friend-1", account="18896904196")],
        ),
        TaskControl(),
        lambda method, payload: events.append((method, payload)),
    )

    retries = [
        payload
        for method, payload in events
        if method == "task.event" and payload["outcome"] == "working"
    ]
    assert result["success"] == 1
    assert len(calls) == 3
    assert [event["attempt"] for event in retries] == [2, 3]
    assert driver.friend_submit_count == 0


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


def test_message_accepts_remark_title_for_unique_nickname_candidate():
    candidate = SearchCandidate(
        "Alice 备注",
        frozenset({"Alice 备注", "Alice 昵称"}),
        "contact",
        "search_item_1",
        0,
        1,
    )
    driver = FakeDriver()
    driver.search_results["Alice 昵称"] = [candidate]
    driver.select_search_result = lambda selected: setattr(
        driver, "chat_title", selected.display_name
    )

    result, _events = run_engine(
        driver,
        request(
            "message_send",
            [TaskItem("one", target="Alice 昵称", message="hello")],
        ),
    )

    assert result["success"] == 1
    assert driver.sent == ["hello"]


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


def test_message_preparation_retries_twice_and_reports_retry_metadata():
    driver = FakeDriver()
    driver.search_results["Alice"] = ["Alice"]

    def search_after_two_failures(target):
        driver.search_calls += 1
        if driver.search_calls < 3:
            raise RuntimeError("control not ready")
        return driver.search_results[target]

    driver.search_contacts = search_after_two_failures

    result, events = run_engine(
        driver,
        request("message_send", [TaskItem("one", target="Alice", message="hello")]),
    )

    retries = [event for event in events if event["outcome"] == "working"]
    assert result["success"] == 1
    assert driver.search_calls == 3
    assert [event["attempt"] for event in retries] == [2, 3]
    assert all(event["maxAttempts"] == 3 for event in retries)
    assert all(event["recoverable"] is True for event in retries)
    assert driver.sent == ["hello"]


def test_message_does_not_retry_a_deterministic_missing_target():
    driver = FakeDriver()

    result, _events = run_engine(
        driver,
        request("message_send", [TaskItem("one", target="Missing", message="hello")]),
    )

    assert result["error"] == 1
    assert driver.search_calls == 1


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


def test_long_boundary_actions_forward_real_driver_progress_to_the_runtime():
    class ProgressDriver(FakeDriver):
        def __init__(self):
            super().__init__()
            self.progress_callback = None

        def set_progress_callback(self, callback):
            self.progress_callback = callback

        def send_files(self, paths):
            assert self.progress_callback is not None
            self.progress_callback("attachment_paste")
            self.progress_callback("attachment_verify")
            return super().send_files(paths)

    driver = ProgressDriver()
    driver.search_results = {"Alice": ["Alice"]}
    task = request(
        "message_send",
        [TaskItem("one", target="Alice", message="")],
        TaskOptions(file_paths=("report.pdf",)),
    )
    notices = []

    result = WeixinWorkflowEngine(driver_factory=lambda: driver).run(
        task,
        TaskControl(),
        lambda method, payload: notices.append((method, payload)),
    )

    progress = [
        payload
        for method, payload in notices
        if method == "agent.status"
        and payload.get("status") == "uia_action_progress"
    ]
    assert result["success"] == 1
    assert [item["detail"] for item in progress] == [
        "attachment_paste",
        "attachment_verify",
    ]
    assert all(item["action"] == "send_files" for item in progress)
    assert driver.progress_callback is None


def test_friend_request_verifies_fields_and_submits_once():
    driver = FakeDriver()
    item = TaskItem(
        "friend-1",
        account="18896904196",
        greeting="你好",
        remark="测试备注",
    )

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [item],
            TaskOptions(submit_friend_request=True),
        ),
    )

    assert result["success"] == 1
    assert driver.friend_submit_count == 1
    assert any(
        event["step"] == "submit_triggered" and event["outcome"] == "success"
        for event in events
    )
    assert events[-1]["step"] == "submit_verified"
    assert events[-1]["outcome"] == "success"


def test_friend_unknown_submit_is_not_clicked_again():
    driver = FakeDriver()
    driver.friend_verification = None
    item = TaskItem("friend-1", account="18896904196")

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [item],
            TaskOptions(submit_friend_request=True),
        ),
    )

    assert driver.friend_submit_count == 1
    assert result["unknown"] == 1
    assert events[-1]["outcome"] == "unknown"


def test_friend_submit_pretrigger_failure_is_error_not_false_clicked_unknown():
    class NotTriggered(RuntimeError):
        destructive_triggered = False

    driver = FakeDriver()
    driver.submit_friend_request = lambda: (_ for _ in ()).throw(
        NotTriggered("hit-test did not match confirm")
    )
    item = TaskItem("friend-1", account="18896904196")

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [item],
            TaskOptions(submit_friend_request=True),
        ),
    )

    assert result["error"] == 1
    assert result["unknown"] == 0
    assert events[-1]["step"] == "submit_triggered"
    assert events[-1]["outcome"] == "error"
    assert "未点击确定" in events[-1]["detail"]
    assert events[-1]["destructiveBoundaryCrossed"] is False


def test_friend_submit_click_transport_failure_stays_unknown_without_retry():
    class TriggerUnknown(RuntimeError):
        destructive_triggered = None

    calls = []
    driver = FakeDriver()

    def uncertain_click():
        calls.append("click")
        raise TriggerUnknown("transport disconnected during click")

    driver.submit_friend_request = uncertain_click
    item = TaskItem("friend-1", account="18896904196")

    result, events = run_engine(
        driver,
        request(
            "friend_add",
            [item],
            TaskOptions(submit_friend_request=True),
        ),
    )

    assert calls == ["click"]
    assert result["unknown"] == 1
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["destructiveBoundaryCrossed"] is True


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
