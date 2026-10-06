import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from build import verify_package as checker
from build.pyinstaller_filters import filter_qt_artifacts


def test_qml_resource_collection_includes_imported_layout_helpers():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "build/build.spec").read_text(encoding="utf-8"))
    collect = next(node for node in tree.body if isinstance(node, ast.For)
                   and isinstance(node.iter, ast.Call)
                   and isinstance(node.iter.func, ast.Attribute)
                   and node.iter.func.attr == "walk")
    scope = {"os": os, "ROOT": str(root), "qml_dir": str(root / "qml"), "datas": []}
    exec(compile(ast.Module(body=[collect], type_ignores=[]), "qml resource collection", "exec"), scope)
    packaged = {Path(source).relative_to(root).as_posix() for source, _ in scope["datas"]}
    for filename in ("qml/components/WorkspaceHeader.qml", "qml/components/TableWidths.js",
                     "qml/icons/search.svg", "qml/icons/refresh.svg", "qml/icons/database.svg"):
        assert filename in packaged, f"QML runtime dependency is missing: {filename}"
    header_runtime = [("PySide6/qml/Qt/labs/qmlmodels/qmldir", "source", "DATA"),
                      ("PySide6/qml/Qt/labs/qmlmodels/labsmodelsplugin.dll", "source", "BINARY")]
    assert filter_qt_artifacts(header_runtime) == header_runtime, "header TableModel runtime was pruned"


def make_package(tmp_path, monkeypatch, missing=(), broken=()):
    calls = []
    qt_dir = tmp_path / "_internal" / "PySide6"
    qt_dir.mkdir(parents=True)
    (qt_dir / "opengl32sw.dll").write_bytes(b"test software OpenGL")
    (qt_dir / "Qt6OpenGL.dll").write_bytes(b"test Qt OpenGL")

    def archive_reader(filename):
        name = Path(filename).name
        calls.append(name)
        if name in broken:
            raise ValueError("broken archive")

        def embedded(archive_name):
            assert archive_name == "PYZ.pyz"
            return SimpleNamespace(toc={} if name in missing else {"win32timezone": ()})

        return SimpleNamespace(open_embedded_archive=embedded)

    monkeypatch.setattr(checker, "CArchiveReader", archive_reader)
    return calls


def test_checks_every_executable_without_launching_it(tmp_path, monkeypatch):
    calls = make_package(tmp_path, monkeypatch)
    checker.verify_package(tmp_path)
    assert calls == list(checker.EXECUTABLES)


@pytest.mark.parametrize("name", checker.EXECUTABLES)
def test_rejects_missing_dynamic_timezone_module(tmp_path, monkeypatch, name):
    calls = make_package(tmp_path, monkeypatch, missing=(name,))
    with pytest.raises(RuntimeError, match="win32timezone") as error:
        checker.verify_package(tmp_path)
    assert name in str(error.value)
    assert calls == list(checker.EXECUTABLES)


def test_reports_broken_archive_and_missing_module_together(tmp_path, monkeypatch):
    make_package(tmp_path, monkeypatch, missing=(checker.EXECUTABLES[1],), broken=(checker.EXECUTABLES[0],))
    with pytest.raises(RuntimeError) as error:
        checker.verify_package(tmp_path)
    assert "cannot inspect executable" in str(error.value)
    assert "missing win32timezone" in str(error.value)


def test_cli_failure_is_nonzero_and_explains_dependency(tmp_path, monkeypatch, capsys):
    make_package(tmp_path, monkeypatch, missing=(checker.EXECUTABLES[1],))
    assert checker.main([str(tmp_path)]) == 1
    assert "missing win32timezone" in capsys.readouterr().err


def test_cli_success_is_zero(tmp_path, monkeypatch, capsys):
    make_package(tmp_path, monkeypatch)
    assert checker.main([str(tmp_path)]) == 0
    assert "all three executables" in capsys.readouterr().out


@pytest.mark.parametrize("dll", ["opengl32sw.dll", "Qt6OpenGL.dll"])
def test_rejects_missing_opengl_runtime(tmp_path, monkeypatch, dll):
    make_package(tmp_path, monkeypatch)
    (tmp_path / "_internal" / "PySide6" / dll).unlink()
    with pytest.raises(RuntimeError, match=dll):
        checker.verify_package(tmp_path)


def test_opengl_runtime_belongs_to_gui_analysis_only():
    spec = Path(__file__).resolve().parents[1] / "build/build.spec"
    assignments = {
        node.targets[0].id: node.value for node in ast.parse(spec.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Analysis"
    }
    for target, expected in (("a", "gui_binaries"), ("agent_analysis", "binaries"), ("contact_analysis", "binaries")):
        keyword = next(item for item in assignments[target].keywords if item.arg == "binaries")
        assert isinstance(keyword.value, ast.Name) and keyword.value.id == expected
