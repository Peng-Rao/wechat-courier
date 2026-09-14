from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.runtime import TaskControl
from app.agent.workflows import WeixinWorkflowEngine
from tests.test_agent_workflows import FakeDriver


def request(task_id="one"):
    return TaskRequest(task_id=task_id, kind="message_send", items=[
        TaskItem(item_id="item", target="文件传输助手", message="unique")
    ], options=TaskOptions())


class LifecycleDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.search_results = {"文件传输助手": ["文件传输助手"]}
        self.calls = []
        self.ready_attempts = 0
        self.cleanup_ok = True

    def begin_task(self, kind):
        self.calls.append("begin")

    def ensure_search_ready(self):
        self.ready_attempts += 1
        return self.ready_attempts != 1

    def finish_task(self):
        self.calls.append("cleanup")
        return {"success": self.cleanup_ok, "reasonCode": "" if self.cleanup_ok else "CLEANUP_FAILED"}


def test_false_search_result_retries_then_second_independent_task_succeeds():
    driver = LifecycleDriver()
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None)
    events = []
    first = engine.run(request(), TaskControl(), lambda m, p: events.append((m, p)))
    second = engine.run(request("two"), TaskControl(), lambda m, p: events.append((m, p)))
    assert first["success"] == second["success"] == 1
    assert driver.sent == ["unique", "unique"]
    assert driver.calls == ["begin", "cleanup", "begin", "cleanup"]
    assert any(p.get("retryLevel") == "same_session" for m, p in events)


def test_cleanup_failure_preserves_delivery_and_blocks_next_run():
    driver = LifecycleDriver()
    driver.ready_attempts = 1
    driver.cleanup_ok = False
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None)
    result = engine.run(request(), TaskControl(), lambda *_: None)
    assert result["success"] == 1
    assert result["cleanup"]["success"] is False
    assert result["health"]["sessionReady"] is False
    second = engine.run(request("two"), TaskControl(), lambda *_: None)
    assert second["outcome"] == "error"
    assert driver.sent == ["unique"]


def test_false_precondition_records_return_value_and_action_completion():
    class Recorder:
        def __init__(self):
            self.entries = []

        def record(self, **entry):
            self.entries.append(entry)

    recorder = Recorder()
    driver = LifecycleDriver()
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver, sleep=lambda _: None,
                                  diagnostics=recorder)
    notices = []
    engine.run(request(), TaskControl(), lambda m, p: notices.append((m, p)))
    failure = next(entry for entry in recorder.entries
                   if entry.get("action") == "ensure_search_ready"
                   and entry.get("outcome") == "error")
    assert failure["result"] == {"type": "bool", "value": False}
    assert failure["postcondition"] is False
    action_id = failure["action_id"]
    assert any(payload.get("actionId") == action_id
               and payload.get("status") == "uia_action_completed"
               for _, payload in notices)


def test_stop_requested_before_forward_never_uploads_source():
    driver = LifecycleDriver()
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver)
    control = TaskControl()
    control.request_stop()
    task = TaskRequest(task_id="stopped-forward", kind="message_send", items=[
        TaskItem(item_id="item", target="文件传输助手", message="note")
    ], options=TaskOptions(use_forward=True, file_paths=("test.txt",)))
    result = engine.run(task, control, lambda *_: None)
    assert driver.forward_preparations == 0
    assert driver.forward_targets == []
    assert result["outcome"] == "stopped"
    assert result["cleanup"]["success"] is True


def test_early_exception_preserves_cleanup_failure_and_health():
    driver = LifecycleDriver()
    driver.cleanup_ok = False

    def broken_begin(_kind):
        raise RuntimeError("task preparation failed")

    driver.begin_task = broken_begin
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver)
    result = engine.run(request(), TaskControl(), lambda *_: None)
    assert result["outcome"] == "error"
    assert result["cleanup"]["success"] is False
    assert result["health"]["sessionReady"] is False
    assert result["health"]["reasonCode"] == "CLEANUP_FAILED"
    assert driver.sent == []


def test_cleanup_recovery_is_explicit_even_while_window_is_in_tray():
    driver = LifecycleDriver()
    driver.inspect = lambda: {"sessionReady": False, "restorable": True,
                              "windowEnabled": True, "windowResponsive": True}
    engine = WeixinWorkflowEngine(driver_factory=lambda: driver)
    engine._cleanup_blocked = True
    health = engine.inspect()
    assert health["sessionReady"] is False
    assert health["cleanupComplete"] is True
