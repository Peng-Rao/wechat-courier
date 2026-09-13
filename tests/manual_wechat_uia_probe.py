# -*- coding: utf-8 -*-
"""Manual integration probe for the Weixin 4.1.13.65 add-friend UIA path.

This script writes one verified runtime accessibility gate byte. With a
Weixin ID it can search for a person and prepare the complete friend-request
form. It never submits the request unless ``--submit`` is explicitly passed.

Run from the repository root:

    python tests/manual_wechat_uia_probe.py --navigate-add-friend
    python tests/manual_wechat_uia_probe.py --wechat-id ID \
        --remark REMARK --greeting GREETING
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SUPPORTED_GATE_RVAS = {
    "4.1.13.65": 0x0AE2B0C8,
}

INTERACTIVE_CONTROL_TYPES = {
    "ButtonControl",
    "CustomControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
}

FRIEND_REQUEST_TITLES = ("申请添加朋友", "发送添加朋友申请")
FRIEND_REQUEST_GREETING_NAMES = ("发送添加朋友申请",)
FRIEND_REQUEST_REMARK_NAMES = ("修改备注",)

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IMAGE_SCN_MEM_WRITE = 0x80000000
MAX_MODULE_NAME32 = 255
MAX_PATH = 260


class GateResolutionError(RuntimeError):
    """Raised when the running Weixin build has no verified gate address."""


class ProbeError(RuntimeError):
    """Raised when a live integration probe cannot safely continue."""


def resolve_gate_rva(version: str) -> int:
    """Return a verified accessibility gate RVA for an exact Weixin version."""
    try:
        return SUPPORTED_GATE_RVAS[version]
    except KeyError as exc:
        raise GateResolutionError(
            f"unsupported Weixin version: {version}; refusing to guess a gate RVA"
        ) from exc


def _safe_attr(control, name: str, default=None):
    if control is None:
        return default
    try:
        value = getattr(control, name)
    except Exception:
        return default
    return default if value is None else value


def find_named_control(
    nodes: Iterable[tuple[object, int]],
    accepted_names: Sequence[str],
):
    """Find an enabled interactive control whose stripped name is exact."""
    accepted = {name.strip() for name in accepted_names}
    for control, _depth in nodes:
        if str(_safe_attr(control, "Name", "")).strip() not in accepted:
            continue
        if str(_safe_attr(control, "ControlTypeName", "")) not in INTERACTIVE_CONTROL_TYPES:
            continue
        if not bool(_safe_attr(control, "IsEnabled", False)):
            continue
        return control
    return None


def _find_named_edit(
    nodes: Iterable[tuple[object, int]],
    accepted_names: Sequence[str],
):
    accepted = {name.strip() for name in accepted_names}
    for control, _depth in nodes:
        if str(_safe_attr(control, "Name", "")).strip() not in accepted:
            continue
        if str(_safe_attr(control, "ControlTypeName", "")) != "EditControl":
            continue
        if not bool(_safe_attr(control, "IsEnabled", False)):
            continue
        return control
    return None


def resolve_friend_form_fields(nodes: Iterable[tuple[object, int]]):
    """Resolve outgoing-request greeting and remark edits by exact UIA names."""
    materialized = list(nodes)
    greeting = _find_named_edit(materialized, FRIEND_REQUEST_GREETING_NAMES)
    remark = _find_named_edit(materialized, FRIEND_REQUEST_REMARK_NAMES)
    if greeting is None or remark is None:
        missing = []
        if greeting is None:
            missing.append("greeting")
        if remark is None:
            missing.append("remark")
        raise ProbeError(
            "friend-request form fields not found by exact UIA name: "
            + ", ".join(missing)
        )
    return greeting, remark


def validate_request_values(
    wechat_id: str | None,
    greeting: str | None,
    remark: str | None,
    submit: bool,
) -> None:
    """Reject ambiguous or accidentally destructive CLI combinations."""
    if (greeting is not None or remark is not None) and wechat_id is None:
        raise ProbeError("--greeting/--remark require --wechat-id")
    if not submit:
        return
    for option, value in (
        ("--wechat-id", wechat_id),
        ("--greeting", greeting),
        ("--remark", remark),
    ):
        if value is None:
            raise ProbeError(f"--submit requires {option}")


class ModuleEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("th32ModuleID", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("GlblcntUsage", ctypes.c_ulong),
        ("ProccntUsage", ctypes.c_ulong),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", ctypes.c_ulong),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_wchar * MAX_PATH),
    ]


@dataclass(frozen=True)
class ProcessModule:
    base: int
    size: int
    path: str


@dataclass
class GateSession:
    pid: int
    module: ProcessModule
    rva: int
    keep_active: bool = False
    handle: int | None = None
    original_value: int | None = None

    @property
    def address(self) -> int:
        return self.module.base + self.rva

    def __enter__(self):
        kernel32 = _kernel32()
        access = (
            PROCESS_QUERY_INFORMATION
            | PROCESS_VM_READ
            | PROCESS_VM_WRITE
            | PROCESS_VM_OPERATION
        )
        self.handle = kernel32.OpenProcess(access, False, self.pid)
        if not self.handle:
            raise ProbeError(f"OpenProcess failed for Weixin PID {self.pid}")
        try:
            self.original_value = self.read_byte()
            if self.original_value not in (0, 1):
                raise ProbeError(
                    f"unexpected gate value {self.original_value!r}; refusing to write"
                )
            if self.original_value == 0 and not self.write_byte(1):
                raise ProbeError("failed to activate the Weixin accessibility gate")
            return self
        except Exception:
            kernel32.CloseHandle(self.handle)
            self.handle = None
            raise

    def __exit__(self, exc_type, exc, traceback):
        if (
            self.handle
            and not self.keep_active
            and self.original_value is not None
            and self.read_byte() != self.original_value
        ):
            self.write_byte(self.original_value)
        if self.handle:
            _kernel32().CloseHandle(self.handle)
            self.handle = None

    def read_byte(self) -> int | None:
        buffer = (ctypes.c_ubyte * 1)()
        count = ctypes.c_size_t()
        ok = _kernel32().ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(self.address),
            buffer,
            1,
            ctypes.byref(count),
        )
        return int(buffer[0]) if ok and count.value == 1 else None

    def write_byte(self, value: int) -> bool:
        buffer = (ctypes.c_ubyte * 1)(value & 0xFF)
        count = ctypes.c_size_t()
        ok = _kernel32().WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(self.address),
            buffer,
            1,
            ctypes.byref(count),
        )
        return bool(ok and count.value == 1)


def _kernel32():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Module32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ModuleEntry32W),
    ]
    kernel32.Module32FirstW.restype = wintypes.BOOL
    kernel32.Module32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ModuleEntry32W),
    ]
    kernel32.Module32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.WriteProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _find_weixin_module(pid: int) -> ProcessModule:
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32,
        pid,
    )
    if snapshot == INVALID_HANDLE_VALUE:
        raise ProbeError(f"cannot enumerate modules for Weixin PID {pid}")
    try:
        entry = ModuleEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
            raise ProbeError("Module32FirstW failed")
        while True:
            if entry.szModule.lower() == "weixin.dll":
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                return ProcessModule(base, int(entry.modBaseSize), entry.szExePath)
            if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    raise ProbeError("Weixin.dll is not loaded by the main Weixin process")


def _file_version(path: str) -> str:
    import win32api

    info = win32api.GetFileVersionInfo(path, "\\")
    ms = info["FileVersionMS"]
    ls = info["FileVersionLS"]
    return ".".join(
        str(part)
        for part in (
            win32api.HIWORD(ms),
            win32api.LOWORD(ms),
            win32api.HIWORD(ls),
            win32api.LOWORD(ls),
        )
    )


def _pe_section_for_rva(path: str, rva: int) -> tuple[str, int]:
    with open(path, "rb") as dll:
        header = dll.read(4096)
    pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
    if header[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ProbeError("Weixin.dll has an invalid PE header")
    coff_offset = pe_offset + 4
    section_count = struct.unpack_from("<H", header, coff_offset + 2)[0]
    optional_size = struct.unpack_from("<H", header, coff_offset + 16)[0]
    section_offset = coff_offset + 20 + optional_size
    for index in range(section_count):
        offset = section_offset + index * 40
        name = header[offset : offset + 8].split(b"\0", 1)[0].decode("ascii", "ignore")
        virtual_size, virtual_address, raw_size = struct.unpack_from(
            "<III", header, offset + 8
        )
        characteristics = struct.unpack_from("<I", header, offset + 36)[0]
        size = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + size:
            return name, characteristics
    raise ProbeError(f"gate RVA 0x{rva:x} is outside every PE section")


def _force_foreground(hwnd: int) -> bool:
    import win32api
    import win32con
    import win32gui
    import win32process

    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    current_thread = win32api.GetCurrentThreadId()
    foreground = win32gui.GetForegroundWindow()
    foreground_thread = (
        win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
    )
    attached = False
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        if foreground_thread and foreground_thread != current_thread:
            win32process.AttachThreadInput(current_thread, foreground_thread, True)
            attached = True
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        return win32gui.GetForegroundWindow() == hwnd
    finally:
        if attached:
            try:
                win32process.AttachThreadInput(current_thread, foreground_thread, False)
            except Exception:
                pass


def _visible_process_windows(pid: int) -> list[int]:
    import win32gui
    import win32process

    windows: list[int] = []

    def collect(hwnd, _extra):
        try:
            window_pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            if window_pid == pid and win32gui.IsWindowVisible(hwnd):
                windows.append(hwnd)
        except Exception:
            pass

    win32gui.EnumWindows(collect, None)
    return windows


def _window_root_class(hwnd: int) -> str:
    root, _nodes = _walk(hwnd)
    return str(_safe_attr(root, "ClassName", ""))


def _wait_for_process_window(
    pid: int,
    titles: Sequence[str],
    root_classes: Sequence[str],
    timeout: float,
) -> int:
    import win32gui

    accepted_titles = {title.strip() for title in titles}
    accepted_classes = {class_name.strip() for class_name in root_classes}
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in _visible_process_windows(pid):
            if win32gui.GetWindowText(hwnd).strip() not in accepted_titles:
                continue
            if _window_root_class(hwnd) not in accepted_classes:
                continue
            return hwnd
        time.sleep(0.25)
    raise ProbeError(
        "Weixin window not found: "
        f"title={' / '.join(titles)}, class={' / '.join(root_classes)}"
    )


def _find_process_window(
    pid: int,
    titles: Sequence[str],
    root_classes: Sequence[str],
) -> int | None:
    import win32gui

    accepted_titles = {title.strip() for title in titles}
    accepted_classes = {class_name.strip() for class_name in root_classes}
    for hwnd in _visible_process_windows(pid):
        if win32gui.GetWindowText(hwnd).strip() not in accepted_titles:
            continue
        if _window_root_class(hwnd) in accepted_classes:
            return hwnd
    return None


def _walk(hwnd: int):
    from src.core import uiautomation as uia

    root = uia.ControlFromHandle(hwnd)
    nodes = list(uia.WalkControl(root, includeTop=True, maxDepth=40)) if root else []
    return root, nodes


def _wait_for_materialized_tree(hwnd: int, timeout: float):
    deadline = time.time() + timeout
    best_root = None
    best_nodes = []
    while time.time() < deadline:
        root, nodes = _walk(hwnd)
        if len(nodes) > len(best_nodes):
            best_root, best_nodes = root, nodes
        root_class = str(_safe_attr(root, "ClassName", ""))
        has_mmui = any(
            str(_safe_attr(control, "ClassName", "")).startswith("mmui::")
            for control, _depth in nodes
        )
        has_interactive_children = any(
            str(_safe_attr(control, "ControlTypeName", "")) in INTERACTIVE_CONTROL_TYPES
            for control, _depth in nodes[1:]
        )
        if root_class == "mmui::MainWindow" and has_mmui and has_interactive_children:
            return root, nodes
        time.sleep(0.25)
    root_class = str(_safe_attr(best_root, "ClassName", ""))
    raise ProbeError(
        "UIA root changed to "
        f"{root_class or '<missing>'}, but the interactive tree did not materialize "
        f"(best node count: {len(best_nodes)}). Restart Weixin and rerun immediately."
    )


def _wait_for_named_control(hwnd: int, names: Sequence[str], timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _root, nodes = _walk(hwnd)
        found = find_named_control(nodes, names)
        if found is not None:
            return found, nodes
        time.sleep(0.25)
    raise ProbeError(f"UIA navigation anchor not found: {' / '.join(names)}")


def _wait_for_named_edit(hwnd: int, names: Sequence[str], timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _root, nodes = _walk(hwnd)
        found = _find_named_edit(nodes, names)
        if found is not None:
            return found, nodes
        time.sleep(0.25)
    raise ProbeError(f"UIA edit anchor not found: {' / '.join(names)}")


def _control_description(control) -> dict:
    rectangle = _safe_attr(control, "BoundingRectangle")
    rect = None
    if rectangle is not None:
        rect = [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]
    return {
        "name": str(_safe_attr(control, "Name", "")).strip(),
        "type": str(_safe_attr(control, "ControlTypeName", "")),
        "class": str(_safe_attr(control, "ClassName", "")),
        "automation_id": str(_safe_attr(control, "AutomationId", "")),
        "rect": rect,
    }


def _click_uia_target(control) -> None:
    """Click the center of a UIA-resolved target.

    Weixin 4.1.13.65 reports a successful Qt InvokePattern for several tab and
    popover controls without performing the action. The target still comes
    entirely from UIA; only the final input event uses its bounding rectangle.
    """
    from src.core import uiautomation as uia

    rectangle = _safe_attr(control, "BoundingRectangle")
    if rectangle is None:
        raise ProbeError("UIA target has no bounding rectangle")
    if rectangle.right <= rectangle.left or rectangle.bottom <= rectangle.top:
        raise ProbeError("UIA target has an empty bounding rectangle")
    x = (rectangle.left + rectangle.right) // 2
    y = (rectangle.top + rectangle.bottom) // 2
    uia.Click(x, y)


def _set_edit_text(control, value: str) -> str:
    """Set and verify an edit through ValuePattern, with keyboard fallback."""
    pattern = None
    try:
        pattern = control.GetValuePattern()
    except Exception:
        pass
    if pattern is not None and not bool(_safe_attr(pattern, "IsReadOnly", True)):
        try:
            if pattern.SetValue(value, waitTime=0.05) and pattern.Value == value:
                return "value_pattern"
        except Exception:
            pass

    _click_uia_target(control)
    try:
        control.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
        control.SendKeys(value, waitTime=0.05)
    except Exception as exc:
        raise ProbeError(f"failed to set UIA edit text: {exc}") from exc
    try:
        pattern = control.GetValuePattern()
        if pattern is not None and pattern.Value != value:
            raise ProbeError("UIA edit value did not match after keyboard input")
    except ProbeError:
        raise
    except Exception:
        pass
    return "send_keys"


def _press_enter(control) -> None:
    try:
        control.SendKeys("{Enter}", waitTime=0.1)
    except Exception as exc:
        raise ProbeError(f"failed to submit Weixin search field: {exc}") from exc


def _record_step(steps: list[dict], label: str, control) -> None:
    description = _control_description(control)
    description["step"] = label
    steps.append(description)


def _open_add_friend_window(
    main_hwnd: int,
    pid: int,
    timeout: float,
    steps: list[dict],
) -> int:
    existing = _find_process_window(
        pid,
        ("添加朋友",),
        ("mmui::AddFriendWindow",),
    )
    if existing:
        _force_foreground(existing)
        return existing

    for label, names in (
        ("chat_tab", ("微信",)),
        ("quick_actions", ("快捷操作",)),
        ("add_friend", ("添加朋友",)),
    ):
        _force_foreground(main_hwnd)
        control, _nodes = _wait_for_named_control(main_hwnd, names, timeout)
        _record_step(steps, label, control)
        _click_uia_target(control)
        time.sleep(0.8)
    add_hwnd = _wait_for_process_window(
        pid,
        ("添加朋友",),
        ("mmui::AddFriendWindow",),
        timeout,
    )
    _force_foreground(add_hwnd)
    return add_hwnd


def _prepare_friend_request(
    add_hwnd: int,
    pid: int,
    wechat_id: str,
    greeting: str | None,
    remark: str | None,
    submit: bool,
    timeout: float,
    steps: list[dict],
) -> tuple[str, int | None, dict[str, str]]:
    search, _nodes = _wait_for_named_edit(
        add_hwnd,
        ("搜索", "微信号/手机号"),
        timeout,
    )
    _record_step(steps, "search_wechat_id", search)
    search_method = _set_edit_text(search, wechat_id)
    _press_enter(search)

    add_to_contacts, _nodes = _wait_for_named_control(
        add_hwnd,
        ("添加到通讯录",),
        timeout,
    )
    _record_step(steps, "add_to_contacts", add_to_contacts)
    _click_uia_target(add_to_contacts)

    verify_hwnd = _wait_for_process_window(
        pid,
        FRIEND_REQUEST_TITLES,
        ("mmui::VerifyFriendWindow",),
        timeout,
    )
    _force_foreground(verify_hwnd)
    _root, nodes = _walk(verify_hwnd)
    greeting_edit, remark_edit = resolve_friend_form_fields(nodes)
    _record_step(steps, "greeting", greeting_edit)
    _record_step(steps, "remark", remark_edit)

    field_methods = {"search": search_method}
    if greeting is not None:
        field_methods["greeting"] = _set_edit_text(greeting_edit, greeting)
    if remark is not None:
        field_methods["remark"] = _set_edit_text(remark_edit, remark)

    if not submit:
        return "ready_to_submit", verify_hwnd, field_methods

    confirm, _nodes = _wait_for_named_control(verify_hwnd, ("确定",), timeout)
    _record_step(steps, "submit", confirm)
    _click_uia_target(confirm)
    deadline = time.time() + timeout
    import win32gui

    while time.time() < deadline and win32gui.IsWindow(verify_hwnd):
        if not win32gui.IsWindowVisible(verify_hwnd):
            return "submitted", None, field_methods
        time.sleep(0.25)
    if win32gui.IsWindow(verify_hwnd) and win32gui.IsWindowVisible(verify_hwnd):
        raise ProbeError("friend-request window stayed open after submit")
    return "submitted", None, field_methods


def run_probe(
    navigate: bool,
    keep_active: bool,
    timeout: float,
    wechat_id: str | None = None,
    greeting: str | None = None,
    remark: str | None = None,
    submit: bool = False,
) -> dict:
    validate_request_values(wechat_id, greeting, remark, submit)
    if os.name != "nt":
        raise ProbeError("this live probe only runs on Windows")

    import win32api
    import win32gui
    import win32process

    from src.core.win32 import find_wechat_window, is_window_visible

    hwnd = find_wechat_window()
    if not hwnd:
        raise ProbeError("Weixin main window was not found")
    if not is_window_visible(hwnd) and not _force_foreground(hwnd):
        raise ProbeError("Weixin main window could not be restored before the probe")

    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    module = _find_weixin_module(pid)
    version = _file_version(module.path)
    rva = resolve_gate_rva(version)
    section_name, section_flags = _pe_section_for_rva(module.path, rva)
    if not section_flags & IMAGE_SCN_MEM_WRITE:
        raise ProbeError(
            f"gate RVA 0x{rva:x} is in non-writable PE section {section_name!r}"
        )
    if rva >= module.size:
        raise ProbeError(f"gate RVA 0x{rva:x} exceeds the loaded module size")

    previous_foreground = win32gui.GetForegroundWindow()
    previous_cursor = win32api.GetCursorPos()
    report = {
        "ok": False,
        "version": version,
        "hwnd": hwnd,
        "pid": pid,
        "gate_rva": f"0x{rva:x}",
        "gate_section": section_name,
        "navigate_add_friend": navigate,
        "submit_requested": submit,
        "request_values": {
            "wechat_id_length": len(wechat_id) if wechat_id is not None else None,
            "greeting_length": len(greeting) if greeting is not None else None,
            "remark_length": len(remark) if remark is not None else None,
        },
        "steps": [],
    }
    leave_weixin_foreground = False
    try:
        foreground_acquired = _force_foreground(hwnd)
        report["foreground_acquired"] = foreground_acquired
        if not foreground_acquired and not is_window_visible(hwnd):
            raise ProbeError("failed to acquire the Weixin foreground window")
        with GateSession(pid, module, rva, keep_active=keep_active) as gate:
            report["gate_original"] = gate.original_value
            report["gate_active"] = gate.read_byte()
            ctypes.windll.user32.SystemParametersInfoW(0x0047, 1, 0, 0x02)
            root, nodes = _wait_for_materialized_tree(hwnd, timeout)
            report["root_class"] = str(_safe_attr(root, "ClassName", ""))
            report["node_count"] = len(nodes)
            if navigate or wechat_id is not None:
                add_hwnd = _open_add_friend_window(
                    hwnd,
                    pid,
                    timeout,
                    report["steps"],
                )
                report["add_friend_hwnd"] = add_hwnd
                report["stage"] = "add_friend_open"
                leave_weixin_foreground = True
                if wechat_id is not None:
                    stage, preview_hwnd, methods = _prepare_friend_request(
                        add_hwnd,
                        pid,
                        wechat_id,
                        greeting,
                        remark,
                        submit,
                        timeout,
                        report["steps"],
                    )
                    report["stage"] = stage
                    report["input_methods"] = methods
                    report["preview_hwnd"] = preview_hwnd
                    report["submitted"] = stage == "submitted"
                    leave_weixin_foreground = preview_hwnd is not None
            report["ok"] = True
            return report
    finally:
        win32api.SetCursorPos(previous_cursor)
        if (
            not leave_weixin_foreground
            and previous_foreground
            and win32gui.IsWindow(previous_foreground)
        ):
            _force_foreground(previous_foreground)


def _parse_args(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--navigate-add-friend",
        action="store_true",
        help="open the standalone add-friend window without searching",
    )
    parser.add_argument(
        "--wechat-id",
        help="search this Weixin ID or mobile number and open its request form",
    )
    parser.add_argument(
        "--greeting",
        help="replace the outgoing friend-request greeting",
    )
    parser.add_argument(
        "--remark",
        help="set the remark in the outgoing friend-request form",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="click Confirm after filling; requires all three request values",
    )
    parser.add_argument(
        "--keep-active",
        action="store_true",
        help="leave the runtime UIA gate enabled after a successful probe",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_probe(
            args.navigate_add_friend,
            args.keep_active,
            args.timeout,
            wechat_id=args.wechat_id,
            greeting=args.greeting,
            remark=args.remark,
            submit=args.submit,
        )
    except Exception as exc:
        report = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
