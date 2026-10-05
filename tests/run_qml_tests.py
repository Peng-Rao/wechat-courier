# -*- coding: utf-8 -*-
"""QML 测试启动器

用法:
    python tests/run_qml_tests.py

使用应用自带的 PySide6 QtQuickTest 运行 tests/qml/ 下的全部测试。
"""

import os
import subprocess
import sys
import tempfile


QML_TEST_DIR = os.path.join(os.path.dirname(__file__), "qml")


def main():
    if "--pyside-runner" in sys.argv:
        from PySide6.QtQuickTest import QUICK_TEST_MAIN
        sys.exit(QUICK_TEST_MAIN("FugeQuickTest", [sys.argv[0], *sys.argv[2:]]))

    # 使用临时文件收集输出（避免 Windows 控制台编码问题）
    # Windows 下 NamedTemporaryFile 必须关闭后其他进程才能写入
    fd, output_file = tempfile.mkstemp(suffix=".txt")
    os.close(fd)

    try:
        # Use the application's Qt runtime, rather than an unrelated system Qt.
        from PySide6 import QtQuickTest
        cmd = [sys.executable, __file__, "--pyside-runner", "-input", QML_TEST_DIR,
               "-o", f"{output_file},txt"]
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=environment)

        # 同时打印 qmltestrunner 的 stderr（可能包含诊断信息）
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if os.path.exists(output_file):
            with open(output_file, "rb") as f:
                data = f.read()
                # Qt 输出通常是本地编码，尝试多种解码
                for encoding in ("utf-8", "gbk", "latin-1"):
                    try:
                        print(data.decode(encoding))
                        break
                    except UnicodeDecodeError:
                        continue

        sys.exit(result.returncode)
    finally:
        if os.path.exists(output_file):
            os.remove(output_file)


if __name__ == "__main__":
    main()
