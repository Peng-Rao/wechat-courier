def test_backend_has_contacts_and_contact_busy_blocks_task(backend):
    assert hasattr(backend, "contacts"), "missing third workspace controller"
    assert backend.contacts is backend.contacts
    assert not backend.operationBusy
    backend.contacts._set_busy(True)
    assert backend.operationBusy
    assert not backend.task._start("message_send", [{"itemId": "x", "target": "filehelper"}], {})
    assert "联系人" in backend.task.error
    backend.contacts._set_busy(False)


def test_contact_guard_does_not_require_uia_health(backend):
    assert hasattr(backend, "contacts"), "missing third workspace controller"
    assert not backend.agent.automationReady
    assert not backend.contacts.operationBlocked
    backend.task._set_active(True)
    assert backend.contacts.operationBlocked
    backend.task._set_active(False)
    backend.shutdown()


def test_manual_wechat_restart_locks_contacts_until_terminal_notice(qapp, tmp_path):
    from tests.test_v3_controllers import make_backend
    backend, client = make_backend(tmp_path)
    try:
        assert not backend.contacts.operationBlocked
        backend.agent.call("recovery.approve", {"decision": "restart_wechat", "loginTimeout": 90})
        assert backend.contacts.operationBlocked
        assert not backend.agent.canStartTask
        client.notificationReceived.emit("agent.status", {"status": "idle"})
        assert backend.contacts.operationBlocked
        client.notificationReceived.emit("agent.status", {"status": "recovered"})
        assert not backend.contacts.operationBlocked
        request = backend.agent.call("recovery.approve", {"decision": "restart_wechat"})
        client.rpcError.emit(request, -32000, "rejected")
        assert not backend.contacts.operationBlocked
    finally:
        backend.shutdown()


def test_legacy_stop_keeps_contacts_locked_until_worker_exits(backend, monkeypatch):
    backend.friendListText = "filehelper"
    backend.templateText = "test"
    backend.start_sending()
    worker = backend._worker
    monkeypatch.setattr(worker, "isRunning", lambda: True)
    backend.stop_sending()
    assert backend.contacts.operationBlocked
    assert backend.operationBusy
    updates = []
    backend.contacts.stateChanged.connect(lambda: updates.append(True))
    monkeypatch.setattr(worker, "isRunning", lambda: False)
    worker.finished.emit()
    assert not backend.contacts.operationBlocked
    assert not backend.operationBusy
    assert updates


def test_legacy_reset_does_not_disown_worker_after_failed_wait(backend, monkeypatch):
    backend.friendListText = "filehelper"
    backend.templateText = "test"
    backend.start_sending()
    worker = backend._worker
    monkeypatch.setattr(worker, "isRunning", lambda: True)
    monkeypatch.setattr(worker, "wait", lambda _timeout: False)
    backend.reset()
    assert backend._worker is worker
    assert backend.contacts.operationBlocked and backend.operationBusy
    monkeypatch.setattr(worker, "isRunning", lambda: False)
    worker.finished.emit()


def test_contacts_block_manual_agent_inspection_and_restart(qapp, tmp_path):
    from tests.test_v3_controllers import make_backend
    backend, client = make_backend(tmp_path)
    try:
        backend.contacts._set_busy(True)
        previous_calls = len(client.calls)
        assert backend.agent.inspect() == 0
        backend.agent.restart()
        assert backend.agent.operationBlocked
        assert len(client.calls) == previous_calls and client.restart_count == 0
        assert backend.agent.call("recovery.approve", {"decision": "restart_wechat", "scope": "gate"}) == 0
        assert len(client.calls) == previous_calls
        backend.contacts._set_busy(False)
        assert not backend.agent.operationBlocked
        assert backend.agent.inspect() > 0
        backend.agent.restart()
        assert client.restart_count == 1
    finally:
        backend.contacts._set_busy(False)
        backend.shutdown()
