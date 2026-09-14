from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

from .retry import AutomationRetryError


class ActionDeadlineExceeded(AutomationRetryError):
    code = "ACTION_DEADLINE_EXCEEDED"


_deadline: ContextVar[float | None] = ContextVar("uia_action_deadline", default=None)


def check_action_deadline() -> None:
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise ActionDeadlineExceeded("自动化步骤超过 15 秒，已停止操作")


@contextmanager
def action_deadline(seconds: float = 15.0):
    parent = _deadline.get()
    end = time.monotonic() + seconds
    token = _deadline.set(min(parent, end) if parent is not None else end)
    try:
        check_action_deadline()
        yield
        check_action_deadline()
    finally:
        _deadline.reset(token)


class DeadlineWaiter:
    """Event-assisted wait with a bounded polling fallback."""

    def __init__(self, poll_interval: float = 0.25):
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
            check_action_deadline()
            if predicate():
                check_action_deadline()
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            delay = min(self.poll_interval, remaining)
            action_end = _deadline.get()
            if action_end is not None:
                delay = max(0, min(delay, action_end - time.monotonic()))
            if wake_event is None:
                time.sleep(delay)
            else:
                wake_event.wait(delay)
                wake_event.clear()


__all__ = ["DeadlineWaiter"]
