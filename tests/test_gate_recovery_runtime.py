from __future__ import annotations

import threading

import pytest

from app.agent.journal import SafetyJournal
from app.agent.runtime import AgentRuntime
from tests.test_agent_runtime import message_request


class BlockingRecovery:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.state = {"stage": "checking", "reasonCode": "GATE_RECOVERING", "attempt": 0}
        self.allow_restart = True

    def run(self, stop, emit):
        self.entered.set()
        emit(dict(self.state))
        while not self.release.wait(0.02):
            if stop.is_set():
                self.state = dict(self.state, stage="blocked", reasonCode="GATE_RECOVERY_CANCELLED")
                return dict(self.state)
        self.state = dict(self.state, stage="completed", reasonCode="")
        return dict(self.state)


class HealthyEngine:
    def inspect(self):
        return {"processDetected": True, "versionSupported": True, "sessionReady": True,
                "windowResponsive": True, "windowEnabled": True, "sequence": 1,
                "agentInstanceId": "engine-local-id"}

    def close(self):
        pass


def test_online_recovery_blocks_uia_and_task_then_publishes_verified_health(qapp, qtbot):
    recovery = BlockingRecovery()
    engines = []
    def factory():
        engines.append(HealthyEngine())
        return engines[-1]
    runtime = AgentRuntime(engine_factory=factory, gate_recovery=recovery)
    notices = []
    runtime.set_notification_sink(lambda m, p: notices.append((m, p)))
    try:
        runtime.begin_gate_recovery()
        assert recovery.entered.wait(1)
        assert runtime.hello()["gateRecovery"]["stage"] == "checking"
        results = []
        runtime.inspect_async(lambda r, e: results.append(r))
        assert not results[0]["sessionReady"]
        with pytest.raises(ValueError, match="GATE"):
            runtime.start_task(message_request())
        assert engines == []
        recovery.release.set()
        qtbot.waitUntil(lambda: any(p.get("health", {}).get("sessionReady") for m, p in notices))
        snapshots = [p["health"] for m, p in notices if "health" in p]
        assert len({h["agentInstanceId"] for h in snapshots}) == 1
        assert [h["sequence"] for h in snapshots] == sorted({h["sequence"] for h in snapshots})
        assert len(engines) == 1
    finally:
        recovery.release.set()
        runtime.close()


def test_gate_scope_cancellation_preserves_destructive_task_journal(qapp, qtbot, tmp_path):
    journal = SafetyJournal(tmp_path / "safety.json")
    boundary = journal.mark(task_id="t", kind="friend_add", item_id="i", item_index=0, boundary="submit")
    recovery = BlockingRecovery()
    runtime = AgentRuntime(engine_factory=HealthyEngine, journal=journal, gate_recovery=recovery)
    try:
        runtime.begin_gate_recovery()
        assert recovery.entered.wait(1)
        runtime.approve_recovery({"scope": "gate", "decision": "stop"})
        qtbot.waitUntil(lambda: runtime.hello()["gateRecovery"]["stage"] == "blocked")
        assert journal.load() == boundary
        with pytest.raises(ValueError):
            runtime.approve_recovery({"scope": "gate", "decision": "discard"})
        assert journal.load() == boundary
    finally:
        recovery.release.set()
        runtime.close()


def test_later_unhealthy_snapshot_blocks_direct_rpc_task_start(qapp, qtbot):
    recovery = BlockingRecovery()
    recovery.release.set()
    runtime = AgentRuntime(engine_factory=HealthyEngine, gate_recovery=recovery)
    try:
        runtime.begin_gate_recovery()
        qtbot.waitUntil(lambda: runtime._gate_verified)
        runtime._forward_notice("agent.status", {"status": "health", "health": {
            "sessionReady": False, "reasonCode": "WECHAT_UNRESPONSIVE"}})
        with pytest.raises(ValueError, match="GATE"):
            runtime.start_task(message_request())
    finally:
        runtime.close()


def test_gate_watchdog_bounds_a_hung_native_recovery_call(qapp, qtbot):
    recovery = BlockingRecovery()
    exits = []
    runtime = AgentRuntime(engine_factory=HealthyEngine, gate_recovery=recovery,
                           gate_timeout_ms=40, fatal_exit=exits.append)
    try:
        runtime.begin_gate_recovery()
        qtbot.waitUntil(lambda: exits == [70], timeout=1000)
        assert not runtime._gate_ready
    finally:
        recovery.release.set()
        runtime.close()
