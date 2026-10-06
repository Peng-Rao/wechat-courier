"""Capture the production contact page with real controllers and inert readers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from PySide6.QtCore import QMetaObject, QSettings, Qt, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from app.backend import BackendController
    from app.window_shell import WindowShellController, configure_native_renderer
    from tests.test_contact_controller import FakeReader, finish
    from tests.test_v3_controllers import FakeAgentClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/contact-refinement/native-100")
    parser.add_argument("--expected-dpr", type=float, default=1)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    configure_native_renderer()
    app = QGuiApplication([])
    with tempfile.TemporaryDirectory(prefix="contact-ui-") as directory:
        settings = QSettings(str(Path(directory) / "ui.ini"), QSettings.IniFormat)
        backend = BackendController(settings=settings, agent_client=FakeAgentClient())
        contacts = backend.contacts
        contacts._reader.eventReceived.disconnect(contacts._on_event)
        reader = FakeReader()
        contacts._reader = reader
        reader.eventReceived.connect(contacts._on_event)
        account = {"accountId": "mock", "label": "wxid_mock_account_with_a_long_name_0123456789",
                   "directory": "D:/示例数据/xwechat_files/mock", "contactDb": "D:/示例数据/contact.db"}
        contacts._discover = lambda _: [account]
        contacts.refreshAccounts()
        records = [{"username": f"wxid_mock_{index:04d}", "nick_name": f"示例联系人 {index:03d}",
                    "remark": f"示例备注 {index:03d}", "phone": "0013800000000" if index % 3 else "",
                    "alias": f"sample_{index:04d}", "description": "仅用于界面验收的虚构数据",
                    "category": "friend" if index <= 180 else "system"} for index in range(1, 201)]
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
        shell = WindowShellController()
        engine.rootContext().setContextProperty("backend", backend)
        engine.rootContext().setContextProperty("windowShell", shell)
        engine.load(QUrl.fromLocalFile(str(ROOT / "qml/main.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        assert abs(window.devicePixelRatio() - args.expected_dpr) < .01
        if app.platformName() == "windows":
            assert shell.attach(window)
        QTest.qWait(3000)
        root = window.findChild(QQuickItem, "appRoot")
        root.setProperty("workspaceIndex", 2)
        window.requestActivate()
        captures = []

        def find(name):
            return window.findChild(QQuickItem, name)

        def click(name):
            item = find(name)
            assert item is not None and item.isVisible() and item.isEnabled(), name
            QTest.mouseClick(window, Qt.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(40)

        def capture(name):
            QTest.mouseMove(window, window.contentItem().mapToScene(window.contentItem().boundingRect().topLeft()).toPoint())
            QTest.qWait(160)
            workspace = find("contactWorkspace")
            boxes = []
            for control in ("contactAccountSelector", "contactRefreshButton", "contactSearchContainer",
                            "contactSpecialCheckBox", "contactCountLabel", "contactReadButton",
                            "contactElevationButton", "contactStatusLabel", "contactElapsedLabel",
                            "contactExportButton", "contactCancelButton"):
                item = find(control)
                if not item.isVisible():
                    continue
                point = item.mapToItem(workspace, 0, 0)
                assert point.x() >= 0 and point.y() >= 0, (name, control)
                assert point.x() + item.width() <= workspace.width() + 1, (name, control)
                assert point.y() + item.height() <= workspace.height() + 1, (name, control)
                box = (point.x(), point.y(), item.width(), item.height())
                for other, previous in boxes:
                    overlap_x = min(box[0] + box[2], previous[0] + previous[2]) - max(box[0], previous[0])
                    overlap_y = min(box[1] + box[3], previous[1] + previous[3]) - max(box[1], previous[1])
                    assert overlap_x <= 1 or overlap_y <= 1, (name, control, other)
                boxes.append((control, box))
            assert find("contactAccountSelector").width() <= 280
            assert find("contactSearchContainer").width() <= 480
            table = find("contactTable")
            assert table.property("contentWidth") == max(table.width(), 1048)
            if table.width() >= 1048:
                assert not find("contactHorizontalScrollBar").isVisible()
            if contacts.totalCount == 0:
                assert find("contactEmptyState").isVisible()
                assert not find("contactVerticalScrollBar").isVisible()
            image = window.grabWindow()
            assert not image.isNull() and image.save(str(args.output / (name + ".png")))
            colors = {image.pixelColor(x, y).rgba() for x in range(0, image.width(), 40)
                      for y in range(0, image.height(), 40)}
            assert len(colors) > 6, name
            captures.append({"file": name + ".png", "width": image.width(), "height": image.height(),
                             "workspaceWidth": workspace.width(), "toolbarRows": 1 if workspace.width() >= 1152 else 2,
                             "records": contacts.totalCount})

        try:
            backend.settings.glassEnabled = False
            for dark in (False, True):
                backend.settings.isDark = dark
                theme = "dark" if dark else "light"
                for width, height in ((960, 680), (1320, 880), (1920, 1080)):
                    window.showNormal()
                    window.resize(width, height)
                    for collapsed in (False, True):
                        backend.settings.sidebarCollapsed = collapsed
                        contacts.clear()
                        capture(f"idle-{theme}-{width}-{'collapsed' if collapsed else 'expanded'}")
                        assert not find("contactElapsedLabel").isVisible()
                        click("contactReadButton")
                        finish(contacts, reader, records)
                        capture(f"loaded-{theme}-{width}-{'collapsed' if collapsed else 'expanded'}")
                window.showMaximized()
                capture(f"maximized-{theme}")

            window.showNormal()
            window.resize(1320, 880)
            backend.settings.sidebarCollapsed = True
            backend.settings.isDark = False
            contacts.clear()
            contacts._discover = lambda _: []
            contacts.refreshAccounts()
            capture("no-account")
            click("contactEmptyActionButton")
            assert find("contactSourcePanel").isVisible()
            capture("source-expanded")
            click("contactSourceToggleButton")
            contacts._discover = lambda _: [account]
            contacts.refreshAccounts()
            click("contactReadButton")
            reader.eventReceived.emit("contacts.progress", {"jobId": contacts._job_id, "stage": "keys"})
            capture("reading")
            finish(contacts, reader, success=False, code="ACCESS_DENIED")
            assert contacts.requiresElevation and find("contactElevationButton").isVisible()
            capture("permission-error")
            click("contactReadButton")
            finish(contacts, reader, records)
            contacts.keyword = "nonexistent-contact"
            capture("filtered-empty")
            click("contactEmptyActionButton")
            assert contacts.visibleCount == 180
            click("contactReadButton")
            capture("reread-preserves-data")
            click("contactCancelButton")
            assert reader.cancelled
            finish(contacts, reader, success=False, code="CANCELLED")
            assert contacts.totalCount == 200 and not find("contactEmptyState").isVisible()
            capture("cancel-preserves-data")
            click("contactReadButton")
            finish(contacts, reader, success=False, code="KEY_NOT_FOUND")
            assert contacts.totalCount == 200 and not find("contactEmptyState").isVisible()
            capture("failure-preserves-data")
            contacts._error = "读取失败：" + "较长的诊断说明，仅用于布局验收。" * 30
            contacts.stateChanged.emit()
            capture("long-error")
            backend.settings.glassEnabled = True
            capture("glass-enabled")
            fatal = [value for value in warnings if any(token in value for token in
                     ("TypeError", "ReferenceError", "Unable to assign", "Cannot open", "Required property", "QML Layout"))]
            assert not fatal, fatal
            report = {"dpr": window.devicePixelRatio(), "nativeFrame": shell.nativeFrameEnabled,
                      "realController": True, "realContacts": False, "agentStarted": False,
                      "captures": captures, "warnings": warnings}
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"screenshots": len(captures), "dpr": report["dpr"], "warnings": len(warnings)}))
        finally:
            backend.shutdown()
            shell.detach()
            window.close()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()
