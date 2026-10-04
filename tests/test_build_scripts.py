# -*- coding: utf-8 -*-
"""Build script regression tests."""

import dis
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_build_module():
    spec = importlib.util.spec_from_file_location("wxauto_build", ROOT / "build" / "build.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_build_filters_module():
    spec = importlib.util.spec_from_file_location(
        "wxauto_pyinstaller_filters",
        ROOT / "build" / "pyinstaller_filters.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_script_does_not_call_missing_parent_comtypes_pregen(monkeypatch):
    build = load_build_module()
    calls = []

    def fake_run(cmd, cwd=None, check=False):
        calls.append((list(cmd), Path(cwd) if cwd else None, check))

    monkeypatch.setattr(build, "_ensure_pyinstaller_available", lambda: None)
    monkeypatch.setattr(build.subprocess, "run", fake_run)

    build.main()

    assert calls
    pyinstaller_calls = [
        call for call in calls
        if call[0][:3] == [build.sys.executable, "-m", "PyInstaller"]
    ]
    assert pyinstaller_calls
    pyinstaller_cmd, pyinstaller_cwd, _ = pyinstaller_calls[0]
    assert pyinstaller_cwd == ROOT
    assert str(ROOT / "build" / "build.spec") in pyinstaller_cmd
    assert not any(part.startswith("--name=") for part in pyinstaller_cmd)
    assert "--windowed" not in pyinstaller_cmd
    assert not any(str(ROOT.parent / "pregen_comtypes.py") in part for cmd, _, _ in calls for part in cmd)


def test_build_spec_uses_repository_root_for_sources_and_hooks():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert "os.path.dirname(os.path.dirname(SPECPATH))" not in spec_text
    assert "ROOT = os.path.dirname(SPECPATH)" in spec_text
    assert "PROJECT_ROOT = os.path.dirname(ROOT)" not in spec_text
    assert 'collect_submodules("src")' in spec_text
    assert "os.path.join(ROOT, \"src\")" not in spec_text
    assert "pathex=[ROOT]" in spec_text
    assert 'os.path.join(ROOT, "build", "_comtypes_hook.py")' in spec_text


def test_build_spec_bootstraps_repository_imports_for_console_entrypoint():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    root_assignment = spec_text.index("ROOT = os.path.dirname(SPECPATH)")
    path_bootstrap = spec_text.index("sys.path.insert(0, ROOT)")
    local_import = spec_text.index(
        "from build.pyinstaller_filters import filter_qt_artifacts"
    )
    assert root_assignment < path_bootstrap < local_import


def test_build_spec_does_not_hardcode_python_312_pywin32_dlls():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert "pywintypes312.dll" not in spec_text
    assert "pythoncom312.dll" not in spec_text
    assert "sys.version_info" in spec_text


def test_build_spec_includes_qml_svg_assets():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert '".svg"' in spec_text


def test_installer_shortcuts_use_embedded_exe_icon():
    script = (ROOT / "installer" / "setup.nsi").read_text(encoding="utf-8-sig")

    assert '"$INSTDIR\\assets\\app.ico"' not in script
    assert (
        'CreateShortCut "$DESKTOP\\${PRODUCT_NAME}.lnk" '
        '"$INSTDIR\\${PRODUCT_NAME}.exe" "" "$INSTDIR\\${PRODUCT_NAME}.exe"'
    ) in script
    assert (
        'CreateShortCut "$SMPROGRAMS\\${PRODUCT_NAME}\\${PRODUCT_NAME}.lnk" '
        '"$INSTDIR\\${PRODUCT_NAME}.exe" "" "$INSTDIR\\${PRODUCT_NAME}.exe"'
    ) in script
    assert (
        'WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" '
        '"$INSTDIR\\${PRODUCT_NAME}.exe"'
    ) in script


def test_windows_ci_uses_python_312_and_validates_every_release_artifact():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert 'PYTHON_VERSION: "3.12"' in workflow
    assert 'PRODUCT_NAME: "福格微信助手"' in workflow
    for artifact in (
        '"dist/$($env:PRODUCT_NAME)/$($env:PRODUCT_NAME).exe"',
        '"dist/$($env:PRODUCT_NAME)/wechat-agent.exe"',
        '"dist/$($env:PRODUCT_NAME)_$version.zip"',
        '"dist/$($env:PRODUCT_NAME)_Setup.exe"',
    ):
        assert artifact in workflow
    assert workflow.count("Test-Path -LiteralPath $artifact -PathType Leaf") == 2
    assert workflow.count('throw "Missing build artifact: $artifact"') == 2


def test_build_spec_includes_qml_singleton_metadata():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert (ROOT / "qml" / "theme" / "qmldir").exists()
    assert '"qmldir"' in spec_text


def test_build_spec_does_not_force_bs4_hidden_import():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")
    markdown_utils = (ROOT / "src" / "utils" / "markdown_utils.py").read_text(encoding="utf-8")

    assert '"bs4"' not in spec_text
    assert "from bs4" not in markdown_utils
    assert "BeautifulSoup" not in markdown_utils


def test_build_spec_does_not_force_missing_hidden_imports():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert "PySide6.QtQuickTemplates2" not in spec_text
    assert "comtypes.server.local" not in spec_text


def test_build_spec_uses_qt_artifact_pruning():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert "filter_qt_artifacts" in spec_text
    assert "a.binaries = filter_qt_artifacts(a.binaries)" in spec_text
    assert "a.datas = filter_qt_artifacts(a.datas)" in spec_text


def test_build_outputs_gui_and_isolated_agent_in_one_directory():
    spec_text = (ROOT / "build" / "build.spec").read_text(encoding="utf-8")

    assert 'os.path.join(ROOT, "agent_main.py")' in spec_text
    assert 'name="福格微信助手"' in spec_text
    assert 'name="wechat-agent"' in spec_text
    assert "agent_exe" in spec_text
    assert "agent_analysis.binaries" in spec_text
    assert '*collect_submodules("openpyxl")' in spec_text


def test_build_spec_packages_one_generated_manifest_for_gui_and_agent(tmp_path, monkeypatch):
    analyses = []

    def analysis(scripts, **kwargs):
        result = SimpleNamespace(
            scripts=scripts, binaries=kwargs["binaries"], datas=kwargs["datas"],
            pure=[], zipped_data=[], zipfiles=[],
        )
        analyses.append(result)
        return result

    # Execute the real spec, replacing only PyInstaller and native DLL discovery.
    package = ModuleType("PyInstaller")
    utils = ModuleType("PyInstaller.utils")
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: []
    hooks.get_pywin32_dll_dir = lambda: None
    package.utils = utils
    utils.hooks = hooks
    for module in (package, utils, hooks):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(__file__=str(tmp_path / "stub.py")))
    runpy.run_path(str(ROOT / "build" / "build.spec"), init_globals={
        "SPECPATH": str(ROOT / "build"), "workpath": str(tmp_path),
        "Analysis": analysis, "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None, "COLLECT": lambda *args, **kwargs: None,
    })

    assert len(analyses) == 2
    manifest_sources = []
    for result in analyses:
        manifests = [entry for entry in result.datas if Path(entry[0]).name == "build-info.json"]
        assert len(manifests) == 1
        source, destination = manifests[0]
        assert destination == "."
        assert Path(source).is_file()
        manifest_sources.append(source)
        assert not any(Path(entry[0]).suffix in {".jsonl", ".log", ".zip"} for entry in result.datas)
    assert manifest_sources[0] == manifest_sources[1]


def test_product_versions_and_installer_upgrade_contract_are_v034():
    app_version = (ROOT / "app" / "_version.py").read_text(encoding="utf-8")
    library_version = (ROOT / "src" / "_version.py").read_text(encoding="utf-8")
    backend = (ROOT / "app" / "backend.py").read_text(encoding="utf-8")
    legacy_log = (ROOT / "qml" / "components" / "SendLogPanel.qml").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "installer" / "setup.nsi").read_text(encoding="utf-8-sig")

    assert '__version__ = "1.0.0"' in app_version
    assert '__version__ = "1.0.0"' in library_version
    assert '!define PRODUCT_NAME "福格微信助手"' in installer
    assert '!define PRODUCT_VERSION "1.0.0"' in installer
    assert '!define OLD_PRODUCT_NAME "五阿哥群发助手"' in installer
    assert "taskkill" in installer
    assert "OLD_PRODUCT_NAME" in installer
    assert "Software\\wx4py\\WeChatCourier" not in installer
    assert "version: str = __version__" in backend
    assert "五阿哥群发助手发送日志" not in legacy_log


def test_qt_artifact_pruning_removes_unused_large_modules():
    filters = load_build_filters_module()
    toc = [
        ("PySide6/Qt6WebEngineCore.dll", "source", "BINARY"),
        ("PySide6/Qt6Quick3D.dll", "source", "BINARY"),
        ("PySide6/qml/QtWebEngine/qtwebenginequickplugin.dll", "source", "BINARY"),
        ("PySide6/qml/QtQuick/VirtualKeyboard/qtvkbplugin.dll", "source", "BINARY"),
        ("PySide6/qml/QtQuick/Controls/FluentWinUI3/fluent.dll", "source", "BINARY"),
        ("PySide6/qml/QtQuick/Controls/Basic/Basic.qml", "source", "DATA"),
        ("PySide6/qml/QtQuick/Layouts/qmllayoutsplugin.dll", "source", "BINARY"),
        ("PySide6/qml/Qt5Compat/GraphicalEffects/DropShadow.qml", "source", "DATA"),
        ("PySide6/Qt6Quick.dll", "source", "BINARY"),
        ("qml/theme/qmldir", "source", "DATA"),
    ]

    kept = filters.filter_qt_artifacts(toc)
    kept_destinations = {entry[0] for entry in kept}

    assert "PySide6/Qt6WebEngineCore.dll" not in kept_destinations
    assert "PySide6/Qt6Quick3D.dll" not in kept_destinations
    assert "PySide6/qml/QtWebEngine/qtwebenginequickplugin.dll" not in kept_destinations
    assert "PySide6/qml/QtQuick/VirtualKeyboard/qtvkbplugin.dll" not in kept_destinations
    assert "PySide6/qml/QtQuick/Controls/FluentWinUI3/fluent.dll" not in kept_destinations
    assert "PySide6/qml/QtQuick/Controls/Basic/Basic.qml" in kept_destinations
    assert "PySide6/qml/QtQuick/Layouts/qmllayoutsplugin.dll" in kept_destinations
    assert "PySide6/qml/Qt5Compat/GraphicalEffects/DropShadow.qml" in kept_destinations
    assert "PySide6/Qt6Quick.dll" in kept_destinations
    assert "qml/theme/qmldir" in kept_destinations


def test_qt_artifact_pruning_rejects_foreign_icu_runtime():
    filters = load_build_filters_module()
    toc = [
        ("icuuc.dll", "C:/tools/poppler/bin/icuuc.dll", "BINARY"),
        ("icudt78.dll", "C:/tools/poppler/bin/icudt78.dll", "BINARY"),
        ("icudt.dll", "C:/tools/poppler/bin/icudt.dll", "BINARY"),
        ("PySide6/Qt6Core.dll", "source", "BINARY"),
    ]

    kept = filters.filter_qt_artifacts(toc)
    kept_destinations = {entry[0] for entry in kept}

    assert "icuuc.dll" not in kept_destinations
    assert "icudt78.dll" not in kept_destinations
    assert "icudt.dll" not in kept_destinations
    assert "PySide6/Qt6Core.dll" in kept_destinations


def test_desktop_demo_imports_wechat_client_without_src_barrel():
    demo_text = (ROOT / "app" / "demo.py").read_text(encoding="utf-8")

    assert "from src import WeChatClient" not in demo_text
    assert "from src.client import WeChatClient" in demo_text


def _iter_code_objects(code):
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            yield from _iter_code_objects(const)


def test_uiautomation_module_is_recursively_disassemblable_for_pyinstaller():
    code = compile(
        (ROOT / "src" / "core" / "uiautomation.py").read_text(encoding="utf-8"),
        str(ROOT / "src" / "core" / "uiautomation.py"),
        "exec",
    )

    for code_object in _iter_code_objects(code):
        list(dis.get_instructions(code_object))


def test_build_script_reports_missing_pyinstaller(monkeypatch):
    build = load_build_module()

    monkeypatch.setattr(build.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(RuntimeError, match="PyInstaller"):
        build._ensure_pyinstaller_available()


def test_pyinstaller_is_declared_as_build_dependency():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()

    assert "pyinstaller" in requirements


def test_build_cli_reports_missing_pyinstaller_without_traceback():
    if importlib.util.find_spec("PyInstaller") is not None:
        pytest.skip("PyInstaller is installed in this environment")

    result = subprocess.run(
        [sys.executable, str(ROOT / "build" / "build.py")],
        cwd=ROOT,
        capture_output=True,
    )
    output = (result.stdout + result.stderr).decode("gbk", errors="replace")

    assert result.returncode == 1
    assert "未安装 PyInstaller" in output
    assert "Traceback" not in output
