from __future__ import annotations

import os
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .contracts import TaskRequest
from .profile import SUPPORTED_WEIXIN_VERSION


class TaskControl:
    """Thread-safe pause and stop flags checked at workflow safe points."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._stop_requested = False

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
            envelope["event"].set()

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


class AgentRuntime(QObject):
    """Owns the COM/UIA thread while keeping the pipe service responsive."""

    inspectRequested = Signal(object)
    taskRequested = Signal(object)
    shutdownRequested = Signal()

    def __init__(
        self,
        *,
        engine_factory: Callable[[], Any] | None = None,
        inspect_timeout_ms: int = 5_000,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        if engine_factory is None:
            from .workflows import WeixinWorkflowEngine

            engine_factory = WeixinWorkflowEngine
        self._notification_sink: Callable[[str, dict[str, Any]], Any] | None = None
        self._inspect_timeout = inspect_timeout_ms / 1000.0
        self._active_task_id = ""
        self._control: TaskControl | None = None
        self._thread = QThread(self)
        self._thread.setObjectName("wechat-automation")
        self._runner = _AutomationRunner(engine_factory)
        self._runner.moveToThread(self._thread)
        self.inspectRequested.connect(self._runner.inspect)
        self.taskRequested.connect(self._runner.run_task)
        self._runner.notice.connect(self._forward_notice)
        self._runner.finished.connect(self._task_finished)
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
        }

    def inspect(self) -> dict[str, Any]:
        envelope: dict[str, Any] = {"event": threading.Event()}
        self.inspectRequested.emit(envelope)
        if not envelope["event"].wait(self._inspect_timeout):
            raise TimeoutError("WeChat inspection timed out")
        if "error" in envelope:
            raise envelope["error"]
        return dict(envelope["result"])

    def start_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._active_task_id:
            raise ValueError(f"task {self._active_task_id} is already active")
        request = TaskRequest.from_payload(payload)
        if not request.items:
            raise ValueError("task must contain at least one item")
        self._active_task_id = request.task_id
        self._control = TaskControl()
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
        return {"accepted": True, "decision": payload.get("decision", "")}

    def shutdown(self) -> dict[str, Any]:
        if self._control is not None:
            self._control.request_stop()
        QTimer.singleShot(0, self.shutdownRequested.emit)
        return {"accepted": True}

    @Slot(str, object)
    def _forward_notice(self, method: str, params: dict[str, Any]) -> None:
        if self._notification_sink is not None:
            self._notification_sink(method, params)

    @Slot(str, object)
    def _task_finished(self, task_id: str, result: dict[str, Any]) -> None:
        if task_id != self._active_task_id:
            return
        self._active_task_id = ""
        self._control = None
        payload = dict(result)
        payload["taskId"] = task_id
        self._forward_notice("task.finished", payload)
        self._forward_notice("agent.status", {"status": "ready", "taskId": ""})

    def close(self, timeout_ms: int = 2_000) -> None:
        if self._control is not None:
            self._control.request_stop()
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            self._thread.terminate()
            self._thread.wait(500)


__all__ = ["AgentRuntime", "TaskControl"]
