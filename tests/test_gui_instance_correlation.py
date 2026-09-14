import json
import uuid

import pytest
from PySide6.QtCore import QProcess

from app.agent.client import AgentClient
from app.agent.diagnostics import UiaDiagnostics
from app.agent.runtime import AgentRuntime
from tests.test_agent_runtime import RecordingEngine


def test_client_gui_id_survives_agent_restart_and_is_passed_to_each_child(
    tmp_path, qapp, monkeypatch,
):
    environments = []
    monkeypatch.setattr(QProcess, "start", lambda process: environments.append(process.processEnvironment()))
    monkeypatch.setenv("WECHAT_GUI_INSTANCE_ID", "untrusted inherited value")
    client = AgentClient(diagnostics_log_dir=tmp_path)
    other = AgentClient(diagnostics_log_dir=tmp_path)
    monkeypatch.setattr(client, "_run_gate_recovery", lambda: True)
    try:
        identity = getattr(client, "gui_instance_id", None)
        assert isinstance(identity, str), "AgentClient must expose a GUI lifetime UUID"
        assert uuid.UUID(identity).version == 4
        assert other.gui_instance_id != identity
        client.start("not-launched.exe")
        client.restart()
        assert client.gui_instance_id == identity
        assert len(environments) == 2
        assert [env.value("WECHAT_GUI_INSTANCE_ID") for env in environments] == [identity, identity]
        assert environments[0].value("WECHAT_AGENT_TOKEN") != environments[1].value("WECHAT_AGENT_TOKEN")
    finally:
        client.close()
        other.close()


@pytest.mark.parametrize("environment_id,expected", [
    ("f329818d568f4fcc890bf712582e282b", "f329818d568f4fcc890bf712582e282b"),
    ("F329818D-568F-4FCC-890B-F712582E282B", "f329818d568f4fcc890bf712582e282b"),
    (None, None), ("password=private-secret", None), ("a" * 64, None),
    ("f329818d568f4fcc890bf712582e282b\nprivate-secret", None),
])
def test_diagnostics_and_hello_share_only_validated_gui_uuid(
    tmp_path, qapp, monkeypatch, environment_id, expected,
):
    if environment_id is None:
        monkeypatch.delenv("WECHAT_GUI_INSTANCE_ID", raising=False)
    else:
        monkeypatch.setenv("WECHAT_GUI_INSTANCE_ID", environment_id)
    monkeypatch.setenv("WECHAT_AGENT_TOKEN", "private-rpc-token")
    monkeypatch.setenv("UNRELATED_SECRET", "private-unrelated-secret")
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    runtime = AgentRuntime(engine_factory=RecordingEngine)
    try:
        entry = diagnostics.record(stage="runtime", action="hello", outcome="success")
        hello = runtime.hello()
        assert "guiInstanceId" in entry
        assert entry["guiInstanceId"] == expected
        assert hello["guiInstanceId"] == expected
        monkeypatch.setenv("WECHAT_GUI_INSTANCE_ID", "changed-private-secret")
        assert diagnostics.record(stage="runtime", action="next", outcome="success")["guiInstanceId"] == expected
        assert runtime.hello()["guiInstanceId"] == expected
    finally:
        diagnostics.close()
        runtime.close()
    raw = diagnostics.path.read_text(encoding="utf-8") + json.dumps(hello)
    for secret in ("private-secret", "private-rpc-token", "private-unrelated-secret", "changed-private-secret"):
        assert secret not in raw
