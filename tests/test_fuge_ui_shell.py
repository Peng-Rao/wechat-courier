"""Brand shell preferences and actual QML interactions, without WeChat access."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QSettings
from tests.test_v3_controllers import make_backend

ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_preference_defaults_and_persists(tmp_path, qapp):
    backend, _ = make_backend(tmp_path)
    assert backend.settings.sidebarCollapsed is False
    changes = []
    backend.settings.sidebarCollapsedChanged.connect(changes.append)
    backend.settings.sidebarCollapsed = True
    backend.settings.sidebarCollapsed = True
    assert changes == [True]
    restored, _ = make_backend(tmp_path)
    assert restored.settings.sidebarCollapsed is True
    assert QSettings(str(tmp_path / "v3.ini"), QSettings.IniFormat).value("ui/sidebarCollapsed", type=bool)


@pytest.mark.parametrize("value", ["broken", "", 12, "null"])
def test_damaged_sidebar_preference_defaults_to_expanded(tmp_path, qapp, value):
    store = QSettings(str(tmp_path / "v3.ini"), QSettings.IniFormat)
    store.setValue("ui/sidebarCollapsed", value)
    store.sync()
    backend, _ = make_backend(tmp_path)
    assert backend.settings.sidebarCollapsed is False


def exercise():
    import tempfile
    from PySide6.QtCore import QObject, QUrl, Qt, QMetaObject, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    app = QGuiApplication([])
    with tempfile.TemporaryDirectory() as directory:
        backend, client = make_backend(Path(directory))
        backend.message.recipientsText = "Mock"
        backend.message.templateText = "Not sent"
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("testBackend", backend)
        engine.loadData(b'''import QtQuick
import QtQuick.Controls.Basic
import "qml"
ApplicationWindow {
    width: 960; height: 680; visible: true
    App { anchors.fill: parent; appBackend: testBackend }
}''', QUrl.fromLocalFile(str(ROOT / "shell-test.qml")))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        root = window.findChild(QQuickItem, "appRoot")
        assert root is not None
        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    return item
                pending.extend(item.childItems())
            return window.findChild(QQuickItem, name)
        def click(name):
            item = find(name)
            assert item is not None, name
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
            QTest.qWait(100)
        sidebar = window.findChild(QQuickItem, "workspaceSidebar")
        assert sidebar is not None
        body = window.findChild(QQuickItem, "workspaceContentSurface")
        assert body is not None and body.property("color").alpha() == 255
        assert root.property("color").alpha() == 0, "The navigation glass must not have an opaque layer behind it"
        assert round(sidebar.width()) == 216
        click("sidebarCollapseButton")
        assert backend.settings.sidebarCollapsed
        assert round(sidebar.width()) == 64
        click("friendWorkspaceTab")
        assert root.property("workspaceIndex") == 1
        click("messageWorkspaceTab")
        assert backend.message.templateText == "Not sent"
        assert root.property("workspaceIndex") == 0
        click("sidebarSettingsButton")
        popup = window.findChild(QObject, "settingsDialog")
        assert popup is not None and popup.property("opened")
        assert backend.task.startMessage()
        QTest.qWait(100)
        assert not popup.property("opened")
        click("sidebarSettingsButton")
        assert popup.property("opened"), "Appearance remains accessible during tasks"
        QTest.mouseClick(window, Qt.LeftButton, pos=find("settingsSection3").mapToScene(QPointF(40, 16)).toPoint())
        QTest.qWait(50)
        click("settingsDarkModeButton")
        assert backend.settings.isDark
        assert not window.findChild(QQuickItem, "settingsFriendIntervalMin").isEnabled()
        assert QMetaObject.invokeMethod(popup, "close")
        client.notificationReceived.emit("task.finished", {"taskId": client.calls[-1][2]["taskId"]})
        for section, name, dirty in [(0, "settingsMessageIntervalMin", "9"),
                                     (0, "settingsMessageIntervalMax", "55"),
                                     (1, "settingsFriendGreeting", "unsaved-greeting"),
                                     (1, "settingsFriendBatchLimit", "333"),
                                     (2, "settingsAgentRestartLimit", "0"),
                                     (2, "settingsLoginTimeout", "33")]:
            popup.setProperty("sectionIndex", section)
            assert QMetaObject.invokeMethod(popup, "open")
            QTest.qWait(100)
            control = find(name)
            assert control is not None, name
            field = control.property("contentItem") if control.metaObject().className().startswith("WxSpinInput") else control
            saved_text = field.property("text")
            field.forceActiveFocus()
            field.setProperty("text", dirty)
            assert backend.task.startMessage()
            QTest.qWait(100)
            assert not popup.property("opened")
            client.notificationReceived.emit("task.finished", {"taskId": client.calls[-1][2]["taskId"]})
            assert QMetaObject.invokeMethod(popup, "open")
            QTest.qWait(100)
            assert field.property("text") == saved_text, (name, saved_text, field.property("text"))
            QMetaObject.invokeMethod(popup, "close")
        window.close()
        engine.deleteLater()
        app.processEvents()


def test_actual_sidebar_and_active_appearance_settings():
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software", "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--exercise"], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def exercise_layout(case):
    import tempfile
    from PySide6.QtCore import QUrl, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    with tempfile.TemporaryDirectory() as directory:
        backend, _ = make_backend(Path(directory))
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("testBackend", backend)
        engine.loadData(b'''import QtQuick
import QtQuick.Controls.Basic
import "qml"
ApplicationWindow {
    width: 1320; height: 880; visible: true
    App { anchors.fill: parent; appBackend: testBackend; workspaceIndex: 1 }
}''', QUrl.fromLocalFile(str(ROOT / "layout-test.qml")))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]

        def items(parent=None):
            pending = [parent or window.contentItem()]
            while pending:
                item = pending.pop()
                yield item
                pending.extend(item.childItems())

        def find(name):
            return next(item for item in items() if item.objectName() == name)

        def text_item(value):
            return next(item for item in items() if item.isVisible() and item.property("text") == value)

        def center(item):
            return item.mapToScene(QPointF(item.width() / 2, item.height() / 2))

        for width, height in [(1320, 880), (960, 680)]:
            window.resize(width, height)
            for collapsed in [True, False]:
                backend.settings.sidebarCollapsed = collapsed
                for dark in [False, True]:
                    backend.settings.isDark = dark
                    QTest.qWait(80)
                    if case == "sidebar":
                        sidebar = find("workspaceSidebar")
                        buttons = [find(name) for name in ["sidebarCollapseButton", "messageWorkspaceTab",
                                   "friendWorkspaceTab", "contactWorkspaceTab", "sidebarSettingsButton"]]
                        buttons.append(next(item for item in items(sidebar) if item.property("iconName") in ("moon", "sun")))
                        icons = [next(item for item in items(button) if item.property("iconSource")) for button in buttons]
                        assert all(round(button.height()) == 42 for button in buttons)
                        assert all(icon.property("iconSize") == 18 for icon in icons)
                        if collapsed:
                            assert all(abs(center(icon).x() - center(sidebar).x()) < 1 for icon in icons), [center(icon).x() for icon in icons]
                        else:
                            assert max(center(icon).x() for icon in icons[1:]) - min(center(icon).x() for icon in icons[1:]) < 1
                    else:
                        status = text_item("等待开始")
                        interval = next(item for item in items() if item.isVisible() and isinstance(item.property("text"), str)
                                        and "随机间隔 15–30 秒" in item.property("text"))
                        status_x = status.mapToScene(QPointF()).x()
                        interval_x = interval.mapToScene(QPointF()).x()
                        assert abs(status_x - interval_x) < 1, (status_x, interval_x)
                        button = find("startFriendsButton")
                        warning = text_item("将实际提交好友申请")
                        assert warning.mapToScene(QPointF()).x() >= status_x
                        assert warning.mapToScene(QPointF(warning.width(), 0)).x() + 12 <= button.mapToScene(QPointF()).x()
                        for item in (status, interval, warning, button):
                            top_left = item.mapToScene(QPointF())
                            bottom_right = item.mapToScene(QPointF(item.width(), item.height()))
                            assert 0 <= top_left.x() < bottom_right.x() <= width
                            assert 0 <= top_left.y() < bottom_right.y() <= height
        backend.shutdown()
        window.close()
        engine.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("case", ["sidebar", "footer"])
def test_actual_sidebar_and_friend_footer_alignment(case):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software", "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--layout", case], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    if "--layout" in sys.argv:
        exercise_layout(sys.argv[-1])
    else:
        exercise()
