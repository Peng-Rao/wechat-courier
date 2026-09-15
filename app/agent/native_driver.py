from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .actions import ActionVerificationError, VerifiedActions, describe_control
from .gate import (
    AccessibilitySafetyError,
    NativeGateBackend,
    WeixinAccessibilitySession,
    restore_gate_lease,
)
from .journal import GateLeaseJournal
from .profile import UnsupportedWeixinVersion, get_weixin_profile
from .retry import (
    AutomationRetryError,
    StaleElementError,
    TransientUiError,
    UiaTreeNotReadyError,
    WeixinUnresponsiveError,
    classify_exception,
)
from .uia_query import ScopedQueryUnavailable, ScopedUiaQuery
from .uia_events import EventCleanupError, subscribe_uia_events
from .waiters import ActionDeadlineExceeded, DeadlineWaiter, check_action_deadline
from .workflows import RiskControlError, normalize_identity


INTERACTIVE_CONTROL_TYPES = {
    "ButtonControl",
    "CustomControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
    "TabItemControl",
}
FRIEND_REQUEST_TITLES = ("申请添加朋友", "发送添加朋友申请")
RISK_KEYWORDS = (
    "验证码",
    "操作频繁",
    "风险提示",
    "账号限制",
    "安全验证",
    "环境异常",
)
FORWARD_CONFIRMATION_KEYWORDS = ("聊天记录", "合并转发")
FRIEND_IDENTITY_LABELS = ("微信号", "手机号", "账号", "帐号")
FRIEND_SUBMIT_SUCCESS_NAMES = (
    "朋友申请已发送",
    "好友申请已发送",
    "等待验证",
    "申请已提交",
)
CHAT_TITLE_CONTAINER_CLASS = "mmui::ChatTitleBarMasterView"
CHAT_TITLE_CONTROL_CLASS = "mmui::XTextView"
CHAT_TITLE_AUTOMATION_ID = (
    "content_view.top_content_view.title_h_view.left_v_view."
    "left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label"
)
SEARCH_EMPTY_STABLE_SECONDS = 0.5
SEARCH_DESTINATION_TIMEOUT_SECONDS = 2.0


class WindowBlockedError(AutomationRetryError):
    code = "WINDOW_BLOCKED"


_STOP_ERRORS = (WeixinUnresponsiveError, WindowBlockedError, ActionDeadlineExceeded, EventCleanupError)


@dataclass(frozen=True)
class SearchCandidate:
    """Immutable search-row description; deliberately contains no UIA wrapper."""

    display_name: str
    identities: frozenset[str]
    result_type: str
    automation_id: str
    row_index: int = field(compare=False)
    row_depth: int = field(compare=False)
    runtime_id: tuple[int, ...] = field(default=(), compare=False)
    semantic_row_key: str = field(default="", compare=False)


@dataclass(frozen=True)
class SearchResultRow:
    """One ephemeral search snapshot entry with its exact originating row."""

    candidate: SearchCandidate
    control: Any = field(compare=False, repr=False)


@dataclass(frozen=True)
class MessageBubbleSnapshot:
    """In-memory evidence for one top-level Weixin message bubble."""

    identity: tuple[Any, ...]
    runtime_id: tuple[int, ...]
    class_name: str
    automation_id: str
    accessible_names: tuple[str, ...]
    bounds: tuple[int, int, int, int] | None
    order: int = field(compare=False)
    outgoing: bool | None = field(compare=False)


@dataclass(frozen=True)
class FriendSubmitReceipt:
    """Proof that the one-way friend-submit mouse injection returned."""

    triggered: bool
    method: str
    control_reference: tuple[Any, ...]
    point: tuple[int, int]


def _runtime_id(control: Any) -> tuple[int, ...]:
    try:
        value = control.GetRuntimeId()
    except _STOP_ERRORS:
        raise
    except Exception:
        value = safe_attr(control, "RuntimeId", ())
    try:
        return tuple(int(part) for part in value)
    except (TypeError, ValueError):
        return ()


def _search_row_kind(control: Any) -> str | None:
    name = str(safe_attr(control, "Name", "")).strip()
    control_type = str(safe_attr(control, "ControlTypeName", ""))
    class_name = str(safe_attr(control, "ClassName", ""))
    automation_id = str(safe_attr(control, "AutomationId", ""))
    if control_type != "ListItemControl":
        return None
    if (
        "SearchContentCellView" not in class_name
        and class_name != "mmui::XTableCell"
    ):
        return None
    if not automation_id.startswith("search_item_"):
        return None
    lowered_id = automation_id.casefold()
    if "web" in lowered_id or "network" in lowered_id:
        return None
    if name in {"搜索网络结果", "网络搜索", "搜一搜"}:
        return None
    if automation_id.startswith("search_item_function"):
        return "function"
    return "contact"


def safe_attr(control: Any, name: str, default=None):
    if control is None:
        return default
    try:
        value = getattr(control, name)
    except _STOP_ERRORS:
        raise
    except Exception:
        return default
    return default if value is None else value


def find_exact_control(
    nodes: Iterable[tuple[Any, int]],
    *,
    name: str | Sequence[str] | None = None,
    control_type: str | None = None,
    control_types: Sequence[str] | None = None,
    class_name: str | None = None,
    automation_id: str | None = None,
    enabled: bool = True,
    visible: bool | None = None,
):
    accepted_names = None
    if isinstance(name, str):
        accepted_names = {name.strip()}
    elif name is not None:
        accepted_names = {item.strip() for item in name}
    accepted_control_types = set(control_types) if control_types is not None else None
    for control, _depth in nodes:
        if accepted_names is not None:
            if str(safe_attr(control, "Name", "")).strip() not in accepted_names:
                continue
        if control_type is not None:
            if str(safe_attr(control, "ControlTypeName", "")) != control_type:
                continue
        if accepted_control_types is not None:
            if (
                str(safe_attr(control, "ControlTypeName", ""))
                not in accepted_control_types
            ):
                continue
        if class_name is not None:
            if str(safe_attr(control, "ClassName", "")) != class_name:
                continue
        if automation_id is not None:
            if str(safe_attr(control, "AutomationId", "")) != automation_id:
                continue
        if enabled and not bool(safe_attr(control, "IsEnabled", False)):
            continue
        if visible is True and bool(safe_attr(control, "IsOffscreen", True)):
            continue
        if visible is False and not bool(safe_attr(control, "IsOffscreen", False)):
            continue
        return control
    return None


def _semantic_row_key(
    result_type: str, automation_id: str, identities: Iterable[str]
) -> str:
    normalized = sorted(
        {
            normalize_identity(str(identity))
            for identity in identities
            if normalize_identity(str(identity))
        }
    )
    return "|".join((result_type, automation_id, *normalized))


def extract_search_result_rows(
    nodes: Iterable[tuple[Any, int]],
) -> list[SearchResultRow]:
    materialized = list(nodes)
    results: list[SearchResultRow] = []
    row_index = 0
    for index, (control, depth) in enumerate(materialized):
        name = str(safe_attr(control, "Name", "")).strip()
        automation_id = str(safe_attr(control, "AutomationId", ""))
        result_type = _search_row_kind(control)
        if result_type is None:
            continue
        is_function = result_type == "function"
        identities: dict[str, str] = {}
        if name:
            identities.setdefault(normalize_identity(name), name)
        for child, child_depth in materialized[index + 1 :]:
            if child_depth <= depth:
                break
            child_name = str(safe_attr(child, "Name", "")).strip()
            if child_name:
                identities.setdefault(normalize_identity(child_name), child_name)
        if is_function:
            helper_key = normalize_identity("文件传输助手")
            if helper_key not in identities:
                continue
            display_name = identities[helper_key]
            values = frozenset({display_name})
        else:
            values = frozenset(value for key, value in identities.items() if key)
            if not values:
                continue
            display_name = name or next(iter(identities.values()))
        candidate = SearchCandidate(
            display_name=display_name,
            identities=values,
            result_type=result_type,
            automation_id=automation_id,
            row_index=row_index,
            row_depth=depth,
            runtime_id=_runtime_id(control),
            semantic_row_key=_semantic_row_key(result_type, automation_id, values),
        )
        results.append(
            SearchResultRow(candidate=candidate, control=control)
        )
        row_index += 1
    return results


def extract_contact_results(
    nodes: Iterable[tuple[Any, int]],
) -> list[SearchCandidate]:
    return [entry.candidate for entry in extract_search_result_rows(nodes)]


def extract_exact_forward_candidates(
    nodes: Iterable[tuple[Any, int]], target: str
) -> list[Any]:
    expected = normalize_identity(target)
    candidates = []
    seen = set()
    for control, _depth in nodes:
        if str(safe_attr(control, "ControlTypeName", "")) not in {
            "ListItemControl",
            "ButtonControl",
            "CheckBoxControl",
        }:
            continue
        if not bool(safe_attr(control, "IsEnabled", False)):
            continue
        if bool(safe_attr(control, "IsOffscreen", True)):
            continue
        if normalize_identity(str(safe_attr(control, "Name", ""))) != expected:
            continue
        key = _control_reference(control)
        if key not in seen:
            seen.add(key)
            candidates.append(control)
    return candidates


def filter_recent_message_bubbles(
    nodes: Iterable[tuple[Any, int]],
    accepted_classes: Sequence[str],
    count: int,
) -> list[Any]:
    if count <= 0:
        return []
    accepted = set(accepted_classes)
    bubbles = [
        control
        for control, _depth in nodes
        if str(safe_attr(control, "ClassName", "")) in accepted
    ]
    return bubbles[-count:]


def control_key(control: Any) -> tuple:
    rectangle = safe_attr(control, "BoundingRectangle")
    rect = None
    if rectangle is not None:
        rect = (
            rectangle.left,
            rectangle.top,
            rectangle.right,
            rectangle.bottom,
        )
    return (
        str(safe_attr(control, "Name", "")),
        str(safe_attr(control, "ClassName", "")),
        str(safe_attr(control, "AutomationId", "")),
        rect,
    )


def _stable_message_control_identity(control: Any) -> tuple:
    """Identify a message independently from layout changes.

    Weixin moves existing message controls when the chat is relaid out.  Bounds
    therefore cannot be used to decide whether a confirmation card is new.
    RuntimeId is preferred; providers without one fall back to stable semantic
    properties only.
    """

    runtime_id = _runtime_id(control)
    if runtime_id:
        return ("runtime", runtime_id)
    return (
        "fallback",
        str(safe_attr(control, "Name", "")),
        str(safe_attr(control, "ControlTypeName", "")),
        str(safe_attr(control, "ClassName", "")),
        str(safe_attr(control, "AutomationId", "")),
    )


def has_new_forward_confirmation(
    controls: Iterable[Any], before: Iterable[tuple]
) -> bool:
    prior_identities = set()
    for entry in before:
        if (
            isinstance(entry, tuple)
            and len(entry) == 2
            and isinstance(entry[0], tuple)
            and entry[0]
            and entry[0][0] in {"runtime", "fallback"}
        ):
            prior_identities.add(entry[0])
        else:
            prior_identities.add(entry)

    message_controls = []
    for control in controls:
        class_name = str(safe_attr(control, "ClassName", ""))
        if "Chat" not in class_name and "Message" not in class_name:
            continue
        message_controls.append(control)

    if not message_controls:
        return False
    tail = message_controls[-1]
    if _stable_message_control_identity(tail) in prior_identities:
        return False
    text = str(safe_attr(tail, "Name", "")).strip()
    return any(keyword in text for keyword in FORWARD_CONFIRMATION_KEYWORDS)


def resolve_friend_form_fields(nodes: Iterable[tuple[Any, int]]):
    materialized = list(nodes)
    greeting = find_exact_control(
        materialized,
        name="发送添加朋友申请",
        control_type="EditControl",
    )
    remark = find_exact_control(
        materialized,
        name="修改备注",
        control_type="EditControl",
    )
    if greeting is None or remark is None:
        raise RuntimeError("好友申请表单字段未完整暴露到 UIA")
    return greeting, remark


def raise_for_risk_controls(nodes: Iterable[tuple[Any, int]]) -> None:
    for control, _depth in nodes:
        text = str(safe_attr(control, "Name", "")).strip()
        if text and any(keyword in text for keyword in RISK_KEYWORDS):
            raise RiskControlError(text)


def extract_labeled_friend_identities(
    nodes: Iterable[tuple[Any, int]],
) -> list[str]:
    """Read profile identities only from explicit account labels."""
    materialized = list(nodes)
    identities: list[str] = []
    inline_pattern = re.compile(
        rf"^(?:{'|'.join(FRIEND_IDENTITY_LABELS)})\s*[：:]\s*(.+)$"
    )
    for index, (control, depth) in enumerate(materialized):
        text = str(safe_attr(control, "Name", "")).strip()
        match = inline_pattern.match(text)
        if match:
            value = match.group(1).strip()
            if value:
                identities.append(value)
            continue
        if text not in FRIEND_IDENTITY_LABELS:
            continue
        for next_control, next_depth in materialized[index + 1 : index + 3]:
            value = str(safe_attr(next_control, "Name", "")).strip()
            if next_depth < depth or value in FRIEND_IDENTITY_LABELS:
                break
            if value:
                identities.append(value)
                break
    unique: dict[str, str] = {}
    for value in identities:
        unique.setdefault(normalize_identity(value), value)
    return [value for key, value in unique.items() if key]


def _profile_add_friend_buttons(
    nodes: Sequence[tuple[Any, int]],
) -> list[Any]:
    """Return only add-friend buttons nested in the real profile action card."""
    matching: list[Any] = []
    stack: list[tuple[int, str]] = []
    for control, depth in nodes:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        class_name = str(safe_attr(control, "ClassName", ""))
        automation_id = str(safe_attr(control, "AutomationId", ""))
        if (
            str(safe_attr(control, "Name", "")).strip() == "添加到通讯录"
            and str(safe_attr(control, "ControlTypeName", "")) == "ButtonControl"
            and class_name == "mmui::XOutlineButton"
            and automation_id.endswith("ProfileActionUi.add_friend_button")
            and bool(safe_attr(control, "IsEnabled", False))
            and not bool(safe_attr(control, "IsOffscreen", True))
            and any(
                ancestor_class == "mmui::ProfileActionUi"
                for _ancestor_depth, ancestor_class in stack
            )
            and any(
                ancestor_class == "mmui::ProfileViewNormal"
                for _ancestor_depth, ancestor_class in stack
            )
        ):
            matching.append(control)
        stack.append((depth, class_name))
    return matching


def _unique_visible_add_friend_button(
    nodes: Sequence[tuple[Any, int]],
) -> Any | None:
    structured = _profile_add_friend_buttons(nodes)
    if len(structured) == 1:
        return structured[0]
    if structured:
        return None
    generic = [
        control
        for control, _depth in nodes
        if str(safe_attr(control, "Name", "")).strip() == "添加到通讯录"
        and str(safe_attr(control, "ControlTypeName", "")) == "ButtonControl"
        and bool(safe_attr(control, "IsEnabled", False))
        and not bool(safe_attr(control, "IsOffscreen", True))
    ]
    return generic[0] if len(generic) == 1 else None


def _control_reference(control: Any) -> tuple[Any, ...]:
    """Capture a fail-closed reference for one current UIA control instance."""
    semantic = (
        str(safe_attr(control, "Name", "")),
        str(safe_attr(control, "ControlTypeName", "")),
        str(safe_attr(control, "ClassName", "")),
        str(safe_attr(control, "AutomationId", "")),
    )
    runtime_id = _runtime_id(control)
    if runtime_id:
        return ("runtime", runtime_id, semantic)
    # Bounds are only a last-resort discriminator when a provider offers no
    # RuntimeId. The unlabeled friend-profile boundary requires RuntimeId and
    # therefore never takes this weaker path.
    return ("semantic_bounds", semantic, control_key(control)[-1])


def _exact_query_profile_card_button(
    nodes: Sequence[tuple[Any, int]],
    *,
    search_control: Any,
    account: str,
    read_text,
) -> Any | None:
    """Verify the real 4.1.13.65 profile card when it exposes no ID label.

    The current build shows only a nickname on this card. In that layout, the
    exact search value, one visible profile action, and its verified ancestor
    chain jointly form the pre-request boundary. A generic search box or an
    unscoped same-name button is never sufficient.
    """
    expected = normalize_identity(account)
    if not expected or normalize_identity(read_text(search_control) or "") != expected:
        return None
    if (
        str(safe_attr(search_control, "ControlTypeName", "")) != "EditControl"
        or str(safe_attr(search_control, "ClassName", ""))
        != "mmui::XValidatorTextEdit"
    ):
        return None

    profile_count = sum(
        1
        for control, _depth in nodes
        if str(safe_attr(control, "ClassName", "")) == "mmui::ProfileViewNormal"
    )
    if profile_count != 1:
        return None
    matching_buttons = _profile_add_friend_buttons(nodes)
    if len(matching_buttons) != 1:
        return None
    button = matching_buttons[0]
    # The unlabeled-card fallback has no account label to bind against. A
    # RuntimeId is therefore mandatory so the exact verified button can be
    # checked again immediately before invoking it.
    profile = next(
        control
        for control, _depth in nodes
        if str(safe_attr(control, "ClassName", "")) == "mmui::ProfileViewNormal"
    )
    return button if _runtime_id(button) and _runtime_id(profile) else None


class NativeWeixinDriver:
    """Exact-profile UIA driver for Weixin 4.1.13.65."""

    def __init__(
        self,
        *,
        gate_backend: Any | None = None,
        gate_lease_journal: GateLeaseJournal | None = None,
        timeout: float = 5.0,
        sleep=time.sleep,
    ):
        self._gate_backend = gate_backend or NativeGateBackend()
        self._gate_lease_journal = (
            gate_lease_journal or GateLeaseJournal.from_environment()
        )
        self._timeout = timeout
        self._sleep = sleep
        self._waiter = DeadlineWaiter(0.25)
        self._session: WeixinAccessibilitySession | None = None
        self._uia = None
        self._query: ScopedUiaQuery | None = None
        self._root = None
        self._search_edit = None
        self._search_results: list[SearchCandidate] = []
        self._search_query = ""
        self._selected_target = ""
        self._selected_identities: frozenset[str] = frozenset()
        self._composer = None
        self._add_hwnd = 0
        self._verify_hwnd = 0
        self._friend_account = ""
        self._friend_profile_reset_for = ""
        self._friend_query_generation = 0
        self._friend_profile_token: tuple[Any, ...] | None = None
        self._friend_search = None
        self._forward_source_count = 0
        self._session_generation = 0
        self._session_identity_changed = False
        self._lease_checked = False
        self._screen_reader_restore_value: bool | None = None
        self._uia_initialized = False
        self._wake_event = threading.Event()
        self._event_subscription = None
        self._event_cleanup_error = None
        self._progress_callback = None
        self._task_kind = ""
        self._task_owned_add_hwnd = 0
        self._task_process_identity = None
        self._bound_window_role = ""
        self._actions = VerifiedActions(
            waiter=self._waiter,
            click_fallback=self._click_bounds,
            replace_text_fallback=self._replace_text,
            timeout=timeout,
        )

    def set_progress_callback(self, callback) -> None:
        self._progress_callback = callback

    def begin_task(self, kind: str) -> None:
        """Start a cleanup scope without discovering, binding, or touching UIA."""
        if self._task_owned_add_hwnd:
            raise WindowBlockedError("Previous task-owned window still requires cleanup")
        self._task_kind = str(kind)
        self._task_owned_add_hwnd = 0
        self._task_process_identity = None

    def _window_guard_state(self) -> dict[str, Any]:
        inspect_window = getattr(self._gate_backend, "window_inspection", None)
        state = dict(inspect_window()) if callable(inspect_window) else {}
        if "windowEnabled" not in state and isinstance(self._gate_backend, NativeGateBackend):
            import win32gui
            import win32process

            hwnd = int(state.get("hwnd", 0) or 0)
            state["windowEnabled"] = bool(hwnd and win32gui.IsWindowEnabled(hwnd))
            state["blockingWindow"] = None
            if hwnd and not state["windowEnabled"]:
                popup = int(win32gui.GetWindow(hwnd, 6) or 0)  # GW_ENABLEDPOPUP
                if popup and popup != hwnd and win32gui.IsWindowVisible(popup):
                    state["blockingWindow"] = {
                        "hwnd": popup,
                        "pid": int(win32process.GetWindowThreadProcessId(popup)[1]),
                        "windowClass": str(win32gui.GetClassName(popup)),
                    }
        return state

    def diagnostic_snapshot(self) -> dict[str, Any]:
        """Read Win32 state and cached Python primitives, never UIA or PE data."""
        session = self._session
        result = {
            "hwnd": int(session.hwnd) if session is not None else 0,
            "pid": int(session.pid) if session is not None else 0,
            "version": str(session.version) if session is not None else "",
            "sessionGeneration": self._session_generation,
            "taskKind": self._task_kind,
            "windowEnabled": None,
            "blockingWindow": None,
            "uiaReady": False,
            "sessionReady": False,
        }
        window = {
            "hwnd": result["hwnd"], "pid": result["pid"],
            "role": self._bound_window_role,
            "foregroundHwnd": 0, "ownerHwnd": 0,
            "windowEnabled": None, "blockingWindow": None,
        }
        result["window"] = window
        try:
            import win32gui
            import win32process

            hwnd = result["hwnd"]
            window["foregroundHwnd"] = int(win32gui.GetForegroundWindow() or 0)
            exists = bool(hwnd and win32gui.IsWindow(hwnd))
            window["exists"] = exists
            if exists:
                window.update({
                    "pid": int(win32process.GetWindowThreadProcessId(hwnd)[1]),
                    "windowEnabled": bool(win32gui.IsWindowEnabled(hwnd)),
                    "ownerHwnd": int(win32gui.GetWindow(hwnd, 4) or 0),
                    "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    "bounds": list(win32gui.GetWindowRect(hwnd)),
                    "windowClass": str(win32gui.GetClassName(hwnd)),
                })
                if not window["windowEnabled"]:
                    popup = int(win32gui.GetWindow(hwnd, 6) or 0)
                    if popup and popup != hwnd and win32gui.IsWindowVisible(popup):
                        window["blockingWindow"] = {
                            "hwnd": popup,
                            "pid": int(win32process.GetWindowThreadProcessId(popup)[1]),
                            "ownerHwnd": int(win32gui.GetWindow(popup, 4) or 0),
                            "windowClass": str(win32gui.GetClassName(popup)),
                        }
            responsive = getattr(self._gate_backend, "window_responsive", None)
            result["windowResponsive"] = (
                bool(responsive(hwnd, timeout_ms=250))
                if exists and callable(responsive) else False
            )
            result.update(window)
        except Exception as exc:
            result["degradedReason"] = self._stable_error_code(
                exc, "PROCESS_INSPECTION_FAILED"
            )
            result["detail"] = str(exc)
        return result

    def _check_window_blocked(
        self, *, allow_verify=False, allow_friend_parent=False, defer_uia=False, state=None
    ) -> int:
        if state is None:
            state = self._window_guard_state()
        blocker = state.get("blockingWindow")
        if state.get("windowEnabled") is not False and not blocker:
            return 0
        session = self._session
        if not isinstance(blocker, dict):
            raise WindowBlockedError("Main window is disabled or has an unidentified modal")
        hwnd = int(blocker.get("hwnd", 0) or 0)
        pid = int(blocker.get("pid", 0) or 0)
        main_hwnd = int(session.hwnd) if session is not None else int(state.get("hwnd", 0) or 0)
        expected_pid = int(session.pid) if session is not None else int(state.get("pid", 0) or 0)
        if not hwnd or hwnd == main_hwnd or not pid or pid != expected_pid:
            raise WindowBlockedError("Blocking window does not belong to the bound Weixin process")
        if defer_uia:
            return hwnd
        if session is None:
            raise WindowBlockedError("Blocking window has no verified process lease")
        self.ensure_window_responsive(hwnd)
        root = self._uia.ControlFromHandle(hwnd) if self._uia is not None else None
        role = str(safe_attr(root, "ClassName", ""))
        profile = session.profile
        if allow_verify and role == profile.verify_friend_root_class:
            return hwnd
        if allow_friend_parent and role == profile.add_friend_root_class:
            return hwnd
        raise WindowBlockedError(f"Unrecognized or disallowed blocking window: HWND {hwnd}, role {role!r}")

    def _cancel_known_verify(self) -> None:
        profile = self._session.profile
        try:
            windows = self._process_windows(
                (profile.verify_friend_root_class,), visible=True, strict=True
            )
        except _STOP_ERRORS:
            raise
        except Exception as exc:
            raise WindowBlockedError(f"Cannot safely identify friend verification forms: {exc}") from exc
        if len(windows) > 1:
            raise WindowBlockedError("Multiple friend verification forms are open")
        if windows:
            self._verify_hwnd = windows[0]
            if not self.cancel_friend_request():
                raise WindowBlockedError("Friend verification form could not be cancelled")

    def _close_task_parent(self, hwnd: int) -> bool:
        import win32gui

        def closed():
            return not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd)

        if closed():
            return True
        self.ensure_window_responsive(hwnd)
        matches = self._process_windows(
            (self._session.profile.add_friend_root_class,), strict=True
        )
        if matches != [hwnd]:
            raise WindowBlockedError("Task-owned add-friend window identity is no longer unique")
        root = self._uia.ControlFromHandle(hwnd)
        if str(safe_attr(root, "ClassName", "")) != self._session.profile.add_friend_root_class:
            raise WindowBlockedError("Task-owned add-friend window role changed")
        pattern = root.GetWindowPattern()
        if pattern is None or pattern.Close() is False:
            return False
        return self._wait_for(closed, self._timeout, hwnd=hwnd)

    def finish_task(self) -> dict[str, Any]:
        """Cancel verified forms; close a parent only when this task opened it."""
        success = False
        try:
            self._retire_event_subscription()
            if not self._task_kind or self._session is None:
                success = True
                return {"success": True, "reasonCode": "", "detail": "No bound task cleanup required"}
            self.ensure_window_responsive()
            identity = (self._session.pid, self._session.process_start_time, self._session.version)
            if self._task_process_identity is not None and identity != self._task_process_identity:
                raise WindowBlockedError("Task process lease changed before modal cleanup")
            self._assert_session_identity(
                hwnd=self._session.hwnd, pid=self._session.pid, version=self._session.version
            )
            self._refresh_accessibility_broadcast()
            self._check_window_blocked(allow_verify=True, allow_friend_parent=True)
            self._cancel_known_verify()
            self._check_window_blocked(allow_friend_parent=True)
            if self._task_owned_add_hwnd and not self._close_task_parent(self._task_owned_add_hwnd):
                raise WindowBlockedError("Task-owned add-friend window could not be closed")
            self._check_window_blocked()
            success = True
            return {"success": True, "reasonCode": "", "detail": "Task modal cleanup verified"}
        except Exception as exc:
            return {"success": False, "reasonCode": self._stable_error_code(exc, "CLEANUP_FAILED"), "detail": str(exc)}
        finally:
            if success:
                self._task_kind = ""
                self._task_owned_add_hwnd = 0
                self._task_process_identity = None
                self._release_control_proxies()

    def _report_progress(self, detail: str) -> None:
        callback = self._progress_callback
        if callback is not None:
            callback(str(detail))

    def restart_wechat(self, timeout: int, emit) -> dict[str, Any]:
        inspect_window = getattr(self._gate_backend, "window_inspection", None)
        if callable(inspect_window):
            window_info = dict(inspect_window())
            pid = int(window_info.get("pid", 0) or 0)
            if not pid:
                raise RuntimeError("无法定位要重启的微信进程")
            module = self._gate_backend.find_module(pid, "Weixin.dll")
            version = str(self._gate_backend.file_version(module.path))
            get_weixin_profile(version)
        else:
            inspection = self.inspect()
            if not inspection.get("connected") or not inspection.get("pid"):
                raise RuntimeError("无法定位要重启的微信进程")
            pid = int(inspection["pid"])
        executable = self._gate_backend.process_path(pid)
        self._prepare_for_weixin_restart()
        try:
            terminate_tree = getattr(
                self._gate_backend, "terminate_process_tree", None
            )
            if callable(terminate_tree):
                terminate_tree(pid)
            else:
                self._gate_backend.terminate_process(pid)
            self._sleep(1.0)
            self._gate_backend.start_process(executable)
        except Exception:
            self._restore_suspended_screen_reader()
            raise

        deadline = time.monotonic() + max(30, int(timeout))
        while time.monotonic() < deadline:
            current = self.inspect()
            if (
                current.get("connected")
                and current.get("supported")
                and current.get("uiaReady")
            ):
                return current
            if (
                current.get("connected")
                and not current.get("supported")
                and current.get("version")
            ):
                raise RuntimeError(
                    f"微信已启动，但版本 {current['version']} 未通过安全门禁"
                )
            if (
                current.get("connected")
                and current.get("supported")
                and current.get("windowResponsive", True)
                and current.get("restorable")
            ):
                try:
                    self.bind_window()
                    rebound = self.inspect()
                    if rebound.get("uiaReady"):
                        return rebound
                except (
                    AccessibilitySafetyError,
                    UnsupportedWeixinVersion,
                ):
                    raise
                except Exception:
                    # Login/window creation can still be in flight. Keep the
                    # same COM/gate session and retry after the bounded delay.
                    pass
            remaining = max(0, int(deadline - time.monotonic()))
            emit(
                "agent.status",
                {"status": "waiting_login", "remaining": remaining},
            )
            self._sleep(1.0)
        raise TimeoutError("等待微信重新登录超时")

    def _prepare_for_weixin_restart(self) -> None:
        """Keep the accessibility flag leased while Weixin starts again."""

        if not self._lease_checked:
            restore_gate_lease(self._gate_backend, self._gate_lease_journal)
            self._lease_checked = True
        if self._session is None:
            session = WeixinAccessibilitySession(
                self._gate_backend,
                lease_journal=self._gate_lease_journal,
                session_generation=self._session_generation + 1,
            )
            self._session = session
            try:
                session.__enter__()
            except Exception:
                self._close_session_resources()
                raise
        restore_value = self._session.screen_reader_restore_value
        self._close_session_resources(preserve_screen_reader=True)
        self._screen_reader_restore_value = restore_value

    def _restore_suspended_screen_reader(self) -> None:
        if self._screen_reader_restore_value is None:
            return
        restore_gate_lease(self._gate_backend, self._gate_lease_journal)
        self._screen_reader_restore_value = None

    @staticmethod
    def _stable_error_code(exc: Exception, fallback: str) -> str:
        retry_error = classify_exception(exc)
        if retry_error is not None:
            return retry_error.code
        return {
            "AccessibilitySafetyError": "GATE_SAFETY",
            "UnsupportedWeixinVersion": "UNSUPPORTED_VERSION",
            "RiskControlError": "RISK_CONTROL",
        }.get(type(exc).__name__, fallback)

    def inspect(self) -> dict[str, Any]:
        try:
            inspect_window = getattr(self._gate_backend, "window_inspection", None)
            if callable(inspect_window):
                window_info = self._window_guard_state()
                hwnd = int(window_info.get("hwnd", 0) or 0)
                pid = int(window_info.get("pid", 0) or 0)
            else:
                hwnd = int(self._gate_backend.find_main_window() or 0)
                pid = (
                    int(self._gate_backend.get_window_pid(hwnd)) if hwnd else 0
                )
                window_info = {
                    "windowState": "visible" if hwnd else "missing",
                    "restorable": False,
                }
            if not hwnd:
                return {
                    "connected": False,
                    "processDetected": False,
                    "version": "",
                    "supported": False,
                    "versionSupported": False,
                    "uiaReady": False,
                    "sessionReady": False,
                    "sessionGeneration": self._session_generation,
                    "windowResponsive": False,
                    "degradedReason": "WECHAT_NOT_FOUND",
                    "windowState": str(
                        window_info.get("windowState", "missing")
                    ),
                    "restorable": False,
                    "detail": "未找到已登录的微信窗口",
                }
            module = self._gate_backend.find_module(pid, "Weixin.dll")
            version = str(self._gate_backend.file_version(module.path))
            if self._session is not None:
                try:
                    self._assert_session_identity(
                        hwnd=hwnd,
                        pid=pid,
                        version=version,
                    )
                except StaleElementError:
                    self._session_identity_changed = True
                    self._close_session_resources()
                else:
                    self._rebind_session_hwnd(hwnd)
            try:
                get_weixin_profile(version)
                supported = True
                detail = "微信版本已验证，正在检查 UIA 控件树"
            except UnsupportedWeixinVersion:
                supported = False
                detail = f"微信 {version} 尚未验证，自动化已禁用"
            result = {
                "connected": True,
                "processDetected": True,
                "hwnd": hwnd,
                "pid": pid,
                "version": version,
                "supported": supported,
                "versionSupported": supported,
                "uiaReady": False,
                "sessionReady": False,
                "sessionGeneration": self._session_generation,
                "windowResponsive": True,
                "degradedReason": "" if supported else "UNSUPPORTED_VERSION",
                "windowState": str(
                    window_info.get("windowState", "visible")
                ),
                "restorable": bool(window_info.get("restorable", False)),
                "detail": detail,
                "windowEnabled": window_info.get("windowEnabled"),
                "blockingWindow": window_info.get("blockingWindow"),
            }
            if not supported:
                return result
            responsive = getattr(self._gate_backend, "window_responsive", None)
            if callable(responsive):
                result["windowResponsive"] = bool(
                    responsive(hwnd, timeout_ms=250)
                )
            if not result["windowResponsive"]:
                result["degradedReason"] = "WECHAT_UNRESPONSIVE"
                result["detail"] = "微信窗口无响应，自动化已暂停"
                return result
            if result["windowState"] == "hidden":
                result["detail"] = (
                    "微信版本已验证，窗口位于托盘；任务开始时将先恢复窗口"
                )
                return result
            try:
                self._check_window_blocked(state=window_info)
                if self._uia is not None:
                    self._release_control_proxies()
                self._ensure_session()
            except Exception as exc:
                result["degradedReason"] = self._stable_error_code(
                    exc, "UIA_NOT_READY"
                )
                if result["degradedReason"] == "WECHAT_UNRESPONSIVE":
                    result["windowResponsive"] = False
                result["detail"] = f"微信版本已验证，但 UIA 未就绪：{exc}"
                return result
            result["uiaReady"] = True
            result["sessionReady"] = True
            result["sessionGeneration"] = self._session_generation
            result["windowState"] = "visible"
            result["restorable"] = False
            result["detail"] = "微信版本与 UIA 控件树均已验证"
            return result
        except Exception as exc:
            return {
                "connected": False,
                "processDetected": False,
                "version": "",
                "supported": False,
                "versionSupported": False,
                "uiaReady": False,
                "sessionReady": False,
                "sessionGeneration": self._session_generation,
                "windowResponsive": False,
                "degradedReason": self._stable_error_code(
                    exc, "PROCESS_INSPECTION_FAILED"
                ),
                "windowState": "missing",
                "restorable": False,
                "detail": str(exc),
            }

    def _initialize_uia(self) -> None:
        if self._event_cleanup_error is not None:
            raise self._event_cleanup_error
        if os.name != "nt":
            raise RuntimeError("Weixin automation is only available on Windows")
        if not self._lease_checked:
            restore_gate_lease(self._gate_backend, self._gate_lease_journal)
            self._lease_checked = True
        if not self._uia_initialized:
            from src.core import uiautomation as uia

            uia.InitializeUIAutomationInCurrentThread()
            self._uia_initialized = True
            self._uia = uia
            self._query = ScopedUiaQuery(uia)

    def _ensure_session(self) -> None:
        if self._event_cleanup_error is not None:
            raise self._event_cleanup_error
        if self._session is not None and self._root is not None:
            return
        self._initialize_uia()
        session = self._session
        session_created = False
        if session is None:
            try:
                session = WeixinAccessibilitySession(
                    self._gate_backend,
                    lease_journal=self._gate_lease_journal,
                    session_generation=self._session_generation + 1,
                    screen_reader_restore_value=(
                        self._screen_reader_restore_value
                    ),
                )
                self._session = session
                session.__enter__()
                session_created = True
                self._screen_reader_restore_value = None
            except Exception:
                self._screen_reader_restore_value = None
                self._close_session_resources()
                raise
        try:
            subscription = self._event_subscription
            if subscription is not None:
                self._retire_event_subscription()
            if not session_created:
                self._refresh_accessibility_broadcast()
            self.ensure_window_responsive(session.hwnd)
            self._root = self._uia.ControlFromHandle(session.hwnd)
            if self._root is None:
                raise RuntimeError("无法从微信句柄建立 UIA 根控件")
            if not self._wait_for(
                self._tree_materialized,
                self._timeout,
                hwnd=session.hwnd,
                root=self._root,
            ):
                raise UiaTreeNotReadyError(
                    "微信 UIA 控件树未就绪：门禁已写入并重新广播，"
                    "但微信仍未加载完整可访问性树；请导出诊断包检查重复 Agent"
                )
            self._session_generation += 1
            self._session_identity_changed = False
        except Exception:
            # A transient provider failure invalidates element proxies, not the
            # verified process gate or COM apartment. Retrying re-queries the
            # same live session and therefore never toggles Weixin's gate.
            self._release_control_proxies()
            raise

    def _refresh_accessibility_broadcast(self) -> None:
        refresh = getattr(self._session, "refresh", None)
        if callable(refresh):
            refresh()
            return
        rebroadcast = getattr(self._gate_backend, "broadcast_screen_reader_enabled", None)
        if callable(rebroadcast):
            try:
                refreshed = bool(rebroadcast())
            except Exception as exc:
                raise AccessibilitySafetyError(
                    "failed to refresh the screen-reader broadcast before rebinding the Weixin UIA tree"
                ) from exc
            if not refreshed:
                raise AccessibilitySafetyError(
                    "failed to refresh the screen-reader broadcast before rebinding the Weixin UIA tree"
                )

    def _assert_session_identity(
        self,
        *,
        hwnd: int,
        pid: int,
        version: str,
    ) -> None:
        session = self._session
        if session is None:
            return
        if int(pid) != int(session.pid):
            raise StaleElementError(
                "微信主窗口实例已变化，需要重建自动化连接"
            )
        expected_start_time = str(
            safe_attr(session, "process_start_time", "") or ""
        )
        process_start_time = getattr(
            self._gate_backend, "process_start_time", None
        )
        if expected_start_time and callable(process_start_time):
            current_start_time = str(process_start_time(pid) or "")
            if current_start_time != expected_start_time:
                raise StaleElementError(
                    "微信进程实例已变化，需要重建自动化连接"
                )
        if str(version) != str(session.version):
            raise StaleElementError(
                "微信版本已变化，需要重建自动化连接"
            )

    def _rebind_session_hwnd(self, hwnd: int) -> None:
        """Replace HWND-bound proxies without releasing the process gate lease."""
        if self._session is None or int(self._session.hwnd) == int(hwnd):
            return
        if self._event_subscription is not None:
            self._retire_event_subscription()
        self._release_control_proxies()
        self._bound_window_role = ""
        self._session.hwnd = int(hwnd)

    def _prepare_existing_session(self):
        session = self._session
        prepare = getattr(self._gate_backend, "prepare_main_window", None)
        if session is None or not callable(prepare):
            return None
        result = prepare()
        window = safe_attr(result, "window")
        if window is None:
            raise RuntimeError("Weixin main window disappeared before reuse")
        if not bool(safe_attr(window, "visible", False)):
            raise RuntimeError("Weixin main window could not be restored before reuse")
        current_pid = int(safe_attr(window, "pid", 0) or 0)
        current_hwnd = int(safe_attr(window, "hwnd", 0) or 0)
        find_module = getattr(self._gate_backend, "find_module", None)
        file_version = getattr(self._gate_backend, "file_version", None)
        current_version = str(session.version)
        if callable(find_module) and callable(file_version):
            module = find_module(current_pid, "Weixin.dll")
            current_version = str(file_version(module.path))
        try:
            self._assert_session_identity(
                hwnd=current_hwnd,
                pid=current_pid,
                version=current_version,
            )
        except StaleElementError:
            self._session_identity_changed = True
            raise
        self._rebind_session_hwnd(current_hwnd)
        return result

    def _bound_main_window_ready(self, hwnd: int, *, foreground: bool = True) -> bool:
        import win32gui
        import win32process

        check_action_deadline()
        session = self._session
        if session is None or int(session.hwnd) != hwnd or not win32gui.IsWindow(hwnd):
            raise StaleElementError("Bound main window changed during activation")
        self._assert_session_identity(
            hwnd=hwnd,
            pid=int(win32process.GetWindowThreadProcessId(hwnd)[1]),
            version=session.version,
        )
        self.ensure_window_responsive(hwnd)
        if not win32gui.IsWindowEnabled(hwnd):
            raise WindowBlockedError("Bound main window became disabled during activation")
        return bool(
            win32gui.IsWindowVisible(hwnd)
            and (not foreground or int(win32gui.GetForegroundWindow() or 0) == hwnd)
        )

    def _activate_bound_main_window(self, hwnd: int) -> bool:
        from src.core.win32 import _foreground_with_thread_handshake

        if not self._bound_main_window_ready(hwnd, foreground=False):
            return False
        check_action_deadline()
        _foreground_with_thread_handshake(hwnd)
        # A successful API call does not prove Windows granted foreground.
        return bool(self._wait_for(
            lambda: self._bound_main_window_ready(hwnd), self._timeout, hwnd=hwnd
        ))

    def _restore_hidden_before_bind(self):
        if not isinstance(self._gate_backend, NativeGateBackend):
            return None
        import win32gui
        from .tray_restore import TrayRestoreError, restore_hidden_window

        check_action_deadline()
        window = self._gate_backend.discover_main_window()
        if window is None or win32gui.IsWindowVisible(window.hwnd):
            return None
        self.ensure_window_responsive(window.hwnd)
        module = self._gate_backend.find_module(window.pid, "Weixin.dll")
        version = str(self._gate_backend.file_version(module.path))
        get_weixin_profile(version)
        self._assert_session_identity(hwnd=window.hwnd, pid=window.pid, version=version)
        if self._event_subscription is not None:
            self._retire_event_subscription()
        self._initialize_uia()
        result = restore_hidden_window(
            window, uia=self._uia, query=self._query, backend=self._gate_backend,
            waiter=self._waiter, timeout=self._timeout,
        )
        if result.window is None or not result.window.visible:
            raise TrayRestoreError("Qt tray restoration did not produce a visible main window")
        return result

    def bind_window(self) -> dict[str, Any]:

        self._check_window_blocked(defer_uia=True)
        hidden_restore = self._restore_hidden_before_bind()
        window_restore = self._prepare_existing_session()
        if hidden_restore is not None:
            window_restore = hidden_restore
        if self._uia is not None:
            self._release_control_proxies()
        self._ensure_session()
        hwnd = self._session.hwnd
        self.ensure_window_responsive(hwnd)
        if self._task_kind:
            self._task_process_identity = (
                self._session.pid, self._session.process_start_time, self._session.version
            )
            self._check_window_blocked(allow_verify=True, allow_friend_parent=True)
            self._cancel_known_verify()
        parent_hwnd = self._check_window_blocked(
            allow_friend_parent="friend" in self._task_kind
        )
        try:
            activated = (
                self._restore_owned_process_window(
                    parent_hwnd, (self._session.profile.add_friend_root_class,)
                ) if parent_hwnd else self._activate_bound_main_window(hwnd)
            )
            visible_root = activated and self._wait_for(
                self._visible_root_bounds,
                self._timeout,
                hwnd=hwnd,
            )
            if visible_root and not parent_hwnd:
                visible_root = self._bound_main_window_ready(hwnd)
        except (
            AccessibilitySafetyError,
            UnsupportedWeixinVersion,
            AutomationRetryError,
        ):
            raise
        except Exception as exc:
            detail = self._bind_failure_detail("activate", exc)
            raise TransientUiError(detail) from exc
        if not visible_root:
            detail = self._bind_failure_detail(
                "activate",
                RuntimeError(
                    f"activation={activated}, rootVisible={bool(visible_root)}"
                ),
            )
            raise TransientUiError(
                "微信窗口恢复/置前或可见根边界校验失败；" + detail
            )

        result = {
            "connected": True,
            "hwnd": hwnd,
            "pid": self._session.pid,
            "version": self._session.version,
            "supported": True,
            "sessionGeneration": self._session_generation,
            "windowResponsive": True,
        }
        restore_result = window_restore or safe_attr(
            self._session, "window_restore"
        )
        as_dict = getattr(restore_result, "as_dict", None)
        if callable(as_dict):
            result["windowRestore"] = as_dict()
        return result

    @staticmethod
    def _bind_retry_is_safe(exc: Exception) -> bool:
        return not isinstance(
            exc,
            (
                AccessibilitySafetyError,
                UnsupportedWeixinVersion,
            ),
        )

    def _bind_failure_detail(self, action: str, exc: Exception) -> str:
        session = self._session
        window_state = "window=unavailable"
        if session is not None:
            window_state = (
                f"hwnd={safe_attr(session, 'hwnd', 'unavailable')}, "
                f"pid={safe_attr(session, 'pid', 'unavailable')}"
            )
        control_state = (
            "control=unavailable"
            if self._root is None
            else describe_control(self._root)
        )
        return (
            f"action=bind_window.{action}, error={exc}; "
            f"{window_state}; {control_state}"
        )

    def _visible_root_bounds(self) -> bool:
        try:
            self.ensure_window_responsive(self._session.hwnd)
            root = self._fresh_main_root()
            rectangle = safe_attr(root, "BoundingRectangle")
            if bool(safe_attr(root, "IsOffscreen", False)):
                return False
            if not self._rect_valid(rectangle):
                return False
            self._root = root
            return True
        except _STOP_ERRORS:
            raise
        except Exception:
            return False

    def _tree_materialized(self) -> bool:
        try:
            self.ensure_window_responsive(self._session.hwnd)
            root = self._fresh_main_root()
            self._root = root
            profile = self._session.profile
            return (
                str(safe_attr(root, "ClassName", "")) == profile.main_root_class
                and bool(
                    self._find_scoped_controls(
                        hwnd=self._session.hwnd,
                        name=profile.search_edit_name,
                        control_type="EditControl",
                        class_name=profile.search_edit_class,
                        enabled=False,
                    )
                )
            )
        except _STOP_ERRORS:
            raise
        except Exception:
            return False

    def _fresh_main_root(self):
        if self._uia is None:
            return self._root
        self.ensure_window_responsive(self._session.hwnd)
        root = self._uia.ControlFromHandle(self._session.hwnd)
        profile = self._session.profile
        if (
            root is None
            or str(safe_attr(root, "ClassName", "")) != profile.main_root_class
            or str(safe_attr(root, "ControlTypeName", "")) != "WindowControl"
            or int(safe_attr(root, "NativeWindowHandle", self._session.hwnd)) != int(self._session.hwnd)
            or int(safe_attr(root, "ProcessId", self._session.pid)) != int(self._session.pid)
        ):
            raise StaleElementError("Fresh UIA root is not the bound Weixin main window")
        self._root = root
        self._bound_window_role = profile.main_root_class
        return root

    def _control_root(self, hwnd: int | None = None):
        target_hwnd = int(hwnd or safe_attr(self._session, "hwnd", 0) or 0)
        if (
            self._root is not None
            and self._session is not None
            and target_hwnd == int(self._session.hwnd)
        ):
            return self._root
        if self._uia is None:
            return self._root
        return self._uia.ControlFromHandle(target_hwnd)

    def _legacy_find_scoped_controls(self, hwnd: int, **selector) -> list[Any]:
        _root, nodes = self._walk(hwnd)
        return [
            control
            for control, depth in nodes
            if find_exact_control(((control, depth),), **selector) is control
        ]

    def _find_scoped_controls(
        self,
        *,
        hwnd: int | None = None,
        root=None,
        **selector,
    ) -> list[Any]:
        target_hwnd = int(hwnd or safe_attr(self._session, "hwnd", 0) or 0)
        self.ensure_window_responsive(target_hwnd)
        if self._query is None:
            return self._legacy_find_scoped_controls(target_hwnd, **selector)
        container = root or self._control_root(target_hwnd)
        if container is None:
            return []
        direct = find_exact_control(((container, 0),), **selector)
        direct_matches = [container] if direct is container else []
        try:
            return direct_matches + self._query.find_all(container, **selector)
        except ScopedQueryUnavailable as exc:
            raise StaleElementError(
                f"局部 UIA 查询失效：{exc}"
            ) from exc

    def _scoped_nodes(self, *, hwnd: int | None = None, root=None):
        target_hwnd = int(hwnd or safe_attr(self._session, "hwnd", 0) or 0)
        self.ensure_window_responsive(target_hwnd)
        if self._query is None:
            _root, nodes = self._walk(target_hwnd)
            return nodes
        container = root or self._control_root(target_hwnd)
        if container is None:
            return []
        try:
            controls = self._query.find_all(container, enabled=False)
        except ScopedQueryUnavailable as exc:
            raise StaleElementError(
                f"局部 UIA 容器查询失效：{exc}"
            ) from exc
        return [(container, 0), *((control, 1) for control in controls)]

    def _raise_scoped_risk(self, *, hwnd: int | None = None, root=None) -> None:
        self.ensure_window_responsive(hwnd)
        if self._query is None:
            nodes = self._walk(int(hwnd))[1] if hwnd else self._all_nodes()
            raise_for_risk_controls(nodes)
            return
        target_hwnd = int(hwnd or safe_attr(self._session, "hwnd", 0) or 0)
        container = root or self._control_root(target_hwnd)
        if container is None:
            return
        controls = self._query.find_all(
            container, name=RISK_KEYWORDS, enabled=False
        )
        raise_for_risk_controls((control, 1) for control in controls)

    def _raise_process_risk(self) -> None:
        if self._query is None:
            raise_for_risk_controls(self._all_nodes())
            return
        for hwnd, root in self._visible_process_roots():
            self._raise_scoped_risk(hwnd=hwnd, root=root)

    def _walk(self, hwnd: int | None = None):
        if self._uia is None:
            raise RuntimeError("UIA is not initialized")
        target_hwnd = int(hwnd or self._session.hwnd)
        self.ensure_window_responsive(target_hwnd)
        root = self._root if hwnd is None else self._uia.ControlFromHandle(target_hwnd)
        nodes = (
            list(self._uia.WalkControl(root, includeTop=True, maxDepth=40))
            if root is not None
            else []
        )
        return root, nodes

    def ensure_window_responsive(self, hwnd: int | None = None) -> bool:
        check_action_deadline()
        if self._event_cleanup_error is not None:
            raise self._event_cleanup_error
        target_hwnd = int(hwnd or safe_attr(self._session, "hwnd", 0) or 0)
        check = getattr(self._gate_backend, "window_responsive", None)
        if callable(check) and not bool(check(target_hwnd, timeout_ms=250)):
            raise WeixinUnresponsiveError(
                "微信窗口无响应，已停止 UIA 调用以避免继续占用界面"
            )
        check_action_deadline()
        return True

    def _release_control_proxies(self) -> None:
        self._root = None
        self._search_edit = None
        self._search_results = []
        self._search_query = ""
        self._selected_target = ""
        self._selected_identities = frozenset()
        self._composer = None
        self._friend_search = None
        self._friend_account = ""
        self._friend_profile_reset_for = ""
        self._friend_profile_token = None
        self._add_hwnd = 0
        self._verify_hwnd = 0

    def soft_refresh_session(self) -> int:
        if self._session is None:
            self._ensure_session()
            return self._session_generation
        if self._session_identity_changed:
            self._close_session_resources()
            self._ensure_session()
            return self._session_generation
        subscription = self._event_subscription
        if subscription is not None:
            self._retire_event_subscription()
        self._release_control_proxies()
        self._wake_event.clear()
        self._refresh_accessibility_broadcast()
        self.ensure_window_responsive(self._session.hwnd)
        self._root = self._uia.ControlFromHandle(self._session.hwnd)
        if self._root is None:
            raise RuntimeError("无法刷新微信 UIA 根控件")
        if not self._wait_for(
            self._tree_materialized,
            self._timeout,
            hwnd=self._session.hwnd,
            root=self._root,
        ):
            raise UiaTreeNotReadyError(
                "刷新后微信 UIA 控件树仍未就绪；可访问性会话不会通过重启循环重试"
            )
        self._session_generation += 1
        return self._session_generation

    def _close_session_resources(
        self, *, preserve_screen_reader: bool = False
    ) -> None:
        cleanup_error: Exception | None = None
        subscription = self._event_subscription
        if subscription is not None:
            try:
                self._retire_event_subscription()
            except Exception as exc:
                cleanup_error = exc
            else:
                self._event_subscription = None
        self._release_control_proxies()
        session = self._session
        if session is not None:
            try:
                if preserve_screen_reader:
                    session.close(preserve_screen_reader=True)
                else:
                    session.close()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            else:
                self._session = None
                self._session_identity_changed = False
        elif (
            not preserve_screen_reader
            and self._screen_reader_restore_value is not None
        ):
            try:
                self._restore_suspended_screen_reader()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error

    def _process_window(self, accepted_classes: Sequence[str]) -> int:
        windows = self._process_windows(accepted_classes)
        return windows[0] if windows else 0

    def _process_windows(
        self,
        accepted_classes: Sequence[str],
        *,
        visible: bool | None = True,
        strict: bool = False,
    ) -> list[int]:
        import win32gui
        import win32process

        found = []
        parse_failures: list[str] = []
        target_pid = int(self._session.pid)

        def collect(hwnd, _extra):
            try:
                pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
                if pid != target_pid:
                    return True
                is_visible = bool(win32gui.IsWindowVisible(hwnd))
                if visible is not None and is_visible is not visible:
                    return True
                native_class = str(win32gui.GetClassName(hwnd) or "")
                native_class_key = native_class.casefold()
                if not (
                    native_class_key.startswith("chrome_widgetwin")
                    or (
                        native_class_key.startswith("qt")
                        and native_class_key.endswith("qwindowicon")
                    )
                ):
                    return True
                self.ensure_window_responsive(hwnd)
                root = self._uia.ControlFromHandle(hwnd)
                if root is None:
                    raise RuntimeError("ControlFromHandle returned no root")
                if strict:
                    root_class_value = getattr(root, "ClassName")
                    if root_class_value is None or not str(root_class_value).strip():
                        raise RuntimeError("UIA root class is empty")
                    root_class = str(root_class_value)
                else:
                    root_class = str(safe_attr(root, "ClassName", ""))
                if root_class in accepted_classes:
                    found.append(hwnd)
            except _STOP_ERRORS:
                raise
            except Exception as exc:
                if strict:
                    parse_failures.append(f"HWND {int(hwnd)}: {exc}")
            return True

        win32gui.EnumWindows(collect, None)
        if parse_failures:
            raise RuntimeError(
                "无法安全解析同 PID 的微信顶层窗口：" + "; ".join(parse_failures)
            )
        return [int(hwnd) for hwnd in found]

    def _restore_owned_process_window(
        self, hwnd: int, accepted_classes: Sequence[str]
    ) -> bool:
        import win32con
        import win32gui
        import win32process
        from src.core.win32 import _foreground_with_thread_handshake

        def is_exact_window(*, visible: bool | None = None) -> bool:
            try:
                if not win32gui.IsWindow(hwnd):
                    return False
                pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
                if pid != int(self._session.pid):
                    return False
                if visible is not None and bool(
                    win32gui.IsWindowVisible(hwnd)
                ) is not visible:
                    return False
                self.ensure_window_responsive(hwnd)
                root = self._uia.ControlFromHandle(hwnd)
                return str(safe_attr(root, "ClassName", "")) in accepted_classes
            except _STOP_ERRORS:
                raise
            except Exception:
                return False

        if not is_exact_window():
            return False
        # Recheck ownership immediately before the Win32 action so a recycled
        # HWND can never be shown or focused.
        if not is_exact_window():
            return False
        try:
            if not is_exact_window(visible=True):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            _foreground_with_thread_handshake(hwnd)
        except _STOP_ERRORS:
            raise
        except Exception:
            return False

        def prepared() -> bool:
            try:
                return is_exact_window(visible=True) and int(
                    win32gui.GetForegroundWindow()
                ) == int(hwnd)
            except _STOP_ERRORS:
                raise
            except Exception:
                return False

        return bool(
            self._wait_for(
                prepared,
                self._timeout,
                hwnd=hwnd,
            )
        )

    def _all_nodes(self) -> list[tuple[Any, int]]:
        _root, nodes = self._walk(self._session.hwnd)
        import win32gui
        import win32process

        handles = []

        def collect(hwnd, _extra):
            try:
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid == self._session.pid and win32gui.IsWindowVisible(hwnd):
                    handles.append(hwnd)
            except _STOP_ERRORS:
                raise
            except Exception:
                pass
            return True

        win32gui.EnumWindows(collect, None)
        for hwnd in handles:
            if hwnd == self._session.hwnd:
                continue
            try:
                _window_root, window_nodes = self._walk(hwnd)
                nodes.extend(window_nodes)
            except _STOP_ERRORS:
                raise
            except Exception:
                pass
        return nodes

    def _wait_control(self, *, hwnd: int | None = None, **selector):
        holder = {"control": None}
        target_hwnd = int(hwnd or self._session.hwnd)

        def locate():
            self.ensure_window_responsive(target_hwnd)
            root = self._control_root(target_hwnd)
            self._raise_scoped_risk(hwnd=target_hwnd, root=root)
            matches = self._find_scoped_controls(
                hwnd=target_hwnd,
                root=root,
                **selector,
            )
            holder["control"] = matches[0] if matches else None
            return holder["control"] is not None

        if not self._wait_for(locate, self._timeout, hwnd=target_hwnd):
            description = ", ".join(
                f"{key}={value!r}" for key, value in selector.items()
            )
            raise RuntimeError(f"UIA 控件未出现：{description}")
        return holder["control"]

    def _wait_for(
        self,
        predicate,
        timeout: float,
        _legacy_wake_event=None,
        *,
        hwnd: int | None = None,
        root=None,
    ) -> bool:
        """Use a temporary container-scoped event subscription plus polling."""

        check_action_deadline()
        self._retire_event_subscription()
        subscription = None
        target_root = root
        if target_root is None and self._uia is not None:
            target_hwnd = int(
                hwnd or safe_attr(self._session, "hwnd", 0) or 0
            )
            if target_hwnd:
                try:
                    target_root = self._control_root(target_hwnd)
                except _STOP_ERRORS:
                    raise
                except Exception:
                    target_root = None
        self._wake_event.clear()
        if self._uia is not None and target_root is not None:
            try:
                check_action_deadline()
                subscription = subscribe_uia_events(
                    self._uia, target_root, self._wake_event
                )
                self._event_subscription = subscription
            except EventCleanupError as exc:
                self._event_subscription = exc.subscription
                self._event_cleanup_error = exc
                raise
            except AutomationRetryError:
                raise
            except Exception:
                check_action_deadline()
                subscription = None
        try:
            check_action_deadline()
            target_hwnd = int(
                hwnd or safe_attr(self._session, "hwnd", 0) or 0
            )

            def responsive_predicate():
                check_action_deadline()
                result = predicate()
                check_action_deadline()
                self._report_progress("bounded_wait_poll")
                # A successful action can legitimately destroy or replace its
                # HWND. Accept that postcondition before probing the old handle,
                # otherwise a closed dialog is misreported as an unresponsive
                # Weixin window.
                if result:
                    return result
                if target_hwnd:
                    self.ensure_window_responsive(target_hwnd)
                return result

            return bool(
                self._waiter.wait(
                    responsive_predicate,
                    timeout,
                    self._wake_event,
                )
            )
        finally:
            if subscription is not None and self._event_subscription is subscription:
                self._retire_event_subscription()

    def _retire_event_subscription(self) -> None:
        subscription = self._event_subscription
        if subscription is None:
            return
        try:
            check_action_deadline()
            subscription.close()
        except Exception as exc:
            error = exc if isinstance(exc, EventCleanupError) else EventCleanupError(subscription, exc)
            self._event_subscription = error.subscription
            self._event_cleanup_error = error
            if error is exc:
                raise
            raise error from exc
        self._event_subscription = None
        self._event_cleanup_error = None

    @staticmethod
    def _rect_valid(rectangle: Any) -> bool:
        try:
            return (
                rectangle is not None
                and rectangle.right > rectangle.left
                and rectangle.bottom > rectangle.top
            )
        except _STOP_ERRORS:
            raise
        except Exception:
            return False

    @staticmethod
    def _point_in_rect(point: tuple[int, int], rectangle: Any) -> bool:
        return (
            NativeWeixinDriver._rect_valid(rectangle)
            and rectangle.left <= point[0] <= rectangle.right
            and rectangle.top <= point[1] <= rectangle.bottom
        )

    @staticmethod
    def _clickable_point(control: Any) -> tuple[int, int] | None:
        try:
            value = control.GetClickablePoint()
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        if isinstance(value, (tuple, list)) and len(value) == 3:
            try:
                return (
                    (int(value[0]), int(value[1]))
                    if bool(value[2])
                    else None
                )
            except (TypeError, ValueError):
                return None
        if isinstance(value, (tuple, list)) and len(value) == 2:
            if isinstance(value[0], bool):
                value = value[1]
                try:
                    return int(value.x), int(value.y)
                except _STOP_ERRORS:
                    raise
                except Exception:
                    return None
            try:
                return int(value[0]), int(value[1])
            except (TypeError, ValueError):
                return None
        try:
            return int(value.x), int(value.y)
        except _STOP_ERRORS:
            raise
        except Exception:
            return None

    def _click_bounds(self, control) -> None:
        if not bool(safe_attr(control, "IsEnabled", False)):
            raise RuntimeError("UIA 控件未启用")
        if bool(safe_attr(control, "IsOffscreen", True)):
            raise RuntimeError("UIA 控件不可见")
        window_root, window_rectangle = self._owning_window(control)
        row_rectangle = safe_attr(control, "BoundingRectangle")

        def click(point: tuple[int, int]) -> None:
            # The owner can lose foreground between navigation and this actual
            # mouse injection.  Revalidate and foreground the exact same-PID
            # HWND at the last possible moment; otherwise a valid coordinate
            # could land on the main window covering a secondary Weixin window.
            self._prepare_click_window(window_root, control, point)
            self._uia.Click(*point)

        point = self._clickable_point(control)
        if point is not None and self._point_in_rect(point, window_rectangle):
            if not self._rect_valid(row_rectangle) or self._point_in_rect(
                point, row_rectangle
            ):
                click(point)
                return

        if self._rect_valid(row_rectangle):
            point = (
                (row_rectangle.left + row_rectangle.right) // 2,
                (row_rectangle.top + row_rectangle.bottom) // 2,
            )
            if self._point_in_rect(point, window_rectangle):
                click(point)
                return

        try:
            descendants = self._uia.WalkControl(
                control, includeTop=False, maxDepth=12
            )
        except _STOP_ERRORS:
            raise
        except Exception:
            descendants = []
        for child, _depth in descendants:
            if not bool(safe_attr(child, "IsEnabled", False)):
                continue
            if bool(safe_attr(child, "IsOffscreen", True)):
                continue
            rectangle = safe_attr(child, "BoundingRectangle")
            if not self._rect_valid(rectangle):
                continue
            point = (
                (rectangle.left + rectangle.right) // 2,
                (rectangle.top + rectangle.bottom) // 2,
            )
            if not self._point_in_rect(point, window_rectangle):
                continue
            if self._rect_valid(row_rectangle) and not self._point_in_rect(
                point, row_rectangle
            ):
                continue
            click(point)
            return
        raise RuntimeError("UIA 控件及其候选子树没有安全的可点击点")

    def _prepare_click_window(
        self, window_root, control, point: tuple[int, int]
    ) -> None:
        """Make the exact live owner foreground immediately before a click."""
        if self._session is None:
            return

        import win32con
        import win32gui
        import win32process
        from src.core.win32 import _foreground_with_thread_handshake

        hwnd = int(safe_attr(window_root, "NativeWindowHandle", 0) or 0)
        self._guard_click_modal(hwnd)
        self.ensure_window_responsive(hwnd)
        expected_pid = int(safe_attr(self._session, "pid", 0) or 0)
        uia_class = str(safe_attr(window_root, "ClassName", ""))
        try:
            native_class = str(win32gui.GetClassName(hwnd))
        except Exception:
            native_class = ""
        is_passive_popover = (
            "Popover" in uia_class
            and native_class.casefold().endswith("qwindowtoolsavebits")
        )
        activation_hwnd = hwnd
        if is_passive_popover:
            try:
                activation_hwnd = int(
                    win32gui.GetWindow(hwnd, win32con.GW_OWNER) or 0
                )
            except Exception:
                activation_hwnd = 0

        def valid_process_window(candidate_hwnd: int) -> bool:
            try:
                return (
                    bool(candidate_hwnd)
                    and bool(expected_pid)
                    and bool(win32gui.IsWindow(candidate_hwnd))
                    and bool(win32gui.IsWindowVisible(candidate_hwnd))
                    and int(
                        win32process.GetWindowThreadProcessId(candidate_hwnd)[1]
                    )
                    == expected_pid
                )
            except Exception:
                return False

        def point_hits_exact_owner() -> bool:
            try:
                hit = int(win32gui.WindowFromPoint(point) or 0)
                hit_root = int(
                    win32gui.GetAncestor(hit, win32con.GA_ROOT) or hit
                )
                return bool(hit_root) and hit_root == hwnd
            except Exception:
                return False

        def valid_owner(*, require_foreground: bool) -> bool:
            try:
                return (
                    valid_process_window(hwnd)
                    and valid_process_window(activation_hwnd)
                    and (
                        not is_passive_popover
                        or int(
                            win32gui.GetWindow(hwnd, win32con.GW_OWNER) or 0
                        )
                        == activation_hwnd
                    )
                    and point_hits_exact_owner()
                    and (
                        not require_foreground
                        or int(win32gui.GetForegroundWindow() or 0)
                        == activation_hwnd
                    )
                )
            except Exception:
                return False

        if not valid_owner(require_foreground=False):
            raise RuntimeError(
                "坐标点击前控件所属微信窗口已失效；"
                + describe_control(control)
            )
        try:
            foreground_hwnd = int(win32gui.GetForegroundWindow() or 0)
        except Exception:
            foreground_hwnd = 0
        if foreground_hwnd != activation_hwnd and not _foreground_with_thread_handshake(
            activation_hwnd
        ):
            raise RuntimeError(
                "无法置前控件所属微信窗口："
                f"ownerHwnd={hwnd}, activationHwnd={activation_hwnd}; "
                + describe_control(control)
            )
        if not self._wait_for(
            lambda: valid_owner(require_foreground=True),
            self._timeout,
            root=window_root,
        ) or not valid_owner(require_foreground=True):
            raise RuntimeError(
                "控件所属微信窗口未保持前台或点击点被覆盖："
                f"ownerHwnd={hwnd}, activationHwnd={activation_hwnd}; "
                + describe_control(control)
            )

        self._guard_click_modal(hwnd)
        self.ensure_window_responsive(hwnd)
        rectangle = safe_attr(control, "BoundingRectangle")
        if (
            not bool(safe_attr(control, "IsEnabled", False))
            or bool(safe_attr(control, "IsOffscreen", True))
            or not self._point_in_rect(point, safe_attr(window_root, "BoundingRectangle"))
            or (self._rect_valid(rectangle) and not self._point_in_rect(point, rectangle))
            or not valid_owner(require_foreground=True)
        ):
            raise TransientUiError("Target bounds or foreground changed before mouse injection")

    def _guard_click_modal(self, hwnd: int) -> None:
        state = self._window_guard_state()
        blocker = state.get("blockingWindow")
        if state.get("windowEnabled") is False or blocker:
            if not isinstance(blocker, dict) or int(blocker.get("hwnd", 0) or 0) != hwnd:
                raise WindowBlockedError("A blocking window prevents clicking this target")
            self._check_window_blocked(allow_verify=True, allow_friend_parent=True)

    def _owning_window(self, control) -> tuple[Any, Any]:
        try:
            window_root = control.GetTopLevelControl()
        except _STOP_ERRORS:
            raise
        except Exception:
            window_root = None

        control_rectangle = safe_attr(control, "BoundingRectangle")
        main_rectangle = safe_attr(self._root, "BoundingRectangle")
        # Geometry-only ownership is useful for isolated controls in unit tests, but
        # is not strong enough once a live process session exists.  In production a
        # control must resolve to an actual UIA top-level window so a secondary
        # dialog can be checked against the session PID.
        if (
            window_root is None
            and self._session is None
            and self._rect_valid(control_rectangle)
        ):
            midpoint = (
                (control_rectangle.left + control_rectangle.right) // 2,
                (control_rectangle.top + control_rectangle.bottom) // 2,
            )
            if self._point_in_rect(midpoint, main_rectangle):
                window_root = self._root
        if window_root is None and control is self._root:
            window_root = self._root
        if window_root is None:
            raise RuntimeError(
                "无法解析控件所属的微信顶层窗口；" + describe_control(control)
            )

        window_rectangle = safe_attr(window_root, "BoundingRectangle")
        if bool(safe_attr(window_root, "IsOffscreen", False)) or not self._rect_valid(
            window_rectangle
        ):
            raise RuntimeError(
                "控件所属顶层窗口不可见或边界无效；"
                + describe_control(window_root)
                + "; target="
                + describe_control(control)
            )
        hwnd = int(safe_attr(window_root, "NativeWindowHandle", 0) or 0)
        if hwnd:
            try:
                import win32gui
                import win32process

                visible = bool(win32gui.IsWindowVisible(hwnd))
                owner_pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
            except _STOP_ERRORS:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"无法校验控件所属窗口：hwnd={hwnd}, error={exc}; "
                    + describe_control(control)
                ) from exc
            expected_pid = int(safe_attr(self._session, "pid", 0) or 0)
            if not visible or not expected_pid or owner_pid != expected_pid:
                raise RuntimeError(
                    f"拒绝非当前微信会话窗口：hwnd={hwnd}, visible={visible}, "
                    f"ownerPid={owner_pid}, expectedPid={expected_pid}; "
                    + describe_control(control)
                )
        elif window_root is not self._root:
            raise RuntimeError(
                "控件所属顶层窗口没有可验证句柄；" + describe_control(control)
            )
        return window_root, window_rectangle

    def _click_search_candidate(self, control) -> None:
        self._click_bounds(control)

    def _replace_text(self, control, value: str) -> None:
        from src.utils.clipboard_utils import set_text_to_clipboard

        self.ensure_window_responsive()
        self._click_bounds(control)
        self.ensure_window_responsive()
        control = self._send_keys(control, "{Ctrl}a{Delete}")
        self.ensure_window_responsive()
        if not set_text_to_clipboard(value):
            raise RuntimeError("写入剪贴板失败")
        self.ensure_window_responsive()
        self._send_keys(control, "{Ctrl}v")

    def _send_keys(self, control, keys: str, *, wait_time: float = 0.05):
        """Resolve, focus, and revalidate the live owner before one key injection."""
        self.ensure_window_responsive()
        if self._session is None:
            control.SendKeys(keys, waitTime=wait_time)
            return control

        import win32gui
        import win32process
        from src.core.win32 import _foreground_with_thread_handshake

        owner, _bounds = self._owning_window(control)
        hwnd = int(safe_attr(owner, "NativeWindowHandle", 0) or 0)
        pid = int(self._session.pid)
        self.ensure_window_responsive(hwnd)
        self._guard_click_modal(hwnd)

        def validate_owner(*, foreground=False):
            self.ensure_window_responsive(hwnd)
            if (
                not hwnd or not win32gui.IsWindow(hwnd)
                or not win32gui.IsWindowVisible(hwnd)
                or not win32gui.IsWindowEnabled(hwnd)
                or int(win32process.GetWindowThreadProcessId(hwnd)[1]) != pid
                or (foreground and int(win32gui.GetForegroundWindow() or 0) != hwnd)
            ):
                raise WindowBlockedError("Keyboard owner is disabled, replaced, or not foreground")

        validate_owner()
        fresh_owner = self._uia.ControlFromHandle(hwnd)
        if (
            fresh_owner is None
            or str(safe_attr(fresh_owner, "ClassName", "")) != str(safe_attr(owner, "ClassName", ""))
            or int(safe_attr(fresh_owner, "NativeWindowHandle", 0) or 0) != hwnd
        ):
            raise StaleElementError("Keyboard owner UIA identity changed")
        is_window = str(safe_attr(control, "ControlTypeName", "")) == "WindowControl"
        if is_window:
            fresh = fresh_owner
        else:
            selector = {
                "control_type": str(safe_attr(control, "ControlTypeName", "")),
                "class_name": str(safe_attr(control, "ClassName", "")),
                "automation_id": str(safe_attr(control, "AutomationId", "")),
                "name": str(safe_attr(control, "Name", "")),
                "visible": True,
            }
            matches = self._find_scoped_controls(hwnd=hwnd, root=fresh_owner, **selector)
            runtime_id = _runtime_id(control)
            if runtime_id:
                matches = [item for item in matches if _runtime_id(item) == runtime_id]
            if len(matches) != 1:
                raise StaleElementError("Keyboard target no longer resolves uniquely")
            fresh = matches[0]
        if not bool(safe_attr(fresh, "IsEnabled", False)) or bool(safe_attr(fresh, "IsOffscreen", True)):
            raise WindowBlockedError("Keyboard target is disabled or hidden")
        validate_owner()
        if int(win32gui.GetForegroundWindow() or 0) != hwnd:
            if not _foreground_with_thread_handshake(hwnd):
                raise WindowBlockedError("Cannot foreground the keyboard owner")
        validate_owner(foreground=True)
        fresh.SetFocus()
        self._guard_click_modal(hwnd)
        validate_owner(foreground=True)
        if (
            not bool(safe_attr(fresh, "IsEnabled", False))
            or bool(safe_attr(fresh, "IsOffscreen", True))
            or (not is_window and not bool(safe_attr(fresh, "HasKeyboardFocus", False)))
        ):
            raise WindowBlockedError("Keyboard target did not retain enabled focus")
        validate_owner(foreground=True)
        check_action_deadline()
        self._uia.SendKeys(keys, waitTime=wait_time)
        check_action_deadline()
        return fresh

    def ensure_search_ready(self) -> bool:
        self._ensure_session()
        profile = self._session.profile

        def find_search():
            matches = self._find_scoped_controls(
                hwnd=self._session.hwnd,
                name=profile.search_edit_name,
                control_type="EditControl",
                class_name=profile.search_edit_class,
            )
            self._search_edit = matches[0] if len(matches) == 1 else None
            return self._search_edit is not None

        if find_search():
            return True
        try:
            self.ensure_window_responsive(self._session.hwnd)
            fresh_root = self._uia.ControlFromHandle(self._session.hwnd)
        except _STOP_ERRORS:
            raise
        except Exception:
            fresh_root = None
        if fresh_root is not None:
            self._release_control_proxies()
            self._root = fresh_root
            if find_search():
                return True
        try:
            self._send_keys(self._root, "{Ctrl}f")
        except _STOP_ERRORS:
            raise
        except Exception:
            return False
        return self._wait_for(
            find_search, self._timeout, hwnd=self._session.hwnd
        )

    @staticmethod
    def _candidate_signature(candidates: Sequence[SearchCandidate]) -> tuple:
        return tuple(
            candidate.semantic_row_key
            or _semantic_row_key(
                candidate.result_type,
                candidate.automation_id,
                candidate.identities,
            )
            for candidate in candidates
        )

    @staticmethod
    def _coerce_search_rows(snapshot) -> list[SearchResultRow] | None:
        """Accept pre-refactor test doubles while production uses paired rows."""
        if snapshot is None:
            return None
        if isinstance(snapshot, tuple) and len(snapshot) == 2:
            candidates, controls = snapshot
            return [
                SearchResultRow(candidate=candidate, control=controls[index])
                for index, candidate in enumerate(candidates)
                if index < len(controls)
            ]
        return list(snapshot)

    @staticmethod
    def _same_candidate(left: SearchCandidate, right: SearchCandidate) -> bool:
        return (
            left.result_type == right.result_type
            and left.automation_id == right.automation_id
            and {
                normalize_identity(value) for value in left.identities
            }
            == {normalize_identity(value) for value in right.identities}
        )

    def _search_rows(self) -> list[SearchResultRow] | None:
        if self._query is None:
            return self._legacy_search_rows()
        return self._scoped_search_rows()

    def _legacy_search_rows(self) -> list[SearchResultRow] | None:
        profile = self._session.profile
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        search_list = find_exact_control(
            nodes,
            automation_id=profile.search_list_automation_id,
            enabled=False,
        )
        if search_list is None:
            return None
        try:
            list_nodes = list(
                self._uia.WalkControl(search_list, includeTop=True, maxDepth=12)
            )
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        return extract_search_result_rows(list_nodes)

    def _scoped_search_rows(self) -> list[SearchResultRow] | None:
        profile = self._session.profile
        roots = [self._control_root(self._session.hwnd)]
        for hwnd in self._process_windows((profile.search_popup_class,)):
            root = self._control_root(hwnd)
            if root is not None:
                roots.append(root)

        search_lists = []
        for root in roots:
            if root is None:
                continue
            risk_controls = self._query.find_all(
                root, name=RISK_KEYWORDS, enabled=False
            )
            raise_for_risk_controls([(control, 1) for control in risk_controls])
            search_lists.extend(
                self._query.find_all(
                    root,
                    automation_id=profile.search_list_automation_id,
                    enabled=False,
                )
            )
        if len(search_lists) != 1:
            return None

        rows = self._query.find_all(
            search_lists[0],
            control_type="ListItemControl",
            enabled=False,
        )
        results = []
        for row_index, row in enumerate(rows):
            result_type = _search_row_kind(row)
            if result_type is None:
                continue
            row_name = str(safe_attr(row, "Name", "")).strip()
            automation_id = str(safe_attr(row, "AutomationId", ""))
            descendants = self._query.find_all(row, enabled=False)
            identities: dict[str, str] = {}
            for value in [row_name, *(
                str(safe_attr(control, "Name", "")).strip()
                for control in descendants
            )]:
                normalized = normalize_identity(value)
                if normalized:
                    identities.setdefault(normalized, value)
            if result_type == "function":
                helper_key = normalize_identity("文件传输助手")
                if helper_key not in identities:
                    continue
                display_name = identities[helper_key]
                values = frozenset({display_name})
            else:
                values = frozenset(identities.values())
                if not values:
                    continue
                display_name = row_name or next(iter(values))
            candidate = SearchCandidate(
                display_name=display_name,
                identities=values,
                result_type=result_type,
                automation_id=automation_id,
                row_index=row_index,
                row_depth=1,
                runtime_id=_runtime_id(row),
                semantic_row_key=_semantic_row_key(
                    result_type, automation_id, values
                ),
            )
            results.append(SearchResultRow(candidate=candidate, control=row))
        return results

    def search_contacts(self, target: str) -> list[SearchCandidate]:
        if not self.ensure_search_ready():
            return []

        initial = self._coerce_search_rows(self._search_rows())
        initial_signature = (
            self._candidate_signature([entry.candidate for entry in initial])
            if initial
            else ()
        )
        self._search_results = []
        self._search_query = ""
        self._actions.set_text(self._search_edit, "", wake_event=self._wake_event)

        refresh_state = {"cleared": False}

        def cleared_results_refreshed() -> bool:
            if self._actions.read_text(self._search_edit) != "":
                return False
            current = self._coerce_search_rows(self._search_rows())
            if current is None:
                refresh_state["cleared"] = True
                return True
            refreshed = (
                not initial_signature
                or self._candidate_signature(
                    [entry.candidate for entry in current]
                )
                != initial_signature
            )
            if refreshed:
                refresh_state["cleared"] = True
            return refreshed

        if not self._wait_for(
            cleared_results_refreshed,
            self._timeout,
            hwnd=safe_attr(self._session, "hwnd", 0) or None,
        ):
            raise RuntimeError("清空搜索词后结果列表未刷新")

        self._actions.set_text(self._search_edit, target, wake_event=self._wake_event)
        holder: dict[str, Any] = {
            "matches": [],
            "signature": None,
            "stable": 0,
            "last_state_valid": False,
            "empty_since": None,
        }

        def reset_stability() -> None:
            holder["signature"] = None
            holder["stable"] = 0
            holder["last_state_valid"] = False
            holder["empty_since"] = None

        def collect_results():
            if self._actions.read_text(self._search_edit) != target:
                reset_stability()
                return False
            current = self._coerce_search_rows(self._search_rows())
            if current is None:
                reset_stability()
                return False
            candidates = [entry.candidate for entry in current]
            holder["last_state_valid"] = True
            signature = self._candidate_signature(candidates)
            if signature == holder["signature"]:
                holder["stable"] += 1
            else:
                holder["signature"] = signature
                holder["stable"] = 1
            holder["matches"] = candidates
            if not candidates:
                holder["signature"] = None
                holder["stable"] = 0
                now = time.monotonic()
                if holder["empty_since"] is None:
                    holder["empty_since"] = now
                    return False
                return (
                    refresh_state["cleared"]
                    and now - holder["empty_since"]
                    >= SEARCH_EMPTY_STABLE_SECONDS
                )
            holder["empty_since"] = None
            return refresh_state["cleared"] and holder["stable"] >= 2

        if not self._wait_for(
            collect_results,
            self._timeout,
            hwnd=safe_attr(self._session, "hwnd", 0) or None,
        ):
            explicit_empty = (
                refresh_state["cleared"]
                and holder["last_state_valid"]
                and holder["matches"] == []
                and self._actions.read_text(self._search_edit) == target
            )
            if not explicit_empty:
                raise RuntimeError("本轮搜索结果列表未稳定")
        self._search_results = list(holder["matches"])
        self._search_query = target
        return list(self._search_results)

    def _resolve_search_candidate(self, candidate: SearchCandidate):
        current = self._coerce_search_rows(self._search_rows())
        if current is None:
            return None
        candidates = [entry.candidate for entry in current]
        expected = normalize_identity(self._search_query)
        matching_indexes = [
            index
            for index, current_candidate in enumerate(candidates)
            if any(
                normalize_identity(identity) == expected
                for identity in current_candidate.identities
            )
        ]
        if len(matching_indexes) != 1:
            return None
        exact_indexes = [
            index
            for index, current_candidate in enumerate(candidates)
            if self._same_candidate(current_candidate, candidate)
        ]
        if len(exact_indexes) != 1:
            expected_identities = {
                normalize_identity(value) for value in candidate.identities
            }
            exact_indexes = [
                index
                for index, current_candidate in enumerate(candidates)
                if current_candidate.automation_id == candidate.automation_id
                and current_candidate.result_type == candidate.result_type
                and {
                    normalize_identity(value)
                    for value in current_candidate.identities
                }
                == expected_identities
            ]
        if len(exact_indexes) != 1:
            return None
        index = exact_indexes[0]
        if index != matching_indexes[0]:
            return None
        return current[index].control

    def _search_candidate_present(self, candidate: SearchCandidate) -> bool:
        current = self._coerce_search_rows(self._search_rows())
        if current is None:
            return False
        return any(
            self._same_candidate(entry.candidate, candidate) for entry in current
        )

    def select_search_result(self, candidate: SearchCandidate) -> None:
        if not isinstance(candidate, SearchCandidate):
            raise TypeError("select_search_result requires SearchCandidate")
        observed = self._resolve_search_candidate(candidate)
        if observed is None:
            raise RuntimeError("无法解析唯一搜索结果控件")
        # Resolve once more immediately before the reversible navigation click.
        # This rejects a newly duplicated result and avoids retaining the row
        # wrapper while the result list is animating.
        control = self._resolve_search_candidate(candidate)
        if control is None:
            raise RuntimeError("点击前无法重新解析唯一搜索结果控件")
        self._selected_target = self._search_query or candidate.display_name
        self._selected_identities = candidate.identities

        def selected_chat_verified() -> bool:
            title = normalize_identity(self.current_chat_title())
            return bool(title) and any(
                normalize_identity(identity) == title
                for identity in (self._selected_identities or candidate.identities)
            )

        def destination_verified() -> bool:
            return self.composer_ready() and selected_chat_verified()

        self._click_search_candidate(control)
        if not self._wait_for(
            destination_verified,
            min(self._timeout, SEARCH_DESTINATION_TIMEOUT_SECONDS),
            hwnd=safe_attr(self._session, "hwnd", 0) or None,
        ):
            source_state = "仍存在" if self._search_candidate_present(candidate) else "已消失"
            raise ActionVerificationError(
                "点击精确搜索结果后，聊天标题或输入框仍未就绪；"
                f"source={source_state}"
            )

    def current_chat_title(self) -> str:
        if not self._selected_target:
            return ""
        if self._find_composer() is None:
            return ""
        root = self._control_root(self._session.hwnd)
        root_rect = safe_attr(root, "BoundingRectangle")
        accepted_identities = {
            normalize_identity(identity)
            for identity in (
                self._selected_identities or frozenset({self._selected_target})
            )
        }
        containers = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            root=root,
            class_name=CHAT_TITLE_CONTAINER_CLASS,
            enabled=False,
        )
        for container in containers:
            controls = self._find_scoped_controls(
                hwnd=self._session.hwnd,
                root=container,
                control_type="TextControl",
                class_name=CHAT_TITLE_CONTROL_CLASS,
                enabled=False,
            )
            for control in controls:
                automation_id = str(safe_attr(control, "AutomationId", ""))
                if automation_id and not (
                    automation_id == CHAT_TITLE_AUTOMATION_ID
                    or automation_id.endswith("current_chat_name_label")
                ):
                    continue
                title = str(safe_attr(control, "Name", "")).strip()
                if normalize_identity(title) not in accepted_identities:
                    continue
                rectangle = safe_attr(control, "BoundingRectangle")
                if not self._rect_valid(root_rect) or not self._rect_valid(rectangle):
                    continue
                midpoint = (
                    (rectangle.left + rectangle.right) // 2,
                    (rectangle.top + rectangle.bottom) // 2,
                )
                if self._point_in_rect(midpoint, root_rect):
                    return title
        return ""

    def _find_composer(self):
        profile = self._session.profile
        matches = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            control_type="EditControl",
            class_name=profile.chat_input_class,
            automation_id=profile.chat_input_automation_id,
        )
        return matches[0] if len(matches) == 1 else None

    def composer_ready(self) -> bool:
        try:
            self._composer = self._find_composer()
            return self._composer is not None
        except _STOP_ERRORS:
            raise
        except Exception:
            return False

    def set_composer_text(self, text: str) -> str:
        if not self.composer_ready():
            raise RuntimeError("消息输入框不可用")
        return self._actions.set_text(
            self._composer, text, wake_event=self._wake_event
        ).method

    def read_composer_text(self) -> str | None:
        try:
            composer = self._find_composer()
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        if composer is None:
            return None
        if bool(safe_attr(composer, "IsOffscreen", True)):
            return None
        if not self._rect_valid(safe_attr(composer, "BoundingRectangle")):
            return None
        try:
            self._owning_window(composer)
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        self._composer = composer
        try:
            return self._actions.read_text(composer)
        except _STOP_ERRORS:
            raise
        except Exception:
            return None

    @staticmethod
    def _control_key(control) -> tuple:
        return control_key(control)

    def _message_controls(self) -> list[Any]:
        profile = self._session.profile
        lists = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            automation_id=profile.chat_message_list_automation_id,
            enabled=False,
        )
        if len(lists) != 1:
            return []
        composer_rect = safe_attr(self._find_composer(), "BoundingRectangle")
        controls = []
        candidates = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            root=lists[0],
            control_types=("ListItemControl", "TextControl", "CustomControl"),
            enabled=False,
        )
        for control in candidates:
            text = str(safe_attr(control, "Name", "")).strip()
            if not text:
                continue
            rectangle = safe_attr(control, "BoundingRectangle")
            if composer_rect is not None and rectangle is not None:
                if rectangle.bottom > composer_rect.top:
                    continue
            class_name = str(safe_attr(control, "ClassName", ""))
            control_type = str(safe_attr(control, "ControlTypeName", ""))
            if (
                "Message" in class_name
                or "Chat" in class_name
                or control_type in {"ListItemControl", "TextControl"}
            ):
                controls.append(control)
        return controls

    @staticmethod
    def _message_identity(control: Any) -> tuple:
        return (
            _stable_message_control_identity(control),
            str(safe_attr(control, "Name", "")).strip(),
        )

    def message_snapshot(self) -> tuple[tuple, ...]:
        return tuple(
            self._message_identity(control) for control in self._message_controls()
        )

    def _attachment_snapshot_controls(self):
        profile = self._session.profile
        matches = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            automation_id=profile.chat_message_list_automation_id,
            enabled=False,
        )
        if len(matches) != 1:
            return None, [], []
        message_list = matches[0]
        rectangle = safe_attr(message_list, "BoundingRectangle")
        controls = self._find_scoped_controls(
            hwnd=self._session.hwnd,
            root=message_list,
            enabled=False,
        )
        accepted_classes = set(profile.chat_message_classes)
        bubbles = [
            control
            for control in controls
            if str(safe_attr(control, "ClassName", "")) in accepted_classes
        ]
        return rectangle, bubbles, controls

    @staticmethod
    def _rectangle_tuple(rectangle: Any) -> tuple[int, int, int, int] | None:
        if not NativeWeixinDriver._rect_valid(rectangle):
            return None
        return (
            int(rectangle.left),
            int(rectangle.top),
            int(rectangle.right),
            int(rectangle.bottom),
        )

    def attachment_snapshot(self) -> tuple[MessageBubbleSnapshot, ...]:
        """Capture top-level bubble evidence without persisting message content."""

        message_rectangle, bubbles, controls = self._attachment_snapshot_controls()
        accepted_classes = set(self._session.profile.chat_message_classes)
        snapshots = []
        for order, bubble in enumerate(bubbles):
            values = []
            outer_name = str(safe_attr(bubble, "Name", "")).strip()
            if outer_name:
                values.append(outer_name)
            bubble_rectangle = safe_attr(bubble, "BoundingRectangle")
            for control in controls:
                if control is bubble or str(
                    safe_attr(control, "ClassName", "")
                ) in accepted_classes:
                    continue
                control_rectangle = safe_attr(control, "BoundingRectangle")
                if (
                    not self._rect_valid(bubble_rectangle)
                    or not self._rect_valid(control_rectangle)
                ):
                    continue
                midpoint = (
                    (control_rectangle.left + control_rectangle.right) // 2,
                    (control_rectangle.top + control_rectangle.bottom) // 2,
                )
                if not self._point_in_rect(midpoint, bubble_rectangle):
                    continue
                value = str(safe_attr(control, "Name", "")).strip()
                if value and value not in values:
                    values.append(value)

            rectangle = bubble_rectangle
            outgoing = None
            if self._rect_valid(message_rectangle) and self._rect_valid(rectangle):
                message_width = message_rectangle.right - message_rectangle.left
                bubble_width = rectangle.right - rectangle.left
                # Weixin's Qt provider exposes many message rows at the full
                # viewport width.  Such geometry carries no sender direction;
                # only genuinely aligned cards may be classified left/right.
                if message_width > 0 and bubble_width < message_width * 0.8:
                    message_midpoint = (
                        message_rectangle.left + message_rectangle.right
                    ) / 2
                    bubble_midpoint = (rectangle.left + rectangle.right) / 2
                    outgoing = bubble_midpoint > message_midpoint

            runtime_id = _runtime_id(bubble)
            identity = _stable_message_control_identity(bubble)
            if not runtime_id and values:
                identity = (
                    "fallback-bubble",
                    str(safe_attr(bubble, "ClassName", "")),
                    str(safe_attr(bubble, "AutomationId", "")),
                    tuple(normalize_identity(value) for value in values),
                )
            snapshots.append(
                MessageBubbleSnapshot(
                    identity=identity,
                    runtime_id=runtime_id,
                    class_name=str(safe_attr(bubble, "ClassName", "")),
                    automation_id=str(safe_attr(bubble, "AutomationId", "")),
                    accessible_names=tuple(values),
                    bounds=self._rectangle_tuple(rectangle),
                    order=order,
                    outgoing=outgoing,
                )
            )
        return tuple(snapshots)

    def _attachment_draft_visible(self, filename: str) -> bool | None:
        """Return whether a pasted attachment draft is exposed near the composer."""

        composer = self._find_composer()
        if composer is None:
            return None
        try:
            parent = composer.GetParentControl()
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        if parent is None:
            return None
        composer_rectangle = safe_attr(composer, "BoundingRectangle")
        try:
            controls = self._find_scoped_controls(
                hwnd=self._session.hwnd,
                root=parent,
                enabled=False,
            )
        except _STOP_ERRORS:
            raise
        except Exception:
            return None
        expected = normalize_identity(filename)
        for control in controls:
            if normalize_identity(str(safe_attr(control, "Name", ""))) != expected:
                continue
            if str(safe_attr(control, "ClassName", "")) in set(
                self._session.profile.chat_message_classes
            ):
                continue
            rectangle = safe_attr(control, "BoundingRectangle")
            if not self._rect_valid(rectangle):
                continue
            if not self._rect_valid(composer_rectangle) or (
                rectangle.bottom >= composer_rectangle.top
            ):
                return True
        return False

    def verify_attachment_sent(
        self,
        before: Sequence[MessageBubbleSnapshot],
        filename: str,
        timeout: float,
        *,
        draft_was_visible: bool | None,
    ) -> bool | None:
        prior_identities = {snapshot.identity for snapshot in before}
        previous_tail = before[-1].identity if before else None
        expected = normalize_identity(filename)
        file_class = "mmui::ChatFileItemView"

        def filename_tokens(snapshot: MessageBubbleSnapshot) -> set[str]:
            return {
                normalize_identity(line)
                for value in snapshot.accessible_names
                for line in str(value).splitlines()
                if normalize_identity(line)
            }

        def appended() -> bool:
            current = self.attachment_snapshot()
            if not current:
                return False
            tail = current[-1]
            if (
                tail.identity == previous_tail
                or tail.identity in prior_identities
                or tail.outgoing is False
            ):
                return False
            exact_filename = expected in filename_tokens(tail)
            if tail.class_name != file_class and not exact_filename:
                return False
            # A full-width Qt row has no usable direction.  In that layout the
            # exact filename token is required to bind the new tail bubble to
            # this one paste/Enter action.
            if tail.outgoing is None and not exact_filename:
                return False
            if self.read_composer_text() != "":
                return False
            return self._attachment_draft_visible(filename) is False

        if self._wait_for(
            appended,
            timeout,
            hwnd=safe_attr(self._session, "hwnd", 0) or None,
        ):
            return True
        self._raise_scoped_risk(
            hwnd=safe_attr(self._session, "hwnd", 0) or None
        )
        return None

    def _invoke_once_or_key(
        self, _button_names: Sequence[str], key_control
    ) -> str:
        """Trigger Weixin's proven composer Enter path exactly once.

        Weixin 4.1.13.65 exposes an InvokePattern on the send button that can
        report success without sending. The v0.2 path targeted the composer
        with Enter and proved materially more stable, so the Agent preserves
        that trigger while adding fresh-control and postcondition checks. Once
        Enter is issued, no button click or alternate shortcut is attempted.
        """
        fresh_control = self._find_composer()
        if fresh_control is None:
            raise ActionVerificationError(
                "发送前无法重新定位消息输入框，拒绝触发发送"
            )
        self._composer = fresh_control
        try:
            self._composer = self._send_keys(fresh_control, "{Enter}")
        except _STOP_ERRORS:
            raise
        except Exception as exc:
            raise ActionVerificationError(
                "消息输入框 Enter 触发异常；结果未知且不会补发"
            ) from exc
        if not self._wait_for(
            lambda: self.read_composer_text() == "",
            self._timeout,
            hwnd=self._session.hwnd,
        ):
            raise ActionVerificationError(
                "消息输入框 Enter 后未清空；为避免重复，不再尝试其他动作"
            )
        return "keyboard_enter"

    def trigger_send(self) -> str:
        if self._composer is None and not self.composer_ready():
            raise RuntimeError("消息输入框不可用")
        return self._invoke_once_or_key(("发送", "发送(S)"), self._composer)

    def verify_sent(self, before, expected: str, timeout: float) -> bool | None:
        def appended():
            controls = self._message_controls()
            current = tuple(self._message_identity(control) for control in controls)
            if not current:
                return False
            old_tail = before[-1][0] if before else None
            new_tail = current[-1]
            prior_identities = {entry[0] for entry in before}
            has_new_match = (
                new_tail[0] != old_tail
                and new_tail[0] not in prior_identities
                and normalize_identity(new_tail[1]) == normalize_identity(expected)
            )
            composer_text = self.read_composer_text()
            return (
                has_new_match
                and composer_text is not None
                and composer_text == ""
            )

        if self._wait_for(
            appended,
            timeout,
            hwnd=safe_attr(self._session, "hwnd", 0) or None,
        ):
            return True
        self._raise_scoped_risk(
            hwnd=safe_attr(self._session, "hwnd", 0) or None
        )
        return None

    def send_files(self, paths: Sequence[str]) -> list[dict[str, str]]:
        from src.utils.clipboard_utils import set_files_to_clipboard

        results = []
        for value in paths:
            path = str(Path(value))
            if not Path(path).is_file():
                results.append(
                    {"path": path, "outcome": "error", "detail": "文件不存在"}
                )
                continue
            before = self.attachment_snapshot()
            if not set_files_to_clipboard([path]):
                results.append(
                    {"path": path, "outcome": "error", "detail": "剪贴板写入失败"}
                )
                continue
            self._report_progress("attachment_paste")
            self._click_bounds(self._composer)
            self._composer = self._send_keys(self._composer, "{Ctrl}v", wait_time=0.1)
            draft_was_visible = self._attachment_draft_visible(Path(path).name)
            self._invoke_once_or_key(("发送", "发送(S)"), self._composer)
            self._report_progress("attachment_verify")
            verified = self.verify_attachment_sent(
                before,
                Path(path).name,
                self._timeout,
                draft_was_visible=draft_was_visible,
            )
            results.append(
                {
                    "path": path,
                    "outcome": "success" if verified else "unknown",
                    "detail": "附件已确认" if verified else "附件结果未知",
                }
            )
        return results

    def _open_exact_chat(self, target: str) -> None:
        if not self.ensure_search_ready():
            raise RuntimeError("搜索入口不可用")
        candidates = self.search_contacts(target)
        expected = normalize_identity(target)
        exact = [
            candidate
            for candidate in candidates
            if any(
                normalize_identity(identity) == expected
                for identity in candidate.identities
            )
        ]
        if len(exact) != 1:
            raise RuntimeError(f"无法定位唯一聊天目标：{target}")
        self.select_search_result(exact[0])
        title = normalize_identity(self.current_chat_title())
        if not title or not any(
            normalize_identity(identity) == title
            for identity in exact[0].identities
        ):
            raise RuntimeError(f"聊天标题校验失败：{target}")

    def prepare_forward_bundle(self, paths: Sequence[str]) -> dict[str, Any]:
        materialized = [str(Path(value)) for value in paths]
        if not materialized or any(not Path(path).is_file() for path in materialized):
            return {"outcome": "error", "detail": "合并转发源文件不存在"}
        self._open_exact_chat("文件传输助手")
        results = self.send_files(materialized)
        if any(result.get("outcome") == "unknown" for result in results):
            return {"outcome": "unknown", "detail": "源文件上传结果未知"}
        failed = [result for result in results if result.get("outcome") != "success"]
        if failed:
            return {
                "outcome": "error",
                "detail": f"{len(failed)} 个源文件上传失败",
            }
        self._forward_source_count = len(materialized)
        return {"outcome": "success", "count": len(materialized)}

    def _legacy_matching_all_controls(self, **selector) -> list[Any]:
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        return [
            control
            for control, depth in nodes
            if find_exact_control(((control, depth),), **selector) is control
        ]

    def _visible_process_roots(self) -> list[tuple[int, Any]]:
        import win32gui
        import win32process

        target_pid = int(self._session.pid)
        handles = [int(self._session.hwnd)]

        def collect(hwnd, _extra):
            try:
                if (
                    win32gui.IsWindowVisible(hwnd)
                    and int(win32process.GetWindowThreadProcessId(hwnd)[1])
                    == target_pid
                    and int(hwnd) not in handles
                ):
                    handles.append(int(hwnd))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(collect, None)
        result = []
        for hwnd in handles:
            self.ensure_window_responsive(hwnd)
            root = self._control_root(hwnd)
            if root is not None:
                result.append((hwnd, root))
        return result

    def _matching_all_controls(self, **selector) -> list[Any]:
        if self._query is None:
            return self._legacy_matching_all_controls(**selector)
        matches = []
        seen = set()
        for hwnd, root in self._visible_process_roots():
            self._raise_scoped_risk(hwnd=hwnd, root=root)
            for control in self._find_scoped_controls(
                hwnd=hwnd, root=root, **selector
            ):
                reference = _control_reference(control)
                if reference not in seen:
                    seen.add(reference)
                    matches.append(control)
        return matches

    def _find_all_control(self, **selector):
        matches = self._matching_all_controls(**selector)
        return matches[0] if len(matches) == 1 else None

    def _resolve_bound_all_control(
        self, reference: tuple[Any, ...], **selector
    ):
        matches = [
            control
            for control in self._matching_all_controls(**selector)
            if _control_reference(control) == reference
        ]
        return matches[0] if len(matches) == 1 else None

    def _click_bound_all_control_once(
        self, control, postcondition, **selector
    ):
        reference = _control_reference(control)
        return self._actions.click(
            control,
            postcondition,
            pre_resolve_control=lambda: self._resolve_bound_all_control(
                reference, **selector
            ),
            wake_event=self._wake_event,
        )

    def _wait_all_control(self, **selector):
        holder = {"control": None}

        def locate():
            holder["control"] = self._find_all_control(**selector)
            return holder["control"] is not None

        if not self._wait_for(locate, self._timeout):
            raise RuntimeError(f"转发控件未出现：{selector}")
        return holder["control"]

    def _message_bubbles(self) -> list[Any]:
        profile = self._session.profile
        message_list = self._wait_control(
            automation_id=profile.chat_message_list_automation_id,
            enabled=False,
        )
        nodes = [
            (control, 1)
            for control in self._find_scoped_controls(
                hwnd=self._session.hwnd,
                root=message_list,
                enabled=False,
            )
        ]
        return filter_recent_message_bubbles(
            nodes, profile.chat_message_classes, len(nodes)
        )

    def _recent_message_bubbles(self, count: int) -> list[Any]:
        bubbles = self._message_bubbles()[-count:] if count > 0 else []
        if len(bubbles) != count:
            raise RuntimeError(f"源消息不足：需要 {count} 条，找到 {len(bubbles)} 条")
        return bubbles

    def _resolve_message_bubble(self, reference: tuple[Any, ...]):
        matches = [
            bubble
            for bubble in self._message_bubbles()
            if _control_reference(bubble) == reference
        ]
        return matches[0] if len(matches) == 1 else None

    def _right_click_bounds(self, control) -> None:
        rectangle = safe_attr(control, "BoundingRectangle")
        if (
            rectangle is None
            or rectangle.right <= rectangle.left
            or rectangle.bottom <= rectangle.top
        ):
            raise RuntimeError("消息气泡没有可用边界")
        point = (
            (rectangle.left + rectangle.right) // 2,
            (rectangle.top + rectangle.bottom) // 2,
        )
        window_root, _window_rectangle = self._owning_window(control)
        self._prepare_click_window(window_root, control, point)
        self._uia.RightClick(*point)

    @staticmethod
    def _read_selection_state(control) -> bool | None:
        for getter, attribute in (
            ("GetSelectionItemPattern", "IsSelected"),
            ("GetTogglePattern", "ToggleState"),
        ):
            try:
                pattern = getattr(control, getter)()
                value = getattr(pattern, attribute)
                if attribute == "ToggleState":
                    return int(value) == 1
                return bool(value)
            except _STOP_ERRORS:
                raise
            except Exception:
                continue
        return None

    @staticmethod
    def _selection_state(control) -> bool:
        return NativeWeixinDriver._read_selection_state(control) is True

    def _select_forward_bubble(self, control) -> None:
        reference = _control_reference(control)

        def resolve():
            return self._resolve_message_bubble(reference)

        current = resolve()
        if current is None:
            raise RuntimeError("待转发消息已变化，拒绝选择")
        if self._selection_state(current):
            return
        self._actions.click(
            current,
            lambda: (
                (fresh := resolve()) is not None
                and self._selection_state(fresh)
            ),
            pre_resolve_control=resolve,
            wake_event=self._wake_event,
        )

    def _forward_search_edit(self):
        profile = self._session.profile
        for automation_id in profile.forward_search_automation_ids:
            controls = self._matching_all_controls(
                control_type="EditControl",
                automation_id=automation_id,
            )
            if len(controls) == 1:
                return controls[0]
        controls = self._matching_all_controls(
            name=("搜索", "查找"),
            control_type="EditControl",
        )
        return controls[0] if len(controls) == 1 else None

    def _forward_candidate(self, target: str):
        candidates = self._matching_all_controls(
            name=target,
            control_types=("ListItemControl", "ButtonControl", "CheckBoxControl"),
            visible=True,
        )
        if len(candidates) != 1:
            raise RuntimeError(f"转发目标不唯一或未找到：{target}")
        return candidates[0]

    def _forward_recipient_selected(self, target: str, search_edit) -> bool:
        candidates = self._matching_all_controls(
            name=target,
            control_types=("ListItemControl", "ButtonControl", "CheckBoxControl"),
            visible=True,
        )
        if len(candidates) != 1:
            return False
        target_control = candidates[0]
        if self._read_selection_state(target_control) is not True:
            return False

        expected_owner = None
        if self._session is not None:
            try:
                expected_owner, _rectangle = self._owning_window(search_edit)
            except _STOP_ERRORS:
                raise
            except Exception:
                return False

        target_class = str(safe_attr(target_control, "ClassName", ""))
        target_type = str(safe_attr(target_control, "ControlTypeName", ""))
        selected_references = set()
        seen_references = set()
        peers = self._matching_all_controls(
            control_type=target_type,
            class_name=target_class,
            enabled=False,
        )
        for control in peers:
            if expected_owner is not None:
                try:
                    owner, _rectangle = self._owning_window(control)
                except _STOP_ERRORS:
                    raise
                except Exception:
                    return False
                expected_hwnd = int(
                    safe_attr(expected_owner, "NativeWindowHandle", 0) or 0
                )
                owner_hwnd = int(safe_attr(owner, "NativeWindowHandle", 0) or 0)
                if expected_hwnd and owner_hwnd:
                    if owner_hwnd != expected_hwnd:
                        continue
                elif owner is not expected_owner:
                    continue

            reference = _control_reference(control)
            if reference in seen_references:
                continue
            seen_references.add(reference)
            selection_state = self._read_selection_state(control)
            if selection_state is None:
                return False
            if selection_state:
                selected_references.add(reference)

        return selected_references == {_control_reference(target_control)}

    def _forward_message_edit(self, search_edit):
        controls = self._matching_all_controls(
            name=("留言", "附言", "给朋友留言"),
            control_type="EditControl",
            visible=True,
        )
        for control in controls:
            if control is search_edit:
                continue
            return control
        return None

    def _invoke_once(self, control) -> str:
        try:
            pattern = control.GetInvokePattern()
        except _STOP_ERRORS:
            raise
        except Exception:
            pattern = None
        if pattern is not None:
            try:
                result = pattern.Invoke(waitTime=0)
            except TypeError:
                result = pattern.Invoke()
            if result is False:
                raise RuntimeError("InvokePattern 返回失败")
            return "invoke_pattern"
        self._click_bounds(control)
        return "uia_bounds_click"

    def forward_bundle(
        self, target: str, message: str, paths: Sequence[str]
    ) -> dict[str, str]:
        count = int(getattr(self, "_forward_source_count", 0))
        if count != len(paths) or count <= 0:
            return {"outcome": "error", "detail": "合并转发源文件尚未准备"}

        self._open_exact_chat(target)
        target_snapshot = self.message_snapshot()
        self._open_exact_chat("文件传输助手")
        bubbles = self._recent_message_bubbles(count)
        last_bubble = self._resolve_message_bubble(
            _control_reference(bubbles[-1])
        )
        if last_bubble is None:
            raise RuntimeError("待转发消息已变化，拒绝打开多选")
        self._right_click_bounds(last_bubble)
        interactive_types = tuple(sorted(INTERACTIVE_CONTROL_TYPES))
        multi_selector = dict(
            name=("多选", "选择多条", "多选消息"),
            control_types=interactive_types,
            visible=True,
        )
        multi = self._wait_all_control(**multi_selector)
        forward_selector = dict(
            name=("转发",),
            control_types=interactive_types,
            visible=True,
        )
        self._click_bound_all_control_once(
            multi,
            lambda: self._find_all_control(**forward_selector) is not None,
            **multi_selector,
        )

        bubbles = self._recent_message_bubbles(count)
        bubble_references = {_control_reference(bubble) for bubble in bubbles}
        for bubble in bubbles:
            self._select_forward_bubble(bubble)
        selected_references = {
            _control_reference(bubble)
            for bubble in self._message_bubbles()
            if self._selection_state(bubble)
        }
        if selected_references != bubble_references:
            raise RuntimeError("多选消息集合与待转发文件不一致，拒绝继续")

        forward = self._wait_all_control(**forward_selector)
        merge_selector = dict(
            name=("合并转发", "合并发送"),
            control_types=interactive_types,
            visible=True,
        )
        self._click_bound_all_control_once(
            forward,
            lambda: self._find_all_control(**merge_selector) is not None,
            **forward_selector,
        )
        merge = self._wait_all_control(**merge_selector)
        self._click_bound_all_control_once(
            merge,
            lambda: self._forward_search_edit() is not None,
            **merge_selector,
        )

        search_edit = self._forward_search_edit()
        if search_edit is None:
            raise RuntimeError("转发搜索框未出现")
        self._actions.set_text(search_edit, target, wake_event=self._wake_event)
        candidate = self._forward_candidate(target)
        candidate_reference = _control_reference(candidate)

        def resolve_candidate():
            try:
                current = self._forward_candidate(target)
            except _STOP_ERRORS:
                raise
            except Exception:
                return None
            return (
                current
                if _control_reference(current) == candidate_reference
                else None
            )

        self._actions.click(
            candidate,
            lambda: self._forward_recipient_selected(target, search_edit),
            pre_resolve_control=resolve_candidate,
            wake_event=self._wake_event,
        )

        if message:
            message_edit = self._forward_message_edit(search_edit)
            if message_edit is None:
                raise RuntimeError("转发留言输入框未暴露到 UIA")
            self._actions.set_text(
                message_edit, message, wake_event=self._wake_event
            )

        if not self._forward_recipient_selected(target, search_edit):
            raise RuntimeError("转发收件人未保持唯一精确选中状态，拒绝发送")
        send_selector = dict(
            name=("发送", "确定"),
            control_type="ButtonControl",
            visible=True,
        )
        send = self._wait_all_control(**send_selector)
        fresh_send = self._resolve_bound_all_control(
            _control_reference(send), **send_selector
        )
        if fresh_send is None:
            raise RuntimeError("转发发送按钮已变化，拒绝触发")
        if not self._forward_recipient_selected(target, search_edit):
            raise RuntimeError("转发收件人在发送前已变化，拒绝触发")
        self._invoke_once(fresh_send)

        self._open_exact_chat(target)
        appended = self._wait_for(
            lambda: has_new_forward_confirmation(
                self._message_controls(), target_snapshot
            ),
            self._timeout,
            hwnd=self._session.hwnd,
        )
        if not appended:
            for hwnd, root in self._visible_process_roots():
                self._raise_scoped_risk(hwnd=hwnd, root=root)
            return {"outcome": "unknown", "detail": "已触发合并转发，但结果无法确认"}
        return {
            "outcome": "success",
            "detail": f"{count} 个文件已合并转发并确认",
        }

    def _activate_navigation(
        self,
        hwnd: int,
        names: Sequence[str],
        postcondition,
    ) -> bool:
        if postcondition():
            return False
        selector = {
            "name": names,
            "control_types": tuple(sorted(INTERACTIVE_CONTROL_TYPES)),
            "visible": True,
        }
        try:
            control = self._wait_control(hwnd=hwnd, **selector)
        except _STOP_ERRORS:
            raise
        except RuntimeError:
            if int(hwnd) != int(self._session.hwnd):
                raise
            self._fresh_main_root()
            if postcondition():
                return False
            control = self._wait_control(hwnd=hwnd, **selector)

        def resolve_navigation_control():
            try:
                matches = self._find_scoped_controls(hwnd=hwnd, **selector)
                return matches[0] if len(matches) == 1 else None
            except _STOP_ERRORS:
                raise
            except Exception:
                return None

        if postcondition():
            return False
        self._actions.click(
            control,
            postcondition,
            pre_resolve_control=resolve_navigation_control,
            wake_event=self._wake_event,
        )
        return True

    def open_add_friend(self) -> bool:
        self._ensure_session()
        self._check_window_blocked(allow_verify=True, allow_friend_parent=True)
        profile = self._session.profile
        verify_class = str(
            safe_attr(profile, "verify_friend_root_class", "") or ""
        )
        if verify_class:
            verify_windows = self._process_windows(
                (verify_class,), visible=None, strict=True
            )
            if len(verify_windows) > 1:
                raise RuntimeError("检测到多个遗留好友申请表单，拒绝继续")
            if verify_windows:
                self._verify_hwnd = verify_windows[0]
                if not self.cancel_friend_request():
                    raise RuntimeError("遗留好友申请表单未能安全关闭")
        self._check_window_blocked(allow_friend_parent=True)
        expected_classes = (profile.add_friend_root_class,)
        visible_windows = self._process_windows(
            expected_classes, visible=True, strict=True
        )
        if len(visible_windows) > 1:
            raise RuntimeError("检测到多个添加朋友窗口，拒绝继续")
        if visible_windows:
            visible_hwnd = visible_windows[0]
            if not self._restore_owned_process_window(
                visible_hwnd, expected_classes
            ):
                raise RuntimeError("添加朋友窗口置前失败")
            self._add_hwnd = visible_hwnd
            return True
        hidden_windows = self._process_windows(
            expected_classes, visible=False, strict=True
        )
        if len(hidden_windows) > 1:
            raise RuntimeError("检测到多个隐藏的添加朋友窗口，拒绝继续")
        if hidden_windows:
            hidden_hwnd = hidden_windows[0]
            if not self._restore_owned_process_window(
                hidden_hwnd, expected_classes
            ):
                raise RuntimeError("隐藏的添加朋友窗口恢复失败")
            self._add_hwnd = hidden_hwnd
            return True
        main_hwnd = self._session.hwnd
        self._fresh_main_root()
        self._activate_navigation(
            main_hwnd,
            ("微信",),
            lambda: bool(self._find_scoped_controls(
                hwnd=main_hwnd,
                name="快捷操作",
                control_types=tuple(sorted(INTERACTIVE_CONTROL_TYPES)),
                visible=True,
            )),
        )
        self._activate_navigation(
            main_hwnd,
            ("快捷操作",),
            lambda: bool(self._find_scoped_controls(
                hwnd=main_hwnd,
                name="添加朋友",
                control_types=tuple(sorted(INTERACTIVE_CONTROL_TYPES)),
                visible=True,
            )),
        )
        def parent_opened():
            windows = self._process_windows(expected_classes, strict=True)
            if len(windows) > 1:
                raise WindowBlockedError("Multiple add-friend windows appeared")
            return bool(windows)

        opened_by_task = self._activate_navigation(
            main_hwnd,
            ("添加朋友",),
            parent_opened,
        )
        self._add_hwnd = self._process_window((profile.add_friend_root_class,))
        if opened_by_task and self._add_hwnd and self._task_kind:
            self._task_owned_add_hwnd = self._add_hwnd
        return bool(self._add_hwnd)

    def _friend_profile_state(self):
        if self._query is None:
            nodes = self._scoped_nodes(hwnd=self._add_hwnd)
            profile_roots = [
                control
                for control, _depth in nodes
                if str(safe_attr(control, "ClassName", ""))
                == "mmui::ProfileViewNormal"
            ]
            if len(profile_roots) != 1:
                return (
                    None,
                    nodes,
                    extract_labeled_friend_identities(nodes),
                    _unique_visible_add_friend_button(nodes),
                )
            return (
                profile_roots[0],
                nodes,
                extract_labeled_friend_identities(nodes),
                _unique_visible_add_friend_button(nodes),
            )
        profile_roots = self._find_scoped_controls(
            hwnd=self._add_hwnd,
            class_name="mmui::ProfileViewNormal",
            enabled=False,
        )
        if len(profile_roots) != 1:
            return None, [], [], None
        profile_root = profile_roots[0]
        self._raise_scoped_risk(hwnd=self._add_hwnd, root=profile_root)
        descendants = self._find_scoped_controls(
            hwnd=self._add_hwnd,
            root=profile_root,
            enabled=False,
        )
        nodes = [(profile_root, 0), *((control, 1) for control in descendants)]
        identities = extract_labeled_friend_identities(nodes)
        buttons = [
            control
            for control in self._find_scoped_controls(
                hwnd=self._add_hwnd,
                root=profile_root,
                name="添加到通讯录",
                control_type="ButtonControl",
                visible=True,
            )
            if str(safe_attr(control, "ClassName", "")) == "mmui::XOutlineButton"
            and str(safe_attr(control, "AutomationId", "")).endswith(
                "ProfileActionUi.add_friend_button"
            )
        ]
        button = buttons[0] if len(buttons) == 1 else None
        return profile_root, nodes, identities, button

    def set_friend_account(self, account: str) -> str:
        search = self._wait_control(
            hwnd=self._add_hwnd,
            name=("搜索", "微信号/手机号"),
            control_type="EditControl",
        )
        self._friend_profile_reset_for = ""
        self._friend_profile_token = None
        current_value = self._actions.read_text(search)

        def profile_absent() -> bool:
            try:
                return not self._find_scoped_controls(
                    hwnd=self._add_hwnd,
                    class_name="mmui::ProfileViewNormal",
                    enabled=False,
                )
            except _STOP_ERRORS:
                raise
            except Exception:
                return False

        if current_value or not profile_absent():
            self._actions.set_text(search, "", wake_event=self._wake_event)
            if not self._wait_for(
                lambda: self._actions.read_text(search) == "" and profile_absent(),
                self._timeout,
                hwnd=self._add_hwnd,
            ):
                raise RuntimeError("旧好友资料未清空，拒绝搜索下一账号")
        self._friend_account = account
        result = self._actions.set_text(
            search, account, wake_event=self._wake_event
        )
        self._friend_search = search
        self._friend_profile_reset_for = normalize_identity(account)
        self._friend_query_generation += 1
        return result.method

    def search_friend(self, account: str) -> dict[str, Any] | None:
        exact_query_was_reset = (
            self._friend_profile_reset_for == normalize_identity(account)
        )
        self._friend_profile_reset_for = ""
        if exact_query_was_reset:
            before_nodes = self._scoped_nodes(hwnd=self._add_hwnd)
            if any(
                str(safe_attr(control, "ClassName", ""))
                == "mmui::ProfileViewNormal"
                or str(safe_attr(control, "Name", "")).strip()
                == "添加到通讯录"
                for control, _depth in before_nodes
            ):
                self._friend_profile_token = None
                raise RuntimeError("本轮搜索前仍有旧好友资料，拒绝继续")
        self._friend_search = self._send_keys(self._friend_search, "{Enter}")
        try:
            self._wait_control(
                hwnd=self._add_hwnd,
                name="添加到通讯录",
                control_types=tuple(sorted(INTERACTIVE_CONTROL_TYPES)),
                visible=True,
            )
        except _STOP_ERRORS:
            raise
        except RuntimeError:
            self._raise_scoped_risk(hwnd=self._add_hwnd)
            return None
        self._raise_scoped_risk(hwnd=self._add_hwnd)
        profile_root, nodes, identities, scoped_button = self._friend_profile_state()
        button = None
        if len(identities) == 1:
            verified_account = identities[0]
            verification = "labeled_profile_identity"
            button = scoped_button
        elif exact_query_was_reset and not identities:
            button = (
                scoped_button
                if profile_root is not None
                and _runtime_id(profile_root)
                and scoped_button is not None
                and _runtime_id(scoped_button)
                and normalize_identity(
                    self._actions.read_text(self._friend_search) or ""
                )
                == normalize_identity(account)
                else None
            )
            if button is not None:
                verified_account = account
                verification = "exact_query_profile_card"
            else:
                verified_account = ""
                verification = "unverified"
        else:
            verified_account = ""
            verification = "unverified"
        if button is None:
            verified_account = ""
            verification = "unverified"
            control_reference: tuple[Any, ...] = ()
            profile_reference: tuple[Any, ...] = ()
            token = None
        else:
            control_reference = _control_reference(button)
            profile_reference = (
                _control_reference(profile_root)
                if profile_root is not None
                else ()
            )
            token = (
                self._friend_query_generation,
                normalize_identity(account),
                normalize_identity(verified_account),
                verification,
                profile_reference,
                control_reference,
            )
        self._friend_profile_token = token
        return {
            "account": verified_account,
            "control": button,
            "verification": verification,
            "query": account,
            "queryGeneration": self._friend_query_generation,
            "profileReference": profile_reference,
            "controlReference": control_reference,
            "profileToken": token,
        }

    @staticmethod
    def profile_account(profile: dict[str, Any]) -> str:
        return str(profile.get("account", ""))

    def open_friend_request(self, profile: dict[str, Any]) -> bool:
        expected_classes = (self._session.profile.verify_friend_root_class,)
        token = profile.get("profileToken")
        expected_query = normalize_identity(str(profile.get("query", "")))
        expected_account = normalize_identity(str(profile.get("account", "")))
        expected_profile_reference = profile.get("profileReference")
        expected_reference = profile.get("controlReference")
        verification = str(profile.get("verification", ""))

        def resolve_add_button():
            try:
                if (
                    not token
                    or token != self._friend_profile_token
                    or int(profile.get("queryGeneration", -1))
                    != self._friend_query_generation
                    or expected_query != normalize_identity(self._friend_account)
                    or expected_account != expected_query
                    or normalize_identity(
                        self._actions.read_text(self._friend_search) or ""
                    )
                    != expected_query
                ):
                    return None
                self._raise_scoped_risk(hwnd=self._add_hwnd)
                profile_root, _nodes, identities, button = (
                    self._friend_profile_state()
                )
                if verification == "exact_query_profile_card":
                    if identities:
                        return None
                    if (
                        profile_root is None
                        or button is None
                        or not _runtime_id(profile_root)
                        or not _runtime_id(button)
                    ):
                        return None
                elif verification == "labeled_profile_identity":
                    if (
                        len(identities) != 1
                        or normalize_identity(identities[0]) != expected_account
                    ):
                        return None
                else:
                    return None
                current_profile_reference = (
                    _control_reference(profile_root)
                    if profile_root is not None
                    else ()
                )
                if (
                    button is None
                    or current_profile_reference != expected_profile_reference
                    or _control_reference(button) != expected_reference
                ):
                    return None
                return button
            except _STOP_ERRORS:
                raise
            except Exception:
                return None

        if self._process_windows(
            expected_classes, visible=None, strict=True
        ):
            raise RuntimeError("检测到旧的好友申请表单，拒绝点击新的资料卡")

        current_button = resolve_add_button()
        if current_button is None:
            raise RuntimeError("好友资料卡已变化或未绑定当前账号，拒绝点击")

        def new_verify_window() -> bool:
            return len(
                self._process_windows(expected_classes, strict=True)
            ) == 1

        self._actions.click(
            current_button,
            new_verify_window,
            pre_resolve_control=resolve_add_button,
            wake_event=self._wake_event,
        )
        verify_windows = self._process_windows(expected_classes, strict=True)
        if len(verify_windows) != 1:
            raise RuntimeError("好友申请表单未唯一出现，拒绝继续")
        self._verify_hwnd = verify_windows[0]
        return bool(self._verify_hwnd)

    def set_friend_fields(
        self, greeting: str | None, remark: str
    ) -> dict[str, str]:
        self._raise_scoped_risk(hwnd=self._verify_hwnd)
        greeting_matches = self._find_scoped_controls(
            hwnd=self._verify_hwnd,
            name="发送添加朋友申请",
            control_type="EditControl",
        )
        remark_matches = self._find_scoped_controls(
            hwnd=self._verify_hwnd,
            name="修改备注",
            control_type="EditControl",
        )
        if len(greeting_matches) != 1 or len(remark_matches) != 1:
            raise RuntimeError("好友申请表单字段未完整暴露到 UIA")
        greeting_edit, remark_edit = greeting_matches[0], remark_matches[0]
        if greeting is not None:
            self._actions.set_text(
                greeting_edit, greeting, wake_event=self._wake_event
            )
        if remark:
            self._actions.set_text(
                remark_edit, remark, wake_event=self._wake_event
            )
        return {
            "greeting": self._actions.read_text(greeting_edit) or "",
            "remark": self._actions.read_text(remark_edit) or "",
        }

    def _resolve_unique_friend_submit_control(self):
        """Resolve the irreversible submit target from a fresh verified root."""

        hwnd = int(self._verify_hwnd or 0)
        session = self._session
        if not hwnd or session is None or self._uia is None:
            raise RuntimeError("好友申请窗口未绑定，拒绝提交")
        expected_pid = int(safe_attr(session, "pid", 0) or 0)
        expected_class = str(
            safe_attr(session.profile, "verify_friend_root_class", "") or ""
        )
        if not expected_pid or not expected_class:
            raise RuntimeError("好友申请窗口身份不完整，拒绝提交")

        verify_windows = self._process_windows(
            (expected_class,), visible=True, strict=True
        )
        if len(verify_windows) != 1 or int(verify_windows[0]) != hwnd:
            raise RuntimeError(
                "好友申请窗口未唯一保持可见，拒绝提交："
                f"expectedHwnd={hwnd}, matches={verify_windows}"
            )

        self.ensure_window_responsive(hwnd)
        root = self._uia.ControlFromHandle(hwnd)
        root_class = str(safe_attr(root, "ClassName", "") or "")
        root_type = str(safe_attr(root, "ControlTypeName", "") or "")
        root_hwnd = int(safe_attr(root, "NativeWindowHandle", 0) or 0)
        root_pid = int(safe_attr(root, "ProcessId", 0) or 0)
        if (
            root is None
            or root_class != expected_class
            or root_type != "WindowControl"
            or root_hwnd != hwnd
            or root_pid != expected_pid
        ):
            raise RuntimeError(
                "好友申请窗口身份已变化，拒绝提交："
                f"hwnd={root_hwnd}, pid={root_pid}, class={root_class!r}, "
                f"type={root_type!r}"
            )
        if bool(safe_attr(root, "IsOffscreen", True)):
            raise RuntimeError("好友申请窗口不可见，拒绝提交")
        if not bool(safe_attr(root, "IsEnabled", False)):
            raise RuntimeError("好友申请窗口未启用，拒绝提交")

        self._raise_scoped_risk(hwnd=hwnd, root=root)
        matches = self._find_scoped_controls(
            hwnd=hwnd,
            root=root,
            name="确定",
            control_type="ButtonControl",
            visible=True,
        )
        if len(matches) != 1:
            raise RuntimeError(
                "好友申请的“确定”按钮未唯一出现，拒绝提交："
                f"matches={len(matches)}"
            )
        confirm = matches[0]
        if not bool(safe_attr(confirm, "IsEnabled", False)):
            raise RuntimeError("好友申请的“确定”按钮未启用，拒绝提交")
        if bool(safe_attr(confirm, "IsOffscreen", True)):
            raise RuntimeError("好友申请的“确定”按钮不可见，拒绝提交")

        owner, _owner_bounds = self._owning_window(confirm)
        owner_hwnd = int(safe_attr(owner, "NativeWindowHandle", 0) or 0)
        owner_pid = int(safe_attr(owner, "ProcessId", 0) or 0)
        owner_class = str(safe_attr(owner, "ClassName", "") or "")
        if (
            owner_hwnd != hwnd
            or owner_pid != expected_pid
            or owner_class != expected_class
        ):
            raise RuntimeError(
                "好友申请确认控件不属于当前申请窗口，拒绝提交："
                f"ownerHwnd={owner_hwnd}, ownerPid={owner_pid}, "
                f"ownerClass={owner_class!r}"
            )
        return confirm

    def submit_friend_request(self) -> FriendSubmitReceipt:
        """Hit-test and click the exact fresh confirmation control once.

        Weixin 4.1.13.65 exposes an InvokePattern that can return success while
        doing nothing.  The irreversible boundary therefore uses one guarded
        physical click and returns a typed receipt only after injection returns.
        Exceptions carry ``destructive_triggered`` so the workflow never claims
        a click occurred when validation actually failed before injection.
        """

        try:
            observed = self._resolve_unique_friend_submit_control()
            observed_reference = _control_reference(observed)
            confirm = self._resolve_unique_friend_submit_control()
            confirm_reference = _control_reference(confirm)
            if confirm_reference != observed_reference:
                raise RuntimeError("好友申请确认控件在提交前发生变化，拒绝提交")

            window_root, window_rectangle = self._owning_window(confirm)
            rectangle = safe_attr(confirm, "BoundingRectangle")
            if not self._rect_valid(rectangle):
                raise RuntimeError("好友申请的“确定”按钮边界无效，拒绝提交")
            point = self._clickable_point(confirm)
            if (
                point is None
                or not self._point_in_rect(point, rectangle)
                or not self._point_in_rect(point, window_rectangle)
            ):
                point = (
                    (rectangle.left + rectangle.right) // 2,
                    (rectangle.top + rectangle.bottom) // 2,
                )
            if not self._point_in_rect(point, window_rectangle):
                raise RuntimeError("好友申请确认点击点不在申请窗口内，拒绝提交")

            self._prepare_click_window(window_root, confirm, point)
            hit = self._uia.ControlFromPoint(*point)
            current = hit
            hit_matches = False
            for _depth in range(16):
                if current is None:
                    break
                if _control_reference(current) == confirm_reference:
                    hit_matches = True
                    break
                try:
                    parent = current.GetParentControl()
                except _STOP_ERRORS:
                    raise
                except Exception:
                    break
                if parent is current:
                    break
                current = parent
            if not hit_matches:
                raise RuntimeError(
                    "好友申请确认点击点未命中当前“确定”按钮，拒绝提交；"
                    f"hit={describe_control(hit)}"
                )
        except Exception as exc:
            try:
                exc.destructive_triggered = False
            except Exception:
                pass
            raise

        try:
            self._uia.Click(*point)
        except Exception as exc:
            try:
                exc.destructive_triggered = None
            except Exception:
                pass
            raise
        return FriendSubmitReceipt(
            triggered=True,
            method="uia_bounds_click",
            control_reference=confirm_reference,
            point=point,
        )

    def cancel_friend_request(self) -> bool:
        import win32gui

        hwnd = int(self._verify_hwnd or 0)
        if not hwnd:
            return True

        def form_closed() -> bool:
            return not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(
                hwnd
            )

        invoked = False
        try:
            cancel = self._wait_control(
                hwnd=hwnd,
                name=("取消", "关闭"),
                control_type="ButtonControl",
            )
            pattern = cancel.GetInvokePattern()
            if pattern is not None:
                try:
                    result = pattern.Invoke(waitTime=0)
                except TypeError:
                    result = pattern.Invoke()
                invoked = result is not False
        except _STOP_ERRORS:
            raise
        except Exception:
            invoked = False

        if invoked and self._wait_for(
            form_closed,
            min(1.0, self._timeout),
            hwnd=hwnd,
        ):
            self._verify_hwnd = 0
            return True

        # Qt 5 can expose a false-positive InvokePattern on XOutlineButton.
        # Closing the verified top-level request window is non-destructive and
        # is safe after the cancel action failed its explicit postcondition.
        root = self._uia.ControlFromHandle(hwnd) if self._uia is not None else None
        try:
            pattern = root.GetWindowPattern() if root is not None else None
            if pattern is not None:
                result = pattern.Close()
                invoked = result is not False
            else:
                invoked = False
        except _STOP_ERRORS:
            raise
        except Exception:
            invoked = False
        if not invoked:
            return False

        closed = self._wait_for(
            form_closed,
            self._timeout,
            hwnd=hwnd,
        )
        if closed:
            self._verify_hwnd = 0
        return bool(closed)

    def verify_friend_request(self, timeout: float) -> bool | None:
        import win32gui

        submitted_form_hwnd = int(self._verify_hwnd or 0)

        def explicitly_confirmed():
            self._raise_process_risk()
            handles = [self._add_hwnd] if self._add_hwnd else []
            if (
                self._verify_hwnd
                and win32gui.IsWindow(self._verify_hwnd)
                and win32gui.IsWindowVisible(self._verify_hwnd)
            ):
                handles.append(self._verify_hwnd)
            for hwnd in handles:
                self._raise_scoped_risk(hwnd=hwnd)
                if self._find_scoped_controls(
                    hwnd=hwnd,
                    name=FRIEND_SUBMIT_SUCCESS_NAMES,
                    enabled=False,
                ):
                    return True
            # The verified confirmation window is modal.  After the exact
            # hit-tested “确定” click, its destruction/hide while a same-session
            # Weixin owner remains visible is an explicit UI transition, not a
            # timeout guess.  Risk controls are checked above before accepting it.
            if submitted_form_hwnd and (
                not win32gui.IsWindow(submitted_form_hwnd)
                or not win32gui.IsWindowVisible(submitted_form_hwnd)
            ):
                owner_handles = {
                    int(self._add_hwnd or 0),
                    int(safe_attr(self._session, "hwnd", 0) or 0),
                }
                if any(
                    hwnd
                    and win32gui.IsWindow(hwnd)
                    and win32gui.IsWindowVisible(hwnd)
                    for hwnd in owner_handles
                ):
                    return True
            return False

        if self._wait_for(
            explicitly_confirmed,
            timeout,
            hwnd=self._add_hwnd or self._verify_hwnd,
        ):
            self._verify_hwnd = 0
            return True
        return None

    def close(self) -> None:
        cleanup_error: Exception | None = None
        try:
            self._close_session_resources()
        except Exception as exc:
            cleanup_error = exc
        if (
            cleanup_error is None
            and self._uia_initialized
            and self._uia is not None
        ):
            try:
                reset_client = getattr(
                    self._uia, "ResetUIAutomationClientInCurrentThread", None
                )
                if reset_client is not None:
                    reset_client()
                self._uia.UninitializeUIAutomationInCurrentThread()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            else:
                self._uia_initialized = False
                self._uia = None
                self._query = None
        if cleanup_error is not None:
            raise cleanup_error


__all__ = [
    "FriendSubmitReceipt",
    "MessageBubbleSnapshot",
    "NativeWeixinDriver",
    "RiskControlError",
    "SearchCandidate",
    "SearchResultRow",
    "extract_contact_results",
    "extract_search_result_rows",
    "extract_exact_forward_candidates",
    "filter_recent_message_bubbles",
    "find_exact_control",
    "has_new_forward_confirmation",
    "extract_labeled_friend_identities",
    "raise_for_risk_controls",
    "resolve_friend_form_fields",
]
