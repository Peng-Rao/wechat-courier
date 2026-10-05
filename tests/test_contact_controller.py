import importlib.util
import time
from pathlib import Path

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


@pytest.mark.parametrize("code", ["KEY_NOT_FOUND", "KEY_VALIDATION_FAILED", "KEY_SCAN_LIMIT"])
def test_key_failures_never_request_login_or_elevation(contacts, code):
    ctrl, reader, _, _ = contacts
    assert ctrl.readContacts()
    finish(ctrl, reader, success=False, code=code)
    assert not ctrl.requiresElevation and not ctrl.readAsAdministrator()
    assert "登录" not in ctrl.errorMessage
    assert {"KEY_NOT_FOUND": "未找到", "KEY_VALIDATION_FAILED": "校验", "KEY_SCAN_LIMIT": "上限"}[code] in ctrl.errorMessage
    assert ctrl.canRead


@pytest.mark.parametrize("stage", ["process", "snapshot", "keys", "validating", "contacts"])
def test_contact_read_progress_uses_distinct_stages_and_safe_diagnostics(contacts, stage):
    ctrl, reader, _, _ = contacts
    assert ctrl.readContacts()
    job = reader.calls[-1][1]
    reader.eventReceived.emit("contacts.progress", {"jobId": job, "stage": stage,
        "diagnostics": {"stage": stage, "strategy": "wcdb", "memoryReads": 5,
            "key": "PRIVATE", "path": "PRIVATE", "records": ["PRIVATE"]}})
    assert ctrl.phase == stage
    assert ctrl.diagnostics["memoryReads"] == 5
    assert "PRIVATE" not in repr(ctrl.diagnostics)
    reader.eventReceived.emit("contacts.progress", {"jobId": "stale", "stage": "keys"})
    assert ctrl.phase == stage
    finish(ctrl, reader, success=False, code="KEY_NOT_FOUND")
    assert ctrl.diagnostics["memoryReads"] == 5
    ctrl.clear()
    assert ctrl.diagnostics == {}


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


@pytest.fixture
def discovered_contacts(qapp, tmp_path, monkeypatch):
    from app.contacts.controller import ContactController
    from app.contacts import reader as contact_reader
    from tests.test_contact_reader import contact_db

    documents, profile = tmp_path / "documents", tmp_path / "profile"
    roots = [documents / "xwechat_files", profile / "xwechat_files"]
    contact_db(roots[0] / "wxid_first")
    contact_db(roots[1] / "wxid_second")
    monkeypatch.setattr(contact_reader, "_documents_directory", lambda: documents)
    monkeypatch.setenv("USERPROFILE", str(profile))
    settings = QSettings(str(tmp_path / "discovery.ini"), QSettings.IniFormat)
    helper = FakeReader()
    ctrl = ContactController(settings, reader=helper)
    yield ctrl, helper, settings, roots
    ctrl.close()


def test_auto_discovery_fills_directory_without_reading_contacts(discovered_contacts):
    ctrl, helper, settings, roots = discovered_contacts
    seen = []
    ctrl.accountsChanged.connect(lambda: seen.append(ctrl.sourceDirectory))
    ctrl.refreshAccounts()
    assert ctrl.sourceDirectory == str(roots[0])
    assert seen == [str(roots[0])]
    assert ctrl.canRead and len(ctrl.accounts) == 2
    assert not helper.calls
    # Automatically detected paths must not narrow the next discovery pass.
    assert settings.value("contacts/sourceDirectory", "") == ""
    ctrl.refreshAccounts()
    assert len(ctrl.accounts) == 2


def test_auto_directory_follows_account_and_survives_controller_recreation(discovered_contacts):
    from app.contacts.controller import ContactController

    ctrl, helper, settings, roots = discovered_contacts
    ctrl.refreshAccounts()
    ctrl.selectedAccountId = ctrl.accounts[1]["accountId"]
    assert ctrl.sourceDirectory == str(roots[1])
    restored = ContactController(settings, reader=FakeReader())
    try:
        restored.refreshAccounts()
        assert len(restored.accounts) == 2
        assert restored.sourceDirectory == str(roots[0])
        assert not helper.calls
    finally:
        restored.close()


def test_manual_directory_is_preserved_until_auto_detect_is_requested(discovered_contacts):
    ctrl, helper, settings, roots = discovered_contacts
    ctrl.sourceDirectory = str(roots[1])
    assert ctrl.sourceDirectory == str(roots[1]) and len(ctrl.accounts) == 1
    ctrl.refreshAccounts()
    assert ctrl.sourceDirectory == str(roots[1])
    assert settings.value("contacts/sourceDirectory") == str(roots[1])
    ctrl.detectSourceDirectory()
    assert ctrl.sourceDirectory == str(roots[0]) and len(ctrl.accounts) == 2
    assert settings.value("contacts/sourceDirectory", "") == ""
    assert not helper.calls


def test_choosing_displayed_auto_directory_explicitly_limits_scan(discovered_contacts):
    ctrl, _, settings, roots = discovered_contacts
    ctrl.refreshAccounts()
    assert len(ctrl.accounts) == 2
    ctrl.sourceDirectory = ctrl.sourceDirectory
    assert len(ctrl.accounts) == 1
    assert settings.value("contacts/sourceDirectory") == str(roots[0])


def test_auto_detect_does_not_change_source_during_read(discovered_contacts):
    ctrl, helper, settings, roots = discovered_contacts
    ctrl.sourceDirectory = str(roots[1])
    assert ctrl.readContacts()
    ctrl.detectSourceDirectory()
    assert ctrl.sourceDirectory == str(roots[1])
    assert settings.value("contacts/sourceDirectory") == str(roots[1])
    assert len(helper.calls) == 1


def test_auto_detect_clears_missing_manual_source_and_reports_no_accounts(discovered_contacts, tmp_path):
    ctrl, helper, settings, roots = discovered_contacts
    ctrl.sourceDirectory = str(tmp_path / "missing")
    assert not ctrl.accounts and ctrl.errorMessage
    ctrl.detectSourceDirectory()
    assert ctrl.sourceDirectory == str(roots[0]) and not ctrl.errorMessage
    # Remove only the synthetic fixtures, never a real database.
    for row in ctrl.accounts:
        Path(row["contactDb"]).unlink()
    ctrl.detectSourceDirectory()
    assert ctrl.sourceDirectory == "" and not ctrl.accounts
    assert not ctrl.canRead and ctrl.errorMessage
    assert not helper.calls
