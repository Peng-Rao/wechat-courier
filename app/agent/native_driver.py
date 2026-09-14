from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .actions import VerifiedActions, describe_control
from .gate import NativeGateBackend, WeixinAccessibilitySession
from .profile import UnsupportedWeixinVersion, get_weixin_profile
from .uia_events import subscribe_uia_events
from .waiters import DeadlineWaiter
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


@dataclass(frozen=True)
class SearchCandidate:
    """Immutable search-row description; deliberately contains no UIA wrapper."""

    display_name: str
    identities: frozenset[str]
    result_type: str
    automation_id: str
    row_index: int
    row_depth: int
    runtime_id: tuple[int, ...] = ()


def _runtime_id(control: Any) -> tuple[int, ...]:
    try:
        value = control.GetRuntimeId()
    except Exception:
        value = safe_attr(control, "RuntimeId", ())
    try:
        return tuple(int(part) for part in value)
    except (TypeError, ValueError):
        return ()


def _search_row_kind(control: Any) -> str | None:
    name = str(safe_attr(control, "Name", "")).strip()
    class_name = str(safe_attr(control, "ClassName", ""))
    automation_id = str(safe_attr(control, "AutomationId", ""))
    if not name or "SearchContentCellView" not in class_name:
        return None
    if not automation_id.startswith("search_item_"):
        return None
    lowered_id = automation_id.casefold()
    if "web" in lowered_id or "network" in lowered_id:
        return None
    if name in {"搜索网络结果", "网络搜索", "搜一搜"}:
        return None
    if automation_id.startswith("search_item_function"):
        return "function" if name == "文件传输助手" else None
    return "contact"


def safe_attr(control: Any, name: str, default=None):
    if control is None:
        return default
    try:
        value = getattr(control, name)
    except Exception:
        return default
    return default if value is None else value


def find_exact_control(
    nodes: Iterable[tuple[Any, int]],
    *,
    name: str | Sequence[str] | None = None,
    control_type: str | None = None,
    class_name: str | None = None,
    automation_id: str | None = None,
    enabled: bool = True,
):
    accepted_names = None
    if isinstance(name, str):
        accepted_names = {name.strip()}
    elif name is not None:
        accepted_names = {item.strip() for item in name}
    for control, _depth in nodes:
        if accepted_names is not None:
            if str(safe_attr(control, "Name", "")).strip() not in accepted_names:
                continue
        if control_type is not None:
            if str(safe_attr(control, "ControlTypeName", "")) != control_type:
                continue
        if class_name is not None:
            if str(safe_attr(control, "ClassName", "")) != class_name:
                continue
        if automation_id is not None:
            if str(safe_attr(control, "AutomationId", "")) != automation_id:
                continue
        if enabled and not bool(safe_attr(control, "IsEnabled", False)):
            continue
        return control
    return None


def extract_contact_results(
    nodes: Iterable[tuple[Any, int]],
) -> list[SearchCandidate]:
    materialized = list(nodes)
    results: list[SearchCandidate] = []
    row_index = 0
    for index, (control, depth) in enumerate(materialized):
        name = str(safe_attr(control, "Name", "")).strip()
        automation_id = str(safe_attr(control, "AutomationId", ""))
        result_type = _search_row_kind(control)
        if result_type is None:
            continue
        is_function = result_type == "function"
        identities: dict[str, str] = {}
        identities.setdefault(normalize_identity(name), name)
        if not is_function:
            for child, child_depth in materialized[index + 1 :]:
                if child_depth <= depth:
                    break
                child_name = str(safe_attr(child, "Name", "")).strip()
                if child_name:
                    identities.setdefault(normalize_identity(child_name), child_name)
        values = frozenset(value for key, value in identities.items() if key)
        results.append(
            SearchCandidate(
                display_name=name,
                identities=(frozenset({"文件传输助手"}) if is_function else values),
                result_type=result_type,
                automation_id=automation_id,
                row_index=row_index,
                row_depth=depth,
                runtime_id=_runtime_id(control),
            )
        )
        row_index += 1
    return results


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
        if normalize_identity(str(safe_attr(control, "Name", ""))) != expected:
            continue
        key = (
            str(safe_attr(control, "AutomationId", "")),
            str(safe_attr(control, "ClassName", "")),
            str(safe_attr(control, "Name", "")),
        )
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


def has_new_forward_confirmation(
    controls: Iterable[Any], before: set[tuple]
) -> bool:
    for control in controls:
        if control_key(control) in before:
            continue
        class_name = str(safe_attr(control, "ClassName", ""))
        if "Chat" not in class_name and "Message" not in class_name:
            continue
        text = str(safe_attr(control, "Name", "")).strip()
        if any(keyword in text for keyword in FORWARD_CONFIRMATION_KEYWORDS):
            return True
    return False


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


class NativeWeixinDriver:
    """Exact-profile UIA driver for Weixin 4.1.13.65."""

    def __init__(
        self,
        *,
        gate_backend: Any | None = None,
        timeout: float = 5.0,
        sleep=time.sleep,
    ):
        self._gate_backend = gate_backend or NativeGateBackend()
        self._timeout = timeout
        self._sleep = sleep
        self._waiter = DeadlineWaiter(0.2)
        self._session: WeixinAccessibilitySession | None = None
        self._uia = None
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
        self._uia_initialized = False
        self._wake_event = threading.Event()
        self._event_subscription = None
        self._actions = VerifiedActions(
            waiter=self._waiter,
            click_fallback=self._click_bounds,
            replace_text_fallback=self._replace_text,
            timeout=timeout,
        )

    def restart_wechat(self, timeout: int, emit) -> dict[str, Any]:
        inspection = self.inspect()
        if not inspection.get("connected") or not inspection.get("pid"):
            raise RuntimeError("无法定位要重启的微信进程")
        pid = int(inspection["pid"])
        executable = self._gate_backend.process_path(pid)
        self.close()
        self._gate_backend.terminate_process(pid)
        self._gate_backend.start_process(executable)

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
            remaining = max(0, int(deadline - time.monotonic()))
            emit(
                "agent.status",
                {"status": "waiting_login", "remaining": remaining},
            )
            self._sleep(1.0)
        raise TimeoutError("等待微信重新登录超时")

    def inspect(self) -> dict[str, Any]:
        try:
            hwnd = int(self._gate_backend.find_main_window() or 0)
            if not hwnd:
                return {
                    "connected": False,
                    "version": "",
                    "supported": False,
                    "detail": "未找到已登录的微信窗口",
                }
            pid = int(self._gate_backend.get_window_pid(hwnd))
            module = self._gate_backend.find_module(pid, "Weixin.dll")
            version = str(self._gate_backend.file_version(module.path))
            try:
                get_weixin_profile(version)
                supported = True
                detail = "微信版本已验证，正在检查 UIA 控件树"
            except UnsupportedWeixinVersion:
                supported = False
                detail = f"微信 {version} 尚未验证，自动化已禁用"
            result = {
                "connected": True,
                "hwnd": hwnd,
                "pid": pid,
                "version": version,
                "supported": supported,
                "uiaReady": False,
                "detail": detail,
            }
            if not supported:
                return result
            try:
                self._ensure_session()
            except Exception as exc:
                result["detail"] = f"微信版本已验证，但 UIA 未就绪：{exc}"
                return result
            result["uiaReady"] = True
            result["detail"] = "微信版本与 UIA 控件树均已验证"
            return result
        except Exception as exc:
            return {
                "connected": False,
                "version": "",
                "supported": False,
                "uiaReady": False,
                "detail": str(exc),
            }

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if os.name != "nt":
            raise RuntimeError("Weixin automation is only available on Windows")
        from src.core import uiautomation as uia

        uia.InitializeUIAutomationInCurrentThread()
        self._uia_initialized = True
        try:
            session = WeixinAccessibilitySession(self._gate_backend)
            session.__enter__()
            self._session = session
            self._uia = uia
            self._root = uia.ControlFromHandle(session.hwnd)
            if self._root is None:
                raise RuntimeError("无法从微信句柄建立 UIA 根控件")
            if not self._waiter.wait(self._tree_materialized, self._timeout):
                raise RuntimeError("微信 UIA 控件树未就绪，请重启微信后重试")
            try:
                self._event_subscription = subscribe_uia_events(
                    self._uia, self._root, self._wake_event
                )
            except Exception:
                self._event_subscription = None
        except Exception:
            self.close()
            raise

    def bind_window(self) -> dict[str, Any]:
        from src.core.win32 import bring_window_to_front

        failures = []
        for attempt in range(2):
            try:
                self._ensure_session()
            except Exception as exc:
                if not self._bind_retry_is_safe(exc):
                    raise
                failures.append(self._bind_failure_detail("initialize", exc))
                if attempt == 0:
                    self.close()
                    continue
                raise RuntimeError(
                    "bind_window failed after one cleanup and rediscovery: "
                    + "; ".join(failures)
                ) from exc

            hwnd = self._session.hwnd
            try:
                activated = bool(bring_window_to_front(hwnd))
                visible_root = activated and self._waiter.wait(
                    self._visible_root_bounds,
                    self._timeout,
                    self._wake_event,
                )
            except Exception as exc:
                if not self._bind_retry_is_safe(exc):
                    raise
                failures.append(self._bind_failure_detail("activate", exc))
                if attempt == 0:
                    self.close()
                    continue
                raise RuntimeError(
                    "bind_window failed after one cleanup and rediscovery: "
                    + "; ".join(failures)
                ) from exc
            if visible_root:
                return {
                    "connected": True,
                    "hwnd": hwnd,
                    "pid": self._session.pid,
                    "version": self._session.version,
                    "supported": True,
                }
            failures.append(
                self._bind_failure_detail(
                    "activate",
                    RuntimeError(
                        f"activation={activated}, rootVisible={bool(visible_root)}"
                    ),
                )
            )
            if attempt == 0:
                self.close()
        raise RuntimeError(
            "微信窗口恢复/置前或可见根边界校验失败；已重新发现句柄并重绑一次："
            + "; ".join(failures)
        )

    @staticmethod
    def _bind_retry_is_safe(exc: Exception) -> bool:
        if isinstance(exc, UnsupportedWeixinVersion):
            return False
        detail = str(exc).casefold()
        unsafe_markers = (
            "gate",
            "rva",
            "pe section",
            "screen-reader",
            "screen reader",
            "refusing to write",
            "restore",
        )
        return not any(marker in detail for marker in unsafe_markers)

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
            root, _nodes = self._walk(self._session.hwnd)
            rectangle = safe_attr(root, "BoundingRectangle")
            if bool(safe_attr(root, "IsOffscreen", False)):
                return False
            if not self._rect_valid(rectangle):
                return False
            self._root = root
            return True
        except Exception:
            return False

    def _tree_materialized(self) -> bool:
        try:
            root, nodes = self._walk(self._session.hwnd)
            self._root = root
            profile = self._session.profile
            return (
                str(safe_attr(root, "ClassName", "")) == profile.main_root_class
                and len(nodes) >= 5
                and any(
                    str(safe_attr(control, "ClassName", "")).startswith("mmui::")
                    for control, _depth in nodes
                )
            )
        except Exception:
            return False

    def _walk(self, hwnd: int | None = None):
        if self._uia is None:
            raise RuntimeError("UIA is not initialized")
        root = self._root if hwnd is None else self._uia.ControlFromHandle(hwnd)
        nodes = (
            list(self._uia.WalkControl(root, includeTop=True, maxDepth=40))
            if root is not None
            else []
        )
        return root, nodes

    def _process_window(self, accepted_classes: Sequence[str]) -> int:
        import win32gui
        import win32process

        found = []

        def collect(hwnd, _extra):
            try:
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid != self._session.pid or not win32gui.IsWindowVisible(hwnd):
                    return True
                root = self._uia.ControlFromHandle(hwnd)
                if str(safe_attr(root, "ClassName", "")) in accepted_classes:
                    found.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(collect, None)
        return int(found[0]) if found else 0

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
            except Exception:
                pass
        return nodes

    def _wait_control(self, *, hwnd: int | None = None, **selector):
        holder = {"control": None}

        def locate():
            _root, nodes = self._walk(hwnd or self._session.hwnd)
            raise_for_risk_controls(nodes)
            holder["control"] = find_exact_control(nodes, **selector)
            return holder["control"] is not None

        if not self._waiter.wait(locate, self._timeout, self._wake_event):
            description = ", ".join(
                f"{key}={value!r}" for key, value in selector.items()
            )
            raise RuntimeError(f"UIA 控件未出现：{description}")
        return holder["control"]

    @staticmethod
    def _rect_valid(rectangle: Any) -> bool:
        try:
            return (
                rectangle is not None
                and rectangle.right > rectangle.left
                and rectangle.bottom > rectangle.top
            )
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
                except Exception:
                    return None
            try:
                return int(value[0]), int(value[1])
            except (TypeError, ValueError):
                return None
        try:
            return int(value.x), int(value.y)
        except Exception:
            return None

    def _click_bounds(self, control) -> None:
        if not bool(safe_attr(control, "IsEnabled", False)):
            raise RuntimeError("UIA 控件未启用")
        if bool(safe_attr(control, "IsOffscreen", True)):
            raise RuntimeError("UIA 控件不可见")
        window_root, window_rectangle = self._owning_window(control)
        row_rectangle = safe_attr(control, "BoundingRectangle")

        point = self._clickable_point(control)
        if point is not None and self._point_in_rect(point, window_rectangle):
            if not self._rect_valid(row_rectangle) or self._point_in_rect(
                point, row_rectangle
            ):
                self._uia.Click(*point)
                return

        if self._rect_valid(row_rectangle):
            point = (
                (row_rectangle.left + row_rectangle.right) // 2,
                (row_rectangle.top + row_rectangle.bottom) // 2,
            )
            if self._point_in_rect(point, window_rectangle):
                self._uia.Click(*point)
                return

        try:
            descendants = self._uia.WalkControl(
                control, includeTop=False, maxDepth=12
            )
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
            self._uia.Click(*point)
            return
        raise RuntimeError("UIA 控件及其候选子树没有安全的可点击点")

    def _owning_window(self, control) -> tuple[Any, Any]:
        try:
            window_root = control.GetTopLevelControl()
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

        self._click_bounds(control)
        control.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
        if not set_text_to_clipboard(value):
            raise RuntimeError("写入剪贴板失败")
        control.SendKeys("{Ctrl}v", waitTime=0.05)

    def ensure_search_ready(self) -> bool:
        self._ensure_session()
        profile = self._session.profile

        def find_search():
            _root, nodes = self._walk(self._session.hwnd)
            self._search_edit = find_exact_control(
                nodes,
                name=profile.search_edit_name,
                control_type="EditControl",
                class_name=profile.search_edit_class,
            )
            return self._search_edit is not None

        if find_search():
            return True
        try:
            self._root.SendKeys("{Ctrl}f", waitTime=0.05)
        except Exception:
            return False
        return self._waiter.wait(find_search, self._timeout, self._wake_event)

    @staticmethod
    def _candidate_signature(candidates: Sequence[SearchCandidate]) -> tuple:
        return tuple(
            (
                candidate.automation_id,
                candidate.row_index,
                tuple(sorted(normalize_identity(value) for value in candidate.identities)),
                candidate.runtime_id,
            )
            for candidate in candidates
        )

    def _search_rows(self) -> tuple[list[SearchCandidate], list[Any]] | None:
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
        except Exception:
            return None
        candidates = extract_contact_results(list_nodes)
        rows = [control for control, _depth in list_nodes if _search_row_kind(control)]
        return candidates, rows

    def search_contacts(self, target: str) -> list[SearchCandidate]:
        if not self.ensure_search_ready():
            return []

        initial = self._search_rows()
        initial_signature = self._candidate_signature(initial[0]) if initial else ()
        self._search_results = []
        self._search_query = ""
        self._actions.set_text(self._search_edit, "", wake_event=self._wake_event)

        refresh_state = {"cleared": False}

        def cleared_results_refreshed() -> bool:
            if self._actions.read_text(self._search_edit) != "":
                return False
            current = self._search_rows()
            if current is None:
                refresh_state["cleared"] = True
                return True
            refreshed = (
                not initial_signature
                or self._candidate_signature(current[0]) != initial_signature
            )
            if refreshed:
                refresh_state["cleared"] = True
            return refreshed

        if not self._waiter.wait(
            cleared_results_refreshed, self._timeout, self._wake_event
        ):
            raise RuntimeError("清空搜索词后结果列表未刷新")

        self._actions.set_text(self._search_edit, target, wake_event=self._wake_event)
        holder: dict[str, Any] = {
            "matches": [],
            "signature": None,
            "stable": 0,
            "last_state_valid": False,
        }

        def reset_stability() -> None:
            holder["signature"] = None
            holder["stable"] = 0
            holder["last_state_valid"] = False

        def collect_results():
            if self._actions.read_text(self._search_edit) != target:
                reset_stability()
                return False
            current = self._search_rows()
            if current is None:
                reset_stability()
                return False
            candidates, _rows = current
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
                return False
            return refresh_state["cleared"] and holder["stable"] >= 2

        if not self._waiter.wait(collect_results, self._timeout, self._wake_event):
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
        current = self._search_rows()
        if current is None:
            return None
        candidates, controls = current
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
            if current_candidate == candidate
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
        return controls[index] if index < len(controls) else None

    def select_search_result(self, candidate: SearchCandidate) -> None:
        if not isinstance(candidate, SearchCandidate):
            raise TypeError("select_search_result requires SearchCandidate")
        control = self._resolve_search_candidate(candidate)
        if control is None:
            raise RuntimeError("无法解析唯一搜索结果控件")
        self._selected_target = self._search_query or candidate.display_name
        self._selected_identities = candidate.identities

        def selected_chat_verified() -> bool:
            title = normalize_identity(self.current_chat_title())
            return bool(title) and any(
                normalize_identity(identity) == title
                for identity in candidate.identities
            )

        self._actions.select(
            control,
            lambda: self.composer_ready()
            and selected_chat_verified(),
            resolve_control=lambda: self._resolve_search_candidate(candidate),
            extra_postcondition=lambda: self.composer_ready(),
            wake_event=self._wake_event,
        )

    def current_chat_title(self) -> str:
        if not self._selected_target:
            return ""
        if self._find_composer() is None:
            return ""
        _root, nodes = self._walk(self._session.hwnd)
        root_rect = safe_attr(self._root, "BoundingRectangle")
        accepted_identities = {
            normalize_identity(identity)
            for identity in (
                self._selected_identities or frozenset({self._selected_target})
            )
        }
        title_container_depth: int | None = None
        for control, depth in nodes:
            class_name = str(safe_attr(control, "ClassName", ""))
            if title_container_depth is not None and depth <= title_container_depth:
                title_container_depth = None
            if class_name == CHAT_TITLE_CONTAINER_CLASS:
                title_container_depth = depth
                continue
            if title_container_depth is None:
                continue
            if class_name != CHAT_TITLE_CONTROL_CLASS:
                continue
            if (
                str(safe_attr(control, "AutomationId", ""))
                != CHAT_TITLE_AUTOMATION_ID
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
        _root, nodes = self._walk(self._session.hwnd)
        return find_exact_control(
            nodes,
            control_type="EditControl",
            class_name=profile.chat_input_class,
            automation_id=profile.chat_input_automation_id,
        )

    def composer_ready(self) -> bool:
        try:
            self._composer = self._find_composer()
            return self._composer is not None
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
        except Exception:
            return None
        self._composer = composer
        try:
            return self._actions.read_text(composer)
        except Exception:
            return None

    @staticmethod
    def _control_key(control) -> tuple:
        return control_key(control)

    def _message_controls(self) -> list[Any]:
        _root, nodes = self._walk(self._session.hwnd)
        composer_rect = safe_attr(self._find_composer(), "BoundingRectangle")
        controls = []
        for control, _depth in nodes:
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
        runtime_id = _runtime_id(control)
        if runtime_id:
            stable_id: tuple = ("runtime", runtime_id)
        else:
            stable_id = ("fallback", control_key(control))
        return stable_id, str(safe_attr(control, "Name", "")).strip()

    def message_snapshot(self) -> tuple[tuple, ...]:
        return tuple(
            self._message_identity(control) for control in self._message_controls()
        )

    def _invoke_once_or_key(self, button_names: Sequence[str], key_control) -> str:
        _root, nodes = self._walk(self._session.hwnd)
        button = find_exact_control(
            nodes,
            name=button_names,
            control_type="ButtonControl",
        )
        if button is not None:
            try:
                pattern = button.GetInvokePattern()
            except Exception:
                pattern = None
            if pattern is not None:
                try:
                    result = pattern.Invoke(waitTime=0)
                except TypeError:
                    result = pattern.Invoke()
                if result is False:
                    raise RuntimeError("发送按钮 InvokePattern 返回失败")
                return "invoke_pattern"
            self._click_bounds(button)
            return "uia_bounds_click"
        key_control.SendKeys("{Enter}", waitTime=0.05)
        return "keyboard_fallback"

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

        if self._waiter.wait(appended, timeout, self._wake_event):
            return True
        raise_for_risk_controls(self._all_nodes())
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
            before = self.message_snapshot()
            if not set_files_to_clipboard([path]):
                results.append(
                    {"path": path, "outcome": "error", "detail": "剪贴板写入失败"}
                )
                continue
            self._click_bounds(self._composer)
            self._composer.SendKeys("{Ctrl}v", waitTime=0.1)
            self._invoke_once_or_key(("发送", "发送(S)"), self._composer)
            verified = self.verify_sent(before, Path(path).name, self._timeout)
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

    def _find_all_control(self, **selector):
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        return find_exact_control(nodes, **selector)

    def _wait_all_control(self, **selector):
        holder = {"control": None}

        def locate():
            holder["control"] = self._find_all_control(**selector)
            return holder["control"] is not None

        if not self._waiter.wait(locate, self._timeout, self._wake_event):
            raise RuntimeError(f"转发控件未出现：{selector}")
        return holder["control"]

    def _recent_message_bubbles(self, count: int) -> list[Any]:
        profile = self._session.profile
        message_list = self._wait_control(
            automation_id=profile.chat_message_list_automation_id,
            enabled=False,
        )
        nodes = list(
            self._uia.WalkControl(message_list, includeTop=False, maxDepth=5)
        )
        bubbles = filter_recent_message_bubbles(
            nodes, profile.chat_message_classes, count
        )
        if len(bubbles) != count:
            raise RuntimeError(f"源消息不足：需要 {count} 条，找到 {len(bubbles)} 条")
        return bubbles

    def _right_click_bounds(self, control) -> None:
        rectangle = safe_attr(control, "BoundingRectangle")
        if rectangle is None or rectangle.right <= rectangle.left:
            raise RuntimeError("消息气泡没有可用边界")
        self._uia.RightClick(
            (rectangle.left + rectangle.right) // 2,
            (rectangle.top + rectangle.bottom) // 2,
        )

    @staticmethod
    def _selection_state(control) -> bool:
        for getter, attribute in (
            ("GetSelectionItemPattern", "IsSelected"),
            ("GetTogglePattern", "ToggleState"),
        ):
            try:
                pattern = getattr(control, getter)()
                value = getattr(pattern, attribute)
                return bool(value)
            except Exception:
                continue
        return False

    def _select_forward_bubble(self, control) -> None:
        if self._selection_state(control):
            return
        self._actions.select(
            control,
            lambda: self._selection_state(control),
            wake_event=self._wake_event,
        )

    def _forward_search_edit(self):
        profile = self._session.profile
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        for automation_id in profile.forward_search_automation_ids:
            control = find_exact_control(
                nodes,
                control_type="EditControl",
                automation_id=automation_id,
            )
            if control is not None:
                return control
        return find_exact_control(
            nodes,
            name=("搜索", "查找"),
            control_type="EditControl",
        )

    def _forward_candidate(self, target: str):
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        candidates = extract_exact_forward_candidates(nodes, target)
        if len(candidates) != 1:
            raise RuntimeError(f"转发目标不唯一或未找到：{target}")
        return candidates[0]

    def _forward_recipient_selected(self, target: str, search_edit) -> bool:
        if self._selection_state(self._forward_candidate(target)):
            return True
        return (self._actions.read_text(search_edit) or "") == ""

    def _forward_message_edit(self, search_edit):
        nodes = self._all_nodes()
        raise_for_risk_controls(nodes)
        for control, _depth in nodes:
            if control is search_edit:
                continue
            if str(safe_attr(control, "ControlTypeName", "")) != "EditControl":
                continue
            name = str(safe_attr(control, "Name", "")).strip()
            if name in {"留言", "附言", "给朋友留言"}:
                return control
        return None

    def _invoke_once(self, control) -> str:
        try:
            pattern = control.GetInvokePattern()
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

        target_snapshot = {
            control_key(control) for control in self._message_controls()
        }
        self._open_exact_chat("文件传输助手")
        bubbles = self._recent_message_bubbles(count)
        self._right_click_bounds(bubbles[-1])
        multi = self._wait_all_control(
            name=("多选", "选择多条", "多选消息"),
        )
        self._actions.invoke(
            multi,
            lambda: self._find_all_control(name=("转发",)) is not None,
            wake_event=self._wake_event,
        )

        bubbles = self._recent_message_bubbles(count)
        for bubble in bubbles:
            self._select_forward_bubble(bubble)

        forward = self._wait_all_control(name="转发")
        self._actions.invoke(
            forward,
            lambda: self._find_all_control(
                name=("合并转发", "合并发送")
            )
            is not None,
            wake_event=self._wake_event,
        )
        merge = self._wait_all_control(name=("合并转发", "合并发送"))
        self._actions.invoke(
            merge,
            lambda: self._forward_search_edit() is not None,
            wake_event=self._wake_event,
        )

        search_edit = self._forward_search_edit()
        if search_edit is None:
            raise RuntimeError("转发搜索框未出现")
        self._actions.set_text(search_edit, target, wake_event=self._wake_event)
        candidate = self._forward_candidate(target)
        self._actions.select(
            candidate,
            lambda: self._forward_recipient_selected(target, search_edit),
            wake_event=self._wake_event,
        )

        if message:
            message_edit = self._forward_message_edit(search_edit)
            if message_edit is None:
                raise RuntimeError("转发留言输入框未暴露到 UIA")
            self._actions.set_text(
                message_edit, message, wake_event=self._wake_event
            )

        send = self._wait_all_control(
            name=("发送", "确定"),
            control_type="ButtonControl",
        )
        self._invoke_once(send)

        self._open_exact_chat(target)
        appended = self._waiter.wait(
            lambda: has_new_forward_confirmation(
                self._message_controls(), target_snapshot
            ),
            self._timeout,
            self._wake_event,
        )
        if not appended:
            raise_for_risk_controls(self._all_nodes())
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
    ) -> None:
        control = self._wait_control(hwnd=hwnd, name=names)
        control_type = str(safe_attr(control, "ControlTypeName", ""))
        if control_type not in INTERACTIVE_CONTROL_TYPES:
            raise RuntimeError(f"控件不可交互：{names[0]}")
        self._actions.invoke(
            control, postcondition, wake_event=self._wake_event
        )

    def open_add_friend(self) -> bool:
        self._ensure_session()
        profile = self._session.profile
        existing = self._process_window((profile.add_friend_root_class,))
        if existing:
            self._add_hwnd = existing
            return True
        main_hwnd = self._session.hwnd
        self._activate_navigation(
            main_hwnd,
            ("微信",),
            lambda: find_exact_control(
                self._walk(main_hwnd)[1], name="快捷操作"
            )
            is not None,
        )
        self._activate_navigation(
            main_hwnd,
            ("快捷操作",),
            lambda: find_exact_control(
                self._walk(main_hwnd)[1], name="添加朋友"
            )
            is not None,
        )
        self._activate_navigation(
            main_hwnd,
            ("添加朋友",),
            lambda: bool(self._process_window((profile.add_friend_root_class,))),
        )
        self._add_hwnd = self._process_window((profile.add_friend_root_class,))
        return bool(self._add_hwnd)

    def set_friend_account(self, account: str) -> str:
        search = self._wait_control(
            hwnd=self._add_hwnd,
            name=("搜索", "微信号/手机号"),
            control_type="EditControl",
        )
        self._friend_account = account
        method = self._actions.set_text(
            search, account, wake_event=self._wake_event
        ).method
        self._friend_search = search
        return method

    def search_friend(self, account: str) -> dict[str, str] | None:
        self._friend_search.SendKeys("{Enter}", waitTime=0.05)
        try:
            button = self._wait_control(
                hwnd=self._add_hwnd,
                name="添加到通讯录",
            )
        except RuntimeError:
            raise_for_risk_controls(self._walk(self._add_hwnd)[1])
            return None
        _root, nodes = self._walk(self._add_hwnd)
        raise_for_risk_controls(nodes)
        identities = extract_labeled_friend_identities(nodes)
        verified_account = identities[0] if len(identities) == 1 else ""
        return {"account": verified_account, "control": button}

    @staticmethod
    def profile_account(profile: dict[str, Any]) -> str:
        return str(profile.get("account", ""))

    def open_friend_request(self, profile: dict[str, Any]) -> bool:
        expected_classes = (self._session.profile.verify_friend_root_class,)
        self._actions.invoke(
            profile["control"],
            lambda: bool(self._process_window(expected_classes)),
            wake_event=self._wake_event,
        )
        self._verify_hwnd = self._process_window(expected_classes)
        return bool(self._verify_hwnd)

    def set_friend_fields(
        self, greeting: str | None, remark: str
    ) -> dict[str, str]:
        _root, nodes = self._walk(self._verify_hwnd)
        raise_for_risk_controls(nodes)
        greeting_edit, remark_edit = resolve_friend_form_fields(nodes)
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

    def submit_friend_request(self) -> str:
        confirm = self._wait_control(
            hwnd=self._verify_hwnd,
            name="确定",
            control_type="ButtonControl",
        )
        try:
            pattern = confirm.GetInvokePattern()
        except Exception:
            pattern = None
        if pattern is not None:
            try:
                result = pattern.Invoke(waitTime=0)
            except TypeError:
                result = pattern.Invoke()
            if result is False:
                raise RuntimeError("好友申请 InvokePattern 返回失败")
            return "invoke_pattern"
        self._click_bounds(confirm)
        return "uia_bounds_click"

    def verify_friend_request(self, timeout: float) -> bool | None:
        import win32gui

        def explicitly_confirmed():
            global_nodes = list(self._all_nodes())
            raise_for_risk_controls(global_nodes)
            status_nodes: list[tuple[Any, int]] = []
            if self._add_hwnd:
                status_nodes.extend(self._walk(self._add_hwnd)[1])
            if (
                self._verify_hwnd
                and win32gui.IsWindow(self._verify_hwnd)
                and win32gui.IsWindowVisible(self._verify_hwnd)
            ):
                status_nodes.extend(self._walk(self._verify_hwnd)[1])
            raise_for_risk_controls(status_nodes)
            return any(
                str(safe_attr(control, "Name", "")).strip()
                in FRIEND_SUBMIT_SUCCESS_NAMES
                for control, _depth in status_nodes
            )

        if self._waiter.wait(
            explicitly_confirmed, timeout, self._wake_event
        ):
            self._verify_hwnd = 0
            return True
        return None

    def close(self) -> None:
        subscription = self._event_subscription
        self._event_subscription = None
        if subscription is not None:
            subscription.close()
        session = self._session
        self._session = None
        if session is not None:
            session.close()
        if self._uia_initialized and self._uia is not None:
            try:
                self._uia.UninitializeUIAutomationInCurrentThread()
            finally:
                self._uia_initialized = False
                self._uia = None


__all__ = [
    "NativeWeixinDriver",
    "RiskControlError",
    "SearchCandidate",
    "extract_contact_results",
    "extract_exact_forward_candidates",
    "filter_recent_message_bubbles",
    "find_exact_control",
    "has_new_forward_confirmation",
    "extract_labeled_friend_identities",
    "raise_for_risk_controls",
    "resolve_friend_form_fields",
]
