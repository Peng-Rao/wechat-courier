"""Small process boundary used to exercise the real Windows named mutex."""

from __future__ import annotations

import os
import sys
import time

from app.agent.instance_lock import AgentAlreadyRunningError, AgentInstanceLock


def main() -> int:
    try:
        with AgentInstanceLock(
            name=os.environ["WECHAT_AGENT_TEST_LOCK"],
            wait_timeout_ms=int(os.environ.get("WECHAT_AGENT_TEST_WAIT_MS", "500")),
        ):
            print("acquired", flush=True)
            time.sleep(float(os.environ.get("WECHAT_AGENT_TEST_HOLD_SECONDS", "0")))
            return 0
    except AgentAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
