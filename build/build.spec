# -*- coding: utf-8 -*-
"""PyInstaller spec — PySide6 + QML 桌面版"""
import os
import sys

ROOT = os.path.dirname(SPECPATH)  # WxAuto/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from build.pyinstaller_filters import filter_qt_artifacts
from app.build_info import MANIFEST_FILENAME, write_build_manifest
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

block_cipher = None

# One immutable source identity for all executables; no user log files included.
manifest_path = write_build_manifest(os.path.join(workpath, MANIFEST_FILENAME), ROOT)
build_datas = [(str(manifest_path), ".")]
licenses_dir = os.path.join(ROOT, "licenses")
license_datas = [(licenses_dir, "licenses")] if os.path.isdir(licenses_dir) else []

# ═══════════════════════════════════════
#  comtypes 预生成目录
# ═══════════════════════════════════════
comtypes_datas = []
comtypes_gen_dir = os.path.join(ROOT, "comtypes_gen")
if os.path.isdir(comtypes_gen_dir):
    comtypes_datas.append((comtypes_gen_dir, "comtypes/gen"))

# ═══════════════════════════════════════
#  src 包 — 通过 collect_submodules 自动收集为可导入模块
#  不再作为 datas 复制，避免与 frozen archive 中的编译模块冲突
# ═══════════════════════════════════════

# ═══════════════════════════════════════
#  QML 文件与图标资源
# ═══════════════════════════════════════
datas = list(comtypes_datas) + build_datas + license_datas
qml_dir = os.path.join(ROOT, "qml")
for dirpath, dirnames, filenames in os.walk(qml_dir):
    for f in filenames:
        if f == "qmldir" or f.endswith((".qml", ".svg")):
            src_path = os.path.join(dirpath, f)
            rel = os.path.relpath(dirpath, ROOT)
            datas.append((src_path, rel))

# ═══════════════════════════════════════
#  图标
# ═══════════════════════════════════════
icon_path = os.path.join(ROOT, "assets", "app.ico")
if os.path.exists(icon_path):
    datas.append((icon_path, "assets"))
for logo_filename in ("fuge-logo.png", "fuge-logo-256.png", "fuge-logo-64.png"):
    datas.append((os.path.join(ROOT, "assets", logo_filename), "assets"))

# ═══════════════════════════════════════
#  pywin32 DLL
# ═══════════════════════════════════════
binaries = []
pywin32_dll_names = [
    f"pywintypes{sys.version_info.major}{sys.version_info.minor}.dll",
    f"pythoncom{sys.version_info.major}{sys.version_info.minor}.dll",
]
try:
    import PyInstaller.utils.hooks as hooks
    pywin32_dll_dir = hooks.get_pywin32_dll_dir()
    if pywin32_dll_dir:
        for dll in pywin32_dll_names:
            dll_path = os.path.join(pywin32_dll_dir, dll)
            if os.path.exists(dll_path):
                binaries.append((dll_path, "."))
except Exception:
    pass

if not binaries:
    try:
        import pywintypes
        dll_dir = os.path.dirname(pywintypes.__file__)
        for dll in pywin32_dll_names:
            dll_path = os.path.join(dll_dir, dll)
            if os.path.exists(dll_path):
                binaries.append((dll_path, "."))
    except Exception:
        pass

hiddenimports = [
    "app.build_info",
    # PySide6 shared by the GUI and local Named Pipe agent
    "PySide6.QtCore", "PySide6.QtGui",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickControls2",
    "PySide6.QtNetwork",
    # pywin32
    "win32gui", "win32con", "win32api", "win32process", "win32clipboard",
    "win32file", "win32event", "win32security", "winerror",
    "pythoncom", "pywintypes", "win32com", "win32com.client",
    # Native pywin32 time conversions import this dynamically.
    "win32timezone",
    # comtypes and generated interfaces
    "comtypes", "comtypes.client", "comtypes.gen", "comtypes.server",
    # Compatibility library and spreadsheet import stack
    *collect_submodules("src"),
    *collect_submodules("openpyxl"),
    "et_xmlfile",
    # Existing optional content helpers
    "PIL", "PIL.Image", "PIL.ImageGrab", "markdown", "pyperclip",
]

# Qt's dynamic OpenGL loader resolves these at runtime, outside import analysis.
import PySide6
gui_binaries = list(binaries)
for dll in ("opengl32sw.dll", "Qt6OpenGL.dll"):
    dll_path = os.path.join(os.path.dirname(PySide6.__file__), dll)
    if not os.path.isfile(dll_path):
        raise RuntimeError(f"Required Qt OpenGL runtime not found: {dll}")
    gui_binaries.append((dll_path, "PySide6"))

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=gui_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, "build", "_comtypes_hook.py")],
    excludes=["tkinter", "streamlit"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = filter_qt_artifacts(a.binaries)
a.datas = filter_qt_artifacts(a.datas)

agent_analysis = Analysis(
    [os.path.join(ROOT, "agent_main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=list(comtypes_datas) + build_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, "build", "_comtypes_hook.py")],
    excludes=["tkinter", "streamlit"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

agent_analysis.binaries = filter_qt_artifacts(agent_analysis.binaries)
agent_analysis.datas = filter_qt_artifacts(agent_analysis.datas)

# Contact reading never imports the automation runtime or its COM/UIA hooks.
contact_analysis = Analysis(
    [os.path.join(ROOT, "contact_reader_main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=build_datas + license_datas + copy_metadata("sqlcipher3"),
    hiddenimports=["PySide6.QtCore", "PySide6.QtNetwork", "win32api", "win32con",
                   "win32security", "win32file", "win32process", "pywintypes",
                   "win32timezone",
                   "sqlcipher3", "sqlcipher3.dbapi2", "sqlcipher3._sqlite3"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "streamlit", "app.agent.native_driver", "app.agent.gate",
              "app.agent.runtime", "pythoncom", "comtypes"],
    noarchive=False,
)
contact_analysis.binaries = filter_qt_artifacts(contact_analysis.binaries)
contact_analysis.datas = filter_qt_artifacts(contact_analysis.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
agent_pyz = PYZ(
    agent_analysis.pure,
    agent_analysis.zipped_data,
    cipher=block_cipher,
)
contact_pyz = PYZ(contact_analysis.pure, contact_analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="福格微信助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_path if os.path.exists(icon_path) else None,
    version=os.path.join(ROOT, "build", "version_info.txt"),
)

agent_exe = EXE(
    agent_pyz,
    agent_analysis.scripts,
    [],
    exclude_binaries=True,
    name="wechat-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=os.path.join(ROOT, "build", "version_info.txt"),
)

contact_exe = EXE(
    contact_pyz, contact_analysis.scripts, [], exclude_binaries=True,
    name="wechat-contact-reader", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    version=os.path.join(ROOT, "build", "version_info.txt"),
)

coll = COLLECT(
    exe,
    agent_exe,
    contact_exe,
    a.binaries,
    agent_analysis.binaries,
    contact_analysis.binaries,
    a.zipfiles,
    agent_analysis.zipfiles,
    contact_analysis.zipfiles,
    a.datas,
    agent_analysis.datas,
    contact_analysis.datas,
    strip=False,
    upx=True,
    name="福格微信助手",
)
