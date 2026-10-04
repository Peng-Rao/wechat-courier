from __future__ import annotations

import os
import sys
import json
import threading

from PySide6.QtCore import QCoreApplication, QSettings, QTimer

from .gate import NativeGateBackend
from .gate_recovery import GateRecoveryManager
from .instance_lock import (
    AGENT_ALREADY_RUNNING_EXIT_CODE,
    AgentAlreadyRunningError,
    AgentInstanceLock,
)
from .runtime import AgentRuntime
from .server import AgentServer


def _run_locked() -> int:
    gate_backend = NativeGateBackend()
    if "--recover-gate" in sys.argv:
        recovery = GateRecoveryManager(gate_backend, allow_restart=False).run(threading.Event(), lambda state: None)
        print(json.dumps(recovery, ensure_ascii=True))
        if recovery.get("stage") == "completed":
            return 0
        print(f"wechat-agent gate recovery failed: {recovery.get('detail', '')}", file=sys.stderr)
        return AGENT_ALREADY_RUNNING_EXIT_CODE if recovery.get("reasonCode") == "AGENT_ALREADY_RUNNING" else 4

    pipe_name = os.environ.get("WECHAT_AGENT_PIPE", "")
    token = os.environ.get("WECHAT_AGENT_TOKEN", "")
    if not pipe_name or not token:
        print("WECHAT_AGENT_PIPE and WECHAT_AGENT_TOKEN are required", file=sys.stderr)
        return 2

    application = QCoreApplication(sys.argv)
    try:
        login_timeout = max(30, min(300, int(QSettings("wx4py", "WeChatCourier").value("recovery/loginTimeout", 90))))
    except (TypeError, ValueError, OverflowError):
        login_timeout = 90
    runtime = AgentRuntime(gate_recovery=GateRecoveryManager(gate_backend, login_timeout=login_timeout))
    server = AgentServer(pipe_name, token, runtime)
    runtime.shutdownRequested.connect(server.close)
    runtime.shutdownRequested.connect(application.quit)
    if not server.listen():
        print(server._server.errorString(), file=sys.stderr)
        runtime.close()
        return 3
    QTimer.singleShot(0, runtime.begin_gate_recovery)
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
