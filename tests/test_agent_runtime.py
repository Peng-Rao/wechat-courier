from __future__ import annotations

import threading
import uuid

from PySide6.QtNetwork import QLocalServer

from app.agent.client import AgentClient
from app.agent.runtime import AgentRuntime
from app.agent.server import AgentServer


class RecordingEngine:
    def __init__(self):
        self.thread_id = None
        self.started = threading.Event()
        self.release = threading.Event()

    def inspect(self):
        return {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
        }

    def run(self, request, control, emit):
        self.thread_id = threading.get_ident()
        self.started.set()
        emit(
            "task.event",
            {
                "taskId": request.task_id,
                "itemId": request.items[0].item_id,
                "step": "window_bound",
                "outcome": "success",
                "detail": "bound",
                "done": 0,
                "total": 1,
                "timestamp": "2026-09-13T00:00:00+00:00",
            },
        )
        self.release.wait(1)
        return {"outcome": "success", "done": 1, "total": 1}


def message_request():
    return {
        "taskId": "task-1",
        "kind": "message_send",
        "items": [{"itemId": "item-1", "target": "文件传输助手"}],
        "options": {},
    }


def test_runtime_runs_automation_off_the_rpc_thread(qapp, qtbot):
    engine = RecordingEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    notices = []
    runtime.set_notification_sink(lambda method, params: notices.append((method, params)))

    caller_thread_id = threading.get_ident()
    reply = runtime.start_task(message_request())

    assert reply == {"accepted": True, "taskId": "task-1"}
    assert engine.started.wait(1)
    assert engine.thread_id != caller_thread_id
    qtbot.waitUntil(lambda: any(name == "task.event" for name, _ in notices))

    engine.release.set()
    qtbot.waitUntil(lambda: any(name == "task.finished" for name, _ in notices))
    assert runtime.active_task_id == ""
    runtime.close()


def test_runtime_rejects_concurrent_tasks(qapp):
    engine = RecordingEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    runtime.start_task(message_request())
    assert engine.started.wait(1)

    duplicate = dict(message_request(), taskId="task-2")
    try:
        runtime.start_task(duplicate)
    except ValueError as exc:
        assert "already active" in str(exc)
    else:
        raise AssertionError("concurrent task was accepted")

    engine.release.set()
    runtime.close()


def test_client_authenticates_and_receives_notifications(qapp, qtbot):
    engine = RecordingEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    name = "wechat-courier-client-test-" + uuid.uuid4().hex
    server = AgentServer(name, "secret", runtime, heartbeat_interval_ms=20)
    assert server.listen()

    client = AgentClient(heartbeat_timeout_ms=500)
    replies = []
    notices = []
    client.replyReceived.connect(lambda request_id, result: replies.append((request_id, result)))
    client.notificationReceived.connect(lambda method, params: notices.append((method, params)))
    client.connect_to_server(name, "secret")

    qtbot.waitUntil(lambda: client.connected, timeout=2_000)
    request_id = client.call("wechat.inspect")
    qtbot.waitUntil(lambda: any(item[0] == request_id for item in replies), timeout=2_000)
    inspection = next(result for item_id, result in replies if item_id == request_id)
    assert inspection["version"] == "4.1.13.65"
    qtbot.waitUntil(lambda: any(name == "heartbeat" for name, _ in notices), timeout=2_000)

    client.close()
    server.close()
    runtime.close()
    QLocalServer.removeServer(name)
