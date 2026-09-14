from __future__ import annotations

import ctypes
import os
import subprocess
import struct
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from .profile import WeixinProfile, get_weixin_profile


PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
IMAGE_SCN_MEM_WRITE = 0x80000000
MAX_MODULE_NAME32 = 255
MAX_PATH = 260
SPI_GETSCREENREADER = 0x0046
SPI_SETSCREENREADER = 0x0047


class AccessibilitySafetyError(RuntimeError):
    """A PE/gate invariant or mutation state that must not be retried."""


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


class NativeGateBackend:
    """Native operations kept behind an injectable boundary for safety tests."""

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise RuntimeError("Weixin automation is only available on Windows")

    def find_main_window(self) -> int:
        self._require_windows()
        from src.core.win32 import find_wechat_window

        return int(find_wechat_window() or 0)

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
                SPI_SETSCREENREADER, int(enabled), None, 0
            )
        )


class WeixinAccessibilitySession:
    """Validated, reversible activation of Weixin's UIA accessibility tree."""

    def __init__(self, backend: Any | None = None):
        self.backend = backend or NativeGateBackend()
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

    def __enter__(self) -> "WeixinAccessibilitySession":
        self.hwnd = int(self.backend.find_main_window() or 0)
        if not self.hwnd:
            raise RuntimeError("Weixin main window was not found")
        self.pid = int(self.backend.get_window_pid(self.hwnd))
        self.module = self.backend.find_module(self.pid, "Weixin.dll")
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
            if self._original_gate == 0:
                if not self.backend.write_byte(self._handle, self.gate_address, 1):
                    raise AccessibilitySafetyError(
                        "failed to activate the Weixin accessibility gate"
                    )
                if self.backend.read_byte(self._handle, self.gate_address) != 1:
                    raise AccessibilitySafetyError(
                        "Weixin accessibility gate write-back failed"
                    )
            self._original_screen_reader = bool(self.backend.get_screen_reader())
            if not self._original_screen_reader:
                if not self.backend.set_screen_reader(True):
                    raise AccessibilitySafetyError(
                        "failed to set the screen-reader session flag"
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

    def close(self) -> None:
        cleanup_error: Exception | None = None
        if self._original_screen_reader is not None:
            try:
                if self.backend.get_screen_reader() != self._original_screen_reader:
                    if not self.backend.set_screen_reader(
                        self._original_screen_reader
                    ):
                        raise AccessibilitySafetyError(
                            "failed to restore the screen-reader session flag"
                        )
            except Exception as exc:
                cleanup_error = exc
            finally:
                self._original_screen_reader = None
        if self._handle is not None:
            try:
                if (
                    self._original_gate is not None
                    and self.backend.read_byte(self._handle, self.gate_address)
                    != self._original_gate
                ):
                    self.backend.write_byte(
                        self._handle, self.gate_address, self._original_gate
                    )
                    if (
                        self.backend.read_byte(self._handle, self.gate_address)
                        != self._original_gate
                    ):
                        raise AccessibilitySafetyError(
                            "failed to restore the Weixin accessibility gate"
                        )
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            finally:
                try:
                    self.backend.close_process(self._handle)
                except Exception as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
                finally:
                    self._handle = None
                    self._original_gate = None
        if cleanup_error is not None:
            if isinstance(cleanup_error, AccessibilitySafetyError):
                raise cleanup_error
            raise AccessibilitySafetyError(str(cleanup_error)) from cleanup_error

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "AccessibilitySafetyError",
    "IMAGE_SCN_MEM_WRITE",
    "NativeGateBackend",
    "ProcessModule",
    "WeixinAccessibilitySession",
]
