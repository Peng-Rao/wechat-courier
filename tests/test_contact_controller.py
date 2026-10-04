import importlib.util
import time

import pytest
from PySide6.QtCore import QObject, QSettings, Signal


class FakeReader(QObject):
    eventReceived = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.cancelled = False

    def start(self, account, job_id, *, elevated=False):
        self.calls.append((account, job_id, elevated))

    def cancel(self):
        self.cancelled = True

    def close(self):
        self.cancel()


@pytest.fixture
def contacts(qapp, tmp_path):
    assert importlib.util.find_spec("app.contacts"), "contact subsystem is missing"
    from app.contacts.controller import ContactController

    reader = FakeReader()
    blocked = {"value": False}
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    account = {"accountId": "test-account", "label": "test-account",
               "directory": str(tmp_path), "contactDb": str(tmp_path / "contact.db")}
    ctrl = ContactController(settings, reader=reader,
        operation_blocked=lambda: blocked["value"], discover=lambda _: [account])
    ctrl.refreshAccounts()
    yield ctrl, reader, blocked, settings
    ctrl.close()


def finish(ctrl, reader, records=None, **result):
    job = reader.calls[-1][1]
    if records is not None:
        reader.eventReceived.emit("contacts.rows", {"jobId": job, "rows": records})
    reader.eventReceived.emit("contacts.finished", {"jobId": job,
        "success": True, "count": len(records or []), **result})


def test_read_locks_until_complete_and_ignores_old_job(contacts):
    ctrl, reader, blocked, _ = contacts
    assert ctrl.canRead
    assert ctrl.readContacts()
    assert ctrl.busy and not ctrl.canRead
    reader.eventReceived.emit("contacts.finished", {"jobId": "old", "success": True})
    assert ctrl.busy
    finish(ctrl, reader, [{"username": "wxid_a", "nick_name": "甲", "category": "friend"}])
    assert not ctrl.busy and ctrl.visibleCount == 1
    blocked["value"] = True
    assert not ctrl.canRead and not ctrl.readContacts()
    assert len(reader.calls) == 1


def test_close_retains_busy_reader_until_confirmed_exit(contacts, monkeypatch):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    monkeypatch.setattr(reader, "close", lambda: False)
    assert ctrl.close() is False
    assert ctrl.busy and ctrl._timer.isActive()


def test_close_keeps_running_export_owned_and_is_bounded(contacts):
    from types import SimpleNamespace
    import threading
    ctrl, _, _, _ = contacts
    waits = []
    worker = SimpleNamespace(cancelled=threading.Event(), wait=lambda timeout: waits.append(timeout) or False)
    ctrl._worker = worker
    ctrl._set_busy(True)
    try:
        assert ctrl.close() is False
        assert waits == [3000]
        assert worker.cancelled.is_set() and ctrl._worker is worker and ctrl.busy
    finally:
        ctrl._worker = None
        ctrl._set_busy(False)


def test_denied_requires_explicit_elevation_and_cancel_retains_table(contacts):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, success=False, code="ACCESS_DENIED")
    assert ctrl.requiresElevation and not ctrl.busy
    assert ctrl.readAsAdministrator()
    assert reader.calls[-1][2]
    ctrl.cancel()
    assert reader.cancelled and ctrl.busy
    finish(ctrl, reader, success=False, code="CANCELLED")
    assert not ctrl.busy and ctrl.phase == "cancelled"


def test_export_freezes_filter_and_remains_mutually_exclusive(contacts, qapp, tmp_path):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, [{"username": "wxid_a", "nick_name": "甲", "category": "friend"},
                         {"username": "wxid_b", "nick_name": "乙", "category": "friend"}])
    ctrl.keyword = "甲"
    assert ctrl.exportContacts("json", str(tmp_path / "联系人.json"))
    ctrl.keyword = "乙"
    until = time.monotonic() + 5
    while ctrl.busy and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(.01)
    assert not ctrl.busy
    import json
    records = json.loads((tmp_path / "联系人.json").read_text(encoding="utf-8"))
    assert len(records) == 1 and records[0]["username"] == "wxid_a"
    assert ctrl.lastExportPaths


def test_overwrite_requires_confirmation(contacts, qapp, tmp_path):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, [{"username": "wxid_a", "category": "friend"}])
    target = tmp_path / "existing.json"
    target.write_text("original", encoding="utf-8")
    prompts = []
    ctrl.overwriteRequested.connect(prompts.append)
    assert not ctrl.exportContacts("json", str(target))
    assert prompts and target.read_text() == "original"
    assert ctrl.confirmOverwrite()
    until = time.monotonic() + 5
    while ctrl.busy and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(.01)
    assert not ctrl.busy and target.read_text() != "original"


def test_account_change_clears_data_and_settings_keep_no_contacts(contacts, tmp_path):
    ctrl, reader, _, settings = contacts
    ctrl.readContacts()
    finish(ctrl, reader, [{"username": "secret-id", "category": "friend"}])
    ctrl.sourceDirectory = str(tmp_path / "other")
    assert ctrl.totalCount == 0
    settings.sync()
    assert "secret-id" not in settings.fileName()
    assert not any("key" in key.lower() or "records" in key.lower() for key in settings.allKeys())


def test_changing_data_directory_requires_fresh_access_denial_before_elevation(contacts, tmp_path):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, success=False, code="ACCESS_DENIED")
    assert ctrl.requiresElevation
    ctrl.sourceDirectory = str(tmp_path / "other")
    assert not ctrl.requiresElevation and not ctrl.readAsAdministrator()


@pytest.mark.parametrize("reset", ["clear", "source", "account", "read"])
def test_pending_overwrite_does_not_survive_data_reset(contacts, tmp_path, reset):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, [{"username": "private-account-a", "category": "friend"}])
    target = tmp_path / "old.json"
    target.write_text("original", encoding="utf-8")
    assert not ctrl.exportContacts("json", str(target))
    if reset == "clear":
        ctrl.clear()
    elif reset == "source":
        ctrl.sourceDirectory = str(tmp_path / "other")
    elif reset == "account":
        ctrl.selectedAccountId = ""
    else:
        ctrl.readContacts()
        finish(ctrl, reader, [])
    assert not ctrl.confirmOverwrite()
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("sidecar", ["", "-wal", "-shm"])
def test_export_never_replaces_contact_database_or_sidecars(contacts, tmp_path, sidecar):
    ctrl, reader, _, _ = contacts
    ctrl.readContacts()
    finish(ctrl, reader, [{"username": "wxid_a", "category": "friend"}])
    target = tmp_path / ("contact.db" + sidecar)
    target.write_bytes(b"encrypted source")
    assert not ctrl.exportContacts("json", str(target), True)
    assert target.read_bytes() == b"encrypted source"
    assert not ctrl.busy
