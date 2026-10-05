"""Render the production QML with synthetic data and fake RPC only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from PySide6.QtCore import QObject, QSettings, QUrl, Qt, QMetaObject, QPointF
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from app.backend import BackendController
    from app.friend_import import load_friend_records
    from app.window_shell import WindowShellController, configure_native_renderer
    from tests.test_v3_controllers import FakeAgentClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "fuge-ui")
    parser.add_argument("--expected-dpr", type=float)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    configure_native_renderer()
    app = QGuiApplication([])
    if app.platformName() != "windows":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    with tempfile.TemporaryDirectory() as temporary:
        client = FakeAgentClient()
        backend = BackendController(settings=QSettings(str(Path(temporary) / "ui.ini"), QSettings.IniFormat), agent_client=client)
        backend.settings.glassEnabled = False
        backend.agent.applyInspection({"connected": True, "version": "4.1.13.65", "supported": True, "uiaReady": True})
        backend.message.recipientsText = "\n".join(f"示例联系人{i:03d}" for i in range(1, 61))
        backend.message.templateText = "{name}，你好！\n这是一份界面验收样例，不会发送到微信。"
        for path in (ROOT / "assets/fuge-logo-256.png", ROOT / "README.md"):
            backend.message.addFile(QUrl.fromLocalFile(str(path)).toString())
        backend.friends.batchLimit = 200
        backend.friends.model.replace_records(load_friend_records([
            ["姓名", "账号", "打招呼语"],
            *[[f"示例学员{i:03d}", f"wxid_sample_{i:04d}", "" if i % 2 else "你好，方便认识一下吗？"] for i in range(1, 201)]
        ]))
        backend.friends.model.selectRange(12, 24)
        # Freeze synthetic account discovery before loading the UI.
        backend.contacts._discover = lambda directory: []
        backend.contacts._directory = "D:/示例数据/xwechat_files"
        backend.contacts._accounts = [{"accountId": "sample-account", "label": "示例账号", "directory": "D:/示例数据/xwechat_files"}]
        backend.contacts._selected = "sample-account"
        backend.contacts.model.replace_records([
            {"nick_name": f"模拟联系人{i:03d}", "remark": f"模拟备注{i:03d}", "phone": "", "username": f"wxid_preview_{i:04d}",
             "alias": f"sample_{i:04d}", "description": "仅用于界面验收", "category": "friend"} for i in range(1, 87)
        ])
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
        shell = WindowShellController()
        engine.rootContext().setContextProperty("backend", backend)
        engine.rootContext().setContextProperty("windowShell", shell)
        engine.load(QUrl.fromLocalFile(str(ROOT / "qml/main.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        if args.expected_dpr is not None:
            assert abs(window.devicePixelRatio() - args.expected_dpr) < 0.01
        if app.platformName() == "windows":
            assert shell.attach(window)
        QTest.qWait(3000)
        startup = window.findChild(QQuickItem, "startupLoader")
        assert startup is not None and not startup.isVisible()
        root = window.findChild(QQuickItem, "appRoot")
        captures = []

        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name and item.isVisible():
                    return item
                pending.extend(item.childItems())
            return None

        def capture(name):
            QTest.mouseMove(window, QPointF(2, 2).toPoint())
            QTest.qWait(180)
            image = window.grabWindow()
            assert not image.isNull()
            colors = {image.pixelColor(x, y).rgba() for x in range(0, image.width(), 40) for y in range(0, image.height(), 40)}
            path = args.output / (name + ".png")
            assert image.save(str(path))
            assert len(colors) > 6, (name, len(colors), warnings)
            captures.append({"file": path.name, "width": image.width(), "height": image.height(), "distinctSampleColors": len(colors)})
            for control in ["startMessageButton", "startFriendsButton", "contactReadButton", "sidebarCollapseButton", "sidebarSettingsButton"]:
                item = find(control)
                if item is None:
                    continue
                point = item.mapToScene(item.boundingRect().center())
                assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, control, point)

        native_states = []
        if shell.nativeFrameEnabled:
            import ctypes
            def corner_preference():
                value = ctypes.c_int()
                result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    ctypes.c_void_p(int(window.winId())), 33, ctypes.byref(value), ctypes.sizeof(value))
                assert result == 0, result
                return value.value
            for state, action, expected in [("normal", window.showNormal, 2),
                                            ("maximized", window.showMaximized, 1),
                                            ("restored", window.showNormal, 2)]:
                action()
                QTest.qWait(300)
                actual = corner_preference()
                assert actual == expected, (state, actual)
                native_states.append({"state": state, "cornerPreference": actual})
            backend.settings.glassEnabled = True
            QTest.qWait(180)
            assert shell.backdropAvailable
            native_states.append({"state": "glass", "backdropAvailable": shell.backdropAvailable})
            backend.settings.glassEnabled = False
            window.resize(960, 680)
            window.setPosition(32, 32)
            window.requestActivate()
            QTest.qWait(300)
            if window.width() + window.x() <= window.screen().geometry().width() and window.height() + window.y() <= window.screen().geometry().height():
                for enabled, name in [(False, "native-rounded-frame.png"), (True, "native-glass-frame.png")]:
                    backend.settings.glassEnabled = enabled
                    QTest.qWait(300)
                    frame = window.screen().grabWindow(0, window.x(), window.y(), window.width(), window.height())
                    assert not frame.isNull() and frame.save(str(args.output / name))
                backend.settings.glassEnabled = False

        for dark in [False, True]:
            backend.settings.isDark = dark
            theme = "dark" if dark else "light"
            for width, height in [(1320, 880), (960, 680)]:
                window.setWidth(width); window.setHeight(height)
                for collapsed in [False, True]:
                    backend.settings.sidebarCollapsed = collapsed
                    for index, label in enumerate(["messages", "friends", "contacts"]):
                        root.setProperty("workspaceIndex", index)
                        if index < 2:
                            QTest.qWait(20)
                            workspace = find("messageWorkspace" if index == 0 else "friendWorkspace")
                            assert workspace is not None
                            QMetaObject.invokeMethod(workspace, "dismissMonitor")
                        capture(f"{label}-{theme}-{width}-{'collapsed' if collapsed else 'expanded'}")
                backend.settings.sidebarCollapsed = False
                popup = window.findChild(QObject, "settingsDialog")
                popup.setProperty("sectionIndex", 1)
                QMetaObject.invokeMethod(popup, "open")
                capture(f"settings-{theme}-{width}")
                editor = find("settingsFriendGreeting")
                assert editor is not None
                editor.forceActiveFocus()
                QMetaObject.invokeMethod(editor, "selectAll")
                point = editor.mapToScene(editor.boundingRect().center()).toPoint()
                QTest.mouseClick(window, Qt.RightButton, pos=point)
                menu = editor.findChild(QObject, "textEditMenu")
                QTest.qWait(300)
                assert menu is not None and menu.property("opened")
                capture(f"settings-menu-{theme}-{width}")
                QTest.keyClick(window, Qt.Key_Escape)
                QTest.qWait(200)
                assert not menu.property("opened")
                assert popup.property("opened"), "Escape closes the edit menu before its dialog"
                QMetaObject.invokeMethod(popup, "close")
                QTest.qWait(180)
            window.setWidth(1320); window.setHeight(880)
            for kind, start in [("message", backend.task.startMessage), ("friend", backend.task.startFriends)]:
                if kind == "friend":
                    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
                assert start(), backend.task.error
                payload = client.calls[-1][2]
                item = payload["items"][0]
                client.notificationReceived.emit("task.event", {"taskId": payload["taskId"], "itemId": item["itemId"], "step": "window_bound",
                    "outcome": "ok", "detail": "界面验收通知", "done": 0, "total": len(payload["items"]), "timestamp": "2026-10-06T02:01:00Z"})
                client.notificationReceived.emit("agent.status", {"taskId": payload["taskId"], "status": "waiting", "remaining": 12})
                for width, height in [(1320, 880), (960, 680)]:
                    window.setWidth(width); window.setHeight(height)
                    capture(f"monitor-{kind}-{theme}-{width}")
                client.notificationReceived.emit("task.finished", {"taskId": payload["taskId"], "outcome": "stopped"})
        fatal = [message for message in warnings if any(token in message for token in ["TypeError", "ReferenceError", "Unable to assign", "Cannot open", "Required property"])]
        assert not fatal, fatal
        report = {"qml": "qml/main.qml", "syntheticDataOnly": True, "devicePixelRatio": window.devicePixelRatio(),
                  "nativeFrame": shell.nativeFrameEnabled, "nativeWindowStates": native_states, "captures": captures, "warnings": warnings}
        (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"screenshots": len(captures), "warnings": len(warnings), "output": str(args.output)}))
        backend.shutdown()
        shell.detach()
        window.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
