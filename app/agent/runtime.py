from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .._version import __version__
from ..build_info import build_info
from .contracts import TaskRequest
from .diagnostics import UiaDiagnostics, gui_instance_id_from_environment
from .journal import SafetyJournal
from .profile import SUPPORTED_WEIXIN_VERSION


class TaskControl:
    """Thread-safe pause and stop flags checked at workflow safe points."""

    def __init__(self, *, require_result_ack: bool = False) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._pause_generation = 0
        self._stop_requested = False
        self._require_result_ack = require_result_ack
        self._result_acks: set[str] = set()

    @property
    def stop_requested(self) -> bool:
        with self._condition:
            return self._stop_requested

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def pause(self) -> None:
        with self._condition:
            if not self._paused:
                self._pause_generation += 1
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

    def wait_at_safe_point(self, on_pause: Callable[[], None]) -> bool:
        notified_generation = -1
        while True:
            with self._condition:
                if self._stop_requested:
                    return False
                if not self._paused:
                    return True
                generation = self._pause_generation
                if notified_generation == generation:
                    self._condition.wait(0.2)
                    continue
            # UIA cleanup must not hold the lock needed by pause/resume/stop RPC.
            on_pause()
            notified_generation = generation

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
            "processDetected": False,
            "version": "",
            "supported": False,
            "versionSupported": False,
            "uiaReady": False,
            "sessionReady": False,
            "windowResponsive": False,
            "sessionGeneration": 0,
            "degradedReason": "UIA_NOT_INITIALIZED",
            "detail": "UIA engine is not initialized",
        }

    def run(self, request, control, emit):
        raise RuntimeError("UIA engine is not initialized")


class _AutomationRunner(QObject):
    notice = Signal(str, object)
    finished = Signal(str, object)
    recoveryFinished = Signal(object)
    inspectionStarted = Signal(object)
    inspectionFinished = Signal(object)
    gateProgress = Signal(object)
    gateFinished = Signal(object)

    def __init__(self, engine_factory: Callable[[], Any]):
        super().__init__()
        self._engine_factory = engine_factory
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            self._engine = self._engine_factory()
        return self._engine

    @Slot(object)
    def recover_gate(self, envelope):
        try:
            envelope["result"] = envelope["manager"].run(envelope["stop"], self.gateProgress.emit)
        except Exception as exc:
            envelope["result"] = {"stage": "failed", "reasonCode": "GATE_RECOVERY_BLOCKED", "detail": str(exc)}
        self.gateFinished.emit(envelope)

    @Slot(object)
    def inspect(self, envelope: dict[str, Any]) -> None:
        self.inspectionStarted.emit(envelope)
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
        def emit_if_running(method, params):
            if envelope["stop"].is_set():
                raise RuntimeError("Weixin recovery cancelled during Agent shutdown")
            self.notice.emit(method, params)

        try:
            if envelope["stop"].is_set():
                raise RuntimeError("Weixin recovery cancelled before start")
            result = self._get_engine().recover_wechat(
                envelope["timeout"], emit_if_running
            )
            envelope["result"] = dict(result or {})
        except Exception as exc:
            envelope["error"] = str(exc)
        self.recoveryFinished.emit(envelope)

    @Slot(object)
    def close(self, envelope: dict[str, Any]) -> None:
        try:
            engine = self._engine
            close = getattr(engine, "close", None)
            if close is not None:
                close()
            self._engine = None
        except Exception as exc:
            envelope["error"] = exc
        finally:
            envelope["event"].set()


class AgentRuntime(QObject):
    """Owns the COM/UIA thread while keeping the pipe service responsive."""

    inspectRequested = Signal(object)
    taskRequested = Signal(object)
    recoveryRequested = Signal(object)
    gateRecoveryRequested = Signal(object)
    closeRequested = Signal(object)
    shutdownRequested = Signal()

    def __init__(
        self,
        *,
        engine_factory: Callable[[], Any] | None = None,
        inspect_timeout_ms: int = 7_500,
        action_timeout_ms: int = 15_000,
        journal: SafetyJournal | None = None,
        diagnostics: UiaDiagnostics | None = None,
        friend_submit_enabled: bool | None = None,
        gate_recovery: Any | None = None,
        gate_timeout_ms: int = 15_000,
        fatal_exit: Callable[[int], Any] = os._exit,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._journal = journal or SafetyJournal.from_environment()
        self._diagnostics = diagnostics
        self._gui_instance_id = gui_instance_id_from_environment()
        self._friend_submit_enabled = (
            os.environ.get("WECHAT_COURIER_ACCEPTANCE") != "1"
            if friend_submit_enabled is None
            else friend_submit_enabled is True
        )
        if engine_factory is None:
            from .workflows import WeixinWorkflowEngine

            if self._diagnostics is None:
                self._diagnostics = UiaDiagnostics()
            engine_factory = lambda: WeixinWorkflowEngine(
                journal=self._journal,
                diagnostics=self._diagnostics,
                friend_submit_enabled=self._friend_submit_enabled,
            )
        self._notification_sink: Callable[[str, dict[str, Any]], Any] | None = None
        self._gate_recovery = gate_recovery
        self._gate_state = dict(gate_recovery.state) if gate_recovery else {"stage": "completed", "reasonCode": ""}
        self._gate_ready = gate_recovery is None
        self._gate_verified = gate_recovery is None
        self._gate_stop: threading.Event | None = None
        self._health_instance = getattr(self._diagnostics, "agent_instance_id", "") or uuid.uuid4().hex
        self._health_serial = 0
        self._gate_timeout_ms = max(1, int(gate_timeout_ms))
        self._gate_watchdog = QTimer(self)
        self._gate_watchdog.setSingleShot(True)
        self._gate_watchdog.timeout.connect(self._on_gate_timeout)
        self._inspect_timeout = inspect_timeout_ms / 1000.0
        self._active_task_id = ""
        self._watch_action_id = ""
        self._last_health = {}
        self._cleanup_failed = False
        self._inspection_pending = False
        self._inspection_envelope: dict[str, Any] | None = None
        self._inspection_callbacks: list[
            Callable[[dict[str, Any] | None, Exception | None], Any]
        ] = []
        self._shutdown_pending = False
        self._recovery_stop: threading.Event | None = None
        self._control: TaskControl | None = None
        self._fatal_exit = fatal_exit
        self._action_watchdog = QTimer(self)
        self._action_watchdog.setSingleShot(True)
        self._action_watchdog.setInterval(max(1_000, int(action_timeout_ms)))
        self._action_watchdog.timeout.connect(self._on_action_timeout)
        self._inspection_watchdog = QTimer(self)
        self._inspection_watchdog.setSingleShot(True)
        self._inspection_watchdog.setInterval(max(1, int(inspect_timeout_ms)))
        self._inspection_watchdog.timeout.connect(self._on_action_timeout)
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
        self.gateRecoveryRequested.connect(self._runner.recover_gate)
        self.closeRequested.connect(self._runner.close)
        self._runner.notice.connect(self._forward_notice)
        self._runner.finished.connect(self._task_finished)
        self._runner.recoveryFinished.connect(self._recovery_finished)
        self._runner.inspectionStarted.connect(self._inspection_started)
        self._runner.inspectionFinished.connect(self._inspection_finished)
        self._runner.gateProgress.connect(self._gate_progress)
        self._runner.gateFinished.connect(self._gate_finished)
        self._thread.start()

    def begin_gate_recovery(self, *, allow_restart: bool | None = None) -> None:
        if self._gate_recovery is None or self._gate_stop is not None or self._shutdown_pending:
            return
        if self._active_task_id or self._inspection_pending:
            raise ValueError("cannot recover gate while automation is active")
        if allow_restart is not None:
            self._gate_recovery.allow_restart = bool(allow_restart)
        self._gate_ready = self._gate_verified = False
        self._gate_stop = threading.Event()
        self._gate_watchdog.start(self._gate_timeout_ms)
        self._gate_state = dict(self._gate_state, stage="checking", reasonCode="GATE_RECOVERING")
        self._publish_gate_health()
        self.gateRecoveryRequested.emit({"manager": self._gate_recovery, "stop": self._gate_stop})

    def _stamp_health(self, result):
        result = dict(result)
        if self._gate_recovery is not None:
            self._health_serial += 1
            result.update(sequence=self._health_serial, agentInstanceId=self._health_instance,
                          checkedAt=datetime.now(timezone.utc).isoformat(), gateRecovery=dict(self._gate_state))
        return result

    @staticmethod
    def _health_allows_task(result):
        return bool(result.get("versionSupported") and result.get("windowResponsive")
                    and result.get("windowEnabled") and not result.get("blockingWindow")
                    and not result.get("reasonCode") and not result.get("degradedReason")
                    and (result.get("sessionReady") or result.get("restorable")))

    def _gate_health(self):
        reason = self._gate_state.get("reasonCode") or "GATE_RECOVERING"
        target = self._gate_state.get("target", {})
        return {"processDetected": bool(target), "versionSupported": bool(target),
                "version": target.get("version", ""), "sessionReady": False, "uiaReady": False,
                "windowResponsive": False, "windowEnabled": False, "restorable": False,
                "sessionGeneration": 0, "reasonCode": reason, "degradedReason": reason,
                "detail": self._gate_state.get("detail", "正在检查遗留自动化状态")}

    def _publish_gate_health(self):
        self._forward_notice("agent.status", {"status": "gate_recovery", "health": self._gate_health()})

    @Slot(object)
    def _gate_progress(self, state):
        if state.get("stage") == "awaiting_login" and self._gate_state.get("stage") != "awaiting_login":
            self._gate_watchdog.start(max(1, int(getattr(self._gate_recovery, "login_timeout", 90) * 1000) + 500))
        self._gate_state = dict(state)
        self._publish_gate_health()

    @Slot(object)
    def _gate_finished(self, envelope):
        self._gate_watchdog.stop()
        self._gate_stop = None
        self._gate_state = dict(envelope["result"])
        self._gate_ready = self._gate_state.get("stage") == "completed"
        self._publish_gate_health()
        if self._shutdown_pending:
            self._shutdown_deadline.stop()
            QTimer.singleShot(0, self.shutdownRequested.emit)
        elif self._gate_ready:
            self.inspect_async(lambda result, error: None)

    @Slot()
    def _on_gate_timeout(self):
        self._gate_ready = self._gate_verified = False
        if self._gate_stop is not None:
            self._gate_stop.set()
        self._gate_state = dict(self._gate_state, stage="failed", reasonCode="GATE_RECOVERY_TIMEOUT",
                                detail="原生租约恢复超过截止时间")
        self._publish_gate_health()
        self._fatal_exit(70)

    @property
    def active_task_id(self) -> str:
        return self._active_task_id

    def set_notification_sink(
        self, sink: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        self._notification_sink = sink

    def hello(self) -> dict[str, Any]:
        return {
            "agentVersion": __version__,
            "guiInstanceId": self._gui_instance_id,
            "build": build_info(),
            "protocolVersion": 1,
            "pid": os.getpid(),
            "supportedWeixinVersions": [SUPPORTED_WEIXIN_VERSION],
            "capabilities": {
                "friendSubmitEnabled": self._friend_submit_enabled,
            },
            "recovery": self._journal.load(),
            "gateRecovery": dict(self._gate_state),
            "health": dict(self._last_health),
        }

    def inspect(self) -> dict[str, Any]:
        if not self._gate_ready:
            return self._stamp_health(self._gate_health())
        envelope: dict[str, Any] = {"event": threading.Event()}
        self.inspectRequested.emit(envelope)
        if not envelope["event"].wait(self._inspect_timeout):
            raise TimeoutError("WeChat inspection timed out")
        if "error" in envelope:
            raise envelope["error"]
        return self._stamp_health(envelope["result"])

    def inspect_async(
        self,
        callback: Callable[[dict[str, Any] | None, Exception | None], Any],
    ) -> None:
        if not self._gate_ready:
            if self._gate_stop is None:
                self.begin_gate_recovery(allow_restart=False)
            callback(self._stamp_health(self._gate_health()), None)
            return
        self._inspection_callbacks.append(callback)
        if self._inspection_pending:
            return
        self._inspection_pending = True
        self._inspection_envelope = {}
        self.inspectRequested.emit(self._inspection_envelope)

    def start_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._gate_ready or not self._gate_verified:
            raise ValueError("GATE_RECOVERY_PENDING: verified automation health is required before task start")
        if self._active_task_id:
            raise ValueError(f"task {self._active_task_id} is already active")
        if self._cleanup_failed:
            raise ValueError("previous task cleanup failed; inspect recovery before starting")
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
        if not self._watch_action_id:
            self._action_watchdog.stop()
        return {"accepted": True, "pendingSafePoint": True}

    def resume_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._control is None:
            return {"accepted": False, "reason": "no active task"}
        self._control.resume()
        if not self._watch_action_id:
            self._action_watchdog.start()
        return {"accepted": True}

    def stop_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._control is None:
            return {"accepted": False, "reason": "no active task"}
        self._control.request_stop()
        if not self._watch_action_id:
            self._action_watchdog.start()
        return {"accepted": True, "pendingSafePoint": True}

    def approve_recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope", "task")
        if scope == "gate":
            decision = payload.get("decision")
            if decision == "stop":
                if self._gate_stop is not None:
                    self._gate_stop.set()
            elif decision == "restart_wechat":
                if self._gate_recovery is None or self._gate_ready:
                    raise ValueError("no pending gate recovery")
                self.begin_gate_recovery(allow_restart=True)
            else:
                raise ValueError("invalid gate recovery decision")
            return {"accepted": True, "scope": "gate", "decision": decision}
        if scope != "task":
            raise ValueError("invalid recovery scope")
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
            if self._recovery_stop is not None or self._shutdown_pending:
                raise ValueError("recovery or shutdown is already in progress")
            timeout = max(30, min(300, int(payload.get("loginTimeout", 90))))
            self._recovery_stop = threading.Event()
            self.recoveryRequested.emit({"timeout": timeout, "stop": self._recovery_stop})
        else:
            self._journal.clear()
        return {"accepted": True, "decision": decision}

    def shutdown(self) -> dict[str, Any]:
        if self._control is not None or self._inspection_pending or self._recovery_stop is not None or self._gate_stop is not None:
            self._shutdown_pending = True
            if self._control is not None:
                self._control.request_stop()
            if self._recovery_stop is not None:
                self._recovery_stop.set()
            if self._gate_stop is not None:
                self._gate_stop.set()
            self._shutdown_deadline.start(
                max(2_500, self._inspection_watchdog.interval() + 500)
                if self._inspection_pending or self._recovery_stop is not None else 2_500
            )
        else:
            QTimer.singleShot(0, self.shutdownRequested.emit)
        return {"accepted": True}

    @Slot(str, object)
    def _forward_notice(self, method: str, params: dict[str, Any]) -> None:
        status = str(params.get("status", ""))
        if method == "agent.status" and status == "uia_action_started":
            self._watch_action_id = str(params.get("actionId") or params.get("action") or "action")
            self._action_watchdog.start()
        elif method == "agent.status" and status == "uia_action_completed":
            self._watch_action_id = ""
            self._action_watchdog.stop()
        elif method == "agent.status" and status in {"waiting", "paused", "health"}:
            if not self._watch_action_id:
                self._action_watchdog.stop()
        health = params.get("health")
        if isinstance(health, dict):
            health = self._stamp_health(health)
            params = dict(params, health=health)
            self._last_health = dict(health)
            if self._gate_recovery is not None:
                self._gate_verified = self._gate_ready and self._health_allows_task(health)
        if self._diagnostics is not None and method != "task.event":
            try:
                self._diagnostics.record(
                    stage="runtime",
                    action=method,
                    outcome=str(params.get("outcome") or params.get("status") or "event"),
                    task_id=str(params.get("taskId", self._active_task_id)),
                    item_id=str(params.get("itemId", "")),
                    action_id=str(params.get("actionId", "")),
                    phase=self._gate_state.get("stage") if status == "gate_recovery" else None,
                    error_code=self._gate_state.get("reasonCode") if status == "gate_recovery" else None,
                    context={"gateRecovery": dict(self._gate_state)} if status == "gate_recovery" else None,
                )
            except Exception:
                pass
        if self._notification_sink is not None:
            self._notification_sink(method, params)

    @Slot(str, object)
    def _task_finished(self, task_id: str, result: dict[str, Any]) -> None:
        if task_id != self._active_task_id:
            return
        self._cleanup_failed = result.get("cleanup", {}).get("success") is False
        if isinstance(result.get("health"), dict):
            self._forward_notice("agent.status", {"status": "health", "health": result["health"]})
        self._active_task_id = ""
        self._watch_action_id = ""
        self._control = None
        self._action_watchdog.stop()
        payload = dict(result)
        payload["taskId"] = task_id
        self._forward_notice("task.finished", payload)
        self._forward_notice("agent.status", {"status": "idle", "taskId": ""})
        if self._shutdown_pending and not self._inspection_pending and self._recovery_stop is None:
            self._shutdown_pending = False
            self._shutdown_deadline.stop()
            QTimer.singleShot(0, self.shutdownRequested.emit)

    @Slot(object)
    def _recovery_finished(self, envelope: dict[str, Any]) -> None:
        self._recovery_stop = None
        if self._shutdown_pending and self._control is None and not self._inspection_pending:
            self._shutdown_pending = False
            self._shutdown_deadline.stop()
            QTimer.singleShot(0, self.shutdownRequested.emit)
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
    def _inspection_started(self, envelope: dict[str, Any]) -> None:
        # Queue time may include an intentional task pause; bound execution only.
        if envelope is self._inspection_envelope:
            self._inspection_watchdog.start()

    @Slot(object)
    def _inspection_finished(self, envelope: dict[str, Any]) -> None:
        if self._inspection_envelope is not None and envelope is not self._inspection_envelope:
            return
        self._inspection_watchdog.stop()
        self._inspection_envelope = None
        callbacks = self._inspection_callbacks
        self._inspection_callbacks = []
        self._inspection_pending = False
        if self._shutdown_pending and self._control is None and self._recovery_stop is None:
            self._shutdown_pending = False
            self._shutdown_deadline.stop()
            QTimer.singleShot(0, self.shutdownRequested.emit)
        fallback_callback = envelope.get("callback")
        if fallback_callback is not None and not callbacks:
            callbacks = [fallback_callback]
        error = envelope.get("error")
        result = None if error is not None else dict(envelope.get("result") or {})
        if error is not None and self._gate_recovery is not None:
            self._gate_verified = False
            self._forward_notice("agent.status", {"status": "health", "health": {
                "sessionReady": False, "reasonCode": "HEALTH_CHECK_FAILED",
                "degradedReason": "HEALTH_CHECK_FAILED", "detail": str(error)}})
        if result is not None:
            result = self._stamp_health(result)
            self._last_health = dict(result)
            if self._gate_recovery is not None:
                self._gate_verified = self._health_allows_task(result)
                if self._notification_sink is not None:
                    self._notification_sink("agent.status", {"status": "health", "health": result})
            cleanup_complete = result.get("cleanupComplete")
            if cleanup_complete is False:
                self._cleanup_failed = True
            elif cleanup_complete is True or (
                cleanup_complete is None and result.get("sessionReady")
                and result.get("windowEnabled", True)
            ):
                self._cleanup_failed = False
        for callback in callbacks:
            try:
                callback(result, error)
            except Exception:
                # A socket/request can disappear while one coalesced inspection
                # is running. Remaining callbacks still own the same result.
                continue

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
        self._gate_watchdog.stop()
        if self._gate_stop is not None:
            self._gate_stop.set()
        if self._recovery_stop is not None:
            self._recovery_stop.set()
        self._action_watchdog.stop()
        self._inspection_watchdog.stop()
        self._inspection_envelope = None
        self._inspection_pending = False
        self._shutdown_deadline.stop()
        if not self._thread.isRunning():
            return
        if self._control is not None:
            self._control.request_stop()
        envelope = {"event": threading.Event()}
        self.closeRequested.emit(envelope)
        completed = envelope["event"].wait(max(0, timeout_ms) / 1000.0)
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            self._thread.terminate()
            self._thread.wait(500)
        if self._diagnostics is not None:
            self._diagnostics.close()
            self._diagnostics = None
        if not completed:
            raise TimeoutError("Agent cleanup timed out; gate recovery is required")
        if "error" in envelope:
            raise RuntimeError("Agent cleanup failed; gate recovery is required") from envelope["error"]


__all__ = ["AgentRuntime", "TaskControl"]
