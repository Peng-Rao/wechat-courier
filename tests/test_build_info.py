from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module():
    assert (ROOT / "app" / "build_info.py").is_file(), "build provenance API is missing"
    return importlib.import_module("app.build_info")


def _sources(root):
    for relative, content in {
        "app/main.py": "APP = 1\n", "src/core.py": "CORE = 1\n",
        "qml/Main.qml": "Item {}\n", "build/build.spec": "BUILD = 1\n",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_fingerprint_is_content_based_and_independent_of_checkout_path(tmp_path):
    module = _module()
    first, second = tmp_path / "first", tmp_path / "second"
    _sources(first)
    _sources(second)
    one = module.create_build_manifest(first)
    two = module.create_build_manifest(second)
    assert one == two
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", one["buildFingerprint"])
    assert one["sourceFileCount"] == 4
    assert str(tmp_path) not in json.dumps(one)


@pytest.mark.parametrize("relative", [
    "app/main.py", "src/core.py", "qml/Main.qml", "build/build.spec",
])
def test_each_source_tree_contributes_to_fingerprint(tmp_path, relative):
    module = _module()
    _sources(tmp_path)
    before = module.create_build_manifest(tmp_path)["buildFingerprint"]
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    assert module.create_build_manifest(tmp_path)["buildFingerprint"] != before
    path.unlink()
    assert module.create_build_manifest(tmp_path)["buildFingerprint"] != before


def test_generated_files_secrets_and_logs_do_not_affect_manifest(tmp_path, monkeypatch):
    module = _module()
    _sources(tmp_path)
    before = module.create_build_manifest(tmp_path)
    monkeypatch.setenv("PROVENANCE_TEST_TOKEN", "environment secret")
    for relative in (
        "app/.env", "app/__pycache__/cached.py", "app/logs/private.py",
        "build/build/generated.py", "build/dist/generated.py",
        "qml/logs/private.qml", "src/session.json", "build/user-logs.zip",
        "build/build-info.json", "logs/uia-diagnostics.jsonl",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private user content", encoding="utf-8")
    assert module.create_build_manifest(tmp_path) == before
    assert "environment secret" not in json.dumps(module.build_info())


def test_packaged_gui_and_agent_use_same_manifest_without_source_tree(tmp_path, monkeypatch):
    module = _module()
    source = tmp_path / "source"
    _sources(source)
    bundle = tmp_path / "bundle"
    manifest_path = module.write_build_manifest(bundle / "build-info.json", source)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["environment"] = {"TOKEN": "must not escape"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    results = []
    for executable in ("gui.exe", "wechat-agent.exe"):
        monkeypatch.setattr(sys, "executable", str(bundle / executable))
        results.append(module.build_info())
    assert results[0]["buildFingerprint"] == manifest["buildFingerprint"]
    assert results[0]["buildFingerprint"] == results[1]["buildFingerprint"]
    assert results[0]["executablePath"] != results[1]["executablePath"]
    assert results[0]["frozen"] is True
    assert results[0]["provenance"] == "packaged"
    assert "must not escape" not in json.dumps(results)


@pytest.mark.parametrize("content", [None, "not json", "{}", '{"buildFingerprint":"fake"}'])
def test_frozen_missing_or_invalid_manifest_does_not_claim_source_provenance(
    tmp_path, monkeypatch, content,
):
    module = _module()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    if content is not None:
        (tmp_path / "build-info.json").write_text(content, encoding="utf-8")
    info = module.build_info()
    assert info["buildFingerprint"] == "unavailable"
    assert info["provenance"] in {"missing", "invalid"}
    assert info["version"] == "0.3.2"


def test_source_build_info_is_json_safe_and_does_not_expose_argv_or_environment(monkeypatch):
    module = _module()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["app", "--password=secret argument"])
    monkeypatch.setenv("PROVENANCE_TEST_TOKEN", "secret environment")
    info = module.build_info()
    assert info["version"] == "0.3.2"
    assert info["releaseChannel"] == "candidate"
    assert info["frozen"] is False
    assert info["provenance"] == "source"
    assert info["executablePath"] == str(Path(sys.executable).resolve())
    assert "secret argument" not in json.dumps(info)
    assert "secret environment" not in json.dumps(info)
