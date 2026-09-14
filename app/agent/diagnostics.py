from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping

from app.build_info import build_info


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3
DEFAULT_FILENAME = "uia-diagnostics.jsonl"


def gui_instance_id_from_environment() -> str | None:
    """Accept only UUID text, never arbitrary environment content."""
    value = os.environ.get("WECHAT_GUI_INSTANCE_ID", "")
    if len(value) not in (32, 36):
        return None
    try:
        identity = uuid.UUID(value)
    except ValueError:
        return None
    return identity.hex if value.lower() in (identity.hex, str(identity)) else None


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        result = inspect.getattr_static(value, name)
        if inspect.getattr_static(type(result), "__get__", None) is not None:
            return default
    except Exception:
        return default
    return default if result is None else result


def _lookup(value: Any, *names: str, default: Any = None) -> Any:
    if issubclass(type(value), Mapping):
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
    if type(value) in (tuple, list) and len(value) == 4:
        if not all(type(part) in (int, float) for part in value):
            return None
        try:
            return [int(part) for part in value]
        except (TypeError, ValueError, OverflowError):
            return None
    return _bounds([_safe_attr(value, name) for name in ("left", "top", "right", "bottom")])


def _text(value: Any) -> str:
    return str(value) if type(value) in (str, int, float, bool) else ""


def _cached_int(value: Any) -> int | None:
    return value if type(value) is int else None


def _cached_bool(value: Any) -> bool | None:
    return bool(value) if type(value) in (bool, int) else None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_identifier(value: Any) -> dict[str, Any]:
    text = _text(value)
    return {
        "length": len(text),
        "hashPrefix": f"sha256:{_hash(text)[:12]}",
    }


def payload_fingerprint(value: Any) -> dict[str, Any]:
    text = _text(value)
    return {"length": len(text), "sha256": _hash(text)}


def window_metadata(window: Any) -> dict[str, Any]:
    """Read only copied values; descriptors and live UIA methods are never used."""
    title = _text(_lookup(window, "title", "Name", default=""))
    visible = _lookup(window, "visible", "IsVisible", default=None)
    if visible is None:
        offscreen = _lookup(window, "IsOffscreen", default=None)
        offscreen = _cached_bool(offscreen)
        visible = None if offscreen is None else not offscreen
    return {
        "hwnd": _cached_int(_lookup(window, "hwnd", "handle", "NativeWindowHandle")),
        "pid": _cached_int(_lookup(window, "pid", "processId", "ProcessId")),
        "title": redact_identifier(title) if title else None,
        "class": _text(
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
        "visible": _cached_bool(visible),
    }


def _runtime_id(control: Any) -> list[int]:
    value = _lookup(control, "runtimeId", "RuntimeId", default=())
    if type(value) in (tuple, list) and all(type(part) is int for part in value):
        return list(value)
    return []


def control_metadata(control: Any, owner_window: Any = None) -> dict[str, Any]:
    name = _text(_lookup(control, "name", "Name", default=""))
    visible = _lookup(control, "visible", "IsVisible", default=None)
    if visible is None:
        offscreen = _lookup(control, "IsOffscreen", default=None)
        offscreen = _cached_bool(offscreen)
        visible = None if offscreen is None else not offscreen
    owner = owner_window
    if owner is None:
        owner = _lookup(
            control,
            "ownerWindow",
            "NativeWindowHandle",
            default=None,
        )
    if type(owner) is int:
        owner_metadata: dict[str, Any] | None = {"hwnd": owner}
    elif owner is None:
        owner_metadata = None
    else:
        owner_metadata = window_metadata(owner)
    return {
        "name": redact_identifier(name) if name else None,
        "type": _text(
            _lookup(control, "type", "ControlTypeName", default="")
        ),
        "class": _text(_lookup(control, "class", "ClassName", default="")),
        "automationId": _text(
            _lookup(control, "automationId", "AutomationId", default="")
        ),
        "runtimeId": _runtime_id(control),
        "bounds": _bounds(
            _lookup(control, "bounds", "BoundingRectangle", default=None)
        ),
        "visible": _cached_bool(visible),
        "ownerWindow": owner_metadata,
    }


_SECRET_KEY = re.compile(
    r"password|passwd|secret|token|credential|authorization|cookie|environment|api_?key|^env$",
    re.I,
)
_CONTEXT_CODES = {
    "degradedReason", "taskKind", "windowState", "phase", "status",
    "errorCode", "retryLevel", "version",
}
_PRIVATE_KEY = re.compile(r"contact|account|payload|message|text|phone|email|title|name|path|detail", re.I)
_RESULT_TYPES = {"bool", "str", "int", "float", "list", "tuple", "dict", "NoneType", "none"}


def _redacted_context(value: Any, depth: int = 0, *, private: bool = False) -> Any:
    if depth >= 6:
        return "[omitted]"
    if value is None:
        return value
    if private and type(value) in (bool, int, float):
        return redact_identifier(value)
    if type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is str:
        return redact_identifier(value)
    if issubclass(type(value), Mapping):
        result = {}
        for index, (key, part) in enumerate(value.items()):
            if index >= 64:
                break
            if type(key) is not str:
                continue
            safe_key = (
                key if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key)
                else _hash(key)[:12]
            )
            if _SECRET_KEY.search(key):
                result[safe_key] = "[redacted]"
            elif not private and key == "type" and type(part) is str and part in _RESULT_TYPES:
                result[safe_key] = part
            elif not private and key in _CONTEXT_CODES and type(part) is str and re.fullmatch(
                r"[A-Za-z0-9_.:+-]{1,80}", part
            ):
                result[safe_key] = part
            else:
                result[safe_key] = _redacted_context(
                    part, depth + 1, private=private or bool(_PRIVATE_KEY.search(key)),
                )
        return result
    if type(value) in (list, tuple):
        return [_redacted_context(part, depth + 1, private=private) for part in value[:64]]
    return "[omitted]"


def default_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "WxAuto" / "logs"


class UiaDiagnostics:
    """Rotating JSONL records from native/cached data, never live UIA queries."""

    def __init__(
        self,
        *,
        log_dir: str | os.PathLike[str] | None = None,
        filename: str = DEFAULT_FILENAME,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        agent_instance_id: str | None = None,
    ):
        self.agent_instance_id = _text(agent_instance_id) or uuid.uuid4().hex
        self._gui_instance_id = gui_instance_id_from_environment()
        self._build = build_info()
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
        duration_ms: int | float | None = None,
        query_count: int | None = None,
        session_generation: int | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
        retry_level: str | None = None,
        retry_in_ms: int | None = None,
        error_code: str | None = None,
        hresult: int | None = None,
        task_id: str | None = None,
        item_id: str | None = None,
        action_id: str | None = None,
        agent_instance_id: str | None = None,
        phase: str | None = None,
        result: Any = None,
        postcondition: bool | None = None,
        context: Mapping[str, Any] | None = None,
        detail: Any = None,
        native_window: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        cached_window = native_window if native_window is not None else window
        if cached_window is None and issubclass(type(context), Mapping):
            cached_window = context.get("window")
            if cached_window is None:
                cached_window = context
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "stage": str(stage),
            "action": str(action),
            "outcome": str(outcome),
            "window": window_metadata(cached_window),
            "control": control_metadata(control, owner_window),
            "pid": os.getpid(),
            "threadId": threading.get_ident(),
            "nativeThreadId": threading.get_native_id(),
            "agentInstanceId": _text(agent_instance_id) or self.agent_instance_id,
            "guiInstanceId": self._gui_instance_id,
            "build": dict(self._build),
        }
        for key, value in (
            ("taskId", task_id), ("itemId", item_id), ("actionId", action_id),
            ("phase", phase),
        ):
            if value is not None:
                entry[key] = _text(value)
        if result is not None:
            entry["result"] = result if type(result) is str and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,63}", result
            ) else _redacted_context(result)
        if postcondition is not None:
            entry["postcondition"] = _redacted_context(postcondition)
        if context is not None:
            entry["context"] = _redacted_context(context)
        if detail is not None:
            entry["detail"] = _redacted_context(detail, private=True)
        if account is not None:
            entry["account"] = redact_identifier(account)
        if contact is not None:
            entry["contact"] = redact_identifier(contact)
        if payload_text is not None:
            entry["payload"] = payload_fingerprint(payload_text)
        metrics = {}
        if duration_ms is not None:
            metrics["durationMs"] = max(0, int(round(duration_ms)))
        if query_count is not None:
            metrics["queryCount"] = max(0, int(query_count))
        if session_generation is not None:
            metrics["sessionGeneration"] = max(0, int(session_generation))
        if metrics:
            entry["metrics"] = metrics
        retry = {}
        if attempt is not None:
            retry["attempt"] = max(1, int(attempt))
        if max_attempts is not None:
            retry["maxAttempts"] = max(1, int(max_attempts))
        if retry_level is not None:
            retry["level"] = str(retry_level)
        if retry_in_ms is not None:
            retry["retryInMs"] = max(0, int(retry_in_ms))
        if retry:
            entry["retry"] = retry
        error = {}
        if error_code:
            error["code"] = str(error_code)
        if hresult is not None:
            error["hresult"] = f"0x{int(hresult) & 0xFFFFFFFF:08X}"
        if error:
            entry["error"] = error
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
    "gui_instance_id_from_environment",
    "payload_fingerprint",
    "redact_identifier",
    "window_metadata",
]
