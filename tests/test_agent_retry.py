from __future__ import annotations

import pytest

from app.agent.actions import ActionVerificationError
from app.agent.retry import (
    LayeredRetry,
    RetryExhausted,
    StaleElementError,
    TransientUiError,
    WeixinUnresponsiveError,
    classify_exception,
)


def test_transient_ui_failure_uses_two_bounded_same_session_retries():
    attempts = []
    delays = []
    notices = []

    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise TransientUiError("control not ready")
        return "ready"

    result = LayeredRetry(sleep=delays.append).run(
        operation,
        on_retry=notices.append,
    )

    assert result == "ready"
    assert attempts == [1, 2, 3]
    assert delays == [0.4, 0.8]
    assert [notice.attempt for notice in notices] == [2, 3]
    assert all(notice.max_attempts == 3 for notice in notices)
    assert all(notice.retry_level == "same_session" for notice in notices)


def test_stale_element_refreshes_before_reusing_invalid_proxy():
    attempts = []
    delays = []
    refreshes = []
    notices = []

    def operation():
        attempts.append(len(attempts) + 1)
        if not refreshes:
            raise StaleElementError("provider disconnected")
        return "ready"

    result = LayeredRetry(sleep=delays.append).run(
        operation,
        soft_refresh=lambda: refreshes.append("refresh"),
        on_retry=notices.append,
    )

    assert result == "ready"
    assert attempts == [1, 2]
    assert delays == [1.6]
    assert refreshes == ["refresh"]
    assert notices[-1].attempt == 2
    assert notices[-1].max_attempts == 2
    assert notices[-1].retry_level == "session_refresh"


def test_unresponsive_weixin_is_never_retried():
    attempts = []
    delays = []

    def operation():
        attempts.append(1)
        raise WeixinUnresponsiveError("window stopped responding")

    with pytest.raises(WeixinUnresponsiveError):
        LayeredRetry(sleep=delays.append).run(operation)

    assert attempts == [1]
    assert delays == []


def test_pre_boundary_action_postcondition_failure_is_transient_ui():
    failure = classify_exception(
        ActionVerificationError(
            "action=uia_bounds_click did not satisfy its postcondition"
        )
    )

    assert isinstance(failure, TransientUiError)
    assert failure.code == "TRANSIENT_UI"


def test_failed_soft_refresh_is_reported_inside_the_same_retry_budget():
    attempts = []
    delays = []

    def operation():
        attempts.append(1)
        raise StaleElementError("old proxy")

    def refresh():
        raise StaleElementError("refresh failed")

    with pytest.raises(RetryExhausted) as raised:
        LayeredRetry(sleep=delays.append).run(
            operation,
            soft_refresh=refresh,
        )

    assert str(raised.value.cause) == "refresh failed"
    assert raised.value.attempt == 2
    assert raised.value.max_attempts == 2
    assert attempts == [1]
    assert delays == []
