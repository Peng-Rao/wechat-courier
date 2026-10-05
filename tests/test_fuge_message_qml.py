"""Message workspace interactions with real controllers and an inert Agent."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def exercise(scenario):
    from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl
    from PySide6.QtGui import QAccessible, QColor, QFont, QFontDatabase, QGuiApplication, QImage
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlProperty
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from tests.test_v3_controllers import make_backend

    app = QGuiApplication([])
    if os.name == "nt":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyhbd.ttc")
        app.setFont(QFont("Microsoft YaHei UI"))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        backend, client = make_backend(path)
        backend.message.recipientsText = "Alice\n Bob \nAlice"
        backend.message.templateText = "{name}, hello"
        if scenario == "locked_on_load":
            assert backend.task.startMessage()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty("testBackend", backend)
        engine.loadData(b'''import QtQuick
import QtQuick.Controls.Basic
import "qml/components"
import "qml/theme"
ApplicationWindow {
    width: 1200; height: 780; visible: true
    color: WxTheme.clBgWindow
    Binding { target: WxTheme; property: "isDark"; value: testBackend.settings.isDark }
    MessageWorkspace { objectName: "messageWorkspace"; anchors.fill: parent; appBackend: testBackend }
}''', QUrl.fromLocalFile(str(ROOT / "fuge-message-test.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        workspace = window.findChild(QQuickItem, "messageWorkspace")
        QTest.qWait(100)
        capture_dir = Path(tempfile.gettempdir()) / "fuge-message-qml-20261006"
        capture_dir.mkdir(exist_ok=True)

        def find(name, required=True):
            item = workspace.findChild(QObject, name)
            if item is None:
                def walk(parent):
                    if parent.objectName() == name:
                        return parent
                    for child in parent.childItems():
                        found = walk(child)
                        if found is not None:
                            return found
                    return None
                item = walk(workspace)
            if required:
                assert item is not None, f"Missing message UI: {name}"
            return item

        def click(item, button=Qt.LeftButton):
            if isinstance(item, str):
                item = find(item)
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            QTest.mouseClick(window, button, pos=point.toPoint())
            QTest.qWait(60)

        def invoke(item, method, *args):
            assert QMetaObject.invokeMethod(item, method, *args), method
            QTest.qWait(40)

        def select_all(item):
            item.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
            QTest.qWait(30)

        def finish():
            payload = client.calls[-1][2]
            client.notificationReceived.emit("task.finished", {
                "taskId": payload["taskId"], "outcome": "stopped", "done": 0,
                "total": len(payload["items"]),
            })
            QTest.qWait(60)
            invoke(workspace, "dismissMonitor")

        try:
            if scenario == "layout":
                title = find("messagePageTitle")
                assert title.property("text") == "\u6d88\u606f\u7fa4\u53d1"
                assert title.property("font").pixelSize() == 20
                assert title.property("font").family() == "Microsoft YaHei UI"
                editor = find("messageEditorScrollView")
                preview = find("messagePreviewPane")
                assert editor.width() / (editor.width() + preview.width()) == pytest.approx(0.53, abs=0.005)
                mode = find("messageSearchMode")
                assert mode.property("text") == "\u7cbe\u786e\u641c\u7d22"
                assert mode.mapToScene(QPointF(mode.width(), 0)).x() == pytest.approx(window.width() - 24, abs=1)
                backend.message.fuzzySearchEnabled = True
                QTest.qWait(40)
                assert mode.property("text") == "\u6a21\u7cca\u641c\u7d22\uff08\u53d6\u9996\u4e2a\u7ed3\u679c\uff09"
                assert find("startMessageButton").height() == 36
                assert find("messageAddFileButton").height() == 36
                assert find("messageRecipientCount").property("text") == "2 \u4eba"
                assert find("messagePreviewText").property("text") == "Alice, hello"
                assert find("messagePreviewTarget").property("text") == "Alice"
                assert find("messagePreviewToolbar", required=False) is None
                for name in ("messageRecipientsInput", "messageTemplateInput"):
                    field = find(name)
                    assert field.property("font").pixelSize() == 14
                    assert field.property("font").family() == "Microsoft YaHei UI"
                assert find("messageRecipientsSurface").property("color").alpha() == 255
                assert find("messageTemplateSurface").property("color").alpha() == 255
                for width, height in [(1104, 780), (744, 600), (800, 600), (640, 480)]:
                    window.setWidth(width)
                    window.setHeight(height)
                    QTest.qWait(80)
                    body = find("messageBodyScrollView")
                    if width < 744:
                        assert body.property("contentWidth") > body.width(), "Narrow workspace must scroll, not shrink"
                    else:
                        assert body.property("contentWidth") <= body.width(), "Both panes must fit at the supported minimum size"
                    assert title.property("font").pixelSize() == 20
                    assert find("messageTemplateInput").property("font").pixelSize() == 14
                    assert editor.width() >= 350 and preview.width() >= 300
                    horizontal = find("messageBodyHorizontalScrollBar")
                    assert window.grabWindow().save(str(capture_dir / f"message-{width}-left.png"))
                    horizontal.setProperty("position", 1 - horizontal.property("size"))
                    QTest.qWait(80)
                    preview_point = preview.mapToScene(QPointF(preview.width(), 0))
                    assert preview_point.x() <= window.width() + 1
                    assert not window.grabWindow().isNull()
                    assert window.grabWindow().save(str(capture_dir / f"message-{width}-right.png"))
                backend.settings.isDark = True
                QTest.qWait(60)
                assert find("messageRecipientsSurface").property("color").alpha() == 255
                assert find("messageTemplateSurface").property("color").alpha() == 255
                assert window.grabWindow().save(str(capture_dir / "message-dark-640.png"))

            elif scenario == "editors":
                recipients = find("messageRecipientsInput")
                template = find("messageTemplateInput")
                recipients.setProperty("text", "Carol\n Carol \nDave")
                assert backend.message.recipients() == ["Carol", "Dave"]
                template.setProperty("text", "Hello ")
                template.setProperty("cursorPosition", 6)
                click("insertMessageNamePlaceholder")
                assert backend.message.templateText == "Hello {name}"
                assert backend.message.previewMessage == "Hello Carol"
                backend.message.templateText = "Changed {name}"
                QTest.qWait(40)
                assert template.property("text") == "Changed {name}"
                long_text = "\n".join(f"Person {i}" for i in range(80))
                backend.message.recipientsText = long_text
                backend.message.templateText = long_text
                QTest.qWait(80)
                recipient_bar = find("messageRecipientsScrollBar")
                template_bar = find("messageTemplateScrollBar")
                assert recipient_bar.property("size") < 1
                assert template_bar.property("size") < 1
                recipients.forceActiveFocus()
                QTest.keyClick(window, Qt.Key_End, Qt.ControlModifier)
                QTest.qWait(60)
                assert recipient_bar.property("position") > 0
                assert template_bar.property("position") == 0
                template.forceActiveFocus()
                QTest.keyClick(window, Qt.Key_End, Qt.ControlModifier)
                QTest.qWait(60)
                assert template_bar.property("position") > 0

            elif scenario == "scrollbars":
                for name in ("messageBodyHorizontalScrollBar", "messageEditorScrollBar",
                             "messageRecipientsScrollBar", "messageTemplateScrollBar", "messagePreviewScrollBar"):
                    bar = find(name)
                    assert not bar.property("visible"), f"Non-overflowing scrollbar leaves a dot: {name}"
                initial = window.grabWindow()
                for prefix in ("Recipients", "Template"):
                    surface = find(f"message{prefix}Surface")
                    point = surface.mapToScene(QPointF(5, 5)).toPoint()
                    assert initial.pixelColor(point) == surface.property("color"), f"Gray dot at {prefix} editor corner"
                backend.message.recipientsText = "\n".join(f"Person {i}" for i in range(80))
                backend.message.templateText = "\n".join(f"Line {i}" for i in range(80))
                QTest.qWait(80)
                for prefix in ("Recipients", "Template"):
                    bar = find(f"message{prefix}ScrollBar")
                    surface = find(f"message{prefix}Surface")
                    assert bar.property("visible")
                    assert bar.height() == pytest.approx(surface.height(), abs=1), "Scroll thumb must use the entire editor height"
                    bar_point = bar.mapToScene(QPointF(0, 0))
                    surface_point = surface.mapToScene(QPointF(surface.width() - bar.width(), 0))
                    assert bar_point.x() == pytest.approx(surface_point.x(), abs=1)
                    assert bar_point.y() == pytest.approx(surface_point.y(), abs=1)
                recipients = find("messageRecipientsInput")
                recipients.forceActiveFocus()
                QTest.keyClick(window, Qt.Key_End, Qt.ControlModifier)
                QTest.qWait(80)
                assert find("messageRecipientsScrollBar").property("position") > 0
                assert find("messageTemplateScrollBar").property("position") == 0
                assert window.grabWindow().save(str(capture_dir / "message-long-recipients.png"))
                window.setWidth(640)
                window.setHeight(480)
                QTest.qWait(80)
                horizontal = find("messageBodyHorizontalScrollBar")
                body = find("messageBodyScrollView")
                assert horizontal.property("visible")
                assert horizontal.width() == pytest.approx(body.width(), abs=1)
                bar_bottom = horizontal.mapToScene(QPointF(0, horizontal.height())).y()
                body_bottom = body.mapToScene(QPointF(0, body.height())).y()
                assert bar_bottom == pytest.approx(body_bottom, abs=1)
                editor_bar = find("messageEditorScrollBar")
                count = find("messageRecipientCount")
                if editor_bar.property("visible"):
                    assert count.mapToScene(QPointF(count.width(), 0)).x() <= editor_bar.mapToScene(QPointF(0, 0)).x(), "Page scrollbar must not cover the recipient count"

            elif scenario == "context_menu":
                for name in ("messageRecipientsInput", "messageTemplateInput"):
                    field = find(name)
                    field.setProperty("text", "Alice")
                    menu = QQmlProperty(field, "ContextMenu.menu", QQmlEngine.contextForObject(field)).read()
                    assert menu is not None, f"Chinese editor menu missing: {name}"
                    assert menu.property("editor") == field
                    click(field, Qt.RightButton)
                    QTest.qWait(250)
                    assert menu.property("opened"), name
                    content = menu.property("contentItem")
                    corner = content.mapToScene(QPointF(0, 0))
                    assert 0 <= corner.x() <= window.width() - content.width()
                    assert 0 <= corner.y() <= window.height() - content.height()
                    assert window.grabWindow().save(str(capture_dir / f"{name}-menu.png"))
                    actions = {obj.property("text"): obj for obj in menu.findChildren(QQuickItem)
                               if obj.metaObject().indexOfSignal("triggered()") >= 0}
                    for label in ("\u64a4\u9500", "\u91cd\u505a", "\u526a\u5207", "\u590d\u5236", "\u7c98\u8d34", "\u5168\u9009"):
                        assert label in actions, (name, list(actions))
                    click(actions["\u5168\u9009"])
                    invoke(menu, "close")
                    assert field.property("selectedText") == "Alice"
                    invoke(actions["\u590d\u5236"], "triggered")
                    assert app.clipboard().text() == "Alice"
                    invoke(actions["\u526a\u5207"], "triggered")
                    assert field.property("text") == ""
                    invoke(actions["\u7c98\u8d34"], "triggered")
                    assert field.property("text") == "Alice"
                    invoke(actions["\u64a4\u9500"], "triggered")
                    assert field.property("text") == ""
                    invoke(actions["\u91cd\u505a"], "triggered")
                    assert field.property("text") == "Alice"

            elif scenario == "attachments":
                document = path / "course.txt"
                document.write_bytes(b"x" * 2048)
                image_path = path / "lesson.png"
                image = QImage(96, 64, QImage.Format_RGB32)
                image.fill(QColor("#F87C40"))
                assert image.save(str(image_path))
                backend.message.addFile(QUrl.fromLocalFile(str(document)).toString())
                backend.message.addFile(QUrl.fromLocalFile(str(image_path)).toString())
                backend.message.templateText = ""
                QTest.qWait(150)
                metadata = find("messageAttachmentMetadata-0")
                assert "TXT" in metadata.property("text"), metadata.property("text")
                assert "2.0 KB" in metadata.property("text")
                assert find("messageAttachmentName-0").property("text") == "course.txt"
                assert find("previewAttachment-0").property("visible")
                with patch("app.controllers.QDesktopServices.openUrl", return_value=True) as opened:
                    click("previewAttachment-0")
                    opened.assert_called_once_with(QUrl.fromLocalFile(str(document)))
                click("previewAttachment-1")
                viewer = find("attachmentImageViewer")
                assert viewer.property("opened")
                assert viewer.property("fileName") == "lesson.png"
                QTest.keyClick(window, Qt.Key_Escape)
                QTest.qWait(40)
                assert not viewer.property("opened")
                document.unlink()
                backend.message.addFile(str(path / "missing.docx"))
                QTest.qWait(80)
                assert "\u6587\u4ef6\u4e0d\u53ef\u7528" in find("messageAttachmentMetadata-0").property("text")
                click("messageRemoveFileButton-0")
                assert backend.message.filePaths == [str(image_path), str(path / "missing.docx")]
                assert find("messageAttachmentName-0").property("text") == "lesson.png"
                click("messageAddFileButton")
                dialog = find("messageFileDialog")
                assert dialog.property("visible")
                invoke(dialog, "reject")

            elif scenario == "locked_on_load":
                assert workspace.property("interactionLocked")
                assert workspace.property("monitorVisible")
                invoke(workspace, "dismissMonitor")
                for name in ("messageRecipientsInput", "messageTemplateInput", "messageAddFileButton", "startMessageButton"):
                    assert not find(name).property("enabled"), name
                finish()
                assert find("messageRecipientsInput").property("enabled")

            elif scenario == "safety":
                start = find("startMessageButton")
                recipients = find("messageRecipientsInput")
                template = find("messageTemplateInput")
                assert start.property("enabled")
                for name in ("messageRecipientsInput", "messageTemplateInput", "messageAddFileButton", "startMessageButton"):
                    assert QAccessible.queryAccessibleInterface(find(name)).text(QAccessible.Name) == name
                backend.message.fuzzySearchEnabled = True
                click(start)
                assert backend.task.active
                payload = client.calls[-1][2]
                assert payload["kind"] == "message_send"
                assert payload["options"]["fuzzySearchEnabled"] is True
                assert [item["target"] for item in payload["items"]] == ["Alice", "Bob"]
                assert [item["message"] for item in payload["items"]] == ["Alice, hello", "Bob, hello"]
                invoke(workspace, "dismissMonitor")
                for name in ("messageRecipientsInput", "messageTemplateInput", "messageAddFileButton",
                             "insertMessageNamePlaceholder", "startMessageButton"):
                    assert not find(name).property("enabled"), name
                before = backend.message.templateText
                invoke(find("insertMessageNamePlaceholder"), "clicked")
                assert backend.message.templateText == before, "Programmatic activation must also respect the task lock"
                calls = len(client.calls)
                invoke(workspace, "startTask")
                assert len(client.calls) == calls
                finish()
                assert recipients.property("enabled") and template.property("enabled")
                backend.agent.applyInspection({"connected": True, "version": "0", "supported": False,
                                              "uiaReady": False, "detail": "unsupported"})
                QTest.qWait(40)
                assert not start.property("enabled")
                assert template.property("enabled")
                backend.agent.applyInspection({"connected": True, "version": "4.1.13.65", "supported": True,
                                              "uiaReady": True, "detail": "ready"})
                backend.message.recipientsText = ""
                QTest.qWait(40)
                assert not start.property("enabled")
                backend.message.recipientsText = "Alice"
                from tests.test_message_fuzzy_settings import start_task
                start_task(backend, client, "friend_add")
                QTest.qWait(60)
                assert not workspace.property("monitorVisible"), "A friend task must not show the message monitor"
                assert not recipients.property("enabled") and not template.property("enabled")
                assert recipients.property("readOnly") and template.property("readOnly")
                assert not start.property("enabled")
                finish()
                assert recipients.property("enabled") and template.property("enabled")
                assert workspace.property("objectName") == "messageWorkspace"

            assert not warnings, warnings
        finally:
            backend.shutdown()
            window.close()
            engine.deleteLater()
            app.processEvents()


@pytest.mark.parametrize("scenario", ["layout", "editors", "scrollbars", "context_menu", "attachments", "locked_on_load", "safety"])
def test_message_workspace(scenario):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software",
           "QT_QUICK_BACKEND": "software", "PYTHONPATH": str(ROOT), "WECHAT_COURIER_ACCEPTANCE": "1"}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--exercise", scenario],
                            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    exercise(sys.argv[2])
