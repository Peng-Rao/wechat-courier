# -*- coding: utf-8 -*-
"""QML 测试封装 — 通过 pytest 统一运行 QML TestCase"""

import os
import subprocess
import sys

import pytest


QML_RUNNER = os.path.join(os.path.dirname(__file__), "run_qml_tests.py")


@pytest.mark.qml
@pytest.mark.slow
def test_qml_suite():
    """运行 tests/qml/ 下的所有 QML TestCase。

    使用应用自带的 PySide6 QtQuickTest，避免系统 Qt 版本不一致。
    """
    result = subprocess.run(
        [sys.executable, QML_RUNNER],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # 将 qmltestrunner 的输出打印出来，便于调试
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        pytest.fail(f"QML 测试失败 (exit code {result.returncode})")
