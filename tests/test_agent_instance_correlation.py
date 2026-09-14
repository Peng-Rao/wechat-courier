import json
import uuid
from types import SimpleNamespace

import pytest

from app.agent.diagnostics import UiaDiagnostics
from app.agent.runtime import AgentRuntime
from app.agent.workflows import WeixinWorkflowEngine
from tests.test_agent_workflows import FakeDriver


def test_runtime_workflow_and_health_share_logger_instance_id(tmp_path, qapp):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    engine = WeixinWorkflowEngine(driver_factory=FakeDriver, diagnostics=diagnostics)
    runtime = AgentRuntime(engine_factory=lambda: engine, diagnostics=diagnostics)
    try:
        runtime._forward_notice("agent.status", {"status": "ready"})
        first_health = runtime.inspect()
        health = engine._driver_action("health", "inspect", engine.inspect)
        runtime._forward_notice("agent.status", {"status": "health", "health": health})
    finally:
        runtime.close()
    entries = [json.loads(line) for line in diagnostics.path.read_text(encoding="utf-8").splitlines()]
    assert any(entry["stage"] == "runtime" for entry in entries)
    assert any(entry["stage"] == "health" for entry in entries)
    assert {entry["agentInstanceId"] for entry in entries} == {diagnostics.agent_instance_id}
    assert first_health["agentInstanceId"] == diagnostics.agent_instance_id
    assert health["agentInstanceId"] == diagnostics.agent_instance_id


@pytest.mark.parametrize("diagnostics", [None, SimpleNamespace(record=lambda **entry: None)])
def test_engines_without_logger_identity_get_independent_stable_uuids(diagnostics):
    first = WeixinWorkflowEngine(driver_factory=FakeDriver, diagnostics=diagnostics)
    second = WeixinWorkflowEngine(driver_factory=FakeDriver, diagnostics=diagnostics)
    try:
        first_id = first.inspect()["agentInstanceId"]
        second_id = second.inspect()["agentInstanceId"]
        assert uuid.UUID(first_id).version == 4
        assert uuid.UUID(second_id).version == 4
        assert first_id != second_id
        assert first.inspect()["agentInstanceId"] == first_id
    finally:
        first.close()
        second.close()
