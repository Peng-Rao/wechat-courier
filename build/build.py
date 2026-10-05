# -*- coding: utf-8 -*-
"""一键构建脚本 — PyInstaller 打包 + NSIS 安装器"""
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREGEN_COMTYPES = ROOT / "build" / "pregen_comtypes.py"
BUILD_SPEC = ROOT / "build" / "build.spec"
NSIS_SCRIPT = ROOT / "installer" / "setup.nsi"


def _ensure_pyinstaller_available():
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "未安装 PyInstaller。请先运行：pip install -r requirements-dev.txt"
        )


def _refresh_windows_shell_icons():
    if sys.platform != "win32":
        return
    import ctypes

    try:
        notify = ctypes.windll.shell32.SHChangeNotify
        notify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        notify.restype = None
        # Invalidate cached EXE icons without deleting caches or restarting Explorer.
        notify(0x08000000, 0, None, None)
    except OSError as exc:
        print(f"Unable to refresh Windows shell icons: {exc}")


def main():
    # 1. 预生成 comtypes 包装（可选）
    print("步骤 1/3: 检查 comtypes 包装...")
    if PREGEN_COMTYPES.exists():
        subprocess.run(
            [sys.executable, str(PREGEN_COMTYPES)],
            cwd=ROOT,
            check=True,
        )
    else:
        print("未找到 build/pregen_comtypes.py，跳过预生成；运行时 hook 将使用临时目录生成。")

    # 2. PyInstaller 打包
    print("步骤 2/3: PyInstaller 打包...")
    _ensure_pyinstaller_available()
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        str(BUILD_SPEC),
    ], cwd=ROOT, check=True)

    subprocess.run([
        sys.executable, str(ROOT / "build" / "verify_package.py"),
        str(ROOT / "dist" / "福格微信助手"),
    ], cwd=ROOT, check=True)

    # 3. NSIS 安装器（可选）
    print("步骤 3/3: 构建 NSIS 安装器...")
    import os
    nsis_exe = os.environ.get("NSIS_EXE", "makensis")
    if NSIS_SCRIPT.exists():
        try:
            icon_hash = hashlib.sha256((ROOT / "assets" / "app.ico").read_bytes()).hexdigest()[:16]
            subprocess.run([
                nsis_exe,
                f"/DPRODUCT_ICON_NAME=fuge-icon-{icon_hash}.ico",
                str(NSIS_SCRIPT),
            ], cwd=ROOT, check=True)
            print(f"\n安装器已生成：{ROOT / 'dist' / '福格微信助手_Setup.exe'}")
        except FileNotFoundError:
            print("未找到 NSIS (makensis)，跳过安装器构建。")
            print("如需构建安装器，请安装 NSIS 并将 makensis 加入 PATH。")
    else:
        print("未找到 setup.nsi，跳过安装器构建。")

    _refresh_windows_shell_icons()
    print("\n构建完成！")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)
