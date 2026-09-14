from __future__ import annotations

import json
from dataclasses import dataclass

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
