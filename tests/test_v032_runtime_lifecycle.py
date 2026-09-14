from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QProcess

from app.agent.client import AgentClient
from app.agent.runtime import AgentRuntime, TaskControl
from tests.test_agent_runtime import RecordingEngine, message_request


class HeldInspection(RecordingEngine):
    def __init__(self):
        super().__init__()
        self.inspect_started = threading.Event()
        self.inspect_release = threading.Event()

    def inspect(self):
        self.inspect_started.set()
        self.inspect_release.wait(3)
        return super().inspect()


@pytest.mark.parametrize("status", ["uia_action_completed", "paused", "waiting", "health"])
def test_inspection_deadline_survives_task_status_notices(qapp, qtbot, status):
    engine = HeldInspection()
    exits = []
    runtime = AgentRuntime(
        engine_factory=lambda: engine, inspect_timeout_ms=80,
        fatal_exit=exits.append,
    )
    try:
        runtime.inspect_async(lambda result, error: None)
        assert engine.inspect_started.wait(1)
        qtbot.wait(20)
        runtime._forward_notice("agent.status", {"status": status, "actionId": "a"})
        qtbot.wait(140)
        assert exits == [70]
    finally:
        engine.inspect_release.set()
        runtime.close()


def test_queued_inspection_gets_deadline_after_task_completion(qapp, qtbot):
    engine = HeldInspection()
    exits = []
    runtime = AgentRuntime(
        engine_factory=lambda: engine, inspect_timeout_ms=80,
        fatal_exit=exits.append,
    )
    try:
        runtime.start_task(message_request())
        assert engine.started.wait(1)
        runtime.inspect_async(lambda result, error: None)
        qtbot.wait(150)
        assert exits == []
        engine.release.set()
        qtbot.waitUntil(engine.inspect_started.is_set)
        qtbot.waitUntil(lambda: runtime.active_task_id == "")
        qtbot.wait(140)
        assert exits == [70]
    finally:
        engine.release.set()
        engine.inspect_release.set()
        runtime.close()


def test_inspection_request_does_not_extend_existing_action_deadline(qapp, qtbot):
    engine = HeldInspection()
    runtime = AgentRuntime(engine_factory=lambda: engine)
    try:
        runtime._forward_notice("agent.status", {"status": "uia_action_started", "actionId": "a"})
        before = runtime._action_watchdog.remainingTime()
        qtbot.wait(60)
        runtime.inspect_async(lambda result, error: None)
        assert runtime._action_watchdog.remainingTime() < before - 20
    finally:
        engine.inspect_release.set()
        runtime.close()


def test_completed_inspection_cancels_its_deadline(qapp, qtbot):
    exits = []
    results = []
    runtime = AgentRuntime(
        engine_factory=RecordingEngine, inspect_timeout_ms=80,
        fatal_exit=exits.append,
    )
    try:
        runtime.inspect_async(lambda result, error: results.append((result, error)))
        qtbot.waitUntil(lambda: bool(results))
        qtbot.wait(140)
        assert exits == []
        assert results[0][1] is None
    finally:
        runtime.close()


def test_runtime_close_propagates_engine_cleanup_failure(qapp):
    class FailingClose(RecordingEngine):
        def close(self):
            raise RuntimeError("gate restoration failed")

    runtime = AgentRuntime(engine_factory=FailingClose)
    runtime.inspect()
    with pytest.raises(RuntimeError, match="cleanup failed") as raised:
        runtime.close()
    assert str(raised.value.__cause__) == "gate restoration failed"
    assert not runtime._thread.isRunning()


def test_runtime_close_reports_missing_cleanup_completion(qapp):
    runtime = AgentRuntime(engine_factory=RecordingEngine)
    runtime.closeRequested.disconnect()
    with pytest.raises(TimeoutError, match="cleanup"):
        runtime.close(timeout_ms=20)
    assert not runtime._thread.isRunning()


@pytest.mark.parametrize("exit_code,exit_status", [
    (70, QProcess.ExitStatus.NormalExit), (0, QProcess.ExitStatus.CrashExit),
])
def test_requested_shutdown_still_recovers_after_abnormal_exit(tmp_path, qapp, exit_code, exit_status):
    client = AgentClient(diagnostics_log_dir=tmp_path)
    recovery = []
    client._run_gate_recovery = lambda: recovery.append("synchronous") or True
    client._start_gate_recovery_async = lambda: recovery.append("asynchronous")
    client._state = "connected"
    client._shutdown_requested = True
    client._on_process_finished(exit_code, exit_status)
    client.close()
    assert recovery == ["synchronous"]


def test_requested_clean_shutdown_recovers_a_remaining_gate_lease(tmp_path, qapp):
    journal_path = tmp_path / "safety.json"
    journal_path.with_name("safety.json.gate").write_text("{}", encoding="utf-8")
    client = AgentClient(journal_path=str(journal_path), diagnostics_log_dir=tmp_path)
    recovery = []
    client._run_gate_recovery = lambda: recovery.append("recover") or True
    client._state = "connected"
    client._shutdown_requested = True
    client._on_process_finished(0, QProcess.ExitStatus.NormalExit)
    client.close()
    assert recovery == ["recover"]


def test_requested_clean_shutdown_without_lease_needs_no_recovery(tmp_path, qapp):
    client = AgentClient(journal_path=str(tmp_path / "safety.json"), diagnostics_log_dir=tmp_path)
    recovery = []
    client._run_gate_recovery = lambda: recovery.append("recover") or True
    client._state = "connected"
    client._shutdown_requested = True
    client._on_process_finished(0, QProcess.ExitStatus.NormalExit)
    client.close()
    assert recovery == []
