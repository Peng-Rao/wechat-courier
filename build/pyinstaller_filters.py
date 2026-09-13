# -*- coding: utf-8 -*-
"""PyInstaller artifact pruning helpers for the desktop build."""

from __future__ import annotations

from pathlib import PurePosixPath


_QML_ROOT = "pyside6/qml/"

_QML_KEEP_PREFIXES = (
    "pyside6/qml/qt5compat",
    "pyside6/qml/qtcore",
    "pyside6/qml/qtqml",
    "pyside6/qml/qtquick",
)

_QML_DROP_PREFIXES = (
    "pyside6/qml/qtquick/controls/designer",
    "pyside6/qml/qtquick/controls/fluentwinui3",
    "pyside6/qml/qtquick/controls/fusion",
    "pyside6/qml/qtquick/controls/imagine",
    "pyside6/qml/qtquick/controls/material",
    "pyside6/qml/qtquick/controls/universal",
    "pyside6/qml/qtquick/controls/windows",
    "pyside6/qml/qtquick/pdf",
    "pyside6/qml/qtquick/particles",
    "pyside6/qml/qtquick/scene2d",
    "pyside6/qml/qtquick/scene3d",
    "pyside6/qml/qtquick/virtualkeyboard",
    "pyside6/qml/qtquick3d",
)

_QT_BINARY_DROP_PREFIXES = (
    "qt63d",
    "qt6charts",
    "qt6chartsqml",
    "qt6datavisualization",
    "qt6graphs",
    "qt6labsplatform",
    "qt6labsstylekit",
    "qt6location",
    "qt6multimedia",
    "qt6pdf",
    "qt6pdfquick",
    "qt6positioning",
    "qt6quick3d",
    "qt6quick3dhelpers",
    "qt6quick3dhelpersimpl",
    "qt6quick3dparticles",
    "qt6quick3druntimerender",
    "qt6quick3dxr",
    "qt6quickcontrols2fluentwinui3",
    "qt6quickcontrols2fusion",
    "qt6quickcontrols2imagine",
    "qt6quickcontrols2material",
    "qt6quickcontrols2universal",
    "qt6quickparticles",
    "qt6remoteobjects",
    "qt6scxml",
    "qt6sensors",
    "qt6spatialaudio",
    "qt6texttospeech",
    "qt6virtualkeyboard",
    "qt6webchannel",
    "qt6webengine",
    "qt6webenginecore",
    "qt6webenginequick",
    "qt6websockets",
    "qt6webview",
)

_PATH_DROP_PARTS = (
    "/qt3d/",
    "/qtcharts/",
    "/qtdatavisualization/",
    "/qtgraphs/",
    "/qtlocation/",
    "/qtmultimedia/",
    "/qtpositioning/",
    "/qtquick3d/",
    "/qtwebchannel/",
    "/qtwebengine/",
    "/qtwebsockets/",
    "/qtwebview/",
)


def _normalize_dest(entry) -> str:
    dest = entry[0] if isinstance(entry, (tuple, list)) else str(entry)
    return str(PurePosixPath(str(dest).replace("\\", "/"))).lower()


def _is_unneeded_qml_artifact(dest: str) -> bool:
    if not dest.startswith(_QML_ROOT):
        return False
    if any(dest.startswith(prefix) for prefix in _QML_DROP_PREFIXES):
        return True
    return not any(dest.startswith(prefix) for prefix in _QML_KEEP_PREFIXES)


def _is_unneeded_qt_binary(dest: str) -> bool:
    name = PurePosixPath(dest).name.lower()
    if any(name.startswith(prefix) for prefix in _QT_BINARY_DROP_PREFIXES):
        return True
    return any(part in dest for part in _PATH_DROP_PARTS)


def _is_conflicting_system_icu(dest: str) -> bool:
    if "/" in dest:
        return False
    name = PurePosixPath(dest).name.lower()
    return name == "icuuc.dll" or (
        name.startswith("icudt") and name.endswith(".dll")
    )


def filter_qt_artifacts(toc):
    """Remove unused Qt/QML artifacts from a PyInstaller TOC-like list."""
    return [
        entry
        for entry in toc
        if not (
            _is_unneeded_qml_artifact(_normalize_dest(entry))
            or _is_unneeded_qt_binary(_normalize_dest(entry))
            or _is_conflicting_system_icu(_normalize_dest(entry))
        )
    ]
