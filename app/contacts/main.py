from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

from app.agent.rpc import JsonLineDecoder, encode_frame, notification
from .security import validate_bootstrap, verify_pipe_server
from .diagnostics import ReadDiagnostics, safe_diagnostics
from .native import ContactError


class _ReadWorker(QThread):
    progress = Signal(object)
    completed = Signal(object)

    def __init__(self, reader, account, cancel, parent=None):
        super().__init__(parent)
        self.reader, self.account, self.cancel = reader, account, cancel

    def run(self):
        diagnostics = ReadDiagnostics()
        def progress(stage, done=0, total=0):
            diagnostics.stage = stage
            self.progress.emit({"stage": stage, "done": done, "total": total,
                                "diagnostics": diagnostics.snapshot()})
        try:
            records = self.reader(self.account, cancel=self.cancel,
                deadline=time.monotonic() + 60, progress=progress, diagnostics=diagnostics)
            result = {"success": True, "records": records}
        except Exception as exc:
            result = {"success": False, "code": exc.code if isinstance(exc, ContactError) else "READER_FAILED"}
        if self.cancel.is_set(): result = {"success": False, "code": "CANCELLED"}
        result["diagnostics"] = diagnostics.snapshot()
        self.completed.emit(result)


class ContactReaderService(QObject):
    def __init__(self, config, reader, parent=None):
        super().__init__(parent)
        self.config, self.reader = config, reader
        self.socket = QLocalSocket(self)
        self.decoder = JsonLineDecoder()
        self.cancelled = threading.Event()
        self.worker = None
        self.authenticated, self.used = False, False
        self.records, self.offset = [], 0
        self.diagnostics = {}
        self.socket.connected.connect(self._connected)
        self.socket.readyRead.connect(self._read)
        self.socket.disconnected.connect(self._disconnected)
        self.socket.errorOccurred.connect(lambda _: self._disconnected())
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(lambda: self._notify("heartbeat", {}))
        self.stream = QTimer(self)
        self.stream.setInterval(5)
        self.stream.timeout.connect(self._stream)
        QTimer.singleShot(10_000, self._authentication_timeout)
        self.socket.connectToServer(config["pipe"])

    def _connected(self):
        try:
            verify_pipe_server(int(self.socket.socketDescriptor()), self.config)
        except Exception:
            self._disconnected()
            return
        self._send({"jsonrpc": "2.0", "id": 1, "method": "exporter.hello", "params": {
            "token": self.config["token"], "jobId": self.config["jobId"], "pid": os.getpid()}})

    def _authentication_timeout(self):
        if not self.authenticated: self._disconnected()

    def _send(self, value):
        try:
            self.socket.write(encode_frame(value))
        except Exception:
            self._disconnected()

    def _notify(self, method, params):
        self._send(notification(method, {"jobId": self.config["jobId"], **params}))

    def _read(self):
        try:
            frames = self.decoder.feed(bytes(self.socket.readAll()))
        except Exception:
            self._disconnected()
            return
        for frame in frames:
            if frame.get("jsonrpc") != "2.0":
                self._disconnected()
                return
            if not self.authenticated:
                result = frame.get("result")
                if (frame.get("id") != 1 or not isinstance(result, dict)
                        or result.get("authenticated") is not True):
                    self._disconnected()
                    return
                self.authenticated = True
                self.heartbeat.start()
                continue
            method, params = frame.get("method"), frame.get("params", {})
            if not isinstance(params, dict):
                self._disconnected()
                return
            if method == "contacts.read" and not self.used:
                try:
                    verify_pipe_server(int(self.socket.socketDescriptor()), self.config)
                except Exception:
                    self._disconnected()
                    return
                account = params.get("account")
                if (params.get("jobId") != self.config["jobId"] or not isinstance(account, dict)
                        or not isinstance(account.get("contactDb"), str)
                        or not isinstance(account.get("accountId"), str)):
                    self._notify("contacts.finished", {"success": False, "code": "INVALID_FRAME"})
                    QTimer.singleShot(100, QCoreApplication.instance().quit)
                    continue
                self.used = True
                self.worker = _ReadWorker(self.reader, account, self.cancelled, self)
                self.worker.progress.connect(lambda value: self._notify("contacts.progress", value))
                self.worker.completed.connect(self._completed)
                self._notify("contacts.progress", {"stage": "scanning"})
                self.worker.start()
            elif method == "contacts.cancel":
                self.cancelled.set()
                self.stream.stop()
                QTimer.singleShot(2500, lambda: os._exit(2))
            elif method == "exporter.shutdown":
                self._disconnected()
            else:
                self._disconnected()

    def _completed(self, result):
        self.worker.wait(1000)
        self.diagnostics = safe_diagnostics(result.get("diagnostics"))
        if not result.get("success"):
            self._notify("contacts.finished", result)
            QTimer.singleShot(100, QCoreApplication.instance().quit)
            return
        self.records = result["records"]
        self.stream.start()

    def _stream(self):
        if self.cancelled.is_set():
            self._notify("contacts.finished", {"success": False, "code": "CANCELLED"})
            self.stream.stop()
            QTimer.singleShot(100, QCoreApplication.instance().quit)
            return
        if self.socket.bytesToWrite() > 256 * 1024: return
        if self.offset >= len(self.records):
            self._notify("contacts.finished", {"success": True, "count": len(self.records),
                                              "diagnostics": self.diagnostics})
            self.records = []
            self.stream.stop()
            QTimer.singleShot(100, QCoreApplication.instance().quit)
            return
        batch, end = [], self.offset
        while end < len(self.records) and len(batch) < 128:
            candidate = batch + [self.records[end]]
            try:
                size = len(encode_frame(notification("contacts.rows", {
                    "jobId": self.config["jobId"], "rows": candidate})))
            except Exception:
                size = 1024 * 1024
            if size > 256 * 1024:
                if not batch:
                    self._notify("contacts.finished", {"success": False, "code": "DATABASE_INVALID"})
                    self.stream.stop()
                    QTimer.singleShot(100, QCoreApplication.instance().quit)
                    return
                break
            batch, end = candidate, end + 1
        self.offset = end
        self._notify("contacts.rows", {"rows": batch})

    def _disconnected(self):
        self.cancelled.set()
        self.heartbeat.stop()
        self.stream.stop()
        if self.worker and self.worker.isRunning():
            QTimer.singleShot(2500, lambda: os._exit(2))
        else:
            QTimer.singleShot(0, QCoreApplication.instance().quit)


def main(reader=None):
    parser = argparse.ArgumentParser(description="Read-only WeChat contact helper")
    parser.add_argument("--bootstrap", required=True)
    args = parser.parse_args()
    try:
        config = validate_bootstrap(Path(args.bootstrap))
    except Exception:
        return 3
    if reader is None:
        from .reader import read_contacts
        reader = read_contacts
    app = QCoreApplication(sys.argv)
    service = ContactReaderService(config, reader)
    result = app.exec()
    if service.worker and service.worker.isRunning():
        os._exit(2)
    return result


if __name__ == "__main__":
    sys.exit(main())
