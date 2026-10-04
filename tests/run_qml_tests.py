# -*- coding: utf-8 -*-
"""QML 测试启动器

用法:
    python tests/run_qml_tests.py

该脚本使用 Qt 自带的 qmltestrunner 运行 tests/qml/ 下的所有 tst_*.qml 文件。
需要系统中安装 Qt 6.x 并可通过 PATH 或常用路径找到 qmltestrunner。
"""

import os
import subprocess
import sys
import tempfile


QML_TEST_DIR = os.path.join(os.path.dirname(__file__), "qml")


def find_qmltestrunner() -> str | None:
    """在常见位置查找 qmltestrunner 可执行文件，优先 Qt 6。"""
    # 常见 Qt 安装路径（Windows）— 优先 Qt 6
    common_paths = [
        r"D:\Qt\6.5.2\msvc2019_64\bin\qmltestrunner.exe",
        r"D:\Qt\6.7.0\msvc2019_64\bin\qmltestrunner.exe",
        r"D:\Qt\6.8.0\msvc2022_64\bin\qmltestrunner.exe",
        r"C:\Qt\6.5.2\msvc2019_64\bin\qmltestrunner.exe",
        r"C:\Qt\6.7.0\msvc2019_64\bin\qmltestrunner.exe",
        r"C:\Qt\6.8.0\msvc2022_64\bin\qmltestrunner.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p

    # 再尝试 PATH
    for name in ("qmltestrunner", "qmltestrunner.exe"):
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(path_dir, name)
            if os.path.isfile(candidate):
                return candidate

    return None


def main():
    runner = find_qmltestrunner()
    if runner is None:
        print("错误: 找不到 qmltestrunner。请确保 Qt 6.x 已安装并在 PATH 中。", file=sys.stderr)
        sys.exit(1)

    # 使用临时文件收集输出（避免 Windows 控制台编码问题）
    # Windows 下 NamedTemporaryFile 必须关闭后其他进程才能写入
    fd, output_file = tempfile.mkstemp(suffix=".txt")
    os.close(fd)

    try:
        cmd = [runner, "-input", QML_TEST_DIR, "-o", f"{output_file},txt"]
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
