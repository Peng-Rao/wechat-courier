import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings

from app.agent.client import AgentClient
from app.backend import BackendController


def test_real_agent_stop_rechecks_before_unlock_and_accepts_next_task(qapp, qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    pipe = "wuge-stop-recovery-" + uuid.uuid4().hex
    token = secrets.token_hex(32)
    environment = dict(
        os.environ, WECHAT_AGENT_PIPE=pipe, WECHAT_AGENT_TOKEN=token,
        WECHAT_AGENT_JOURNAL=str(tmp_path / "safety.json"),
        WECHAT_AGENT_GATE_LEASE=str(tmp_path / "gate.json"),
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.stop_recovery_agent_fixture"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    client = AgentClient(
        journal_path=str(tmp_path / "safety.json"),
        gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path,
    )
    backend = BackendController(
        settings=QSettings(str(tmp_path / "gui.ini"), QSettings.IniFormat),
        agent_client=client,
    )
    notices, errors, unlocks = [], [], []
    stopped_task = []
    checked_while_active = []
    client.rpcError.connect(lambda key, code, detail: errors.append((key, code, detail)))
    backend.task.activeChanged.connect(lambda: unlocks.append(
        (backend.task.active, backend.agent.automationReady)
    ))

    def receive(method, payload):
        notices.append((method, payload))
        if method == "task.event" and payload.get("outcome") == "error" and not stopped_task:
            stopped_task.append(payload["taskId"])
            backend.task.stop()
        if (
            method == "agent.status" and payload.get("status") == "uia_action_started"
            and payload.get("action") == "inspect" and stopped_task
            and not checked_while_active
        ):
            checked_while_active.append(backend.task.active)
            client.call("task.start", {
                "taskId": "premature", "kind": "message_send",
                "items": [{"itemId": "x", "target": "Mock", "message": "must-not-send"}],
            })

    client.notificationReceived.connect(receive)
    try:
        for _ in range(30):
            client.connect_to_server(pipe, token)
            qtbot.wait(100)
            if client.connected:
                break
        assert client.connected
        qtbot.waitUntil(lambda: backend.agent.automationReady, timeout=4000)
        backend.message.recipientsText = "Mock\nMock Two"
        backend.message.templateText = "mock-only"
        backend.message.intervalMin = 1
        backend.message.intervalMax = 1
        assert backend.task.startMessage()
        qtbot.waitUntil(lambda: bool(stopped_task) and not backend.task.active, timeout=5000)

        assert checked_while_active == [True]
        assert backend.agent.automationReady is True
        assert backend.agent.canStartTask is True
        assert unlocks[-1] == (False, True)
        assert backend.task.failureCount == 1
        assert backend.task.successCount == 0
        assert backend.task.unknownCount == 0
        assert any(code == -32602 and "already active" in detail for _, code, detail in errors)
        first_id = stopped_task[0]
        finished_index = next(i for i, (m, p) in enumerate(notices)
                              if m == "task.finished" and p["taskId"] == first_id)
        assert any(m == "agent.status" and p.get("health", {}).get("sessionReady") is True
                   for m, p in notices[:finished_index])
        assert sum(m == "task.finished" for m, _ in notices) == 1

        first_health = backend.agent.healthSnapshot
        backend.message.recipientsText = "Mock"
        assert backend.task.startMessage()
        qtbot.waitUntil(lambda: not backend.task.active, timeout=4000)
        assert backend.task.successCount == 1
        assert backend.agent.automationReady is True
        assert backend.agent.healthSnapshot["sequence"] > first_health["sequence"]
        backend.agent.applyInspection(first_health)
        assert backend.agent.healthSnapshot["sequence"] > first_health["sequence"]
        assert process.poll() is None
        assert sum(m == "task.finished" for m, _ in notices) == 2
        second_id = backend.task._task_id
        bound_index = next(i for i, (m, p) in enumerate(notices)
                           if m == "agent.status" and p.get("health", {}).get("taskId") == second_id
                           and p["health"].get("taskWindowReady"))
        search_index = next(i for i, (m, p) in enumerate(notices)
                            if m == "agent.status" and p.get("taskId") == second_id
                            and p.get("action") == "ensure_search_ready")
        assert bound_index < search_index
        for index in range(2):
            backend.friends.model.appendEmptyRecord()
            backend.friends.model.setCell(index, "account", f"mock_only_{index}")
            backend.friends.model.setCell(index, "name", f"Mock {index}")
        backend.friends.intervalMax = 1
        assert backend.task.startFriends()
        assert backend.task._original_payload["options"]["intervalMin"] == 1
        assert backend.task._original_payload["options"]["intervalMax"] == 1
        backend.friends.intervalMin = 100
        assert backend.friends.intervalMin == 1
        qtbot.waitUntil(lambda: backend.task.waitingRemaining > 0, timeout=3000)
        assert backend.task.automationStatus == "自动化执行中"
        assert backend.task.waitingRemaining <= 1
        qtbot.waitUntil(lambda: not backend.task.active, timeout=4000)
        assert backend.task.waitingRemaining == 0
        assert backend.task.successCount == 2
    finally:
        if client.connected:
            client.call("agent.shutdown")
            qtbot.wait(200)
        client.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def test_real_agent_watchdog_terminates_blocked_health_preflight(qapp, qtbot, tmp_path):
    pipe = "wuge-stop-hung-health-" + uuid.uuid4().hex
    token = secrets.token_hex(32)
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.stop_recovery_agent_fixture"],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, WECHAT_AGENT_PIPE=pipe, WECHAT_AGENT_TOKEN=token,
                 WECHAT_AGENT_JOURNAL=str(tmp_path / "safety.json"),
                 STOP_RECOVERY_FIXTURE_BLOCK_HEALTH="1"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    client = AgentClient(journal_path=str(tmp_path / "safety.json"), diagnostics_log_dir=tmp_path)
    notices, health_started = [], []

    def receive(method, payload):
        notices.append((method, payload))
        if method == "task.event" and payload.get("outcome") == "error":
            client.call("task.stop")
        if method == "agent.status" and payload.get("status") == "uia_action_started" and payload.get("step") == "health":
            health_started.append(time.monotonic())

    client.notificationReceived.connect(receive)
    try:
        for _ in range(30):
            client.connect_to_server(pipe, token)
            qtbot.wait(100)
            if client.connected:
                break
        assert client.connected
        client.call("task.start", {
            "taskId": "blocked-health", "kind": "message_send",
            "items": [{"itemId": "first", "target": "Mock", "message": "mock-only"},
                      {"itemId": "remaining", "target": "Mock", "message": "must-not-send"}],
            "options": {"intervalMin": 1, "intervalMax": 1},
        })
        qtbot.waitUntil(lambda: bool(health_started) or process.poll() is not None, timeout=6000)
        assert health_started, (process.poll(), notices)
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=4000)
        assert process.returncode == 70
        assert time.monotonic() - health_started[0] < 4.0
        assert not any(method == "task.finished" for method, _ in notices)
        health_index = next(i for i, (method, payload) in enumerate(notices)
                            if method == "agent.status" and payload.get("status") == "uia_action_started"
                            and payload.get("step") == "health")
        assert not any(method == "agent.status" and payload.get("health", {}).get("sessionReady")
                       for method, payload in notices[health_index:])
    finally:
        client.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
