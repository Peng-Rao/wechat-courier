"""Windows-session ownership for the single Weixin automation Agent."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
DEFAULT_AGENT_MUTEX_NAME = r"Local\WugeWechatAutomationAgent-v1"
DEFAULT_LOCK_WAIT_MS = 5_000
AGENT_ALREADY_RUNNING_EXIT_CODE = 5


class AgentAlreadyRunningError(RuntimeError):
    """Raised when another process owns the Windows-session Agent lease."""


class NativeMutexBackend:
    @staticmethod
    def _kernel32():
        if os.name != "nt":
            raise RuntimeError("wechat-agent instance locking requires Windows")
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    def create_mutex(self, name: str):
        kernel32 = self._kernel32()
        handle = kernel32.CreateMutexW(None, False, str(name))
        if not handle:
            raise RuntimeError("failed to create the wechat-agent session mutex")
        return handle

    def wait(self, handle, timeout_ms: int) -> int:
        return int(self._kernel32().WaitForSingleObject(handle, int(timeout_ms)))

    def release(self, handle) -> None:
        if not self._kernel32().ReleaseMutex(handle):
            raise RuntimeError("failed to release the wechat-agent session mutex")

    def close(self, handle) -> None:
        self._kernel32().CloseHandle(handle)


class AgentInstanceLock:
    """Own one named mutex for the lifetime of an automation Agent process."""

    def __init__(
        self,
        *,
        name: str = DEFAULT_AGENT_MUTEX_NAME,
        wait_timeout_ms: int = DEFAULT_LOCK_WAIT_MS,
        backend: Any | None = None,
    ) -> None:
        self.name = str(name)
        self.wait_timeout_ms = max(0, int(wait_timeout_ms))
        self.backend = backend or NativeMutexBackend()
        self._handle = None
        self._owned = False

    def acquire(self) -> "AgentInstanceLock":
        if self._owned:
            return self
        handle = self.backend.create_mutex(self.name)
        try:
            result = int(self.backend.wait(handle, self.wait_timeout_ms))
        except Exception:
            self.backend.close(handle)
            raise
        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.backend.close(handle)
            if result == WAIT_TIMEOUT:
                raise AgentAlreadyRunningError(
                    "wechat-agent is already running in this Windows session"
                )
            raise RuntimeError(
                f"failed to acquire the wechat-agent session mutex: {result}"
            )
        self._handle = handle
        self._owned = True
        return self

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        owned = self._owned
        self._owned = False
        try:
            if owned:
                self.backend.release(handle)
        finally:
            self.backend.close(handle)

    def __enter__(self) -> "AgentInstanceLock":
        return self.acquire()

    def __exit__(self, *_args) -> None:
        self.close()


__all__ = [
    "AGENT_ALREADY_RUNNING_EXIT_CODE",
    "DEFAULT_AGENT_MUTEX_NAME",
    "DEFAULT_LOCK_WAIT_MS",
    "WAIT_ABANDONED",
    "WAIT_OBJECT_0",
    "WAIT_TIMEOUT",
    "AgentAlreadyRunningError",
    "AgentInstanceLock",
    "NativeMutexBackend",
]
