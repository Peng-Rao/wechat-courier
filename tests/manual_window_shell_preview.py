"""Native shell visual/interaction gate. Never starts a real automation Agent."""

import argparse
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qVersion
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from app import win32_helper as wh
from app.backend import BackendController
from app.window_shell import WindowShellController, configure_native_renderer


def run(output: Path, prototype: bool):
    faulthandler.dump_traceback_later(90)
    app = QGuiApplication([])
    configure_native_renderer()
    original_cursor = QCursor.pos()
    output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory()
    from PySide6.QtCore import QSettings
    settings = QSettings(str(Path(temporary.name) / "settings.ini"), QSettings.IniFormat)
    backend = BackendController(settings=settings, auto_start_agent=False)
    shell = WindowShellController()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("windowShell", shell)
    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    underlay = QQuickWindow()
    underlay.setFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
                      | Qt.WindowStaysOnTopHint)
    underlay.setColor(QColor("#d23465"))
    underlay.setGeometry(geometry.x() + 24, geometry.y() + 24,
                         geometry.width() - 48, geometry.height() - 48)
    underlay.show()
    try:
        if prototype:
            prototype_qml = b'''import QtQuick
import QtQuick.Controls.Basic
import "qml/theme"
ApplicationWindow {
    width: 960; height: 680; visible: false; opacity: 1
    flags: windowShell.initialWindowFlags | Qt.WindowStaysOnTopHint; color: "transparent"
    background: Rectangle { color: WxTheme.clWindowTint }
    Text { anchors.centerIn: parent; text: "Native rounded shell + Acrylic";
           color: WxTheme.clTextPrimary; font.pixelSize: 24 }
}'''
            engine.loadData(prototype_qml, QUrl.fromLocalFile(str(ROOT / "shell-prototype.qml")))
        else:
            engine.load(QUrl.fromLocalFile(str(ROOT / "qml/main.qml")))
        assert engine.rootObjects(), "QML failed to load"
        window = engine.rootObjects()[0]
        if not prototype:
            window.setFlags(window.flags() | Qt.WindowStaysOnTopHint)
        assert shell.attach(window), shell.fallbackReason
        assert shell.nativeFrameEnabled, shell.fallbackReason
        window.resize(960, 680)
        window.setPosition(geometry.x() + (geometry.width() - 960) // 2,
                           geometry.y() + (geometry.height() - 680) // 2)
        window.show()
        window.raise_()
        window.requestActivate()
        QCursor.setPos(window.mapToGlobal(QPointF(400, 400).toPoint()))
        QTest.qWait(650)
        hwnd = int(window.winId())
        exstyle = wh._GetWindowLongPtr(ctypes.c_void_p(hwnd), wh.GWL_EXSTYLE)
        if prototype:
            assert not exstyle & wh.WS_EX_LAYERED, hex(exstyle)
        assert window.opacity() == 1
        report = {"nativeFrameEnabled": shell.nativeFrameEnabled, "hwnd": hwnd,
                  "qtVersion": qVersion(), "renderer": window.rendererInterface().graphicsApi().name,
                  "style": hex(wh._GetWindowLongPtr(ctypes.c_void_p(hwnd), wh.GWL_STYLE)),
                  "extendedStyle": hex(exstyle), "dpi": screen.devicePixelRatio(),
                  "prototype": prototype, "scenarios": []}

        def activate():
            current_thread = ctypes.WinDLL("kernel32").GetCurrentThreadId()
            foreground_thread = wh.user32.GetWindowThreadProcessId(wh.user32.GetForegroundWindow(), None)
            linked = foreground_thread != current_thread and wh.user32.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                window.raise_()
                wh.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
                wh.user32.SetActiveWindow(ctypes.c_void_p(hwnd))
                wh.user32.SetFocus(ctypes.c_void_p(hwnd))
            finally:
                if linked:
                    wh.user32.AttachThreadInput(current_thread, foreground_thread, False)
            QTest.qWait(100)

        def script(source):
            expression = QQmlExpression(engine.contextForObject(window), window, source)
            expression.evaluate()
            assert not expression.hasError(), expression.error().toString()

        def capture(name):
            bounds = wh.wintypes.RECT()
            assert wh.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 9,
                                                  ctypes.byref(bounds), ctypes.sizeof(bounds)) == 0
            activate()
            QTest.qWait(150)
            assert window.isActive(), "Visual capture requires the preview in foreground"
            image = screen.grabWindow(0).toImage()
            image = image.copy(bounds.left, bounds.top, bounds.right - bounds.left,
                               bounds.bottom - bounds.top)
            assert not image.isNull()
            assert image.save(str(output / f"{name}.png"))
            # Client grabs render a frame: only use them after desktop evidence.
            window.grabWindow().save(str(output / f"{name}-client.png"))
            client_rect = wh.wintypes.RECT()
            wh.user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(client_rect))
            client_origin = wh.wintypes.POINT()
            wh.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(client_origin))
            return {"width": image.width(), "height": image.height(),
                    "topLeft": image.pixelColor(0, 0).name(),
                    "topMid": image.pixelColor(image.width() // 2, 0).name(),
                    "surfaceSample": image.pixelColor(image.width() // 4, image.height() // 4).getRgb()[:3],
                    "bounds": [bounds.left, bounds.top, bounds.right, bounds.bottom],
                    "clientBounds": [client_origin.x, client_origin.y,
                                     client_origin.x + client_rect.right, client_origin.y + client_rect.bottom],
                    "visible": bool(wh.user32.IsWindowVisible(ctypes.c_void_p(hwnd))),
                    "foreground": wh.user32.GetForegroundWindow(),
                    "currentHwnd": int(window.winId()), "shellHwnd": shell._hwnd,
                    "alphaBuffer": window.format().alphaBufferSize(),
                    "activeFocus": app.focusWindow() == window,
                    "active": window.isActive()}

        for dark in (False, True):
            for glass, opacity in ((True, 45), (True, 72), (True, 90), (False, 72)):
                script(f"WxTheme.isDark = {str(dark).lower()}; "
                       f"WxTheme.glassEnabled = {str(glass).lower()}; WxTheme.glassOpacity = {opacity}")
                if prototype:
                    shell.applyVisuals(dark, glass, opacity)
                assert shell._visuals == (dark, glass, opacity)
                assert shell.backdropAvailable
                window.raise_()
                activate()
                window.update()
                QTest.qWait(500)
                name = f"{'dark' if dark else 'light'}-{'glass' if glass else 'solid'}-{opacity}"
                pixels = capture(name)
                if prototype:
                    assert not wh._GetWindowLongPtr(ctypes.c_void_p(hwnd), wh.GWL_EXSTYLE) & wh.WS_EX_LAYERED
                report["scenarios"].append({"name": name, **pixels})
        if prototype:
            samples = [item["surfaceSample"] for item in report["scenarios"]
                       if item["name"].endswith("glass-45")]
            report["translucencyGatePassed"] = all(red - green > 12 for red, green, blue in samples)
            report["integrationEnabled"] = True
            report["renderer"] = window.rendererInterface().graphicsApi().name
            pattern_component = QQmlComponent(engine)
            pattern_component.setData(b'''import QtQuick
Item { Repeater { model: 250; Rectangle { x: index * 8; width: 8; height: 2000;
color: index % 2 ? "#d23465" : "#287eae" } } }''', QUrl())
            pattern = pattern_component.create()
            pattern.setParentItem(underlay.contentItem())
            script("WxTheme.isDark = false; WxTheme.glassEnabled = true; WxTheme.glassOpacity = 45")
            shell.applyVisuals(False, True, 45)
            QTest.qWait(500)
            capture("pattern-blur")
            blurred = screen.grabWindow(0).toImage()
            assert wh.disable_window_backdrop(hwnd)
            QTest.qWait(500)
            capture("pattern-without-blur")
            sharp = screen.grabWindow(0).toImage()
            region_x, region_y = report["scenarios"][0]["bounds"][:2]
            def contrast(im):
                values = [im.pixelColor(region_x + x, region_y + 200).red() for x in range(150, 350)]
                return max(values) - min(values)
            report["patternContrast"] = {"blur": contrast(blurred), "noBlur": contrast(sharp)}
            assert contrast(sharp) > contrast(blurred) + 15
        else:
            popup = next(obj for obj in window.findChildren(QObject)
                         if obj.metaObject().className().startswith("SettingsDialog_"))
            for size in ((960, 680), (1320, 880)):
                window.resize(min(size[0], geometry.width() - 32), min(size[1], geometry.height() - 32))
                window.setPosition(geometry.x() + (geometry.width() - window.width()) // 2,
                                   geometry.y() + (geometry.height() - window.height()) // 2)
                for dark in (False, True):
                    script(f"WxTheme.isDark = {str(dark).lower()}; appRoot.openSettings(1)")
                    QTest.qWait(500)
                    assert popup.property("opened")
                    assert popup.property("padding") == 1
                    assert popup.property("x") >= 0 and popup.property("y") >= 0
                    name = f"settings-{'dark' if dark else 'light'}-{size[0]}"
                    capture(name)
                    client_image = window.grabWindow()
                    scale = window.devicePixelRatio()
                    client_image.copy(round(popup.property("x") * scale),
                                      round(popup.property("y") * scale),
                                      round(popup.property("width") * scale),
                                      round(popup.property("height") * scale)).save(str(output / f"{name}-popup.png"))
                    popup.close()
                    QTest.qWait(100)
            for action, expected in [("root.showMaximized()", QQuickWindow.Maximized),
                                     ("root.centerAndRestore()", QQuickWindow.Windowed),
                                     ("root.enterFullScreenPreview()", QQuickWindow.FullScreen),
                                     ("root.exitFullScreenPreview()", QQuickWindow.Windowed),
                                     ("root.applySnapMode('left')", QQuickWindow.Windowed),
                                     ("root.applySnapMode('right')", QQuickWindow.Windowed),
                                     ("root.centerAndRestore()", QQuickWindow.Windowed)]:
                script(action)
                QTest.qWait(500)
                assert window.visibility() == expected
                if "applySnapMode" in action:
                    assert shell._layout_mode == ("left" if "left" in action else "right")
                style = wh._GetWindowLongPtr(ctypes.c_void_p(hwnd), wh.GWL_STYLE)
                assert not style & wh.WS_CAPTION, (action, hex(style))
                report["scenarios"].append({"action": action, "style": hex(style),
                    "mode": shell._layout_mode, **capture(f"state-{len(report['scenarios'])}")})
            # Window-manager geometry notifications must exit custom half-screen mode.
            script("root.applySnapMode('left')")
            QTest.qWait(150)
            wh.user32.SendMessageW(ctypes.c_void_p(hwnd), wh.WM_ENTERSIZEMOVE, 0, 0)
            window.setPosition(window.x() + 32, window.y() + 32)
            QTest.qWait(150)
            assert shell._layout_mode == window.property("shellLayoutMode") == "normal"
            script("root.applySnapMode('right')")
            QTest.qWait(150)
            wh.user32.SendMessageW(ctypes.c_void_p(hwnd), wh.WM_ENTERSIZEMOVE, 0, 0)
            window.resize(window.width() + 24, window.height() - 32)
            QTest.qWait(150)
            assert shell._layout_mode == window.property("shellLayoutMode") == "normal"
            for name, expected in [("windowMaximizeButton", QQuickWindow.Maximized),
                                   ("windowMaximizeButton", QQuickWindow.Windowed),
                                   ("windowMinimizeButton", QQuickWindow.Minimized)]:
                item = window.findChild(QObject, name)
                point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                QTest.qWait(350)
                assert window.visibility() == expected, name
            window.showNormal()
            QTest.qWait(200)
            report["captionButtonsPassed"] = True
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        if prototype:
            assert report["translucencyGatePassed"], "Native/glass gate failed; production shell is unchanged"
    finally:
        faulthandler.cancel_dump_traceback_later()
        shell.detach()
        for window in engine.rootObjects():
            window.close()
        underlay.close()
        QCursor.setPos(original_cursor)
        backend.shutdown()
        engine.deleteLater()
        app.processEvents()
        temporary.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "window-shell")
    args = parser.parse_args()
    run(args.output.resolve(), args.prototype)
