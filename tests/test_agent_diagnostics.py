from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from app.agent.diagnostics import UiaDiagnostics


@dataclass(frozen=True)
class FakeRectangle:
    left: int
    top: int
    right: int
    bottom: int


class FakeControl:
    Name = "do not leak this message"
    ControlTypeName = "TextControl"
    ClassName = "mmui::MessageView"
    AutomationId = "message_item_7"
    RuntimeId = (42, 7)
    BoundingRectangle = FakeRectangle(10, 20, 110, 60)
    IsOffscreen = False
    NativeWindowHandle = 9001


def test_record_writes_structured_metadata_without_identifier_or_payload_text(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)

    written = diagnostics.record(
        stage="message_open",
        action="verify_chat",
        outcome="success",
        window={
            "hwnd": 9001,
            "pid": 321,
            "title": "Alice Secret",
            "class": "mmui::MainWindow",
            "bounds": (0, 0, 800, 600),
            "visible": True,
        },
        control=FakeControl(),
        account="wx-secret-id",
        contact="Alice Secret",
        payload_text="do not leak this message",
    )
    diagnostics.close()

    raw = (tmp_path / "uia-diagnostics.jsonl").read_text(encoding="utf-8")
    entry = json.loads(raw)

    assert entry == written
    assert entry["timestamp"].endswith("Z")
    assert entry["stage"] == "message_open"
    assert entry["action"] == "verify_chat"
    assert entry["outcome"] == "success"
    assert entry["window"] == {
        "hwnd": 9001,
        "pid": 321,
        "title": {
            "length": 12,
            "hashPrefix": "sha256:70b02494643d",
        },
        "class": "mmui::MainWindow",
        "bounds": [0, 0, 800, 600],
        "visible": True,
    }
    assert entry["control"] == {
        "name": {
            "length": 24,
            "hashPrefix": "sha256:bf68c1a73b40",
        },
        "type": "TextControl",
        "class": "mmui::MessageView",
        "automationId": "message_item_7",
        "runtimeId": [42, 7],
        "bounds": [10, 20, 110, 60],
        "visible": True,
        "ownerWindow": {"hwnd": 9001},
    }
    assert entry["account"] == {
        "length": 12,
        "hashPrefix": "sha256:6bebaaa3019e",
    }
    assert entry["contact"] == {
        "length": 12,
        "hashPrefix": "sha256:70b02494643d",
    }
    assert entry["payload"] == {
        "length": 24,
        "sha256": "bf68c1a73b40883abd9bdd6c39419b713f53b9b527f54cc7ae3d379dc7a33fe0",
    }
    assert "wx-secret-id" not in raw
    assert "Alice Secret" not in raw
    assert "do not leak this message" not in raw


def test_jsonl_rotation_keeps_only_the_configured_backups(tmp_path):
    diagnostics = UiaDiagnostics(
        log_dir=tmp_path,
        max_bytes=420,
        backup_count=3,
    )

    for index in range(20):
        diagnostics.record(
            stage="rotation",
            action=f"snapshot_{index}",
            outcome="success",
            contact="Alice Secret",
            payload_text="do not leak this message",
        )
    diagnostics.close()

    paths = sorted(tmp_path.glob("uia-diagnostics.jsonl*"))
    assert [path.name for path in paths] == [
        "uia-diagnostics.jsonl",
        "uia-diagnostics.jsonl.1",
        "uia-diagnostics.jsonl.2",
        "uia-diagnostics.jsonl.3",
    ]
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        assert "Alice Secret" not in raw
        assert "do not leak this message" not in raw
        for line in raw.splitlines():
            assert json.loads(line)["stage"] == "rotation"


def test_default_path_is_beneath_local_appdata_wxauto_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    diagnostics = UiaDiagnostics()

    diagnostics.record(stage="restore", action="bind", outcome="success")
    diagnostics.close()

    assert diagnostics.path == tmp_path / "WxAuto" / "logs" / "uia-diagnostics.jsonl"
    assert diagnostics.path.is_file()


def test_production_rotation_defaults_are_two_mib_and_three_backups(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)

    assert diagnostics._handler.maxBytes == 2 * 1024 * 1024
    assert diagnostics._handler.backupCount == 3

    diagnostics.close()


def test_record_includes_timing_query_session_and_retry_metadata(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)

    entry = diagnostics.record(
        stage="target_selected",
        action="search_contacts",
        outcome="retry",
        duration_ms=184,
        query_count=3,
        session_generation=2,
        attempt=2,
        max_attempts=3,
        retry_level="same_session",
        retry_in_ms=800,
        error_code="TRANSIENT_UI",
        hresult=-2147220991,
    )
    diagnostics.close()

    assert entry["metrics"] == {
        "durationMs": 184,
        "queryCount": 3,
        "sessionGeneration": 2,
    }
    assert entry["retry"] == {
        "attempt": 2,
        "maxAttempts": 3,
        "level": "same_session",
        "retryInMs": 800,
    }
    assert entry["error"] == {
        "code": "TRANSIENT_UI",
        "hresult": "0x80040201",
    }


def test_record_includes_correlation_process_and_build_provenance(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path, agent_instance_id="agent-17")
    try:
        entry = diagnostics.record(
            stage="send_verified", action="verify", outcome="success",
            task_id="task-1", item_id="item-2", action_id="action-3",
            phase="postcondition", result="confirmed", postcondition=True,
            context={"queryCount": 2, "contact": "private contact"},
            detail="private contact sent a private message",
        )
    finally:
        diagnostics.close()

    assert entry["taskId"] == "task-1"
    assert entry["itemId"] == "item-2"
    assert entry["actionId"] == "action-3"
    assert entry["agentInstanceId"] == "agent-17"
    assert entry["phase"] == "postcondition"
    assert entry["result"] == "confirmed"
    assert entry["postcondition"] is True
    assert entry["pid"] == os.getpid()
    assert entry["threadId"] == threading.get_ident()
    assert entry["nativeThreadId"] == threading.get_native_id()
    assert entry["build"]["version"] == "0.3.3"
    assert entry["build"]["buildFingerprint"].startswith("sha256:")
    assert entry["context"]["queryCount"] == 2
    assert entry["context"]["contact"]["hashPrefix"].startswith("sha256:")
    assert entry["detail"]["length"] == 38
    assert "private contact" not in json.dumps(entry)
    assert "private message" not in json.dumps(entry)


def test_record_never_queries_live_properties_or_runtime_id(tmp_path):
    accesses = []

    class LiveControl:
        @property
        def Name(self):
            accesses.append("Name")
            return "live secret"

        @property
        def BoundingRectangle(self):
            accesses.append("BoundingRectangle")
            return FakeRectangle(1, 2, 3, 4)

        def GetRuntimeId(self):
            accesses.append("GetRuntimeId")
            return (42, 7)

        def __getattr__(self, name):
            accesses.append(name)
            raise AttributeError(name)

    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="runtime", action="snapshot", outcome="success",
            window=LiveControl(), control=LiveControl(), owner_window=LiveControl(),
        )
    finally:
        diagnostics.close()

    assert accesses == []
    assert entry["window"]["title"] is None
    assert entry["control"]["runtimeId"] == []


def test_record_accepts_native_cached_metadata_and_instance_override(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="runtime", action="snapshot", outcome="success",
            agent_instance_id="replacement-agent", native_window={
                "hwnd": 456, "pid": 789, "title": "private title",
                "class": "mmui::MainWindow", "bounds": [1, 2, 301, 402],
                "visible": False,
            },
            control={"runtimeId": [4, 2], "ownerWindow": 456},
        )
    finally:
        diagnostics.close()
    assert entry["window"]["hwnd"] == 456
    assert entry["window"]["bounds"] == [1, 2, 301, 402]
    assert entry["window"]["visible"] is False
    assert entry["control"]["runtimeId"] == [4, 2]
    assert entry["agentInstanceId"] == "replacement-agent"
    assert "private title" not in json.dumps(entry)


def test_nested_context_redacts_secrets_without_stringifying_live_objects(tmp_path):
    class LiveValue:
        def __str__(self):
            raise AssertionError("must not inspect arbitrary objects")

    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="runtime", action="snapshot", outcome="error",
            context={
                "attempt": 2, "verified": False,
                "password": 123456, "environment": {"TOKEN": "secret token"},
                "nested": [{"text": "secret message", "count": 4}],
                "control": LiveValue(),
            },
            detail=LiveValue(),
        )
    finally:
        diagnostics.close()
    assert entry["context"]["attempt"] == 2
    assert entry["context"]["verified"] is False
    assert entry["context"]["nested"][0]["count"] == 4
    raw = json.dumps(entry)
    for secret in ("123456", "secret token", "secret message"):
        assert secret not in raw


def test_workflow_flat_native_snapshot_populates_window_without_live_reads(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="verify", action="postcondition", outcome="success",
            window=None, result=False, postcondition=False,
            context={
                "hwnd": 44, "pid": 55, "windowClass": "mmui::MainWindow",
                "windowResponsive": True, "sessionGeneration": 3,
                "degradedReason": "UIA_UNAVAILABLE", "taskKind": "send_message",
            },
        )
    finally:
        diagnostics.close()
    assert entry["window"]["hwnd"] == 44
    assert entry["window"]["pid"] == 55
    assert entry["window"]["class"] == "mmui::MainWindow"
    assert entry["result"] is False
    assert entry["postcondition"] is False
    assert entry["context"]["degradedReason"] == "UIA_UNAVAILABLE"
    assert entry["context"]["taskKind"] == "send_message"


def test_logger_instance_id_is_stable_and_thread_ids_describe_each_caller(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    entries = []

    def write():
        entries.append(diagnostics.record(stage="runtime", action="snapshot", outcome="success"))

    try:
        write()
        thread = threading.Thread(target=write)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        diagnostics.close()
    assert len(entries) == 2
    assert isinstance(entries[0]["agentInstanceId"], str)
    assert entries[0]["agentInstanceId"]
    assert entries[0]["agentInstanceId"] == entries[1]["agentInstanceId"]
    assert entries[0]["threadId"] != entries[1]["threadId"]
    assert entries[0]["nativeThreadId"] != entries[1]["nativeThreadId"]
    assert entries[0]["build"] == entries[1]["build"]


def test_logger_does_not_invoke_proxy_getattribute_or_string_hooks(tmp_path):
    accesses = []

    class Proxy:
        def __getattribute__(self, name):
            accesses.append(name)
            raise AttributeError(name)

        def __str__(self):
            raise AssertionError("must not stringify proxies")

    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        diagnostics.record(
            stage="runtime", action="snapshot", outcome="success",
            window=Proxy(), control=Proxy(), owner_window=Proxy(),
            context={"proxy": Proxy()}, detail=Proxy(),
        )
    finally:
        diagnostics.close()
    assert accesses == []


def test_numeric_detail_and_private_context_values_are_redacted(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="runtime", action="snapshot", outcome="success",
            detail=13812345678,
            context={"contact": 13812345678, "account": [13812345678], "queryCount": 2},
        )
    finally:
        diagnostics.close()
    assert entry["detail"]["length"] == 11
    assert entry["context"]["contact"]["length"] == 11
    assert entry["context"]["queryCount"] == 2
    assert "13812345678" not in json.dumps(entry)


@pytest.mark.parametrize("summary", [
    {"type": "bool", "value": False}, {"type": "bool", "value": True},
    {"type": "str", "length": 32}, {"type": "NoneType"},
])
def test_content_free_result_summaries_are_preserved(tmp_path, summary):
    context = MappingProxyType({"hwnd": 44, "windowResponsive": True})
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="send_verified", action="verify_sent", outcome="unconfirmed",
            result=summary, postcondition=False, context=context,
        )
    finally:
        diagnostics.close()
    assert entry["result"] == summary
    assert entry["postcondition"] is False
    assert entry["outcome"] == "unconfirmed"
    assert entry["window"]["hwnd"] == 44
    assert dict(context) == {"hwnd": 44, "windowResponsive": True}


def test_started_event_has_no_synthetic_duration_or_postcondition(tmp_path):
    diagnostics = UiaDiagnostics(log_dir=tmp_path)
    try:
        entry = diagnostics.record(
            stage="send_verified", action="verify_sent", outcome="started",
            phase="started", postcondition=None,
        )
    finally:
        diagnostics.close()
    assert "metrics" not in entry
    assert "postcondition" not in entry
    assert "result" not in entry
