"""Shared, environment-free provenance for the GUI and isolated agent."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from app._version import __version__


MANIFEST_FILENAME = "build-info.json"
RELEASE_CHANNEL = "candidate"
_SOURCE_TREES = ("app", "src", "qml", "build")
_SOURCE_SUFFIXES = {".py", ".pyi", ".qml", ".qmltypes", ".js", ".mjs", ".svg", ".qrc", ".spec"}
_EXCLUDED_DIRS = {
    "__pycache__", "build", "dist", "logs", "log", "artifacts",
    "venv", "node_modules", "comtypes_gen",
}
_ROOT_SOURCES = ("main.py", "agent_main.py", "requirements.txt", "requirements-dev.txt")


def _source_files(root: Path) -> list[Path]:
    paths = []
    for tree in _SOURCE_TREES:
        directory = root / tree
        if directory.is_symlink() or directory.is_junction():
            continue
        for parent, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = sorted(
                name for name in dirs
                if not name.startswith(".") and name.lower() not in _EXCLUDED_DIRS
                and not (Path(parent) / name).is_symlink()
                and not (Path(parent) / name).is_junction()
            )
            for name in files:
                path = Path(parent) / name
                if (
                    not name.startswith(".") and not path.is_symlink()
                    and (path.suffix.lower() in _SOURCE_SUFFIXES or name == "qmldir")
                ):
                    paths.append(path)
    for name in _ROOT_SOURCES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def create_build_manifest(source_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Hash ordered relative source paths and bytes, never logs or build outputs."""
    root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[1]
    digest = hashlib.sha256(b"wechat-courier-build-v1\0")
    paths = _source_files(root)
    for path in paths:
        # Length prefixes distinguish both path/content boundaries and empty files.
        name = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {
        "schemaVersion": 1,
        "version": __version__,
        "releaseChannel": RELEASE_CHANNEL,
        "buildFingerprint": f"sha256:{digest.hexdigest()}",
        "sourceFileCount": len(paths),
    }


def write_build_manifest(
    destination: str | os.PathLike[str],
    source_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Generate the single data file consumed by both packaged executables."""
    manifest = create_build_manifest(source_root)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


@lru_cache(maxsize=1)
def _source_manifest() -> dict[str, Any]:
    return create_build_manifest()


def _packaged_manifest() -> tuple[dict[str, Any], str]:
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    try:
        manifest = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except (OSError, ValueError):
        return {}, "invalid"
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != 1
        or manifest.get("version") != __version__
        or manifest.get("releaseChannel") != RELEASE_CHANNEL
        or not isinstance(manifest.get("buildFingerprint"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["buildFingerprint"]) is None
        or type(manifest.get("sourceFileCount")) is not int
        or manifest["sourceFileCount"] < 0
    ):
        return {}, "invalid"
    return {
        key: manifest[key] for key in (
            "schemaVersion", "version", "releaseChannel", "buildFingerprint", "sourceFileCount",
        )
    }, "packaged"


def build_info() -> dict[str, Any]:
    """Return JSON-safe identity, excluding argv, environment and user log paths.

    Source identity is cached for this process. Frozen processes only trust the
    packaged manifest; missing/corrupt provenance is explicit, never recomputed.
    """
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        manifest, provenance = _packaged_manifest()
    else:
        try:
            manifest, provenance = _source_manifest(), "source"
        except OSError:
            manifest, provenance = {}, "unavailable"
    return {
        "version": __version__,
        "releaseChannel": RELEASE_CHANNEL,
        "buildFingerprint": "unavailable",
        **manifest,
        "executablePath": str(Path(sys.executable).resolve()),
        "frozen": frozen,
        "pythonVersion": ".".join(map(str, sys.version_info[:3])),
        "platform": sys.platform,
        "provenance": provenance,
    }


__all__ = ["MANIFEST_FILENAME", "build_info", "create_build_manifest", "write_build_manifest"]
