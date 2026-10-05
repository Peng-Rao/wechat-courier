"""Run the migrated workspaces against inert QML controllers, never WeChat."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.qml
@pytest.mark.parametrize("case", ["ContactWorkspace", "TaskMonitorTimeline"])
def test_fuge_monitor_contacts_qml(case):
    pytest.importorskip("PySide6.QtQuickTest")
    with tempfile.TemporaryDirectory(prefix="fuge-qml-") as directory:
        output = Path(directory) / "results.txt"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "run_qml_tests.py"), "--pyside-runner",
             "-input", str(ROOT / "tests" / "qml" / f"tst_{case}.qml"),
             "-o", f"{output},txt"],
            cwd=ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        report = output.read_text(encoding="utf-8", errors="replace") if output.exists() else ""
    assert result.returncode == 0, report + result.stdout + result.stderr
