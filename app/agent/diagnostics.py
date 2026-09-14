from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3
DEFAULT_FILENAME = "uia-diagnostics.jsonl"


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        result = getattr(value, name)
    except Exception:
        return default
    return default if result is None else result


def _lookup(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value and value[name] is not None:
                return value[name]
        return default
    for name in names:
        result = _safe_attr(value, name, None)
        if result is not None:
            return result
    return default


def _bounds(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) == 4:
        try:
            return [int(part) for part in value]
        except (TypeError, ValueError):
            return None
    try:
        return [
            int(value.left),
            int(value.top),
            int(value.right),
            int(value.bottom),
        ]
    except (AttributeError, TypeError, ValueError):
        return None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_identifier(value: Any) -> dict[str, Any]:
    text = str(value)
    return {
        "length": len(text),
        "hashPrefix": f"sha256:{_hash(text)[:12]}",
    }


def payload_fingerprint(value: Any) -> dict[str, Any]:
    text = str(value)
    return {"length": len(text), "sha256": _hash(text)}


def window_metadata(window: Any) -> dict[str, Any]:
    title = str(_lookup(window, "title", "Name", default=""))
    visible = _lookup(window, "visible", "IsVisible", default=None)
    if visible is None:
        offscreen = _lookup(window, "IsOffscreen", default=None)
        visible = None if offscreen is None else not bool(offscreen)
    return {
        "hwnd": _lookup(window, "hwnd", "handle", "NativeWindowHandle"),
        "pid": _lookup(window, "pid", "processId", "ProcessId"),
        "title": redact_identifier(title) if title else None,
        "class": str(
            _lookup(
                window,
                "class",
                "windowClass",
                "ClassName",
                default="",
            )
        ),
        "bounds": _bounds(
            _lookup(window, "bounds", "BoundingRectangle", default=None)
        ),
        "visible": None if visible is None else bool(visible),
    }


def _runtime_id(control: Any) -> list[int]:
    try:
        value = control.GetRuntimeId()
    except Exception:
        value = _lookup(control, "runtimeId", "RuntimeId", default=())
    try:
        return [int(part) for part in value]
    except (TypeError, ValueError):
        return []


def control_metadata(control: Any, owner_window: Any = None) -> dict[str, Any]:
    name = str(_lookup(control, "name", "Name", default=""))
    visible = _lookup(control, "visible", "IsVisible", default=None)
    if visible is None:
        offscreen = _lookup(control, "IsOffscreen", default=None)
        visible = None if offscreen is None else not bool(offscreen)
    owner = owner_window
    if owner is None:
        owner = _lookup(
            control,
            "ownerWindow",
            "NativeWindowHandle",
            default=None,
        )
    if isinstance(owner, int):
        owner_metadata: dict[str, Any] | None = {"hwnd": owner}
    elif owner is None:
        owner_metadata = None
    else:
        owner_metadata = window_metadata(owner)
    return {
        "name": redact_identifier(name) if name else None,
        "type": str(
            _lookup(control, "type", "ControlTypeName", default="")
        ),
        "class": str(_lookup(control, "class", "ClassName", default="")),
        "automationId": str(
            _lookup(control, "automationId", "AutomationId", default="")
        ),
        "runtimeId": _runtime_id(control),
        "bounds": _bounds(
            _lookup(control, "bounds", "BoundingRectangle", default=None)
        ),
        "visible": None if visible is None else bool(visible),
        "ownerWindow": owner_metadata,
    }


def default_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "WxAuto" / "logs"


class UiaDiagnostics:
    """Privacy-safe rotating JSONL diagnostics for UI Automation probes."""

    def __init__(
        self,
        *,
        log_dir: str | os.PathLike[str] | None = None,
        filename: str = DEFAULT_FILENAME,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ):
        directory = Path(log_dir) if log_dir is not None else default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / filename
        self._logger = logging.Logger(
            f"wxauto.uia.diagnostics.{id(self)}", level=logging.INFO
        )
        self._logger.propagate = False
        self._handler = RotatingFileHandler(
            self.path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._handler)

    def record(
        self,
        *,
        stage: str,
        action: str,
        outcome: str,
        window: Any = None,
        control: Any = None,
        owner_window: Any = None,
        account: Any = None,
        contact: Any = None,
        payload_text: Any = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "stage": str(stage),
            "action": str(action),
            "outcome": str(outcome),
            "window": window_metadata(window),
            "control": control_metadata(control, owner_window),
        }
        if account is not None:
            entry["account"] = redact_identifier(account)
        if contact is not None:
            entry["contact"] = redact_identifier(contact)
        if payload_text is not None:
            entry["payload"] = payload_fingerprint(payload_text)
        self._logger.info(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        )
        return entry

    def close(self) -> None:
        self._logger.removeHandler(self._handler)
        self._handler.close()


__all__ = [
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_FILENAME",
    "DEFAULT_MAX_BYTES",
    "UiaDiagnostics",
    "control_metadata",
    "default_log_dir",
    "payload_fingerprint",
    "redact_identifier",
    "window_metadata",
]
