from pathlib import Path
from types import SimpleNamespace

import pytest

from build import verify_package as checker


def make_package(tmp_path, monkeypatch, missing=(), broken=()):
    calls = []

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
