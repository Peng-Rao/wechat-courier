"""Real RPC/runtime/workflow in a child process, with no native desktop driver."""
import os
import time

from PySide6.QtCore import QCoreApplication

from app.agent.runtime import AgentRuntime
from app.agent.server import AgentServer
from app.agent.workflows import WeixinWorkflowEngine
from tests.test_task_stop_recovery import RecoveryDriver


class ProcessDriver(RecoveryDriver):
    def __init__(self):
        super().__init__()
        self.tasks = 0

    def begin_task(self, kind):
        super().begin_task(kind)
        self.tasks += 1
        self.search_available = self.tasks != 1

    def inspect(self):
        time.sleep(0.1)
        return super().inspect()

    def bind_window(self):
        return {**super().bind_window(), "processDetected": True, "versionSupported": True,
                "sessionReady": True, "uiaReady": True, "restorable": False,
                "reasonCode": "", "degradedReason": "", "taskWindowReady": True,
                "taskWindowRole": "main", "taskWindowHwnd": self.window["hwnd"]}

    def health_window_snapshot(self):
        if os.environ.get("STOP_RECOVERY_FIXTURE_BLOCK_HEALTH") == "1":
            time.sleep(60)
        return self.diagnostic_snapshot()


def main():
    app = QCoreApplication([])
    runtime = AgentRuntime(
        engine_factory=lambda: WeixinWorkflowEngine(driver_factory=ProcessDriver),
        action_timeout_ms=2_000 if os.environ.get("STOP_RECOVERY_FIXTURE_BLOCK_HEALTH") == "1" else 15_000,
    )
    server = AgentServer(os.environ["WECHAT_AGENT_PIPE"], os.environ["WECHAT_AGENT_TOKEN"], runtime)
    runtime.shutdownRequested.connect(app.quit)
    assert server.listen()
    try:
        return app.exec()
    finally:
        server.close()
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
