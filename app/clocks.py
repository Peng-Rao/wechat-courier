from __future__ import annotations

import time
from typing import Callable


class ElapsedClock:
    """A monotonic stopwatch that excludes explicit pauses."""

    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock or time.monotonic
        self._elapsed = 0.0
        self._started: float | None = None

    def reset(self) -> None:
        self._elapsed = 0.0
        self._started = None

    def resume(self) -> None:
        if self._started is None:
            self._started = self._clock()

    def pause(self) -> None:
        if self._started is not None:
            self._elapsed += max(0.0, self._clock() - self._started)
            self._started = None

    @property
    def seconds(self) -> float:
        running = max(0.0, self._clock() - self._started) if self._started is not None else 0.0
        return self._elapsed + running
