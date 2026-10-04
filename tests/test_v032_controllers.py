from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.agent.diagnostics import redact_identifier
from tests.test_v3_controllers import make_backend


def health(sequence=1, instance="agent-a", **changes):
    return {
        "sequence": sequence,
        "agentInstanceId": instance,
        "checkedAt": "2026-09-14T08:00:00+00:00",
        "reasonCode": "READY",
        "processDetected": True,
        "versionSupported": True,
        "sessionReady": True,
        "sessionGeneration": 7,
        "windowResponsive": True,
        "windowEnabled": True,
        "blockingWindow": None,
        "restorable": False,
        "version": "4.1.13.65",
        "detail": "ready",
        **changes,
    }


def status(client, snapshot):
    client.notificationReceived.emit("agent.status", {"status": "health", "health": snapshot})


def start_message(backend, client):
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    return client.calls[-1][2]


def event(client, payload, **changes):
    value = {
        "taskId": payload["taskId"],
        "itemId": payload["items"][0]["itemId"],
        "step": "window_bound",
        "outcome": "error",
        "done": 1,
        "total": 1,
        "recoverable": True,
        "destructiveBoundaryCrossed": False,
        "wechatResponsive": True,
        "sessionGeneration": 7,
        **changes,
    }
    client.notificationReceived.emit("task.event", value)
    return value


def finish(client, payload, **changes):
    client.notificationReceived.emit("task.finished", {
        "taskId": payload["taskId"], "done": 1, "total": 1,
        "outcome": "success", **changes,
    })


def test_status_health_is_applied_before_forwarding_and_rejects_stale_inspect(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    request = backend.agent.inspect()
    seen = []
    backend.agent.notificationReceived.connect(
        lambda *_: seen.append(backend.agent.sessionGeneration)
    )
    status(client, health(3))
    assert seen == [7]
    client.replyReceived.emit(request, health(2, sessionGeneration=2))
    status(client, health(3, sessionGeneration=3))
    assert backend.agent.sessionGeneration == 7
    assert backend.agent.healthSnapshot == health(3)
    snapshot = backend.agent.healthSnapshot
    snapshot["sequence"] = 99
    assert backend.agent.healthSnapshot["sequence"] == 3


def test_stopped_failed_task_unlocks_on_fresh_health_without_auto_start(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, step="search_ready", errorCode="TRANSIENT_UI")
    backend.task.stop()
    status(client, health(2, sessionReady=False, reasonCode="TRANSIENT_UI"))
    status(client, health(3))
    assert backend.task.active is True
    assert backend.agent.automationReady is True
    assert backend.task.startMessage() is False
    finish(client, payload, outcome="error", cleanup={"success": True}, health=health(3))

    assert backend.task.active is False
    assert backend.task.failureCount == 1
    assert backend.task.currentStepLabel == "搜索入口准备失败"
    assert backend.task.safeRetryAvailable is True
    assert backend.agent.canStartTask is True
    assert client.restart_count == 0
    assert len([c for c in client.calls if c[1] == "task.start"]) == 1
    status(client, health(2, sessionReady=False, reasonCode="TRANSIENT_UI"))
    assert backend.agent.automationReady is True
    assert backend.task.startMessage() is True


def test_unknown_stopped_item_is_not_retryable_after_automatic_health_restore(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, step="send_verified", outcome="unknown", errorCode="RESULT_UNKNOWN",
          destructiveBoundaryCrossed=True)
    backend.task.stop()
    status(client, health(3))
    finish(client, payload, outcome="unknown", cleanup={"success": True})
    assert backend.agent.automationReady is True
    assert backend.task.unknownCount == 1
    assert backend.task.safeRetryAvailable is False
    assert backend.task.retryFailedItem() is False
    assert len([c for c in client.calls if c[1] == "task.start"]) == 1


def test_manual_recovery_check_does_not_queue_another_inspection_during_stop(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    backend.task.stop()
    before = len(client.calls)
    backend.task.detectWechatRecovery()
    assert len(client.calls) == before
    finish(client, payload, outcome="stopped")
    backend.task.detectWechatRecovery()
    assert client.calls[-1][1] == "wechat.inspect"


@pytest.mark.parametrize("reason", ["CLEANUP_FAILED", "HEALTH_CHECK_FAILED", "EVENT_CLEANUP_FAILED",
                                   "WINDOW_BLOCKED", "WINDOW_DISABLED", "ACTION_DEADLINE_EXCEEDED"])
def test_recovery_hint_reports_environment_failure_instead_of_a_safe_retry(reason, tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, errorCode="TRANSIENT_UI")
    status(client, health(2, sessionReady=False, reasonCode=reason))
    finish(client, payload, outcome="error")
    assert "检测微信恢复" in backend.task.recoveryHint
    assert "可在任务结束后安全重试本条" not in backend.task.recoveryHint


@pytest.mark.parametrize("code", ["RISK_CONTROL", "GATE_SAFETY", "RESULT_UNKNOWN"])
def test_cleanup_failure_keeps_task_safety_guidance(code, tmp_path, qapp):
    from app.controllers import ERROR_RECOVERY_HINTS

    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, errorCode=code, destructiveBoundaryCrossed=code == "RESULT_UNKNOWN")
    status(client, health(2, sessionReady=False, reasonCode="CLEANUP_FAILED"))
    finish(client, payload, outcome="error", cleanup={"success": False})

    assert ERROR_RECOVERY_HINTS[code] in backend.task.recoveryHint
    assert "检测微信恢复" in backend.task.recoveryHint


def test_disconnect_notifies_cleared_health_and_accepts_new_instance(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    status(client, health(90))
    old_request = backend.agent.inspect()
    observed = []
    backend.agent.inspectionChanged.connect(
        lambda: observed.append((backend.agent.sessionReady, backend.agent.windowResponsive))
    )
    client.connectedChanged.emit(False)
    assert observed[-1] == (False, False)
    assert backend.agent.canStartTask is False
    status(client, health(91))
    assert backend.agent.sessionReady is False
    client.connectedChanged.emit(True)
    client.replyReceived.emit(old_request, health(92))
    assert backend.agent.sessionReady is False
    status(client, health(1, "agent-b", sessionGeneration=1))
    assert backend.agent.automationReady is True
    assert backend.agent.sessionGeneration == 1
    status(client, health(93))
    assert backend.agent.healthSnapshot["agentInstanceId"] == "agent-b"


def test_same_instance_reconnect_retains_sequence_and_accepts_new_health(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    status(client, health(90))
    client.connectedChanged.emit(False)
    client.connectedChanged.emit(True)
    status(client, health(89))
    assert backend.agent.sessionReady is False
    status(client, health(91))
    assert backend.agent.automationReady is True
    assert backend.agent.healthSnapshot["sequence"] == 91


@pytest.mark.parametrize("with_attachment", [False, True])
def test_stop_disconnect_releases_lock_without_replay_or_cleanup_claim(tmp_path, qapp, monkeypatch, with_attachment):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    backend, client = make_backend(tmp_path)
    if with_attachment:
        backend.message.addFile(str(tmp_path / "test.txt"))
    start_message(backend, client)
    backend.task.stop()
    unlocked = []
    backend.task.activeChanged.connect(lambda: unlocked.append((
        backend.task.active, backend.task.phase, backend.task._pending_start_request_id,
    )))
    client.connectedChanged.emit(False)

    assert unlocked == [(False, "error", 0)]
    assert backend.task._pending_resume is False
    assert backend.task._restart_scheduled is False
    assert not backend.task._agent_restart_timer.isActive()
    assert not backend.task._inspection_grace.isActive()
    assert not backend.task._recovery_poll.isActive()
    assert backend.task.cleanupResult == {}
    assert backend.task.acceptanceTaskState["outcome"] == "error"
    assert backend.task.acceptanceTaskState["cleanup"] == {}
    assert backend.task.acceptanceTaskState["health"] == {}
    assert backend.task.error
    client.connectedChanged.emit(True)
    client.helloReceived.emit({"recovery": None})
    status(client, health())
    backend.task._perform_agent_restart()
    assert client.restart_count == 0
    assert len([call for call in client.calls if call[1] == "task.start"]) == 1


@pytest.mark.parametrize("outcome", ["success", "unknown", "error"])
def test_stop_disconnect_preserves_terminal_item_and_disallows_retry(tmp_path, qapp, outcome):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, step="send_verified" if outcome != "error" else "window_bound", outcome=outcome)
    client.safety_record = {"taskId": payload["taskId"], "itemId": payload["items"][0]["itemId"],
                            "boundary": "send_triggered"}
    backend.task.stop()
    client.connectedChanged.emit(False)
    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert backend.task.items._items[0].result == outcome
    assert backend.task.done == 1
    assert backend.task.cleanupResult == {}
    client.connectedChanged.emit(True)
    status(client, health())
    assert backend.task.safeRetryAvailable is False
    assert backend.task.retryFailedItem() is False


@pytest.mark.parametrize("boundary_source", ["journal", "event"])
def test_stop_disconnect_marks_unresolved_boundary_unknown_preserving_verified_item(tmp_path, qapp, boundary_source):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Alice\nBob"
    backend.message.templateText = "hello"
    assert backend.task.startMessage()
    payload = client.calls[-1][2]
    event(client, payload, step="send_verified", outcome="success", done=1, total=2)
    second_id = payload["items"][1]["itemId"]
    if boundary_source == "journal":
        client.safety_record = {"taskId": payload["taskId"], "itemId": second_id,
                                "boundary": "send_triggered"}
    else:
        event(client, payload, itemId=second_id, step="send_triggered", outcome="working",
              destructiveBoundaryCrossed=True, done=1, total=2)
    backend.task.stop()
    client.connectedChanged.emit(False)
    assert backend.task.active is False
    assert backend.task.phase == "error"
    assert [item.result for item in backend.task.items._items] == ["success", "unknown"]
    assert backend.task.done == 2
    assert backend.task.currentOutcome == "unknown"
    assert backend.task.cleanupResult == {}
    assert len([call for call in client.calls if call[1] == "task.start"]) == 1


@pytest.mark.parametrize("changes,can_start,ready", [
    ({}, True, True),
    ({"sessionReady": False, "restorable": True}, True, False),
    ({"sessionReady": False}, False, False),
    ({"windowEnabled": False, "restorable": True}, False, False),
    ({"windowResponsive": False, "restorable": True}, False, False),
    ({"blockingWindow": {"hwnd": 123}, "restorable": True}, False, False),
    ({"versionSupported": False, "restorable": True}, False, False),
    ({"processDetected": False, "restorable": True}, False, False),
    ({"sessionReady": False, "restorable": True, "reasonCode": "CLEANUP_FAILED"}, False, False),
    ({"sessionReady": False, "restorable": True, "reasonCode": "GATE_SAFETY"}, False, False),
    ({"sessionReady": False, "restorable": True, "reasonCode": "HEALTH_CHECK_FAILED"}, False, False),
])
def test_task_eligibility_is_distinct_from_session_readiness(tmp_path, qapp, changes, can_start, ready):
    backend, client = make_backend(tmp_path)
    backend.agent.applyInspection(health(**changes))
    assert backend.agent.canStartTask is can_start
    assert backend.agent.automationReady is ready
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    assert backend.task.startMessage() is can_start


def test_foreground_permission_is_granted_before_every_start(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    ordering = []
    original_call = client.call
    client.grant_foreground_permission = lambda: ordering.append("grant")

    def record_call(method, params=None):
        ordering.append(method)
        return original_call(method, params)

    client.call = record_call
    payload = start_message(backend, client)
    assert ordering[-2:] == ["grant", "task.start"]
    event(client, payload)
    finish(client, payload, outcome="error")
    assert backend.task.retryFailedItem()
    assert ordering[-2:] == ["grant", "task.start"]
    backend.task._pending_resume = True
    backend.task._resume_if_ready()
    assert ordering[-2:] == ["grant", "task.start"]


def test_cleanup_failure_preserves_confirmed_send_and_revokes_retry(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, done=0)
    event(client, payload, step="send_verified", outcome="success", done=1)
    cleanup = {"success": False, "reasonCode": "WINDOW_DISABLED", "detail": "blocked"}
    status(client, health(2, windowEnabled=False, reasonCode="WINDOW_DISABLED"))
    finish(client, payload, cleanup=cleanup)
    assert backend.task.cleanupResult == cleanup
    assert backend.task.cleanupFailed is True
    assert backend.task.currentOutcome == "success"
    assert backend.task.successCount == 1
    assert backend.task.failureCount == 0
    assert backend.task.safeRetryAvailable is False
    status(client, health(3))
    event(client, payload, step="window_bound", outcome="error", recoverable=True)
    assert backend.task.safeRetryAvailable is False
    assert backend.task.retryFailedItem() is False


@pytest.mark.parametrize("changes", [
    {"step": "send_triggered", "outcome": "working", "destructiveBoundaryCrossed": True},
    {"step": "send_verified", "outcome": "unknown"},
    {"step": "window_bound", "outcome": "error", "recoverable": False},
])
def test_later_unsafe_event_revokes_previous_retry_candidate(tmp_path, qapp, changes):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, done=0)
    event(client, payload, **changes)
    finish(client, payload, outcome="error")
    assert backend.task.safeRetryAvailable is False


def test_failure_step_label_is_used_in_export(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, step="target_verified")
    assert backend.task.currentStepLabel == "目标校验失败"
    destination = tmp_path / "results.csv"
    assert backend.task.exportResults(str(destination))
    source = destination.read_text(encoding="utf-8-sig")
    assert "目标校验失败" in source
    assert "目标校验通过" not in source


def test_diagnostics_preserve_health_and_event_generation_after_disconnect(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    backend, client = make_backend(tmp_path)
    status(client, health())
    payload = start_message(backend, client)
    sent = event(client, payload, step="send_verified", outcome="success", sessionGeneration=6)
    cleanup = {"success": True, "reasonCode": "READY", "detail": "restored"}
    finish(client, payload, cleanup=cleanup)
    client.connectedChanged.emit(False)
    destination = tmp_path / "diagnostics.zip"
    assert backend.task.exportDiagnostics(str(destination))
    with zipfile.ZipFile(destination) as archive:
        summary = json.loads(archive.read("diagnostic-summary.json"))
        events = [json.loads(line) for line in archive.read("task-events.jsonl").splitlines()]
    assert summary["agentConnected"] is False
    assert summary["health"] == {**health(), "detail": redact_identifier("ready")}
    assert summary["cleanup"] == {**cleanup, "detail": redact_identifier("restored")}
    assert summary["sessionGeneration"] == 7
    assert events[0]["sessionGeneration"] == sent["sessionGeneration"]
    assert events[-1]["cleanup"] == summary["cleanup"]


def test_acceptance_metadata_is_opt_in_and_hello_is_not_inferred(tmp_path, qapp, monkeypatch):
    monkeypatch.delenv("WECHAT_COURIER_ACCEPTANCE", raising=False)
    backend, client = make_backend(tmp_path)
    assert backend.task.acceptanceEnabled is False
    assert backend.task.acceptanceMessageState == {}
    assert backend.task.acceptanceFriendState == {}
    assert backend.task.acceptanceTaskState == {}
    assert backend.task.acceptanceMessageStateJson == "{}"
    assert backend.task.acceptanceFriendStateJson == "{}"
    assert backend.task.acceptanceTaskStateJson == "{}"
    assert backend.agent.friendSubmitEnabled is None
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False}})
    assert backend.agent.friendSubmitEnabled is False
    client.connectedChanged.emit(False)
    assert backend.agent.friendSubmitEnabled is None


def test_acceptance_metadata_is_stable_notified_and_correlated_to_actual_task(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    backend, client = make_backend(tmp_path)
    changed = []
    backend.task.acceptanceStateChanged.connect(lambda: changed.append(True))
    assert backend.task.acceptanceMessageState["friendSubmitEnabled"] is None
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False}})
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    backend.message.intervalMin = 2.5
    assert len(changed) >= 4
    editor = backend.task.acceptanceMessageState
    assert editor == backend.task.acceptanceMessageState
    assert editor == {
        "active": False, "friendSubmitEnabled": False, "kind": "message_send",
        "items": [{"target": "Alice", "message": "hello"}],
        "options": {"intervalMin": 2.5, "intervalMax": 3.0, "unknownPolicy": "continue",
                    "filePaths": [], "fuzzySearchEnabled": False},
    }
    backend.friends.model.appendEmptyRecord()
    backend.friends.model.setCell(0, "account", "wxid_demo")
    backend.friends.model.setCell(0, "greeting", "greeting")
    backend.friends.model.setCell(0, "name", "remark")
    backend.friends.model.setCell(0, "relationship", "无")
    assert backend.friends.model.selectRange(1, 1)
    friend = backend.task.acceptanceFriendState
    assert friend["items"] == [{"account": "wxid_demo", "greeting": "greeting", "remark": "remark",
                                "sourceRow": 1, "sourceFileRow": 0}]
    assert friend["options"]["filePaths"] == []
    assert "useForward" not in friend["options"]
    payload = start_message(backend, client)
    sent = event(client, payload, step="send_verified", outcome="success")
    finish(client, payload)
    state = backend.task.acceptanceTaskState
    assert state["taskId"] == payload["taskId"]
    assert state["echoedItems"] == payload["items"]
    assert state["events"] == [{key: sent[key] for key in ("taskId", "itemId", "step", "outcome")}]
    assert (state["outcome"], state["done"], state["success"], state["error"], state["unknown"], state["stopped"]) == (
        "success", 1, 1, 0, 0, 0,
    )
    assert state["active"] is False
    assert state["phase"] == "done"
    state["echoedItems"][0]["message"] = "mutated"
    assert backend.task.acceptanceTaskState["echoedItems"][0]["message"] == "hello"


def test_diagnostic_export_redacts_payload_text(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    event(client, payload, detail="private-content", target="private-recipient", message="private-body")
    destination = tmp_path / "redacted.zip"
    assert backend.task.exportDiagnostics(str(destination))
    with zipfile.ZipFile(destination) as archive:
        text = archive.read("task-events.jsonl").decode("utf-8")
    assert "private-content" not in text
    assert "private-recipient" not in text
    assert "private-body" not in text


def test_acceptance_keeps_actual_finish_health_cleanup_and_hello_build(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    backend, client = make_backend(tmp_path)
    assert backend.task.acceptanceTaskState["buildFingerprint"] == ""
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False},
                               "build": {"buildFingerprint": "sha256:actual-agent-build"}})
    payload = start_message(backend, client)
    event(client, payload, step="send_verified", outcome="success")
    assert backend.task.acceptanceTaskState["outcome"] != "success"
    assert backend.task.acceptanceTaskState["cleanup"] == {}
    assert backend.task.acceptanceTaskState["health"] == {}
    actual_health = health(4)
    actual_cleanup = {"success": True, "reasonCode": "", "detail": "actual cleanup"}
    finish(client, payload, health=actual_health, cleanup=actual_cleanup)
    status(client, health(5, windowEnabled=False))
    state = backend.task.acceptanceTaskState
    assert state["health"] == actual_health
    assert state["cleanup"] == actual_cleanup
    assert state["buildFingerprint"] == "sha256:actual-agent-build"
    state["health"]["sequence"] = 99
    assert backend.task.acceptanceTaskState["health"]["sequence"] == 4


def test_qml_uses_task_eligibility_live_health_and_failure_labels():
    components = Path(__file__).resolve().parents[1] / "qml" / "components"
    for name in ("FriendWorkspace.qml", "MessageWorkspace.qml"):
        source = (components / name).read_text(encoding="utf-8")
        assert "root.appBackend.agent.canStartTask" in source
        assert "待恢复" in source
    monitor = (components / "TaskMonitor.qml").read_text(encoding="utf-8")
    assert "root.agentBackend.windowResponsive" in monitor
    assert "root.agentBackend.windowEnabled" in monitor
    assert "root.taskBackend.currentStepLabel" in monitor
    assert "root.taskBackend.cleanupFailed" in monitor
    assert "清理" in monitor
    assert "Accessible.name: text" in monitor
    assert "Accessible.name: text" in (components / "WxTitleBar.qml").read_text(encoding="utf-8")


def test_acceptance_controls_have_opt_in_accessible_names():
    components = Path(__file__).resolve().parents[1] / "qml" / "components"
    controls = {
        "MessageWorkspace.qml": ["messageRecipientsInput", "messageTemplateInput", "startMessageButton",
                                 "messageAddFileButton", "messageRemoveFileButton-"],
        "FriendWorkspace.qml": ["importFriendsButton", "friendAccountField", "startFriendsButton"],
        "TaskMonitor.qml": ["taskReturnToEditorButton", "taskStopButton"],
        "WxTitleBar.qml": ["settingsButton"],
    }
    for name, identifiers in controls.items():
        source = (components / name).read_text(encoding="utf-8")
        assert "acceptanceEnabled" in source
        for identifier in identifiers:
            assert f'? "{identifier}"' in source


def test_offscreen_qml_health_and_cleanup_states(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "tests.test_v032_controllers", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_settings_navigation_has_semantic_and_opt_in_accessible_names():
    source = (Path(__file__).resolve().parents[1] / "qml" / "components" / "SettingsDialog.qml").read_text(encoding="utf-8")
    assert 'objectName: "settingsSection" + index' in source
    assert "Accessible.name: root.appBackend && root.appBackend.task.acceptanceEnabled" in source
    assert "? objectName : modelData" in source


def render_fake_health_states(output):
    from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPointF, QUrl
    from PySide6.QtGui import QAccessible, QAccessibleActionInterface, QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    if os.name == "nt":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        app.setFont(QFont("Microsoft YaHei", 10))
    backend, client = make_backend(output)
    client.helloReceived.emit(
        {"capabilities": {"friendSubmitEnabled": True}}
    )
    backend.message.recipientsText = "Alice"
    backend.message.templateText = "hello"
    backend.friends.model.appendEmptyRecord()
    assert backend.friends.model.setCell(0, "account", "wxid_demo")
    assert backend.friends.model.setCell(0, "name", "示例学生")
    assert backend.friends.model.selectRange(1, 1)
    engine = QQmlApplicationEngine()
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    engine.rootContext().setContextProperty("backend", backend)
    base = Path(__file__).resolve().parents[1] / "qml" / "v032-test.qml"
    engine.loadData(b'''import QtQuick
import QtQuick.Layouts
import "components"
Window {
    width: 1280; height: 860; visible: true
    WxTitleBar { id: title; anchors.top: parent.top; width: parent.width; titleBackend: backend }
    StackLayout {
        anchors.top: title.bottom; anchors.bottom: parent.bottom; width: parent.width
        objectName: "pages"
        MessageWorkspace { appBackend: backend; monitorDismissed: true }
        FriendWorkspace { appBackend: backend; monitorDismissed: true }
        TaskMonitor { taskBackend: backend.task; agentBackend: backend.agent }
    }
}''', QUrl.fromLocalFile(str(base)))
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    pages = window.findChild(QObject, "pages")

    def visible_texts():
        # Delegates are visual children and may not have QObject ownership in the window.
        result = []

        def visit(item):
            if not item.isVisible():
                return
            text = item.property("text")
            if isinstance(text, str) and text:
                result.append(text)
                point = item.mapToScene(QPointF(0, 0))
                assert point.y() >= -1 and point.y() + item.height() <= window.height() + 1, text
            for child in item.childItems():
                visit(child)

        visit(window.contentItem())
        return result

    status(client, health(sessionReady=False, restorable=True))
    QTest.qWait(150)
    assert window.findChild(QObject, "startMessageButton").property("enabled")
    assert any("待恢复" in text for text in visible_texts())
    pages.setProperty("currentIndex", 1)
    QTest.qWait(100)
    assert window.findChild(QObject, "startFriendsButton").property("enabled")
    assert any("待恢复" in text for text in visible_texts())
    status(client, health(2, windowEnabled=False))
    QTest.qWait(100)
    assert not window.findChild(QObject, "startFriendsButton").property("enabled")
    assert any("被阻挡" in text for text in visible_texts())
    status(client, health(3))
    payload = start_message(backend, client)
    event(client, payload, step="target_verified", detail="target mismatch")
    finish(client, payload, outcome="error", cleanup={
        "success": False, "reasonCode": "WINDOW_DISABLED", "detail": "window cleanup failed",
    })
    status(client, health(4, windowEnabled=False))
    pages.setProperty("currentIndex", 2)
    QTest.qWait(150)
    texts = visible_texts()
    assert any("目标校验失败" in text for text in texts), texts
    assert not any(text == "目标校验通过" for text in texts), texts
    assert any("任务清理失败" in text for text in texts), texts
    shot = window.grabWindow()
    assert not shot.isNull()
    assert shot.save(str(output / "v032-monitor.png"))
    assert not errors, errors
    window.close()
    backend.shutdown()

    os.environ["WECHAT_COURIER_ACCEPTANCE"] = "1"
    acceptance, acceptance_client = make_backend(output)
    acceptance_client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": False}})
    engine.rootContext().setContextProperty("backend", acceptance)
    engine.loadData(b'''import QtQuick
import "."
Window { width: 1280; height: 860; visible: true
    App { anchors.fill: parent; appBackend: backend }
}''', QUrl.fromLocalFile(str(base)))
    integrated = engine.rootObjects()[-1]
    app_root = integrated.findChild(QObject, "appRoot")
    assert app_root is not None
    QTest.qWait(100)

    def accessible_node(name, object_name=None):
        nodes = integrated.findChildren(QObject)

        def visit(item):
            nodes.append(item)
            for child in item.childItems():
                visit(child)

        visit(integrated.contentItem())
        interfaces = [QAccessible.queryAccessibleInterface(node) for node in nodes]
        matches = [node for node in interfaces if node and node.text(QAccessible.Name) == name
                   and (object_name is None or node.object().objectName() == object_name)]
        assert matches, name
        return matches[0]

    def snapshot(name):
        return json.loads(accessible_node(name).text(QAccessible.Description))

    editor_node = "acceptanceEditorState"
    assert snapshot(editor_node) == acceptance.task.acceptanceMessageState
    assert snapshot(editor_node)["friendSubmitEnabled"] is False
    for name in ("messageWorkspaceTab", "friendWorkspaceTab", "messageRecipientsInput", "messageTemplateInput", "startMessageButton"):
        accessible_node(name)
    app_root.setProperty("workspaceIndex", 1)
    QTest.qWait(80)
    assert snapshot(editor_node) == acceptance.task.acceptanceFriendState
    for name in ("importFriendsButton", "startFriendsButton"):
        accessible_node(name)
    QMetaObject.invokeMethod(app_root, "openSettings", Q_ARG("QVariant", 3))
    QTest.qWait(100)
    for index in range(4):
        name = f"settingsSection{index}"
        node = accessible_node(name)
        assert node.object().objectName() == name
        assert node.role() == QAccessible.Button
        assert not node.state().invisible
    assert accessible_node("settingsMessageIntervalMin").state().invisible
    action = accessible_node("settingsSection0").actionInterface()
    assert QAccessibleActionInterface.pressAction() in action.actionNames()
    action.doAction(QAccessibleActionInterface.pressAction())
    QTest.qWait(100)
    for name in ("settingsMessageIntervalMin", "settingsMessageIntervalMax", "settingsCloseButton"):
        assert not accessible_node(name).state().invisible
    payload = start_message(acceptance, acceptance_client)
    event(acceptance_client, payload, step="send_verified", outcome="success")
    finish(acceptance_client, payload, health=health(4), cleanup={
        "success": True, "reasonCode": "CLEANUP_COMPLETE", "detail": None,
    })
    QTest.qWait(100)
    assert "blockingWindow" in snapshot("acceptanceTaskState")["health"]
    assert snapshot("acceptanceTaskState")["health"]["blockingWindow"] is None
    assert snapshot("acceptanceTaskState")["cleanup"]["detail"] is None
    assert snapshot("acceptanceTaskState") == acceptance.task.acceptanceTaskState
    assert snapshot("acceptanceTaskState")["taskId"] == payload["taskId"]
    missing_blocker = health(5)
    del missing_blocker["blockingWindow"]
    finish(acceptance_client, payload, health=missing_blocker)
    QTest.qWait(50)
    assert "blockingWindow" not in snapshot("acceptanceTaskState")["health"]
    assert snapshot("acceptanceTaskState")["cleanup"] == {}
    acceptance_client.helloReceived.emit({"capabilities": {}})
    QTest.qWait(50)
    calls_before = list(acceptance_client.calls)
    for index in (0, 1):
        app_root.setProperty("workspaceIndex", index)
        QTest.qWait(30)
        assert "friendSubmitEnabled" in snapshot(editor_node)
        assert snapshot(editor_node)["friendSubmitEnabled"] is None
    for _ in range(3):
        assert snapshot("acceptanceTaskState") == acceptance.task.acceptanceTaskState
    assert acceptance_client.calls == calls_before
    for name in ("taskReturnToEditorButton", "taskStopButton"):
        accessible_node(name)
    app_root.setProperty("appBackend", backend)
    QMetaObject.invokeMethod(app_root, "openSettings", Q_ARG("QVariant", 3))
    QTest.qWait(100)
    for index, name in enumerate(("消息群发", "自动发送好友申请", "自动化与恢复", "外观")):
        assert not accessible_node(name, f"settingsSection{index}").state().invisible
    assert not errors, errors
    integrated.close()
    acceptance.shutdown()


if __name__ == "__main__":
    render_fake_health_states(Path(sys.argv[1]))
