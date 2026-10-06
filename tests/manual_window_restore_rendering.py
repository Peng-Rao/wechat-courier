"""Desktop-first restore gate using production QML and fake RPC, never WeChat."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def compare_colors(reference, actual, dark, *, border_rounding=0):
    """Check stable surface, text and brand pixels, not merely nonblank images."""
    assert all(abs(a - b) <= border_rounding for a, b in zip(actual.size, reference.size)), (actual.size, reference.size)
    if actual.size != reference.size:
        bounds = (0, 0, min(reference.width, actual.width), min(reference.height, actual.height))
        reference, actual = reference.crop(bounds), actual.crop(bounds)
    before, after = reference.load(), actual.load()
    groups = {"surface": [], "text": [], "brand": []}
    ink = (238, 238, 239) if dark else (37, 38, 42)
    for y in range(12, reference.height - 8, 4):
        for x in range(12, reference.width - 8, 4):
            color = before[x, y][:3]
            if max(abs(a - b) for a, b in zip(color, (248, 124, 64))) < 9:
                kind = "brand"
            elif max(abs(a - b) for a, b in zip(color, ink)) < 9:
                kind = "text"
            elif (max(color) - min(color) < 12 and (max(color) < 100 if dark else min(color) > 180)
                  and color == before[x + 1, y][:3] == before[x, y + 1][:3]):
                kind = "surface"
            else:
                continue
            groups[kind].append(max(abs(a - b) for a, b in zip(color, after[x, y][:3])))
    result = {}
    for kind, errors in groups.items():
        assert len(errors) >= 12, (kind, len(errors))
        retained = sum(error <= 20 for error in errors) / len(errors)
        result[kind] = {"samples": len(errors), "retained": round(retained, 4),
                        "medianError": statistics.median(errors)}
        assert retained >= (0.85 if kind == "surface" else 0.65), (kind, result[kind])
        assert statistics.median(errors) <= 12, (kind, result[kind])
    return result


def run(output, cycles):
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    from PySide6.QtCore import QObject, QSettings, Qt, QUrl, qVersion
    from PySide6.QtGui import QColor, QFont, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from app import win32_helper as wh
    from app.backend import BackendController
    from app.friend_import import load_friend_records
    from app.window_shell import WindowShellController, configure_native_renderer, configure_window_diagnostics
    from tests.test_v3_controllers import FakeAgentClient

    output.mkdir(parents=True, exist_ok=True)
    configure_window_diagnostics(output)
    app = QGuiApplication([])
    configure_native_renderer()
    app.setFont(QFont("Microsoft YaHei UI", 10))
    assert app.platformName() == "windows"
    report = {"qml": "qml/main.qml", "qt": qVersion(), "syntheticOnly": True,
              "captureOrder": "desktop immediate, desktop idle, then optional client", "restores": []}
    with tempfile.TemporaryDirectory() as temporary:
        client = FakeAgentClient()
        backend = BackendController(settings=QSettings(str(Path(temporary) / "ui.ini"), QSettings.IniFormat), agent_client=client)
        backend.agent.applyInspection({"connected": True, "version": "4.1.13.65", "supported": True, "uiaReady": True})
        backend.message.recipientsText = "Alice\nBob\nCarol"
        backend.message.templateText = "{name}, restore rendering acceptance only."
        backend.friends.model.replace_records(load_friend_records([
            ["姓名", "账号"], *[[f"Sample {i}", f"wxid_restore_mock_{i:03}"] for i in range(1, 201)]]))
        assert backend.friends.model.selectRange(3, 6)
        backend.contacts._discover = lambda directory: []
        backend.contacts._directory = "D:/Synthetic/xwechat_files"
        backend.contacts.model.replace_records([
            {"nick_name": f"Sample {i}", "remark": "Mock", "phone": "", "username": f"wxid_mock_{i}",
             "alias": "", "description": "Synthetic", "category": "friend"} for i in range(20)])
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
        shell = WindowShellController()
        engine.rootContext().setContextProperty("backend", backend)
        engine.rootContext().setContextProperty("windowShell", shell)
        screen = app.primaryScreen()
        geometry = screen.availableGeometry()
        underlay = QQuickWindow()
        underlay.setFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnTopHint)
        underlay.setColor(QColor("#647c78"))
        underlay.setGeometry(geometry)
        underlay.show()
        try:
            engine.load(QUrl.fromLocalFile(str(ROOT / "qml/main.qml")))
            assert engine.rootObjects(), warnings
            window = engine.rootObjects()[0]
            window.setFlags(window.flags() | Qt.WindowStaysOnTopHint)
            assert shell.attach(window) and shell.nativeFrameEnabled
            window.resize(960, 680)
            window.setPosition(geometry.x() + (geometry.width() - 960) // 2,
                               geometry.y() + (geometry.height() - 680) // 2)
            window.show()
            QTest.qWait(3000)
            # Startup geometry is queued by QML; apply the gate size afterwards.
            window.resize(960, 680)
            window.setPosition(geometry.x() + (geometry.width() - 960) // 2,
                               geometry.y() + (geometry.height() - 680) // 2)
            QTest.qWait(400)
            assert (window.width(), window.height()) == (960, 680)
            root = window.findChild(QObject, "appRoot")
            popup = window.findChild(QObject, "settingsDialog")
            report.update(renderer=window.rendererInterface().graphicsApi().name,
                          softwareRequested=os.environ.get("QT_OPENGL") == "software",
                          dpr=window.devicePixelRatio())
            import win32api
            import win32process
            libraries = [Path(win32process.GetModuleFileNameEx(win32api.GetCurrentProcess(), module)).name.lower()
                         for module in win32process.EnumProcessModules(win32api.GetCurrentProcess())]
            report["softwareOpenGLLoaded"] = "opengl32sw.dll" in libraries
            if report["softwareRequested"]:
                assert report["softwareOpenGLLoaded"], libraries
            assert report["renderer"] == "OpenGL", report

            def script(source):
                expression = QQmlExpression(engine.contextForObject(window), window, source)
                expression.evaluate()
                assert not expression.hasError(), expression.error().toString()

            def activate():
                hwnd = ctypes.c_void_p(int(window.winId()))
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                foreground = wh.user32.GetWindowThreadProcessId(wh.user32.GetForegroundWindow(), None)
                linked = foreground != current and wh.user32.AttachThreadInput(current, foreground, True)
                try:
                    window.raise_()
                    wh.user32.SetForegroundWindow(hwnd)
                    wh.user32.SetActiveWindow(hwnd)
                finally:
                    if linked:
                        wh.user32.AttachThreadInput(current, foreground, False)

            def capture(name):
                bounds = wh.wintypes.RECT()
                assert wh.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(int(window.winId())), 9,
                    ctypes.byref(bounds), ctypes.sizeof(bounds)) == 0
                image = ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom), all_screens=True).convert("RGB")
                image.save(output / f"{name}.png")
                return image

            def invariant():
                return (backend.message.recipientsText, backend.message.templateText,
                        backend.friends.model.selectedCount, backend.contacts.model.totalCount,
                        backend.task.kind, backend.task.active, backend.task.done,
                        backend.task.successCount, backend.task.failureCount,
                        backend.task.unknownCount, backend.task.phase)

            for page in ("messages", "friends", "contacts", "message-monitor", "friend-monitor", "settings"):
                if backend.task.active:
                    client.notificationReceived.emit("task.finished", {"taskId": backend.task._task_id, "outcome": "stopped"})
                for name in ("messageWorkspace", "friendWorkspace"):
                    window.findChild(QObject, name).setProperty("monitorDismissed", True)
                root.setProperty("workspaceIndex", 2 if page == "contacts" else 1 if page.startswith("friend") else 0)
                if "monitor" in page:
                    if page.startswith("friend"):
                        client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
                    start = backend.task.startFriends if page.startswith("friend") else backend.task.startMessage
                    assert start(), backend.task.error
                    request_id, _, payload = client.calls[-1]
                    client.replyReceived.emit(request_id, {"accepted": True})
                    client.notificationReceived.emit("task.event", {"taskId": payload["taskId"], "itemId": payload["items"][0]["itemId"],
                        "step": "window_bound", "outcome": "ok", "done": 0, "total": len(payload["items"]), "detail": "Synthetic acceptance"})
                    client.notificationReceived.emit("agent.status", {"taskId": payload["taskId"], "status": "waiting", "remaining": 12})
                if page == "settings":
                    script("appRoot.openSettings(1)")
                    assert popup.property("opened")
                for dark in (False, True):
                    for glass in (False, True):
                        backend.settings.isDark = dark
                        script(f"WxTheme.glassEnabled = {str(glass).lower()}")
                        assert shell._visuals[:2] == (dark, glass)
                        for cycle in range(cycles + 1):
                            hidden = cycle == cycles
                            maximized = cycle == cycles - 1
                            backend.settings.sidebarCollapsed = cycle % 2 == 0
                            (window.showMaximized if maximized else window.showNormal)()
                            activate()
                            QTest.qWait(400)
                            label = f"{page}-{'dark' if dark else 'light'}-{'glass' if glass else 'solid'}-{cycle}"
                            reference = capture(label + "-before")
                            saved = invariant()
                            elapsed = backend.task.elapsedSeconds
                            hwnd = int(window.winId())
                            (window.hide if hidden else window.showMinimized)()
                            QTest.qWait(80)
                            (window.showMaximized if maximized else window.showNormal)()
                            activate()
                            QTest.qWait(160)
                            # No grabWindow, resize or extra update before either desktop capture.
                            immediate = capture(label + "-immediate")
                            QTest.qWait(500)
                            idle = capture(label + "-idle")
                            entry = {"scenario": label, "hidden": hidden, "maximized": maximized,
                                     "immediate": compare_colors(reference, immediate, dark),
                                     "idle": compare_colors(reference, idle, dark),
                                     "hwnd": int(window.winId()), "sameHandle": hwnd == int(window.winId()),
                                     "backdrop": shell.backdropAvailable, "opacity": window.opacity()}
                            assert invariant() == saved and backend.task.elapsedSeconds >= elapsed
                            assert shell.backdropAvailable and window.opacity() == 1 and window.isExposed()
                            report["restores"].append(entry)
                            if cycle == 0:
                                window.grabWindow().save(str(output / f"{label}-client-after.png"))
                        print(f"PASS {page} dark={dark} glass={glass}", flush=True)
                if page == "settings":
                    popup.close()
            window.showNormal()
            activate()
            QTest.qWait(400)
            reference = capture("surface-before")
            saved = invariant()
            saved_geometry = window.geometry()
            old_hwnd = int(window.winId())
            window.hide()
            window.destroy()
            QTest.qWait(100)
            window.create()
            window.showNormal()
            activate()
            QTest.qWait(160)
            immediate = capture("surface-immediate")
            QTest.qWait(500)
            idle = capture("surface-idle")
            report["surfaceRecreation"] = {
                "oldHwnd": old_hwnd, "newHwnd": int(window.winId()),
                "beforeGeometry": saved_geometry.getRect(), "afterGeometry": window.geometry().getRect(),
                "beforePixels": reference.size, "afterPixels": immediate.size,
                "immediate": compare_colors(reference, immediate, True, border_rounding=1),
                "idle": compare_colors(reference, idle, True, border_rounding=1)}
            assert window.geometry() == saved_geometry
            assert invariant() == saved and shell._hwnd == int(window.winId())
            assert shell.backdropAvailable
            fatal = [warning for warning in warnings if any(token in warning for token in
                     ("TypeError", "ReferenceError", "Unable to assign", "Cannot open", "Required property"))]
            assert not fatal, fatal
            report["warnings"] = warnings
            report["minimizeRestores"] = sum(not item["hidden"] for item in report["restores"])
            report["hiddenRestores"] = sum(item["hidden"] for item in report["restores"])
            print(json.dumps({key: value for key, value in report.items() if key != "restores"}))
        finally:
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            shell.detach()
            for window in engine.rootObjects():
                window.close()
            underlay.close()
            backend.shutdown()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/restore-fix/hardware")
    parser.add_argument("--cycles", type=int, default=5)
    args = parser.parse_args()
    assert args.cycles >= 1
    run(args.output.resolve(), args.cycles)
