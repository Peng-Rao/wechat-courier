from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .rpc import AgentRpcRouter, JsonLineDecoder, encode_frame, notification


class AgentServer(QObject):
    """Single-client JSON-RPC server backed by a Windows named pipe."""

    stopped = Signal()

    def __init__(
        self,
        pipe_name: str,
        token: str,
        runtime,
        *,
        heartbeat_interval_ms: int = 1_000,
        disconnect_grace_ms: int = 1_000,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.pipe_name = pipe_name
        self.runtime = runtime
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._accept_connection)
        self._socket: QLocalSocket | None = None
        self._decoder = JsonLineDecoder()
        self._router = AgentRpcRouter(token, runtime)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(heartbeat_interval_ms)
        self._heartbeat.timeout.connect(self._send_heartbeat)
        self._disconnect_grace = QTimer(self)
        self._disconnect_grace.setSingleShot(True)
        self._disconnect_grace.setInterval(max(1, int(disconnect_grace_ms)))
        self._disconnect_grace.timeout.connect(
            self._expire_disconnected_client
        )
        self._closing = False
        if hasattr(runtime, "set_notification_sink"):
            runtime.set_notification_sink(self.send_notification)

    @property
    def authenticated(self) -> bool:
        return self._router.authenticated

    def listen(self) -> bool:
        if self._server.isListening():
            return True
        ok = self._server.listen(self.pipe_name)
        if ok:
            self._heartbeat.start()
        return ok

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._heartbeat.stop()
        self._disconnect_grace.stop()
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.disconnectFromServer()
            socket.deleteLater()
        self._server.close()
        self.stopped.emit()

    def _accept_connection(self) -> None:
        incoming = self._server.nextPendingConnection()
        if incoming is None:
            return
        if self._socket is not None:
            incoming.abort()
            incoming.deleteLater()
            return
        self._decoder = JsonLineDecoder()
        self._socket = incoming
        incoming.readyRead.connect(self._read_available)
        incoming.disconnected.connect(self._on_disconnected)

    def _on_disconnected(self, socket: QLocalSocket | None = None) -> None:
        if socket is None:
            sender = self.sender()
            socket = sender if isinstance(sender, QLocalSocket) else None
        if socket is not None and self._socket is not socket:
            socket.deleteLater()
            return
        was_authenticated = self.authenticated
        if self._socket is not None:
            self._socket.deleteLater()
            self._socket = None
        self._router.authenticated = False
        stop = getattr(self.runtime, "stop_task", None)
        if callable(stop):
            stop()
        if was_authenticated and not self._closing:
            self._disconnect_grace.start()

    def _expire_disconnected_client(self) -> None:
        if self._closing or self.authenticated:
            return
        shutdown = getattr(self.runtime, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _read_available(self) -> None:
        if self._socket is None:
            return
        try:
            messages = self._decoder.feed(bytes(self._socket.readAll()))
            for message in messages:
                if (
                    self.authenticated
                    and message.get("method") == "wechat.inspect"
                    and hasattr(self.runtime, "inspect_async")
                ):
                    self._start_inspection(message.get("id"))
                    continue
                was_authenticated = self.authenticated
                response = self._router.handle(message)
                if not was_authenticated and self.authenticated:
                    self._disconnect_grace.stop()
                if response is not None:
                    self._write(response)
        except Exception as exc:
            request_id = None
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32700, "message": str(exc)},
                }
            )

    def _start_inspection(self, request_id) -> None:
        request_socket = self._socket
        def complete(result, error) -> None:
            if self._socket is not request_socket:
                return
            if error is not None:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(error)},
                    }
                )
                return
            if request_id is not None:
                self._write(
                    {"jsonrpc": "2.0", "id": request_id, "result": result or {}}
                )

        self.runtime.inspect_async(complete)

    def _write(self, message: dict[str, Any]) -> bool:
        if self._socket is None:
            return False
        return self._socket.write(encode_frame(message)) >= 0

    def send_notification(self, method: str, params: dict[str, Any]) -> bool:
        if not self.authenticated:
            return False
        return self._write(notification(method, params))

    def _send_heartbeat(self) -> None:
        self.send_notification(
            "heartbeat",
            {"pid": os.getpid()},
        )
