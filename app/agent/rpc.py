from __future__ import annotations

import json
from typing import Any


JSONRPC_VERSION = "2.0"
MAX_FRAME_SIZE = 1024 * 1024


class RpcError(RuntimeError):
    """Base error for local RPC protocol failures."""


class FrameTooLarge(RpcError):
    """Raised when a peer sends a frame larger than the protocol limit."""


class InvalidFrame(RpcError):
    """Raised when a peer sends malformed JSON or a non-object payload."""


def encode_frame(message: dict[str, Any], max_frame_size: int = MAX_FRAME_SIZE) -> bytes:
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > max_frame_size:
        raise FrameTooLarge(f"RPC frame exceeds {max_frame_size} bytes")
    return encoded + b"\n"


class JsonLineDecoder:
    def __init__(self, max_frame_size: int = MAX_FRAME_SIZE):
        self.max_frame_size = max_frame_size
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(data)
        messages: list[dict[str, Any]] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                if len(self._buffer) > self.max_frame_size:
                    self._buffer.clear()
                    raise FrameTooLarge(
                        f"RPC frame exceeds {self.max_frame_size} bytes"
                    )
                break
            if newline > self.max_frame_size:
                del self._buffer[: newline + 1]
                raise FrameTooLarge(
                    f"RPC frame exceeds {self.max_frame_size} bytes"
                )
            raw = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if not raw:
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidFrame("invalid JSON-RPC frame") from exc
            if not isinstance(message, dict):
                raise InvalidFrame("JSON-RPC frame must contain an object")
            messages.append(message)
        return messages


def notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params or {},
    }


def _result(request_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": value}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class AgentRpcRouter:
    """Authenticated fixed-surface dispatcher for the agent process."""

    def __init__(self, token: str, runtime):
        self._token = token
        self._runtime = runtime
        self.authenticated = False

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request.get("jsonrpc") != JSONRPC_VERSION:
            return _error(request_id, -32600, "invalid JSON-RPC version")
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return _error(request_id, -32600, "invalid request")

        if method == "agent.hello":
            if params.get("token") != self._token:
                return _error(request_id, -32001, "authentication failed")
            self.authenticated = True
            return _result(request_id, self._runtime.hello())

        if not self.authenticated:
            return _error(request_id, -32001, "agent.hello is required")

        handlers = {
            "wechat.inspect": lambda: self._runtime.inspect(),
            "task.start": lambda: self._runtime.start_task(params),
            "task.pause": lambda: self._runtime.pause_task(),
            "task.resume": lambda: self._runtime.resume_task(),
            "task.stop": lambda: self._runtime.stop_task(),
            "recovery.approve": lambda: self._runtime.approve_recovery(params),
            "agent.shutdown": lambda: self._runtime.shutdown(),
        }
        handler = handlers.get(method)
        if handler is None:
            return _error(request_id, -32601, f"method not found: {method}")
        try:
            value = handler()
        except (TypeError, ValueError) as exc:
            return _error(request_id, -32602, str(exc))
        except Exception as exc:
            return _error(request_id, -32000, str(exc))
        return None if request_id is None else _result(request_id, value)

