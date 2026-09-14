from __future__ import annotations

import json
import os
import tempfile
import threading
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
        safety_path = os.environ.get("WECHAT_AGENT_JOURNAL", "").strip()
        if safety_path:
            return cls(safety_path + ".gate")
        return cls(
            Path(tempfile.gettempdir())
            / f"wuge-wechat-agent-{os.getppid()}-gate.json"
        )

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict) or not GATE_LEASE_FIELDS <= payload.keys():
                return None
            try:
                payload["pid"] = int(payload["pid"])
                payload["gateRva"] = int(payload["gateRva"])
                payload["originalGate"] = int(payload["originalGate"])
                payload["sessionGeneration"] = int(payload["sessionGeneration"])
                payload["processStartTime"] = str(payload["processStartTime"])
                payload["version"] = str(payload["version"])
                payload["originalScreenReader"] = bool(
                    payload["originalScreenReader"]
                )
                payload["gateOwned"] = bool(payload["gateOwned"])
                payload["screenReaderOwned"] = bool(
                    payload["screenReaderOwned"]
                )
            except (TypeError, ValueError):
                return None
            if payload["originalGate"] not in (0, 1):
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
        with self._lock:
            _write_atomic(self.path, record)
        return record

    def clear(self) -> bool:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
            return True


__all__ = ["GateLeaseJournal", "SafetyJournal"]
