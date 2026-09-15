from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.agent.instance_lock import (
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    AgentAlreadyRunningError,
    AgentInstanceLock,
)


class FakeMutexBackend:
    def __init__(self, wait_result):
        self.wait_result = wait_result
        self.calls = []

    def create_mutex(self, name):
        self.calls.append(("create", name))
        return 123

    def wait(self, handle, timeout_ms):
        self.calls.append(("wait", handle, timeout_ms))
        return self.wait_result

    def release(self, handle):
        self.calls.append(("release", handle))

    def close(self, handle):
        self.calls.append(("close", handle))


def test_agent_lock_waits_five_seconds_then_reports_the_existing_owner():
    backend = FakeMutexBackend(WAIT_TIMEOUT)
    lock = AgentInstanceLock(
        name=r"Local\WxAuto-test",
        wait_timeout_ms=5_000,
        backend=backend,
    )

    with pytest.raises(AgentAlreadyRunningError, match="already running"):
        lock.acquire()

    assert backend.calls == [
        ("create", r"Local\WxAuto-test"),
        ("wait", 123, 5_000),
        ("close", 123),
    ]


def test_agent_lock_releases_the_owned_mutex_exactly_once():
    backend = FakeMutexBackend(WAIT_OBJECT_0)
    lock = AgentInstanceLock(backend=backend)

    lock.acquire()
    lock.close()
    lock.close()

    assert [call[0] for call in backend.calls] == [
        "create",
        "wait",
        "release",
        "close",
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex contract")
def test_real_second_agent_is_blocked_until_the_first_releases_its_lock(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment.update(
        WECHAT_AGENT_TEST_LOCK=r"Local\WxAuto-test-" + uuid.uuid4().hex,
        WECHAT_AGENT_TEST_WAIT_MS="150",
        WECHAT_AGENT_TEST_HOLD_SECONDS="0.8",
    )
    first = subprocess.Popen(
        [sys.executable, "-m", "tests.agent_lock_fixture"],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "acquired"
        second = subprocess.run(
            [sys.executable, "-m", "tests.agent_lock_fixture"],
            cwd=root,
            env={
                **environment,
                "WECHAT_AGENT_TEST_HOLD_SECONDS": "0",
            },
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        assert second.returncode == 5
        assert "already running" in second.stderr
        assert first.wait(timeout=3) == 0

        takeover = subprocess.run(
            [sys.executable, "-m", "tests.agent_lock_fixture"],
            cwd=root,
            env={
                **environment,
                "WECHAT_AGENT_TEST_HOLD_SECONDS": "0",
            },
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        assert takeover.returncode == 0
        assert takeover.stdout.strip() == "acquired"
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=3)


def test_agent_main_takes_the_lock_before_recovering_a_gate(monkeypatch):
    from app.agent import main as agent_main

    events = []

    class RecordingLock:
        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_args):
            events.append("unlock")

    class RecordingGateBackend:
        @staticmethod
        def legacy_agent_pids():
            events.append("detect")
            return ()

    monkeypatch.setattr(agent_main, "AgentInstanceLock", RecordingLock)
    monkeypatch.setattr(
        agent_main, "NativeGateBackend", RecordingGateBackend
    )
    monkeypatch.setattr(
        agent_main,
        "restore_gate_lease",
        lambda *_args: events.append("restore") or {"restored": False},
    )
    monkeypatch.setattr(
        agent_main,
        "restore_legacy_gate_leases",
        lambda *_args, **_kwargs: events.append("legacy") or [],
    )
    monkeypatch.setattr(sys, "argv", ["wechat-agent", "--recover-gate"])

    assert agent_main.main() == 0
    assert events == ["lock", "detect", "restore", "legacy", "unlock"]


def test_agent_main_fails_closed_when_existing_agent_detection_is_unavailable(
    monkeypatch, capsys
):
    from app.agent import main as agent_main

    events = []

    class RecordingLock:
        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_args):
            events.append("unlock")

    class FailingGateBackend:
        @staticmethod
        def legacy_agent_pids():
            events.append("detect")
            raise RuntimeError("process enumeration denied")

    monkeypatch.setattr(agent_main, "AgentInstanceLock", RecordingLock)
    monkeypatch.setattr(agent_main, "NativeGateBackend", FailingGateBackend)
    monkeypatch.setattr(
        agent_main,
        "restore_gate_lease",
        lambda *_args: events.append("restore") or {"restored": False},
    )
    monkeypatch.setattr(sys, "argv", ["wechat-agent", "--recover-gate"])

    assert agent_main.main() == 4
    assert events == ["lock", "detect", "unlock"]
    assert "cannot verify existing Agent processes" in capsys.readouterr().err
