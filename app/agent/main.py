from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication

from .gate import (
    NativeGateBackend,
    restore_gate_lease,
    restore_legacy_gate_leases,
)
from .instance_lock import (
    AGENT_ALREADY_RUNNING_EXIT_CODE,
    AgentAlreadyRunningError,
    AgentInstanceLock,
)
from .runtime import AgentRuntime
from .server import AgentServer


def _run_locked() -> int:
    gate_backend = NativeGateBackend()
    try:
        other_agents = gate_backend.legacy_agent_pids()
    except Exception as exc:
        print(
            "wechat-agent gate recovery failed: "
            f"cannot verify existing Agent processes: {exc}",
            file=sys.stderr,
        )
        return 4
    if other_agents:
        raise AgentAlreadyRunningError(
            "wechat-agent is already running in this Windows session"
        )
    try:
        recovery = restore_gate_lease(gate_backend)
        restore_legacy_gate_leases(
            gate_backend,
            other_agent_pids=gate_backend.legacy_agent_pids,
        )
    except Exception as exc:
        print(f"wechat-agent gate recovery failed: {exc}", file=sys.stderr)
        return 4
    if "--recover-gate" in sys.argv:
        if recovery.get("restored"):
            print(recovery.get("reason", "restored"))
        return 0

    pipe_name = os.environ.get("WECHAT_AGENT_PIPE", "")
    token = os.environ.get("WECHAT_AGENT_TOKEN", "")
    if not pipe_name or not token:
        print("WECHAT_AGENT_PIPE and WECHAT_AGENT_TOKEN are required", file=sys.stderr)
        return 2

    application = QCoreApplication(sys.argv)
    runtime = AgentRuntime()
    server = AgentServer(pipe_name, token, runtime)
    runtime.shutdownRequested.connect(server.close)
    runtime.shutdownRequested.connect(application.quit)
    if not server.listen():
        print(server._server.errorString(), file=sys.stderr)
        runtime.close()
        return 3
    try:
        return application.exec()
    finally:
        server.close()
        runtime.close()


def main() -> int:
    try:
        with AgentInstanceLock():
            return _run_locked()
    except AgentAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return AGENT_ALREADY_RUNNING_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
