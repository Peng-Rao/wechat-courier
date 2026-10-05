from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Property, QSettings, QThread, QTimer, QUrl, Signal, Slot, Qt

from .models import ContactTableModel


ERRORS = {
    "ACCESS_DENIED": "读取权限不足，可单独授权联系人读取进程。",
    "LOGIN_REQUIRED": "没有找到该账号的可验证密钥，请登录对应微信账号。",
    "UNSUPPORTED_VERSION": "联系人导出仅支持微信 4.1.13.65。",
    "PROCESS_CHANGED": "微信进程已变化，请重新读取。",
    "SNAPSHOT_UNSTABLE": "联系人库正在变化，未取得稳定副本，请稍后重试。",
    "DATABASE_INVALID": "联系人库或密钥校验失败，未读取任何结果。",
    "SCHEMA_UNSUPPORTED": "当前联系人库结构尚未适配。",
    "CANCELLED": "已取消联系人读取。",
    "TIMEOUT": "联系人读取超时，已结束辅助进程。",
    "READER_DISCONNECTED": "联系人读取进程已断开，请重新读取。",
    "READER_FAILED": "联系人读取失败，请检查微信登录状态及数据目录。",
    "INVALID_FRAME": "联系人读取通信校验失败。",
}
STAGES = {"starting": "正在连接读取进程", "scanning": "正在验证账号密钥",
          "snapshot": "正在获取联系人库副本", "reading": "正在读取联系人",
          "authorizing": "等待管理员授权", "exporting": "正在导出文件"}


class _ExportWorker(QThread):
    completed = Signal(object)

    def __init__(self, records, fmt, target, overwrite, parent=None):
        super().__init__(parent)
        self.records, self.fmt, self.target, self.overwrite = records, fmt, target, overwrite
        self.cancelled = threading.Event()

    def run(self):
        from .export import export_contacts
        try:
            paths = export_contacts(self.records, self.fmt, self.target,
                overwrite=self.overwrite, cancel=self.cancelled)
            result = {"success": True, "paths": paths}
        except Exception:
            result = {"success": False, "cancelled": self.cancelled.is_set()}
        self.completed.emit(result)


class ContactController(QObject):
    stateChanged = Signal()
    busyChanged = Signal()
    accountsChanged = Signal()
    filterChanged = Signal()
    elapsedChanged = Signal()
    exportFinished = Signal(object)
    overwriteRequested = Signal(object)
    actionFailed = Signal(str)

    def __init__(self, settings: QSettings, parent=None, *, reader=None,
                 operation_blocked=None, discover=None):
        super().__init__(parent)
        from .reader import discover_accounts
        from .client import ContactReaderClient
        self._settings = settings
        self._reader = reader or ContactReaderClient(self)
        self._discover = discover or discover_accounts
        self._operation_blocked = operation_blocked or (lambda: False)
        self._model = ContactTableModel(self)
        self._model.countsChanged.connect(self.stateChanged)
        self._accounts, self._selected = [], ""
        self._directory = str(settings.value("contacts/sourceDirectory", ""))
        self._discovery_directory = self._directory
        self._busy, self._phase, self._error = False, "idle", ""
        self._status = "等待读取联系人"
        self._requires_elevation = False
        self._keyword, self._include_special = "", False
        self._job_id, self._staging = "", []
        self._worker = None
        self._pending_export = None
        self._last_paths = []
        self._started_at, self._elapsed = 0.0, 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.elapsedChanged)
        self._reader.eventReceived.connect(self._on_event)

    @Property(QObject, constant=True)
    def model(self): return self._model

    @Property("QVariantList", notify=accountsChanged)
    def accounts(self): return [dict(account) for account in self._accounts]

    @Property(str, notify=accountsChanged)
    def selectedAccountId(self): return self._selected

    @selectedAccountId.setter
    def selectedAccountId(self, value):
        if self._busy or value == self._selected: return
        if value and not any(a["accountId"] == value for a in self._accounts): return
        self._selected = value
        self._pending_export = None
        self._model.clear()
        self._requires_elevation = False
        self._update_detected_directory()
        self.accountsChanged.emit()
        self.stateChanged.emit()

    @Property(str, notify=accountsChanged)
    def sourceDirectory(self): return self._directory

    @sourceDirectory.setter
    def sourceDirectory(self, value):
        if self._busy: return
        url = QUrl(value)
        value = url.toLocalFile() if url.isLocalFile() else value.strip()
        if value != self._directory or value != self._discovery_directory:
            self._pending_export = None
            self._requires_elevation = False
            self._directory = value
            self._discovery_directory = value
            self._settings.setValue("contacts/sourceDirectory", value)
            self._settings.sync()
            self._model.clear()
            self._selected = ""
            self.refreshAccounts()

    @Property(bool, notify=stateChanged)
    def operationBlocked(self): return bool(self._operation_blocked())

    @Property(bool, notify=stateChanged)
    def canRead(self): return bool(self._selected and not self._busy and not self.operationBlocked)

    @Property(bool, notify=busyChanged)
    def busy(self): return self._busy

    @Property(str, notify=stateChanged)
    def phase(self): return self._phase

    @Property(str, notify=stateChanged)
    def statusText(self): return self._status

    @Property(str, notify=stateChanged)
    def errorMessage(self): return self._error

    @Property(bool, notify=stateChanged)
    def requiresElevation(self): return self._requires_elevation

    @Property(str, notify=elapsedChanged)
    def elapsedText(self):
        elapsed = time.monotonic() - self._started_at if self._busy else self._elapsed
        seconds = max(0, int(elapsed))
        return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"

    @Property(int, notify=stateChanged)
    def totalCount(self): return self._model.totalCount

    @Property(int, notify=stateChanged)
    def visibleCount(self): return self._model.visibleCount

    @Property(str, notify=filterChanged)
    def keyword(self): return self._keyword

    @keyword.setter
    def keyword(self, value):
        if value == self._keyword: return
        self._keyword = value
        self._model.set_keyword(value)
        self.filterChanged.emit()
        self.stateChanged.emit()

    @Property(bool, notify=filterChanged)
    def includeSpecial(self): return self._include_special

    @includeSpecial.setter
    def includeSpecial(self, value):
        if value == self._include_special: return
        self._include_special = value
        self._model.set_include_special(value)
        self.filterChanged.emit()
        self.stateChanged.emit()

    @Property("QStringList", notify=stateChanged)
    def lastExportPaths(self): return list(self._last_paths)

    @Property(str, notify=stateChanged)
    def exportFormat(self): return str(self._settings.value("contacts/exportFormat", "xlsx"))

    def _set_busy(self, busy):
        if busy == self._busy: return
        self._busy = busy
        if busy:
            self._started_at, self._elapsed = time.monotonic(), 0.0
            self._timer.start()
        else:
            self._elapsed = time.monotonic() - self._started_at
            self._timer.stop()
        self.busyChanged.emit()
        self.stateChanged.emit()
        self.elapsedChanged.emit()

    @Slot()
    def environmentChanged(self):
        self.stateChanged.emit()

    def _update_detected_directory(self):
        if self._discovery_directory:
            return
        selected = next((a for a in self._accounts if a["accountId"] == self._selected), None)
        directory = Path(selected["directory"]) if selected else None
        if directory is not None and directory.parent.name.casefold() == "xwechat_files":
            directory = directory.parent
        self._directory = str(directory) if directory is not None else ""

    @Slot()
    def detectSourceDirectory(self):
        if self._busy:
            return
        if self._discovery_directory:
            self.sourceDirectory = ""
        else:
            self.refreshAccounts()

    @Slot()
    def refreshAccounts(self):
        if self._busy: return
        try:
            # The displayed auto-detected path must not narrow future scans.
            accounts = self._discover(self._discovery_directory)
            previous = next((a for a in self._accounts if a["accountId"] == self._selected), None)
            selected = next((a for a in accounts if a["accountId"] == self._selected), None)
            if previous != selected:
                self._pending_export = None
                self._requires_elevation = False
                self._model.clear()
            self._accounts = accounts
            if selected is None: self._selected = accounts[0]["accountId"] if accounts else ""
            self._error = "" if accounts else "未找到联系人库，请选择微信数据目录。"
        except Exception:
            self._pending_export = None
            self._requires_elevation = False
            self._accounts, self._selected = [], ""
            self._model.clear()
            self._error = "无法访问数据目录。"
        self._update_detected_directory()
        self.accountsChanged.emit()
        self.stateChanged.emit()

    @Slot(result=bool)
    def readContacts(self): return self._read(False)

    @Slot(result=bool)
    def readAsAdministrator(self):
        return self._read(True) if self._requires_elevation else False

    def _read(self, elevated):
        if not self.canRead: return False
        self._pending_export = None
        account = next(a for a in self._accounts if a["accountId"] == self._selected)
        self._error, self._staging, self._job_id = "", [], uuid.uuid4().hex
        self._phase = "authorizing" if elevated else "starting"
        self._status = STAGES[self._phase]
        self._requires_elevation = False
        self._set_busy(True)
        try:
            self._reader.start(dict(account), self._job_id, elevated=elevated)
        except Exception:
            self._on_event("contacts.finished", {"jobId": self._job_id, "success": False,
                "code": "READER_FAILED"})
            return False
        return True

    @Slot(str, object)
    def _on_event(self, method, value):
        if not self._busy or not isinstance(value, dict) or value.get("jobId") != self._job_id:
            return
        if method == "contacts.progress":
            stage = value.get("stage", "reading")
            self._phase = stage if stage in STAGES else "reading"
            self._status = STAGES[self._phase]
            self.stateChanged.emit()
        elif method == "contacts.rows":
            rows = value.get("rows")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                self.cancel()
                return
            self._staging.extend(dict(row) for row in rows)
        elif method == "contacts.finished":
            if value.get("success") and value.get("count") == len(self._staging):
                self._model.replace_records(self._staging)
                self._phase, self._status = "ready", f"已读取 {self._model.totalCount} 条记录"
                self._error = ""
            else:
                code = value.get("code", "READER_FAILED")
                self._phase = "cancelled" if code == "CANCELLED" else "error"
                self._error = ERRORS.get(code, ERRORS["READER_FAILED"])
                self._status = self._error
                self._requires_elevation = code == "ACCESS_DENIED"
            self._staging = []
            self._set_busy(False)

    @Slot()
    def cancel(self):
        if not self._busy: return
        self._status = "正在取消并清理"
        self.stateChanged.emit()
        if self._worker is not None:
            self._worker.cancelled.set()
        else:
            self._reader.cancel()

    @Slot()
    def clear(self):
        if self._busy: return
        self._pending_export = None
        self._requires_elevation = False
        self._model.clear()
        self._last_paths = []
        self._phase, self._status, self._error = "idle", "等待读取联系人", ""
        self.stateChanged.emit()

    @Slot(int, bool)
    def sort(self, column, ascending):
        self._model.sort(column, Qt.AscendingOrder if ascending else Qt.DescendingOrder)

    @Slot(int, int)
    def copyCell(self, row, column):
        if self.operationBlocked: return
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.clipboard().setText(self._model.text(row, column))

    @Slot(str, str, result=bool)
    @Slot(str, str, bool, result=bool)
    def exportContacts(self, fmt, target_url, overwrite=False):
        if self._busy or self.operationBlocked or not self.visibleCount: return False
        if fmt not in ("csv", "json", "xlsx", "all"): return False
        url = QUrl(target_url)
        if not Path(target_url).is_absolute() and url.scheme() and not url.isLocalFile(): return False
        target = Path(url.toLocalFile() if url.isLocalFile() else target_url)
        if not str(target_url).strip() or not target.is_absolute(): return False
        records = self._model.snapshot()
        paths = [target / ("微信联系人." + ext) for ext in ("csv", "json", "xlsx")] if fmt == "all" else [target]
        existing = [str(p) for p in paths if p.exists()]
        if existing and not overwrite:
            self._pending_export = (records, fmt, target)
            self.overwriteRequested.emit(existing)
            return False
        return self._export(records, fmt, target, overwrite)

    @Slot(result=bool)
    def confirmOverwrite(self):
        if not self._pending_export or self._busy or self.operationBlocked: return False
        records, fmt, target = self._pending_export
        self._pending_export = None
        return self._export(records, fmt, target, True)

    def _export(self, records, fmt, target, overwrite):
        target = target.resolve()
        for account in self._accounts:
            source = Path(account["contactDb"])
            protected = [source, source.with_name(source.name + "-wal"),
                         source.with_name(source.name + "-shm")]
            if any(target == path.resolve() for path in protected):
                self._error = "不能覆盖微信联系人数据库或旁路文件，请选择其他保存位置。"
                self.stateChanged.emit()
                self.actionFailed.emit(self._error)
                return False
        self._phase, self._status, self._error = "exporting", STAGES["exporting"], ""
        self._settings.setValue("contacts/exportFormat", fmt)
        self._settings.sync()
        self._set_busy(True)
        worker = _ExportWorker(records, fmt, target, overwrite, self)
        self._worker = worker
        worker.completed.connect(self._on_export_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return True

    @Slot(object)
    def _on_export_completed(self, value):
        worker = self._worker
        if worker is not None: worker.wait(1000)
        self._worker = None
        if value.get("success"):
            self._last_paths = list(value["paths"])
            self._phase, self._status = "ready", "联系人导出完成"
            self.exportFinished.emit(self._last_paths)
        else:
            self._phase = "cancelled" if value.get("cancelled") else "error"
            self._error = "已取消文件导出。" if value.get("cancelled") else "导出失败，请检查保存位置、权限及文件是否被占用。"
            self._status = self._error
            self.actionFailed.emit(self._error)
        self._set_busy(False)

    @Slot()
    def openExportFolder(self):
        if self._last_paths:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._last_paths[0]).parent)))

    def close(self):
        if self._reader.close() is False:
            return False
        if self._worker is not None:
            self._worker.cancelled.set()
            if not self._worker.wait(3000):
                return False
            self._worker = None
        self._timer.stop()
        return True
