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
    read_stages = set()
    def observe_read(method, value):
        if method == "contacts.progress":
            read_stages.add(value.get("stage"))
    contacts._reader.eventReceived.connect(observe_read)
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
        assert contacts.sourceDirectory
        assert find("contactSourceField") is None
        click("contactSourceToggleButton")
        assert find("contactSourceField").property("text") == contacts.sourceDirectory
        click("contactDetectDirectoryButton")
        assert contacts.accounts and not contacts.busy
        assert find("contactSourceField").property("text") == contacts.sourceDirectory
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
        if live:
            import hashlib
            import threading
            import uuid
            import win32gui
            import win32process
            from app.contacts.native import Win32Probe, matching_processes

            def verify_wechat_responsive():
                processes = matching_processes(Win32Probe(), cancel=threading.Event(),
                                               deadline=time.monotonic() + 5)
                pids = {process.pid for process in processes}
                handles = []
                def collect(hwnd, _):
                    if (win32process.GetWindowThreadProcessId(hwnd)[1] in pids and
                            win32gui.GetClassName(hwnd) == "Qt51514QWindowIcon" and
                            not win32gui.GetWindow(hwnd, 4)):
                        handles.append(hwnd)
                win32gui.EnumWindows(collect, None)
                assert handles, "verified WeChat main window not found"
                for hwnd in handles:
                    assert win32gui.IsWindowEnabled(hwnd), "WeChat main window disabled"
                    win32gui.SendMessageTimeout(hwnd, 0, 0, 0, 2, 250)

            counts, diagnostics = [contacts.totalCount], [contacts.diagnostics]
            assert counts[0] > 0, "no contact records returned"
            verify_wechat_responsive()
            for _ in range(2):
                click("contactReadButton")
                assert contacts.busy and backend.operationBusy
                assert not backend.task.startFriends() and not backend.task.startMessage()
                wait_done()
                assert contacts.phase == "ready", contacts.errorMessage
                assert not contacts._reader.processRunning
                counts.append(contacts.totalCount)
                diagnostics.append(contacts.diagnostics)
                verify_wechat_responsive()
            assert len(set(counts)) == 1, "independent contact reads returned different counts"
            ordinary_count = contacts.visibleCount
            click("contactSpecialCheckBox")
            assert contacts.visibleCount >= ordinary_count
            click("contactSpecialCheckBox")
            assert contacts.visibleCount == ordinary_count
            query = "fuge-contact-no-match-" + uuid.uuid4().hex
            search = find("contactSearchField")
            search.forceActiveFocus()
            for char in query:
                QTest.keyClick(window, Qt.Key(ord(char.upper())), Qt.NoModifier)
            QTest.qWait(100)
            assert contacts.visibleCount == 0 and not find("contactExportButton").isEnabled()
            QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(window, Qt.Key_Backspace)
            QTest.qWait(100)
            assert contacts.visibleCount == ordinary_count
            click("contactReadButton")
            click("contactCancelButton")
            wait_done(10)
            assert contacts.phase == "cancelled" and contacts.canRead
            assert contacts.totalCount == counts[0], "cancel replaced the previous valid table"
            verify_wechat_responsive()
            click("contactReadButton")
            wait_done()
            assert contacts.phase == "ready", contacts.errorMessage
            assert contacts.totalCount == counts[0]
            verify_wechat_responsive()
            click("contactClearButton")
            assert contacts.totalCount == contacts.visibleCount == 0 and contacts.diagnostics == {}
            assert not backend.operationBusy
            assert {"process", "snapshot", "keys", "validating", "contacts", "complete"} <= read_stages
            assert not any("Required property" in value or "TypeError" in value
                or "Unable to assign" in value for value in warnings), "QML warnings detected"
            root = Path(__file__).resolve().parents[1]
            digest = hashlib.sha256()
            for module in ("app/contacts/native.py", "app/contacts/wcdb.py", "app/contacts/reader.py",
                           "app/contacts/diagnostics.py", "app/contacts/main.py", "app/contacts/controller.py",
                           "app/contacts/client.py", "qml/components/ContactWorkspace.qml"):
                digest.update(module.encode())
                digest.update((root / module).read_bytes())
            report = {"entrypoint": "QML controls -> BackendController -> Named Pipe -> independent reader",
                      "live": True, "independentReadCounts": counts, "cancelled": True, "reread": True,
                      "filtered": True, "cleared": True, "wechatResponsive": True,
                      "realContactExports": False, "contactsLogged": False, "automationAgentStarted": False,
                      "sourceFingerprint": "sha256:" + digest.hexdigest(), "diagnostics": diagnostics,
                      "warnings": len(warnings)}
            (output / "live-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
            return
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
            assert table.property("contentWidth") == max(table.width(), 1048)
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
            click("contactExportButton")
            assert find("contactExportCountLabel").property("text") == "10 位联系人"
            click("contactExportCancelButton")
            assert not contacts.busy
            click("contactClearSearchButton")
            assert contacts.keyword == "" and contacts.visibleCount == 80
            click("contactSpecialCheckBox")
            assert contacts.visibleCount == 90
            assert window.grabWindow().save(str(output / "contacts-loaded-960.png"))
        contacts.keyword = "Nick05"
        QTest.qWait(100)
        snapshot = contacts.model.snapshot()
        assert len(snapshot) == 10 and contacts.totalCount == 90, "exports must use the current filter"
        assert snapshot, "empty selected contact view"
        # Exercise the actual export control and accepted file dialog path.
        formats = ["xlsx", "csv", "json"]
        dialog = window.findChild(QObject, "contactSaveDialog")
        # Non-native dialog keeps offscreen input in this Qt event loop.
        dialog.setProperty("options", 4 | 8)
        for index, fmt in enumerate(formats):
            click("contactExportButton")
            selector = window.findChild(QObject, "contactFormatSelector")
            selector.setProperty("currentIndex", index)
            click("contactExportConfirmButton")
            destination = output / ("contacts." + fmt)
            dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(destination)))
            assert QMetaObject.invokeMethod(dialog, "accepted")
            assert QMetaObject.invokeMethod(dialog, "close")
            QTest.qWait(40)
            if window.findChild(QObject, "contactOverwriteDialog").property("visible"):
                click("contactOverwriteConfirmButton")
            wait_done()
            assert destination.exists(), contacts.errorMessage
        click("contactExportButton")
        window.findChild(QObject, "contactFormatSelector").setProperty("currentIndex", 3)
        click("contactExportConfirmButton")
        folder = window.findChild(QObject, "contactExportFolderDialog")
        folder.setProperty("options", 8)
        folder.setProperty("selectedFolder", QUrl.fromLocalFile(str(output)))
        assert QMetaObject.invokeMethod(folder, "accepted")
        assert QMetaObject.invokeMethod(folder, "close")
        QTest.qWait(40)
        if window.findChild(QObject, "contactOverwriteDialog").property("visible"):
            click("contactOverwriteConfirmButton")
        wait_done()
        assert len(contacts.lastExportPaths) == 3
        json_rows = json.loads((output / "contacts.json").read_text(encoding="utf-8"))
        with (output / "contacts.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.reader(stream))
        from openpyxl import load_workbook
        workbook = load_workbook(output / "contacts.xlsx", read_only=True)
        xlsx_rows = list(workbook.active.values)
        workbook.close()
        assert len(json_rows) == len(csv_rows) - 1 == len(xlsx_rows) - 1 == len(snapshot)
        assert json_rows[0] == {field: snapshot[0][field] for field in CONTACT_FIELDS}
        assert all("Nick05" in row["nick_name"] for row in json_rows)
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


def test_read_only_live_acceptance_never_deletes_existing_exports(tmp_path):
    originals = {tmp_path / ("contacts." + fmt): ("existing-" + fmt).encode()
                 for fmt in ("csv", "json", "xlsx")}
    for path, content in originals.items():
        path.write_bytes(content)
    code = ("from pathlib import Path; import sys; from app.contacts import reader; "
            "reader.discover_accounts=lambda _: []; "
            "from tests.test_contact_gui import exercise_gui; "
            "exercise_gui(Path(sys.argv[1]), live=True)")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    assert result.returncode != 0 and "no local accounts discovered" in result.stderr
    assert all(path.is_file() and path.read_bytes() == content for path, content in originals.items())


if __name__ == "__main__":
    live = "--live" in sys.argv
    if live and os.environ.get("WECHAT_CONTACT_ACCEPTANCE") != "1":
        raise SystemExit("Live contact acceptance requires an explicit opt-in")
    exercise_gui(Path(sys.argv[1]), live)
