"""Read-only Windows contact-reader primitives, independent of UI automation."""

from __future__ import annotations

import ctypes
import hashlib
import math
import ntpath
import os
import re
import stat
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_VERSION = "4.1.13.65"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# VirtualQueryEx requires QUERY_INFORMATION; neither access mask allows writes.
PROCESS_MEMORY_READ = 0x0400 | 0x0010
MAX_CHUNK = 1024 * 1024
_MESSAGES = {
    "ACCESS_DENIED": "Access to the local contact data was denied.",
    "LOGIN_REQUIRED": "Sign in to WeChat in the current Windows session first.",
    "UNSUPPORTED_VERSION": "Only WeChat 4.1.13.65 is supported.",
    "PROCESS_CHANGED": "The verified WeChat process changed. Retry the read.",
    "SNAPSHOT_UNSTABLE": "The contact database changed during all snapshot attempts.",
    "DATABASE_INVALID": "The encrypted contact database could not be validated.",
    "SCHEMA_UNSUPPORTED": "The contact database schema is not supported.",
    "CANCELLED": "The contact read was cancelled.",
    "TIMEOUT": "The contact read timed out.",
}


class ContactError(RuntimeError):
    """Public failures never include OS details, paths, SQL, or key material."""

    def __init__(self, code: str, message: str | None = None):
        if code not in _MESSAGES:
            code = "DATABASE_INVALID"
        self.code = code
        # Do not trust dependency exception strings as user-visible messages.
        self.safe_message = self.message = _MESSAGES[code]
        super().__init__(self.safe_message)


def check_budget(cancel: threading.Event, deadline: float) -> None:
    if cancel.is_set():
        raise ContactError("CANCELLED")
    if not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise ContactError("TIMEOUT")


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_time: int
    session_id: int
    sid: str
    path: str
    version: str


def verified_path(value: str | Path, *, missing: bool = False) -> Path:
    """Require a local absolute path without symlinks, junctions, or ADS."""
    path = Path(value)
    if not path.is_absolute():
        raise ContactError("DATABASE_INVALID")
    if os.name == "nt":
        drive, tail = ntpath.splitdrive(str(path))
        if not re.fullmatch(r"[A-Za-z]:", drive) or ":" in tail:
            raise ContactError("DATABASE_INVALID")
    try:
        for part in [*reversed(path.parents), path]:
            try:
                info = part.lstat()
            except FileNotFoundError:
                if missing:
                    continue
                raise
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ContactError("ACCESS_DENIED")
        resolved = path.resolve(strict=not missing)
        if os.path.normcase(str(resolved)) != os.path.normcase(os.path.normpath(str(path))):
            raise ContactError("ACCESS_DENIED")
        return resolved
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except OSError:
        raise ContactError("DATABASE_INVALID") from None


def _weixin_path(path: str) -> bool:
    return ntpath.isabs(path) and ntpath.basename(path).lower() in {"weixin.exe", "wechat.exe"}


def matching_processes(probe, *, cancel, deadline) -> list[ProcessIdentity]:
    """Return every eligible process; memory usage is never a selection signal."""
    check_budget(cancel, deadline)
    try:
        sid, session = probe.current_identity()
        matches, unsupported, denied = [], False, False
        for pid in probe.process_ids():
            check_budget(cancel, deadline)
            try:
                item = probe.inspect(pid)
            except PermissionError:
                denied = True
                continue
            except ProcessLookupError:
                continue
            if item.pid != pid or not item.start_time or not _weixin_path(item.path):
                continue
            if (item.sid, item.session_id) != (sid, session):
                continue
            if item.version != SUPPORTED_VERSION:
                unsupported = True
                continue
            matches.append(item)
        check_budget(cancel, deadline)
        if matches:
            return matches
        raise ContactError("UNSUPPORTED_VERSION" if unsupported else
                           "ACCESS_DENIED" if denied else "LOGIN_REQUIRED")
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except OSError:
        raise ContactError("PROCESS_CHANGED") from None


def verify_process(probe, expected: ProcessIdentity, handle=None, *, full: bool = True) -> None:
    try:
        if expected.version != SUPPORTED_VERSION or not _weixin_path(expected.path):
            raise ContactError("PROCESS_CHANGED")
        if probe.current_identity() != (expected.sid, expected.session_id):
            raise ContactError("PROCESS_CHANGED")
        inspect = probe.inspect
        if not full and handle is not None:
            inspect = getattr(probe, "inspect_handle", inspect)
        if inspect(expected.pid, handle) != expected:
            raise ContactError("PROCESS_CHANGED")
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except (OSError, KeyError):
        raise ContactError("PROCESS_CHANGED") from None


_MAX_KEY_HEX = 512
_KEY_OVERLAP = 2 * (_MAX_KEY_HEX + 3) - 1
_ASCII_KEY = re.compile(rf"[xX]'([0-9a-fA-F]{{96,{_MAX_KEY_HEX}}})'".encode("ascii"))
_WIDE_KEY = re.compile(
    rf"[xX]\x00'\x00((?:[0-9a-fA-F]\x00){{96,{_MAX_KEY_HEX}}})'\x00".encode("ascii"))


def candidate_keys(probe, identity: ProcessIdentity, salt: bytes, *, cancel, deadline,
                   chunk_size: int = 64 * 1024):
    """Yield bounded raw keys only from explicit SQLCipher key+salt literals.

    The yielded mutable key is wiped when iteration resumes or is closed. The
    consumer must validate it synchronously and close the iterator on success.
    """
    check_budget(cancel, deadline)
    if len(salt) != 16 or not 1 <= chunk_size <= MAX_CHUNK:
        raise ContactError("DATABASE_INVALID")
    verify_process(probe, identity)
    try:
        handle = probe.open_memory(identity.pid)
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except OSError:
        raise ContactError("PROCESS_CHANGED") from None
    seen = set()
    tail = bytearray()
    try:
        verify_process(probe, identity, handle)
        for address, size in probe.memory_regions(handle):
            check_budget(cancel, deadline)
            verify_process(probe, identity, handle, full=False)
            tail[:] = b"\0" * len(tail)
            tail.clear()
            offset = 0
            while offset < size:
                check_budget(cancel, deadline)
                count = min(chunk_size, size - offset)
                data = probe.read_memory(handle, address + offset, count)
                check_budget(cancel, deadline)
                if not data:
                    # Do not join candidate fragments across unreadable gaps.
                    tail[:] = b"\0" * len(tail)
                    tail.clear()
                    offset += count
                    continue
                if len(data) > count:
                    raise ContactError("PROCESS_CHANGED")
                read_length = len(data)
                window = tail + data
                if isinstance(data, bytearray):
                    data[:] = b"\0" * len(data)
                del data
                try:
                    for pattern, encoding in ((_ASCII_KEY, "ascii"), (_WIDE_KEY, "utf-16-le")):
                        for match in pattern.finditer(window):
                            check_budget(cancel, deadline)
                            literal = match.group(1).decode(encoding)
                            if len(literal) % 2:
                                continue
                            material = bytearray.fromhex(literal)
                            try:
                                if material.find(salt, 32) < 0:
                                    continue
                                key = material[:32]
                            finally:
                                material[:] = b"\0" * len(material)
                            fingerprint = hashlib.sha256(key).digest()
                            try:
                                if fingerprint in seen:
                                    continue
                                if len(seen) >= 128:
                                    raise ContactError("DATABASE_INVALID")
                                seen.add(fingerprint)
                                verify_process(probe, identity, handle, full=False)
                                yield key
                                check_budget(cancel, deadline)
                                verify_process(probe, identity, handle, full=False)
                            finally:
                                key[:] = b"\0" * len(key)
                    # Keep every possible prefix of the longest UTF-16 literal.
                    tail[:] = window[-_KEY_OVERLAP:]
                finally:
                    window[:] = b"\0" * len(window)
                # Partial reads are contiguous; never skip their unread suffix.
                offset += read_length
            verify_process(probe, identity, handle, full=False)
        verify_process(probe, identity, handle)
    except PermissionError:
        raise ContactError("ACCESS_DENIED") from None
    except OSError:
        raise ContactError("PROCESS_CHANGED") from None
    finally:
        tail[:] = b"\0" * len(tail)
        probe.close_memory(handle)


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class _MemoryInfo(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


def _kernel():
    if os.name != "nt":
        raise ContactError("ACCESS_DENIED")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "GetProcessId": ([wintypes.HANDLE], wintypes.DWORD),
        "ProcessIdToSessionId": ([wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "GetProcessTimes": ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                        ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
        "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
        "VirtualQueryEx": ([wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MemoryInfo),
                            ctypes.c_size_t], ctypes.c_size_t),
        "ReadProcessMemory": ([wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result
    return kernel


def _win_error():
    code = ctypes.get_last_error()
    if code == 5:
        return PermissionError()
    if code in {6, 87, 1168}:
        return ProcessLookupError()
    return OSError(code, "Windows read-only query failed")


def _start_time(kernel, handle) -> int:
    created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                  ctypes.byref(system), ctypes.byref(user)):
        raise _win_error()
    return created.dwLowDateTime | created.dwHighDateTime << 32


def _token_sid(handle) -> str:
    import pywintypes
    import win32security
    try:
        token = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
        try:
            return win32security.ConvertSidToStringSid(
                win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        finally:
            token.Close()
    except (OSError, pywintypes.error) as error:
        code = getattr(error, "winerror", None)
        if code is None:
            code = getattr(error, "errno", None)
        if code == 5 or isinstance(error, PermissionError):
            raise PermissionError() from None
        if code in {6, 87, 1168} or isinstance(error, ProcessLookupError):
            raise ProcessLookupError() from None
        raise OSError("Windows token query failed") from None


class Win32Probe:
    """Small injectable adapter. No privilege adjustment, writes, or UI calls."""

    def __init__(self, *, kernel=None):
        self.kernel = kernel if kernel is not None else _kernel()
        self._image_identity = {}

    def _open_process(self, pid: int, *, memory: bool):
        handle = self.kernel.OpenProcess(PROCESS_MEMORY_READ if memory else
                                         PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise _win_error()
        return handle

    def open_memory(self, pid):
        return self._open_process(pid, memory=True)

    def close_memory(self, handle):
        self.kernel.CloseHandle(handle)

    def current_identity(self):
        session = wintypes.DWORD()
        if not self.kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise _win_error()
        return _token_sid(self.kernel.GetCurrentProcess()), session.value

    def process_ids(self):
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise _win_error()
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                if entry.szExeFile.lower() in {"weixin.exe", "wechat.exe"}:
                    yield entry.th32ProcessID
                more = self.kernel.Process32NextW(handle, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise _win_error()
        finally:
            self.kernel.CloseHandle(handle)

    def inspect(self, pid, handle=None):
        import win32api
        owned = handle is None
        if owned:
            handle = self._open_process(pid, memory=False)
        try:
            actual_pid = self.kernel.GetProcessId(handle)
            if actual_pid != pid:
                raise ProcessLookupError()
            start = _start_time(self.kernel, handle)
            session = wintypes.DWORD()
            if not self.kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
                raise _win_error()
            size = wintypes.DWORD(32768)
            image = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                raise _win_error()
            path = str(verified_path(image.value))
            try:
                info = win32api.GetFileVersionInfo(path, "\\")
                ms, ls = info["FileVersionMS"], info["FileVersionLS"]
                version = ".".join(str(n) for n in (ms >> 16, ms & 65535, ls >> 16, ls & 65535))
            except Exception:
                version = ""
            self._image_identity[(actual_pid, start)] = path, version
            return ProcessIdentity(actual_pid, start, session.value, _token_sid(handle), path, version)
        finally:
            if owned:
                self.kernel.CloseHandle(handle)

    def inspect_handle(self, pid, handle):
        """Recheck live ownership at boundaries, reusing the immutable image.

        Full inspect is still used before and after the read. PID/start time,
        token SID and Windows session remain live queries, not cached values.
        """
        actual_pid = self.kernel.GetProcessId(handle)
        if actual_pid != pid:
            raise ProcessLookupError()
        start = _start_time(self.kernel, handle)
        image = self._image_identity.get((pid, start))
        if image is None:
            return self.inspect(pid, handle)
        session = wintypes.DWORD()
        if not self.kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
            raise _win_error()
        return ProcessIdentity(actual_pid, start, session.value, _token_sid(handle), *image)

    def memory_regions(self, handle):
        address = 0
        limit = 0x7FFFFFFEFFFF if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x7FFEFFFF
        while address < limit:
            info = _MemoryInfo()
            if not self.kernel.VirtualQueryEx(handle, address, ctypes.byref(info), ctypes.sizeof(info)):
                if ctypes.get_last_error() == 87:
                    break
                raise _win_error()
            base, size = info.BaseAddress or 0, info.RegionSize
            end = base + size
            if size <= 0 or end <= address:
                raise ProcessLookupError()
            if info.State == 0x1000 and not info.Protect & (0x100 | 1) and info.Protect & 0xEE:
                yield base, size
            address = end

    def read_memory(self, handle, address, size):
        if not 0 < size <= MAX_CHUNK or address < 0:
            raise ValueError("Invalid bounded memory read")
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        try:
            ok = self.kernel.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(count))
            if not ok and not count.value and ctypes.get_last_error() not in {299, 487, 998}:
                raise _win_error()
            return bytearray(buffer.raw[:min(count.value, size)])
        finally:
            ctypes.memset(ctypes.addressof(buffer), 0, size)


def current_job_identity() -> dict:
    """Identity of this Python job only, for snapshot ownership and crash cleanup."""
    kernel = _kernel()
    handle = kernel.GetCurrentProcess()
    return {"ownerSid": _token_sid(handle), "pid": os.getpid(),
            "startTime": _start_time(kernel, handle)}


def process_start_time(pid: int) -> int | None:
    probe = Win32Probe()
    try:
        handle = probe._open_process(pid, memory=False)
    except ProcessLookupError:
        return None
    try:
        return _start_time(probe.kernel, handle)
    finally:
        probe.close_memory(handle)
