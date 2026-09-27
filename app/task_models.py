from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, QUrl, Signal, Slot

from .friend_import import FriendRecord, load_friend_records, validate_records
from .friend_templates import normalize_relationship, split_name
from .constants import FRIEND_BATCH_LIMIT_DEFAULT, normalize_friend_batch_limit


_TERMINAL_STEPS = {"send_verified", "preflight_completed", "submit_verified"}
_TERMINAL_OUTCOMES = {"error", "unknown", "stopped"}


def _display_result(event: dict[str, Any]) -> tuple[str, bool]:
    outcome = str(event.get("outcome", "working"))
    step = str(event.get("step", ""))
    terminal = outcome in _TERMINAL_OUTCOMES or step in _TERMINAL_STEPS
    return (outcome if terminal else "working"), terminal


def _event_time(event: dict[str, Any]) -> datetime | None:
    value = str(event.get("timestamp", "")).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class FriendImportModel(QAbstractListModel):
    AccountRole = Qt.UserRole + 1
    GreetingRole = Qt.UserRole + 2
    RemarkRole = Qt.UserRole + 3
    ValidRole = Qt.UserRole + 4
    ErrorRole = Qt.UserRole + 5
    StatusRole = Qt.UserRole + 6
    SelectedRole = Qt.UserRole + 7
    ItemIdRole = Qt.UserRole + 8
    NameRole = Qt.UserRole + 9
    RelationshipRole = Qt.UserRole + 10
    RelationshipSourceRole = Qt.UserRole + 11
    RenderedGreetingRole = Qt.UserRole + 12

    countsChanged = Signal()
    selectionLimitChanged = Signal(int)
    importErrorChanged = Signal(str)
    importWarningChanged = Signal(str)

    _ROLE_NAMES = {
        AccountRole: b"account",
        GreetingRole: b"greeting",
        RemarkRole: b"remark",
        ValidRole: b"valid",
        ErrorRole: b"error",
        StatusRole: b"status",
        SelectedRole: b"selected",
        ItemIdRole: b"itemId",
        NameRole: b"friendName",
        RelationshipRole: b"relationshipChoice",
        RelationshipSourceRole: b"relationshipSource",
        RenderedGreetingRole: b"renderedGreeting",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[FriendRecord] = []
        self._manual_rows_pending_selection: set[str] = set()
        self._import_error = ""
        self._import_warning = ""
        self._default_greeting = ""
        self._default_relationship = "妈妈"
        self._selection_limit = FRIEND_BATCH_LIMIT_DEFAULT

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
            self.NameRole: record.name,
            self.RelationshipRole: "使用全局" if record.relationship is None else record.relationship or "无",
            self.RelationshipSourceRole: record.relationship_source,
            self.RenderedGreetingRole: record.rendered_greeting or "",
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

    @Property(int, notify=selectionLimitChanged)
    def selectionLimit(self):
        return self._selection_limit

    def set_selection_limit(self, limit: int) -> None:
        limit = normalize_friend_batch_limit(limit)
        if limit == self._selection_limit:
            return
        self._selection_limit = limit
        if self._trim_selected_records() and self._records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._records) - 1, 0),
                                  [self.SelectedRole])
        self.selectionLimitChanged.emit(limit)
        self.countsChanged.emit()

    def _trim_selected_records(self) -> bool:
        kept = 0
        changed = False
        for record in self._records:
            if not record.selected:
                continue
            if kept < self._selection_limit:
                kept += 1
            else:
                record.selected = False
                changed = True
        return changed

    @Property(str, notify=importErrorChanged)
    def importError(self):
        return self._import_error

    @Property(str, notify=importWarningChanged)
    def importWarning(self):
        return self._import_warning

    def set_defaults(self, greeting: str, relationship: str) -> None:
        self._default_greeting = greeting
        self._default_relationship = normalize_relationship(relationship)
        self._refresh()

    def _validate(self) -> None:
        validate_records(self._records, self._default_greeting, self._default_relationship)

    def _refresh(self) -> None:
        self._validate()
        self._select_newly_valid_manual_records()
        if self._records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._records) - 1, 0), list(self._ROLE_NAMES))
        self.countsChanged.emit()

    @Slot(int, result="QVariantMap")
    def preview(self, row: int) -> dict:
        if not 0 <= row < len(self._records):
            return {}
        record = self._records[row]
        return {"greeting": record.rendered_greeting, "remark": record.remark,
                "error": record.error, "valid": record.valid}

    def record_at(self, row: int) -> FriendRecord:
        return self._records[row]

    def _select_newly_valid_manual_records(self) -> None:
        selected_count = self.selectedCount
        for record in self._records:
            if (
                record.item_id not in self._manual_rows_pending_selection
                or not record.valid
            ):
                continue
            self._manual_rows_pending_selection.discard(record.item_id)
            if selected_count < self._selection_limit:
                record.selected = True
                selected_count += 1

    def replace_records(self, records: Iterable[FriendRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self._manual_rows_pending_selection.clear()
        self._validate()
        self._trim_selected_records()
        self.endResetModel()
        self.countsChanged.emit()

    @Slot(result=int)
    def appendEmptyRecord(self) -> int:
        row = len(self._records)
        record = FriendRecord(item_id=f"manual-{uuid4().hex}", account="")
        self.beginInsertRows(QModelIndex(), row, row)
        self._records.append(record)
        self._validate()
        self._manual_rows_pending_selection.add(record.item_id)
        self.endInsertRows()
        self.countsChanged.emit()
        return row

    @Slot(int, result=bool)
    def removeRecord(self, row: int) -> bool:
        if not 0 <= row < len(self._records):
            return False
        item_id = self._records[row].item_id
        self.beginRemoveRows(QModelIndex(), row, row)
        self._records.pop(row)
        self._manual_rows_pending_selection.discard(item_id)
        self.endRemoveRows()
        self._validate()
        self._select_newly_valid_manual_records()
        if self._records:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._records) - 1, 0),
                [self.AccountRole, self.ValidRole, self.ErrorRole, self.SelectedRole],
            )
        self.countsChanged.emit()
        return True

    @Slot(result=bool)
    def clearRecords(self) -> bool:
        changed = bool(
            self._records
            or self._manual_rows_pending_selection
            or self._import_error
            or self._import_warning
        )
        if not changed:
            return False

        self.beginResetModel()
        self._records.clear()
        self._manual_rows_pending_selection.clear()
        self.endResetModel()
        if self._import_error:
            self._import_error = ""
            self.importErrorChanged.emit("")
        self._import_warning = ""
        self.importWarningChanged.emit("")
        self.countsChanged.emit()
        return True

    @Slot(str, result=bool)
    def importFile(self, path: str) -> bool:
        if QUrl(path).isLocalFile():
            path = QUrl(path).toLocalFile()
        try:
            warnings = []
            records = load_friend_records(path, warnings=warnings, selection_limit=self._selection_limit)
        except Exception as exc:
            self._import_error = str(exc)
            self.importErrorChanged.emit(self._import_error)
            return False
        self._import_error = ""
        self.importErrorChanged.emit("")
        self._import_warning = "；".join(warnings)
        self.importWarningChanged.emit(self._import_warning)
        self.replace_records(records)
        # Selection must use the actual global template, not loader defaults.
        self.selectFirstValid()
        return True

    @Slot(int, str, object, result=bool)
    @Slot(int, str, str, result=bool)
    def setCell(self, row: int, field: str, value: Any) -> bool:
        if not 0 <= row < len(self._records):
            return False
        if field not in {"account", "greeting", "name", "relationship"}:
            return False
        record = self._records[row]
        value = str(value).strip()
        if field == "relationship":
            record.relationship = None if value == "使用全局" else normalize_relationship(value)
            record.relationship_source = "manual"
        elif field == "name":
            if value == record.name:
                return True
            record.name, recognized = split_name(value)
            if record.relationship_source != "manual":
                record.relationship = recognized
                record.relationship_source = "auto" if recognized is not None else "global"
        else:
            setattr(record, field, value)
        self._refresh()
        return True

    @Slot(int, bool, result=bool)
    def setSelected(self, row: int, selected: bool) -> bool:
        if not 0 <= row < len(self._records):
            return False
        record = self._records[row]
        if record.selected == selected:
            return True
        if selected and (not record.valid or self.selectedCount >= self._selection_limit):
            return False
        record.selected = selected
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.SelectedRole])
        self.countsChanged.emit()
        return True

    @Slot()
    def selectFirstValid(self) -> None:
        selected = 0
        for record in self._records:
            record.selected = record.valid and selected < self._selection_limit
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
        self, default_greeting: str | None = None, default_relationship: str | None = None
    ) -> list[dict[str, Any]]:
        if default_greeting is not None or default_relationship is not None:
            self.set_defaults(self._default_greeting if default_greeting is None else default_greeting,
                              self._default_relationship if default_relationship is None else default_relationship)
        self._validate()
        payload = []
        for record in self._records:
            if not record.valid or not record.selected:
                continue
            payload.append(
                {
                    "itemId": record.item_id,
                    "account": record.account,
                    "greeting": record.rendered_greeting,
                    "remark": record.remark,
                }
            )
        return payload

    def apply_event(self, event: dict[str, Any]) -> None:
        item_id = str(event.get("itemId", ""))
        for row, record in enumerate(self._records):
            if record.item_id != item_id:
                continue
            record.status, _terminal = _display_result(event)
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
        self._started_at: dict[str, datetime] = {}

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
        self._started_at.clear()
        self.endResetModel()

    def apply_event(self, event: dict[str, Any]) -> None:
        item_id = str(event.get("itemId", ""))
        for row, item in enumerate(self._items):
            if item.item_id != item_id:
                continue
            timestamp = _event_time(event)
            if timestamp is not None and item_id not in self._started_at:
                self._started_at[item_id] = timestamp
            item.detail = str(event.get("detail", ""))
            item.result, terminal = _display_result(event)
            item.step_code = str(event.get("step", ""))
            started = self._started_at.get(item_id)
            if terminal and started is not None and timestamp is not None:
                elapsed = max(0.0, (timestamp - started).total_seconds())
                item.duration = f"{elapsed:.1f}s"
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
