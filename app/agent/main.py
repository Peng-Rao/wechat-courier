from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication

from .runtime import AgentRuntime
from .server import AgentServer


def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
