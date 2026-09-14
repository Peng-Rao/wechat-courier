"""Fault-injection process fixture; never imports a native WeChat driver."""
import os
import time

from PySide6.QtCore import QCoreApplication

from app.agent.runtime import AgentRuntime
from app.agent.server import AgentServer


class ProcessEngine:
    def __init__(self):
        self.generation = 1
        self.sequence = 0

    def inspect(self):
        self.sequence += 1
        return {"sequence": self.sequence, "agentInstanceId": str(os.getpid()),
                "sessionGeneration": self.generation, "sessionReady": True,
                "windowEnabled": True, "windowResponsive": True,
                "versionSupported": True, "processDetected": True}

    def run(self, request, control, emit):
        mode = request.items[0].target
        if mode == "crash":
            os._exit(71)
        emit("agent.status", {"status": "uia_action_started", "actionId": "blocking"})
        if mode == "hang":
            time.sleep(60)
        emit("agent.status", {"status": "uia_action_completed", "actionId": "blocking"})
        item = request.items[0]
        emit("task.event", {"taskId": request.task_id, "itemId": item.item_id,
                            "step": "send_verified", "outcome": "success"})
        if not control.wait_for_result_ack(item.item_id, 2):
            return {"outcome": "unknown", "done": 1, "total": 1}
        health = self.inspect()
        emit("agent.status", {"status": "health", "health": health})
        return {"outcome": "success", "done": 1, "total": 1,
                "cleanup": {"success": True}, "health": health}

    def close(self):
        pass


def main():
    app = QCoreApplication([])
    runtime = AgentRuntime(engine_factory=ProcessEngine, action_timeout_ms=1000)
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
