from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .contracts import TaskRequest
from .journal import SafetyJournal
from .profile import SUPPORTED_WEIXIN_VERSION


class TaskControl:
    """Thread-safe pause and stop flags checked at workflow safe points."""

    def __init__(self, *, require_result_ack: bool = False) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._stop_requested = False
        self._require_result_ack = require_result_ack
        self._result_acks: set[str] = set()

    @property
    def stop_requested(self) -> bool:
        with self._condition:
            return self._stop_requested

    def pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def request_stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._paused = False
            self._condition.notify_all()

    def wait_if_paused(self) -> bool:
        with self._condition:
            while self._paused and not self._stop_requested:
                self._condition.wait(0.2)
            return not self._stop_requested

    def acknowledge_result(self, item_id: str) -> None:
        with self._condition:
            self._result_acks.add(str(item_id))
            self._condition.notify_all()

    def wait_for_result_ack(self, item_id: str, timeout: float) -> bool:
        if not self._require_result_ack:
            return True
        item_id = str(item_id)
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while item_id not in self._result_acks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(0.2, remaining))
            self._result_acks.remove(item_id)
            return True


class _UnavailableEngine:
    def inspect(self) -> dict[str, Any]:
        return {
            "connected": False,
            "version": "",
            "supported": False,
            "detail": "UIA engine is not initialized",
        }

    def run(self, request, control, emit):
        raise RuntimeError("UIA engine is not initialized")


class _AutomationRunner(QObject):
    notice = Signal(str, object)
    finished = Signal(str, object)
    recoveryFinished = Signal(object)
    inspectionFinished = Signal(object)

    def __init__(self, engine_factory: Callable[[], Any]):
        super().__init__()
        self._engine_factory = engine_factory
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            self._engine = self._engine_factory()
        return self._engine

    @Slot(object)
    def inspect(self, envelope: dict[str, Any]) -> None:
        try:
            envelope["result"] = self._get_engine().inspect()
        except Exception as exc:
            envelope["error"] = exc
        finally:
            event = envelope.get("event")
            if event is not None:
                event.set()
            self.inspectionFinished.emit(envelope)

    @Slot(object)
    def run_task(self, envelope: dict[str, Any]) -> None:
        request = envelope["request"]
        control = envelope["control"]
        try:
            result = self._get_engine().run(request, control, self.notice.emit)
            if not isinstance(result, dict):
                result = {"outcome": "success"}
        except Exception as exc:
            result = {
                "outcome": "error",
                "detail": str(exc),
                "done": 0,
                "total": len(request.items),
            }
        self.finished.emit(request.task_id, result)

    @Slot(object)
    def recover_wechat(self, envelope: dict[str, Any]) -> None:
        try:
            result = self._get_engine().recover_wechat(
                envelope["timeout"], self.notice.emit
            )
            envelope["result"] = dict(result or {})
        except Exception as exc:
            envelope["error"] = str(exc)
        self.recoveryFinished.emit(envelope)


class AgentRuntime(QObject):
    """Owns the COM/UIA thread while keeping the pipe service responsive."""

    inspectRequested = Signal(object)
    taskRequested = Signal(object)
    recoveryRequested = Signal(object)
    shutdownRequested = Signal()

    def __init__(
        self,
        *,
        engine_factory: Callable[[], Any] | None = None,
        inspect_timeout_ms: int = 5_000,
        action_timeout_ms: int = 30_000,
        journal: SafetyJournal | None = None,
        fatal_exit: Callable[[int], Any] = os._exit,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._journal = journal or SafetyJournal.from_environment()
        if engine_factory is None:
            from .workflows import WeixinWorkflowEngine

            engine_factory = lambda: WeixinWorkflowEngine(journal=self._journal)
        self._notification_sink: Callable[[str, dict[str, Any]], Any] | None = None
        self._inspect_timeout = inspect_timeout_ms / 1000.0
        self._active_task_id = ""
        self._inspection_pending = False
        self._shutdown_pending = False
        self._control: TaskControl | None = None
        self._fatal_exit = fatal_exit
        self._action_watchdog = QTimer(self)
        self._action_watchdog.setSingleShot(True)
        self._action_watchdog.setInterval(max(1_000, int(action_timeout_ms)))
        self._action_watchdog.timeout.connect(self._on_action_timeout)
        self._shutdown_deadline = QTimer(self)
        self._shutdown_deadline.setSingleShot(True)
        self._shutdown_deadline.setInterval(2_500)
        self._shutdown_deadline.timeout.connect(self.shutdownRequested.emit)
        self._thread = QThread(self)
        self._thread.setObjectName("wechat-automation")
        self._runner = _AutomationRunner(engine_factory)
        self._runner.moveToThread(self._thread)
        self.inspectRequested.connect(self._runner.inspect)
        self.taskRequested.connect(self._runner.run_task)
        self.recoveryRequested.connect(self._runner.recover_wechat)
        self._runner.notice.connect(self._forward_notice)
        self._runner.finished.connect(self._task_finished)
        self._runner.recoveryFinished.connect(self._recovery_finished)
        self._runner.inspectionFinished.connect(self._inspection_finished)
        self._thread.start()

    @property
    def active_task_id(self) -> str:
        return self._active_task_id

    def set_notification_sink(
        self, sink: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        self._notification_sink = sink

    def hello(self) -> dict[str, Any]:
        return {
            "agentVersion": "0.3.0",
            "protocolVersion": 1,
            "pid": os.getpid(),
            "supportedWeixinVersions": [SUPPORTED_WEIXIN_VERSION],
            "recovery": self._journal.load(),
        }

    def inspect(self) -> dict[str, Any]:
        envelope: dict[str, Any] = {"event": threading.Event()}
        self.inspectRequested.emit(envelope)
        if not envelope["event"].wait(self._inspect_timeout):
            raise TimeoutError("WeChat inspection timed out")
        if "error" in envelope:
            raise envelope["error"]
        return dict(envelope["result"])

    def inspect_async(
        self,
        callback: Callable[[dict[str, Any] | None, Exception | None], Any],
    ) -> None:
        self._inspection_pending = True
        self._action_watchdog.start()
        self.inspectRequested.emit({"callback": callback})

    def start_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._active_task_id:
            raise ValueError(f"task {self._active_task_id} is already active")
        if self._journal.load() is not None:
            raise ValueError("recovery acknowledgement is required before task start")
        request = TaskRequest.from_payload(payload)
        if not request.items:
            raise ValueError("task must contain at least one item")
        self._active_task_id = request.task_id
        self._control = TaskControl(require_result_ack=True)
        self._action_watchdog.start()
        self.taskRequested.emit({"request": request, "control": self._control})
        self._forward_notice(
            "agent.status",
            {"status": "running", "taskId": request.task_id},
        )
        return {"accepted": True, "taskId": request.task_id}

    def pause_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._control is None:
            return {"accepted": False, "reason": "no active task"}
        self._control.pause()
        return {"accepted": True, "pendingSafePoint": True}

    def resume_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._control is None:
            return {"accepted": False, "reason": "no active task"}
        self._control.resume()
        return {"accepted": True}

    def stop_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._control is None:
            return {"accepted": False, "reason": "no active task"}
        self._control.request_stop()
        return {"accepted": True, "pendingSafePoint": True}

    def approve_recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        decision = str(payload.get("decision", ""))
        if decision not in {
            "acknowledge",
            "mark_unknown",
            "discard",
            "stop",
            "restart_wechat",
        }:
            raise ValueError("invalid recovery decision")
        if decision == "acknowledge":
            task_id = str(payload.get("taskId", ""))
            item_id = str(payload.get("itemId", ""))
            if not task_id or not item_id:
                raise ValueError("result acknowledgement requires taskId and itemId")
            if self._control is not None and task_id == self._active_task_id:
                self._control.acknowledge_result(item_id)
            else:
                self._journal.clear(task_id=task_id, item_id=item_id)
        elif decision == "restart_wechat":
            timeout = max(30, min(300, int(payload.get("loginTimeout", 90))))
            self.recoveryRequested.emit({"timeout": timeout})
        else:
            self._journal.clear()
        return {"accepted": True, "decision": decision}

    def shutdown(self) -> dict[str, Any]:
        if self._control is not None:
            self._shutdown_pending = True
            self._control.request_stop()
            self._shutdown_deadline.start()
        else:
            QTimer.singleShot(0, self.shutdownRequested.emit)
        return {"accepted": True}

    @Slot(str, object)
    def _forward_notice(self, method: str, params: dict[str, Any]) -> None:
        if self._active_task_id:
            self._action_watchdog.start()
        if self._notification_sink is not None:
            self._notification_sink(method, params)

    @Slot(str, object)
    def _task_finished(self, task_id: str, result: dict[str, Any]) -> None:
        if task_id != self._active_task_id:
            return
        self._active_task_id = ""
        self._control = None
        self._action_watchdog.stop()
        payload = dict(result)
        payload["taskId"] = task_id
        self._forward_notice("task.finished", payload)
        self._forward_notice("agent.status", {"status": "ready", "taskId": ""})
        if self._shutdown_pending:
            self._shutdown_pending = False
            self._shutdown_deadline.stop()
            QTimer.singleShot(0, self.shutdownRequested.emit)

    @Slot(object)
    def _recovery_finished(self, envelope: dict[str, Any]) -> None:
        if "error" in envelope:
            self._forward_notice(
                "agent.status",
                {"status": "recovery_failed", "detail": envelope["error"]},
            )
            return
        payload = dict(envelope.get("result") or {})
        payload["status"] = "recovered"
        self._forward_notice("agent.status", payload)

    @Slot(object)
    def _inspection_finished(self, envelope: dict[str, Any]) -> None:
        callback = envelope.get("callback")
        if callback is None:
            return
        self._inspection_pending = False
        if not self._active_task_id:
            self._action_watchdog.stop()
        error = envelope.get("error")
        result = None if error is not None else dict(envelope.get("result") or {})
        callback(result, error)

    @Slot()
    def _on_action_timeout(self) -> None:
        self._forward_notice(
            "agent.status",
            {
                "status": "fatal_timeout",
                "taskId": self._active_task_id,
                "detail": "UIA action exceeded its deadline",
            },
        )
        self._fatal_exit(70)

    def close(self, timeout_ms: int = 2_000) -> None:
        self._action_watchdog.stop()
        self._shutdown_deadline.stop()
        if self._control is not None:
            self._control.request_stop()
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            self._thread.terminate()
            self._thread.wait(500)


__all__ = ["AgentRuntime", "TaskControl"]
