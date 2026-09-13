from __future__ import annotations

import time
from typing import Callable


class DeadlineWaiter:
    """Event-assisted wait with a bounded polling fallback."""

    def __init__(self, poll_interval: float = 0.2):
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.poll_interval = poll_interval

    def wait(
        self,
        predicate: Callable[[], bool],
        timeout: float,
        wake_event=None,
    ) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if predicate():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            delay = min(self.poll_interval, remaining)
            if wake_event is None:
                time.sleep(delay)
            else:
                wake_event.wait(delay)
                wake_event.clear()


__all__ = ["DeadlineWaiter"]
