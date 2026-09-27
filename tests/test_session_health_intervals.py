from __future__ import annotations

import pytest

from app.agent.runtime import TaskControl
from tests.test_task_stop_recovery import RecoveryDriver, make_engine, make_request
from tests.test_v3_controllers import make_backend
from tests.test_v032_controllers import health, status, start_message, event, finish


@pytest.mark.parametrize("edits, expected", [
    ([("intervalMin", 30), ("intervalMax", 40)], (30, 40)),
    ([("intervalMax", 40), ("intervalMin", 30)], (30, 40)),
    ([("intervalMax", 5), ("intervalMin", 1)], (1, 5)),
    ([("intervalMin", 1), ("intervalMax", 5)], (1, 5)),
    ([("intervalMin", 300)], (300, 300)),
    ([("intervalMax", 1)], (1, 1)),
])
def test_interval_pair_links_and_persists_atomically(tmp_path, qapp, edits, expected):
    backend, _ = make_backend(tmp_path)
    friends = backend.friends
    friends.intervalMax = 15
    observed = []
    def changed(_):
        observed.append((friends.intervalMin, friends.intervalMax))
        assert friends.intervalMin <= friends.intervalMax
        assert float(friends._settings.value("friends/intervalMin")) == friends.intervalMin
        assert float(friends._settings.value("friends/intervalMax")) == friends.intervalMax
    friends.intervalMinChanged.connect(changed)
    friends.intervalMaxChanged.connect(changed)
    for key, value in edits:
        setattr(friends, key, value)
    assert (friends.intervalMin, friends.intervalMax) == expected
    reopened, _ = make_backend(tmp_path)
    assert (reopened.friends.intervalMin, reopened.friends.intervalMax) == expected
    assert observed


def test_intervals_locked_during_task_and_rpc_uses_snapshot(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    backend.message.recipientsText = "Mock"
    backend.message.templateText = "mock-only"
    assert backend.task.startMessage()
    backend.friends.intervalMin = 99
    backend.friends.intervalMax = 100
    assert (backend.friends.intervalMin, backend.friends.intervalMax) == (15, 30)


@pytest.mark.parametrize("kind", ["message_send", "friend_add"])
def test_verified_bind_publishes_health_before_search_without_inspection(kind):
    driver = RecoveryDriver()
    driver.bind_window = lambda: {
        **driver.window, "processDetected": True, "versionSupported": True,
        "sessionReady": True, "uiaReady": True, "restorable": False,
        "reasonCode": "", "degradedReason": "", "taskWindowReady": True,
        "taskWindowRole": "main",
    }
    engine = make_engine(driver)
    notices = []
    checked = []
    def search_ready():
        snapshots = [p["health"] for m, p in notices if m == "agent.status" and "health" in p]
        assert snapshots and snapshots[-1]["sessionReady"]
        assert snapshots[-1]["taskId"] == "first"
        assert driver.order.count("inspect") == 0
        checked.append(True)
        return True
    driver.ensure_search_ready = search_ready
    driver.open_add_friend = search_ready
    engine.run(make_request(kind), TaskControl(), lambda m, p: notices.append((m, p)))
    assert checked


def test_running_health_is_task_scoped_and_real_failures_win(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    status(client, health(1, sessionReady=False, restorable=True))
    payload = start_message(backend, client)
    assert backend.task.automationStatus == "正在恢复微信"
    ready = health(2, taskId=payload["taskId"], taskWindowReady=True,
                   taskWindowRole="friend_search", taskWindowHwnd=99,
                   windowEnabled=False, blockingWindow={"hwnd": 99})
    status(client, ready)
    assert not backend.agent.windowEnabled
    assert not backend.agent.canStartTask
    assert backend.task.taskWindowReady
    assert backend.task.automationStatus == "自动化执行中"
    status(client, health(1, sessionReady=False, restorable=True))
    assert backend.task.automationStatus == "自动化执行中"
    event(client, payload, errorCode="ACCOUNT_NOT_FOUND")
    assert backend.task.automationStatus == "自动化执行中"
    status(client, {**ready, "sequence": 3, "blockingWindow": {"hwnd": 100}})
    assert backend.task.automationStatus == "微信窗口被阻挡"
    status(client, {**ready, "sequence": 4, "windowResponsive": False})
    assert backend.task.automationStatus == "微信窗口无响应"
    status(client, {**ready, "sequence": 5, "taskId": "old-task"})
    assert not backend.task.taskWindowReady
    status(client, health(6))
    finish(client, payload)
    assert backend.task.automationStatus == "自动化已就绪"


def test_countdown_snapshot_pause_stop_and_stale_notifications(tmp_path, qapp):
    backend, client = make_backend(tmp_path)
    payload = start_message(backend, client)
    def wait(task_id, remaining):
        client.notificationReceived.emit("agent.status", {
            "status": "waiting", "taskId": task_id, "remaining": remaining,
        })
    wait(payload["taskId"], 4.5)
    assert backend.task.waitingRemaining == 4.5
    assert backend.task.intervalLabel == "本批间隔 2–3 秒"
    wait("old-task", 99)
    assert backend.task.waitingRemaining == 4.5
    backend.task.pause()
    assert backend.task.waitingRemaining == 0
    backend.task.resume()
    wait(payload["taskId"], 3)
    assert backend.task.waitingRemaining == 3
    backend.task.stop()
    wait(payload["taskId"], 2)
    assert backend.task.waitingRemaining == 0
    finish(client, payload)
    wait(payload["taskId"], 1)
    assert backend.task.waitingRemaining == 0


@pytest.mark.parametrize("bounds,chosen", [((2, 2), 2), ((1, 5), 3.5)])
def test_wait_after_failed_item_not_after_last(monkeypatch, bounds, chosen):
    from app.agent.contracts import TaskOptions
    calls, sleeps, notices = [], [], []
    def choose(low, high):
        calls.append((low, high))
        return chosen
    monkeypatch.setattr("app.agent.workflows.random.uniform", choose)
    driver = RecoveryDriver()
    driver.search_friend = lambda _: None
    result = make_engine(driver, sleep=sleeps.append).run(
        make_request("friend_add", count=2, options=TaskOptions(
            interval_min=bounds[0], interval_max=bounds[1])),
        TaskControl(), lambda m, p: notices.append((m, p)))
    assert result["error"] == 2
    assert calls == [bounds]
    assert sum(sleeps) == chosen
    waits = [p["remaining"] for m, p in notices if p.get("status") == "waiting"]
    assert waits[0] == chosen and waits[-1] == 0


def test_closed_task_windows_invalidate_or_refresh_health_without_inspecting():
    driver = RecoveryDriver()
    engine = make_engine(driver)
    engine._driver = driver
    engine._active_task_id = "active"
    emitted = []
    engine._progress_emit = lambda m, p: emitted.append(p)
    engine._last_health = {"taskWindowReady": True, "sessionReady": True,
                           "taskWindowRole": "friend_request", "taskId": "active"}
    driver.verified_task_health = lambda: {
        **driver.window, "taskWindowReady": True, "sessionReady": True,
        "taskWindowRole": "friend_search",
    }
    engine._driver_action("submit_verified", "verify_friend_request", lambda: True)
    assert engine._last_health["taskWindowRole"] == "friend_search"
    engine._driver_action("cleanup", "finish_task", driver.finish_task)
    assert engine._last_health["taskWindowReady"] is False
    assert engine._last_health["sessionReady"] is False
    assert "inspect" not in driver.order


def test_health_failure_after_confirmed_submission_does_not_change_result():
    driver = RecoveryDriver()
    engine = make_engine(driver)
    engine._driver = driver
    engine._active_task_id = "active"
    engine._progress_emit = lambda *_: None
    def unavailable():
        raise RuntimeError("post-submit window disappeared")
    driver.verified_task_health = unavailable
    assert engine._driver_action("submit_verified", "verify_friend_request", lambda: True) is True
    assert engine._last_health["taskWindowReady"] is False
