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
    ) -> dict[str, Any]:
        record = {
            "taskId": str(task_id),
            "kind": str(kind),
            "itemId": str(item_id),
            "boundary": str(boundary),
            "itemIndex": int(item_index),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
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


__all__ = ["SafetyJournal"]
