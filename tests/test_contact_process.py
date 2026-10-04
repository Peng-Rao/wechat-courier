import json
import time

from PySide6.QtCore import QSettings


def wait_until(qapp, predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert predicate()


def test_real_reader_process_auth_stream_and_shutdown(qapp, tmp_path):
    from app.contacts.client import ContactReaderClient
    import sys
    code = ("from app.contacts.main import main; "
            "main(reader=lambda a,**kw: [{'username':'wxid_test','nick_name':'test','category':'friend'}]*300)")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "job-test")
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events))
    rows = [row for name, event in events if name == "contacts.rows" for row in event["rows"]]
    assert len(rows) == 300
    result = events[-1][1]
    assert result["success"] and result["count"] == 300
    assert all(event["jobId"] == "job-test" for _, event in events)
    assert client.processRunning is False
    assert not list(tmp_path.glob("bootstrap-*"))
    assert not any("key" in key.lower() for _, event in events for key in event)
    client.close()


def test_real_reader_cancel_is_bounded_and_does_not_touch_agent(qapp, tmp_path):
    from app.contacts.client import ContactReaderClient
    import sys
    code = ("import time; from app.contacts.main import main; "
            "main(reader=lambda a,**kw: (time.sleep(30) or []))")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "cancel-job")
    wait_until(qapp, lambda: any(name == "contacts.progress" for name, _ in events))
    started = time.monotonic()
    client.cancel()
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 6)
    assert time.monotonic() - started < 6
    assert events[-1][1]["code"] == "CANCELLED"
    assert not client.processRunning
    client.close()


def test_bootstrap_rejects_wrong_owner_without_exposing_token(tmp_path):
    from app.contacts.security import validate_bootstrap, current_user_sid, restrict_path
    target = tmp_path / "bootstrap.json"
    target.write_text(json.dumps({"schemaVersion": 1, "ownerSid": "S-1-0-0",
        "pipe": "fuge-contacts-test", "token": "s" * 64, "jobId": "test"}))
    restrict_path(target)
    import pytest
    with pytest.raises((ValueError, PermissionError)) as error:
        validate_bootstrap(target)
    assert "s" * 64 not in str(error.value)


def test_forged_pipe_handshake_cannot_read(qapp, tmp_path):
    from app.contacts.client import ContactReaderClient
    import sys
    code = ("import argparse,json; from PySide6.QtCore import QCoreApplication,QTimer; "
            "from PySide6.QtNetwork import QLocalSocket; "
            "p=argparse.ArgumentParser(); p.add_argument('--bootstrap'); args=p.parse_args(); "
            "c=json.load(open(args.bootstrap)); app=QCoreApplication([]); s=QLocalSocket(); "
            "s.connected.connect(lambda:s.write((json.dumps({'jsonrpc':'2.0','id':1,'method':'exporter.hello',"
            "'params':{'token':'wrong','jobId':c['jobId']}})+'\\n').encode())); "
            "s.connectToServer(c['pipe']); QTimer.singleShot(3000,app.quit); app.exec()")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "auth-job")
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 6)
    assert events[-1][1]["success"] is False
    assert not any(name == "contacts.rows" for name, _ in events)
    client.close()


def test_setup_failure_can_retry_without_stuck_job(qapp, tmp_path, monkeypatch):
    import sys
    import app.contacts.client as module
    client = module.ContactReaderClient(command=[sys.executable, "-c",
        "from app.contacts.main import main; main(reader=lambda a,**kw: [])"], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    with monkeypatch.context() as patch:
        patch.setattr(module, "private_directory", lambda *_: (_ for _ in ()).throw(PermissionError()))
        client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "bad")
    assert events[-1][1]["code"] == "ACCESS_DENIED"
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "good")
    wait_until(qapp, lambda: any(value.get("jobId") == "good" and name == "contacts.finished"
        for name, value in events))
    assert events[-1][1]["success"]
    client.close()


def test_oversized_contact_fails_without_hanging(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    client = ContactReaderClient(command=[sys.executable, "-c",
        "from app.contacts.main import main; main(reader=lambda a,**kw: [{'username':'x'*1100000}])"],
        bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "large")
    try:
        wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 5)
        assert events[-1][1]["success"] is False
        assert events[-1][1]["code"] == "DATABASE_INVALID"
    finally:
        client.close()


def test_stale_bootstrap_cleanup_only_removes_own_dead_job(tmp_path, monkeypatch):
    from app.contacts import security
    from app.contacts.native import current_job_identity
    root = security.private_directory(tmp_path, "bootstrap-")
    marker = {"schemaVersion": 1, "pipe": "fuge-contacts-test", "token": "a" * 64,
        "jobId": "stale", **current_job_identity(), "guiPid": 2147483000, "guiStartTime": 123}
    path = root / "launch.json"
    path.write_text(json.dumps(marker), encoding="utf-8")
    security.restrict_path(path)
    monkeypatch.setattr("app.contacts.native.process_start_time", lambda _: None)
    assert security.cleanup_bootstraps(tmp_path) == 1
    assert not root.exists()
    unknown = tmp_path / "bootstrap-unrelated"
    unknown.mkdir()
    (unknown / "keep").write_text("keep")
    assert security.cleanup_bootstraps(tmp_path) == 0
    assert (unknown / "keep").exists()


def test_helper_crash_discards_partial_results_and_allows_reconnect(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    client = ContactReaderClient(command=[sys.executable, "-c",
        "import os; os._exit(7)"], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    account = {"accountId": "test", "contactDb": str(tmp_path / "contact.db")}
    client.start(account, "crash")
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events))
    assert not events[-1][1]["success"] and not client.processRunning
    assert not list(tmp_path.glob("bootstrap-*"))
    client._command = [sys.executable, "-c",
        "from app.contacts.main import main; main(reader=lambda a,**kw: [])"]
    client.start(account, "reconnect")
    wait_until(qapp, lambda: any(name == "contacts.finished" and value.get("jobId") == "reconnect"
        for name, value in events))
    assert events[-1][1]["success"]
    client.close()


def test_read_deadline_only_terminates_its_helper(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    client = ContactReaderClient(command=[sys.executable, "-c",
        "import time; from app.contacts.main import main; main(reader=lambda a,**kw: (time.sleep(30) or []))"],
        bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "deadline")
    wait_until(qapp, lambda: any(name == "contacts.progress" for name, _ in events))
    client._deadline = time.monotonic() - 1
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 6)
    assert events[-1][1]["code"] == "TIMEOUT"
    assert not client.processRunning
    client.close()


def test_completion_with_heartbeats_cannot_extend_read_deadline(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    code = ("from PySide6.QtCore import QCoreApplication; QCoreApplication.quit=lambda:None; "
        "from app.contacts.main import main; main(reader=lambda a,**kw: [])")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "completed-hang")
    try:
        wait_until(qapp, lambda: client._result is not None)
        assert client.processRunning
        client._deadline = time.monotonic() - 1
        wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 6)
        assert events[-1][1]["code"] == "TIMEOUT"
        assert not client.processRunning
    finally:
        client.close()


def test_crashed_reader_encrypted_snapshot_is_cleaned_without_wechat(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    root = snapshots / ("wechat-contact-" + "c" * 32)
    code = ("import json,os; from pathlib import Path; "
        "from app.contacts.native import current_job_identity; "
        "from app.contacts.snapshot import _private_mkdir; "
        "owner=current_job_identity(); "
        f"root=Path({str(root)!r}); _private_mkdir(root,owner['ownerSid']); "
        "(root/'owner.json').write_text(json.dumps(dict(owner,kind='contact-snapshot',"
        "schemaVersion=1,job='c'*32))); (root/'contact.db').write_bytes(b'encrypted-fixture'); os._exit(7)")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path / "launch",
                                snapshot_root=snapshots)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "snapshot-crash")
    wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events))
    assert not root.exists()
    assert events[-1][1]["success"] is False
    client.close()
