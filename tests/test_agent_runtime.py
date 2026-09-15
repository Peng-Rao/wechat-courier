from __future__ import annotations

import threading
import uuid

from PySide6.QtNetwork import QLocalServer

from app.agent.client import AgentClient
from app.agent.journal import SafetyJournal
from app.agent.runtime import AgentRuntime, TaskControl
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


class RecoveryEngine(RecordingEngine):
    def __init__(self):
        super().__init__()
        self.recovered = threading.Event()

    def recover_wechat(self, timeout, emit):
        emit("agent.status", {"status": "waiting_login", "remaining": timeout})
        self.recovered.set()
        return {"connected": True, "supported": True, "version": "4.1.13.65"}


class BlockingInspectEngine(RecordingEngine):
    def __init__(self):
        super().__init__()
        self.inspect_started = threading.Event()
        self.inspect_release = threading.Event()
        self.inspect_calls = 0

    def inspect(self):
        self.inspect_calls += 1
        self.inspect_started.set()
        self.inspect_release.wait(1)
        return super().inspect()


class ClosableEngine(RecordingEngine):
    def __init__(self):
        super().__init__()
        self.close_thread_id = None
        self.closed = threading.Event()

    def close(self):
        self.close_thread_id = threading.get_ident()
        self.closed.set()


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


def test_default_inspection_watchdog_outlives_the_five_second_tree_diagnostic(
    qapp,
):
    runtime = AgentRuntime(engine_factory=RecordingEngine)

    try:
        assert runtime._inspection_watchdog.interval() == 7_500
        assert runtime._inspect_timeout == 7.5
    finally:
        runtime.close()


def test_runtime_closes_engine_on_the_automation_thread(qapp):
    engine = ClosableEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)

    runtime.inspect()
    caller_thread_id = threading.get_ident()
    runtime.close()

    assert engine.closed.is_set() is True
    assert engine.close_thread_id is not None
    assert engine.close_thread_id != caller_thread_id


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


def test_runtime_shutdown_waits_for_active_item_to_reach_safe_finish(qapp, qtbot):
    engine = RecordingEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    shutdowns = []
    runtime.shutdownRequested.connect(lambda: shutdowns.append(True))
    runtime.start_task(message_request())
    assert engine.started.wait(1)

    assert runtime.shutdown() == {"accepted": True}
    qtbot.wait(30)
    assert shutdowns == []

    engine.release.set()
    qtbot.waitUntil(lambda: shutdowns == [True])
    runtime.close()


def test_runtime_reports_and_requires_acknowledgement_of_recovery_record(
    tmp_path, qapp
):
    journal = SafetyJournal(tmp_path / "safety.json")
    journal.mark(
        task_id="task-1",
        kind="message_send",
        item_id="item-1",
        boundary="send_triggered",
        item_index=0,
    )
    runtime = AgentRuntime(engine_factory=RecordingEngine, journal=journal)

    assert runtime.hello()["recovery"]["itemId"] == "item-1"
    try:
        runtime.start_task(message_request())
    except ValueError as exc:
        assert "recovery" in str(exc).lower()
    else:
        raise AssertionError("task was accepted before recovery acknowledgement")

    assert runtime.approve_recovery({"decision": "mark_unknown"}) == {
        "accepted": True,
        "decision": "mark_unknown",
    }
    assert journal.load() is None
    runtime.close()


def test_runtime_advertises_friend_submit_in_normal_mode(qapp, monkeypatch):
    monkeypatch.delenv("WECHAT_COURIER_ACCEPTANCE", raising=False)
    runtime = AgentRuntime(engine_factory=RecordingEngine)

    assert runtime.hello()["capabilities"]["friendSubmitEnabled"] is True

    runtime.close()


def test_runtime_disables_friend_submit_in_acceptance_mode(qapp, monkeypatch):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    runtime = AgentRuntime(engine_factory=RecordingEngine)

    assert runtime.hello()["capabilities"]["friendSubmitEnabled"] is False

    runtime.close()


def test_runtime_wires_advertised_submit_capability_into_default_engine(
    tmp_path, qapp, monkeypatch
):
    captured = []

    class CapturingEngine(RecordingEngine):
        def __init__(self, **kwargs):
            super().__init__()
            captured.append(kwargs)

    monkeypatch.delenv("WECHAT_COURIER_ACCEPTANCE", raising=False)
    monkeypatch.setattr(
        "app.agent.workflows.WeixinWorkflowEngine",
        CapturingEngine,
    )
    runtime = AgentRuntime(
        journal=SafetyJournal(tmp_path / "safety.json"),
    )

    assert runtime.inspect()["supported"] is True
    assert captured[0]["friend_submit_enabled"] is True
    assert runtime.hello()["capabilities"]["friendSubmitEnabled"] is True

    runtime.close()


def test_task_control_waits_for_an_explicit_result_acknowledgement():
    control = TaskControl(require_result_ack=True)
    released = threading.Event()

    worker = threading.Thread(
        target=lambda: (
            control.wait_for_result_ack("item-1", timeout=1.0),
            released.set(),
        )
    )
    worker.start()
    assert released.wait(0.05) is False

    control.acknowledge_result("item-1")
    worker.join(1)

    assert released.is_set() is True


def test_runtime_action_timeout_uses_fatal_agent_exit(tmp_path, qapp):
    exits = []
    runtime = AgentRuntime(
        engine_factory=RecordingEngine,
        journal=SafetyJournal(tmp_path / "safety.json"),
        fatal_exit=lambda code: exits.append(code),
    )

    runtime._on_action_timeout()

    assert exits == [70]
    runtime.close()


def test_runtime_pausing_suspends_no_progress_watchdog(tmp_path, qapp):
    runtime = AgentRuntime(
        engine_factory=RecordingEngine,
        journal=SafetyJournal(tmp_path / "safety.json"),
    )
    runtime._active_task_id = "task-paused"
    runtime._control = TaskControl()
    runtime._action_watchdog.start()

    assert runtime.pause_task()["accepted"] is True
    assert runtime._action_watchdog.isActive() is False

    assert runtime.resume_task()["accepted"] is True
    assert runtime._action_watchdog.isActive() is True
    runtime._active_task_id = ""
    runtime._control = None
    runtime.close()


def test_runtime_runs_confirmed_wechat_recovery_on_automation_thread(
    tmp_path, qapp, qtbot
):
    engine = RecoveryEngine()
    runtime = AgentRuntime(
        engine_factory=lambda: engine,
        journal=SafetyJournal(tmp_path / "safety.json"),
    )
    notices = []
    runtime.set_notification_sink(lambda method, params: notices.append((method, params)))

    reply = runtime.approve_recovery(
        {"decision": "restart_wechat", "loginTimeout": 90}
    )

    assert reply == {"accepted": True, "decision": "restart_wechat"}
    assert engine.recovered.wait(1)
    qtbot.waitUntil(
        lambda: any(
            method == "agent.status" and params.get("status") == "recovered"
            for method, params in notices
        )
    )
    runtime.close()


def test_client_authenticates_and_receives_notifications(qapp, qtbot):
    engine = RecordingEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    name = "wechat-courier-client-test-" + uuid.uuid4().hex
    server = AgentServer(name, "secret", runtime, heartbeat_interval_ms=20)
    assert server.listen()

    client = AgentClient(heartbeat_timeout_ms=500)
    replies = []
    hellos = []
    notices = []
    client.replyReceived.connect(lambda request_id, result: replies.append((request_id, result)))
    client.helloReceived.connect(hellos.append)
    client.notificationReceived.connect(lambda method, params: notices.append((method, params)))
    client.connect_to_server(name, "secret")

    qtbot.waitUntil(lambda: client.connected, timeout=2_000)
    assert hellos and hellos[0]["protocolVersion"] == 1
    request_id = client.call("wechat.inspect")
    qtbot.waitUntil(lambda: any(item[0] == request_id for item in replies), timeout=2_000)
    inspection = next(result for item_id, result in replies if item_id == request_id)
    assert inspection["version"] == "4.1.13.65"
    qtbot.waitUntil(lambda: any(name == "heartbeat" for name, _ in notices), timeout=2_000)

    client.close()
    server.close()
    runtime.close()
    QLocalServer.removeServer(name)


def test_client_rotates_and_redacts_agent_stderr(tmp_path, qapp):
    client = AgentClient(
        diagnostics_log_dir=tmp_path,
        stderr_max_bytes=80,
    )
    token = "a" * 64

    client._write_agent_stderr(
        f"failed account 18896904196 token {token}\n".encode("utf-8")
    )
    client._write_agent_stderr(b"second diagnostic line that rotates the file\n")

    captured = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(tmp_path.glob("agent-stderr.log*"))
    )
    assert "18896904196" not in captured
    assert token not in captured
    assert "[redacted-number]" in captured
    assert "[redacted-token]" in captured
    assert (tmp_path / "agent-stderr.log.1").exists()


def test_client_uses_one_stable_gate_lease_across_gui_instances(
    tmp_path, qapp, monkeypatch
):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    first = AgentClient(diagnostics_log_dir=tmp_path)
    second = AgentClient(diagnostics_log_dir=tmp_path)

    expected = str(
        local_app_data / "WxAuto" / "state" / "weixin-uia-gate-v1.json"
    )
    assert first._journal_path != second._journal_path
    assert first._gate_lease_path == expected
    assert second._gate_lease_path == expected


def test_client_accepts_an_isolated_gate_lease_for_tests(tmp_path, qapp):
    gate_path = tmp_path / "isolated-gate.json"

    client = AgentClient(
        gate_lease_path=str(gate_path),
        diagnostics_log_dir=tmp_path,
    )

    assert client._gate_lease_path == str(gate_path)


def test_unexpected_agent_exit_runs_gate_recovery_even_without_active_task(
    tmp_path, qapp
):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    recovery_calls = []
    client._start_gate_recovery_async = (
        lambda: recovery_calls.append("recover")
    )
    client._state = "connected"
    client._process = type(
        "FinishedProcess",
        (),
        {"readAllStandardError": staticmethod(lambda: b"")},
    )()

    client._on_process_finished(70, None)

    assert recovery_calls == ["recover"]
    assert client._process is None


def test_existing_agent_exit_code_is_clear_and_never_runs_gate_recovery(
    tmp_path, qapp
):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    recoveries = []
    errors = []
    client._start_gate_recovery_async = lambda: recoveries.append("recover")
    client.processError.connect(errors.append)
    client._state = "starting"
    client._process = type(
        "FinishedProcess",
        (),
        {"readAllStandardError": staticmethod(lambda: b"already running")},
    )()

    client._on_process_finished(5, None)

    assert recoveries == []
    assert client._process is None
    assert client.state == "error"
    assert errors == ["已有自动化 Agent 正在操作微信，请先关闭其他助手实例后重试"]


def test_expected_agent_exit_does_not_spawn_recovery_helper(tmp_path, qapp):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    recovery_calls = []
    client._start_gate_recovery_async = (
        lambda: recovery_calls.append("recover")
    )
    client._state = "stopped"
    client._process = type(
        "FinishedProcess",
        (),
        {"readAllStandardError": staticmethod(lambda: b"")},
    )()

    client._on_process_finished(0, None)

    assert recovery_calls == []


def test_client_defers_new_agent_until_async_gate_recovery_finishes(
    tmp_path, qapp, monkeypatch
):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    recovery_process = object()
    client._recovery_process = recovery_process

    class UnexpectedProcess:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("new Agent started before gate recovery finished")

    monkeypatch.setattr("app.agent.client.QProcess", UnexpectedProcess)

    client.start("wechat-agent.exe")

    assert client._process is None
    assert client._pending_start_after_recovery is True
    assert client.state == "recovering_gate"


def test_failed_async_gate_recovery_blocks_the_deferred_agent_start(
    tmp_path, qapp
):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    errors = []
    starts = []
    client.processError.connect(errors.append)

    class RecoveryProcess:
        @staticmethod
        def deleteLater():
            return None

    process = RecoveryProcess()
    client._recovery_process = process
    client._pending_start_after_recovery = True
    client._state = "recovering_gate"
    client.start = lambda *_args, **_kwargs: starts.append("start")

    client._finish_gate_recovery(
        process,
        successful=False,
        detail="gate restore failed",
    )

    assert starts == []
    assert client._pending_start_after_recovery is False
    assert client._recovery_process is None
    assert client.state == "error"
    assert errors == ["gate restore failed"]


def test_gate_recovery_allows_mutex_wait_before_cleanup(monkeypatch, tmp_path, qapp):
    from app.agent import client as client_module

    class ContendedRecovery:
        def setProcessEnvironment(self, *_): pass
        def setProgram(self, *_): pass
        def setArguments(self, *_): pass
        def start(self): pass
        def kill(self): self.killed = True
        def waitForFinished(self, timeout): return timeout >= 5_500
        def exitCode(self): return 0

    process = ContendedRecovery()
    process.killed = False
    monkeypatch.setattr(client_module, "QProcess", lambda: process)
    client = AgentClient(diagnostics_log_dir=tmp_path)
    assert client._run_gate_recovery() is True
    assert process.killed is False


def test_async_gate_recovery_timeout_fails_closed(tmp_path, qapp):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    errors = []
    client.processError.connect(errors.append)

    class RecoveryProcess:
        def __init__(self):
            self.killed = False
            self.deleted = False

        def kill(self):
            self.killed = True

        def waitForFinished(self, _timeout):
            return True

        def deleteLater(self):
            self.deleted = True

    process = RecoveryProcess()
    client._recovery_process = process
    client._pending_start_after_recovery = True
    client._state = "recovering_gate"

    client._on_gate_recovery_timeout()

    assert process.killed is True
    assert process.deleted is True
    assert client._recovery_process is None
    assert client._pending_start_after_recovery is False
    assert client.state == "error"
    assert errors == ["wechat-agent gate recovery timed out"]


def test_one_inspection_callback_cannot_block_the_other_callbacks(qapp):
    runtime = AgentRuntime(engine_factory=RecordingEngine)
    delivered = []
    runtime._inspection_pending = True

    def broken_callback(_result, _error):
        raise RuntimeError("receiver disappeared")

    runtime._inspection_callbacks = [
        broken_callback,
        lambda result, error: delivered.append((result, error)),
    ]

    runtime._inspection_finished({"result": {"sessionReady": True}})

    assert delivered == [({"sessionReady": True}, None)]
    assert runtime._inspection_pending is False
    runtime.close()


def test_server_keeps_heartbeats_flowing_during_slow_uia_inspection(qapp, qtbot):
    engine = BlockingInspectEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    name = "wechat-courier-async-inspect-" + uuid.uuid4().hex
    server = AgentServer(name, "secret", runtime, heartbeat_interval_ms=20)
    assert server.listen()
    client = AgentClient(heartbeat_timeout_ms=180)
    replies = []
    notices = []
    client.replyReceived.connect(
        lambda request_id, result: replies.append((request_id, result))
    )
    client.notificationReceived.connect(
        lambda method, params: notices.append((method, params))
    )
    client.connect_to_server(name, "secret")
    qtbot.waitUntil(lambda: client.connected, timeout=2_000)

    request_id = client.call("wechat.inspect")
    qtbot.waitUntil(engine.inspect_started.is_set, timeout=2_000)
    qtbot.wait(260)
    assert client.connected is True
    assert any(method == "heartbeat" for method, _params in notices)

    engine.inspect_release.set()
    qtbot.waitUntil(
        lambda: any(item[0] == request_id for item in replies), timeout=2_000
    )
    client.close()
    server.close()
    runtime.close()
    QLocalServer.removeServer(name)


def test_runtime_coalesces_overlapping_inspection_requests(qapp, qtbot):
    engine = BlockingInspectEngine()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    results = []

    runtime.inspect_async(
        lambda result, error: results.append(("first", result, error))
    )
    assert engine.inspect_started.wait(1)
    runtime.inspect_async(
        lambda result, error: results.append(("second", result, error))
    )

    engine.inspect_release.set()
    qtbot.waitUntil(lambda: len(results) == 2)

    assert engine.inspect_calls == 1
    assert [entry[0] for entry in results] == ["first", "second"]
    assert all(entry[1]["version"] == "4.1.13.65" for entry in results)
    assert all(entry[2] is None for entry in results)
    runtime.close()
