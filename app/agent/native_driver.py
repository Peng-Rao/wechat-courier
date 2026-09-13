from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from .actions import VerifiedActions
from .gate import NativeGateBackend, WeixinAccessibilitySession
from .profile import UnsupportedWeixinVersion, get_weixin_profile
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
) -> list[tuple[str, Any]]:
    results = []
    for control, _depth in nodes:
        name = str(safe_attr(control, "Name", "")).strip()
        class_name = str(safe_attr(control, "ClassName", ""))
        automation_id = str(safe_attr(control, "AutomationId", ""))
        if not name or "SearchContentCellView" not in class_name:
            continue
        if not automation_id.startswith("search_item_"):
            continue
        if automation_id.startswith("search_item_function"):
            continue
        results.append((name, control))
    return results


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


class NativeWeixinDriver:
    """Exact-profile UIA driver for Weixin 4.1.13.65."""

    def __init__(
        self,
        *,
        gate_backend: Any | None = None,
        timeout: float = 5.0,
    ):
        self._gate_backend = gate_backend or NativeGateBackend()
        self._timeout = timeout
        self._waiter = DeadlineWaiter(0.2)
        self._session: WeixinAccessibilitySession | None = None
        self._uia = None
        self._root = None
        self._search_edit = None
        self._search_results: list[tuple[str, Any]] = []
        self._selected_target = ""
        self._composer = None
        self._add_hwnd = 0
        self._verify_hwnd = 0
        self._friend_account = ""
        self._uia_initialized = False
        self._wake_event = threading.Event()
        self._actions = VerifiedActions(
            waiter=self._waiter,
            click_fallback=self._click_bounds,
            replace_text_fallback=self._replace_text,
            timeout=timeout,
        )

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
                detail = "微信版本已验证"
            except UnsupportedWeixinVersion:
                supported = False
                detail = f"微信 {version} 尚未验证，自动化已禁用"
            return {
                "connected": True,
                "hwnd": hwnd,
                "pid": pid,
                "version": version,
                "supported": supported,
                "detail": detail,
            }
        except Exception as exc:
            return {
                "connected": False,
                "version": "",
                "supported": False,
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
        except Exception:
            self.close()
            raise

    def bind_window(self) -> dict[str, Any]:
        self._ensure_session()
        from src.core.win32 import bring_window_to_front

        bring_window_to_front(self._session.hwnd)
        return {
            "connected": True,
            "hwnd": self._session.hwnd,
            "pid": self._session.pid,
            "version": self._session.version,
            "supported": True,
        }

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

    def _click_bounds(self, control) -> None:
        rectangle = safe_attr(control, "BoundingRectangle")
        if rectangle is None:
            raise RuntimeError("UIA 控件没有可点击边界")
        if rectangle.right <= rectangle.left or rectangle.bottom <= rectangle.top:
            raise RuntimeError("UIA 控件边界为空")
        self._uia.Click(
            (rectangle.left + rectangle.right) // 2,
            (rectangle.top + rectangle.bottom) // 2,
        )

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

    def search_contacts(self, target: str) -> list[str]:
        if not self.ensure_search_ready():
            return []
        self._actions.set_text(self._search_edit, target, wake_event=self._wake_event)
        profile = self._session.profile
        holder = {"matches": []}

        def collect_results():
            nodes = self._all_nodes()
            raise_for_risk_controls(nodes)
            search_list = find_exact_control(
                nodes,
                automation_id=profile.search_list_automation_id,
                enabled=False,
            )
            if search_list is None:
                return False
            try:
                list_nodes = list(
                    self._uia.WalkControl(
                        search_list, includeTop=True, maxDepth=12
                    )
                )
            except Exception:
                return False
            holder["matches"] = extract_contact_results(list_nodes)
            return bool(holder["matches"])

        self._waiter.wait(collect_results, self._timeout, self._wake_event)
        self._search_results = holder["matches"]
        return [name for name, _control in self._search_results]

    def select_search_result(self, candidate: str) -> None:
        normalized = normalize_identity(candidate)
        controls = [
            control
            for name, control in self._search_results
            if normalize_identity(name) == normalized
        ]
        if len(controls) != 1:
            raise RuntimeError("无法解析唯一搜索结果控件")
        self._selected_target = candidate
        self._actions.select(
            controls[0],
            lambda: self.composer_ready()
            and normalize_identity(self.current_chat_title()) == normalized,
            wake_event=self._wake_event,
        )

    def current_chat_title(self) -> str:
        if not self._selected_target:
            return ""
        _root, nodes = self._walk(self._session.hwnd)
        root_rect = safe_attr(self._root, "BoundingRectangle")
        expected = normalize_identity(self._selected_target)
        for control, _depth in nodes:
            if normalize_identity(str(safe_attr(control, "Name", ""))) != expected:
                continue
            if control in [item for _name, item in self._search_results]:
                continue
            rectangle = safe_attr(control, "BoundingRectangle")
            if root_rect is None or rectangle is None:
                continue
            right_pane = rectangle.left >= root_rect.left + root_rect.width() * 0.25
            near_top = rectangle.top <= root_rect.top + root_rect.height() * 0.25
            if right_pane and near_top:
                return str(safe_attr(control, "Name", "")).strip()
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

    def read_composer_text(self) -> str:
        if self._composer is None and not self.composer_ready():
            return ""
        return self._actions.read_text(self._composer) or ""

    @staticmethod
    def _control_key(control) -> tuple:
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

    def message_snapshot(self) -> set[tuple]:
        return {self._control_key(control) for control in self._message_controls()}

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
            current = {self._control_key(control) for control in controls}
            has_new_match = any(
                normalize_identity(str(safe_attr(control, "Name", "")))
                == normalize_identity(expected)
                and self._control_key(control) not in before
                for control in controls
            )
            return has_new_match and self.read_composer_text() == ""

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

    def forward_bundle(
        self, target: str, message: str, paths: Sequence[str]
    ) -> dict[str, str]:
        # The caller treats this as one destructive boundary. Never retry here.
        results = self.send_files(paths)
        if any(result["outcome"] != "success" for result in results):
            return {"outcome": "unknown", "detail": "合并内容中的附件结果未知"}
        if message:
            before = self.message_snapshot()
            self.set_composer_text(message)
            self.trigger_send()
            if not self.verify_sent(before, message, self._timeout):
                return {"outcome": "unknown", "detail": "留言结果未知"}
        return {"outcome": "success", "detail": "内容已发送"}

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
        return {"account": account, "control": button}

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

        def closed():
            if not self._verify_hwnd or not win32gui.IsWindow(self._verify_hwnd):
                return True
            if not win32gui.IsWindowVisible(self._verify_hwnd):
                return True
            raise_for_risk_controls(self._walk(self._verify_hwnd)[1])
            return False

        if self._waiter.wait(closed, timeout, self._wake_event):
            self._verify_hwnd = 0
            return True
        return None

    def close(self) -> None:
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
    "extract_contact_results",
    "find_exact_control",
    "raise_for_risk_controls",
    "resolve_friend_form_fields",
]
