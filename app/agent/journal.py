from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "taskId",
    "kind",
    "itemId",
    "boundary",
    "itemIndex",
    "timestamp",
}

GATE_LEASE_FIELDS = {
    "pid",
    "processStartTime",
    "version",
    "gateRva",
    "originalGate",
    "originalScreenReader",
    "gateOwned",
    "screenReaderOwned",
    "sessionGeneration",
    "timestamp",
}


def default_gate_lease_path() -> Path:
    """Return the cross-GUI lease used by the one Windows automation session."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return base / "WxAuto" / "state" / "weixin-uia-gate-v1.json"


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class SafetyJournal:
    """Tiny durable record guarding destructive Weixin actions from replay."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "SafetyJournal":
        configured = os.environ.get("WECHAT_AGENT_JOURNAL", "").strip()
        if configured:
            return cls(configured)
        return cls(
            Path(tempfile.gettempdir())
            / f"wuge-wechat-agent-{os.getppid()}-safety.json"
        )

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict) or not REQUIRED_FIELDS <= payload.keys():
                return None
            if not all(str(payload.get(key, "")).strip() for key in REQUIRED_FIELDS - {"itemIndex"}):
                return None
            try:
                payload["itemIndex"] = int(payload["itemIndex"])
                payload["sessionGeneration"] = int(
                    payload.get("sessionGeneration", 0)
                )
            except (TypeError, ValueError):
                return None
            return payload

    def mark(
        self,
        *,
        task_id: str,
        kind: str,
        item_id: str,
        boundary: str,
        item_index: int,
        session_generation: int = 0,
    ) -> dict[str, Any]:
        record = {
            "taskId": str(task_id),
            "kind": str(kind),
            "itemId": str(item_id),
            "boundary": str(boundary),
            "itemIndex": int(item_index),
            "sessionGeneration": int(session_generation),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            _write_atomic(self.path, record)
        return record

    def clear(
        self,
        *,
        task_id: str | None = None,
        item_id: str | None = None,
    ) -> bool:
        with self._lock:
            current = self.load()
            if current is None:
                return False
            if task_id is not None and current["taskId"] != task_id:
                return False
            if item_id is not None and current["itemId"] != item_id:
                return False
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
            return True


class GateLeaseJournal:
    """Durable ownership record for the reversible Weixin UIA gate."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "GateLeaseJournal":
        configured = os.environ.get("WECHAT_AGENT_GATE_LEASE", "").strip()
        if configured:
            return cls(configured)
        return cls(default_gate_lease_path())

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict) or not GATE_LEASE_FIELDS <= payload.keys():
                return None
            schema = payload.get("schemaVersion", 1)
            if type(schema) is not int or schema not in (1, 2):
                return None
            if schema == 2:
                if not all(isinstance(payload.get(key), str) and payload[key].strip()
                           for key in ("logonId", "logonTime", "ownerAgentStartTime")):
                    return None
                if type(payload.get("ownerAgentPid")) is not int or payload["ownerAgentPid"] <= 0:
                    return None
                if type(payload.get("windowsSessionId")) is not int:
                    return None
            integer_fields = (
                "pid",
                "gateRva",
                "originalGate",
                "sessionGeneration",
            )
            boolean_fields = (
                "originalScreenReader",
                "gateOwned",
                "screenReaderOwned",
            )
            if not all(type(payload[field]) is int for field in integer_fields):
                return None
            if not all(type(payload[field]) is bool for field in boolean_fields):
                return None
            if "windowsSessionId" in payload and (
                type(payload["windowsSessionId"]) is not int or payload["windowsSessionId"] < 0
            ):
                return None
            if not all(
                isinstance(payload[field], str) and payload[field].strip()
                for field in ("processStartTime", "version", "timestamp")
            ):
                return None
            if (
                payload["pid"] <= 0
                or payload["gateRva"] < 0
                or payload["sessionGeneration"] < 0
                or payload["originalGate"] not in (0, 1)
            ):
                return None
            return payload

    def mark(
        self,
        *,
        pid: int,
        process_start_time: str | int,
        version: str,
        gate_rva: int,
        original_gate: int,
        original_screen_reader: bool,
        gate_owned: bool,
        screen_reader_owned: bool,
        session_generation: int,
        windows_session_id: int | None = None,
        lease_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "pid": int(pid),
            "processStartTime": str(process_start_time),
            "version": str(version),
            "gateRva": int(gate_rva),
            "originalGate": int(original_gate),
            "originalScreenReader": bool(original_screen_reader),
            "gateOwned": bool(gate_owned),
            "screenReaderOwned": bool(screen_reader_owned),
            "sessionGeneration": int(session_generation),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if windows_session_id is not None:
            record["windowsSessionId"] = int(windows_session_id)
        if lease_context is not None:
            record.update({key: lease_context[key] for key in (
                "windowsSessionId", "logonId", "logonTime", "ownerAgentPid", "ownerAgentStartTime"
            )})
            record["schemaVersion"] = 2
        with self._lock:
            _write_atomic(self.path, record)
        return record

    def archive(self, reason: str, *, recovery_id: str = "") -> str:
        """Keep evidence on the same volume; never discard a corrupt lease."""
        with self._lock:
            if not self.path.exists():
                return ""
            destination = self.path.parent / "gate-archive" / f"{uuid.uuid4().hex}-{self.path.name}"
            metadata = {"source": str(self.path), "reason": reason,
                        "recoveryId": recovery_id, "timestamp": datetime.now(timezone.utc).isoformat()}
            _write_atomic(destination.with_name(destination.name + ".meta.json"), metadata)
            os.replace(self.path, destination)
            self.last_archive = str(destination)
            return str(destination)

    def clear(self) -> bool:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
            return True


__all__ = ["GateLeaseJournal", "SafetyJournal", "default_gate_lease_path"]
