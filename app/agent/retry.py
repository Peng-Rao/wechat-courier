from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class AutomationRetryError(RuntimeError):
    code = "AUTOMATION_ERROR"
    retry_kind = "none"
    recoverable = False
    wechat_responsive = True


class TransientUiError(AutomationRetryError):
    code = "TRANSIENT_UI"
    retry_kind = "transient"
    recoverable = True


class StaleElementError(AutomationRetryError):
    code = "STALE_ELEMENT"
    retry_kind = "stale"
    recoverable = True


class WeixinUnresponsiveError(AutomationRetryError):
    code = "WECHAT_UNRESPONSIVE"
    retry_kind = "none"
    recoverable = False
    wechat_responsive = False


class UiaTreeNotReadyError(AutomationRetryError):
    code = "UIA_TREE_NOT_READY_AFTER_REFRESH"
    retry_kind = "none"
    recoverable = False


@dataclass(frozen=True)
class RetryNotice:
    attempt: int
    max_attempts: int
    retry_level: str
    retry_in_ms: int
    error_code: str
    detail: str


class RetryExhausted(RuntimeError):
    def __init__(
        self,
        cause: Exception,
        *,
        attempt: int,
        max_attempts: int,
        retry_level: str,
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.retry_level = retry_level


_STALE_HRESULTS = {
    0x80010108,  # RPC_E_DISCONNECTED
    0x80040201,  # UIA_E_ELEMENTNOTAVAILABLE
    0x800706BA,  # RPC_S_SERVER_UNAVAILABLE
}
_TRANSIENT_HRESULTS = {
    0x80010001,  # RPC_E_CALL_REJECTED
    0x8001010A,  # RPC_E_SERVERCALL_RETRYLATER
}
_STALE_MARKERS = (
    "provider disconnected",
    "rpc server is unavailable",
    "element not available",
    "stale element",
    "controlfromhandle temporarily failed",
    "uia provider disconnected",
    "自动化连接中断",
)
_TRANSIENT_MARKERS = (
    "temporarily",
    "not ready",
    "timed out",
    "timeout",
    "控件未出现",
    "尚未就绪",
    "窗口恢复",
    "置前",
)


def _unsigned_hresult(value: Any) -> int | None:
    try:
        return int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def classify_exception(exc: Exception) -> AutomationRetryError | None:
    retry_error = getattr(exc, "retry_error", None)
    if isinstance(retry_error, AutomationRetryError):
        return retry_error
    if isinstance(exc, AutomationRetryError):
        return exc

    class_name = type(exc).__name__
    if class_name == "ActionVerificationError":
        return TransientUiError(str(exc))
    if class_name in {
        "AccessibilitySafetyError",
        "UnsupportedWeixinVersion",
        "RiskControlError",
    }:
        return None

    hresult = _unsigned_hresult(getattr(exc, "hresult", None))
    if hresult in _STALE_HRESULTS:
        return StaleElementError(str(exc))
    if hresult in _TRANSIENT_HRESULTS:
        return TransientUiError(str(exc))

    detail = str(exc).casefold()
    if any(marker in detail for marker in _STALE_MARKERS):
        return StaleElementError(str(exc))
    if any(marker in detail for marker in _TRANSIENT_MARKERS):
        return TransientUiError(str(exc))
    return None


class LayeredRetry:
    """Bounded retries for read-only and otherwise pre-boundary UIA work."""

    def __init__(self, *, sleep: Callable[[float], None]) -> None:
        self._sleep = sleep

    def run(
        self,
        operation: Callable[[], Any],
        *,
        soft_refresh: Callable[[], Any] | None = None,
        on_retry: Callable[[RetryNotice], Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        last_failure: AutomationRetryError | None = None
        for attempt in range(1, 4):
            try:
                return operation()
            except Exception as exc:
                failure = classify_exception(exc)
                if failure is None or not failure.recoverable:
                    raise
                last_error = exc
                last_failure = failure
                if failure.retry_kind == "stale":
                    if soft_refresh is None:
                        raise
                    self._notify(on_retry, RetryNotice(
                        attempt=attempt + 1,
                        max_attempts=attempt + 1,
                        retry_level="session_refresh",
                        retry_in_ms=1600,
                        error_code=failure.code,
                        detail=str(exc),
                    ))
                    try:
                        soft_refresh()
                    except Exception as refresh_error:
                        raise RetryExhausted(
                            refresh_error, attempt=attempt + 1,
                            max_attempts=attempt + 1, retry_level="session_refresh",
                        ) from refresh_error
                    try:
                        self._sleep(1.6)
                        return operation()
                    except Exception as refresh_error:
                        refresh_failure = classify_exception(refresh_error)
                        if refresh_failure is None or not refresh_failure.recoverable:
                            raise
                        raise RetryExhausted(
                            refresh_error, attempt=attempt + 1,
                            max_attempts=attempt + 1, retry_level="session_refresh",
                        ) from refresh_error
                if attempt == 3:
                    break
                delay = 0.4 if attempt == 1 else 0.8
                maximum = 4 if failure.retry_kind == "stale" and soft_refresh else 3
                self._notify(
                    on_retry,
                    RetryNotice(
                        attempt=attempt + 1,
                        max_attempts=maximum,
                        retry_level="same_session",
                        retry_in_ms=int(delay * 1000),
                        error_code=failure.code,
                        detail=str(exc),
                    ),
                )
                self._sleep(delay)

        assert last_error is not None
        raise RetryExhausted(
            last_error,
            attempt=3,
            max_attempts=3,
            retry_level="same_session",
        ) from last_error

    @staticmethod
    def _notify(callback, notice: RetryNotice) -> None:
        if callback is not None:
            callback(notice)


__all__ = [
    "AutomationRetryError",
    "LayeredRetry",
    "RetryExhausted",
    "RetryNotice",
    "StaleElementError",
    "TransientUiError",
    "UiaTreeNotReadyError",
    "WeixinUnresponsiveError",
    "classify_exception",
]
