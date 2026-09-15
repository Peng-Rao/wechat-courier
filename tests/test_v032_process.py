import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.agent.client import AgentClient


@pytest.fixture
def process_peer(qapp, qtbot, tmp_path):
    pipe = "wuge-process-test-" + uuid.uuid4().hex
    token = secrets.token_hex(32)
    environment = dict(os.environ, WECHAT_AGENT_PIPE=pipe, WECHAT_AGENT_TOKEN=token,
                       WECHAT_AGENT_JOURNAL=str(tmp_path / "safety.json"),
                       WECHAT_AGENT_GATE_LEASE=str(tmp_path / "gate.json"))
    process = subprocess.Popen([sys.executable, "-m", "tests.agent_process_fixture"],
                               cwd=Path(__file__).resolve().parents[1], env=environment,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    client = AgentClient(diagnostics_log_dir=tmp_path)
    try:
        # Retry connection creation only; no automation task has started yet.
        for _ in range(30):
            client.connect_to_server(pipe, token)
            qtbot.wait(100)
            if client.connected:
                break
        assert client.connected, f"fixture exit={process.poll()}"
        yield process, client, pipe, token
    finally:
        if client.connected:
            client.call("agent.shutdown")
            qtbot.wait(150)
        client.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def test_real_pipe_multiple_independent_tasks_cleanup_and_reconnect(process_peer, qtbot):
    process, client, pipe, token = process_peer
    notices = []

    def receive(method, payload):
        notices.append((method, payload))
        if method == "task.event" and payload.get("step") == "send_verified":
            client.call("recovery.approve", {"decision": "acknowledge",
                        "taskId": payload["taskId"], "itemId": payload["itemId"]})

    client.notificationReceived.connect(receive)
    for index in range(3):
        task_id = f"independent-{index}"
        client.call("task.start", {"taskId": task_id, "kind": "message_send",
                    "items": [{"itemId": "one", "target": "fake"}], "options": {}})
        qtbot.waitUntil(lambda: any(m == "task.finished" and p.get("taskId") == task_id
                                   for m, p in notices), timeout=4000)
        finished = next(p for m, p in notices if m == "task.finished" and p.get("taskId") == task_id)
        assert finished["outcome"] == "success"
        assert finished["cleanup"]["success"]
        assert finished["health"]["sessionGeneration"] == 1
    client._socket.abort()
    qtbot.wait(100)
    client.connect_to_server(pipe, token)
    qtbot.waitUntil(lambda: client.connected, timeout=2000)
    assert process.poll() is None


def test_authenticated_gui_disappearance_exits_agent_and_cleans_gate_lease(
    qapp, qtbot, tmp_path
):
    pipe = "wuge-process-orphan-test-" + uuid.uuid4().hex
    token = secrets.token_hex(32)
    gate_path = tmp_path / "stable-gate.json"
    environment = dict(
        os.environ,
        WECHAT_AGENT_PIPE=pipe,
        WECHAT_AGENT_TOKEN=token,
        WECHAT_AGENT_JOURNAL=str(tmp_path / "safety.json"),
        WECHAT_AGENT_GATE_LEASE=str(gate_path),
        PROCESS_FIXTURE_GATE_LEASE="1",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.agent_process_fixture"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    client = AgentClient(
        gate_lease_path=gate_path,
        diagnostics_log_dir=tmp_path,
    )
    replies = []
    client.replyReceived.connect(
        lambda request_id, result: replies.append((request_id, result))
    )
    try:
        for _ in range(30):
            client.connect_to_server(pipe, token)
            qtbot.wait(100)
            if client.connected:
                break
        assert client.connected
        inspect_id = client.call("wechat.inspect")
        qtbot.waitUntil(
            lambda: any(reply[0] == inspect_id for reply in replies),
            timeout=2_000,
        )
        assert gate_path.is_file()

        client._socket.abort()
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=4_000)

        assert process.returncode == 0
        assert not gate_path.exists()
    finally:
        client.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


@pytest.mark.parametrize("mode,code", [("crash", 71), ("hang", 70)])
def test_real_process_crash_and_blocking_action_exit(process_peer, qtbot, mode, code):
    process, client, _, _ = process_peer
    client.call("task.start", {"taskId": "fault", "kind": "message_send",
                "items": [{"itemId": "one", "target": mode}], "options": {}})
    qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
    assert process.returncode == code
