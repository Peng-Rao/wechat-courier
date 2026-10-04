from __future__ import annotations

import ctypes
import os
import sys
import subprocess
import struct
import tempfile
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .journal import GateLeaseJournal
from .profile import WeixinProfile, get_weixin_profile

if TYPE_CHECKING:
    from src.core.win32 import WindowRef, WindowRestoreResult


PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INVALID_PARAMETER = 87
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
TH32CS_SNAPPROCESS = 0x00000002
IMAGE_SCN_MEM_WRITE = 0x80000000
MAX_MODULE_NAME32 = 255
MAX_PATH = 260
SPI_GETSCREENREADER = 0x0046
SPI_SETSCREENREADER = 0x0047
SPIF_SENDCHANGE = 0x0002
WM_NULL = 0x0000
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002


class AccessibilitySafetyError(RuntimeError):
    """A PE/gate invariant or mutation state that must not be retried."""


class GateRecoveryRequired(AccessibilitySafetyError):
    """Lease evidence is insufficient; only a verified process restart is safe."""


class WechatStartupPending(RuntimeError):
    """The verified root executable is running but its DLL is still loading."""


@dataclass(frozen=True)
class ProcessModule:
    base: int
    size: int
    path: str


class ModuleEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_wchar * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_wchar * MAX_PATH),
    ]


class ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


class NativeGateBackend:
    """Native operations kept behind an injectable boundary for safety tests."""

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise RuntimeError("Weixin automation is only available on Windows")

    def discover_main_window(self) -> WindowRef | None:
        self._require_windows()
        from src.core.win32 import find_wechat_window_ref

        return find_wechat_window_ref()

    def find_main_window(self) -> int:
        """Backward-compatible, read-only HWND discovery."""
        window = self.discover_main_window()
        return int(window.hwnd if window is not None else 0)

    def window_inspection(self) -> dict[str, object]:
        """Return JSON-compatible window state without restoring or mutating it."""
        window = self.discover_main_window()
        if window is None:
            return {
                "hwnd": 0,
                "pid": 0,
                "processPath": "",
                "windowClass": "",
                "title": "",
                "visible": False,
                "bounds": [0, 0, 0, 0],
                "windowState": "missing",
                "restorable": False,
            }
        result = window.as_dict()
        result.update(
            {
                "windowState": "visible" if window.visible else "hidden",
                "restorable": not window.visible,
            }
        )
        return result

    @staticmethod
    def window_responsive(hwnd: int, timeout_ms: int = 250) -> bool:
        if not hwnd:
            return False
        result = ctypes.c_size_t()
        return bool(
            ctypes.windll.user32.SendMessageTimeoutW(
                int(hwnd),
                WM_NULL,
                0,
                0,
                SMTO_ABORTIFHUNG | SMTO_BLOCK,
                max(1, int(timeout_ms)),
                ctypes.byref(result),
            )
        )

    def prepare_main_window(self) -> WindowRestoreResult:
        """Discover and, only when hidden, restore the main window."""
        from src.core.win32 import WindowRestoreResult, restore_wechat_window

        window = self.discover_main_window()
        if window is None:
            return WindowRestoreResult(None, None, False)
        return restore_wechat_window(window)

    def get_window_pid(self, hwnd: int) -> int:
        import win32process

        return int(win32process.GetWindowThreadProcessId(hwnd)[1])

    def find_module(self, pid: int, name: str) -> ProcessModule:
        self._require_windows()
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid
        )
        invalid = ctypes.c_void_p(-1).value
        if snapshot == invalid:
            raise RuntimeError(f"cannot enumerate modules for Weixin PID {pid}")
        try:
            entry = ModuleEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
                raise RuntimeError("Module32FirstW failed")
            while True:
                if entry.szModule.casefold() == name.casefold():
                    base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                    return ProcessModule(base, int(entry.modBaseSize), entry.szExePath)
                if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)
        raise RuntimeError(f"{name} is not loaded by Weixin")

    @staticmethod
    def file_version(path: str) -> str:
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

    @staticmethod
    def pe_section_for_rva(path: str, rva: int) -> tuple[str, int]:
        with open(path, "rb") as dll:
            dos = dll.read(64)
            if len(dos) < 64 or dos[:2] != b"MZ":
                raise AccessibilitySafetyError(
                    "Weixin.dll has an invalid DOS header"
                )
            pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
            dll.seek(pe_offset)
            signature = dll.read(4)
            coff = dll.read(20)
            if signature != b"PE\0\0" or len(coff) != 20:
                raise AccessibilitySafetyError(
                    "Weixin.dll has an invalid PE header"
                )
            section_count = struct.unpack_from("<H", coff, 2)[0]
            optional_size = struct.unpack_from("<H", coff, 16)[0]
            dll.seek(optional_size, os.SEEK_CUR)
            sections = dll.read(section_count * 40)
        for index in range(section_count):
            offset = index * 40
            header = sections[offset : offset + 40]
            if len(header) != 40:
                break
            name = header[:8].split(b"\0", 1)[0].decode("ascii", "ignore")
            virtual_size, virtual_address, raw_size = struct.unpack_from(
                "<III", header, 8
            )
            characteristics = struct.unpack_from("<I", header, 36)[0]
            size = max(virtual_size, raw_size)
            if virtual_address <= rva < virtual_address + size:
                return name, characteristics
        raise AccessibilitySafetyError(
            f"gate RVA 0x{rva:x} is outside every PE section"
        )

    def open_process(self, pid: int):
        access = (
            PROCESS_QUERY_INFORMATION
            | PROCESS_VM_READ
            | PROCESS_VM_WRITE
            | PROCESS_VM_OPERATION
        )
        handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
        if not handle:
            raise RuntimeError(f"OpenProcess failed for Weixin PID {pid}")
        return handle

    def process_path(self, pid: int) -> str:
        self._require_windows()
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            raise RuntimeError(f"cannot open Weixin PID {pid} to read its path")
        try:
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(capacity)
            )
            if not ok or not buffer.value:
                raise RuntimeError("cannot resolve the Weixin executable path")
            return buffer.value
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def process_start_time(self, pid: int) -> str:
        """Return the immutable Windows creation FILETIME for PID reuse checks."""

        self._require_windows()
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise RuntimeError(f"cannot open Weixin PID {pid} to read start time")
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                raise RuntimeError("cannot read Weixin process start time")
            value = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            return str(value)
        finally:
            kernel32.CloseHandle(handle)

    def process_exists(self, pid: int) -> bool:
        """Distinguish an exited PID from an identity check failure."""

        self._require_windows()
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            error = int(kernel32.GetLastError())
            if error == ERROR_INVALID_PARAMETER:
                return False
            raise RuntimeError(
                f"cannot verify whether Weixin PID {pid} is still running "
                f"(Win32 error {error})"
            )
        try:
            wait_result = int(kernel32.WaitForSingleObject(handle, 0))
            if wait_result == WAIT_TIMEOUT:
                return True
            if wait_result == WAIT_OBJECT_0:
                return False
            raise RuntimeError(
                f"cannot query Weixin PID {pid} state (wait result {wait_result})"
            )
        finally:
            kernel32.CloseHandle(handle)

    def other_agent_pids(self) -> tuple[int, ...]:
        """List peers across sessions: the same user can share a lease path."""

        self._require_windows()
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        invalid = ctypes.c_void_p(-1).value
        if snapshot == invalid:
            raise RuntimeError("cannot enumerate running Agent processes")
        current_pid = os.getpid()
        matches: list[int] = []
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise RuntimeError("Process32FirstW failed")
            while True:
                pid = int(entry.th32ProcessID)
                if (
                    pid != current_pid
                    and entry.szExeFile.casefold() == "wechat-agent.exe"
                ):
                    matches.append(pid)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)
        return tuple(matches)

    def process_session_id(self, pid: int) -> int:
        self._require_windows()
        session_id = wintypes.DWORD()
        if not ctypes.windll.kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(session_id)):
            raise RuntimeError(f"cannot verify Windows session for Agent PID {pid}")
        return int(session_id.value)

    def process_context(self, pid: int | None = None) -> dict[str, Any]:
        """Read token/LSA identity without creating a COM apartment."""
        import win32api
        import win32security

        pid = os.getpid() if pid is None else int(pid)
        process = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            token = win32security.OpenProcessToken(process, win32security.TOKEN_QUERY)
            try:
                logon_id = int(win32security.GetTokenInformation(token, win32security.TokenStatistics)["AuthenticationId"])
            finally:
                token.Close()
        finally:
            process.Close()

        class Luid(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

        class UnicodeString(ctypes.Structure):
            _fields_ = [("length", wintypes.USHORT), ("capacity", wintypes.USHORT), ("buffer", ctypes.c_void_p)]

        class LogonData(ctypes.Structure):
            _fields_ = [("size", wintypes.ULONG), ("id", Luid),
                        ("user", UnicodeString), ("domain", UnicodeString),
                        ("package", UnicodeString), ("type", wintypes.ULONG),
                        ("session", wintypes.ULONG), ("sid", ctypes.c_void_p),
                        ("time", ctypes.c_longlong)]

        secur32 = ctypes.WinDLL("secur32")
        query = secur32.LsaGetLogonSessionData
        query.argtypes = [ctypes.POINTER(Luid), ctypes.POINTER(ctypes.c_void_p)]
        query.restype = wintypes.LONG
        free = secur32.LsaFreeReturnBuffer
        free.argtypes = [ctypes.c_void_p]
        free.restype = wintypes.LONG
        luid = Luid(logon_id & 0xFFFFFFFF, (logon_id >> 32) & 0xFFFFFFFF)
        pointer = ctypes.c_void_p()
        status = query(ctypes.byref(luid), ctypes.byref(pointer))
        if status or not pointer.value:
            raise AccessibilitySafetyError(f"cannot read logon identity (NTSTATUS {status:#x})")
        try:
            data = ctypes.cast(pointer, ctypes.POINTER(LogonData)).contents
            if data.size < ctypes.sizeof(LogonData) or data.time <= 0:
                raise AccessibilitySafetyError("logon identity has no verifiable login time")
            return {"windowsSessionId": self.process_session_id(pid),
                    "logonId": str(logon_id), "logonTime": str(data.time),
                    "ownerAgentPid": pid, "ownerAgentStartTime": self.process_start_time(pid)}
        finally:
            free(pointer)

    def legacy_agent_pids(self) -> tuple[int, ...]:
        """Call only while owning AgentInstanceLock; peers of this image wait on it.

        Windows keeps a loaded executable locked. Compare file identities, not
        an editable version manifest. Unknown/different images stay fail-closed.
        """
        peers = self.other_agent_pids()
        if not getattr(sys, "frozen", False):
            return peers
        current_session = self.process_session_id(os.getpid())
        return tuple(pid for pid in peers
                     if self.process_session_id(pid) != current_session
                     or not os.path.samefile(self.process_path(pid), sys.executable))

    def verified_wechat_process(self) -> dict[str, Any] | None:
        """Require one root Weixin in this login, even when it has no window."""
        from src.core.win32 import _get_process_command_line, _is_weixin_root_process

        context = self.process_context()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateToolhelp32Snapshot
        create.argtypes, create.restype = [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE
        close = kernel32.CloseHandle
        close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
        first, next_entry = kernel32.Process32FirstW, kernel32.Process32NextW
        for function in (first, next_entry):
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
            function.restype = wintypes.BOOL
        snapshot = create(TH32CS_SNAPPROCESS, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise AccessibilitySafetyError("cannot enumerate Weixin processes")
        candidates = []
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not first(snapshot, ctypes.byref(entry)):
                raise AccessibilitySafetyError("cannot enumerate Weixin process identities")
            while True:
                if entry.szExeFile.casefold() == "weixin.exe":
                    pid = int(entry.th32ProcessID)
                    if self.process_session_id(pid) == context["windowsSessionId"]:
                        path = self.process_path(pid)
                        command = _get_process_command_line(pid)
                        if command is None:
                            raise AccessibilitySafetyError("cannot verify Weixin root process")
                        if _is_weixin_root_process(path, command):
                            candidate_context = self.process_context(pid)
                            if any(candidate_context[key] != context[key] for key in ("logonId", "logonTime")):
                                raise AccessibilitySafetyError("Weixin belongs to another login")
                            try:
                                module = self.find_module(pid, "Weixin.dll")
                            except RuntimeError as exc:
                                if str(exc) == "Weixin.dll is not loaded by Weixin":
                                    raise WechatStartupPending(str(exc)) from exc
                                raise
                            version = self.file_version(module.path)
                            get_weixin_profile(version)
                            window = self.window_inspection()
                            candidates.append({"pid": pid, "processStartTime": self.process_start_time(pid),
                                               "processPath": path, "version": version,
                                               "hwnd": window.get("hwnd", 0) if window.get("pid") == pid else 0,
                                               "windowClass": window.get("windowClass", "")})
                if not next_entry(snapshot, ctypes.byref(entry)):
                    break
        finally:
            close(snapshot)
        if len(candidates) > 1:
            raise AccessibilitySafetyError("multiple Weixin processes; cannot choose a restart target")
        return candidates[0] if candidates else None

    def request_close(self, candidate: dict[str, Any]) -> None:
        import win32con
        import win32gui

        hwnd = int(candidate.get("hwnd", 0))
        if not hwnd or not win32gui.IsWindow(hwnd):
            return
        if self.get_window_pid(hwnd) != candidate["pid"]:
            raise AccessibilitySafetyError("Weixin window owner changed before close")
        window_class = win32gui.GetClassName(hwnd)
        if window_class != candidate.get("windowClass") or not (
            window_class in {"mmui::MainWindow", "mmui::LoginWindow"}
            or (window_class.startswith("Qt") and window_class.endswith("QWindowIcon"))
        ):
            raise AccessibilitySafetyError("unrecognized Weixin window role before close")
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    def login_window_ready(self, candidate: dict[str, Any]) -> bool:
        import win32con
        import win32gui

        window = self.window_inspection()
        hwnd = int(window.get("hwnd", 0))
        if not hwnd or window.get("pid") != candidate["pid"]:
            return False
        # Qt's native class is shared by login/main windows. Resizable main
        # window styles are only a preflight signal; UIA verifies readiness next.
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        return bool(style & win32con.WS_MAXIMIZEBOX and style & win32con.WS_THICKFRAME
                    and self.window_responsive(hwnd))

    def terminate_process(self, pid: int) -> None:
        self._require_windows()
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_TERMINATE | SYNCHRONIZE, False, pid
        )
        if not handle:
            raise RuntimeError(f"cannot open Weixin PID {pid} for restart")
        try:
            if not ctypes.windll.kernel32.TerminateProcess(handle, 0):
                raise RuntimeError("failed to terminate Weixin for recovery")
            ctypes.windll.kernel32.WaitForSingleObject(handle, 5_000)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def terminate_process_tree(
        self, pid: int, *, wait_seconds: float = 5.0
    ) -> None:
        """Terminate the verified Weixin process and all of its children."""

        self._require_windows()
        result = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        process_alive = self.process_exists(pid)
        while process_alive:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))
            process_alive = self.process_exists(pid)
        if process_alive:
            detail = (result.stderr or result.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"Weixin process tree is still running after taskkill{suffix}"
            )

    @staticmethod
    def start_process(path: str) -> None:
        if not os.path.isfile(path):
            raise RuntimeError(f"Weixin executable no longer exists: {path}")
        subprocess.Popen([path], close_fds=True)

    @staticmethod
    def close_process(handle) -> None:
        ctypes.windll.kernel32.CloseHandle(handle)

    @staticmethod
    def read_byte(handle, address: int) -> int | None:
        buffer = (ctypes.c_ubyte * 1)()
        count = ctypes.c_size_t()
        ok = ctypes.windll.kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(address), buffer, 1, ctypes.byref(count)
        )
        return int(buffer[0]) if ok and count.value == 1 else None

    @staticmethod
    def write_byte(handle, address: int, value: int) -> bool:
        buffer = (ctypes.c_ubyte * 1)(value & 0xFF)
        count = ctypes.c_size_t()
        ok = ctypes.windll.kernel32.WriteProcessMemory(
            handle, ctypes.c_void_p(address), buffer, 1, ctypes.byref(count)
        )
        return bool(ok and count.value == 1)

    @staticmethod
    def get_screen_reader() -> bool:
        value = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETSCREENREADER, 0, ctypes.byref(value), 0
        )
        if not ok:
            raise RuntimeError("failed to read the screen-reader session flag")
        return bool(value.value)

    @staticmethod
    def set_screen_reader(enabled: bool) -> bool:
        return bool(
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETSCREENREADER, int(enabled), None, SPIF_SENDCHANGE
            )
        )

    def broadcast_screen_reader_enabled(self) -> bool:
        """Refresh the per-session accessibility notification for Weixin."""

        return self.set_screen_reader(True)


def _process_start_time(backend: Any, pid: int) -> str:
    reader = getattr(backend, "process_start_time", None)
    return str(reader(pid)) if callable(reader) else f"pid:{pid}"


def classify_gate_lease(backend: Any, journal: GateLeaseJournal) -> dict[str, Any]:
    """Preflight only. Classify every lease before any rollback."""
    if not journal.path.exists():
        return {"action": "missing", "reason": "no_lease", "journal": journal}
    journal.path.read_bytes()
    record = journal.load()
    if record is None:
        raise GateRecoveryRequired(f"invalid gate lease: {journal.path.name}")
    owner = record.get("ownerAgentPid")
    if owner and owner != os.getpid() and backend.process_exists(owner):
        if _process_start_time(backend, owner) == record["ownerAgentStartTime"]:
            raise AccessibilitySafetyError("another Agent still owns the gate lease")
    pid = record["pid"]
    same = backend.process_exists(pid) and _process_start_time(backend, pid) == record["processStartTime"]
    result = {"action": "restore" if same else "archive",
              "reason": "stale_lease_recovered" if same else "process_changed",
              "record": record, "journal": journal}
    if not same:
        return result
    session_reader = getattr(backend, "process_session_id", None)
    if callable(session_reader):
        current = session_reader(os.getpid())
        if session_reader(pid) != current or record.get("windowsSessionId", current) != current:
            raise AccessibilitySafetyError("gate lease belongs to another Windows session")
    context_reader = getattr(backend, "process_context", None)
    if callable(context_reader):
        current_context, process_context = context_reader(), context_reader(pid)
        if any(current_context[key] != process_context[key] for key in ("logonId", "logonTime")):
            raise AccessibilitySafetyError("leased Weixin belongs to another login")
    _validate_leased_gate(backend, record)
    return result


def _validate_leased_gate(backend: Any, record: dict[str, Any]) -> tuple[ProcessModule, int]:
    module = backend.find_module(record["pid"], "Weixin.dll")
    version = str(backend.file_version(module.path))
    if version != record["version"]:
        raise GateRecoveryRequired("stale gate lease version does not match the live process")
    profile = get_weixin_profile(version)
    if profile.gate_rva != record["gateRva"] or profile.gate_rva >= module.size:
        raise GateRecoveryRequired("stale gate lease has an invalid verified RVA")
    _section, flags = backend.pe_section_for_rva(module.path, profile.gate_rva)
    if not flags & IMAGE_SCN_MEM_WRITE:
        raise GateRecoveryRequired("stale gate lease points to a non-writable section")
    address = module.base + profile.gate_rva
    handle = backend.open_process(record["pid"])
    try:
        if backend.read_byte(handle, address) not in (0, 1):
            raise GateRecoveryRequired("unexpected gate value during lease recovery")
    finally:
        backend.close_process(handle)
    return module, address


def _same_logon(backend: Any, record: dict[str, Any]) -> bool:
    reader = getattr(backend, "process_context", None)
    if record.get("schemaVersion") != 2 or not callable(reader):
        return False
    current = reader()
    return all(record[key] == current[key] for key in ("windowsSessionId", "logonId", "logonTime"))


def apply_gate_lease(backend: Any, classified: dict[str, Any], *, recovery_id: str = "") -> dict[str, object]:
    journal = classified["journal"]
    if classified["action"] == "missing":
        return {"restored": False, "reason": "no_lease"}
    fresh = classify_gate_lease(backend, journal)
    if fresh["action"] == "missing":
        return {"restored": False, "reason": "no_lease"}
    record = fresh["record"]
    if fresh["action"] == "restore":
        _module, address = _validate_leased_gate(backend, record)
        handle = backend.open_process(record["pid"])
        try:
            if _process_start_time(backend, record["pid"]) != record["processStartTime"]:
                raise AccessibilitySafetyError("process identity changed before gate restore")
            current = backend.read_byte(handle, address)
            if current not in (0, 1):
                raise GateRecoveryRequired("unexpected gate value before restore")
            if record["gateOwned"] and current != record["originalGate"]:
                if not backend.write_byte(handle, address, record["originalGate"]) or backend.read_byte(handle, address) != record["originalGate"]:
                    raise AccessibilitySafetyError("stale gate lease restore verification failed")
        finally:
            backend.close_process(handle)
    if record["screenReaderOwned"] and _same_logon(backend, record):
        original = record["originalScreenReader"]
        if backend.get_screen_reader() != original:
            if not backend.set_screen_reader(original) or backend.get_screen_reader() != original:
                raise AccessibilitySafetyError("failed to restore screen-reader flag from stale lease")
    journal.archive(fresh["reason"], recovery_id=recovery_id)
    return {"restored": True, "reason": fresh["reason"]}


def restore_gate_lease(backend: Any | None = None, journal: GateLeaseJournal | None = None) -> dict[str, object]:
    """Restore/archive abandoned evidence without creating UIA objects."""
    backend = backend or NativeGateBackend()
    journal = journal or GateLeaseJournal.from_environment()
    try:
        return apply_gate_lease(backend, classify_gate_lease(backend, journal))
    except AccessibilitySafetyError:
        raise
    except Exception as exc:
        raise AccessibilitySafetyError(f"gate lease recovery cannot verify identity or archive evidence: {exc}") from exc


def validate_lease_group(entries: list[dict[str, Any]]) -> None:
    originals = {}
    for entry in entries:
        record = entry.get("record")
        if not record or entry["action"] != "restore":
            continue
        key = (record["pid"], record["processStartTime"])
        original = (record["originalGate"], record["originalScreenReader"],
                    record.get("logonId"), record.get("logonTime"))
        if key in originals and originals[key] != original:
            raise GateRecoveryRequired("conflicting gate lease originals; refusing partial rollback")
        originals[key] = original


def restore_legacy_gate_leases(backend: Any | None = None, *,
                              temp_dir: str | os.PathLike[str] | None = None,
                              other_agent_pids: Any | None = None) -> list[dict[str, str]]:
    """Recover old random-path leases only when no legacy Agent is alive."""
    backend = backend or NativeGateBackend()
    directory = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    paths = sorted(directory.glob("wuge-wechat-agent-*-safety.json.gate"), key=lambda path: path.name.casefold())
    if not paths:
        return []
    detector = other_agent_pids or getattr(backend, "other_agent_pids", None)
    if not callable(detector):
        raise AccessibilitySafetyError("cannot verify whether another Agent owns a legacy gate lease")
    if tuple(detector()):
        raise AccessibilitySafetyError("another Agent is still running; legacy gate lease was left untouched")
    entries = []
    for path in paths:
        try:
            entries.append(classify_gate_lease(backend, GateLeaseJournal(path)))
        except GateRecoveryRequired as exc:
            raise AccessibilitySafetyError(f"invalid legacy gate lease was left untouched: {path.name}: {exc}") from exc
    validate_lease_group(entries)
    return [{"path": str(entry["journal"].path), "reason": str(apply_gate_lease(backend, entry)["reason"])}
            for entry in entries]


class WeixinAccessibilitySession:
    """Validated, reversible activation of Weixin's UIA accessibility tree."""

    def __init__(
        self,
        backend: Any | None = None,
        *,
        lease_journal: GateLeaseJournal | None = None,
        session_generation: int = 0,
        screen_reader_restore_value: bool | None = None,
    ):
        self.backend = backend or NativeGateBackend()
        self.lease_journal = lease_journal
        self.session_generation = int(session_generation)
        self.hwnd = 0
        self.pid = 0
        self.module: ProcessModule | None = None
        self.version = ""
        self.profile: WeixinProfile | None = None
        self.section_name = ""
        self.gate_address = 0
        self._handle = None
        self._original_gate: int | None = None
        self._original_screen_reader: bool | None = None
        self._screen_reader_restore_value = screen_reader_restore_value
        self._process_start_time = ""
        self.window_restore: WindowRestoreResult | None = None

    @property
    def process_start_time(self) -> str:
        return self._process_start_time

    @property
    def screen_reader_restore_value(self) -> bool | None:
        return self._original_screen_reader

    def _same_process_instance(self) -> bool:
        process_exists = getattr(self.backend, "process_exists", None)
        if not callable(process_exists):
            return True
        try:
            if not bool(process_exists(self.pid)):
                return False
            current_start_time = _process_start_time(self.backend, self.pid)
        except Exception as exc:
            raise AccessibilitySafetyError(
                f"cannot verify live gate process identity: {exc}"
            ) from exc
        return current_start_time == self._process_start_time

    def __enter__(self) -> "WeixinAccessibilitySession":
        prepare = getattr(self.backend, "prepare_main_window", None)
        if callable(prepare):
            self.window_restore = prepare()
            window = self.window_restore.window
            if window is None:
                raise RuntimeError("Weixin main window was not found")
            if not window.visible:
                outcomes = "; ".join(
                    f"{stage.stage}: {stage.detail}"
                    for stage in self.window_restore.stages
                )
                suffix = f" ({outcomes})" if outcomes else ""
                raise RuntimeError(
                    "Weixin main window could not be restored before gate access"
                    + suffix
                )
            self.hwnd = int(window.hwnd)
            self.pid = int(window.pid)
        else:
            self.hwnd = int(self.backend.find_main_window() or 0)
            if not self.hwnd:
                raise RuntimeError("Weixin main window was not found")
            self.pid = int(self.backend.get_window_pid(self.hwnd))
        self.module = self.backend.find_module(self.pid, "Weixin.dll")
        self._process_start_time = _process_start_time(self.backend, self.pid)
        self.version = str(self.backend.file_version(self.module.path))
        self.profile = get_weixin_profile(self.version)
        if self.profile.gate_rva >= self.module.size:
            raise AccessibilitySafetyError(
                "verified gate RVA exceeds the loaded module size"
            )
        self.section_name, section_flags = self.backend.pe_section_for_rva(
            self.module.path, self.profile.gate_rva
        )
        if not section_flags & IMAGE_SCN_MEM_WRITE:
            raise AccessibilitySafetyError(
                f"verified gate is in non-writable PE section {self.section_name!r}"
            )
        self.gate_address = self.module.base + self.profile.gate_rva
        gate_access_started = False
        try:
            self._handle = self.backend.open_process(self.pid)
            gate_access_started = True
            self._original_gate = self.backend.read_byte(
                self._handle, self.gate_address
            )
            if self._original_gate not in (0, 1):
                raise AccessibilitySafetyError(
                    f"unexpected gate value {self._original_gate!r}; refusing to write"
                )
            current_screen_reader = bool(self.backend.get_screen_reader())
            self._original_screen_reader = (
                current_screen_reader
                if self._screen_reader_restore_value is None
                else bool(self._screen_reader_restore_value)
            )
            if self.lease_journal is not None:
                self.lease_journal.mark(
                    pid=self.pid,
                    process_start_time=self._process_start_time,
                    version=self.version,
                    gate_rva=self.profile.gate_rva,
                    original_gate=self._original_gate,
                    original_screen_reader=self._original_screen_reader,
                    gate_owned=self._original_gate == 0,
                    screen_reader_owned=not self._original_screen_reader,
                    session_generation=self.session_generation,
                    windows_session_id=(
                        self.backend.process_session_id(os.getpid())
                        if callable(getattr(self.backend, "process_session_id", None)) else None
                    ),
                    lease_context=(
                        self.backend.process_context()
                        if callable(getattr(self.backend, "process_context", None)) else None
                    ),
                )
            if not self.backend.write_byte(self._handle, self.gate_address, 1):
                raise AccessibilitySafetyError(
                    "failed to activate the Weixin accessibility gate"
                )
            if self.backend.read_byte(self._handle, self.gate_address) != 1:
                raise AccessibilitySafetyError(
                    "Weixin accessibility gate write-back failed"
                )
            broadcast = getattr(
                self.backend, "broadcast_screen_reader_enabled", None
            )
            notified = (
                bool(broadcast())
                if callable(broadcast)
                else bool(self.backend.set_screen_reader(True))
            )
            if not notified:
                raise AccessibilitySafetyError(
                    "failed to broadcast the screen-reader session flag"
                )
            if not self.backend.get_screen_reader():
                raise AccessibilitySafetyError(
                    "screen-reader session flag notification did not persist"
                )
            return self
        except Exception as exc:
            try:
                self.close()
            except Exception as cleanup_exc:
                if isinstance(cleanup_exc, AccessibilitySafetyError):
                    raise
                raise AccessibilitySafetyError(str(cleanup_exc)) from cleanup_exc
            if gate_access_started and not isinstance(exc, AccessibilitySafetyError):
                raise AccessibilitySafetyError(str(exc)) from exc
            raise

    def refresh(self) -> None:
        """Reassert the live gate without replacing its original ownership lease.

        Weixin can reset the byte during a tray/window transition. A reader
        broadcast alone cannot reactivate that process's accessibility tree.
        """
        if self._handle is None or self._original_gate is None or not self._same_process_instance():
            raise AccessibilitySafetyError("cannot refresh an inactive or replaced gate session")
        module = self.backend.find_module(self.pid, "Weixin.dll")
        if module.base != self.module.base or self.backend.file_version(module.path) != self.version:
            raise AccessibilitySafetyError("gate module identity changed before refresh")
        current = self.backend.read_byte(self._handle, self.gate_address)
        if current not in (0, 1):
            raise AccessibilitySafetyError("unexpected gate value during session refresh")
        try:
            if not self.backend.write_byte(self._handle, self.gate_address, 1):
                raise AccessibilitySafetyError("failed to reassert the live Weixin gate")
            if self.backend.read_byte(self._handle, self.gate_address) != 1:
                raise AccessibilitySafetyError("live gate refresh read-back failed")
            broadcast = getattr(self.backend, "broadcast_screen_reader_enabled", None)
            notified = bool(broadcast()) if callable(broadcast) else bool(self.backend.set_screen_reader(True))
            if not notified or not self.backend.get_screen_reader():
                raise AccessibilitySafetyError("failed to refresh the screen-reader broadcast")
        except Exception:
            self.close()
            raise

    def close(self, *, preserve_screen_reader: bool = False) -> None:
        cleanup_error: Exception | None = None
        gate_was_restored = True

        # Restore the process gate before disabling the session flag. If the
        # process gate cannot be rolled back, keep the flag enabled rather than
        # leaving Weixin in the inconsistent gate=1/screen-reader=False state.
        if self._handle is not None:
            try:
                same_process = self._same_process_instance()
                current_gate = None
                if same_process and self._original_gate is not None:
                    module = self.backend.find_module(self.pid, "Weixin.dll")
                    if module.base != self.module.base or self.backend.file_version(module.path) != self.version:
                        raise AccessibilitySafetyError("gate module identity changed before cleanup")
                    current_gate = self.backend.read_byte(self._handle, self.gate_address)
                    if current_gate not in (0, 1) and current_gate != self._original_gate:
                        raise AccessibilitySafetyError("unexpected gate value during session cleanup")
                if same_process and (
                    self._original_gate is not None
                    and current_gate != self._original_gate
                ):
                    if not self.backend.write_byte(
                        self._handle, self.gate_address, self._original_gate
                    ):
                        raise AccessibilitySafetyError(
                            "failed to restore the Weixin accessibility gate"
                        )
                    if (
                        self.backend.read_byte(self._handle, self.gate_address)
                        != self._original_gate
                    ):
                        raise AccessibilitySafetyError(
                            "failed to restore the Weixin accessibility gate"
                        )
            except Exception as exc:
                gate_was_restored = False
                if cleanup_error is None:
                    cleanup_error = exc
            finally:
                if gate_was_restored:
                    try:
                        self.backend.close_process(self._handle)
                    except Exception as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                    finally:
                        self._handle = None
                        self._original_gate = None
        if self._original_screen_reader is not None and not preserve_screen_reader:
            screen_reader_was_restored = False
            try:
                if gate_was_restored:
                    if (
                        self.backend.get_screen_reader()
                        != self._original_screen_reader
                    ):
                        if not self.backend.set_screen_reader(
                            self._original_screen_reader
                        ):
                            raise AccessibilitySafetyError(
                                "failed to restore the screen-reader session flag"
                            )
                    if (
                        self.backend.get_screen_reader()
                        != self._original_screen_reader
                    ):
                        raise AccessibilitySafetyError(
                            "screen-reader session flag restore verification failed"
                        )
                    screen_reader_was_restored = True
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            finally:
                if screen_reader_was_restored:
                    self._original_screen_reader = None
        if cleanup_error is not None:
            if isinstance(cleanup_error, AccessibilitySafetyError):
                raise cleanup_error
            raise AccessibilitySafetyError(str(cleanup_error)) from cleanup_error
        if (
            self.lease_journal is not None
            and self._handle is None
            and self._original_gate is None
            and self._original_screen_reader is None
        ):
            self.lease_journal.clear()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "AccessibilitySafetyError",
    "IMAGE_SCN_MEM_WRITE",
    "SMTO_ABORTIFHUNG",
    "SMTO_BLOCK",
    "WM_NULL",
    "NativeGateBackend",
    "ProcessModule",
    "WeixinAccessibilitySession",
    "restore_legacy_gate_leases",
    "restore_gate_lease",
]
