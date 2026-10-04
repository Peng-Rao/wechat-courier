import ctypes
import importlib
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QProcess

from app.contacts.client import ContactReaderClient


class ProcessHandle:
    def __init__(self):
        self.exited = False
        self.exit_code = 259
        self.closed = False
        self.wait_error = None
        self.code_error = None
        self.terminate_error = None
        self.waits = []

    def __int__(self):
        return 1

    def Close(self):
        self.closed = True


@pytest.fixture
def elevated_client(qapp, tmp_path, monkeypatch):
    handle = ProcessHandle()

    def wait(process, timeout):
        assert process is handle and not handle.closed
        handle.waits.append(timeout)
        if handle.wait_error:
            raise handle.wait_error
        return 0 if handle.exited else 258

    def exit_code(process):
        assert process is handle and not handle.closed
        if handle.code_error:
            raise handle.code_error
        return handle.exit_code

    def terminate(process, code):
        assert process is handle and code == 2 and not handle.closed
        if handle.terminate_error:
            raise handle.terminate_error

    replacements = {
        "win32event": {"WaitForSingleObject": wait, "WAIT_OBJECT_0": 0, "WAIT_TIMEOUT": 258},
        "win32process": {"GetExitCodeProcess": exit_code},
        "win32api": {"TerminateProcess": terminate},
    }
    for name, attributes in replacements.items():
        if os.name == "nt":
            module = importlib.import_module(name)
            for attribute, value in attributes.items():
                monkeypatch.setattr(module, attribute, value)
        else:
            monkeypatch.setitem(sys.modules, name, SimpleNamespace(**attributes))
    client = ContactReaderClient(bootstrap_root=tmp_path, snapshot_root=tmp_path / "snapshots")
    client._job = "owned-job"
    client._account = {"accountId": "fixture"}
    client._token = "private-token"
    client._bootstrap_dir = tmp_path / "bootstrap-owned"
    client._bootstrap_dir.mkdir()
    (client._bootstrap_dir / "launch.json").write_text("private-bootstrap", encoding="utf-8")
    client._elevated_handle = handle
    client._started_at = time.monotonic()
    client._watchdog.start()
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    yield client, handle, events
    handle.exited, handle.exit_code, handle.wait_error, handle.code_error = True, 2, None, None
    client._watch()
    client.close()


@pytest.mark.parametrize("denied", [False, True], ids=["termination-pending", "termination-denied"])
def test_close_retains_elevated_ownership_until_confirmed_exit(elevated_client, denied):
    client, handle, events = elevated_client
    if denied:
        handle.terminate_error = PermissionError("fixture termination denied")
    bootstrap = client._bootstrap_dir
    completed = client.close()

    assert client._elevated_handle is handle
    assert client._job == "owned-job"
    assert client.processRunning and client._watchdog.isActive()
    assert client._account == {"accountId": "fixture"}
    assert client._token == "private-token" and (bootstrap / "launch.json").exists()
    assert not handle.closed and not events
    assert completed is False
    with pytest.raises(RuntimeError, match="already running"):
        client.start({}, "replacement")

    handle.exited, handle.exit_code = True, 2
    client._watch()
    assert handle.closed and client._elevated_handle is None
    assert not client._job and not client._watchdog.isActive()
    assert not bootstrap.exists() and not client.processRunning
    assert events == [("contacts.finished", {
        "success": False, "code": "CANCELLED", "jobId": "owned-job"})]
    client._watch()
    assert len(events) == 1
    assert client.close() is True


def test_unknown_exit_status_keeps_watchdog_and_ownership(elevated_client):
    client, handle, events = elevated_client
    handle.wait_error = PermissionError("fixture status unavailable")
    handle.code_error = PermissionError("fixture status unavailable")

    assert client.processRunning
    assert client.close() is False
    client._watch()
    assert client._job == "owned-job" and client._elevated_handle is handle
    assert client._watchdog.isActive() and not handle.closed and not events

    handle.wait_error, handle.code_error, handle.exited, handle.exit_code = None, None, True, 2
    client._watch()
    assert not client._job and handle.closed
    assert events[-1][1]["code"] == "CANCELLED"


def test_finalization_refuses_to_release_live_elevated_child(elevated_client):
    client, handle, events = elevated_client
    completed = client._finalize({"success": False, "code": "ACCESS_DENIED"})
    assert client._elevated_handle is handle and not handle.closed
    assert client._job == "owned-job" and client._watchdog.isActive()
    assert not events and completed is False
    handle.exited, handle.exit_code = True, 2
    client._watch()
    assert events[-1][1]["code"] == "ACCESS_DENIED"


@pytest.mark.skipif(os.name != "nt", reason="Windows elevated launch boundary")
def test_setup_failure_after_shell_launch_retains_child_ownership(elevated_client, monkeypatch):
    import app.contacts.client as module
    import win32com.shell.shell as shell

    client, handle, events = elevated_client
    client._job, client._elevated_handle = "", None
    client._watchdog.stop()
    monkeypatch.setattr(shell, "ShellExecuteEx", lambda **_: {"hProcess": handle})

    def get_pid(_):
        raise PermissionError("fixture PID query denied after launch")

    monkeypatch.setattr(module, "ctypes", SimpleNamespace(c_void_p=ctypes.c_void_p,
        c_ulong=ctypes.c_ulong, windll=SimpleNamespace(kernel32=SimpleNamespace(GetProcessId=get_pid))))
    client.start({"accountId": "fixture"}, "launched-job", elevated=True)

    assert client._elevated_handle is handle and not handle.closed
    assert client._job == "launched-job" and client._watchdog.isActive()
    assert client.processRunning and not events
    handle.exited, handle.exit_code = True, 2
    client._watch()
    assert events == [("contacts.finished", {
        "success": False, "code": "ACCESS_DENIED", "jobId": "launched-job"})]


@pytest.mark.parametrize("exit_code", [0, 259])
def test_close_accepts_only_signaled_exit_even_with_still_active_exit_code(elevated_client, exit_code):
    client, handle, events = elevated_client
    handle.exited, handle.exit_code = True, exit_code
    assert client.close() is True
    assert not client.processRunning and handle.closed and not client._job
    assert len(events) == 1 and events[0][1]["code"] == "CANCELLED"


def test_zero_timeout_close_returns_pending_without_blocking(elevated_client):
    client, handle, events = elevated_client
    started = time.monotonic()
    assert client.close(timeout_ms=0) is False
    assert time.monotonic() - started < .5
    assert handle.waits and all(timeout == 0 for timeout in handle.waits)
    assert client._job and client._watchdog.isActive() and not events


def test_watch_can_release_confirmed_exit_when_exit_code_query_fails(elevated_client):
    client, handle, events = elevated_client
    client._result = {"success": True, "count": 0}
    handle.exited = True
    handle.code_error = PermissionError("fixture exit code unavailable")
    client._watch()
    assert handle.closed and not client._job and not client._watchdog.isActive()
    assert events == [("contacts.finished", {
        "success": False, "code": "READER_FAILED", "jobId": "owned-job"})]


def test_qprocess_close_handles_finished_signal_during_bounded_wait(qapp, tmp_path):
    client = ContactReaderClient(command=[sys.executable, "-c", "import time; time.sleep(.2)"],
                                 bootstrap_root=tmp_path, snapshot_root=tmp_path / "snapshots")
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "fixture"}, "qprocess-wait")
    process = client._process
    try:
        assert process.waitForStarted(1000)
        assert client.close(timeout_ms=1000) is True
        assert not client.processRunning and not client._job and client._process is None
        assert not client._watchdog.isActive()
        assert events == [("contacts.finished", {
            "success": False, "code": "CANCELLED", "jobId": "qprocess-wait"})]
    finally:
        if client._process is not None:
            process.kill()
            process.waitForFinished(1000)
        client.close()


def test_qprocess_status_poll_does_not_enter_blocking_wait(elevated_client):
    client, _handle, events = elevated_client

    class PendingProcess(QProcess):
        def state(self):
            return QProcess.Running

        def waitForFinished(self, timeout):
            raise AssertionError("A status poll must not pump process callbacks")

    process = PendingProcess(client)
    client._process, client._elevated_handle = process, None
    try:
        assert client.processRunning
        assert client._job == "owned-job" and not events
    finally:
        client._process = None
        process.deleteLater()


@pytest.mark.skipif(os.name != "nt", reason="Windows process-handle integration")
def test_denied_termination_retains_real_child_handle_until_exit(qapp, tmp_path):
    import win32api
    import win32con
    import win32event

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = ContactReaderClient(bootstrap_root=tmp_path, snapshot_root=tmp_path / "snapshots")
    handle = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_INFORMATION,
                                 False, child.pid)
    client._elevated_handle, client._job = handle, "real-child"
    client._started_at = time.monotonic()
    client._watchdog.start()
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    try:
        started = time.monotonic()
        assert client.close(timeout_ms=0) is False
        assert time.monotonic() - started < .5
        assert child.poll() is None and client.processRunning
        assert client._elevated_handle is handle and client._job == "real-child"
        assert client._watchdog.isActive() and not events
        child.terminate()
        child.wait(timeout=5)
        assert win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_OBJECT_0
        client._watch()
        assert client._elevated_handle is None and not client._job
        assert events == [("contacts.finished", {
            "success": False, "code": "CANCELLED", "jobId": "real-child"})]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        client.close()
