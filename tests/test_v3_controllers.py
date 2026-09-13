from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

from app.backend import BackendController


class FakeAgentClient(QObject):
    stateChanged = Signal(str)
    connectedChanged = Signal(bool)
    replyReceived = Signal(int, object)
    rpcError = Signal(int, int, str)
    notificationReceived = Signal(str, object)
    processError = Signal(str)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.state = "connected"
        self.calls = []
        self.next_id = 1
        self.started = False

    def start(self):
        self.started = True

    def call(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        self.calls.append((request_id, method, params or {}))
        return request_id

    def close(self):
        pass


def settings(tmp_path):
    return QSettings(str(tmp_path / "v3.ini"), QSettings.IniFormat)


def make_backend(tmp_path):
    client = FakeAgentClient()
    backend = BackendController(
        version="0.3.0-test",
        settings=settings(tmp_path),
        agent_client=client,
    )
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "detail": "ready",
        }
    )
    return backend, client


def test_backend_exposes_five_stable_qobject_facades(tmp_path, qapp):
    backend, _client = make_backend(tmp_path)

    assert isinstance(backend.message, QObject)
    assert isinstance(backend.friends, QObject)
    assert isinstance(backend.task, QObject)
    assert isinstance(backend.settings, QObject)
    assert isinstance(backend.agent, QObject)
    assert backend.versionInfo == "五阿哥微信助手 v0.3.0-test"


def test_message_task_is_built_for_the_agent_and_is_globally_exclusive(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob"
    backend.message.templateText = "{name}，你好"

    assert backend.task.startMessage() is True
    _request_id, method, payload = client.calls[-1]
    assert method == "task.start"
    assert payload["kind"] == "message_send"
    assert [item["target"] for item in payload["items"]] == ["Alice", "Bob"]
    assert [item["message"] for item in payload["items"]] == [
        "Alice，你好",
        "Bob，你好",
    ]
    assert backend.task.startFriends() is False


def test_unsupported_weixin_version_blocks_start_but_not_editing(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.14.1",
            "supported": False,
            "detail": "unsupported",
        }
    )
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"

    assert backend.task.startMessage() is False
    assert backend.message.recipientsText == "Alice"
    assert not any(method == "task.start" for _id, method, _payload in client.calls)


def test_friend_task_uses_default_precedence_and_limits(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.friends.model.replace_records(
        __import__("app.friend_import", fromlist=["load_friend_records"])
        .load_friend_records(
            [
                ["账号", "打招呼语", "备注"],
                ["18896904196", "行内问候", ""],
            ]
        )
    )
    backend.friends.defaultGreeting = "默认问候"
    backend.friends.defaultRemark = "默认备注"

    assert backend.task.startFriends() is True
    payload = client.calls[-1][2]
    assert payload["kind"] == "friend_add"
    assert payload["items"][0]["greeting"] == "行内问候"
    assert payload["items"][0]["remark"] == "默认备注"


def test_task_events_update_monitor_and_release_global_lock(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    task_id = client.calls[-1][2]["taskId"]
    item_id = client.calls[-1][2]["items"][0]["itemId"]

    client.notificationReceived.emit(
        "task.event",
        {
            "taskId": task_id,
            "itemId": item_id,
            "step": "target_verified",
            "outcome": "success",
            "detail": "目标校验通过",
            "done": 0,
            "total": 1,
            "timestamp": "2026-09-13T00:00:00+00:00",
        },
    )
    assert backend.task.currentStepCode == "target_verified"
    assert backend.task.currentStepLabel == "目标校验通过"
    assert backend.task.runtimeLogs.rowCount() == 1

    client.notificationReceived.emit(
        "task.finished",
        {"taskId": task_id, "outcome": "success", "done": 1, "total": 1},
    )
    assert backend.task.active is False
    assert backend.task.phase == "done"
