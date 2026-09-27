"""Real QML fields against real QSettings-backed setters in an isolated GUI process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def exercise():
    from PySide6.QtCore import QObject, QUrl, Qt, QMetaObject, QPointF
    from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from tests.test_v3_controllers import make_backend

    app = QGuiApplication([])
    if os.name == "nt":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        app.setFont(QFont("Microsoft YaHei", 10))
    with tempfile.TemporaryDirectory() as directory:
        backend, client = make_backend(Path(directory))
        backend.friends.intervalMax = 15
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("testBackend", backend)
        engine.loadData(b'''import QtQuick
import QtQuick.Controls.Basic
import "qml/components"
ApplicationWindow {
    width: 960; height: 680; visible: true
    SettingsDialog { objectName: "dialog"; appBackend: testBackend; sectionIndex: 1 }
}''', QUrl.fromLocalFile(str(ROOT / "interval-test.qml")))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        popup = window.findChild(QObject, "dialog")
        low = popup.findChild(QQuickItem, "settingsFriendIntervalMin")
        high = popup.findChild(QQuickItem, "settingsFriendIntervalMax")
        assert low is not None and high is not None
        def invoke(obj, method):
            assert QMetaObject.invokeMethod(obj, method)
            QTest.qWait(50)
        def edit(field, text, enter=True):
            field.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(window, Qt.Key_Backspace)
            for character in text:
                QTest.keyClick(window, getattr(Qt, "Key_" + character.upper()))
            if enter:
                QTest.keyClick(window, Qt.Key_Return)
            QTest.qWait(30)
        def click_button(name):
            item = popup.findChild(QQuickItem, name)
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
            QTest.qWait(80)
        invoke(popup, "open")
        edit(low, "30")
        assert (backend.friends.intervalMin, backend.friends.intervalMax) == (30, 30)
        assert high.property("text") == "30"
        edit(high, "40", enter=False)
        click_button("settingsDoneButton")
        assert backend.friends.intervalMax == 40
        invoke(popup, "open")
        assert (low.property("text"), high.property("text")) == ("30", "40")
        edit(high, "5")
        assert low.property("text") == "5"
        edit(low, "1", enter=False)
        high.forceActiveFocus()
        QTest.qWait(40)
        assert backend.friends.intervalMin == 1
        edit(low, "", enter=False)
        high.forceActiveFocus()
        QTest.qWait(40)
        assert low.property("text") == "1"
        assert popup.property("intervalValidation")
        for invalid in ["0", "301", "invalid"]:
            low.setProperty("text", invalid)
            invoke(low, "commit")
            assert low.property("text") == "1"
        for key in [Qt.Key_Return, Qt.Key_Enter]:
            for invalid in ["", "0", "301"]:
                edit(low, invalid, enter=False)
                QTest.keyClick(window, key)
                QTest.qWait(30)
                assert low.property("text") == "1", (invalid, low.property("text"))
        edit(high, "300")
        click_button("settingsCloseButton")
        invoke(popup, "open")
        edit(low, "2", enter=False)
        QTest.keyClick(window, Qt.Key_Escape)
        QTest.qWait(60)
        assert not popup.property("opened")
        assert backend.friends.intervalMin == 2
        invoke(popup, "open")
        edit(low, "1")
        edit(low, "99", enter=False)
        backend.message.recipientsText = "Mock"
        backend.message.templateText = "mock-only"
        assert backend.task.startMessage()
        QTest.qWait(100)
        assert not popup.property("opened")
        assert backend.friends.intervalMin == 1
        assert backend.friends.intervalMax == 300
        reopened, _ = make_backend(Path(directory))
        assert (reopened.friends.intervalMin, reopened.friends.intervalMax) == (1, 300)
        payload = client.calls[-1][2]
        client.notificationReceived.emit("task.finished", {"taskId": payload["taskId"]})
        invoke(popup, "open")
        assert low.width() > 40 and high.width() > 40
        assert low.mapToScene(low.boundingRect().topLeft()).x() >= 0
        if os.environ.get("INTERVAL_SCREENSHOT"):
            window.grabWindow().save(os.environ["INTERVAL_SCREENSHOT"])
        invoke(popup, "close")
        window.close()
        engine.deleteLater()
        app.processEvents()


def test_settings_intervals_with_real_controller():
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software",
           "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--exercise"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    exercise()
