from __future__ import annotations

from app.agent.runtime import _UnavailableEngine
from tests.manual_v031_stability_probe import _run_soak


class _Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class _HealthyEngine:
    def __init__(self, generations=(7,)):
        self.calls = 0
        self.generations = tuple(generations)

    def inspect(self):
        generation = self.generations[min(self.calls, len(self.generations) - 1)]
        self.calls += 1
        return {
            "processDetected": True,
            "versionSupported": True,
            "sessionReady": True,
            "windowResponsive": True,
            "sessionGeneration": generation,
        }


def test_unavailable_engine_exposes_complete_health_contract():
    result = _UnavailableEngine().inspect()

    assert result["processDetected"] is False
    assert result["versionSupported"] is False
    assert result["sessionReady"] is False
    assert result["windowResponsive"] is False
    assert result["sessionGeneration"] == 0
    assert result["degradedReason"] == "UIA_NOT_INITIALIZED"


def test_read_only_soak_keeps_one_session_generation():
    clock = _Clock()
    engine = _HealthyEngine()

    result = _run_soak(
        engine,
        duration_seconds=30,
        interval_seconds=10,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == {
        "ok": True,
        "checks": 3,
        "elapsedSeconds": 30.0,
        "sessionGeneration": 7,
        "failures": [],
    }


def test_read_only_soak_fails_when_session_generation_changes():
    clock = _Clock()
    engine = _HealthyEngine(generations=(7, 8))

    result = _run_soak(
        engine,
        duration_seconds=20,
        interval_seconds=10,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["ok"] is False
    assert result["checks"] == 2
    assert result["failures"][0]["sessionGeneration"] == 8
