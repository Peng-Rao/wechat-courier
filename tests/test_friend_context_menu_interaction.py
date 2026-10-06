"""Offscreen interaction regression coverage for the friend-table context menu."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, Property, QPoint, QUrl, Qt, Signal, Slot, QSettings
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

from app.controllers import FriendController


REPO_ROOT = Path(__file__).resolve().parents[1]


class TaskBackend(QObject):
    activeChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._active = False

    @Property(bool, notify=activeChanged)
    def active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.activeChanged.emit(active)

    @Property(str, constant=True)
    def kind(self) -> str:
        return ""

    @Property(str, constant=True)
    def error(self) -> str:
        return ""

    @Slot(result=bool)
    def startFriends(self) -> bool:
        return False


class AgentBackend(QObject):
    @Property(bool, constant=True)
    def automationReady(self) -> bool:
        return False


class AppBackend(QObject):
    def __init__(
        self,
        friends: FriendController,
        task: TaskBackend,
        agent: AgentBackend,
    ) -> None:
        super().__init__()
        self._friends = friends
        self._task = task
        self._agent = agent

    @Property(QObject, constant=True)
    def friends(self) -> FriendController:
        return self._friends

    @Property(QObject, constant=True)
    def task(self) -> TaskBackend:
        return self._task

    @Property(QObject, constant=True)
    def agent(self) -> AgentBackend:
        return self._agent


def _view_point(item: QQuickItem, view: QQuickView, point: QPoint) -> QPoint:
    scene_point = item.mapToScene(point)
    return QPoint(round(scene_point.x()), round(scene_point.y()))


def _find_item(item: QQuickItem, object_name: str) -> QQuickItem | None:
    if item.objectName() == object_name:
        return item
    for child in item.childItems():
        found = _find_item(child, object_name)
        if found is not None:
            return found
    return None


def _click(view: QQuickView, item: QQuickItem, point: QPoint, button: Qt.MouseButton) -> None:
    QTest.mouseClick(view, button, Qt.NoModifier, _view_point(item, view, point))
    QTest.qWait(100)


def _activate(view: QQuickView, action: QQuickItem) -> None:
    _click(view, action, QPoint(10, int(action.height() / 2)), Qt.LeftButton)


def _type(view: QQuickView, text: str) -> None:
    for character in text:
        QTest.keyClick(view, getattr(Qt, f"Key_{character.upper()}"))


def _exercise_context_menu() -> None:
    app = QGuiApplication([])
    if os.name == "nt":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        app.setFont(QFont("Microsoft YaHei", 10))
    settings_dir = tempfile.TemporaryDirectory()
    friends = FriendController(QSettings(str(Path(settings_dir.name) / "settings.ini"), QSettings.IniFormat))
    friends.defaultGreeting = "{称呼}，您好！"
    model = friends.model
    model.appendEmptyRecord()
    assert model.setCell(0, "account", "wxid_original")
    assert model.setCell(0, "name", "示例学生")
    task = TaskBackend()
    backend = AppBackend(friends, task, AgentBackend())
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setInitialProperties({"appBackend": backend})
    view.setSource(QUrl.fromLocalFile(str(REPO_ROOT / "qml" / "components" / "FriendWorkspace.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.resize(1000, 700)
    view.show()
    QTest.qWait(250)

    root = view.rootObject()
    table = root.findChild(QQuickItem, "friendImportTable")
    menu = root.findChild(QObject, "friendContextMenu")
    add_action = root.findChild(QQuickItem, "addFriendRowMenuItem")
    remove_action = root.findChild(QQuickItem, "removeFriendRowMenuItem")
    assert table is not None
    assert menu is not None
    assert add_action is not None
    assert remove_action is not None
    assert table.height() > 46
    account_field = _find_item(table.property("contentItem"), "friendAccountField")
    assert account_field is not None
    assert account_field.property("modelRow") == 0, account_field.property("modelRow")
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier,
                     _view_point(account_field, view, QPoint(20, int(account_field.height() / 2))))
    assert account_field.property("activeFocus") is True
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    _type(view, "wxidedited")
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(100)
    assert account_field.property("text") == "wxidedited", account_field.property("text")
    assert model.record_at(0).account == "wxidedited"

    name_field = _find_item(table.property("contentItem"), "friendNameField")
    relationship = _find_item(table.property("contentItem"), "friendRelationshipSelector")
    remark = _find_item(table.property("contentItem"), "friendRemarkField")
    preview = root.findChild(QQuickItem, "friendContentPreview")
    global_relationship = root.findChild(QQuickItem, "globalRelationshipSelector")
    global_greeting = root.findChild(QQuickItem, "globalFriendGreetingField")
    assert all(item is not None for item in (name_field, relationship, remark, preview, global_relationship))
    assert remark.property("readOnly") is True
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier,
                     _view_point(name_field, view, QPoint(20, 15)))
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    _type(view, "Student")
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(50)
    assert model.record_at(0).name == "student"
    assert "student妈妈" in preview.property("text")

    # Exercise the real popup: first item is global, second is explicit none.
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier,
                     _view_point(relationship, view, QPoint(20, 15)))
    _click(view, relationship, QPoint(int(relationship.width()) - 12, 15), Qt.LeftButton)
    QTest.keyClick(view, Qt.Key_Home)
    QTest.keyClick(view, Qt.Key_Down)
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(100)
    assert model.record_at(0).relationship == ""
    assert remark.property("text") == "student"
    _activate(view, root.findChild(QQuickItem, "selectFriendRangeButton"))
    assert friends.build_items()[0]["greeting"] == "student，您好！"
    friends.defaultRelationship = "姐姐"
    QTest.qWait(50)
    assert remark.property("text") == "student"

    # Custom entry uses the ComboBox's editable input, not a fake model setter.
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier,
                     _view_point(relationship, view, QPoint(25, 15)))
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    _type(view, "Guardian")
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(100)
    assert model.record_at(0).relationship == "guardian"
    assert "studentguardian" in preview.property("text")
    _click(view, global_greeting, QPoint(20, 15), Qt.LeftButton)
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_Backspace)
    QTest.qWait(50)
    assert friends.build_items()[0]["greeting"] is None
    assert "保留微信原文" in preview.property("text")
    insert_address = root.findChild(QQuickItem, "insertAddressPlaceholder")
    _activate(view, insert_address)
    assert friends.defaultGreeting == "{称呼}"
    assert friends.build_items()[0]["greeting"] == "studentguardian"
    task.set_active(True)
    QTest.qWait(50)
    assert not relationship.property("enabled")
    assert not name_field.property("enabled")
    assert not global_relationship.property("enabled")
    assert not global_greeting.property("enabled")
    assert not insert_address.property("enabled")
    task.set_active(False)

    _click(view, table, QPoint(30, 20), Qt.RightButton)
    assert menu.property("visible") is True
    assert root.property("contextRow") == 0
    _activate(view, add_action)
    QTest.qWait(100)
    assert model.count == 2

    _click(view, table, QPoint(30, int(table.height()) - 20), Qt.RightButton)
    assert menu.property("visible") is True
    assert root.property("contextRow") == -1
    assert remove_action.property("visible") is False
    _activate(view, add_action)
    QTest.qWait(100)
    assert model.count == 3

    _click(view, table, QPoint(30, 20), Qt.RightButton)
    assert menu.property("visible") is True
    assert remove_action.property("visible") is True
    _activate(view, remove_action)
    QTest.qWait(100)
    assert model.count == 2

    _click(view, table, QPoint(30, 20), Qt.RightButton)
    assert menu.property("visible") is True
    assert root.property("contextRow") == 0
    task.set_active(True)
    QTest.qWait(50)
    assert add_action.property("enabled") is False
    assert remove_action.property("enabled") is False
    _activate(view, add_action)
    _activate(view, remove_action)
    QTest.qWait(100)
    assert model.count == 2
    assert QMetaObject.invokeMethod(root, "appendManualRecord")
    assert QMetaObject.invokeMethod(root, "removeContextRecord")
    assert model.count == 2
    menu.close()
    QTest.qWait(50)
    _click(view, table, QPoint(30, int(table.height()) - 20), Qt.RightButton)
    assert menu.property("visible") is False

    task.set_active(False)
    for row in range(model.count, 20):
        model.appendEmptyRecord()
        assert model.setCell(row, "account", f"wxid_scroll{row}")
    QTest.qWait(100)
    target_row = 10
    target_account = model.record_at(target_row).account
    table.setProperty("contentY", target_row * 40)
    QTest.qWait(100)
    _click(view, table, QPoint(30, 23), Qt.RightButton)
    assert root.property("contextRow") == target_row
    assert remove_action.property("visible") is True
    _activate(view, remove_action)
    QTest.qWait(100)
    assert all(model.record_at(row).account != target_account for row in range(model.count))
    assert QMetaObject.invokeMethod(root, "appendManualRecord")
    last_row = model.count - 1
    # The viewport changed; wait for Qt's row-positioning animation, not a fixed frame delay.
    for _ in range(50):
        if float(table.property("contentY")) + table.height() >= (last_row + 1) * 40:
            break
        QTest.qWait(20)
    content_y = float(table.property("contentY"))
    assert content_y <= last_row * 40
    assert content_y + table.height() >= (last_row + 1) * 40, (content_y, table.height(), last_row)

    # Replacing a long, scrolled table with a short import must show its first row.
    from app.friend_import import load_friend_records
    model.replace_records(load_friend_records([
            ["姓名", "账号", "打招呼语"],
            ["示例学生妈妈", "mock_only_001", ""],
            ["示例学生姐姐", "mock_only_002", "{称呼}您好，我是班主任。"],
            ["示例学生", "mock_only_003", ""],
    ]))
    model.setCell(2, "relationship", "无")
    friends.defaultGreeting = "{称呼}，您好，我是老师。"
    QTest.qWait(150)
    assert table.property("contentY") == 0, table.property("contentY")
    if os.environ.get("FRIEND_PREVIEW_IMAGE"):
        view.resize(1280, 760)
        QTest.qWait(250)
        view.grabWindow().save(os.environ["FRIEND_PREVIEW_IMAGE"])
    view.hide()
    view.setSource(QUrl())
    app.processEvents()


def test_friend_table_context_menu_accepts_real_right_clicks_offscreen() -> None:
    """A right-click on a live table must expose the add/remove menu actions."""
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("QSG_RHI_BACKEND", "software")
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--exercise"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    if sys.argv[1:] != ["--exercise"]:
        raise SystemExit("expected --exercise")
    _exercise_context_menu()
