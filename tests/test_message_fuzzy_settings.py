from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings

from app.agent.contracts import TaskRequest
from app.controllers import MessageController
from app.friend_import import load_friend_records
from tests.test_v3_controllers import make_backend, settings


KEY = "message/fuzzySearchEnabled"


def test_legacy_task_options_default_to_exact_message_search():
    from app.agent.contracts import TaskOptions, TaskRequest

    assert TaskOptions().fuzzy_search_enabled is False
    assert TaskOptions.from_payload(None).fuzzy_search_enabled is False
    assert TaskRequest.from_payload({
        "taskId": "legacy", "kind": "message_send",
        "items": [{"itemId": "one", "target": "Alice", "message": "hello"}],
    }).options.fuzzy_search_enabled is False


@pytest.mark.parametrize("enabled", [False, True])
def test_message_contract_accepts_literal_fuzzy_search_boolean(enabled):
    from app.agent.contracts import TaskOptions, TaskRequest

    assert TaskOptions(fuzzy_search_enabled=enabled).fuzzy_search_enabled is enabled
    request = TaskRequest.from_payload({
        "taskId": "fuzzy", "kind": "message_send",
        "items": [{"itemId": "one", "target": "Alice", "message": "hello"}],
        "options": {"fuzzySearchEnabled": enabled},
    })
    assert request.options.fuzzy_search_enabled is enabled


@pytest.mark.parametrize("invalid", [1, 0, -1, 1.0, "true", "false", "1", "", None, [], {}])
@pytest.mark.parametrize("source", ["direct", "options_payload", "request_payload"])
def test_fuzzy_search_contract_rejects_non_boolean(invalid, source):
    from app.agent.contracts import ContractError, TaskOptions, TaskRequest

    with pytest.raises(ContractError, match="fuzzySearchEnabled"):
        if source == "direct":
            TaskOptions(fuzzy_search_enabled=invalid)
        elif source == "options_payload":
            TaskOptions.from_payload({"fuzzySearchEnabled": invalid})
        else:
            TaskRequest.from_payload({
                "taskId": "fuzzy", "kind": "message_send", "items": [],
                "options": {"fuzzySearchEnabled": invalid},
            })


@pytest.mark.parametrize("source", ["direct", "payload"])
def test_friend_request_rejects_enabled_fuzzy_search(source):
    from app.agent.contracts import ContractError, TaskOptions, TaskRequest

    with pytest.raises(ContractError, match="fuzzySearchEnabled"):
        if source == "direct":
            TaskRequest("friend-fuzzy", "friend_add", (), TaskOptions(fuzzy_search_enabled=True))
        else:
            TaskRequest.from_payload({
                "taskId": "friend-fuzzy", "kind": "friend_add",
                "items": [{"itemId": "one", "account": "wxid_fuzzy_test0001"}],
                "options": {"fuzzySearchEnabled": True},
            })


@pytest.mark.parametrize("options", [{}, {"fuzzySearchEnabled": False}])
def test_friend_request_accepts_disabled_or_omitted_fuzzy_search(options):
    from app.agent.contracts import TaskOptions, TaskRequest

    assert TaskRequest("friend-exact", "friend_add", (), TaskOptions()).options.fuzzy_search_enabled is False
    request = TaskRequest.from_payload({
        "taskId": "friend-exact", "kind": "friend_add",
        "items": [{"itemId": "one", "account": "wxid_fuzzy_test0001"}],
        "options": options,
    })
    assert request.options.fuzzy_search_enabled is False


class RecordingSettings(QSettings):
    def __init__(self, path):
        super().__init__(str(path), QSettings.IniFormat)
        self.writes = []
        self.syncs = 0

    def setValue(self, key, value):
        self.writes.append((key, value))
        super().setValue(key, value)

    def sync(self):
        self.syncs += 1
        super().sync()


def start_task(backend, client, kind):
    if kind == "message_send":
        backend.message.recipientsText = "Alice"
        backend.message.templateText = "Hello {name}"
        assert backend.task.startMessage()
    else:
        client.helloReceived.emit({"capabilities": {"friendSubmitEnabled": True}})
        backend.friends.model.replace_records(load_friend_records(
            [["\u59d3\u540d", "\u8d26\u53f7"], ["Test", "wxid_fuzzy_test0001"]]))
        backend.friends.model.selectFirstValid()
        assert backend.task.startFriends()
    return client.calls[-1][2]


def finish_task(client, payload):
    client.notificationReceived.emit("task.finished", {
        "taskId": payload["taskId"], "outcome": "stopped",
        "done": 0, "total": len(payload["items"]),
    })


def test_fuzzy_search_defaults_off_without_writing_settings(tmp_path, qapp):
    stored = RecordingSettings(tmp_path / "message.ini")
    message = MessageController(stored)
    assert message.fuzzySearchEnabled is False
    message.fuzzySearchEnabled = False
    assert not stored.contains(KEY)
    assert stored.writes == []
    assert stored.syncs == 0


@pytest.mark.parametrize("raw, expected", [
    (True, True), (False, False), ("true", True), ("false", False),
    ("1", False), ("0", False), (1, False), (0, False), (1.0, False),
    (None, False), ("", False), ("yes", False), ("garbage", False),
    (" true ", False), ([], False), ({"enabled": True}, False),
])
def test_fuzzy_search_restores_only_safe_settings_values(tmp_path, qapp, raw, expected):
    stored = RecordingSettings(tmp_path / "message.ini")
    stored.setValue(KEY, raw)
    stored.writes.clear()
    assert MessageController(stored).fuzzySearchEnabled is expected
    assert stored.writes == []
    assert stored.syncs == 0


def test_fuzzy_search_persists_and_notifies_only_changes(tmp_path, qapp):
    path = tmp_path / "message.ini"
    stored = RecordingSettings(path)
    message = MessageController(stored)
    changes = []
    message.fuzzySearchEnabledChanged.connect(changes.append)

    message.fuzzySearchEnabled = True
    message.fuzzySearchEnabled = True
    assert message.fuzzySearchEnabled is True
    assert MessageController(QSettings(str(path), QSettings.IniFormat)).fuzzySearchEnabled is True
    assert changes == [True]
    assert stored.writes == [(KEY, True)]
    assert stored.syncs == 1

    message.fuzzySearchEnabled = False
    message.fuzzySearchEnabled = False
    assert MessageController(QSettings(str(path), QSettings.IniFormat)).fuzzySearchEnabled is False
    assert changes == [True, False]
    assert stored.writes == [(KEY, True), (KEY, False)]
    assert stored.syncs == 2


@pytest.mark.parametrize("value", [1, 0, 1.0, "true", "false", None, [], {}])
def test_fuzzy_search_setter_does_not_enable_from_non_boolean(tmp_path, qapp, value):
    message = MessageController(settings(tmp_path))
    changes = []
    message.fuzzySearchEnabledChanged.connect(changes.append)
    message.fuzzySearchEnabled = value
    assert message.fuzzySearchEnabled is False
    assert not settings(tmp_path).contains(KEY)
    assert changes == []


@pytest.mark.parametrize("kind", ["message_send", "friend_add"])
@pytest.mark.parametrize("enabled", [False, True])
def test_fuzzy_search_locked_for_all_active_task_phases(tmp_path, qapp, kind, enabled):
    backend, client = make_backend(tmp_path)
    try:
        backend.message.fuzzySearchEnabled = enabled
        changes = []
        backend.message.fuzzySearchEnabledChanged.connect(changes.append)
        payload = start_task(backend, client, kind)
        if kind == "friend_add":
            assert "fuzzySearchEnabled" not in payload["options"]
            TaskRequest.from_payload(payload)
        for phase in ["running", "pausing", "paused", "stopping", "recovering",
                      "awaiting_recovery", "waiting_login"]:
            backend.task._set_phase(phase)
            assert backend.task.active
            backend.message.fuzzySearchEnabled = not enabled
            assert backend.message.fuzzySearchEnabled is enabled
            assert settings(tmp_path).value(KEY, False, type=bool) is enabled
            assert changes == []
        finish_task(client, payload)
        backend.message.fuzzySearchEnabled = not enabled
        assert backend.message.fuzzySearchEnabled is (not enabled)
        assert changes == [not enabled]
    finally:
        backend.shutdown()


@pytest.mark.parametrize("enabled", [False, True])
def test_message_start_snapshots_fuzzy_search_without_changing_template(tmp_path, qapp, enabled):
    backend, client = make_backend(tmp_path)
    try:
        backend.message.fuzzySearchEnabled = enabled
        payload = start_task(backend, client, "message_send")
        assert payload["options"]["fuzzySearchEnabled"] is enabled
        assert TaskRequest.from_payload(payload).options.fuzzy_search_enabled is enabled
        assert payload["items"][0]["target"] == "Alice"
        assert payload["items"][0]["message"] == "Hello Alice"
        assert backend.message.previewMessage == "Hello Alice"
        finish_task(client, payload)
        backend.message.fuzzySearchEnabled = not enabled
        assert payload["options"]["fuzzySearchEnabled"] is enabled
        assert backend.task._original_payload["options"]["fuzzySearchEnabled"] is enabled
        next_payload = start_task(backend, client, "message_send")
        assert next_payload["options"]["fuzzySearchEnabled"] is (not enabled)
    finally:
        backend.shutdown()


def test_fuzzy_search_unlocks_after_agent_rejects_start(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    try:
        payload = start_task(backend, client, "message_send")
        request_id = client.calls[-1][0]
        client.rpcError.emit(request_id, -32602, "rejected")
        assert not backend.task.active
        backend.message.fuzzySearchEnabled = True
        assert backend.message.fuzzySearchEnabled is True
        assert payload["options"]["fuzzySearchEnabled"] is False
    finally:
        backend.shutdown()


def test_fuzzy_search_acceptance_metadata_notifies_and_keeps_snapshot(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("WECHAT_COURIER_ACCEPTANCE", "1")
    backend, client = make_backend(tmp_path)
    try:
        changes = []
        backend.task.acceptanceStateChanged.connect(lambda: changes.append(True))
        assert backend.task.acceptanceMessageState["options"]["fuzzySearchEnabled"] is False
        backend.message.fuzzySearchEnabled = True
        assert len(changes) == 1
        assert json.loads(backend.task.acceptanceMessageStateJson)["options"]["fuzzySearchEnabled"] is True
        assert "fuzzySearchEnabled" not in backend.task.acceptanceFriendState["options"]
        backend.message.fuzzySearchEnabled = True
        assert len(changes) == 1
        payload = start_task(backend, client, "message_send")
        finish_task(client, payload)
        backend.message.fuzzySearchEnabled = False
        snapshot = json.loads(backend.task.acceptanceTaskStateJson)
        assert snapshot["echoedOptions"]["fuzzySearchEnabled"] is True
        assert backend.task.acceptanceMessageState["options"]["fuzzySearchEnabled"] is False
        snapshot["echoedOptions"]["fuzzySearchEnabled"] = False
        assert backend.task.acceptanceTaskState["echoedOptions"]["fuzzySearchEnabled"] is True
    finally:
        backend.shutdown()


def test_safe_message_retry_preserves_original_fuzzy_option(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    try:
        backend.message.fuzzySearchEnabled = True
        payload = start_task(backend, client, "message_send")
        client.notificationReceived.emit("task.event", {
            "taskId": payload["taskId"], "itemId": payload["items"][0]["itemId"],
            "step": "search_ready", "outcome": "error", "detail": "not ready",
            "done": 1, "total": 1, "recoverable": True,
            "destructiveBoundaryCrossed": False, "errorCode": "TRANSIENT_UI",
        })
        client.notificationReceived.emit("task.finished", {
            "taskId": payload["taskId"], "outcome": "error", "done": 1, "total": 1,
        })
        backend.message.fuzzySearchEnabled = False
        assert backend.task.retryFailedItem()
        assert client.calls[-1][2]["options"]["fuzzySearchEnabled"] is True
    finally:
        backend.shutdown()
