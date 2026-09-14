from __future__ import annotations

import random
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable

from .contracts import TaskEvent, TaskItem, TaskRequest


class WorkflowError(RuntimeError):
    def __init__(self, step: str, detail: str):
        super().__init__(detail)
        self.step = step
        self.detail = detail


class RiskControlError(RuntimeError):
    """A Weixin risk, frequency, account, or captcha stop signal."""


class StopRequested(RuntimeError):
    pass


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
    ):
        if driver_factory is None:
            from .native_driver import NativeWeixinDriver

            driver_factory = NativeWeixinDriver
        self._driver_factory = driver_factory
        self._sleep = sleep
        self._journal = journal

    def inspect(self) -> dict[str, Any]:
        driver = self._driver_factory()
        try:
            return dict(driver.inspect())
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                close()

    def recover_wechat(self, timeout: int, emit) -> dict[str, Any]:
        driver = self._driver_factory()
        try:
            return dict(driver.restart_wechat(timeout, emit))
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                close()

    def run(self, request: TaskRequest, control, emit) -> dict[str, Any]:
        if request.kind == "friend_add" and len(request.items) > 20:
            raise ValueError("friend task cannot contain more than 20 items")
        driver = self._driver_factory()
        counts = {"success": 0, "error": 0, "unknown": 0, "stopped": 0}
        done = 0
        forced_stop = False
        try:
            if request.kind == "message_send" and request.options.use_forward:
                if not request.options.file_paths:
                    raise ValueError("merged forwarding requires at least one file")
                first_item = request.items[0]
                self._mark_boundary(
                    request, first_item, "forward_source_upload", 0
                )
                try:
                    preparation = driver.prepare_forward_bundle(
                        request.options.file_paths
                    )
                except Exception as exc:
                    preparation = {
                        "outcome": "unknown",
                        "detail": f"源文件上传后自动化连接中断：{exc}",
                    }
                if preparation.get("outcome") != "success":
                    detail = str(
                        preparation.get("detail", "合并转发源文件准备失败")
                    )
                    outcome = (
                        "unknown"
                        if preparation.get("outcome") == "unknown"
                        else "error"
                    )
                    for index, item in enumerate(request.items):
                        if index == 0:
                            self._finish_boundary(
                                emit,
                                request,
                                item,
                                "send_verified",
                                outcome,
                                detail,
                                index,
                                control,
                            )
                        else:
                            self._event(
                                emit,
                                request,
                                item,
                                "send_verified",
                                outcome,
                                detail,
                                index + 1,
                            )
                    return {
                        "outcome": outcome,
                        "done": len(request.items),
                        "total": len(request.items),
                        "success": 0,
                        "error": len(request.items) if outcome == "error" else 0,
                        "unknown": (
                            len(request.items) if outcome == "unknown" else 0
                        ),
                        "stopped": 0,
                    }
                self._mark_boundary(
                    request, first_item, "forward_source_ready", 0
                )
            for index, item in enumerate(request.items):
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
                    )
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
                    )
                counts[outcome] += 1
                done += 1
                if forced_stop:
                    break
                if outcome == "unknown" and request.options.unknown_policy == "stop":
                    break
                if index + 1 < len(request.items):
                    self._safe_point(control)
                    self._sleep_interval(request, control, emit)
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                close()

        if (
            request.kind == "message_send"
            and request.options.use_forward
            and self._journal is not None
            and not control.stop_requested
        ):
            self._journal.clear(task_id=request.task_id)

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

    @staticmethod
    def _safe_point(control) -> None:
        if not control.wait_if_paused():
            raise StopRequested()

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
    ) -> str:
        return self._finish_boundary(
            emit,
            request,
            item,
            step,
            "unknown",
            detail,
            index,
            control,
        )

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
    ) -> str:
        self._event(
            emit,
            request,
            item,
            step,
            outcome,
            detail,
            index + 1,
        )
        if control.wait_for_result_ack(item.item_id, timeout=5.0):
            self._clear_boundary(request, item)
        else:
            control.request_stop()
        return outcome

    @staticmethod
    def _event(
        emit,
        request: TaskRequest,
        item: TaskItem,
        step: str,
        outcome: str,
        detail: str,
        done: int,
    ) -> None:
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
        self._event(emit, request, item, step, "success", detail, index)

    def _run_message_item(
        self,
        driver,
        request: TaskRequest,
        item: TaskItem,
        index: int,
        emit,
        control,
    ) -> str:
        last_error: WorkflowError | None = None
        for _attempt in range(2):
            try:
                self._prepare_message_item(driver, item, control)
                last_error = None
                break
            except WorkflowError as exc:
                last_error = exc
                self._safe_point(control)
        if last_error is not None:
            raise last_error

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

        self._safe_point(control)
        boundary_marked = False
        if request.options.use_forward:
            self._mark_boundary(request, item, "send_triggered", index)
            boundary_marked = True
            try:
                result = driver.forward_bundle(
                    item.target, item.message, request.options.file_paths
                )
                self._success_step(
                    emit, request, item, "send_triggered", "已触发合并转发", index
                )
            except Exception as exc:
                return self._boundary_exception(
                    emit,
                    request,
                    item,
                    "send_verified",
                    f"转发已触发，但自动化连接中断：{exc}；不会自动重发",
                    index,
                    control,
                )
            outcome = str(result.get("outcome", "unknown"))
            if outcome == "unknown":
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "unknown",
                    str(result.get("detail", "合并转发结果无法确认；不会自动重发")),
                    index,
                    control,
                )
            if outcome != "success":
                return self._finish_boundary(
                    emit,
                    request,
                    item,
                    "send_verified",
                    "error",
                    str(result.get("detail", "合并转发失败")),
                    index,
                    control,
                )
            return self._finish_boundary(
                emit,
                request,
                item,
                "send_verified",
                "success",
                str(result.get("detail", "合并转发结果已确认")),
                index,
                control,
            )

        if item.message:
            try:
                before = driver.message_snapshot()
            except Exception as exc:
                raise WorkflowError(
                    "send_verified", f"message_snapshot 失败：{exc}"
                ) from exc
            self._mark_boundary(request, item, "send_triggered", index)
            boundary_marked = True
            try:
                driver.trigger_send()
                self._success_step(
                    emit, request, item, "send_triggered", "已触发发送", index
                )
                verified = driver.verify_sent(before, item.message, timeout=5.0)
            except Exception as exc:
                return self._boundary_exception(
                    emit,
                    request,
                    item,
                    "send_verified",
                    f"发送已触发，但自动化连接中断：{exc}；不会自动重发",
                    index,
                    control,
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
                file_results = driver.send_files(request.options.file_paths)
            except Exception as exc:
                return self._boundary_exception(
                    emit,
                    request,
                    item,
                    "send_verified",
                    f"文本已发送，但附件结果无法确认：{exc}；不会重放整项",
                    index,
                    control,
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
    def _driver_action(step: str, action: str, callback):
        try:
            return callback()
        except WorkflowError:
            raise
        except RiskControlError as exc:
            wrapped = RiskControlError(f"{action} 风控阻止：{exc}")
            wrapped.step = step
            raise wrapped from exc
        except Exception as exc:
            raise WorkflowError(step, f"{action} 失败：{exc}") from exc

    def _prepare_message_item(self, driver, item: TaskItem, control) -> None:
        self._driver_action("window_bound", "bind_window", driver.bind_window)
        self._safe_point(control)

        ready = self._driver_action(
            "search_ready", "ensure_search_ready", driver.ensure_search_ready
        )
        if not ready:
            raise WorkflowError("search_ready", "ensure_search_ready 失败：搜索入口不可用")

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
            raise WorkflowError("target_selected", f"未找到精确目标：{item.target}")
        if len(exact) != 1:
            raise WorkflowError("target_selected", f"目标不唯一：{item.target}")
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
                "target_verified", f"聊天标题校验失败：{title or '<空>'}"
            )

        composer_ready = self._driver_action(
            "composer_ready", "composer_ready", driver.composer_ready
        )
        if not composer_ready:
            raise WorkflowError("composer_ready", "消息输入框不可用")

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
                raise WorkflowError("content_inserted", "输入内容回读不一致")

    def _run_friend_item(
        self,
        driver,
        request: TaskRequest,
        item: TaskItem,
        index: int,
        emit,
        control,
    ) -> str:
        self._driver_action("window_bound", "bind_window", driver.bind_window)
        self._success_step(
            emit, request, item, "window_bound", "已绑定微信窗口", index
        )
        self._safe_point(control)

        add_friend_ready = self._driver_action(
            "add_friend_window_ready", "open_add_friend", driver.open_add_friend
        )
        if not add_friend_ready:
            raise WorkflowError(
                "add_friend_window_ready", "添加好友窗口不可用"
            )
        self._success_step(
            emit,
            request,
            item,
            "add_friend_window_ready",
            "添加好友窗口已就绪",
            index,
        )

        self._driver_action(
            "account_inserted",
            "set_friend_account",
            lambda: driver.set_friend_account(item.account),
        )
        self._success_step(
            emit, request, item, "account_inserted", "账号已写入并核对", index
        )

        profile = self._driver_action(
            "account_searched",
            "search_friend",
            lambda: driver.search_friend(item.account),
        )
        if not profile:
            raise WorkflowError("account_searched", f"未找到账号：{item.account}")
        self._success_step(
            emit, request, item, "account_searched", "已搜索账号", index
        )

        actual_account = self._driver_action(
            "profile_verified",
            "profile_account",
            lambda: driver.profile_account(profile),
        )
        if normalize_identity(actual_account) != normalize_identity(item.account):
            raise WorkflowError(
                "profile_verified", f"资料账号不匹配：{actual_account or '<空>'}"
            )
        self._success_step(
            emit, request, item, "profile_verified", "资料核对通过", index
        )

        request_ready = self._driver_action(
            "request_form_ready",
            "open_friend_request",
            lambda: driver.open_friend_request(profile),
        )
        if not request_ready:
            raise WorkflowError("request_form_ready", "好友申请窗口不可用")
        self._success_step(
            emit, request, item, "request_form_ready", "申请窗口已就绪", index
        )

        fields = self._driver_action(
            "fields_verified",
            "set_friend_fields",
            lambda: driver.set_friend_fields(item.greeting, item.remark),
        )
        if item.greeting is not None and fields.get("greeting") != item.greeting:
            raise WorkflowError("fields_verified", "打招呼语回读不一致")
        if item.remark and fields.get("remark") != item.remark:
            raise WorkflowError("fields_verified", "备注回读不一致")
        self._success_step(
            emit, request, item, "fields_verified", "申请内容已核对", index
        )

        self._safe_point(control)
        self._mark_boundary(request, item, "submit_triggered", index)
        try:
            driver.submit_friend_request()
            verified = driver.verify_friend_request(timeout=5.0)
        except Exception as exc:
            return self._boundary_exception(
                emit,
                request,
                item,
                "submit_verified",
                f"已点击确定，但自动化连接中断：{exc}；不会再次提交",
                index,
                control,
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


__all__ = [
    "RiskControlError",
    "WeixinWorkflowEngine",
    "WorkflowError",
    "normalize_identity",
]
