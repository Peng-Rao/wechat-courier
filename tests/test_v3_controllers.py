from __future__ import annotations

import json
import zipfile

import pytest
from PySide6.QtCore import QObject, QSettings, Signal

from app.backend import BackendController


def test_finished_batch_marks_unstarted_rows_without_counting_them_as_failures(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob\nCarol"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    payload = client.calls[-1][2]
    client.notificationReceived.emit("task.event", {
        "taskId": payload["taskId"], "itemId": payload["items"][0]["itemId"],
        "step": "search_ready", "outcome": "error", "detail": "window blocked",
        "done": 1, "total": 3, "errorCode": "WINDOW_BLOCKED",
    })
    client.notificationReceived.emit("task.finished", {
        "taskId": payload["taskId"], "outcome": "error", "done": 1, "total": 3,
    })
    rows = backend.task._items._items
    assert [row.result for row in rows] == ["error", "stopped", "stopped"]
    assert all("未执行" in row.detail for row in rows[1:])
    assert backend.task.failureCount == 1
    assert backend.task.done == 1
    assert not backend.task.active


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
        self.safety_record = None

    def start(self):
        self.started = True

    def call(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        self.calls.append((request_id, method, params or {}))
        return request_id

    def grant_foreground_permission(self):
        return True

    def close(self):
        pass

    def restart(self):
        self.restart_count += 1

    def shutdown(self):
        self.shutdown_count += 1

    def recovery_snapshot(self):
        return self.safety_record


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


def fire_scheduled_agent_restart(backend):
    backend.task._agent_restart_timer.stop()
    backend.task._perform_agent_restart()


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


def test_agent_controller_exposes_distinct_process_version_and_session_health(
    tmp_path, qapp
):
    backend, _client = make_backend(tmp_path)
    backend.agent.applyInspection(
        {
            "processDetected": True,
            "versionSupported": True,
            "sessionReady": False,
            "windowResponsive": False,
            "sessionGeneration": 3,
            "degradedReason": "WECHAT_UNRESPONSIVE",
            "version": "4.1.13.65",
        }
    )

    assert backend.agent.processDetected is True
    assert backend.agent.versionSupported is True
    assert backend.agent.sessionReady is False
    assert backend.agent.windowResponsive is False
    assert backend.agent.sessionGeneration == 3
    assert backend.agent.degradedReason == "WECHAT_UNRESPONSIVE"
    assert backend.agent.automationReady is False


def test_hidden_verified_weixin_is_task_ready_when_backend_can_restore_it(
    tmp_path, qapp
):
    backend, _client = make_backend(tmp_path)
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "uiaReady": False,
            "windowState": "hidden",
            "restorable": True,
            "detail": "窗口位于托盘，任务开始时可恢复",
        }
    )

    assert backend.agent.uiaReady is False
    assert backend.agent.automationReady is False
    assert backend.agent.canStartTask is True


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
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
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
    assert payload["options"]["submitFriendRequest"] is True


def test_friend_task_refuses_agent_without_submit_capability(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False}})
    backend.friends.model.replace_records(
        __import__("app.friend_import", fromlist=["load_friend_records"])
        .load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", ""]]
        )
    )

    assert backend.task.startFriends() is False
    assert "提交能力" in backend.task.error
    assert not any(method == "task.start" for _id, method, _payload in client.calls)


def test_task_kind_has_its_own_notify_signal(tmp_path, qapp, qtbot):
    backend, _client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"

    assert hasattr(backend.task, "kindChanged"), "kind 不能继续借用 phaseChanged"
    with qtbot.waitSignal(backend.task.kindChanged, timeout=1000):
        assert backend.task.startMessage() is True
    assert backend.task.kind == "message_send"


def test_friend_interval_accepts_one_second_and_normalizes_persisted_bounds(
    tmp_path, qapp
):
    stored = settings(tmp_path)
    stored.setValue("friends/intervalMin", 0)
    stored.setValue("friends/intervalMax", 999)
    client = FakeAgentClient()
    backend = BackendController(
        version="0.3.3-test",
        settings=stored,
        agent_client=client,
    )

    assert backend.friends.intervalMin == 1.0
    assert backend.friends.intervalMax == 300.0

    backend.friends.intervalMax = 1
    backend.friends.intervalMin = 1
    assert backend.friends.intervalMin == 1.0
    assert backend.friends.intervalMax == 1.0


def test_acceptance_mode_keeps_friend_task_as_non_submitting_preflight(
    tmp_path, qapp, monkeypatch
):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False}})
    backend.friends.model.replace_records(
        __import__("app.friend_import", fromlist=["load_friend_records"])
        .load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", ""]]
        )
    )

    assert backend.task.startFriends() is True
    payload = client.calls[-1][2]
    assert payload["kind"] == "friend_add"
    assert payload["options"]["submitFriendRequest"] is False


@pytest.mark.parametrize("capabilities", [{"friendSubmitEnabled": False}, {}])
def test_friend_task_recovery_refuses_replacement_agent_without_submit_capability(
    tmp_path, qapp, capabilities
):
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.friends.model.replace_records(
        __import__("app.friend_import", fromlist=["load_friend_records"])
        .load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", ""]]
        )
    )
    assert backend.task.startFriends() is True
    assert len([call for call in client.calls if call[1] == "task.start"]) == 1

    client.connected = False
    client.connectedChanged.emit(False)
    assert backend.task.phase == "recovering"
    fire_scheduled_agent_restart(backend)
    client.connected = True
    client.connectedChanged.emit(True)
    client.helloReceived.emit({"recovery": None, "capabilities": capabilities})

    assert len([call for call in client.calls if call[1] == "task.start"]) == 1
    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert "提交能力" in backend.task.error


def test_friend_task_rechecks_submit_capability_immediately_before_resume(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.friends.model.replace_records(
        __import__("app.friend_import", fromlist=["load_friend_records"])
        .load_friend_records(
            [["账号", "打招呼语", "备注"], ["18896904196", "你好", ""]]
        )
    )
    assert backend.task.startFriends() is True

    client.connected = False
    client.connectedChanged.emit(False)
    fire_scheduled_agent_restart(backend)
    client.connected = True
    client.connectedChanged.emit(True)
    client.helloReceived.emit(
        {"recovery": None, "capabilities": {"friendSubmitEnabled": True}}
    )
    assert backend.task._pending_resume is True

    backend.agent._friend_submit_enabled = False
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "uiaReady": True,
            "detail": "ready",
        }
    )

    assert len([call for call in client.calls if call[1] == "task.start"]) == 1
    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert "提交能力" in backend.task.error


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


def test_agent_recovery_marks_boundary_item_unknown_and_stops_batch(
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
    assert client.restart_count == 0
    assert backend.task._agent_restart_timer.interval() == 2_000
    fire_scheduled_agent_restart(backend)
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
    starts = [payload for _id, method, payload in client.calls if method == "task.start"]
    assert len(starts) == 1
    assert backend.task.done == 2
    assert backend.task.phase == "error"
    assert backend.task.active is False
    assert backend.task.items._items[1].result == "unknown"
    assert backend.task.items._items[2].result == "pending"
    assert "不会自动恢复" in backend.task.error


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
    fire_scheduled_agent_restart(backend)
    assert client.restart_count == 1


def test_unavailable_uia_requests_one_confirmed_wechat_restart(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)
    fire_scheduled_agent_restart(backend)
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


def test_refreshed_but_empty_uia_tree_stops_without_a_restart_loop(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)
    fire_scheduled_agent_restart(backend)
    client.connected = True
    client.connectedChanged.emit(True)
    client.helloReceived.emit({"recovery": None})
    backend.agent.applyInspection(
        {
            "connected": True,
            "processDetected": True,
            "version": "4.1.13.65",
            "supported": True,
            "versionSupported": True,
            "uiaReady": False,
            "sessionReady": False,
            "windowResponsive": True,
            "windowEnabled": True,
            "degradedReason": "UIA_TREE_NOT_READY_AFTER_REFRESH",
            "detail": "可访问性广播已刷新，但微信仍只暴露壳节点",
        }
    )

    backend.task._check_reconnect_inspection()

    restart_wechat_calls = [
        payload
        for _id, method, payload in client.calls
        if method == "recovery.approve"
        and payload.get("decision") == "restart_wechat"
    ]
    assert restart_wechat_calls == []
    assert backend.task.recoveryRequired is False
    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert "广播已刷新" in backend.task.error


def test_agent_restarts_use_two_and_five_second_backoff(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()

    client.connected = False
    client.connectedChanged.emit(False)
    assert backend.task._agent_restart_timer.isActive()
    assert backend.task._agent_restart_timer.interval() == 2_000
    fire_scheduled_agent_restart(backend)

    client.connected = True
    client.connectedChanged.emit(True)
    client.connected = False
    client.connectedChanged.emit(False)
    assert backend.task._agent_restart_timer.isActive()
    assert backend.task._agent_restart_timer.interval() == 5_000
    fire_scheduled_agent_restart(backend)

    assert client.restart_count == 2


def test_boundary_record_marks_unknown_and_never_resumes_batch(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    payload = client.calls[-1][2]
    client.safety_record = {
        "taskId": payload["taskId"],
        "kind": "message_send",
        "itemId": payload["items"][0]["itemId"],
        "boundary": "send_triggered",
        "itemIndex": 0,
        "timestamp": "2026-09-14T00:00:00+00:00",
    }

    client.connected = False
    client.connectedChanged.emit(False)

    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert backend.task.items._items[0].result == "unknown"
    assert backend.task.destructiveBoundaryCrossed is True
    assert backend.task.safeRetryAvailable is False
    assert "不会自动重发" in backend.task.recoveryHint
    fire_scheduled_agent_restart(backend)
    assert client.restart_count == 1


def test_failed_event_exposes_counts_and_safe_retry_permissions(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    payload = client.calls[-1][2]

    client.notificationReceived.emit(
        "task.event",
        {
            "taskId": payload["taskId"],
            "itemId": payload["items"][0]["itemId"],
            "step": "window_bound",
            "outcome": "error",
            "detail": "bind_window failed",
            "done": 1,
            "total": 1,
            "timestamp": "2026-09-14T00:00:00+00:00",
            "attempt": 3,
            "maxAttempts": 3,
            "retryLevel": "same_session",
            "recoverable": True,
            "destructiveBoundaryCrossed": False,
            "wechatResponsive": True,
            "errorCode": "TRANSIENT_UI",
        },
    )
    client.notificationReceived.emit(
        "task.finished",
        {
            "taskId": payload["taskId"],
            "outcome": "error",
            "done": 1,
            "total": 1,
            "success": 0,
            "error": 1,
            "unknown": 0,
        },
    )

    assert backend.task.successCount == 0
    assert backend.task.failureCount == 1
    assert backend.task.unknownCount == 0
    assert backend.task.currentOutcome == "error"
    assert backend.task.currentErrorCode == "TRANSIENT_UI"
    assert backend.task.retryAttempt == 3
    assert backend.task.retryMaxAttempts == 3
    assert backend.task.safeRetryAvailable is True

    previous_starts = len([call for call in client.calls if call[1] == "task.start"])
    assert backend.task.retryFailedItem() is True
    starts = [call for call in client.calls if call[1] == "task.start"]
    assert len(starts) == previous_starts + 1
    assert len(starts[-1][2]["items"]) == 1


def test_diagnostics_export_bundles_rotating_logs_and_safe_summary(
    tmp_path, qapp, monkeypatch
):
    local_app_data = tmp_path / "local"
    log_dir = local_app_data / "WxAuto" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "uia-diagnostics.jsonl").write_text(
        '{"stage":"window_bound","outcome":"error"}\n', encoding="utf-8"
    )
    (log_dir / "uia-diagnostics.jsonl.1").write_text(
        '{"stage":"inspect","outcome":"success"}\n', encoding="utf-8"
    )
    (log_dir / "agent-stderr.log").write_text("agent error\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    backend, _client = make_backend(tmp_path)

    destination = tmp_path / "wechat-diagnostics.zip"
    assert backend.task.exportDiagnostics(str(destination)) is True

    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert "diagnostic-summary.json" in names
        assert "logs/uia-diagnostics.jsonl" in names
        assert "logs/uia-diagnostics.jsonl.1" in names
        assert "logs/agent-stderr.log" in names
        summary = json.loads(archive.read("diagnostic-summary.json"))
    assert summary["schemaVersion"] == 1
    assert summary["wechatVersion"] == "4.1.13.65"
    assert summary["sessionReady"] is True


def test_unresponsive_failure_offers_detection_and_one_explicit_restart(
    tmp_path, qapp
):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    payload = client.calls[-1][2]

    client.notificationReceived.emit(
        "task.event",
        {
            "taskId": payload["taskId"],
            "itemId": payload["items"][0]["itemId"],
            "step": "window_bound",
            "outcome": "error",
            "detail": "微信窗口无响应",
            "done": 1,
            "total": 1,
            "timestamp": "2026-09-14T00:00:00+00:00",
            "recoverable": False,
            "destructiveBoundaryCrossed": False,
            "wechatResponsive": False,
            "errorCode": "WECHAT_UNRESPONSIVE",
        },
    )
    client.notificationReceived.emit(
        "task.finished",
        {
            "taskId": payload["taskId"],
            "outcome": "error",
            "done": 1,
            "total": 1,
        },
    )

    assert backend.task.wechatResponsive is False
    assert backend.task.safeRetryAvailable is False
    assert backend.task.wechatRestartAvailable is True

    before_inspect = len([call for call in client.calls if call[1] == "wechat.inspect"])
    backend.task.detectWechatRecovery()
    after_inspect = len([call for call in client.calls if call[1] == "wechat.inspect"])
    assert after_inspect == before_inspect + 1

    assert backend.task.restartWechatAfterFailure() is True
    assert backend.task.restartWechatAfterFailure() is False
    restart_calls = [
        call for call in client.calls
        if call[1] == "recovery.approve"
        and call[2].get("decision") == "restart_wechat"
    ]
    assert len(restart_calls) == 1
