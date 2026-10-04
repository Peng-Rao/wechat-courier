"""Opt-in 1.0.0 acceptance. Default: write a plan, never touch the desktop.

GUI mode drives a packaged Courier exclusively through UIA. Source and RPC
are comparison modes, not substitutes for GUI acceptance. See README for the
read-only QML accessibility contract and explicit live-run authorization.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import platform
import re
import subprocess
import struct
import sys
import time
import traceback
import uuid
import zlib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEND_TARGET = "\u6587\u4ef6\u4f20\u8f93\u52a9\u624b"
FRIEND_ACCOUNT = "18896904196"
STATES = ("visible", "minimized", "tray")
MAX_NODES = 512
MAX_EVENTS = 256
PROFILE_COUNTS = {"smoke": 6, "independent": 40, "delivery": 2, "images": 3}
GUI_NAMES = {
    "editor": ["messageWorkspaceTab", "friendWorkspaceTab", "messageRecipientsInput",
               "messageTemplateInput", "startMessageButton", "settingsButton",
               "acceptanceEditorState", "acceptanceTaskState"],
    "settings": ["settingsSection0", "settingsMessageIntervalMin", "settingsMessageIntervalMax", "settingsCloseButton"],
    "friend": ["importFriendsButton", "startFriendsButton", "friendAccountField",
               "friendRangeStart", "friendRangeEnd", "selectFriendRangeButton"],
    "monitor": ["taskReturnToEditorButton", "taskStopButton", "acceptanceTaskState"],
    "delivery": ["messageAddFileButton", "messageRemoveFileButton-0"],
}


def make_case(run_id, index):
    kind = "message_send" if index % 2 == 0 else "friend_add"
    marker = f"v100-{run_id}-{index + 1:04d}"
    item = {"itemId": marker + "-item"}
    if kind == "message_send":
        item.update(target=SEND_TARGET, message=f"Fuge WeChat Assistant acceptance {marker}")
    else:
        item.update(account=FRIEND_ACCOUNT, greeting=f"Acceptance preflight {marker}",
                    remark=f"v100-{index + 1:04d}\u5988\u5988")
    case = {"index": index + 1, "windowState": STATES[(index // 2) % 3],
            "request": {"taskId": marker, "kind": kind, "items": [item],
                        "options": {"intervalMin": 2.0 if kind == "message_send" else 15.0,
                                    "intervalMax": 3.0 if kind == "message_send" else 30.0,
                                    "unknownPolicy": "continue", "filePaths": []}}}
    if kind == "friend_add":
        case["request"]["options"]["friendBatchLimit"] = 100
    return case


def benign_content(task_id):
    return f"Fuge WeChat Assistant 1.0.0 benign acceptance attachment\nTask: {task_id}\nNo private data.\n".encode("ascii")


def benign_image(task_id):
    """A small task-specific PNG with no desktop or private content."""
    color = hashlib.sha256(task_id.encode("ascii")).digest()
    width, height = 128, 96
    pixels = b"".join(b"\0" + bytes(color[:3]) * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def make_plan(run_id, count=None, *, profile="smoke", artifact_dir=None):
    count = count if count is not None else PROFILE_COUNTS.get(profile, 6)
    if profile in {"delivery", "images"}:
        if artifact_dir is None:
            raise ValueError("Delivery planning requires a dedicated artifact directory")
        cases = []
        for index in range(PROFILE_COUNTS[profile]):
            case = make_case(run_id, index * 2)
            case.update(index=index + 1, windowState="visible", delivery=True)
            request = case["request"]
            extensions = ([".png"] if index == 0 else [".txt"] if index == 1 else [".png", ".txt"]) if profile == "images" else [".txt"]
            paths = [Path(artifact_dir).resolve() / (request["taskId"] + ext) for ext in extensions]
            path = paths[0]
            request["options"].update(filePaths=[str(p) for p in paths])
            content = benign_image(request["taskId"]) if path.suffix == ".png" else benign_content(request["taskId"])
            case["attachment"] = {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(),
                                  "size": len(content)}
            cases.append(case)
        return cases
    return [make_case(run_id, index) for index in range(count)]


def materialize_delivery(case, artifact_dir):
    for value in case["request"]["options"]["filePaths"]:
        path = Path(value)
        if path.parent.resolve() != Path(artifact_dir).resolve():
            raise ValueError("Generated attachment must stay in the run directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        content = benign_image(case["request"]["taskId"]) if path.suffix == ".png" else benign_content(case["request"]["taskId"])
        with path.open("xb") as stream:
            stream.write(content)


def validate_request(request, *, delivery=False, artifact_dir=None):
    items = request.get("items", [])
    if len(items) != 1 or not request.get("taskId"):
        raise ValueError("Each independent task must contain exactly one item and a taskId")
    options = request.get("options", {})
    if "useForward" in options:
        raise ValueError("Retired useForward option is not permitted")
    if options.get("filePaths"):
        if not delivery or request.get("kind") != "message_send" or artifact_dir is None:
            raise ValueError("Attachments require explicit delivery authorization")
        paths = options.get("filePaths", [])
        if not 1 <= len(paths) <= 2 or len(set(paths)) != len(paths):
            raise ValueError("Delivery requires one or two distinct generated benign attachments")
        for value in paths:
            path = Path(value).resolve(strict=True)
            expected = Path(artifact_dir).resolve() / (request["taskId"] + path.suffix)
            content = benign_image(request["taskId"]) if path.suffix == ".png" else benign_content(request["taskId"])
            if path.suffix not in {".png", ".txt"} or path != expected or path.stat().st_size > 65536 or path.read_bytes() != content:
                raise ValueError("Attachment path/content does not match the generated acceptance file")
    item = items[0]
    if request.get("kind") == "message_send":
        if item.get("target") != SEND_TARGET or not item.get("message"):
            raise ValueError("Only File Transfer Assistant text sends are permitted")
    elif request.get("kind") == "friend_add":
        if item.get("account") != FRIEND_ACCOUNT:
            raise ValueError("Only the fixed friend preflight account is permitted")
    else:
        raise ValueError("Unsupported acceptance task kind")


def semantic_items(items):
    return [{key: value for key, value in item.items() if key not in {"itemId", "sourceRow", "sourceFileRow"}} for item in items]


def friend_import_rows(item):
    # A known inline suffix makes the fixture independent of the user's defaults.
    return [["\u59d3\u540d", "\u8d26\u53f7", "\u6253\u62db\u547c\u8bed"],
            [item["remark"], item["account"], item["greeting"]]]


def result_evidence(result):
    keys = {"taskId", "mode", "outcome", "done", "total", "success", "error", "unknown",
            "stopped", "windowStateEvidence", "settingsEvidence", "echoedItems", "buildFingerprint",
            "active", "phase", "elapsedSeconds", "elapsedLabel"}
    clean = {key: value for key, value in result.items() if key in keys}
    event_keys = {"taskId", "itemId", "step", "outcome", "errorCode", "attempt",
                  "maxAttempts", "retryLevel", "wechatResponsive", "itemElapsedMs", "riskKind", "timestamp"}
    clean["events"] = [{key: value for key, value in event.items() if key in event_keys}
                       for event in result.get("events", [])[:MAX_EVENTS]]
    cleanup, health = result.get("cleanup", {}), result.get("health", {})
    clean["cleanup"] = None if cleanup is None else {
        key: value for key, value in cleanup.items() if key in {"success", "reasonCode"}}
    clean["health"] = None if health is None else {
        key: value for key, value in health.items()
        if key in {"windowEnabled", "windowResponsive", "sessionReady", "sequence",
                   "sessionGeneration", "agentInstanceId", "checkedAt", "reasonCode"}}
    if health is not None and "blockingWindow" in health:
        blocker = result["health"]["blockingWindow"]
        clean["health"]["blockingWindow"] = (
            {key: value for key, value in blocker.items() if key in {"hwnd", "pid", "visible", "enabled"}}
            if isinstance(blocker, dict) else blocker
        )
    if "deliveryEvidence" in result:
        evidence = result["deliveryEvidence"]
        clean["deliveryEvidence"] = {
            "taskId": evidence.get("taskId", ""),
            "boundaries": {name: {key: value for key, value in boundary.items()
                                  if key in {"started", "completed", "verified"} and type(value) in (int, bool)}
                           for name, boundary in evidence.get("boundaries", {}).items()
                           if name in {"text", "attachment"}},
            **{field: {key: value for key, value in evidence.get(field, {}).items()
                       if key in {"text", "attachment"} and type(value) is int}
               for field in ("baseline", "observed")},
        }
    if "deliveryVerificationError" in result:
        clean["deliveryVerificationError"] = result["deliveryVerificationError"]
    return clean


def validate_result(case, result, seen_ids):
    request = case["request"]
    if result.get("active") is True:
        raise ValueError("GUI task remains active; interrupted snapshot is not a terminal success")
    task_id = result.get("taskId")
    if not task_id or task_id in seen_ids:
        raise ValueError("Missing or reused task ID")
    if result.get("mode") == "gui":
        if semantic_items(result.get("echoedItems", [])) != semantic_items(request["items"]):
            raise ValueError("GUI result is not correlated to the requested item")
    elif task_id != request["taskId"]:
        raise ValueError("Stale or unrelated task result")
    if result.get("cleanup", {}).get("success") is not True:
        raise ValueError("Task cleanup is missing or unsuccessful")
    health = result.get("health", {})
    if any(health.get(key) is not True for key in ("windowEnabled", "windowResponsive", "sessionReady")):
        raise ValueError("Terminal health is missing, disabled, unresponsive, or not session-ready")
    if "blockingWindow" not in health or health["blockingWindow"] is not None:
        raise ValueError("Terminal health has missing blocker evidence or a residual blockingWindow")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", result.get("buildFingerprint", "")):
        raise ValueError("Missing valid runtime buildFingerprint")
    if (result.get("outcome") != "success" or result.get("done") != 1
            or result.get("total") != 1 or result.get("success") != 1
            or any(result.get(key, 0) != 0 for key in ("error", "unknown", "stopped"))):
        raise ValueError("Task did not complete with exactly one verified success")
    events = result.get("events", [])
    terminal = "send_verified" if request["kind"] == "message_send" else "preflight_completed"
    if request["kind"] == "friend_add" and any(
        str(event.get("step", "")).startswith("submit_") for event in events
    ):
        raise ValueError("Forbidden friend submit evidence")
    if not any(event.get("taskId") == task_id and event.get("step") == terminal
               and event.get("outcome") == "success" for event in events):
        raise ValueError("Missing task-correlated terminal verification evidence")
    if case.get("delivery"):
        validate_delivery(case, result)


def validate_delivery(case, result):
    if result.get("deliveryVerificationError"):
        raise ValueError("Post-send evidence collection failed; do not replay the completed task")
    evidence = result.get("deliveryEvidence", {})
    if evidence.get("taskId") != result["taskId"]:
        raise ValueError("Missing task-correlated delivery sub-boundary evidence")
    names = {"text", "attachment"}
    boundaries = evidence.get("boundaries", {})
    if set(boundaries) != names or any(
        boundary.get("started") != 1 or boundary.get("completed") != 1 or boundary.get("verified") is not True
        for boundary in boundaries.values()
    ):
        raise ValueError("Delivery sub-boundary missing, unverified, or repeated")
    expected = {"text": 1, "attachment": len(case["request"]["options"]["filePaths"])}
    baseline = evidence.get("baseline", {})
    observed = evidence.get("observed", {})
    if baseline.get("text") != 0 or baseline.get("attachment") != 0:
        raise ValueError("Unique delivery marker already existed before task")
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ValueError("Delivery count mismatch or duplicate observed")


def delivery_counts(case, before, after):
    text = case["request"]["items"][0]["message"]
    paths = [Path(value) for value in case["request"]["options"]["filePaths"]]
    filenames = {path.name for path in paths}
    has_image = any(path.suffix == ".png" for path in paths)
    old_ids = {row["id"] for row in before}

    def selected(rows, kind):
        if kind == "text":
            return {row["id"] for row in rows if row["text"].strip() == text}
        return {row["id"] for row in rows
                if filenames.intersection(line.strip() for line in row["text"].splitlines())
                or (has_image and row.get("isImage") is True and row["id"] not in old_ids)}

    baseline = {key: len(selected(before, key)) for key in ("text", "attachment")}
    observed = {key: len(selected(after, key)) for key in ("text", "attachment")}
    return baseline, observed


DELIVERY_ACTIONS = {"trigger_send", "verify_sent", "send_files"}


def delivery_boundaries(case, records):
    def boundary(action, *, length=None, value=None):
        relevant = [row for row in records if row["action"] == action]
        starts = [row for row in relevant if row["outcome"] == "started"]
        finished = [row for row in relevant if row["outcome"] != "started"]
        good = (len(starts) == len(finished) == 1 and bool(starts[0].get("actionId"))
                and starts[0]["actionId"] == finished[0].get("actionId")
                and finished[0]["outcome"] == "success")
        if length is not None:
            good = good and finished[0].get("result", {}).get("length") == length
        if value is not None:
            good = good and finished[0].get("result", {}).get("value") is value
        return {"started": len(starts), "completed": len(finished), "verified": bool(good)}

    result = {"text": boundary("trigger_send"),
              "attachment": boundary("send_files", length=len(case["request"]["options"]["filePaths"]))}
    result["text"]["verified"] &= boundary("verify_sent", value=True)["verified"]
    if any(row["action"] not in DELIVERY_ACTIONS for row in records):
        raise ValueError("Unexpected delivery action implies an unplanned or repeated send")
    return result


def read_delivery_actions(log_dir, task_id, fingerprint):
    """Read a bounded set of already-redacted production diagnostics, never raw context."""
    records = []
    names = ["uia-diagnostics.jsonl" + suffix for suffix in (".3", ".2", ".1", "")]
    for name in names:
        path = Path(log_dir) / name
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            stream.seek(0, 2)
            offset = max(0, stream.tell() - 2 * 1024 * 1024)
            stream.seek(offset)
            lines = stream.read(2 * 1024 * 1024).splitlines()
            if offset:
                lines = lines[1:]  # Discard a potentially truncated first record.
        for line in lines:
            if len(line) > 65536:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("taskId") != task_id or row.get("action") not in DELIVERY_ACTIONS:
                continue
            if row.get("build", {}).get("buildFingerprint") != fingerprint:
                raise ValueError("Delivery diagnostics do not match the runtime build fingerprint")
            records.append({key: row[key] for key in ("action", "actionId", "outcome", "result") if key in row})
            if len(records) > 64:
                raise ValueError("Delivery action evidence exceeds budget")
    return records


def attach_delivery_evidence(case, result, baseline, desktop, log_dir):
    if (not case.get("delivery") or result.get("outcome") != "success"
            or result.get("cleanup", {}).get("success") is not True):
        return result
    try:
        after = desktop.delivery_snapshot()
        initial, observed = delivery_counts(case, baseline, after)
        records = read_delivery_actions(log_dir, result["taskId"], result["buildFingerprint"])
        result["deliveryEvidence"] = {"taskId": result["taskId"], "baseline": initial, "observed": observed,
                                      "boundaries": delivery_boundaries(case, records),
                                      "observationScope": "current_chat_uia_message_list"}
    except Exception as exc:
        result["deliveryVerificationError"] = failure_evidence(exc)
    return result


def normalized_options(options):
    result = dict(options)
    result["filePaths"] = [os.path.normcase(os.path.normpath(path)) for path in options.get("filePaths", [])]
    return result


def run_schedule(run_case, run_id, profile, interval, duration, *,
                 monotonic=time.monotonic, sleep=time.sleep, checkpoint=None, artifact_dir=None):
    started = monotonic()
    report = {"ok": False, "tasks": [], "stoppedAfterFirstFailure": False}
    seen = set()
    fingerprint = None
    index = 0
    limit = PROFILE_COUNTS.get(profile)
    delivery_plan = make_plan(run_id, profile=profile, artifact_dir=artifact_dir) if profile in {"delivery", "images"} else None
    while (index < limit if limit is not None else monotonic() - started < duration):
        case = delivery_plan[index] if delivery_plan is not None else make_case(run_id, index)
        entry = {"case": case, "ok": False}
        report["tasks"].append(entry)
        try:
            validate_request(case["request"], delivery=profile in {"delivery", "images"}, artifact_dir=artifact_dir)
            result = run_case(case)
            entry["result"] = result
            validate_result(case, result, seen)
            if fingerprint is not None and result["buildFingerprint"] != fingerprint:
                raise ValueError("Runtime buildFingerprint changed between independent tasks")
            fingerprint = result["buildFingerprint"]
            report["runtimeBuildFingerprint"] = fingerprint
            seen.add(result["taskId"])
            entry["ok"] = True
        except Exception as exc:
            entry.update(errorType=type(exc).__name__, error=str(exc)[:2000])
            if isinstance(exc, WorkerFailure):
                entry["failure"] = exc.evidence
            report["stoppedAfterFirstFailure"] = True
            if checkpoint:
                checkpoint(report)
            break
        if checkpoint:
            checkpoint(report)
        index += 1
        if limit is not None and index == limit:
            break
        remaining = duration - (monotonic() - started)
        sleep(interval if limit is not None else max(0, min(interval, remaining)))
    report["elapsedSeconds"] = round(monotonic() - started, 3)
    report["ok"] = bool(report["tasks"]) and all(t["ok"] for t in report["tasks"])
    if profile == "soak":
        report["ok"] = report["ok"] and report["elapsedSeconds"] >= duration and index >= 6
    return report


def hash_files(root, files):
    manifest = []
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        file_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                file_hash.update(block)
        entry = {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
                 "sha256": file_hash.hexdigest()}
        digest.update(json.dumps(entry, sort_keys=True).encode("utf-8"))
        manifest.append(entry)
    return {"sha256": digest.hexdigest(), "fileCount": len(manifest), "files": manifest}


def hash_tree(root):
    root = Path(root)
    return hash_files(root, [p for p in root.rglob("*") if p.is_file()])


def build_fingerprint(args):
    files = [REPO_ROOT / "main.py", REPO_ROOT / "agent_main.py", Path(__file__)]
    for folder in ("app", "src", "qml", "build"):
        files.extend(p for p in (REPO_ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts
                     and p.suffix in {".py", ".qml", ".qrc", ".json", ".spec"})
    result = {"source": hash_files(REPO_ROOT, files), "python": sys.version,
              "platform": platform.platform(), "executable": sys.executable}
    for label, command in (("gitHead", ["git", "rev-parse", "HEAD"]),
                           ("gitStatus", ["git", "status", "--short"])):
        try:
            result[label] = subprocess.check_output(command, cwd=REPO_ROOT, timeout=5,
                                                     text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.SubprocessError):
            result[label] = "unavailable"
    executable = args.gui_exe if args.mode == "gui" else args.agent_exe
    if executable:
        path = Path(executable).resolve(strict=True)
        result["packagePath"] = str(path)
        result["package"] = hash_tree(path.parent)
    return result


def control_center(control):
    if not control.IsEnabled or control.IsOffscreen:
        raise ValueError("Control must be visible and enabled")
    rect = control.BoundingRectangle
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise ValueError("Control has empty accessible bounds")
    return (int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2))


def invoke_control(control, bounds_click):
    if not control.IsEnabled or control.IsOffscreen:
        raise ValueError("Control must be visible and enabled")
    pattern = control.GetInvokePattern()
    if pattern is not None:
        # An exception after Invoke may mean the action already happened. Never retry it.
        pattern.Invoke()
    else:
        control_center(control)
        bounds_click(control)


def find_named(root, name, max_nodes=MAX_NODES):
    pending = deque([root])
    matches = []
    visited = 0
    while pending:
        control = pending.popleft()
        visited += 1
        if visited > max_nodes:
            raise ValueError("UIA tree node budget exceeded")
        if control.Name == name and not control.IsOffscreen:
            matches.append(control)
        children = control.GetChildren()
        if len(children) + len(pending) + visited > max_nodes:
            raise ValueError("UIA tree node budget exceeded")
        pending.extend(children)
    if len(matches) > 1:
        raise ValueError(f"UIA name is ambiguous: {name}")
    if not matches:
        raise LookupError(f"Accessible.name missing: {name}")
    return matches[0]


def file_dialog_open_control(root):
    """Resolve the classic button or Windows 11 split-button Open control."""

    classic = root.ButtonControl(AutomationId="1", searchDepth=8)
    if classic.Exists(1, 0.1):
        return classic
    # AutomationId is only unique among siblings: file-list entries also use 1.
    modern = root.SplitButtonControl(AutomationId="1", searchDepth=8)
    if (
        modern.Exists(1, 0.1)
        and modern.ControlTypeName == "SplitButtonControl"
        and modern.AutomationId == "1"
    ):
        return modern
    raise LookupError(
        "Native file dialog Open AutomationId=1 Button/SplitButton unavailable"
    )


class AcceptanceTimeout(TimeoutError):
    def __init__(self, stage, timeout):
        self.stage, self.timeout = stage, timeout
        super().__init__(f"Deadline exceeded at {stage} after {timeout}s")


class WorkerFailure(RuntimeError):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(f"{evidence.get('errorType')}: worker failed (see safe failure evidence)")


def failure_evidence(exc):
    frames = traceback.extract_tb(exc.__traceback__)[-12:]
    result = {"errorType": type(exc).__name__, "traceback": [
        {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno} for frame in frames
    ]}
    if isinstance(exc, AcceptanceTimeout):
        result.update(stage=exc.stage, timeoutSeconds=exc.timeout)
    if isinstance(exc, RuntimeError):
        match = re.fullmatch(
            r"cursor position mismatch: expected=\((-?\d+), (-?\d+)\), actual=\((-?\d+), (-?\d+)\)",
            str(exc),
        )
        if match:
            coordinates = [int(value) for value in match.groups()]
            result["cursor"] = {"expected": coordinates[:2], "actual": coordinates[2:]}
    return result


def wait_until(callback, timeout=10, *, stage="control_or_state"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = callback()
            if value:
                return value
        except LookupError as exc:
            last = exc
        time.sleep(0.2)
    raise AcceptanceTimeout(stage, timeout)


def hide_to_tray(resolve, invoke, click, hidden, owner_valid, notice, *, wait=wait_until):
    def identity(control):
        runtime_id = tuple(control.GetRuntimeId())
        if not runtime_id or not owner_valid(control):
            raise ValueError("Tray close has no stable identity or verified main-window owner")
        return runtime_id, control.ProcessId, control.Name

    notice({"stage": "wechat.tray.find_close"})
    close = wait_until(resolve, timeout=3, stage="wechat.tray.find_close")
    reference = identity(close)
    notice({"stage": "wechat.tray.invoke_close"})
    invoke(close)
    try:
        notice({"stage": "wechat.tray.verify_hidden.invoke", "timeoutSeconds": 3})
        wait(hidden, timeout=3, stage="wechat.tray.verify_hidden.invoke")
        return
    except TimeoutError:
        pass
    if hidden():
        return
    notice({"stage": "wechat.tray.revalidate_close"})
    current = wait_until(resolve, timeout=3, stage="wechat.tray.revalidate_close")
    if identity(current) != reference:
        raise ValueError("Tray close identity changed; refusing fallback")
    notice({"stage": "wechat.tray.bounds_fallback"})
    click(current)
    notice({"stage": "wechat.tray.verify_hidden.bounds", "timeoutSeconds": 3})
    wait(hidden, timeout=3, stage="wechat.tray.verify_hidden.bounds")


def window_diagnostics(pids=()):
    """No UIA: at most 24 top-level windows, 100 ms responsiveness per window."""
    if os.name != "nt":
        return {"unavailable": "Win32 required"}
    import win32con
    import win32gui
    import win32process

    windows = []
    started = time.monotonic()

    def collect(hwnd, _):
        if len(windows) >= 24 or time.monotonic() - started >= 3:
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        title = win32gui.GetWindowText(hwnd)
        if pid not in pids and title.casefold() not in {"\u5fae\u4fe1", "weixin", "wechat"}:
            return True
        row = {"hwnd": hwnd, "pid": pid, "titleSha256": hashlib.sha256(title.encode()).hexdigest(),
               "className": win32gui.GetClassName(hwnd), "visible": bool(win32gui.IsWindowVisible(hwnd)),
               "minimized": bool(win32gui.IsIconic(hwnd)), "bounds": win32gui.GetWindowRect(hwnd)}
        try:
            win32gui.SendMessageTimeout(hwnd, win32con.WM_NULL, 0, 0,
                                        win32con.SMTO_ABORTIFHUNG, 100)
            row["responsive"] = True
        except Exception as exc:
            row.update(responsive=False, error=str(exc)[:160])
        windows.append(row)
        return True

    try:
        win32gui.EnumWindows(collect, None)
    except Exception as exc:
        return {"windows": windows, "enumerationError": str(exc)[:200]}
    return {"windows": windows, "elapsedSeconds": round(time.monotonic() - started, 3)}


class WindowsDpiApi:
    def __init__(self):
        import ctypes

        self.ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        for name, args, restype in (
            ("SetProcessDpiAwarenessContext", [ctypes.c_void_p], ctypes.c_int),
            ("SetThreadDpiAwarenessContext", [ctypes.c_void_p], ctypes.c_void_p),
            ("GetThreadDpiAwarenessContext", [], ctypes.c_void_p),
            ("GetAwarenessFromDpiAwarenessContext", [ctypes.c_void_p], ctypes.c_int),
            ("AreDpiAwarenessContextsEqual", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
        ):
            function = getattr(self.user32, name)
            function.argtypes, function.restype = args, restype

    def set_process(self):
        self.ctypes.set_last_error(0)
        return bool(self.user32.SetProcessDpiAwarenessContext(self.ctypes.c_void_p(-4)))

    def set_thread(self):
        return self.user32.SetThreadDpiAwarenessContext(self.ctypes.c_void_p(-4))

    def last_error(self):
        return self.ctypes.get_last_error()

    def snapshot(self):
        context = self.user32.GetThreadDpiAwarenessContext()
        return {"threadAwareness": self.user32.GetAwarenessFromDpiAwarenessContext(context),
                "perMonitorV2": bool(self.user32.AreDpiAwarenessContextsEqual(context, self.ctypes.c_void_p(-4)))}


def configure_dpi_awareness(api=None):
    api = api or WindowsDpiApi()
    process_set = api.set_process()
    process_error = 0 if process_set else api.last_error()
    previous_context = api.set_thread()
    result = {"processSet": process_set, "processError": process_error,
              "threadSet": bool(previous_context), **api.snapshot()}
    if not previous_context or result["threadAwareness"] != 2 or result["perMonitorV2"] is not True:
        raise ValueError("DPI awareness could not be verified as per-monitor V2")
    return result


def clamp_window_to_work_area(bounds, work_area):
    left, top, right, bottom = bounds
    work_left, work_top, work_right, work_bottom = work_area
    width, height = right - left, bottom - top
    work_width, work_height = work_right - work_left, work_bottom - work_top
    if min(width, height, work_width, work_height) <= 0:
        raise ValueError("Window or monitor work area has invalid geometry")
    if width > work_width or height > work_height:
        raise ValueError("Window cannot fit monitor work area while preserving size")
    x = min(max(left, work_left), work_right - width)
    y = min(max(top, work_top), work_bottom - height)
    return x, y, x + width, y + height


class Desktop:
    def __init__(self, notice=lambda value: None):
        dpi = configure_dpi_awareness()
        notice({"dpi": dpi})
        import win32api
        import win32gui
        import win32process
        from src.core import uiautomation

        self.win = win32gui
        self.monitors = win32api
        self.proc = win32process
        self.uia = uiautomation
        self.notice = notice
        self.dpi_api = WindowsDpiApi()

    def windows(self, pid=None, class_name=None):
        found = []

        def collect(hwnd, _):
            if pid is not None and self.proc.GetWindowThreadProcessId(hwnd)[1] != pid:
                return True
            if class_name is not None and self.win.GetClassName(hwnd) != class_name:
                return True
            found.append(hwnd)
            return True

        self.win.EnumWindows(collect, None)
        return found

    def root(self, hwnd):
        return self.uia.ControlFromHandle(hwnd)

    def activate_gui(self, hwnd, pid, *, role="gui"):
        from src.core.win32 import _foreground_with_thread_handshake

        def verify_owner():
            if (not self.win.IsWindow(hwnd)
                    or self.proc.GetWindowThreadProcessId(hwnd)[1] != pid
                    or not self.win.IsWindowEnabled(hwnd)):
                raise ValueError("GUI window identity changed or window disabled")

        self.notice({"stage": role + ".activate.verify_before"})
        verify_owner()
        activated = True
        if self.win.GetForegroundWindow() != hwnd:
            self.notice({"stage": role + ".activate.handshake"})
            activated = _foreground_with_thread_handshake(hwnd)
        self.notice({"stage": role + ".activate.verify_after"})
        verify_owner()
        foreground = self.win.GetForegroundWindow()
        self.notice({"stage": role + ".activate.foreground", "hwnd": hwnd,
                     "pid": pid, "foregroundHwnd": foreground})
        if not activated or foreground != hwnd:
            raise ValueError("GUI foreground activation not verified")

    def fit_main_window(self, hwnd, pid):
        import win32con

        self.notice({"stage": "wechat.fit_main.measure"})
        dpi = self.dpi_api.snapshot()
        if dpi["threadAwareness"] != 2 or dpi["perMonitorV2"] is not True:
            raise ValueError("Physical window placement requires per-monitor-V2 DPI awareness")

        def verify_owner():
            if (not self.win.IsWindow(hwnd)
                    or self.proc.GetWindowThreadProcessId(hwnd)[1] != pid
                    or not self.win.IsWindowEnabled(hwnd)):
                raise ValueError("Main window changed or became disabled during placement")

        verify_owner()
        before = tuple(self.win.GetWindowRect(hwnd))
        monitor = self.monitors.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST.
        work = tuple(self.monitors.GetMonitorInfo(monitor)["Work"])
        desired = clamp_window_to_work_area(before, work)
        evidence = {"before": list(before), "workArea": list(work), "desired": list(desired),
                    "coordinateSpace": "physical_per_monitor_v2", "moved": desired != before}
        self.notice({"stage": "wechat.fit_main.geometry", **evidence})
        if desired != before:
            verify_owner()
            self.win.SetWindowPos(hwnd, 0, desired[0], desired[1], 0, 0,
                                  win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                                  | win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER)

        def placed():
            verify_owner()
            current = tuple(self.win.GetWindowRect(hwnd))
            if (current[2] - current[0], current[3] - current[1]) != (before[2] - before[0], before[3] - before[1]):
                raise ValueError("Main window dimensions changed during size-preserving placement")
            return current if clamp_window_to_work_area(current, work) == current else None

        self.notice({"stage": "wechat.fit_main.verify", "timeoutSeconds": 3})
        evidence["after"] = list(wait_until(placed, 3, stage="wechat.fit_main.verify"))
        self.notice({"stage": "wechat.fit_main.completed", **evidence})
        return evidence

    def click(self, control):
        x, y = control_center(control)
        dpi = self.dpi_api.snapshot()
        self.notice({"stage": "uia.bounds_click", "expectedPoint": [x, y], "dpi": dpi})
        if dpi["threadAwareness"] != 2 or not dpi["perMonitorV2"]:
            raise ValueError("DPI awareness changed before a guarded bounds click")
        # The point comes only from the current accessible control, never a constant.
        hit = self.uia.ControlFromPoint(x, y)
        if hit.ProcessId != control.ProcessId:
            raise ValueError("Accessible control is covered by another process")
        self.uia.Click(x, y)

    def invoke(self, control):
        invoke_control(control, self.click)

    def set_toggle(self, control, enabled, read_state):
        if read_state() is enabled:
            return
        control_center(control)
        pattern = control.GetTogglePattern()
        if pattern is not None:
            if int(pattern.ToggleState) not in (0, 1):
                raise ValueError("Indeterminate forwarding toggle")
            pattern.Toggle()
        else:
            self.click(control)
        wait_until(lambda: read_state() is enabled, 3, stage="gui.forward_toggle.readback")

    def delivery_snapshot(self):
        from src.core.win32 import find_wechat_window_refs

        self.notice({"stage": "delivery.readonly_chat_snapshot"})
        windows = find_wechat_window_refs()
        if len(windows) != 1:
            raise ValueError("Delivery audit requires one verified WeChat main window")
        root = self.root(windows[0].hwnd)
        title_id = ("content_view.top_content_view.title_h_view.left_v_view."
                    "left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label")
        # 4.1.13.65 nests the title label at depth 22 beneath the main window.
        title = self.uia.Control(searchFromControl=root, AutomationId=title_id, searchDepth=24)
        if not title.Exists(1, 0.1) or title.Name != SEND_TARGET:
            raise ValueError("Delivery audit requires File Transfer Assistant already selected")
        message_list = self.uia.Control(searchFromControl=root, AutomationId="chat_message_list", searchDepth=20)
        if not message_list.Exists(1, 0.1):
            raise LookupError("Delivery message list is inaccessible")
        pending = deque([message_list])
        visited, result, seen = 0, [], set()
        accepted = {"mmui::ChatTextItemView", "mmui::ChatBubbleItemView", "mmui::ChatFileItemView",
                    "mmui::ChatBubbleReferItemView"}
        while pending:
            node = pending.popleft()
            visited += 1
            if visited > MAX_NODES:
                raise ValueError("Delivery observation node budget exceeded")
            if node.ClassName in accepted:
                runtime_id = tuple(node.GetRuntimeId())
                if not runtime_id:
                    raise ValueError("Delivery bubble has no stable runtime identity")
                if runtime_id not in seen:
                    result.append({"id": hashlib.sha256(repr(runtime_id).encode()).hexdigest(), "text": node.Name,
                                   "isImage": node.ClassName == "mmui::ChatBubbleReferItemView" and node.Name in {"图片", "[图片]"}})
                    seen.add(runtime_id)
            children = node.GetChildren()
            if visited + len(pending) + len(children) > MAX_NODES:
                raise ValueError("Delivery observation node budget exceeded")
            pending.extend(children)
        return result

    def read(self, control):
        pattern = control.GetValuePattern()
        if pattern is not None:
            return pattern.Value
        pattern = control.GetTextPattern()
        if pattern is None:
            raise ValueError(f"No readable Value/Text pattern: {control.Name}")
        return pattern.DocumentRange.GetText(-1).rstrip("\r\n")

    def fill(self, control, value):
        control_center(control)
        pattern = control.GetValuePattern()
        if pattern is not None:
            pattern.SetValue(value)
        else:
            import pyperclip

            previous = pyperclip.paste()
            self.click(control)
            try:
                pyperclip.copy(value)
                self.uia.SendKeys("{Ctrl}a{Ctrl}v")
                wait_until(lambda: self.read(control) == value, 2)
            finally:
                pyperclip.copy(previous)
        if self.read(control) != value:
            raise ValueError("UIA input readback differs from requested value")

    def prepare_wechat(self, state):
        from src.core.win32 import find_wechat_window_refs

        self.notice({"stage": "wechat.discover_main"})
        windows = find_wechat_window_refs()
        if len(windows) != 1:
            raise ValueError("Expected exactly one verified WeChat main window")
        hwnd = windows[0].hwnd
        pid = self.proc.GetWindowThreadProcessId(hwnd)[1]
        self.notice({"pid": pid, "role": "wechat"})
        self.notice({"stage": "wechat.restore_main"})
        self.win.ShowWindow(hwnd, 9)  # SW_RESTORE, not a click.
        wait_until(lambda: self.win.IsWindowVisible(hwnd) and not self.win.IsIconic(hwnd), 3,
                   stage="wechat.restore_main.visible")
        geometry = self.fit_main_window(hwnd, pid)
        if state == "minimized":
            self.win.ShowWindow(hwnd, 6)  # SW_MINIMIZE.
            wait_until(lambda: self.win.IsIconic(hwnd), 3)
        elif state == "tray":
            self.activate_gui(hwnd, pid, role="wechat")
            def owner_valid(control):
                if not self.win.IsWindow(hwnd) or self.proc.GetWindowThreadProcessId(hwnd)[1] != pid:
                    return False
                if not self.win.IsWindowEnabled(hwnd) or control.ProcessId != pid:
                    return False
                for _ in range(16):
                    if control.NativeWindowHandle == hwnd:
                        return True
                    control = control.GetParentControl()
                    if control is None:
                        break
                return False

            def hidden():
                if not self.win.IsWindow(hwnd) or self.proc.GetWindowThreadProcessId(hwnd)[1] != pid:
                    raise ValueError("WeChat main window changed or exited instead of hiding")
                return not self.win.IsWindowVisible(hwnd)

            def invoke_close(control):
                pattern = control.GetInvokePattern()
                if pattern is not None:
                    pattern.Invoke()

            hide_to_tray(lambda: find_named(self.root(hwnd), "\u5173\u95ed"), invoke_close,
                         self.click, hidden, owner_valid, self.notice)
            if not self.win.IsWindow(hwnd) or self.proc.GetWindowThreadProcessId(hwnd)[1] != pid:
                raise ValueError("WeChat exited instead of hiding to tray; abort")
        elif state == "visible":
            wait_until(lambda: self.win.IsWindowVisible(hwnd) and not self.win.IsIconic(hwnd), 3)
        else:
            raise ValueError("Invalid window state")
        return {"requested": state, "hwnd": hwnd, "pid": pid,
                "geometry": geometry,
                "visible": bool(self.win.IsWindowVisible(hwnd)),
                "minimized": bool(self.win.IsIconic(hwnd))}


class SourceAdapter:
    def __init__(self, args, notice):
        from app.build_info import build_info
        from app.agent.workflows import WeixinWorkflowEngine
        from app.agent.diagnostics import UiaDiagnostics

        self.args = args
        self.build = build_info()
        self.notice = notice
        self.diagnostics = UiaDiagnostics(log_dir=args.artifact_dir) if args.profile in {"delivery", "images"} else None
        self.engine = WeixinWorkflowEngine(friend_submit_enabled=False, diagnostics=self.diagnostics)
        self.desktop = Desktop(notice)
        notice({"buildFingerprint": self.build["buildFingerprint"]})

    def run(self, case):
        from app.agent.contracts import TaskRequest
        from app.agent.runtime import TaskControl

        validate_request(case["request"], delivery=self.args.profile in {"delivery", "images"}, artifact_dir=self.args.artifact_dir)
        state = self.desktop.prepare_wechat(case["windowState"])
        baseline = None
        if case.get("delivery"):
            self.engine.inspect()
            baseline = self.desktop.delivery_snapshot()
        events = []

        def emit(method, payload):
            if method == "agent.status" and payload.get("action"):
                self.notice({"stage": "engine:" + payload["action"] + ":" + payload.get("status", "")})
            if method == "task.event":
                if len(events) >= MAX_EVENTS:
                    raise ValueError("Event budget exceeded")
                events.append(payload)

        result = self.engine.run(TaskRequest.from_payload(case["request"]), TaskControl(), emit)
        result = {**result, "taskId": case["request"]["taskId"], "events": events,
                "windowStateEvidence": state, "mode": "source",
                "buildFingerprint": self.build["buildFingerprint"]}
        return attach_delivery_evidence(case, result, baseline, self.desktop, self.args.artifact_dir)

    def close(self):
        self.engine.close()
        if self.diagnostics is not None:
            self.diagnostics.close()


class RpcAdapter:
    def __init__(self, args, notice):
        from PySide6.QtCore import QCoreApplication
        from app.agent.client import AgentClient
        from app.agent.diagnostics import default_log_dir

        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.args = args
        self.notice = notice
        self.log_dir = default_log_dir()
        self.client = AgentClient(journal_path=str(Path(args.artifact_dir) / "rpc-safety.json"))
        self.replies, self.errors, self.events, self.finished = {}, [], [], {}
        self.hello = None
        self.client.replyReceived.connect(lambda key, value: self.replies.__setitem__(key, value))
        self.client.rpcError.connect(lambda key, code, message: self.errors.append(message))
        self.client.processError.connect(self.errors.append)
        self.client.helloReceived.connect(lambda value: setattr(self, "hello", value))
        self.client.notificationReceived.connect(self.on_notification)
        self.client.start(args.agent_exe)
        self.pump(lambda: self.hello is not None, args.startup_timeout)
        notice({"pid": self.hello["pid"], "role": "agent"})
        self.build_fingerprint = self.hello.get("build", {}).get("buildFingerprint", "")
        notice({"buildFingerprint": self.build_fingerprint})
        if self.hello.get("capabilities", {}).get("friendSubmitEnabled") is not False:
            raise ValueError("Agent did not attest friendSubmitEnabled=false")
        self.desktop = Desktop(notice)

    def pump(self, predicate, timeout):
        def poll():
            self.app.processEvents()
            if self.errors:
                raise RuntimeError(self.errors[0])
            return predicate()

        return wait_until(poll, timeout)

    def on_notification(self, method, payload):
        if method == "agent.status" and payload.get("action"):
            self.notice({"stage": "agent:" + payload["action"] + ":" + payload.get("status", "")})
        if method == "task.event":
            if len(self.events) >= MAX_EVENTS:
                self.errors.append("Event budget exceeded")
                return
            self.events.append(payload)
            if payload.get("step") in {"send_verified", "submit_verified"}:
                self.client.call("recovery.approve", {
                    "decision": "acknowledge", "taskId": payload["taskId"],
                    "itemId": payload["itemId"],
                })
        elif method == "task.finished":
            self.finished[payload["taskId"]] = payload

    def run(self, case):
        validate_request(case["request"], delivery=self.args.profile in {"delivery", "images"}, artifact_dir=self.args.artifact_dir)
        state = self.desktop.prepare_wechat(case["windowState"])
        baseline = None
        if case.get("delivery"):
            key = self.client.call("wechat.inspect")
            self.pump(lambda: key in self.replies, 10)
            self.replies.pop(key)
            baseline = self.desktop.delivery_snapshot()
        self.events = []
        request = case["request"]
        key = self.client.call("task.start", request)
        self.pump(lambda: key in self.replies, 5)
        if self.replies.pop(key).get("accepted") is not True:
            raise ValueError("Agent rejected task")
        self.pump(lambda: request["taskId"] in self.finished, 120)
        result = {**self.finished.pop(request["taskId"]), "events": list(self.events),
                "windowStateEvidence": state, "mode": "rpc", "buildFingerprint": self.build_fingerprint}
        return attach_delivery_evidence(case, result, baseline, self.desktop, self.log_dir)

    def close(self):
        self.client.shutdown()
        self.client.close()

    def idle(self):
        self.app.processEvents()
        if self.errors:
            raise RuntimeError("Agent failed during inter-task idle")


class GuiAdapter:
    """GUI actions only; snapshots are read-only UIA descriptions, not commands."""

    def __init__(self, args, notice):
        from app.agent.diagnostics import default_log_dir

        environment = dict(os.environ, QT_ACCESSIBILITY="1", WECHAT_COURIER_ACCEPTANCE="1")
        self.notice = notice
        self.log_dir = default_log_dir()
        self.loaded_files = set()
        source_gui = getattr(args, "gui_source", False)
        command = ([sys.executable, str(REPO_ROOT / "tests/manual_v100_source_gui.py"),
                    str(Path(args.artifact_dir) / "gui-settings.ini")] if source_gui
                   else [str(Path(args.gui_exe).resolve())])
        self.process = subprocess.Popen(command,
                                        cwd=str(REPO_ROOT if source_gui else Path(args.gui_exe).resolve().parent),
                                        env=environment, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        notice({"pid": self.process.pid, "role": "gui"})
        self.args = args
        self.desktop = Desktop(notice)
        self.hwnd = wait_until(self.find_window, args.startup_timeout)
        self.seen = set()
        for name in GUI_NAMES["editor"]:
            self.control(name)
        self.click("settingsButton")
        self.click("settingsSection0")
        for name in GUI_NAMES["settings"]:
            self.control(name)
        self.settings = {name: self.desktop.read(self.control(name))
                         for name in GUI_NAMES["settings"] if "Interval" in name}
        self.click("settingsCloseButton")
        wait_until(lambda: self.snapshot("acceptanceEditorState").get("friendSubmitEnabled")
                   is not None, 5)
        self.editor_state()
        fingerprint = self.snapshot("acceptanceTaskState").get("buildFingerprint", "")
        self.notice({"buildFingerprint": fingerprint})

    def find_window(self):
        if self.process.poll() is not None:
            raise RuntimeError(f"Packaged GUI exited: {self.process.returncode}")
        windows = [hwnd for hwnd in self.desktop.windows(pid=self.process.pid)
                   if self.desktop.win.IsWindowVisible(hwnd)
                   and self.desktop.win.GetClassName(hwnd).startswith("Qt")]
        return windows[0] if len(windows) == 1 else None

    def control(self, name):
        self.notice({"stage": "uia:" + name})
        return wait_until(lambda: find_named(self.desktop.root(self.hwnd), name), 4, stage="uia:" + name)

    def click(self, name):
        self.desktop.invoke(self.control(name))

    def snapshot(self, name):
        control = self.control(name)
        # Qt Accessible.description maps to UIA FullDescriptionProperty.
        value = control.GetPropertyValue(30159)
        if value == "":
            value = control.HelpText
        if len(value) > 32768:
            raise ValueError("Accessible snapshot exceeds size budget")
        return json.loads(value)

    def editor_state(self):
        state = self.snapshot("acceptanceEditorState")
        if state.get("friendSubmitEnabled") is not False or state.get("active") is not False:
            raise ValueError("GUI must be idle and attest friendSubmitEnabled=false")
        return state

    def open_editor(self, kind):
        stage = "gui.navigation." + kind
        self.notice({"stage": stage})
        # Editor metadata follows the selected tab, unlike the last task's kind.
        wait_until(lambda: self.snapshot("acceptanceEditorState").get("kind") == kind,
                   4, stage=stage + ".workspace")
        field = "messageRecipientsInput" if kind == "message_send" else "importFriendsButton"
        returned = False

        def visible_editor():
            nonlocal returned
            if self.snapshot("acceptanceEditorState").get("kind") != kind:
                raise ValueError("Selected GUI workspace changed during navigation")
            root = self.desktop.root(self.hwnd)
            try:
                editor = find_named(root, field)
            except LookupError:
                if not returned:
                    button = find_named(root, "taskReturnToEditorButton")
                    returned = True
                    self.desktop.invoke(button)
                return None
            if not editor.IsEnabled:
                raise ValueError("GUI editor is visible but disabled")
            return editor

        wait_until(visible_editor, 4, stage=stage + ".editor_visible")

    def import_friend(self, item, index):
        path = Path(self.args.artifact_dir) / f"friend-{index:04d}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerows(friend_import_rows(item))
        self.click("importFriendsButton")
        self.choose_file(path)
        if self.desktop.read(self.control("friendAccountField")) != FRIEND_ACCOUNT:
            raise ValueError("Friend import did not populate the permitted account")
        self.desktop.fill(self.control("friendRangeStart"), "1")
        self.desktop.fill(self.control("friendRangeEnd"), "1")
        self.click("selectFriendRangeButton")

    def choose_file(self, path):
        self.notice({"stage": "gui.file_dialog.find"})
        def get_dialog():
            windows = self.desktop.windows(pid=self.process.pid, class_name="#32770")
            return windows[0] if len(windows) == 1 else None

        dialog = wait_until(get_dialog, 5, stage="gui.file_dialog.find")
        root = self.desktop.root(dialog)
        # Standard native Windows Open dialog IDs, never screen coordinates.
        filename = root.EditControl(AutomationId="1148", searchDepth=8)
        if not filename.Exists(1, 0.1):
            raise LookupError("Native file dialog filename AutomationId=1148 unavailable")
        self.notice({"stage": "gui.file_dialog.filename"})
        self.desktop.fill(filename, str(path.resolve()))
        open_button = wait_until(
            lambda: file_dialog_open_control(self.desktop.root(dialog)),
            3,
            stage="gui.file_dialog.open_control",
        )
        self.notice({"stage": "gui.file_dialog.open"})
        self.desktop.invoke(open_button)
        wait_until(lambda: not self.desktop.win.IsWindowVisible(dialog), 5, stage="gui.file_dialog.closed")

    def configure_delivery(self, request):
        old = self.editor_state()["options"].get("filePaths", [])
        if len(old) > 2 or any(str(Path(path).resolve()) not in self.loaded_files for path in old):
            raise ValueError("Refusing to remove unrelated GUI attachments")
        for _ in old:
            self.click("messageRemoveFileButton-0")
            old = old[1:]
            wait_until(lambda: len(self.editor_state()["options"]["filePaths"]) == len(old), 3,
                       stage="gui.delivery.remove_attachment")
        for value in request["options"]["filePaths"]:
            path = Path(value)
            self.click("messageAddFileButton")
            self.choose_file(path)
            self.loaded_files.add(str(path.resolve()))
        wait_until(lambda: normalized_options(self.editor_state()["options"])["filePaths"]
                   == normalized_options(request["options"])["filePaths"], 3,
                   stage="gui.delivery.attachment_readback")

    def run(self, case):
        request = case["request"]
        validate_request(request, delivery=self.args.profile in {"delivery", "images"}, artifact_dir=self.args.artifact_dir)
        self.desktop.win.ShowWindow(self.hwnd, 9)
        self.desktop.activate_gui(self.hwnd, self.process.pid)
        kind = request["kind"]
        self.click("messageWorkspaceTab" if kind == "message_send" else "friendWorkspaceTab")
        self.open_editor(kind)
        item = request["items"][0]
        if kind == "message_send":
            self.desktop.fill(self.control("messageRecipientsInput"), item["target"])
            self.desktop.fill(self.control("messageTemplateInput"), item["message"])
            if case.get("delivery"):
                self.configure_delivery(request)
        else:
            self.import_friend(item, case["index"])
        editor = self.editor_state()
        if editor.get("kind") != kind or semantic_items(editor.get("items", [])) != semantic_items(request["items"]):
            raise ValueError("GUI editor payload does not match the independent task")
        if normalized_options(editor.get("options", {})) != normalized_options(request["options"]):
            raise ValueError("GUI options differ from canonical task; inspect settings/attachments")
        state = self.desktop.prepare_wechat(case["windowState"])
        baseline = self.desktop.delivery_snapshot() if case.get("delivery") else None
        self.desktop.activate_gui(self.hwnd, self.process.pid)
        # Recheck the GUI immediately before its single destructive Start action.
        if self.editor_state() != editor:
            raise ValueError("GUI editor changed during window preparation")
        old_id = self.snapshot("acceptanceTaskState").get("taskId")
        self.click("startMessageButton" if kind == "message_send" else "startFriendsButton")

        def completed():
            snapshot = self.snapshot("acceptanceTaskState")
            if snapshot.get("taskId") in (None, "", old_id):
                return None
            if snapshot.get("active") is False:
                return snapshot
            if snapshot.get("active") is True and snapshot.get("phase") in {
                    "recovering", "awaiting_recovery", "waiting_login"}:
                # Preserve evidence before validate_result stops the schedule.
                return snapshot
            return None

        result = wait_until(completed, self.args.task_timeout - 5)
        result.update(mode="gui", windowStateEvidence=state, settingsEvidence=self.settings)
        if result.get("active") is True or result.get("outcome") != "success":
            return result
        return attach_delivery_evidence(case, result, baseline, self.desktop, self.log_dir)

    def close(self):
        # A source acceptance window is temporary; never force-kill a live task.
        if getattr(self.args, "gui_source", False) and self.process.poll() is None:
            if self.snapshot("acceptanceTaskState").get("active") is False:
                self.desktop.win.PostMessage(self.hwnd, 0x0010, 0, 0)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass


def worker_main(connection, args):
    sys.path.insert(0, str(REPO_ROOT))
    adapter = None
    try:
        connection.send({"notice": {"stage": "worker.configure_dpi"}})
        connection.send({"notice": {"dpi": configure_dpi_awareness()}})
        adapter_type = {"source": SourceAdapter, "rpc": RpcAdapter, "gui": GuiAdapter}[args.mode]
        adapter = adapter_type(args, lambda value: connection.send({"notice": value}))
        connection.send({"ready": True})
        while True:
            if not connection.poll(0.1):
                idle = getattr(adapter, "idle", None)
                if idle is not None:
                    idle()
                continue
            command = connection.recv()
            if command.get("close"):
                adapter.close()
                adapter = None
                connection.send({"closed": True})
                break
            result = adapter.run(command["case"])
            connection.send({"result": result})
    except BaseException as exc:
        connection.send({"failure": failure_evidence(exc)})
        # No recovery or retry after an unexplained failure. Parent owns shutdown.
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass
        connection.close()


class WorkerSession:
    def __init__(self, args):
        self.args = args
        self.pids = []
        self.last_stage = "worker_startup"
        self.breadcrumbs = deque(maxlen=200)
        self.runtime_fingerprint = ""
        self.failure = None
        self.dpi_evidence = []
        self.started = time.monotonic()
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=worker_main, args=(child, args))
        self.process.start()
        child.close()

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.connection.poll(min(0.2, max(0, deadline - time.monotonic()))):
                if not self.process.is_alive():
                    raise RuntimeError(f"Acceptance worker exited ({self.process.exitcode})")
                continue
            value = self.connection.recv()
            if "notice" in value:
                notice = value["notice"]
                if "pid" in notice and notice not in self.pids:
                    self.pids.append(notice)
                if "stage" in notice:
                    changed = self.last_stage != notice["stage"]
                    self.last_stage = notice["stage"]
                    if changed:
                        self.breadcrumbs.append({**notice, "elapsedSeconds": round(time.monotonic() - self.started, 3)})
                if "buildFingerprint" in notice:
                    self.runtime_fingerprint = notice["buildFingerprint"]
                if "dpi" in notice and notice["dpi"] not in self.dpi_evidence:
                    self.dpi_evidence.append(notice["dpi"])
                continue
            if "failure" in value:
                self.failure = {**value["failure"], "lastStage": self.last_stage}
                raise WorkerFailure(self.failure)
            return value
        raise AcceptanceTimeout("worker_watchdog.no_retry", timeout)

    def ready(self):
        if not self.receive(self.args.startup_timeout).get("ready"):
            raise RuntimeError("Worker did not become ready")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.runtime_fingerprint):
            raise ValueError("No valid startup source/hello buildFingerprint; refusing live tasks")

    def run(self, case):
        self.last_stage = "task:" + case["request"]["taskId"]
        self.connection.send({"case": case})
        result = self.receive(self.args.task_timeout)["result"]
        if self.runtime_fingerprint and result.get("buildFingerprint") != self.runtime_fingerprint:
            raise ValueError("Task fingerprint differs from source/hello startup fingerprint")
        # Never retain unrelated GUI input, even when reporting a failed correlation.
        if semantic_items(result.get("echoedItems", [])) != semantic_items(case["request"]["items"]):
            result.pop("echoedItems", None)
        return result_evidence(result)

    def close(self, failed=False):
        if self.process.is_alive():
            try:
                self.connection.send({"close": True})
                self.receive(1 if failed else 5)
            except (OSError, RuntimeError, TimeoutError, EOFError):
                failed = True
        if self.process.is_alive():
            self.process.join(1)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(3)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(3)
        self.connection.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "rpc", "gui"), default="gui")
    parser.add_argument("--profile", choices=("smoke", "soak", "independent", "delivery", "images"), default="smoke")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-send", action="store_true")
    parser.add_argument("--confirm-friend-preflight", action="store_true")
    parser.add_argument("--confirm-delivery", action="store_true")
    parser.add_argument("--gui-exe")
    parser.add_argument("--gui-source", action="store_true")
    parser.add_argument("--agent-exe")
    parser.add_argument("--report", default=str(REPO_ROOT / ".artifacts" / "v032-acceptance.json"))
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--startup-timeout", type=float, default=20)
    parser.add_argument("--task-timeout", type=float, default=120)
    return parser.parse_args(argv)


def validate_args(args):
    if args.gui_source and (args.mode != "gui" or args.gui_exe):
        raise ValueError("gui-source requires GUI mode and cannot be combined with gui-exe")
    if not 10 <= args.interval_seconds <= 600:
        raise ValueError("interval-seconds must be between 10 and 600")
    if not 5 <= args.startup_timeout <= 30 or not 15 <= args.task_timeout <= 180:
        raise ValueError("Bounded timeouts required: startup 5..30s, task 15..180s")
    if args.execute:
        if args.profile in {"delivery", "images"}:
            if not args.confirm_send or not args.confirm_delivery:
                raise ValueError("Delivery requires --confirm-send AND --confirm-delivery")
        elif not args.confirm_send or not args.confirm_friend_preflight:
            raise ValueError("Live runs require --confirm-send AND --confirm-friend-preflight")
        if args.mode == "gui" and not args.gui_exe and not args.gui_source:
            raise ValueError("GUI acceptance requires --gui-exe pointing to a packaged .exe")
        if args.mode == "rpc" and not args.agent_exe:
            raise ValueError("RPC comparison requires --agent-exe pointing to packaged wechat-agent.exe")
        executable = args.gui_exe if args.mode == "gui" else args.agent_exe
        if executable and (Path(executable).suffix.lower() != ".exe" or not Path(executable).is_file()):
            raise ValueError("Packaged executable does not exist")
        if os.name != "nt":
            raise ValueError("Live acceptance requires Windows")


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    args = parse_args(argv)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    args.artifact_dir = str(Path(args.report).resolve().parent / run_id)
    report = {"schemaVersion": 1, "acceptanceVersion": "1.0.0", "runId": run_id,
              "mode": args.mode, "guiSource": args.gui_source, "profile": args.profile, "status": "planned", "ok": False,
              "taskAttempts": 0, "liveTasksExecuted": 0,
              "startedAt": datetime.now(timezone.utc).isoformat(),
              "plan": make_plan(run_id, profile=args.profile, artifact_dir=args.artifact_dir),
              "accessibilityContract": GUI_NAMES,
              "coverage": {"scope": "text-and-friend-preflight-subset", "fullV100Gate": False,
                           "included": ["text_send", "friend_preflight", "mixed_window_states"],
                           "excluded": ["attachments"]},
              "safety": {"sendTarget": SEND_TARGET, "friendAccount": FRIEND_ACCOUNT,
                         "friendSubmitEnabled": False, "retryFailedTasks": False}}
    session = None
    try:
        validate_args(args)
        if args.profile in {"delivery", "images"}:
            report["coverage"] = {"scope": "delivery-subset", "fullV100Gate": False,
                                  "included": ["text_send", "attachments", "duplicate_check"],
                                  "excluded": ["friend_preflight", "mixed_window_states", "independent_40", "soak"]}
        report["buildFingerprint"] = build_fingerprint(args)
        if not args.execute:
            write_report(args.report, report)
            print(json.dumps({"status": "planned", "report": str(Path(args.report).resolve())}))
            return 0
        Path(args.artifact_dir).mkdir(parents=True)
        if args.profile in {"delivery", "images"}:
            for case in report["plan"]:
                materialize_delivery(case, args.artifact_dir)
        report["status"] = "starting"
        write_report(args.report, report)
        session = WorkerSession(args)
        session.ready()
        report["status"] = "running"

        def checkpoint(schedule):
            report["schedule"] = schedule
            report["taskAttempts"] = len(schedule["tasks"])
            # Count observed execution, never an ID from the planned request.
            report["liveTasksExecuted"] = sum(
                isinstance(entry.get("result", {}).get("taskId"), str)
                and bool(entry["result"]["taskId"].strip())
                for entry in schedule["tasks"]
            )
            write_report(args.report, report)

        schedule = run_schedule(session.run, run_id, args.profile, args.interval_seconds,
                                3600, checkpoint=checkpoint, artifact_dir=args.artifact_dir)
        report.update(schedule=schedule, ok=schedule["ok"],
                      status="passed" if schedule["ok"] else "failed")
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="failed", errorType=type(exc).__name__, error=str(exc)[:2000])
        report["failure"] = exc.evidence if isinstance(exc, WorkerFailure) else failure_evidence(exc)
    finally:
        if session is not None:
            report["processes"] = session.pids
            report["lastStage"] = session.last_stage
            report["breadcrumbs"] = list(session.breadcrumbs)
            report["runtimeBuildFingerprint"] = session.runtime_fingerprint
            report["dpiEvidence"] = session.dpi_evidence
            if session.failure:
                report["failure"] = session.failure
            if not report["ok"]:
                # Collect Win32-only evidence before terminating the stuck UIA worker.
                report["diagnostics"] = window_diagnostics([p["pid"] for p in session.pids])
                report["operatorActionRequired"] = (
                    "Inspect Courier/WeChat and stop any active task. Do not replay an uncertain send. "
                    "The worker is terminated; GUI/Agent may remain alive."
                )
            session.close(failed=not report["ok"])
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_report(args.report, report)
    print(json.dumps({"status": report["status"], "report": str(Path(args.report).resolve()),
                      "taskAttempts": report["taskAttempts"],
                      "liveTasksExecuted": report["liveTasksExecuted"]}))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
