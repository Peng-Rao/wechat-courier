from __future__ import annotations

import os
import re
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

from .rpc import JsonLineDecoder, encode_frame
from .diagnostics import default_log_dir
from .instance_lock import AGENT_ALREADY_RUNNING_EXIT_CODE
from .journal import SafetyJournal, default_gate_lease_path


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
        gate_lease_path: str | os.PathLike[str] | None = None,
        diagnostics_log_dir: str | os.PathLike[str] | None = None,
        stderr_max_bytes: int = 2 * 1024 * 1024,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._gui_instance_id = uuid.uuid4().hex
        self._socket = QLocalSocket(self)
        self._socket.connected.connect(self._on_socket_connected)
        self._socket.disconnected.connect(self._on_socket_disconnected)
        self._socket.readyRead.connect(self._read_available)
        self._socket.errorOccurred.connect(self._on_socket_error)
        self._decoder = JsonLineDecoder()
        self._process: QProcess | None = None
        self._recovery_process: QProcess | None = None
        self._pending_start_after_recovery = False
        self._executable: str | None = None
        self._pipe_name = ""
        self._token = ""
        self._journal_path = journal_path or str(
            Path(tempfile.gettempdir())
            / f"wuge-wechat-agent-{os.getpid()}-{uuid.uuid4().hex}-safety.json"
        )
        self._gate_lease_path = str(
            Path(gate_lease_path)
            if gate_lease_path is not None
            else default_gate_lease_path()
        )
        log_dir = (
            Path(diagnostics_log_dir)
            if diagnostics_log_dir is not None
            else default_log_dir()
        )
        self._stderr_path = log_dir / "agent-stderr.log"
        self._stderr_max_bytes = max(1, int(stderr_max_bytes))
        self._stderr_backup_count = 2
        self._state = "stopped"
        self._connected = False
        self._next_id = 1
        self._hello_id = 0
        self._last_heartbeat_ms = 0
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(max(100, heartbeat_timeout_ms // 3))
        self._watchdog.timeout.connect(self._check_heartbeat)
        self._gate_recovery_timeout = QTimer(self)
        self._gate_recovery_timeout.setSingleShot(True)
        # Includes the Agent's five-second ownership wait, then startup/rollback.
        self._gate_recovery_timeout.setInterval(8_000)
        self._gate_recovery_timeout.timeout.connect(
            self._on_gate_recovery_timeout
        )
        self._retry = QTimer(self)
        self._retry.setInterval(100)
        self._retry.timeout.connect(self._retry_connection)
        self._connect_attempts = 0
        self._shutdown_requested = False

    @property
    def gui_instance_id(self) -> str:
        return self._gui_instance_id

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
        if self._recovery_process is not None:
            self._pending_start_after_recovery = True
            self._shutdown_requested = False
            self._set_state("recovering_gate")
            return
        self._shutdown_requested = False
        self._pipe_name = "wuge-wechat-agent-" + uuid.uuid4().hex
        self._token = secrets.token_hex(32)
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WECHAT_AGENT_PIPE", self._pipe_name)
        environment.insert("WECHAT_AGENT_TOKEN", self._token)
        environment.insert("WECHAT_AGENT_JOURNAL", self._journal_path)
        environment.insert("WECHAT_AGENT_GATE_LEASE", self._gate_lease_path)
        environment.insert("WECHAT_GUI_INSTANCE_ID", self._gui_instance_id)
        process.setProcessEnvironment(environment)
        process.errorOccurred.connect(
            lambda error: self.processError.emit(process.errorString())
        )
        process.finished.connect(self._on_process_finished)
        process.readyReadStandardError.connect(self._capture_process_stderr)
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

    def grant_foreground_permission(self) -> bool:
        if os.name != "nt" or self._process is None:
            return False
        pid = int(self._process.processId())
        if not pid:
            return False
        import ctypes

        return bool(ctypes.windll.user32.AllowSetForegroundWindow(pid))

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
        unexpected = self._state != "stopped" and not self._shutdown_requested
        shutdown_recovery = (
            self._shutdown_requested and self._state != "stopped"
            and (
                _exit_code != 0 or _exit_status == QProcess.ExitStatus.CrashExit
                or Path(self._gate_lease_path).is_file()
            )
        )
        self._capture_process_stderr()
        self._process = None
        if int(_exit_code) == AGENT_ALREADY_RUNNING_EXIT_CODE:
            self._retry.stop()
            self._watchdog.stop()
            self._set_connected(False)
            self._set_state("error")
            self.processError.emit(
                "已有自动化 Agent 正在操作微信，请先关闭其他助手实例后重试"
            )
            return
        if self._state != "stopped":
            self._set_state("disconnected")
            self._set_connected(False)
        if shutdown_recovery:
            # The GUI may exit immediately after waitForFinished returns.
            self._run_gate_recovery()
        elif unexpected:
            self._start_gate_recovery_async()

    def _capture_process_stderr(self) -> None:
        process = self._process
        if process is None:
            return
        raw = bytes(process.readAllStandardError())
        if raw:
            self._write_agent_stderr(raw)

    def _write_agent_stderr(self, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace")
        text = re.sub(
            r"(?i)\b[0-9a-f]{32,}\b",
            "[redacted-token]",
            text,
        )
        text = re.sub(
            r"(?<!\d)\d{7,20}(?!\d)",
            "[redacted-number]",
            text,
        )
        encoded = text.encode("utf-8")
        self._stderr_path.parent.mkdir(parents=True, exist_ok=True)
        current_size = (
            self._stderr_path.stat().st_size
            if self._stderr_path.exists()
            else 0
        )
        if current_size and current_size + len(encoded) > self._stderr_max_bytes:
            for index in range(self._stderr_backup_count, 0, -1):
                source = (
                    self._stderr_path
                    if index == 1
                    else self._stderr_path.with_name(
                        f"{self._stderr_path.name}.{index - 1}"
                    )
                )
                destination = self._stderr_path.with_name(
                    f"{self._stderr_path.name}.{index}"
                )
                if destination.exists():
                    destination.unlink()
                if source.exists():
                    source.replace(destination)
        with self._stderr_path.open("ab") as stream:
            stream.write(encoded)

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
        self._pending_start_after_recovery = False
        self._retry.stop()
        self._watchdog.stop()
        self._set_state("stopped")
        self._set_connected(False)
        socket = self._socket
        if socket.state() != QLocalSocket.UnconnectedState:
            socket.abort()
        process = self._process
        self._process = None
        forced = process is not None
        if process is not None:
            process.terminate()
            if not process.waitForFinished(1_500):
                process.kill()
                process.waitForFinished(500)
            self._process = process
            self._capture_process_stderr()
            self._process = None
        if forced:
            self._run_gate_recovery()

    def _run_gate_recovery(self) -> bool:
        """Best-effort cleanup after an Agent that could not exit normally."""

        process = QProcess()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WECHAT_AGENT_GATE_LEASE", self._gate_lease_path)
        environment.insert("WECHAT_GUI_INSTANCE_ID", self._gui_instance_id)
        process.setProcessEnvironment(environment)
        if self._executable:
            process.setProgram(self._executable)
            process.setArguments(["--recover-gate"])
        elif getattr(sys, "frozen", False):
            process.setProgram(str(Path(sys.executable).with_name("wechat-agent.exe")))
            process.setArguments(["--recover-gate"])
        else:
            process.setProgram(sys.executable)
            process.setArguments(["-m", "app.agent.main", "--recover-gate"])
        process.start()
        if not process.waitForFinished(self._gate_recovery_timeout.interval()):
            process.kill()
            process.waitForFinished(500)
            self.processError.emit("wechat-agent gate recovery timed out")
            return False
        if process.exitCode() != 0:
            detail = bytes(process.readAllStandardError()).decode(
                "utf-8", errors="replace"
            ).strip()
            self.processError.emit(detail or "wechat-agent gate recovery failed")
            return False
        return True

    def _start_gate_recovery_async(self) -> None:
        if self._recovery_process is not None:
            return
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WECHAT_AGENT_GATE_LEASE", self._gate_lease_path)
        environment.insert("WECHAT_GUI_INSTANCE_ID", self._gui_instance_id)
        process.setProcessEnvironment(environment)
        if self._executable:
            process.setProgram(self._executable)
            process.setArguments(["--recover-gate"])
        elif getattr(sys, "frozen", False):
            process.setProgram(
                str(Path(sys.executable).with_name("wechat-agent.exe"))
            )
            process.setArguments(["--recover-gate"])
        else:
            process.setProgram(sys.executable)
            process.setArguments(
                ["-m", "app.agent.main", "--recover-gate"]
            )

        def finished(exit_code, _exit_status):
            successful = int(exit_code) == 0
            detail = ""
            if not successful:
                detail = bytes(process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                ).strip()
            self._finish_gate_recovery(
                process,
                successful=successful,
                detail=detail or (
                    "" if successful else "wechat-agent gate recovery failed"
                ),
            )

        def failed(error):
            if error != QProcess.ProcessError.FailedToStart:
                return
            self._finish_gate_recovery(
                process,
                successful=False,
                detail=process.errorString()
                or "wechat-agent gate recovery failed to start",
            )

        process.finished.connect(finished)
        process.errorOccurred.connect(failed)
        self._recovery_process = process
        self._gate_recovery_timeout.start()
        process.start()

    def _finish_gate_recovery(
        self,
        process,
        *,
        successful: bool,
        detail: str = "",
    ) -> None:
        if self._recovery_process is not process:
            return
        self._gate_recovery_timeout.stop()
        self._recovery_process = None
        should_start = bool(
            successful
            and self._pending_start_after_recovery
            and self._state != "stopped"
        )
        self._pending_start_after_recovery = False
        if not successful:
            if self._state != "stopped":
                self._set_state("error")
            self.processError.emit(
                detail or "wechat-agent gate recovery failed"
            )
        process.deleteLater()
        if should_start:
            QTimer.singleShot(0, self.start)

    def _on_gate_recovery_timeout(self) -> None:
        process = self._recovery_process
        if process is None:
            return
        self._gate_recovery_timeout.stop()
        self._recovery_process = None
        self._pending_start_after_recovery = False
        if self._state != "stopped":
            self._set_state("error")
        self.processError.emit("wechat-agent gate recovery timed out")
        process.kill()
        process.waitForFinished(500)
        process.deleteLater()

    def restart(self) -> None:
        self.close()
        self.start(self._executable)

    def recovery_snapshot(self) -> dict[str, Any] | None:
        return SafetyJournal(self._journal_path).load()

    def shutdown(self, grace_ms: int = 2_500) -> None:
        self._shutdown_requested = True
        if self._connected:
            try:
                self.call("agent.shutdown")
                self._socket.waitForBytesWritten(250)
            except Exception:
                pass
        process = self._process
        if process is not None and process.waitForFinished(grace_ms):
            self._process = None
        self.close()


__all__ = ["AgentClient"]
