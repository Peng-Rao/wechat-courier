"""Real QML/controller integration; isolated fake RPC, no WeChat side effects."""
import os
from pathlib import Path
import subprocess
import sys


def exercise_gui(output):
    from PySide6.QtCore import QObject, QSettings, Qt, QUrl
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QImage
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest

    from app.backend import BackendController
    from app.friend_import import load_friend_records
    from tests.test_v3_controllers import FakeAgentClient

    output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 10))
    client = FakeAgentClient()
    backend = BackendController(settings=QSettings(str(output / "gui.ini"), QSettings.IniFormat), agent_client=client)
    backend.settings.glassEnabled = False
    backend.agent.applyInspection({"connected": True, "version": "4.1.13.65", "supported": True, "uiaReady": True})
    client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
    backend.message.recipientsText = "\n".join(f"测试好友{i:03d}" for i in range(60))
    backend.message.templateText = "{name}，你好！\n" + "内容预览\n" * 25
    image_path = output / "图片 100%.png"
    image = QImage(480, 240, QImage.Format_RGB32)
    image.fill(0x00A876)
    assert image.save(str(image_path))
    document = output / "普通附件 #1.txt"
    document.write_text("test fixture", encoding="utf-8")
    backend.message.addFile(QUrl.fromLocalFile(str(image_path)).toString())
    backend.message.addFile(QUrl.fromLocalFile(str(document)).toString())
    backend.friends.model.replace_records(load_friend_records(
        [["姓名", "账号"], *[[f"示例{i:03d}", f"wxid_mock_{i:04d}"] for i in range(120)]]))
    assert backend.friends.model.selectedCount == 0
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.rootContext().setContextProperty("backend", backend)
    engine.loadData(b'''import QtQuick
import "components"
Window {
    id: host
    width: 1320; height: 880; visible: true; title: backend.versionInfo
    WxTitleBar { id: title; width: parent.width; window: host; titleBackend: backend }
    App { anchors.top: title.bottom; anchors.bottom: parent.bottom; width: parent.width; appBackend: backend }
}''', QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "qml" / "integration.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]

    def find(name, item=None):
        item = item or window.contentItem()
        if not item.isVisible():
            return None
        if item.objectName() == name:
            return item
        for child in item.childItems():
            result = find(name, child)
            if result is not None:
                return result
        return None

    def click(item):
        assert item is not None and item.isVisible() and item.isEnabled()
        point = item.mapToScene(item.boundingRect().center())
        assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), point
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(100)

    def capture(name):
        QTest.qWait(120)
        assert window.grabWindow().save(str(output / name))

    QTest.qWait(300)
    app_root = window.findChild(QObject, "appRoot")
    capture("message-1320.png")
    for name in ("messageRecipientsScrollBar", "messageTemplateScrollBar"):
        assert window.findChild(QObject, name).property("size") < 1
    backend.message.templateText = "{name}，你好！"
    QTest.qWait(100)
    click(find("previewAttachment-0"))
    viewer = window.findChild(QObject, "attachmentImageViewer")
    assert viewer.property("opened")
    capture("image-expanded.png")
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(100)
    assert not viewer.property("opened")
    window.setWidth(960)
    window.setHeight(680)
    capture("message-960.png")
    assert find("previewAttachment-0").width() > 160
    app_root.setProperty("workspaceIndex", 1)
    QTest.qWait(100)
    start = find("friendRangeStart")
    end = find("friendRangeEnd")
    start.setProperty("text", "105")
    end.setProperty("text", "110")
    click(find("selectFriendRangeButton"))
    assert backend.friends.model.selectedCount == 6
    assert [row["sourceRow"] for row in backend.friends.build_items()] == list(range(105, 111))
    capture("friends-960.png")
    end.setProperty("text", "2")
    click(find("selectFriendRangeButton"))
    assert backend.friends.model.selectedCount == 6
    assert backend.friends.model.selectionError
    start.setProperty("text", "1.5")
    end.setProperty("text", "4")
    click(find("selectFriendRangeButton"))
    assert backend.friends.model.selectedCount == 6
    assert backend.friends.model.selectionError
    start.setProperty("text", "105")
    end.setProperty("text", "110")
    click(find("selectFriendRangeButton"))
    assert backend.task.startFriends()
    request = client.calls[-1][2]
    QTest.qWait(1100)
    assert backend.task.elapsedSeconds >= 1
    click(find("messageWorkspaceTab"))
    before = backend.task.elapsedSeconds
    QTest.qWait(100)
    assert backend.task.elapsedSeconds >= before
    assert not find("startMessageButton").isEnabled()
    click(find("friendWorkspaceTab"))
    backend.task.pause()
    client.notificationReceived.emit("agent.status", {"taskId": request["taskId"], "status": "paused"})
    frozen = backend.task.elapsedSeconds
    QTest.qWait(200)
    assert backend.task.elapsedSeconds == frozen
    backend.task.resume()
    client.notificationReceived.emit("agent.status", {"taskId": request["taskId"], "status": "waiting", "remaining": 3.1})
    assert "4 秒" in find("taskIntervalCountdown").property("text")
    first = request["items"][0]
    client.notificationReceived.emit("task.event", {
        "taskId": request["taskId"], "itemId": first["itemId"], "step": "account_searched",
        "outcome": "error", "errorCode": "RISK_CONTROL", "riskKind": "friend_frequency",
        "detail": "操作过于频繁，请稍后再试", "done": 1, "total": 6,
        "timestamp": "2026-10-04T07:25:33Z", "itemElapsedMs": 15321,
    })
    client.notificationReceived.emit("task.finished", {
        "taskId": request["taskId"], "outcome": "error", "done": 1, "total": 6,
    })
    assert backend.task.riskStopSourceRow == 105
    assert backend.task.items._items[0].duration == "15.3s"
    assert backend.task.waitingRemaining == 0
    assert all(row.result == "stopped" for row in backend.task.items._items[1:])
    capture("friend-risk-960.png")
    sidebar = find("taskStatusSidebar")
    assert sidebar is not None and sidebar.width() == 220
    sidebar_scroll = find("taskStatusScroll")
    assert sidebar_scroll.property("contentWidth") <= sidebar_scroll.width()
    assert 180 <= find("taskStepList").width() <= sidebar.width() - 24
    assert find("taskQueueScroll").width() > sidebar.width()
    click(find("taskReturnToEditorButton"))
    assert window.findChild(QObject, "friendWorkspace").property("currentRow") == 104
    assert find("friendImportTable").property("contentY") > 0
    capture("friend-risk-editor.png")
    for size in ((1320, 880), (960, 680)):
        window.setWidth(size[0]); window.setHeight(size[1])
        capture(f"friend-editor-{size[0]}.png")
    assert not any("Required property" in value or "TypeError" in value or "Unable to assign" in value
                   for value in warnings), warnings
    backend.shutdown()
    window.close()
    engine.deleteLater()
    app.processEvents()


def test_full_gui_with_real_controllers(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "tests.test_v100_gui_interaction", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    exercise_gui(Path(sys.argv[1]))
