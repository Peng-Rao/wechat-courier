from __future__ import annotations

import random
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from app.clocks import ElapsedClock

from .contracts import TaskEvent, TaskItem, TaskRequest
from .retry import LayeredRetry, RetryExhausted, TransientUiError, classify_exception
from .waiters import action_deadline


_AUTO_INSPECTION_BLOCKERS = frozenset({
    "RISK_CONTROL", "GATE_SAFETY", "UNSUPPORTED_VERSION", "WECHAT_UNRESPONSIVE",
    "WINDOW_BLOCKED", "WINDOW_DISABLED", "EVENT_CLEANUP_FAILED",
    "UIA_TREE_NOT_READY_AFTER_REFRESH", "ACTION_DEADLINE_EXCEEDED",
})


class WorkflowError(RuntimeError):
    def __init__(
        self,
        step: str,
        detail: str,
        *,
        retry_error=None,
        attempt: int = 1,
        max_attempts: int = 1,
        retry_level: str = "none",
        error_code: str = "",
        fatal_batch: bool = False,
    ):
        super().__init__(detail)
        self.step = step
        self.detail = detail
        self.retry_error = retry_error
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.retry_level = retry_level
        self.error_code = str(error_code)
        self.fatal_batch = bool(fatal_batch)


class RiskControlError(RuntimeError):
    """A Weixin risk, frequency, account, or captcha stop signal."""


class StopRequested(RuntimeError):
    pass


class StopAfterBoundary(RuntimeError):
    def __init__(self, outcome: str):
        super().__init__(outcome)
        self.outcome = str(outcome)


def normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def candidate_matches_identity(candidate: Any, expected: str) -> bool:
    identities = getattr(candidate, "identities", None)
    if identities is None:
        identities = (str(candidate),)
    return any(normalize_identity(str(value)) == expected for value in identities)


class WeixinWorkflowEngine:
    """Verified, non-replaying workflows independent of a concrete UIA driver."""

    def __init__(
        self,
        *,
        driver_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        journal=None,
        diagnostics=None,
        friend_submit_enabled: bool = False,
    ):
        if driver_factory is None:
            from .native_driver import NativeWeixinDriver

            driver_factory = NativeWeixinDriver
        self._driver_factory = driver_factory
        self._driver = None
        self._sleep = sleep
        self._journal = journal
        self._diagnostics = diagnostics
        self._friend_submit_enabled = friend_submit_enabled is True
        self._progress_emit = None
        self._active_task_id = ""
        self._active_item_id = ""
        self._active_action_id = ""
        self._instance_id = getattr(diagnostics, "agent_instance_id", None) or uuid.uuid4().hex
        self._health_sequence = 0
        self._last_health = {}
        self._cleanup_blocked = False
        self._last_failure_code = ""
        self._safety_failure_code = ""
        self._task_kind = ""
        self._item_clock = ElapsedClock()

    def _get_driver(self):
        if self._driver is None:
            self._driver = self._driver_factory()
        return self._driver

    def inspect(self) -> dict[str, Any]:
        driver = self._get_driver()
        with action_deadline():
            if self._cleanup_blocked:
                finish = getattr(driver, "finish_task", None)
                if callable(finish):
                    cleanup = finish()
                    self._cleanup_blocked = not bool(cleanup.get("success"))
            health = dict(driver.inspect())
        if self._cleanup_blocked:
            health.update(sessionReady=False, uiaReady=False,
                          reasonCode="CLEANUP_FAILED", degradedReason="CLEANUP_FAILED")
        return self._stamp_health(health)

    def _stamp_health(self, health):
        self._health_sequence += 1
        result = dict(health)
        result.update(sequence=self._health_sequence, agentInstanceId=self._instance_id,
                      checkedAt=datetime.now(timezone.utc).isoformat())
        result["cleanupComplete"] = not self._cleanup_blocked
        result.setdefault("reasonCode", result.get("degradedReason", ""))
        self._last_health = result
        return dict(result)

    def recover_wechat(self, timeout: int, emit) -> dict[str, Any]:
        result = dict(self._get_driver().restart_wechat(timeout, emit))
        self._cleanup_blocked = False
        return self._stamp_health(result)

    def run(self, request: TaskRequest, control, emit) -> dict[str, Any]:
        if self._cleanup_blocked:
            return {"outcome": "error", "done": 0, "total": len(request.items),
                    "detail": "上次任务窗口清理失败，请先恢复微信",
                    "cleanup": {"success": False, "reasonCode": "CLEANUP_FAILED"},
                    "health": dict(self._last_health)}
        driver = self._get_driver()
        self._last_failure_code = ""
        self._safety_failure_code = ""
        self._task_kind = request.kind
        self._active_task_id = request.task_id
        self._progress_emit = emit
        result = None
        cleanup = {"success": True, "reasonCode": "", "detail": ""}
        try:
            begin = getattr(driver, "begin_task", None)
            if callable(begin):
                begin(request.kind)
            self._safe_point(control)
            result = self._run_items(request, control, emit)
        except StopRequested:
            result = {"outcome": "stopped", "done": 0, "total": len(request.items),
                      "success": 0, "error": 0, "unknown": 0, "stopped": 0,
                      "detail": "任务已在执行前安全停止"}
        except Exception as exc:
            failure = classify_exception(exc)
            self._last_failure_code = getattr(exc, "error_code", "") or (
                failure.code if failure else {
                    "RiskControlError": "RISK_CONTROL",
                    "AccessibilitySafetyError": "GATE_SAFETY",
                    "UnsupportedWeixinVersion": "UNSUPPORTED_VERSION",
                }.get(type(exc).__name__, "AUTOMATION_ERROR")
            )
            self._remember_safety_failure(self._last_failure_code)
            result = {"outcome": "error", "done": 0, "total": len(request.items),
                      "success": 0, "error": 0, "unknown": 0, "stopped": 0,
                      "detail": str(exc), "errorCode": self._last_failure_code}
        finally:
            self._active_task_id = request.task_id
            self._progress_emit = emit
            try:
                finish = getattr(driver, "finish_task", None)
                if callable(finish):
                    cleanup = self._driver_action("cleanup", "finish_task", finish)
                    if not isinstance(cleanup, dict):
                        cleanup = {"success": cleanup is not False}
            except Exception as exc:
                failure = classify_exception(exc)
                reason = getattr(exc, "error_code", "") or (
                    failure.code if failure else "CLEANUP_FAILED"
                )
                cleanup = {"success": False, "reasonCode": reason,
                           "detail": str(exc)}
            self._cleanup_blocked = not bool(cleanup.get("success"))
            health = self._post_task_health(cleanup)
            emit("agent.status", {"status": "health", "health": health})
            if result is not None:
                result.update(cleanup=cleanup, health=health)
            self._progress_emit = None
            self._active_task_id = ""
            self._active_item_id = ""
        return result

    def _post_task_health(self, cleanup: dict[str, Any]) -> dict[str, Any]:
        observed = {}

        def blocked(reason, detail=""):
            return self._stamp_health({
                **self._last_health, **observed,
                "sessionGeneration": self._session_generation(),
                "sessionReady": False, "uiaReady": False,
                "reasonCode": reason, "degradedReason": reason,
                "detail": detail or reason,
            })

        def check_health():
            nonlocal observed
            snapshotter = getattr(self._driver, "health_window_snapshot", None)
            if not callable(snapshotter):
                snapshotter = getattr(self._driver, "diagnostic_snapshot", None)
            snapshot = dict(snapshotter()) if callable(snapshotter) else {}
            observed = {key: snapshot[key] for key in (
                "sessionGeneration", "windowResponsive", "windowEnabled",
                "blockingWindow", "hwnd", "pid", "version", "windowState", "restorable",
            ) if key in snapshot}
            if self._cleanup_blocked:
                return blocked(cleanup.get("reasonCode") or "CLEANUP_FAILED", cleanup.get("detail", ""))
            if self._safety_failure_code:
                return blocked(self._safety_failure_code)
            if snapshot.get("windowState") == "missing":
                return blocked("WECHAT_NOT_FOUND")
            if snapshot.get("windowResponsive") is False:
                return blocked("WECHAT_UNRESPONSIVE")
            if snapshot.get("blockingWindow"):
                return blocked("WINDOW_BLOCKED")
            if snapshot.get("windowEnabled") is False:
                return blocked("WINDOW_DISABLED")
            if callable(snapshotter) and any(
                snapshot.get(key) is not True
                for key in ("windowResponsive", "windowEnabled")
            ):
                return blocked("HEALTH_CHECK_FAILED", "Window state could not be verified")
            # Task errors describe delivery, not the health of the next task.
            return self.inspect()

        try:
            return self._driver_action("health", "inspect", check_health)
        except Exception as exc:
            failure = classify_exception(exc)
            reason = getattr(exc, "error_code", "") or (
                failure.code if failure else "HEALTH_CHECK_FAILED"
            )
            return blocked(reason, str(exc))

    def _remember_safety_failure(self, code: str) -> None:
        if code in _AUTO_INSPECTION_BLOCKERS and not self._safety_failure_code:
            self._safety_failure_code = code

    def _run_items(self, request: TaskRequest, control, emit) -> dict[str, Any]:
        if request.kind == "friend_add" and len(request.items) > request.options.friend_batch_limit:
            raise ValueError(f"friend task exceeds friendBatchLimit ({request.options.friend_batch_limit})")
        driver = self._get_driver()
        counts = {"success": 0, "error": 0, "unknown": 0, "stopped": 0}
        done = 0
        forced_stop = False
        self._progress_emit = emit
        self._active_task_id = request.task_id
        try:
            for index, item in enumerate(request.items):
                self._active_item_id = item.item_id
                self._item_clock.reset()
                self._item_clock.resume()
                try:
                    self._safe_point(control)
                    if request.kind == "message_send":
                        outcome = self._run_message_item(
                            driver, request, item, index, emit, control
                        )
                    else:
                        outcome = self._run_friend_item(
                            driver, request, item, index, emit, control
                        )
                except StopRequested:
                    outcome = "stopped"
                    self._event(
                        emit,
                        request,
                        item,
                        "window_bound",
                        outcome,
                        "任务已安全停止",
                        index,
                    )
                    forced_stop = True
                except StopAfterBoundary as exc:
                    outcome = exc.outcome
                    forced_stop = True
                except WorkflowError as exc:
                    outcome = "error"
                    self._event(
                        emit,
                        request,
                        item,
                        exc.step,
                        outcome,
                        exc.detail,
                        index + 1,
                        attempt=exc.attempt,
                        max_attempts=exc.max_attempts,
                        retry_level=exc.retry_level,
                        recoverable=bool(
                            exc.retry_error is not None
                            and exc.retry_error.recoverable
                        ),
                        wechat_responsive=bool(
                            exc.retry_error is None
                            or exc.retry_error.wechat_responsive
                        ),
                        error_code=(
                            exc.error_code
                            or (
                                exc.retry_error.code
                                if exc.retry_error is not None
                                else "AUTOMATION_ERROR"
                            )
                        ),
                    )
                    if exc.fatal_batch or (
                        exc.retry_error is not None
                        and not exc.retry_error.wechat_responsive
                    ):
                        forced_stop = True
                except RiskControlError as exc:
                    outcome = "error"
                    step = str(
                        getattr(
                            exc,
                            "step",
                            "add_friend_window_ready"
                            if request.kind == "friend_add"
                            else "target_selected",
                        )
                    )
                    self._event(
                        emit,
                        request,
                        item,
                        step,
                        outcome,
                        str(exc),
                        index + 1,
                        recoverable=False,
                        error_code="RISK_CONTROL",
                        risk_kind=str(getattr(exc, "risk_kind", "")),
                    )
                    forced_stop = True
                except Exception as exc:
                    outcome = "error"
                    self._event(
                        emit,
                        request,
                        item,
                        (
                            "send_verified"
                            if request.kind == "message_send"
                            else "submit_verified"
                        ),
                        outcome,
                        f"自动化异常：{exc}",
                        index + 1,
                        recoverable=False,
                        error_code="AUTOMATION_ERROR",
                    )
                    forced_stop = True
                self._item_clock.pause()
                counts[outcome] += 1
                done += 1
                if forced_stop:
                    break
                if outcome == "unknown" and request.options.unknown_policy == "stop":
                    break
                if index + 1 < len(request.items):
                    try:
                        self._safe_point(control)
                        self._sleep_interval(request, control, emit)
                    except StopRequested:
                        forced_stop = True
                        break
        finally:
            self._progress_emit = None
            self._active_task_id = ""

        overall = "success"
        if counts["stopped"]:
            overall = "stopped"
        elif counts["error"]:
            overall = "error"
        elif counts["unknown"]:
            overall = "unknown"
        return {
            "outcome": overall,
            "done": done,
            "total": len(request.items),
            **counts,
        }

    def close(self) -> None:
        driver = self._driver
        if driver is None:
            return
        close = getattr(driver, "close", None)
        if close is not None:
            close()
        self._driver = None

    def _safe_point(self, control) -> bool:
        paused = False

        def before_pause():
            nonlocal paused
            paused = True
            finish = getattr(self._driver, "finish_task", None)
            if callable(finish):
                cleanup = self._driver_action("cleanup", "finish_task", finish)
                if not cleanup.get("success"):
                    self._cleanup_blocked = True
                    raise WorkflowError("cleanup", "暂停前窗口清理失败",
                                        error_code="CLEANUP_FAILED", fatal_batch=True)
            self._item_clock.pause()
            if self._progress_emit:
                self._progress_emit("agent.status", {"status": "paused", "taskId": self._active_task_id})

        wait = getattr(control, "wait_at_safe_point", None)
        if callable(wait):
            allowed = wait(before_pause)
        else:
            if bool(getattr(control, "paused", False)):
                before_pause()
            allowed = control.wait_if_paused()
        if not allowed:
            raise StopRequested()
        if paused:
            self._item_clock.resume()
            begin = getattr(self._driver, "begin_task", None)
            if callable(begin):
                begin(self._task_kind)
        return paused

    def _sleep_interval(self, request: TaskRequest, control, emit) -> None:
        minimum = request.options.interval_min
        maximum = request.options.interval_max
        if maximum <= 0:
            return
        remaining = random.uniform(minimum, maximum)
        while remaining > 0:
            self._safe_point(control)
            emit(
                "agent.status",
                {
                    "status": "waiting",
                    "taskId": request.task_id,
                    "remaining": round(remaining, 1),
                },
            )
            duration = min(1.0, remaining)
            self._sleep(duration)
            remaining -= duration
        emit("agent.status", {"status": "waiting", "taskId": request.task_id, "remaining": 0})

    def _mark_boundary(
        self,
        request: TaskRequest,
        item: TaskItem,
        boundary: str,
        index: int,
    ) -> None:
        if self._journal is not None:
            self._journal.mark(
                task_id=request.task_id,
                kind=request.kind,
                item_id=item.item_id,
                boundary=boundary,
                item_index=index,
                session_generation=self._session_generation(),
            )

    def _clear_boundary(self, request: TaskRequest, item: TaskItem) -> None:
        if self._journal is not None:
            self._journal.clear(task_id=request.task_id, item_id=item.item_id)

    def _boundary_exception(
        self,
        emit,
        request: TaskRequest,
        item: TaskItem,
        step: str,
        detail: str,
        index: int,
        control,
        *,
        cause: Exception | None = None,
    ) -> str:
        retry_error = classify_exception(cause) if cause is not None else None
        if isinstance(cause, WorkflowError):
            retry_error = cause.retry_error or retry_error
            error_code = cause.error_code
            fatal_batch = cause.fatal_batch
        elif isinstance(cause, RiskControlError):
            error_code = "RISK_CONTROL"
            fatal_batch = True
        else:
            error_code = getattr(retry_error, "code", "")
            fatal_batch = False
        wechat_responsive = bool(
            retry_error is None or retry_error.wechat_responsive
        )
        outcome = self._finish_boundary(
            emit,
            request,
            item,
            step,
            "unknown",
            detail,
            index,
            control,
            error_code=error_code or "RESULT_UNKNOWN",
            wechat_responsive=wechat_responsive,
            risk_kind=str(getattr(cause, "risk_kind", "")),
        )
        if (
            fatal_batch
            or not wechat_responsive
            or error_code in {
                "GATE_SAFETY",
                "RISK_CONTROL",
                "UNSUPPORTED_VERSION",
            }
        ):
            raise StopAfterBoundary(outcome)
        return outcome

    def _finish_boundary(
        self,
        emit,
        request: TaskRequest,
        item: TaskItem,
        step: str,
        outcome: str,
        detail: str,
        index: int,
        control,
        *,
        error_code: str = "",
        risk_kind: str = "",
        wechat_responsive: bool = True,
    ) -> str:
        self._event(
            emit,
            request,
            item,
            step,
            outcome,
            detail,
            index + 1,
            recoverable=False,
            destructive_boundary_crossed=True,
            wechat_responsive=wechat_responsive,
            error_code=error_code or (
                "RESULT_UNKNOWN"
                if outcome == "unknown"
                else "RESULT_VERIFICATION_FAILED"
                if outcome == "error"
                else ""
            ),
            risk_kind=risk_kind,
        )
        if control.wait_for_result_ack(item.item_id, timeout=5.0):
            self._clear_boundary(request, item)
        else:
            control.request_stop()
        return outcome

    def _event(
        self,
        emit,
        request: TaskRequest,
        item: TaskItem,
        step: str,
        outcome: str,
        detail: str,
        done: int,
        *,
        attempt: int = 1,
        max_attempts: int = 1,
        retry_level: str = "none",
        retry_in_ms: int = 0,
        recoverable: bool = False,
        destructive_boundary_crossed: bool = False,
        wechat_responsive: bool = True,
        error_code: str = "",
        risk_kind: str = "",
    ) -> None:
        if outcome in {"error", "unknown"}:
            self._remember_safety_failure(error_code)
        if outcome == "error" and error_code not in {
            "TARGET_NOT_FOUND", "TARGET_NOT_UNIQUE", "ACCOUNT_NOT_FOUND",
        }:
            self._last_failure_code = error_code or "AUTOMATION_ERROR"
        self._record_diagnostic(
            stage=step,
            action="task.event",
            outcome=(
                "retry"
                if outcome == "working" and retry_level != "none"
                else outcome
            ),
            account=item.account if request.kind == "friend_add" else None,
            contact=item.target if request.kind == "message_send" else None,
            session_generation=self._session_generation(),
            attempt=attempt,
            max_attempts=max_attempts,
            retry_level=retry_level,
            retry_in_ms=retry_in_ms,
            error_code=error_code or None,
        )
        emit(
            "task.event",
            TaskEvent(
                task_id=request.task_id,
                item_id=item.item_id,
                step=step,
                outcome=outcome,
                detail=detail,
                done=done,
                total=len(request.items),
                timestamp=datetime.now(timezone.utc),
                attempt=attempt,
                max_attempts=max_attempts,
                retry_level=retry_level,
                retry_in_ms=retry_in_ms,
                recoverable=recoverable,
                destructive_boundary_crossed=destructive_boundary_crossed,
                wechat_responsive=wechat_responsive,
                error_code=error_code,
                item_elapsed_ms=round(self._item_clock.seconds * 1000, 1),
                risk_kind=risk_kind,
            ).to_payload(),
        )

    def _success_step(
        self,
        emit,
        request: TaskRequest,
        item: TaskItem,
        step: str,
        detail: str,
        index: int,
    ) -> None:
        crossed = step in {"send_triggered", "submit_triggered"}
        self._event(
            emit,
            request,
            item,
            step,
            "success",
            detail,
            index,
            recoverable=False,
            destructive_boundary_crossed=crossed,
        )

    def _run_message_item(
        self,
        driver,
        request: TaskRequest,
        item: TaskItem,
        index: int,
        emit,
        control,
    ) -> str:
        self._run_pre_boundary_with_retry(
            lambda: self._prepare_message_item(driver, item, control),
            driver=driver,
            request=request,
            item=item,
            index=index,
            emit=emit,
            control=control,
        )

        for step, detail in (
            ("window_bound", "已绑定微信窗口"),
            ("search_ready", "搜索入口已就绪"),
            ("target_selected", "已选择唯一目标"),
            ("target_verified", "目标校验通过"),
            ("composer_ready", "输入框已就绪"),
            (
                "content_inserted",
                "内容已写入并核对" if item.message else "本项仅发送附件",
            ),
        ):
            self._success_step(emit, request, item, step, detail, index)

        if self._safe_point(control):
            self._run_pre_boundary_with_retry(
                lambda: self._prepare_message_item(driver, item, control),
                driver=driver, request=request, item=item, index=index,
                emit=emit, control=control,
            )
        boundary_marked = False

        if item.message:
            before = self._driver_action(
                "send_triggered",
                "message_snapshot",
                driver.message_snapshot,
            )
            self._mark_boundary(request, item, "send_triggered", index)
            boundary_marked = True
            try:
                self._driver_action(
                    "send_triggered", "trigger_send", driver.trigger_send
                )
                self._success_step(
                    emit, request, item, "send_triggered", "已触发发送", index
                )
                verified = self._driver_action(
                    "send_verified",
                    "verify_sent",
                    lambda: driver.verify_sent(
                        before, item.message, timeout=5.0
                    ),
                )
            except Exception as exc:
                return self._boundary_exception(
                    emit,
                    request,
                    item,
                    "send_verified",
                    f"发送已触发，但自动化连接中断：{exc}；不会自动重发",
                    index,
                    control,
                    cause=exc,
                )

            if verified is None:
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "unknown",
                    "已触发发送，但无法确认结果；不会自动重发",
                    index,
                    control,
                )
            if not verified:
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "error",
                    "发送结果校验失败",
                    index,
                    control,
                )

        detail = "发送结果已确认"
        if request.options.file_paths:
            if not boundary_marked:
                self._mark_boundary(request, item, "send_triggered", index)
                boundary_marked = True
                self._success_step(
                    emit, request, item, "send_triggered", "已触发附件发送", index
                )
            try:
                file_results = self._driver_action(
                    "send_verified",
                    "send_files",
                    lambda: driver.send_files(request.options.file_paths),
                )
            except Exception as exc:
                return self._boundary_exception(
                    emit,
                    request,
                    item,
                    "send_verified",
                    f"文本已发送，但附件结果无法确认：{exc}；不会重放整项",
                    index,
                    control,
                    cause=exc,
                )
            unknown = [
                result
                for result in file_results
                if result.get("outcome") == "unknown"
            ]
            if unknown:
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "unknown",
                    f"{len(unknown)} 个附件结果未知；不会重放整项",
                    index,
                    control,
                )
            failed = [result for result in file_results if result.get("outcome") != "success"]
            if failed:
                prefix = "文本已发送，" if item.message else ""
                detail = f"{prefix}{len(failed)} 个附件失败"
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "error",
                    detail,
                    index,
                    control,
                )
            if any(result.get("verificationSkipped") is True for result in file_results):
                prefix = "文本已发送，" if item.message else ""
                detail = f"{prefix}{len(file_results)} 个附件发送成功"
            else:
                detail = (
                    f"文本及 {len(file_results)} 个附件已确认"
                    if item.message
                    else f"{len(file_results)} 个附件已确认"
                )
        return self._finish_boundary(
            emit,
            request,
            item,
            "send_verified",
            "success",
            detail,
            index,
            control,
        )

    @staticmethod
    def _exception_hresult(exc: BaseException) -> int | None:
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            value = getattr(current, "hresult", None)
            if isinstance(value, int):
                return value
            if current.args and isinstance(current.args[0], int):
                return int(current.args[0])
            current = current.__cause__ or current.__context__
        return None

    @staticmethod
    def _destructive_trigger_state(exc: BaseException) -> bool | None:
        """Read the closest driver's pre/in/post-injection classification."""

        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if hasattr(current, "destructive_triggered"):
                value = getattr(current, "destructive_triggered")
                return value if value is True or value is False else None
            current = current.__cause__ or current.__context__
        return None

    def _session_generation(self) -> int:
        return int(getattr(self._driver, "_session_generation", 0) or 0)

    def _query_count(self) -> int:
        query = getattr(self._driver, "_query", None)
        return int(getattr(query, "request_count", 0) or 0)

    def _record_diagnostic(self, **entry) -> None:
        if self._diagnostics is None:
            return
        try:
            snapshot = getattr(self._driver, "diagnostic_snapshot", None)
            context = dict(snapshot()) if callable(snapshot) else {}
            entry.update(task_id=self._active_task_id, item_id=self._active_item_id,
                         action_id=self._active_action_id, agent_instance_id=self._instance_id,
                         context=context)
            entry.setdefault("window", context.get("window"))
            self._diagnostics.record(**entry)
        except Exception:
            # Diagnostics must never change task behavior.
            pass

    @staticmethod
    def _check_driver_responsive(driver) -> None:
        check = getattr(driver, "ensure_window_responsive", None)
        if callable(check):
            check()

    def _emit_action_progress(
        self,
        step: str,
        action: str,
        status: str,
        detail: str = "",
    ) -> None:
        emit = self._progress_emit
        if emit is None:
            return
        payload = {
            "status": status,
            "taskId": self._active_task_id,
            "itemId": self._active_item_id,
            "actionId": self._active_action_id,
            "step": step,
            "action": action,
        }
        if detail:
            payload["detail"] = detail
        emit(
            "agent.status",
            payload,
        )

    def _driver_action(self, step: str, action: str, callback):
        started = time.monotonic()
        returned_false = False
        self._active_action_id = uuid.uuid4().hex
        query_before = self._query_count()
        progress_setter = getattr(self._driver, "set_progress_callback", None)
        if callable(progress_setter):
            progress_setter(
                lambda detail: self._emit_action_progress(
                    step,
                    action,
                    "uia_action_progress",
                    detail,
                )
            )
        try:
            try:
                self._emit_action_progress(step, action, "uia_action_started")
                with action_deadline():
                    if action == "finish_task":
                        self._invalidate_task_health("TASK_WINDOW_RELEASED")
                    if action not in {"bind_window", "finish_task", "inspect"}:
                        self._check_driver_responsive(self._driver)
                    self._record_diagnostic(stage=step, action=action, outcome="started",
                                            session_generation=self._session_generation())
                    result = callback()
                    returned_false = result is False
                    if result is False and action in {
                        "ensure_search_ready", "composer_ready", "open_add_friend",
                        "open_friend_request",
                    }:
                        raise TransientUiError("界面前置条件未满足：" + action)
                    health = result if action == "bind_window" else None
                    if result is True and action in {
                        "open_add_friend", "open_friend_request", "cancel_friend_request",
                        "verify_friend_request",
                    }:
                        snapshotter = getattr(self._driver, "verified_task_health", None)
                        if callable(snapshotter):
                            try:
                                health = snapshotter()
                            except Exception as exc:
                                if action != "verify_friend_request":
                                    raise
                                # A confirmed submission must stay confirmed even if
                                # its surviving window cannot be used by the next item.
                                failure = classify_exception(exc)
                                code = failure.code if failure else "HEALTH_CHECK_FAILED"
                                self._remember_safety_failure(code)
                                self._invalidate_task_health(code)
                        elif action == "verify_friend_request":
                            self._invalidate_task_health("TASK_WINDOW_RELEASED")
                    if isinstance(health, dict) and health.get("sessionReady") is True:
                        self._publish_task_health(health)
            except WorkflowError as exc:
                self._remember_safety_failure(exc.error_code)
                raise
            except RiskControlError as exc:
                self._remember_safety_failure("RISK_CONTROL")
                self._invalidate_task_health("RISK_CONTROL")
                self._record_diagnostic(
                    stage=step,
                    action=action,
                    outcome="blocked",
                    duration_ms=(time.monotonic() - started) * 1000,
                    query_count=self._query_count() - query_before,
                    session_generation=self._session_generation(),
                    error_code="RISK_CONTROL",
                    hresult=self._exception_hresult(exc),
                )
                wrapped = RiskControlError(f"{action} 风控阻止：{exc}")
                wrapped.step = step
                wrapped.risk_kind = str(getattr(exc, "risk_kind", ""))
                if wrapped.risk_kind == "frequency" and self._task_kind == "friend_add":
                    wrapped.risk_kind = "friend_frequency"
                raise wrapped from exc
            except Exception as exc:
                retry_error = classify_exception(exc)
                error_code = (
                    retry_error.code if retry_error is not None else {
                        "UnsupportedWeixinVersion": "UNSUPPORTED_VERSION",
                        "AccessibilitySafetyError": "GATE_SAFETY",
                    }.get(type(exc).__name__, "AUTOMATION_ERROR")
                )
                self._remember_safety_failure(error_code)
                self._invalidate_task_health(error_code)
                fatal_batch = type(exc).__name__ in {
                    "UnsupportedWeixinVersion",
                    "AccessibilitySafetyError",
                }
                fatal_batch = fatal_batch or error_code in {
                    "ACTION_DEADLINE_EXCEEDED", "WINDOW_BLOCKED", "CLEANUP_FAILED",
                    "EVENT_CLEANUP_FAILED", "UIA_TREE_NOT_READY_AFTER_REFRESH",
                }
                self._record_diagnostic(
                    stage=step,
                    action=action,
                    outcome="error",
                    duration_ms=(time.monotonic() - started) * 1000,
                    query_count=self._query_count() - query_before,
                    session_generation=self._session_generation(),
                    error_code=error_code,
                    hresult=self._exception_hresult(exc),
                    result={"type": "bool", "value": False} if returned_false else None,
                    postcondition=False if returned_false else None,
                )
                raise WorkflowError(
                    step,
                    f"{action} 失败：{exc}",
                    retry_error=retry_error,
                    error_code=error_code,
                    fatal_batch=fatal_batch,
                ) from exc
            verification = action in {"verify_sent", "verify_friend_request"}
            recorded_outcome = (
                "unconfirmed" if verification and result is None else
                "error" if result is False else "success"
            )
            result_summary = {"type": type(result).__name__}
            if isinstance(result, bool) or result is None:
                result_summary["value"] = result
            elif isinstance(result, (str, list, tuple, dict)):
                result_summary["length"] = len(result)
            postcondition = result if isinstance(result, bool) else None
            cleanup_error_code = None
            if action == "finish_task" and isinstance(result, dict):
                postcondition = result.get("success") is True
                result_summary["success"] = postcondition
                recorded_outcome = "success" if postcondition else "error"
                if not postcondition:
                    reason = result.get("reasonCode", "")
                    # Only stable internal codes enter logs; never cleanup detail.
                    cleanup_error_code = (
                        reason if isinstance(reason, str) and reason.isascii()
                        and reason.replace("_", "").isalnum() and len(reason) <= 80
                        else "CLEANUP_FAILED"
                    )
            self._record_diagnostic(
                stage=step,
                action=action,
                outcome=recorded_outcome,
                result=result_summary,
                postcondition=postcondition,
                error_code=cleanup_error_code,
                duration_ms=(time.monotonic() - started) * 1000,
                query_count=self._query_count() - query_before,
                session_generation=self._session_generation(),
            )
            return result
        finally:
            if callable(progress_setter):
                progress_setter(None)
            self._emit_action_progress(step, action, "uia_action_completed")

    def _publish_task_health(self, health):
        if self._progress_emit is not None:
            self._progress_emit("agent.status", {
                "status": "health", "taskId": self._active_task_id,
                "health": self._stamp_health({**health, "taskId": self._active_task_id}),
            })

    def _invalidate_task_health(self, reason):
        health = {
            **self._last_health, "sessionReady": False, "uiaReady": False,
            "taskWindowReady": False, "taskWindowRole": "", "taskWindowHwnd": 0,
            "restorable": False, "reasonCode": reason, "degradedReason": reason,
        }
        if reason == "WECHAT_UNRESPONSIVE":
            health["windowResponsive"] = False
        self._publish_task_health(health)

    def _run_pre_boundary_with_retry(
        self,
        callback,
        *,
        driver,
        request: TaskRequest,
        item: TaskItem,
        index: int,
        emit,
        control,
    ):
        def retry_notice(notice) -> None:
            self._safe_point(control)
            self._event(
                emit,
                request,
                item,
                getattr(last_error[0], "step", "window_bound"),
                "working",
                f"自动重试 {notice.attempt}/{notice.max_attempts}：{notice.detail}",
                index,
                attempt=notice.attempt,
                max_attempts=notice.max_attempts,
                retry_level=notice.retry_level,
                retry_in_ms=notice.retry_in_ms,
                recoverable=True,
                error_code=notice.error_code,
            )

        last_error = [None]

        def operation():
            try:
                return callback()
            except WorkflowError as exc:
                last_error[0] = exc
                raise

        refresh = getattr(driver, "soft_refresh_session", None)
        try:
            return LayeredRetry(sleep=self._sleep).run(
                operation,
                soft_refresh=(lambda: self._driver_action(
                    "window_bound", "soft_refresh_session", refresh,
                )) if callable(refresh) else None,
                on_retry=retry_notice,
            )
        except RetryExhausted as exc:
            cause = exc.cause
            if isinstance(cause, RiskControlError):
                raise cause
            if isinstance(cause, WorkflowError):
                cause.attempt = exc.attempt
                cause.max_attempts = exc.max_attempts
                cause.retry_level = exc.retry_level
                raise cause
            prior = last_error[0]
            retry_error = classify_exception(cause)
            error_code = (
                retry_error.code
                if retry_error is not None
                else {
                    "AccessibilitySafetyError": "GATE_SAFETY",
                    "UnsupportedWeixinVersion": "UNSUPPORTED_VERSION",
                    "RiskControlError": "RISK_CONTROL",
                }.get(type(cause).__name__, "AUTOMATION_ERROR")
            )
            raise WorkflowError(
                getattr(prior, "step", "window_bound"),
                f"自动化会话刷新失败：{cause}",
                retry_error=retry_error,
                attempt=exc.attempt,
                max_attempts=exc.max_attempts,
                retry_level=exc.retry_level,
                error_code=error_code,
                fatal_batch=error_code
                in {
                    "GATE_SAFETY",
                    "RISK_CONTROL",
                    "UNSUPPORTED_VERSION",
                    "UIA_TREE_NOT_READY_AFTER_REFRESH",
                },
            ) from cause

    def _prepare_message_item(self, driver, item: TaskItem, control) -> None:
        self._driver_action("window_bound", "bind_window", driver.bind_window)
        self._safe_point(control)

        ready = self._driver_action(
            "search_ready", "ensure_search_ready", driver.ensure_search_ready
        )
        if not ready:
            raise WorkflowError(
                "search_ready",
                "ensure_search_ready 失败：搜索入口不可用",
                error_code="SEARCH_NOT_READY",
            )

        candidates = list(
            self._driver_action(
                "target_selected",
                "search_contacts",
                lambda: driver.search_contacts(item.target),
            )
        )
        expected = normalize_identity(item.target)
        exact = [
            candidate
            for candidate in candidates
            if candidate_matches_identity(candidate, expected)
        ]
        if not exact:
            raise WorkflowError(
                "target_selected",
                f"未找到精确目标：{item.target}",
                error_code="TARGET_NOT_FOUND",
            )
        if len(exact) != 1:
            raise WorkflowError(
                "target_selected",
                f"目标不唯一：{item.target}",
                error_code="TARGET_NOT_UNIQUE",
            )
        self._driver_action(
            "target_selected",
            "select_search_result",
            lambda: driver.select_search_result(exact[0]),
        )

        title = self._driver_action(
            "target_verified", "current_chat_title", driver.current_chat_title
        )
        if not candidate_matches_identity(exact[0], normalize_identity(title)):
            raise WorkflowError(
                "target_verified",
                f"聊天标题校验失败：{title or '<空>'}",
                error_code="TARGET_MISMATCH",
            )

        composer_ready = self._driver_action(
            "composer_ready", "composer_ready", driver.composer_ready
        )
        if not composer_ready:
            raise WorkflowError(
                "composer_ready",
                "消息输入框不可用",
                error_code="COMPOSER_NOT_READY",
            )

        if item.message:
            self._driver_action(
                "content_inserted",
                "set_composer_text",
                lambda: driver.set_composer_text(item.message),
            )
            content = self._driver_action(
                "content_inserted",
                "read_composer_text",
                driver.read_composer_text,
            )
            if content != item.message:
                raise WorkflowError(
                    "content_inserted",
                    "输入内容回读不一致",
                    error_code="CONTENT_READBACK_MISMATCH",
                )

    def _run_friend_item(
        self,
        driver,
        request: TaskRequest,
        item: TaskItem,
        index: int,
        emit,
        control,
    ) -> str:
        submit_enabled = (
            self._friend_submit_enabled
            and request.options.submit_friend_request is True
        )
        self._run_pre_boundary_with_retry(
            lambda: self._prepare_friend_item(
                driver,
                item,
                control,
                submit_enabled=submit_enabled,
            ),
            driver=driver,
            request=request,
            item=item,
            index=index,
            emit=emit,
            control=control,
        )
        for step, detail in (
            ("window_bound", "已绑定微信窗口"),
            ("add_friend_window_ready", "添加好友窗口已就绪"),
            ("account_inserted", "账号已写入并核对"),
            ("account_searched", "已搜索账号"),
            ("profile_verified", "资料核对通过"),
            ("request_form_ready", "申请窗口已就绪"),
            ("fields_verified", "申请内容已核对"),
        ):
            self._success_step(emit, request, item, step, detail, index)

        if not submit_enabled:
            self._event(
                emit,
                request,
                item,
                "preflight_completed",
                "success",
                "表单预检完成，未提交好友申请",
                index + 1,
            )
            return "success"

        self._safe_point(control)
        self._mark_boundary(request, item, "submit_triggered", index)
        try:
            self._driver_action(
                "submit_triggered",
                "submit_friend_request",
                driver.submit_friend_request,
            )
        except Exception as exc:
            if self._destructive_trigger_state(exc) is False:
                self._clear_boundary(request, item)
                if isinstance(exc, RiskControlError) or isinstance(exc, WorkflowError) and exc.fatal_batch:
                    raise
                self._event(
                    emit,
                    request,
                    item,
                    "submit_triggered",
                    "error",
                    f"未点击确定：{exc}",
                    index + 1,
                    recoverable=False,
                    destructive_boundary_crossed=False,
                    error_code=getattr(exc, "error_code", "")
                    or "SUBMIT_NOT_TRIGGERED",
                )
                return "error"
            return self._boundary_exception(
                emit,
                request,
                item,
                "submit_verified",
                f"确定点击状态无法判定：{exc}；不会再次提交",
                index,
                control,
                cause=exc,
            )

        self._success_step(
            emit, request, item, "submit_triggered", "已点击确定", index
        )
        try:
            verified = self._driver_action(
                "submit_verified",
                "verify_friend_request",
                lambda: driver.verify_friend_request(timeout=5.0),
            )
        except Exception as exc:
            return self._boundary_exception(
                emit,
                request,
                item,
                "submit_verified",
                f"已点击确定，但结果核对中断：{exc}；不会再次提交",
                index,
                control,
                cause=exc,
            )
        if verified is None:
            return self._finish_boundary(
                emit,
                request,
                item,
                "submit_verified",
                "unknown",
                "已点击确定，但无法确认结果；不会再次提交",
                index,
                control,
            )
        if not verified:
            return self._finish_boundary(
                emit,
                request,
                item,
                "submit_verified",
                "error",
                "好友申请提交校验失败",
                index,
                control,
            )
        return self._finish_boundary(
            emit,
            request,
            item,
            "submit_verified",
            "success",
            "提交结果已确认",
            index,
            control,
        )

    def _prepare_friend_item(
        self,
        driver,
        item: TaskItem,
        control,
        *,
        submit_enabled: bool,
    ) -> None:
        self._driver_action("window_bound", "bind_window", driver.bind_window)
        self._safe_point(control)

        add_friend_ready = self._driver_action(
            "add_friend_window_ready", "open_add_friend", driver.open_add_friend
        )
        if not add_friend_ready:
            raise WorkflowError(
                "add_friend_window_ready",
                "添加好友窗口不可用",
                error_code="FRIEND_WINDOW_NOT_READY",
            )
        self._driver_action(
            "account_inserted",
            "set_friend_account",
            lambda: driver.set_friend_account(item.account),
        )
        profile = self._driver_action(
            "account_searched",
            "search_friend",
            lambda: driver.search_friend(item.account),
        )
        if not profile:
            raise WorkflowError(
                "account_searched",
                f"未找到账号：{item.account}",
                error_code="ACCOUNT_NOT_FOUND",
            )
        actual_account = self._driver_action(
            "profile_verified",
            "profile_account",
            lambda: driver.profile_account(profile),
        )
        if normalize_identity(actual_account) != normalize_identity(item.account):
            raise WorkflowError(
                "profile_verified",
                f"资料账号不匹配：{actual_account or '<空>'}",
                error_code="PROFILE_MISMATCH",
            )
        request_ready = self._driver_action(
            "request_form_ready",
            "open_friend_request",
            lambda: driver.open_friend_request(profile),
        )
        if not request_ready:
            raise WorkflowError(
                "request_form_ready",
                "好友申请窗口不可用",
                error_code="FRIEND_FORM_NOT_READY",
            )
        fields = self._driver_action(
            "fields_verified",
            "set_friend_fields",
            lambda: driver.set_friend_fields(item.greeting, item.remark),
        )
        if item.greeting is not None and fields.get("greeting") != item.greeting:
            raise WorkflowError(
                "fields_verified",
                "打招呼语回读不一致",
                error_code="GREETING_READBACK_MISMATCH",
            )
        if item.remark and fields.get("remark") != item.remark:
            raise WorkflowError(
                "fields_verified",
                "备注回读不一致",
                error_code="REMARK_READBACK_MISMATCH",
            )
        if not submit_enabled:
            cancelled = self._driver_action(
                "preflight_completed",
                "cancel_friend_request",
                driver.cancel_friend_request,
            )
            if not cancelled:
                raise WorkflowError(
                    "preflight_completed",
                    "好友申请表单未能安全关闭",
                    error_code="FRIEND_FORM_CANCEL_FAILED",
                    fatal_batch=True,
                )


__all__ = [
    "RiskControlError",
    "WeixinWorkflowEngine",
    "WorkflowError",
    "normalize_identity",
]
