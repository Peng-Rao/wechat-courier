from types import SimpleNamespace

import pytest

from app.contacts import security


class PipeKernel:
    def __init__(self, pid=123, available=True):
        self.pid, self.available = pid, available
        self.GetNamedPipeServerProcessId = self.peer_pid

    def peer_pid(self, _handle, pointer):
        pointer._obj.value = self.pid
        return self.available


class PeerProbe:
    def __init__(self, **changes):
        self.identity = SimpleNamespace(pid=123, start_time=456, sid="owner", session_id=2)
        for key, value in changes.items():
            setattr(self.identity, key, value)

    def current_identity(self):
        return "owner", 2

    def inspect(self, _pid):
        return self.identity


def config():
    return {"guiPid": 123, "guiStartTime": 456, "ownerSid": "owner"}


def test_pipe_server_is_original_gui_process():
    security.verify_pipe_server(99, config(), kernel=PipeKernel(), probe=PeerProbe())


@pytest.mark.parametrize("kernel,changes", [
    (PipeKernel(pid=789), {}), (PipeKernel(available=False), {}),
    (PipeKernel(), {"start_time": 789}), (PipeKernel(), {"sid": "other"}),
    (PipeKernel(), {"session_id": 3}), (PipeKernel(), {"pid": 789}),
])
def test_forged_or_reused_pipe_server_is_rejected(kernel, changes):
    with pytest.raises(PermissionError, match="Reader server identity"):
        security.verify_pipe_server(99, config(), kernel=kernel, probe=PeerProbe(**changes))


def test_service_verifies_server_before_sending_token(qapp, monkeypatch):
    from app.contacts import main
    sent, verified = [], []
    service = SimpleNamespace(config=config(), socket=SimpleNamespace(socketDescriptor=lambda: 99),
        _send=sent.append, _disconnected=lambda: verified.append("disconnected"))
    monkeypatch.setattr(main, "verify_pipe_server", lambda *_: (_ for _ in ()).throw(PermissionError()))
    main.ContactReaderService._connected(service)
    assert sent == []
    assert verified == ["disconnected"]


def test_real_helper_rejects_gui_start_time_mismatch(qapp, tmp_path):
    import sys
    from app.contacts.client import ContactReaderClient
    from tests.test_contact_process import wait_until
    code = ("import app.contacts.main as m; original=m.validate_bootstrap; "
            "m.validate_bootstrap=lambda p:dict(original(p),guiStartTime=1); "
            "m.main(reader=lambda a,**kw:[{'username':'must_not_be_read'}])")
    client = ContactReaderClient(command=[sys.executable, "-c", code], bootstrap_root=tmp_path)
    events = []
    client.eventReceived.connect(lambda name, value: events.append((name, value)))
    client.start({"accountId": "test", "contactDb": str(tmp_path / "contact.db")}, "wrong-server")
    try:
        wait_until(qapp, lambda: any(name == "contacts.finished" for name, _ in events), 6)
        assert not events[-1][1]["success"]
        assert not any(name in ("contacts.rows", "contacts.progress") for name, _ in events)
        assert not client.processRunning
    finally:
        client.close()


@pytest.mark.parametrize("field,value", [
    ("guiPid", None), ("guiPid", True), ("guiPid", 0),
    ("guiStartTime", None), ("guiStartTime", "123"), ("guiStartTime", -1),
])
def test_bootstrap_requires_strict_gui_identity(tmp_path, field, value):
    import json
    from app.contacts.native import current_job_identity
    identity = current_job_identity()
    bootstrap = {"schemaVersion": 1, "ownerSid": identity["ownerSid"],
        "pipe": "fuge-contacts-test", "token": "a" * 64, "jobId": "test",
        "guiPid": identity["pid"], "guiStartTime": identity["startTime"], field: value}
    target = tmp_path / "launch.json"
    target.write_text(json.dumps(bootstrap), encoding="utf-8")
    security.restrict_path(target)
    with pytest.raises(ValueError):
        security.validate_bootstrap(target)
