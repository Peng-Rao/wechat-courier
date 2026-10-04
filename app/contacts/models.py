from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Property, Qt, Signal, Slot

from .data import CONTACT_FIELDS, CONTACT_HEADERS, normalize_contact


class ContactTableModel(QAbstractTableModel):
    CellTextRole = Qt.UserRole + 1
    countsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[dict[str, str]] = []
        self._visible: list[dict[str, str]] = []
        self._keyword = ""
        self._include_special = False
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def roleNames(self):
        roles = super().roleNames()
        roles[self.CellTextRole] = b"cellText"
        return roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(CONTACT_FIELDS)

    def data(self, index, role=Qt.DisplayRole):
        if (not index.isValid() or index.model() is not self
                or not 0 <= index.row() < len(self._visible)
                or not 0 <= index.column() < len(CONTACT_FIELDS)):
            return None
        if role in (Qt.DisplayRole, self.CellTextRole):
            return self.text(index.row(), index.column())
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and 0 <= section < len(CONTACT_HEADERS):
                return CONTACT_HEADERS[section]
            if orientation == Qt.Vertical and 0 <= section < len(self._visible):
                return str(section + 1)
        return None

    @Slot(int, int, result=str)
    def text(self, row: int, column: int) -> str:
        if not 0 <= row < len(self._visible) or not 0 <= column < len(CONTACT_FIELDS):
            return ""
        return self._visible[row][CONTACT_FIELDS[column]]

    @Property(int, notify=countsChanged)
    def totalCount(self):
        return len(self._records)

    @Property(int, notify=countsChanged)
    def visibleCount(self):
        return len(self._visible)

    def replace_records(self, records: list) -> None:
        canonical_keys = {*CONTACT_FIELDS, "category"}
        categories = {"friend", "group", "official", "system", "cache", "other"}
        copied = []
        for row in records:
            contact = normalize_contact(row)
            # Reader output is already classified, with source metadata removed.
            if set(row) <= canonical_keys and row.get("category") in categories:
                contact["category"] = row["category"]
            copied.append(contact)
        self._refresh(copied)

    @Slot()
    def clear(self) -> None:
        self._refresh([])

    @Slot(str)
    def set_keyword(self, keyword: str) -> None:
        folded = keyword.casefold()
        if folded != self._keyword:
            self._keyword = folded
            self._refresh()

    @Slot(bool)
    def set_include_special(self, include: bool) -> None:
        if bool(include) != self._include_special:
            self._include_special = bool(include)
            self._refresh()

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        if not 0 <= column < len(CONTACT_FIELDS):
            return
        self._sort_column = column
        self._sort_order = order
        self._refresh()

    def snapshot(self) -> list[dict]:
        """Return independent records in the current visible order."""
        return [dict(row) for row in self._visible]

    def _refresh(self, records=None) -> None:
        source = self._records if records is None else records
        visible = [row for row in source
                   if (self._include_special or row["category"] == "friend")
                   and (not self._keyword or any(
                       self._keyword in row[field].casefold() for field in CONTACT_FIELDS))]
        if self._sort_column >= 0:
            field = CONTACT_FIELDS[self._sort_column]
            visible.sort(key=lambda row: row[field], reverse=self._sort_order == Qt.DescendingOrder)
        self.beginResetModel()
        self._records = source
        self._visible = visible
        self.endResetModel()
        self.countsChanged.emit()
