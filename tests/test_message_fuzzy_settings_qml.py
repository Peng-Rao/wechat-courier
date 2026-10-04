"""Exercise the settings switch with real controllers and an inert Agent client."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def exercise(kind):
    from PySide6.QtCore import QObject, QUrl, Qt, QMetaObject, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from tests.test_message_fuzzy_settings import start_task, finish_task, KEY
    from tests.test_v3_controllers import make_backend, settings

    app = QGuiApplication([])
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        backend, client = make_backend(path)
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty("testBackend", backend)
        engine.loadData(b'''import QtQuick
import QtQuick.Controls.Basic
import "qml/components"
ApplicationWindow {
    width: 960; height: 680; visible: true
    SettingsDialog { objectName: "dialog"; appBackend: testBackend; sectionIndex: 0 }
}''', QUrl.fromLocalFile(str(ROOT / "fuzzy-settings-test.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        popup = window.findChild(QObject, "dialog")
        switch = popup.findChild(QQuickItem, "settingsMessageFuzzySearch")
        row = popup.findChild(QQuickItem, "settingsMessageFuzzySearchRow")
        assert switch is not None, "message fuzzy search switch is missing"
        assert row is not None
        assert row.property("title") == "\u6a21\u7cca\u641c\u7d22\uff08\u53d6\u9996\u4e2a\u7ed3\u679c\uff09"

        def invoke(obj, method):
            assert QMetaObject.invokeMethod(obj, method)
            QTest.qWait(60)

        def click_switch():
            point = switch.mapToScene(QPointF(switch.width() / 2, switch.height() / 2))
            QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
            QTest.qWait(50)

        try:
            invoke(popup, "open")
            assert switch.property("visible") and switch.property("enabled")
            assert switch.property("checked") is False
            assert not settings(path).contains(KEY)
            popup.setProperty("sectionIndex", 1)
            QTest.qWait(50)
            assert not switch.property("visible")
            popup.setProperty("sectionIndex", 0)
            QTest.qWait(50)
            assert switch.property("visible")
            click_switch()
            assert backend.message.fuzzySearchEnabled is True
            assert settings(path).value(KEY, False, type=bool) is True
            click_switch()
            assert backend.message.fuzzySearchEnabled is False
            switch.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(50)
            assert backend.message.fuzzySearchEnabled is True
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(50)
            assert backend.message.fuzzySearchEnabled is False
            backend.message.fuzzySearchEnabled = True
            QTest.qWait(50)
            assert switch.property("checked") is True
            invoke(popup, "close")
            invoke(popup, "open")
            assert switch.property("checked") is True

            for width, height in [(960, 680), (800, 600)]:
                window.setWidth(width)
                window.setHeight(height)
                QTest.qWait(80)
                assert switch.property("visible")
                point = switch.mapToScene(QPointF(0, 0))
                assert point.x() >= 0 and point.y() >= 0
                assert point.x() + switch.width() <= window.width()
                assert point.y() + switch.height() <= window.height()
                assert not window.grabWindow().isNull()

            payload = start_task(backend, client, kind)
            QTest.qWait(80)
            assert popup.property("interactionLocked") is True
            assert not popup.property("opened")
            assert not switch.property("enabled")
            checked_before = switch.property("checked")
            invoke(switch, "toggled")
            backend.message.fuzzySearchEnabled = False
            assert backend.message.fuzzySearchEnabled is True
            assert settings(path).value(KEY, False, type=bool) is True
            assert switch.property("checked") is checked_before
            if kind == "message_send":
                assert payload["options"]["fuzzySearchEnabled"] is True
            else:
                assert "fuzzySearchEnabled" not in payload["options"]
            finish_task(client, payload)
            invoke(popup, "open")
            assert switch.property("enabled")
            click_switch()
            assert backend.message.fuzzySearchEnabled is False
            assert settings(path).value(KEY, True, type=bool) is False
            assert not warnings, warnings
        finally:
            backend.shutdown()
            window.close()
            engine.deleteLater()
            app.processEvents()


@pytest.mark.parametrize("kind", ["message_send", "friend_add"])
def test_fuzzy_settings_switch_with_real_controller(kind):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software",
           "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--exercise", kind],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    exercise(sys.argv[2])
