"""Asset fidelity and real QML loading for the PDF-sourced Fuge monogram."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
ICON_SIZES = {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)}
SOURCE_COLOR = (248, 124, 64)


@pytest.mark.parametrize("filename,size", [
    ("fuge-logo.png", 512),
    ("fuge-logo-256.png", 256),
    ("fuge-logo-64.png", 64),
])
def test_monogram_preserves_transparency_color_and_proportions(filename, size):
    path = ROOT / "assets" / filename
    assert path.is_file(), f"Missing PDF-derived logo: {filename}"
    with Image.open(path) as logo:
        assert logo.mode == "RGBA"
        assert logo.size == (size, size)
        alpha = logo.getchannel("A")
        assert alpha.getextrema() == (0, 255)
        assert all(alpha.getpixel(p) == 0 for p in (
            (0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1),
        ))
        left, top, right, bottom = alpha.point(lambda v: 255 if v >= 128 else 0).getbbox()
        assert (right - left) / (bottom - top) == pytest.approx(211.623 / 198.950, abs=0.03)
        assert left / size == pytest.approx(0.0625, abs=0.02)
        assert abs((left + right) / 2 - size / 2) <= 1
        assert abs((top + bottom) / 2 - size / 2) <= 1
        for x, y in ((0.10, 0.10), (0.85, 0.10), (0.10, 0.50), (0.90, 0.55), (0.90, 0.90)):
            pixel = logo.getpixel((int(left + x * (right - left)), int(top + y * (bottom - top))))
            assert pixel[3] == 255
            assert all(abs(actual - expected) <= 1 for actual, expected in zip(pixel[:3], SOURCE_COLOR))
        for x, y in ((0.30, 0.50), (0.60, 0.30), (0.60, 0.70)):
            assert alpha.getpixel((int(left + x * (right - left)), int(top + y * (bottom - top)))) == 0


def test_windows_icon_uses_the_same_monogram_at_every_size():
    with Image.open(ROOT / "assets" / "app.ico") as icon:
        assert icon.info["sizes"] == ICON_SIZES
        with Image.open(ROOT / "assets" / "fuge-logo.png") as master:
            for size in sorted(ICON_SIZES):
                frame = icon.ico.getimage(size).convert("RGBA")
                expected_alpha = master.getchannel("A").resize(size, Image.Resampling.BOX)
                assert frame.getchannel("A").tobytes() == expected_alpha.tobytes(), f"Different logo in {size} icon frame"


def test_small_icons_preserve_the_pdf_fill_without_color_fringes():
    with Image.open(ROOT / "assets" / "app.ico") as icon:
        for size in ((16, 16), (32, 32)):
            frame = icon.ico.getimage(size).convert("RGBA")
            for y in range(frame.height):
                for x in range(frame.width):
                    red, green, blue, alpha = frame.getpixel((x, y))
                    if alpha:
                        assert (red, green, blue) == SOURCE_COLOR


def packaged_logo_data():
    # Evaluate only the spec's asset collection, never Analysis/EXE or packaging.
    tree = ast.parse((ROOT / "build" / "build.spec").read_text(encoding="utf-8"))
    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "icon_path" for t in node.targets))
    end = next(i for i, node in enumerate(tree.body[start + 1:], start + 1)
               if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "binaries" for t in node.targets))
    namespace = {"ROOT": str(ROOT), "os": os, "datas": []}
    exec(compile(ast.Module(body=tree.body[start:end], type_ignores=[]), "logo_datas", "exec"), namespace)
    return namespace["datas"]


def test_packaging_includes_all_qml_logo_assets():
    data = {(Path(source).name, target) for source, target in packaged_logo_data()}
    assert {("app.ico", "assets"), ("fuge-logo.png", "assets"),
            ("fuge-logo-256.png", "assets"), ("fuge-logo-64.png", "assets")} <= data


@pytest.mark.parametrize("frozen_layout", [False, True])
@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_qml_logos_load_and_render_in_source_and_packaged_layout(tmp_path, frozen_layout, scale):
    layout = ROOT
    if frozen_layout:
        layout = tmp_path / "_internal"
        shutil.copytree(ROOT / "qml", layout / "qml")
        for source, target in packaged_logo_data():
            destination = layout / target
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QT_QUICK_CONTROLS_STYLE="Basic", QT_SCALE_FACTOR=str(scale))
    result = subprocess.run([sys.executable, str(Path(__file__)), str(layout), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def render_logo_ui(layout, output):
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest

    output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Microsoft YaHei", 10))
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.load(QUrl.fromLocalFile(str(layout / "qml" / "main.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    QTest.qWait(80)
    images = {}
    for name in ("titlebarBrandLogo", "startupBrandLogo", "defaultBrandAvatar"):
        logo = window.findChild(QObject, name)
        assert logo is not None, f"Missing {name}"
        assert QQmlExpression(engine.rootContext(), logo, "Number(status)").evaluate()[0] == 1, f"{name}: {warnings}"
        assert QQmlExpression(engine.rootContext(), logo, "Number(fillMode)").evaluate()[0] == 1, f"{name} must preserve aspect ratio"
        images[name] = logo
    assert window.grabWindow().save(str(output / "fuge-logo-startup.png"))
    QTest.qWait(1000)
    assert window.grabWindow().save(str(output / "fuge-logo-workspace.png"))
    screenshot = window.grabWindow()
    # The screenshot is in physical pixels; QQuickItem geometry is logical.
    scale_x = screenshot.width() / window.width()
    scale_y = screenshot.height() / window.height()
    for name in ("titlebarBrandLogo", "defaultBrandAvatar"):
        logo = images[name]
        position = logo.mapToScene(logo.boundingRect().topLeft())
        crop = screenshot.copy(round(position.x() * scale_x), round(position.y() * scale_y),
                               round(logo.width() * scale_x), round(logo.height() * scale_y))
        assert crop.save(str(output / f"{name}.png"))
        assert any(abs(crop.pixelColor(x, y).red() - 248) <= 1
                   and abs(crop.pixelColor(x, y).green() - 124) <= 1
                   for x in range(crop.width()) for y in range(crop.height())), name
    assert not any("fuge-logo" in warning for warning in warnings), warnings
    window.close()
    app.processEvents()


if __name__ == "__main__":
    render_logo_ui(Path(sys.argv[1]), Path(sys.argv[2]))
