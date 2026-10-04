"""Real RPC/Agent process with isolated Win32 fault injection; no real UIA."""
import os
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer

from app.agent.gate_recovery import GateRecoveryManager
from app.agent.journal import GateLeaseJournal
from app.agent.runtime import AgentRuntime
from app.agent.server import AgentServer
from tests.agent_process_fixture import ProcessEngine
from tests.test_gate_recovery import RestartBackend


class ProcessRecovery(GateRecoveryManager):
    def run(self, stop, emit):
        scenario = os.environ.get("GATE_TEST_SCENARIO", "slow")
        if scenario == "slow":
            emit(dict(self.state))
            stop.wait(0.8)
        elif scenario == "hang":
            time.sleep(60)
        def progress(state):
            emit(state)
            if scenario == "crash" and state["stage"] == "restarting":
                os._exit(71)
        return super().run(stop, progress)


def main():
    app = QCoreApplication([])
    path = Path(os.environ["WECHAT_AGENT_GATE_LEASE"])
    backend = RestartBackend()
    recovery = ProcessRecovery(backend, journal=GateLeaseJournal(path), temp_dir=path.parent)
    runtime = AgentRuntime(engine_factory=ProcessEngine, gate_recovery=recovery,
                           gate_timeout_ms=400 if os.environ.get("GATE_TEST_SCENARIO") == "hang" else 15_000)
    server = AgentServer(os.environ["WECHAT_AGENT_PIPE"], os.environ["WECHAT_AGENT_TOKEN"],
                         runtime, heartbeat_interval_ms=75)
    runtime.shutdownRequested.connect(app.quit)
    assert server.listen()
    QTimer.singleShot(0, runtime.begin_gate_recovery)
    try:
        return app.exec()
    finally:
        server.close()
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
