from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


TaskKind = Literal["message_send", "friend_add"]
Outcome = Literal["pending", "working", "success", "error", "unknown", "stopped"]

MESSAGE_STEPS = (
    "window_bound",
    "search_ready",
    "target_selected",
    "target_verified",
    "composer_ready",
    "content_inserted",
    "send_triggered",
    "send_verified",
)

FRIEND_STEPS = (
    "window_bound",
    "add_friend_window_ready",
    "account_inserted",
    "account_searched",
    "profile_verified",
    "request_form_ready",
    "fields_verified",
    "preflight_completed",
    "submit_verified",
)


class ContractError(ValueError):
    """Raised when an RPC payload violates the shared contract."""


@dataclass(frozen=True)
class TaskOptions:
    interval_min: float = 0.0
    interval_max: float = 0.0
    unknown_policy: str = "continue"
    use_forward: bool = False
    file_paths: tuple[str, ...] = ()
    submit_friend_request: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "TaskOptions":
        data = payload or {}
        minimum = float(data.get("intervalMin", 0.0))
        maximum = float(data.get("intervalMax", minimum))
        if minimum < 0 or maximum < minimum:
            raise ContractError("invalid interval range")
        policy = str(data.get("unknownPolicy", "continue"))
        if policy not in {"continue", "stop"}:
            raise ContractError("unknownPolicy must be continue or stop")
        submit_friend_request = data.get("submitFriendRequest", False)
        if type(submit_friend_request) is not bool:
            raise ContractError("submitFriendRequest must be a boolean")
        return cls(
            interval_min=minimum,
            interval_max=maximum,
            unknown_policy=policy,
            use_forward=bool(data.get("useForward", False)),
            file_paths=tuple(str(path) for path in data.get("filePaths", ())),
            submit_friend_request=submit_friend_request,
        )


@dataclass(frozen=True)
class TaskItem:
    item_id: str
    target: str = ""
    message: str = ""
    account: str = ""
    greeting: str | None = None
    remark: str = ""

    @classmethod
    def from_payload(cls, kind: TaskKind, payload: dict[str, Any]) -> "TaskItem":
        item_id = str(payload.get("itemId", "")).strip()
        if not item_id:
            raise ContractError("itemId is required")
        if kind == "message_send":
            target = str(payload.get("target", "")).strip()
            if not target:
                raise ContractError("message target is required")
            return cls(
                item_id=item_id,
                target=target,
                message=str(payload.get("message", "")),
            )
        account = str(payload.get("account", "")).strip()
        if not account:
            raise ContractError("friend account is required")
        greeting = payload.get("greeting")
        return cls(
            item_id=item_id,
            account=account,
            greeting=None if greeting is None else str(greeting),
            remark=str(payload.get("remark", "")),
        )


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    kind: TaskKind
    items: tuple[TaskItem, ...]
    options: TaskOptions = field(default_factory=TaskOptions)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskRequest":
        task_id = str(payload.get("taskId", "")).strip()
        if not task_id:
            raise ContractError("taskId is required")
        kind = payload.get("kind")
        if kind not in {"message_send", "friend_add"}:
            raise ContractError("kind must be message_send or friend_add")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ContractError("items must be a list")
        items = tuple(TaskItem.from_payload(kind, item) for item in raw_items)
        return cls(
            task_id=task_id,
            kind=kind,
            items=items,
            options=TaskOptions.from_payload(payload.get("options")),
        )


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    item_id: str
    step: str
    outcome: Outcome
    detail: str
    done: int
    total: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempt: int = 1
    max_attempts: int = 1
    retry_level: str = "none"
    retry_in_ms: int = 0
    recoverable: bool = False
    destructive_boundary_crossed: bool = False
    wechat_responsive: bool = True
    error_code: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "itemId": self.item_id,
            "step": self.step,
            "outcome": self.outcome,
            "detail": self.detail,
            "done": self.done,
            "total": self.total,
            "timestamp": self.timestamp.isoformat(),
            "attempt": self.attempt,
            "maxAttempts": self.max_attempts,
            "retryLevel": self.retry_level,
            "retryInMs": self.retry_in_ms,
            "recoverable": self.recoverable,
            "destructiveBoundaryCrossed": self.destructive_boundary_crossed,
            "wechatResponsive": self.wechat_responsive,
            "errorCode": self.error_code,
        }
