"""Full third workspace with real controllers, process transport and file jobs."""
import os
from pathlib import Path
import subprocess
import sys


def exercise_gui(output, live=False):
    output = output.resolve()
    import csv
    import json
    import time
    from PySide6.QtCore import QObject, QMetaObject, QSettings, Qt, QUrl
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from app.backend import BackendController
    from app.contacts.client import ContactReaderClient
    from app.contacts.data import CONTACT_FIELDS
    from tests.test_v3_controllers import FakeAgentClient
    from app.window_shell import configure_native_renderer

    output.mkdir(parents=True, exist_ok=True)
    configure_native_renderer()
    app = QGuiApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 10))
    backend = BackendController(settings=QSettings(str(output / "gui.ini"), QSettings.IniFormat),
                                agent_client=FakeAgentClient())
    backend.settings.glassEnabled = False
    contacts = backend.contacts
    if not live:
        old = contacts._reader
        old.eventReceived.disconnect(contacts._on_event)
        code = ("from app.contacts.main import main; main(reader=lambda a,**kw: "
            "[{'username':'wxid_fixture_%03d'%i,'nick_name':'Nick%03d'%i,'phone':'00138',"
            "'category':'friend' if i<80 else 'system'} for i in range(90)])")
        contacts._reader = ContactReaderClient(contacts, command=[sys.executable, "-c", code],
                                              bootstrap_root=output / "bootstrap")
        contacts._reader.eventReceived.connect(contacts._on_event)
        contacts._discover = lambda _: [{"accountId": "fixture", "label": "Fixture account",
            "directory": str(output), "contactDb": str(output / "contact.db")}]
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    engine.rootContext().setContextProperty("backend", backend)
    engine.loadData(b'''import QtQuick
import "components"
Window {
    id: host
    width: 1320; height: 880; visible: true; title: backend.versionInfo
    WxTitleBar { id: title; width: parent.width; window: host; titleBackend: backend }
    App { anchors.top: title.bottom; anchors.bottom: parent.bottom; width: parent.width; appBackend: backend }
}''', QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "qml" / "contact-test.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]

    def find(name, item=None):
        item = item or window.contentItem()
        if not item.isVisible(): return None
        if item.objectName() == name: return item
        for child in item.childItems():
            found = find(name, child)
            if found is not None: return found
        return None

    def click(name, double=False):
        item = find(name)
        assert item is not None and item.isEnabled(), name
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), name
        (QTest.mouseDClick if double else QTest.mouseClick)(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(60)

    def wait_done(seconds=70):
        until = time.monotonic() + seconds
        while contacts.busy and time.monotonic() < until:
            QTest.qWait(20)
            time.sleep(.005)
        assert not contacts.busy, "operation deadline exceeded"

    try:
        QTest.qWait(300)
        click("contactWorkspaceTab")
        click("contactRefreshButton")
        assert contacts.accounts, "no local accounts discovered"
        if not live:
            for width, height in ((1320, 880), (960, 680)):
                window.setWidth(width); window.setHeight(height)
                QTest.qWait(150)
                assert window.grabWindow().save(str(output / f"contacts-empty-{width}.png"))
        click("contactReadButton")
        assert contacts.busy and backend.operationBusy
        assert not backend.task.startFriends()
        wait_done()
        assert contacts.phase == "ready", contacts.errorMessage
        QTest.qWait(180)
        if not live:
            assert contacts.visibleCount == 80 and contacts.totalCount == 90
            table = find("contactTable")
            until = time.monotonic() + 3
            while find("contactVerticalScrollBar").property("size") >= 1 and time.monotonic() < until:
                QTest.qWait(40)
                time.sleep(.005)
            assert find("contactVerticalScrollBar").property("size") < 1, (
                table.property("rows"), table.property("contentHeight"), table.height(),
                table.property("model"), warnings)
            assert find("contactHorizontalScrollBar").property("size") < 1
            click("contactHeader-0")
            click("contactCell-0-0", double=True)
            assert app.clipboard().text() == contacts.model.text(0, 0)
            app.clipboard().setText("automation-clipboard")
            backend.task._set_active(True)
            QTest.qWait(50)
            contacts.copyCell(0, 0)
            click("contactCell-0-0", double=True)
            assert app.clipboard().text() == "automation-clipboard"
            assert not find("contactExportButton").isEnabled()
            backend.task._set_active(False)
            search = find("contactSearchField")
            search.forceActiveFocus()
            for char in "Nick05":
                QTest.keyClick(window, Qt.Key(ord(char.upper())),
                    Qt.ShiftModifier if char.isupper() else Qt.NoModifier)
            QTest.qWait(100)
            assert contacts.visibleCount == 10
            QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(window, Qt.Key_Backspace)
            click("contactSpecialCheckBox")
            assert contacts.visibleCount == 90
            assert window.grabWindow().save(str(output / "contacts-loaded-960.png"))
        snapshot = contacts.model.snapshot()
        assert snapshot, "empty selected contact view"
        # Exercise the actual export control and accepted file dialog path.
        formats = ["xlsx", "csv", "json"]
        dialog = window.findChild(QObject, "contactSaveDialog")
        # Non-native dialog keeps offscreen input in this Qt event loop.
        dialog.setProperty("options", 4 | 8)
        for index, fmt in enumerate(formats):
            selector = window.findChild(QObject, "contactFormatSelector")
            selector.setProperty("currentIndex", index)
            click("contactExportButton")
            destination = output / ("contacts." + fmt)
            dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(destination)))
            assert QMetaObject.invokeMethod(dialog, "accepted")
            assert QMetaObject.invokeMethod(dialog, "close")
            QTest.qWait(40)
            if window.findChild(QObject, "contactOverwriteDialog").property("visible"):
                click("contactOverwriteConfirmButton")
            wait_done()
            assert destination.exists(), contacts.errorMessage
        json_rows = json.loads((output / "contacts.json").read_text(encoding="utf-8"))
        with (output / "contacts.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.reader(stream))
        from openpyxl import load_workbook
        workbook = load_workbook(output / "contacts.xlsx", read_only=True)
        xlsx_rows = list(workbook.active.values)
        workbook.close()
        assert len(json_rows) == len(csv_rows) - 1 == len(xlsx_rows) - 1 == len(snapshot)
        assert json_rows[0] == {field: snapshot[0][field] for field in CONTACT_FIELDS}
        assert not backend.operationBusy
        click("contactReadButton")
        click("contactCancelButton")
        wait_done(10)
        assert contacts.phase == "cancelled"
        click("contactReadButton")
        wait_done()
        assert contacts.phase == "ready"
        assert not any("Required property" in value or "TypeError" in value
            or "Unable to assign" in value for value in warnings), warnings
        print(json.dumps({"live": live, "records": len(snapshot), "formats": formats,
                          "cancelled": True, "reread": True, "warnings": len(warnings)}))
    finally:
        if live:
            for fmt in ("csv", "json", "xlsx"):
                (output / ("contacts." + fmt)).unlink(missing_ok=True)
        backend.shutdown()
        window.close()
        engine.deleteLater()
        app.processEvents()


def test_contact_workspace_real_controller_and_process(tmp_path):
    try:
        result = subprocess.run([sys.executable, "-m", "tests.test_contact_gui", str(tmp_path)],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
    except subprocess.TimeoutExpired as error:
        import pytest
        pytest.fail(str(error.stderr))
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    live = "--live" in sys.argv
    if live and os.environ.get("WECHAT_CONTACT_ACCEPTANCE") != "1":
        raise SystemExit("Live contact acceptance requires an explicit opt-in")
    exercise_gui(Path(sys.argv[1]), live)
