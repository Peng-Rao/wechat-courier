from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

from app.agent.client import AgentClient


def spawn(tmp_path, scenario):
    pipe, token = "gate-process-" + uuid.uuid4().hex, secrets.token_hex(32)
    environment = dict(os.environ, WECHAT_AGENT_PIPE=pipe, WECHAT_AGENT_TOKEN=token,
        WECHAT_AGENT_GATE_LEASE=str(tmp_path / "gate.json"),
        WECHAT_AGENT_JOURNAL=str(tmp_path / "task.json"), GATE_TEST_SCENARIO=scenario)
    process = subprocess.Popen([sys.executable, "-m", "tests.gate_recovery_process_fixture"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return process, pipe, token


def connect(client, pipe, token, qtbot):
    for _ in range(40):
        client.connect_to_server(pipe, token)
        qtbot.wait(50)
        if client.connected:
            return
    raise AssertionError("Agent did not authenticate")


def close_peer(process, client, qtbot):
    if client.connected:
        client.call("agent.shutdown")
        qtbot.wait(100)
    client.close()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def test_real_pipe_heartbeats_continue_while_recovery_blocks_tasks(qapp, qtbot, tmp_path):
    process, pipe, token = spawn(tmp_path, "slow")
    client = AgentClient(gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path)
    notices, errors = [], []
    client.notificationReceived.connect(lambda m, p: notices.append((m, p)))
    client.rpcError.connect(lambda i, c, m: errors.append(m))
    try:
        connect(client, pipe, token, qtbot)
        client.call("task.start", {"taskId": "must-not-run", "kind": "message_send",
                    "items": [{"itemId": "i", "target": "fake"}], "options": {}})
        qtbot.waitUntil(lambda: bool(errors))
        assert "GATE_RECOVERY_PENDING" in errors[0]
        qtbot.waitUntil(lambda: sum(m == "heartbeat" for m, p in notices) >= 3)
        qtbot.waitUntil(lambda: any(p.get("health", {}).get("sessionReady") for m, p in notices))
        assert not any(m == "task.event" for m, p in notices)
        assert process.poll() is None
    finally:
        close_peer(process, client, qtbot)


def test_real_agent_crash_keeps_reservation_and_new_agent_stays_online_blocked(qapp, qtbot, tmp_path):
    (tmp_path / "gate.json").write_text("{}", encoding="utf-8")
    first, _, _ = spawn(tmp_path, "crash")
    assert first.wait(timeout=5) == 71
    reservation = json.loads((tmp_path / "gate.json.recovery.json").read_text(encoding="utf-8"))
    assert reservation["attempt"] == 1
    process, pipe, token = spawn(tmp_path, "normal")
    client = AgentClient(gate_lease_path=tmp_path / "gate.json", diagnostics_log_dir=tmp_path)
    replies, notices = [], []
    client.replyReceived.connect(lambda i, r: replies.append((i, r)))
    client.notificationReceived.connect(lambda m, p: notices.append((m, p)))
    try:
        connect(client, pipe, token, qtbot)
        request_id = client.call("wechat.inspect")
        qtbot.waitUntil(lambda: any(i == request_id for i, r in replies))
        health = next(r for i, r in replies if i == request_id)
        assert health["gateRecovery"]["attempt"] == 1
        assert not health["sessionReady"]
        qtbot.waitUntil(lambda: any(p.get("health", {}).get("gateRecovery", {}).get("reasonCode") == "GATE_RESTART_LIMIT" for m, p in notices))
        assert process.poll() is None
    finally:
        close_peer(process, client, qtbot)


def test_production_recovery_cli_archives_exited_old_schema_without_uia(tmp_path):
    from app.agent.journal import GateLeaseJournal

    lease = GateLeaseJournal(tmp_path / "gate.json")
    lease.mark(pid=2_000_000_000, process_start_time="old", version="4.1.13.65", gate_rva=0x0AE2B0C8,
               original_gate=0, original_screen_reader=False, gate_owned=True,
               screen_reader_owned=True, session_generation=1)
    result = subprocess.run([sys.executable, "-m", "app.agent.main", "--recover-gate"],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, WECHAT_AGENT_GATE_LEASE=str(lease.path)),
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stage"] == "completed"
    assert not lease.path.exists()
    assert list((tmp_path / "gate-archive").glob("*.json"))


def test_real_process_native_recovery_hang_exits_on_service_watchdog(tmp_path):
    process, _, _ = spawn(tmp_path, "hang")
    try:
        assert process.wait(timeout=5) == 70
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
