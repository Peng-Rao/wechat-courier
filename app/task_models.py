from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot

from .friend_import import FriendRecord, load_friend_records, validate_records


class FriendImportModel(QAbstractListModel):
    AccountRole = Qt.UserRole + 1
    GreetingRole = Qt.UserRole + 2
    RemarkRole = Qt.UserRole + 3
    ValidRole = Qt.UserRole + 4
    ErrorRole = Qt.UserRole + 5
    StatusRole = Qt.UserRole + 6
    SelectedRole = Qt.UserRole + 7
    ItemIdRole = Qt.UserRole + 8

    countsChanged = Signal()
    importErrorChanged = Signal(str)

    _ROLE_NAMES = {
        AccountRole: b"account",
        GreetingRole: b"greeting",
        RemarkRole: b"remark",
        ValidRole: b"valid",
        ErrorRole: b"error",
        StatusRole: b"status",
        SelectedRole: b"selected",
        ItemIdRole: b"itemId",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[FriendRecord] = []
        self._import_error = ""

    def roleNames(self):
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._records)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        values = {
            self.AccountRole: record.account,
            self.GreetingRole: record.greeting,
            self.RemarkRole: record.remark,
            self.ValidRole: record.valid,
            self.ErrorRole: record.error,
            self.StatusRole: record.status,
            self.SelectedRole: record.selected,
            self.ItemIdRole: record.item_id,
        }
        return values.get(role)

    @Property(int, notify=countsChanged)
    def count(self):
        return len(self._records)

    @Property(int, notify=countsChanged)
    def selectedCount(self):
        return sum(record.selected for record in self._records)

    @Property(int, notify=countsChanged)
    def validCount(self):
        return sum(record.valid for record in self._records)

    @Property(str, notify=importErrorChanged)
    def importError(self):
        return self._import_error

    def record_at(self, row: int) -> FriendRecord:
        return self._records[row]

    def replace_records(self, records: Iterable[FriendRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()
        self.countsChanged.emit()

    @Slot(str, result=bool)
    def importFile(self, path: str) -> bool:
        if path.startswith("file:///"):
            path = path[8:]
        try:
            records = load_friend_records(path)
        except Exception as exc:
            self._import_error = str(exc)
            self.importErrorChanged.emit(self._import_error)
            return False
        self._import_error = ""
        self.importErrorChanged.emit("")
        self.replace_records(records)
        return True

    @Slot(int, str, object, result=bool)
    def setCell(self, row: int, field: str, value: Any) -> bool:
        if not 0 <= row < len(self._records):
            return False
        if field not in {"account", "greeting", "remark"}:
            return False
        setattr(self._records[row], field, str(value).strip())
        if field == "account":
            validate_records(self._records)
        top = self.index(0, 0)
        bottom = self.index(len(self._records) - 1, 0)
        if bottom.isValid():
            self.dataChanged.emit(top, bottom, list(self._ROLE_NAMES))
        self.countsChanged.emit()
        return True

    @Slot(int, bool, result=bool)
    def setSelected(self, row: int, selected: bool) -> bool:
        if not 0 <= row < len(self._records):
            return False
        record = self._records[row]
        if selected and (not record.valid or self.selectedCount >= 20):
            return False
        if record.selected == selected:
            return True
        record.selected = selected
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.SelectedRole])
        self.countsChanged.emit()
        return True

    @Slot()
    def selectFirstValid(self) -> None:
        selected = 0
        for record in self._records:
            record.selected = record.valid and selected < 20
            if record.selected:
                selected += 1
        if self._records:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._records) - 1, 0),
                [self.SelectedRole],
            )
        self.countsChanged.emit()

    def selected_payload(
        self, default_greeting: str, default_remark: str
    ) -> list[dict[str, Any]]:
        payload = []
        for record in self._records:
            if not record.valid or not record.selected:
                continue
            greeting = record.greeting or default_greeting or None
            remark = record.remark or default_remark or ""
            payload.append(
                {
                    "itemId": record.item_id,
                    "account": record.account,
                    "greeting": greeting,
                    "remark": remark,
                }
            )
        return payload

    def apply_event(self, event: dict[str, Any]) -> None:
        item_id = str(event.get("itemId", ""))
        for row, record in enumerate(self._records):
            if record.item_id != item_id:
                continue
            record.status = str(event.get("outcome", record.status))
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [self.StatusRole])
            break


@dataclass
class TaskDisplayItem:
    target: str
    detail: str = "等待执行"
    result: str = "pending"
    duration: str = "--"
    step_code: str = ""
    item_id: str = ""


class TaskItemModel(QAbstractListModel):
    TargetRole = Qt.UserRole + 1
    DetailRole = Qt.UserRole + 2
    ResultRole = Qt.UserRole + 3
    DurationRole = Qt.UserRole + 4
    StepCodeRole = Qt.UserRole + 5
    ItemIdRole = Qt.UserRole + 6

    _ROLE_NAMES = {
        TargetRole: b"target",
        DetailRole: b"detail",
        ResultRole: b"result",
        DurationRole: b"duration",
        StepCodeRole: b"stepCode",
        ItemIdRole: b"itemId",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[TaskDisplayItem] = []

    def roleNames(self):
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        return {
            self.TargetRole: item.target,
            self.DetailRole: item.detail,
            self.ResultRole: item.result,
            self.DurationRole: item.duration,
            self.StepCodeRole: item.step_code,
            self.ItemIdRole: item.item_id,
        }.get(role)

    def replace(self, items: Iterable[TaskDisplayItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def apply_event(self, event: dict[str, Any]) -> None:
        item_id = str(event.get("itemId", ""))
        for row, item in enumerate(self._items):
            if item.item_id != item_id:
                continue
            item.detail = str(event.get("detail", ""))
            item.result = str(event.get("outcome", "working"))
            item.step_code = str(event.get("step", ""))
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, list(self._ROLE_NAMES))
            break


@dataclass
class RuntimeLogEntry:
    timestamp: str
    level: str
    message: str
    step_code: str = ""


class RuntimeLogModel(QAbstractListModel):
    TimestampRole = Qt.UserRole + 1
    LevelRole = Qt.UserRole + 2
    MessageRole = Qt.UserRole + 3
    StepCodeRole = Qt.UserRole + 4
    _ROLE_NAMES = {
        TimestampRole: b"timestamp",
        LevelRole: b"level",
        MessageRole: b"message",
        StepCodeRole: b"stepCode",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[RuntimeLogEntry] = []

    def roleNames(self):
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        return {
            self.TimestampRole: entry.timestamp,
            self.LevelRole: entry.level,
            self.MessageRole: entry.message,
            self.StepCodeRole: entry.step_code,
        }.get(role)

    def clear(self) -> None:
        self.beginResetModel()
        self._entries.clear()
        self.endResetModel()

    def append_event(self, event: dict[str, Any]) -> None:
        outcome = str(event.get("outcome", "working"))
        level = "error" if outcome in {"error", "unknown"} else "info"
        entry = RuntimeLogEntry(
            timestamp=str(event.get("timestamp", "")),
            level=level,
            message=str(event.get("detail", "")),
            step_code=str(event.get("step", "")),
        )
        row = len(self._entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self._entries.append(entry)
        self.endInsertRows()


__all__ = [
    "FriendImportModel",
    "RuntimeLogModel",
    "TaskDisplayItem",
    "TaskItemModel",
]
