from __future__ import annotations

import os
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

from .rpc import JsonLineDecoder, encode_frame


class AgentClient(QObject):
    stateChanged = Signal(str)
    connectedChanged = Signal(bool)
    replyReceived = Signal(int, object)
    rpcError = Signal(int, int, str)
    notificationReceived = Signal(str, object)
    processError = Signal(str)
    helloReceived = Signal(object)

    def __init__(
        self,
        *,
        heartbeat_timeout_ms: int = 3_500,
        journal_path: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._socket = QLocalSocket(self)
        self._socket.connected.connect(self._on_socket_connected)
        self._socket.disconnected.connect(self._on_socket_disconnected)
        self._socket.readyRead.connect(self._read_available)
        self._socket.errorOccurred.connect(self._on_socket_error)
        self._decoder = JsonLineDecoder()
        self._process: QProcess | None = None
        self._executable: str | None = None
        self._pipe_name = ""
        self._token = ""
        self._journal_path = journal_path or str(
            Path(tempfile.gettempdir())
            / f"wuge-wechat-agent-{os.getpid()}-{uuid.uuid4().hex}-safety.json"
        )
        self._state = "stopped"
        self._connected = False
        self._next_id = 1
        self._hello_id = 0
        self._last_heartbeat_ms = 0
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(max(100, heartbeat_timeout_ms // 3))
        self._watchdog.timeout.connect(self._check_heartbeat)
        self._retry = QTimer(self)
        self._retry.setInterval(100)
        self._retry.timeout.connect(self._retry_connection)
        self._connect_attempts = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def pipe_name(self) -> str:
        return self._pipe_name

    def _set_state(self, value: str) -> None:
        if value == self._state:
            return
        self._state = value
        self.stateChanged.emit(value)

    def _set_connected(self, value: bool) -> None:
        if value == self._connected:
            return
        self._connected = value
        self.connectedChanged.emit(value)

    def start(self, executable: str | None = None) -> None:
        if self._process is not None:
            return
        if executable is not None:
            self._executable = executable
        self._pipe_name = "wuge-wechat-agent-" + uuid.uuid4().hex
        self._token = secrets.token_hex(32)
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WECHAT_AGENT_PIPE", self._pipe_name)
        environment.insert("WECHAT_AGENT_TOKEN", self._token)
        environment.insert("WECHAT_AGENT_JOURNAL", self._journal_path)
        process.setProcessEnvironment(environment)
        process.errorOccurred.connect(
            lambda error: self.processError.emit(process.errorString())
        )
        process.finished.connect(self._on_process_finished)
        if self._executable:
            process.setProgram(self._executable)
        elif getattr(sys, "frozen", False):
            process.setProgram(str(Path(sys.executable).with_name("wechat-agent.exe")))
        else:
            process.setProgram(sys.executable)
            process.setArguments(["-m", "app.agent.main"])
        self._process = process
        self._set_state("starting")
        process.start()
        self._connect_attempts = 0
        self._retry.start()

    def connect_to_server(self, pipe_name: str, token: str) -> None:
        self._pipe_name = pipe_name
        self._token = token
        self._decoder = JsonLineDecoder()
        self._set_state("connecting")
        self._socket.connectToServer(pipe_name)

    def _retry_connection(self) -> None:
        if self._socket.state() != QLocalSocket.UnconnectedState:
            return
        self._connect_attempts += 1
        if self._connect_attempts > 100:
            self._retry.stop()
            self._set_state("error")
            self.processError.emit("wechat-agent connection timed out")
            return
        self.connect_to_server(self._pipe_name, self._token)

    def _on_socket_connected(self) -> None:
        self._retry.stop()
        self._set_state("authenticating")
        self._hello_id = self.call("agent.hello", {"token": self._token})

    def _on_socket_disconnected(self) -> None:
        self._watchdog.stop()
        self._set_connected(False)
        if self._state != "stopped":
            self._set_state("disconnected")

    def _on_socket_error(self, _error) -> None:
        if self._process is None and self._state != "stopped":
            self._set_state("error")

    def _on_process_finished(self, _exit_code: int, _exit_status) -> None:
        self._process = None
        if self._state != "stopped":
            self._set_state("disconnected")
            self._set_connected(False)

    def call(self, method: str, params: dict[str, Any] | None = None) -> int:
        request_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        if self._socket.write(encode_frame(message)) < 0:
            raise ConnectionError(self._socket.errorString())
        self._socket.flush()
        return request_id

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        if self._socket.write(encode_frame(message)) < 0:
            raise ConnectionError(self._socket.errorString())
        self._socket.flush()

    def _read_available(self) -> None:
        try:
            messages = self._decoder.feed(bytes(self._socket.readAll()))
        except Exception as exc:
            self.processError.emit(str(exc))
            self._socket.abort()
            return
        for message in messages:
            if "method" in message and "id" not in message:
                method = str(message["method"])
                params = message.get("params") or {}
                if method == "heartbeat":
                    self._last_heartbeat_ms = self._now_ms()
                self.notificationReceived.emit(method, params)
                continue
            request_id = int(message.get("id", 0) or 0)
            if "error" in message:
                error = message["error"]
                self.rpcError.emit(
                    request_id,
                    int(error.get("code", -32000)),
                    str(error.get("message", "RPC error")),
                )
                continue
            result = message.get("result")
            if request_id == self._hello_id:
                self._last_heartbeat_ms = self._now_ms()
                self._set_connected(True)
                self._set_state("connected")
                self._watchdog.start()
                self.helloReceived.emit(result or {})
            self.replyReceived.emit(request_id, result)

    @staticmethod
    def _now_ms() -> int:
        import time

        return int(time.monotonic() * 1000)

    def _check_heartbeat(self) -> None:
        if not self._connected:
            return
        if self._now_ms() - self._last_heartbeat_ms <= self._heartbeat_timeout_ms:
            return
        self.processError.emit("wechat-agent heartbeat timed out")
        self._socket.abort()
        self._set_connected(False)
        self._set_state("disconnected")

    def close(self) -> None:
        self._retry.stop()
        self._watchdog.stop()
        self._set_state("stopped")
        self._set_connected(False)
        socket = self._socket
        if socket.state() != QLocalSocket.UnconnectedState:
            socket.abort()
        process = self._process
        self._process = None
        if process is not None:
            process.terminate()
            if not process.waitForFinished(1_500):
                process.kill()
                process.waitForFinished(500)

    def restart(self) -> None:
        self.close()
        self.start(self._executable)


__all__ = ["AgentClient"]
