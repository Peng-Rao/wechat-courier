from __future__ import annotations

"""Manual stability gate for the production v0.3.1 automation runtime.

The default invocation performs read-only health inspections. Message delivery
requires ``--confirm-send`` and is restricted to File Transfer Assistant.
Friend checks always stop after verified form fill and cancellation; this tool
contains no path that can submit a friend request.
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent.contracts import TaskItem, TaskOptions, TaskRequest
from app.agent.runtime import TaskControl
from app.agent.workflows import WeixinWorkflowEngine


def _emit_collector(events: list[dict[str, Any]]):
    def emit(method: str, payload: dict[str, Any]) -> None:
        if method != "task.event":
            return
        events.append(
            {
                "itemId": str(payload.get("itemId", "")),
                "step": str(payload.get("step", "")),
                "outcome": str(payload.get("outcome", "")),
                "detail": str(payload.get("detail", "")),
                "errorCode": str(payload.get("errorCode", "")),
                "wechatResponsive": bool(
                    payload.get("wechatResponsive", True)
                ),
                "sessionGeneration": int(
                    payload.get("sessionGeneration", 0) or 0
                ),
            }
        )

    return emit


def _inspection_snapshot(inspection: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "processDetected": bool(inspection.get("processDetected", False)),
        "version": str(inspection.get("version", "")),
        "versionSupported": bool(inspection.get("versionSupported", False)),
        "sessionReady": bool(inspection.get("sessionReady", False)),
        "windowResponsive": bool(inspection.get("windowResponsive", False)),
        "sessionGeneration": int(
            inspection.get("sessionGeneration", 0) or 0
        ),
        "degradedReason": str(inspection.get("degradedReason", "")),
        "restorable": bool(inspection.get("restorable", False)),
    }


def _run_soak(
    engine,
    duration_seconds: float,
    interval_seconds: float,
    *,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, Any]:
    """Run a compact, read-only session health soak without task actions."""

    started = monotonic()
    deadline = started + max(0.0, float(duration_seconds))
    checks = 0
    expected_generation: int | None = None
    failures: list[dict[str, Any]] = []
    while monotonic() < deadline:
        checks += 1
        try:
            snapshot = _inspection_snapshot(engine.inspect(), checks)
        except Exception as exc:
            failures.append(
                {
                    "index": checks,
                    "errorType": type(exc).__name__,
                    "detail": str(exc),
                }
            )
            break

        generation = snapshot["sessionGeneration"]
        if expected_generation is None and snapshot["sessionReady"]:
            expected_generation = generation
        healthy = (
            snapshot["processDetected"]
            and snapshot["versionSupported"]
            and snapshot["sessionReady"]
            and snapshot["windowResponsive"]
            and expected_generation is not None
            and generation == expected_generation
        )
        if not healthy:
            failures.append(snapshot)
            # Do not keep querying a provider after Weixin reports hung.
            if not snapshot["windowResponsive"]:
                break

        remaining = deadline - monotonic()
        if remaining > 0:
            sleep(min(max(0.1, interval_seconds), remaining))

    return {
        "ok": checks > 0 and not failures,
        "checks": checks,
        "elapsedSeconds": round(max(0.0, monotonic() - started), 1),
        "sessionGeneration": expected_generation or 0,
        "failures": failures[:10],
    }


def _message_request(count: int) -> TaskRequest:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return TaskRequest(
        task_id="manual-message-" + uuid.uuid4().hex,
        kind="message_send",
        items=tuple(
            TaskItem(
                item_id=f"message-{index + 1}",
                target="文件传输助手",
                message=f"五阿哥微信助手 v0.3.1 稳定性测试 {stamp}-{index + 1:02d}",
            )
            for index in range(count)
        ),
        options=TaskOptions(interval_min=0.5, interval_max=0.8),
    )


def _friend_request(
    account: str,
    greeting: str,
    remark: str,
    count: int,
) -> TaskRequest:
    return TaskRequest(
        task_id="manual-friend-preflight-" + uuid.uuid4().hex,
        kind="friend_add",
        items=tuple(
            TaskItem(
                item_id=f"friend-preflight-{index + 1}",
                account=account,
                greeting=greeting,
                remark=remark,
            )
            for index in range(count)
        ),
        options=TaskOptions(interval_min=0.5, interval_max=0.8),
    )


def run_probe(args) -> dict[str, Any]:
    if args.send_count and not args.confirm_send:
        raise ValueError("--send-count requires --confirm-send")
    if args.friend_preflight_count and not args.friend_account:
        raise ValueError("--friend-preflight-count requires --friend-account")
    if args.friend_preflight_count > 20:
        raise ValueError("friend preflight count cannot exceed 20")

    report: dict[str, Any] = {
        "ok": False,
        "health": [],
        "message": None,
        "friendPreflight": None,
        "recovery": None,
        "messageTail": None,
        "soak": None,
        "events": [],
    }
    engine = WeixinWorkflowEngine(friend_submit_enabled=False)
    try:
        if args.restart_wechat:
            recovery_events = []
            report["recovery"] = engine.recover_wechat(
                args.login_timeout,
                lambda method, payload: recovery_events.append(
                    {
                        "method": method,
                        "status": str(payload.get("status", "")),
                        "remaining": int(payload.get("remaining", 0) or 0),
                    }
                ),
            )
            report["recoveryEvents"] = recovery_events
        for index in range(args.health_count):
            report["health"].append(
                _inspection_snapshot(engine.inspect(), index + 1)
            )
            if index + 1 < args.health_count:
                time.sleep(args.health_interval)

        if args.soak_minutes > 0:
            report["soak"] = _run_soak(
                engine,
                duration_seconds=args.soak_minutes * 60.0,
                interval_seconds=args.soak_interval,
            )

        emit = _emit_collector(report["events"])
        if args.inspect_message_tail:
            driver = engine._get_driver()
            driver.bind_window()
            driver._open_exact_chat("文件传输助手")
            snapshot = driver.message_snapshot()
            report["messageTail"] = [
                {
                    "identity": repr(entry[0]),
                    "text": str(entry[1]),
                }
                for entry in snapshot[-10:]
            ]
            report["composerText"] = driver.read_composer_text()
            buttons = driver._find_scoped_controls(
                hwnd=driver._session.hwnd,
                control_type="ButtonControl",
                visible=True,
            )
            report["visibleButtons"] = [
                {
                    "name": str(getattr(control, "Name", "") or ""),
                    "className": str(
                        getattr(control, "ClassName", "") or ""
                    ),
                    "automationId": str(
                        getattr(control, "AutomationId", "") or ""
                    ),
                }
                for control in buttons
            ]
        if args.send_count:
            report["message"] = engine.run(
                _message_request(args.send_count),
                TaskControl(),
                emit,
            )
        if args.friend_preflight_count:
            report["friendPreflight"] = engine.run(
                _friend_request(
                    args.friend_account,
                    args.greeting,
                    args.remark,
                    args.friend_preflight_count,
                ),
                TaskControl(),
                emit,
            )
        driver = engine._get_driver()
        responsive = getattr(driver, "ensure_window_responsive", None)
        if callable(responsive) and getattr(driver, "_session", None) is not None:
            responsive()
        report["ok"] = all(
            item["processDetected"]
            and item["versionSupported"]
            and item["windowResponsive"]
            and (item["sessionReady"] or item["restorable"])
            for item in report["health"]
        )
        if report["message"] is not None:
            report["ok"] = report["ok"] and (
                report["message"].get("outcome") == "success"
            )
        if report["friendPreflight"] is not None:
            report["ok"] = report["ok"] and (
                report["friendPreflight"].get("outcome") == "success"
            )
        if report["soak"] is not None:
            report["ok"] = report["ok"] and report["soak"]["ok"]
        return report
    finally:
        engine.close()


def _parse_args(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-count", type=int, default=1)
    parser.add_argument("--health-interval", type=float, default=0.5)
    parser.add_argument("--soak-minutes", type=float, default=0.0)
    parser.add_argument("--soak-interval", type=float, default=10.0)
    parser.add_argument("--restart-wechat", action="store_true")
    parser.add_argument("--login-timeout", type=int, default=90)
    parser.add_argument("--send-count", type=int, default=0)
    parser.add_argument("--confirm-send", action="store_true")
    parser.add_argument("--inspect-message-tail", action="store_true")
    parser.add_argument("--friend-preflight-count", type=int, default=0)
    parser.add_argument("--friend-account")
    parser.add_argument("--greeting", default="你好，我是五阿哥，方便认识一下吗？")
    parser.add_argument("--remark", default="新联系人")
    args = parser.parse_args(argv)
    args.health_count = max(1, min(100, int(args.health_count)))
    args.health_interval = max(0.1, min(10.0, float(args.health_interval)))
    args.soak_minutes = max(0.0, min(180.0, float(args.soak_minutes)))
    args.soak_interval = max(1.0, min(60.0, float(args.soak_interval)))
    args.login_timeout = max(30, min(300, int(args.login_timeout)))
    args.send_count = max(0, min(20, int(args.send_count)))
    args.friend_preflight_count = max(
        0, min(21, int(args.friend_preflight_count))
    )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report = run_probe(_parse_args(argv))
    except Exception as exc:
        report = {
            "ok": False,
            "errorType": type(exc).__name__,
            "error": str(exc),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
