"""Closed, non-sensitive contact-read statistics for IPC and diagnostics."""

from dataclasses import dataclass, field
import time


STAGES = frozenset({"starting", "process", "snapshot", "keys", "validating", "contacts", "complete"})
STRATEGIES = frozenset({"literal", "wcdb", "mixed"})
COUNTERS = ("processCount", "processesChecked", "memoryReads", "memoryBytes", "anchorCount",
            "structureCount", "candidateCount", "validatedCount", "elapsedMs")


def safe_diagnostics(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, allowed in (("stage", STAGES), ("strategy", STRATEGIES)):
        text = value.get(name)
        if isinstance(text, str) and text in allowed:
            result[name] = text
    for name in COUNTERS:
        count = value.get(name)
        if type(count) is int and 0 <= count <= 2 ** 63 - 1:
            result[name] = count
    return result


@dataclass
class ReadDiagnostics:
    stage: str = "starting"
    strategy: str = ""
    processCount: int = 0
    processesChecked: int = 0
    memoryReads: int = 0
    memoryBytes: int = 0
    anchorCount: int = 0
    structureCount: int = 0
    candidateCount: int = 0
    validatedCount: int = 0
    _started: float = field(default_factory=time.monotonic, repr=False)

    def snapshot(self):
        value = {name: getattr(self, name) for name in COUNTERS if name != "elapsedMs"}
        value.update(stage=self.stage, strategy=self.strategy,
                     elapsedMs=max(0, int((time.monotonic() - self._started) * 1000)))
        return safe_diagnostics(value)
