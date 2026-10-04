from __future__ import annotations

import ctypes
import json
import os
import secrets
import subprocess
import sys
import threading
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from app.agent.rpc import JsonLineDecoder, encode_frame
from .security import current_user_sid, private_directory, restrict_path, cleanup_bootstraps


class ContactReaderClient(QObject):
    eventReceived = Signal(str, object)

    def __init__(self, parent=None, *, command=None, bootstrap_root=None, snapshot_root=None):
        super().__init__(parent)
        self._command = command
        self._snapshot_root = Path(snapshot_root or tempfile.gettempdir())
        self._bootstrap_root = Path(bootstrap_root) if bootstrap_root else (
            Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "FugeWeChatAssistant" / "contacts")
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._accept)
        self._socket = None
        self._process = None
        self._elevated_handle = None
        self._pid = 0
        self._job = ""
        self._account = {}
        self._token = ""
        self._bootstrap_dir = None
        self._decoder = JsonLineDecoder()
        self._authenticated = False
        self._result = None
        self._cancel_code = ""
        self._last_heartbeat = 0.0
        self._started_at = 0.0
        self._deadline = 0.0
        self._stopping_at = 0.0
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(100)
        self._watchdog.timeout.connect(self._watch)

    @property
    def processRunning(self):
        return not self._wait_for_exit()

    def _wait_for_exit(self, timeout_ms=0):
        timeout_ms = max(0, int(timeout_ms))
        if self._process is not None:
            process = self._process
            if timeout_ms and process.state() != QProcess.NotRunning:
                process.waitForFinished(timeout_ms)
            return process.state() == QProcess.NotRunning
        if self._elevated_handle is not None:
            try:
                import win32event
                return win32event.WaitForSingleObject(
                    self._elevated_handle, timeout_ms) == win32event.WAIT_OBJECT_0
            except Exception:
                # Unknown status is not permission to release a live child.
                return False
        return True

    def start(self, account, job_id, *, elevated=False):
        if self._job: raise RuntimeError("Contact reader is already running")
        self._job, self._account = job_id, dict(account)
        try:
            self._launch(elevated)
        except PermissionError:
            self._finalize({"success": False, "code": "ACCESS_DENIED"})
        except Exception:
            self._finalize({"success": False, "code": "READER_FAILED"})

    def _launch(self, elevated):
        from .native import current_job_identity
        cleanup_bootstraps(self._bootstrap_root)
        identity = current_job_identity()
        self._token = secrets.token_hex(32)
        self._cancel_code, self._result, self._authenticated = "", None, False
        self._decoder = JsonLineDecoder()
        self._started_at = time.monotonic()
        self._bootstrap_dir = private_directory(self._bootstrap_root, "bootstrap-")
        name = "fuge-contacts-" + secrets.token_hex(16)
        if not self._server.listen(name):
            self._finalize({"success": False, "code": "READER_FAILED"})
            return
        bootstrap = self._bootstrap_dir / "launch.json"
        bootstrap.write_text(json.dumps({"schemaVersion": 1, "ownerSid": current_user_sid(),
            "pipe": name, "token": self._token, "jobId": self._job,
            "guiPid": os.getpid(), "guiStartTime": identity["startTime"]}), encoding="utf-8")
        restrict_path(bootstrap)
        command = self._command or (
            [str(Path(sys.executable).with_name("wechat-contact-reader.exe"))]
            if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.contacts.main"])
        command = [*command, "--bootstrap", str(bootstrap)]
        if elevated:
            try:
                import win32com.shell.shell as shell
                import win32com.shell.shellcon as shellcon
                result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
                    lpVerb="runas", lpFile=command[0], lpParameters=subprocess.list2cmdline(command[1:]),
                    lpDirectory=str(Path(__file__).resolve().parents[2]), nShow=0)
                self._elevated_handle = result["hProcess"]
                get_pid = ctypes.windll.kernel32.GetProcessId
                get_pid.argtypes, get_pid.restype = [ctypes.c_void_p], ctypes.c_ulong
                self._pid = int(get_pid(int(self._elevated_handle)))
            except Exception as exc:
                code = "CANCELLED" if getattr(exc, "winerror", None) == 1223 else "ACCESS_DENIED"
                self._finalize({"success": False, "code": code})
                return
        else:
            process = QProcess(self)
            process.setProgram(command[0])
            process.setArguments(command[1:])
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
            # Neither SQL statements nor child exception text enter diagnostics.
            process.setStandardOutputFile(QProcess.nullDevice())
            process.setStandardErrorFile(QProcess.nullDevice())
            process.finished.connect(self._process_finished)
            process.errorOccurred.connect(self._process_error)
            self._process = process
            process.start()
        self._started_at = time.monotonic()
        self._watchdog.start()

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._finalize({"success": False, "code": "READER_FAILED"})

    def _accept(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if self._socket is not None:
                socket.abort()
                socket.deleteLater()
                continue
            self._socket = socket
            socket.readyRead.connect(self._read)
            socket.disconnected.connect(self._disconnected)

    def _send(self, method, params=None, request_id=2):
        if self._socket is not None:
            self._socket.write(encode_frame({"jsonrpc": "2.0", "id": request_id,
                "method": method, "params": params or {}}))

    def _peer_pid(self):
        if os.name != "nt": return self._pid
        pid = ctypes.c_ulong()
        function = ctypes.windll.kernel32.GetNamedPipeClientProcessId
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        function.restype = ctypes.c_bool
        return int(pid.value) if function(int(self._socket.socketDescriptor()), ctypes.byref(pid)) else 0

    def _read(self):
        try:
            frames = self._decoder.feed(bytes(self._socket.readAll()))
            for frame in frames:
                if frame.get("jsonrpc") != "2.0": raise ValueError("Invalid frame")
                params = frame.get("params", {})
                if not isinstance(params, dict): raise ValueError("Invalid frame")
                if not self._authenticated:
                    self._pid = self._pid or int(self._process.processId())
                    if (frame.get("method") != "exporter.hello" or params.get("token") != self._token
                            or params.get("jobId") != self._job or params.get("pid") != self._pid
                            or self._peer_pid() != self._pid):
                        raise ValueError("Invalid handshake")
                    self._authenticated = True
                    self._deadline = time.monotonic() + 60
                    self._last_heartbeat = time.monotonic()
                    self._socket.write(encode_frame({"jsonrpc": "2.0", "id": frame.get("id"),
                        "result": {"authenticated": True}}))
                    self._send("contacts.read", {"jobId": self._job, "account": self._account})
                    if self._cancel_code: self._send("contacts.cancel")
                    continue
                if params.get("jobId") != self._job: raise ValueError("Invalid job")
                method = frame.get("method")
                if method == "heartbeat":
                    self._last_heartbeat = time.monotonic()
                elif method == "contacts.finished":
                    self._result = params
                elif method in ("contacts.progress", "contacts.rows"):
                    if self._result is not None: raise ValueError("Data after completion")
                    self.eventReceived.emit(method, params)
                else:
                    raise ValueError("Invalid notification")
        except Exception:
            self._abort("INVALID_FRAME")

    def _disconnected(self):
        if self._job and self._result is None and not self._cancel_code:
            self._abort("READER_DISCONNECTED")

    def _watch(self):
        if not self._job: return
        now = time.monotonic()
        if self._elevated_handle is not None and not self.processRunning:
            try:
                import win32process
                code = win32process.GetExitCodeProcess(self._elevated_handle)
            except Exception:
                code = None
            self._process_finished(code, None)
            return
        if self._stopping_at and now - self._stopping_at >= 3:
            self._kill()
        elif self._authenticated and now >= self._deadline:
            self._abort("TIMEOUT")
        elif not self._authenticated and now - self._started_at >= 10:
            self._abort("TIMEOUT")
        elif self._authenticated and self._result is None and (
                now - self._last_heartbeat > 3.5):
            self._abort("TIMEOUT")
        elif self._result is not None and now - self._last_heartbeat > 3.5:
            self._abort("READER_FAILED")

    def _abort(self, code):
        if not self._job: return
        if not self._cancel_code: self._cancel_code = code
        if not self._stopping_at:
            self._stopping_at = time.monotonic()
            self._send("contacts.cancel")
        if not self.processRunning:
            self._finalize({"success": False, "code": self._cancel_code})
        elif not self._watchdog.isActive():
            self._watchdog.start()

    def cancel(self): self._abort("CANCELLED")

    def _kill(self):
        try:
            if self._process is not None:
                self._process.kill()
            elif self._elevated_handle is not None:
                import win32api
                win32api.TerminateProcess(self._elevated_handle, 2)
        except Exception:
            if self._socket: self._socket.abort()

    def _process_finished(self, code, _status):
        if not self._job: return
        result = {"success": False, "code": self._cancel_code} if self._cancel_code else self._result
        if result is None or (code != 0 and result.get("success")):
            result = {"success": False, "code": "READER_FAILED"}
        self._finalize(result)

    def _finalize(self, result):
        if self.processRunning:
            if result.get("success"):
                self._result = dict(result)
                self._watchdog.start()
            else:
                self._abort(result.get("code") or "READER_FAILED")
            return not bool(self._job)
        job = self._job
        self._job = ""
        self._watchdog.stop()
        if self._socket is not None:
            self._socket.abort()
            self._socket.deleteLater()
            self._socket = None
        self._server.close()
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if self._elevated_handle is not None:
            self._elevated_handle.Close()
            self._elevated_handle = None
        if self._bootstrap_dir is not None:
            try:
                (self._bootstrap_dir / "launch.json").unlink(missing_ok=True)
                self._bootstrap_dir.rmdir()
            except OSError:
                pass
        self._bootstrap_dir, self._token, self._account = None, "", {}
        self._pid, self._stopping_at = 0, 0.0
        try:
            from .snapshot import cleanup_leftovers
            cleanup_leftovers(self._snapshot_root, cancel=threading.Event(), deadline=time.monotonic() + 2)
        except Exception:
            # Only verified, dead, private jobs may be cleaned on the next read.
            pass
        if job: self.eventReceived.emit("contacts.finished", {**result, "jobId": job})
        return True

    def close(self, timeout_ms=3000) -> bool:
        """Bound child waits; False keeps ownership until a later confirmed exit."""
        if not self._job:
            return self._wait_for_exit()
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000
        self._abort("CANCELLED")
        if not self._job:
            return True
        if self._socket is not None:
            self._socket.flush()
        grace_ms = min(2500, max(0, int((deadline - time.monotonic()) * 1000)))
        if not self._wait_for_exit(grace_ms):
            self._kill()
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if not self._wait_for_exit(remaining_ms):
                return False
        if self._job:
            return self._finalize({"success": False, "code": self._cancel_code})
        return True
