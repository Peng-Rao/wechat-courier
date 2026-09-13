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
    helloReceived = Signal(object)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.state = "connected"
        self.calls = []
        self.next_id = 1
        self.started = False
        self.restart_count = 0
        self.shutdown_count = 0

    def start(self):
        self.started = True

    def call(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        self.calls.append((request_id, method, params or {}))
        return request_id

    def close(self):
        pass

    def restart(self):
        self.restart_count += 1

    def shutdown(self):
        self.shutdown_count += 1


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
            "uiaReady": True,
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


def test_backend_shutdown_requests_graceful_agent_exit(tmp_path, qapp):
    backend, client = make_backend(tmp_path)

    backend.shutdown()

    assert client.shutdown_count == 1


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


def test_message_recipients_use_the_same_normalized_deduplication_as_agent(
    tmp_path, qapp
):
    backend, _client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\n alice \nＡｌｉｃｅ\nBob"

    assert backend.message.recipients() == ["Alice", "Bob"]


def test_async_task_start_rejection_releases_the_global_lock(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage() is True
    request_id = client.calls[-1][0]

    client.rpcError.emit(request_id, -32000, "Agent 拒绝了任务")

    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert backend.task.error == "Agent 拒绝了任务"


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


def test_supported_version_with_unavailable_uia_still_blocks_start(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "uiaReady": False,
            "detail": "UIA 控件树未就绪",
        }
    )
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"

    assert backend.agent.automationReady is False
    assert backend.task.startMessage() is False
    assert not any(method == "task.start" for _id, method, _payload in client.calls)


def test_supported_version_without_explicit_uia_readiness_still_blocks_start(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "detail": "legacy inspection response",
        }
    )
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"

    assert backend.agent.automationReady is False
    assert backend.task.startMessage() is False
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
        "task.event",
        {
            "taskId": task_id,
            "itemId": item_id,
            "step": "send_verified",
            "outcome": "success",
            "detail": "发送结果已确认",
            "done": 1,
            "total": 1,
            "timestamp": "2026-09-13T00:00:01+00:00",
        },
    )
    assert client.calls[-1][1:] == (
        "recovery.approve",
        {
            "decision": "acknowledge",
            "taskId": task_id,
            "itemId": item_id,
        },
    )

    client.notificationReceived.emit(
        "task.finished",
        {"taskId": task_id, "outcome": "success", "done": 1, "total": 1},
    )
    assert backend.task.active is False
    assert backend.task.phase == "done"


def test_agent_recovery_marks_boundary_item_unknown_and_resumes_remaining(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob\nCharlie"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    original = client.calls[-1][2]
    task_id = original["taskId"]
    first, second, third = original["items"]

    client.notificationReceived.emit(
        "task.event",
        {
            "taskId": task_id,
            "itemId": first["itemId"],
            "step": "send_verified",
            "outcome": "success",
            "detail": "发送结果已确认",
            "done": 1,
            "total": 3,
            "timestamp": "2026-09-13T00:00:00+00:00",
        },
    )

    client.connected = False
    client.connectedChanged.emit(False)
    assert backend.task.phase == "recovering"
    assert client.restart_count == 1

    client.connected = True
    client.connectedChanged.emit(True)
    client.helloReceived.emit(
        {
            "recovery": {
                "taskId": task_id,
                "kind": "message_send",
                "itemId": second["itemId"],
                "boundary": "send_triggered",
                "itemIndex": 1,
                "timestamp": "2026-09-13T00:00:01+00:00",
            }
        }
    )
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "uiaReady": True,
            "detail": "ready",
        }
    )

    recovery_calls = [(method, payload) for _id, method, payload in client.calls]
    assert ("recovery.approve", {"decision": "mark_unknown"}) in recovery_calls
    resumed = [payload for _id, method, payload in client.calls if method == "task.start"][-1]
    assert [item["itemId"] for item in resumed["items"]] == [third["itemId"]]
    assert backend.task.done == 2
    assert backend.task.phase == "running"
    assert backend.task.items._items[1].result == "unknown"

    client.notificationReceived.emit(
        "task.event",
        {
            "taskId": task_id,
            "itemId": third["itemId"],
            "step": "send_verified",
            "outcome": "success",
            "detail": "发送结果已确认",
            "done": 1,
            "total": 1,
            "timestamp": "2026-09-13T00:00:02+00:00",
        },
    )
    assert backend.task.done == 3
    assert backend.task.total == 3


def test_agent_restart_limit_stops_active_task_safely(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.settings.agentRestartLimit = 0
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)

    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert "重启次数" in backend.task.error


def test_merged_forward_task_is_not_resumed_after_agent_disconnect(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob"
    backend.message.templateText = "hello"
    backend.message.useForward = True
    backend.message._files = ["one.pdf"]
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)

    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert "不会自动恢复" in backend.task.error
    assert client.restart_count == 1


def test_unavailable_uia_requests_one_confirmed_wechat_restart(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)
    client.connected = True
    client.connectedChanged.emit(True)
    client.helloReceived.emit({"recovery": None})
    backend.task._check_reconnect_inspection()

    assert backend.task.recoveryRequired is True
    assert backend.task.phase == "awaiting_recovery"

    backend.task.approveWechatRestart()
    backend.task.approveWechatRestart()

    restart_wechat_calls = [
        payload
        for _id, method, payload in client.calls
        if method == "recovery.approve" and payload.get("decision") == "restart_wechat"
    ]
    assert restart_wechat_calls == [
        {"decision": "restart_wechat", "loginTimeout": 90}
    ]
    assert backend.task.recoveryRequired is False
    assert backend.task.phase == "waiting_login"
