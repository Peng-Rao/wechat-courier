"""Offscreen interaction regression coverage for the friend-table context menu."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, Property, QPoint, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

from app.task_models import FriendImportModel


REPO_ROOT = Path(__file__).resolve().parents[1]


class FriendBackend(QObject):
    def __init__(self, model: FriendImportModel) -> None:
        super().__init__()
        self._model = model

    @Property(QObject, constant=True)
    def model(self) -> FriendImportModel:
        return self._model

    @Property(str, constant=True)
    def defaultGreeting(self) -> str:
        return ""

    @Property(str, constant=True)
    def defaultRemark(self) -> str:
        return ""

    @Property(float, constant=True)
    def intervalMin(self) -> float:
        return 15.0

    @Property(float, constant=True)
    def intervalMax(self) -> float:
        return 30.0

    @Slot(str, result=bool)
    def importFile(self, _path: str) -> bool:
        return False

    @Slot(str, result=bool)
    def createTemplate(self, _path: str) -> bool:
        return False


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
        friends: FriendBackend,
        task: TaskBackend,
        agent: AgentBackend,
    ) -> None:
        super().__init__()
        self._friends = friends
        self._task = task
        self._agent = agent

    @Property(QObject, constant=True)
    def friends(self) -> FriendBackend:
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
    model = FriendImportModel()
    model.appendEmptyRecord()
    assert model.setCell(0, "account", "wxid_original")
    task = TaskBackend()
    backend = AppBackend(FriendBackend(model), task, AgentBackend())
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
    _click(view, account_field, QPoint(20, int(account_field.height() / 2)), Qt.LeftButton)
    assert account_field.property("activeFocus") is True
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    _type(view, "wxidedited")
    QTest.keyClick(view, Qt.Key_Return)
    QTest.qWait(100)
    assert account_field.property("text") == "wxidedited", account_field.property("text")
    assert model.record_at(0).account == "wxidedited"

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
    table.setProperty("contentY", target_row * 46)
    QTest.qWait(100)
    _click(view, table, QPoint(30, 23), Qt.RightButton)
    assert root.property("contextRow") == target_row
    assert remove_action.property("visible") is True
    _activate(view, remove_action)
    QTest.qWait(100)
    assert all(model.record_at(row).account != target_account for row in range(model.count))
    assert QMetaObject.invokeMethod(root, "appendManualRecord")
    QTest.qWait(100)
    last_row = model.count - 1
    content_y = float(table.property("contentY"))
    assert content_y <= last_row * 46
    assert content_y + table.height() >= (last_row + 1) * 46

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
