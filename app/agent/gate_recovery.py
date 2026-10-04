from __future__ import annotations

import json
import hashlib
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .gate import (AccessibilitySafetyError, GateRecoveryRequired, NativeGateBackend, WechatStartupPending,
                   apply_gate_lease, classify_gate_lease, validate_lease_group)
from .journal import GateLeaseJournal, _write_atomic
from .profile import get_weixin_profile


class GateRecoveryManager:
    """Mutex-owned, Win32-only startup recovery. Never touches task journals."""

    def __init__(self, backend=None, *, journal=None, temp_dir=None,
                 allow_restart=True, login_timeout=90):
        self.backend = backend or NativeGateBackend()
        self.journal = journal or GateLeaseJournal.from_environment()
        self.temp_dir = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
        self.allow_restart = bool(allow_restart)
        self.login_timeout = max(0.01, float(login_timeout))
        self.progress_path = self.journal.path.with_name(self.journal.path.name + ".recovery.json")
        self.state = {"recoveryId": "", "stage": "checking", "reasonCode": "GATE_RECOVERING", "attempt": 0}
        self._stop = threading.Event()
        self._emit: Callable[[dict[str, Any]], None] = lambda state: None
        self._deadline = 0.0

    def _load_progress(self):
        if not self.progress_path.exists():
            return None
        record = json.loads(self.progress_path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or not isinstance(record.get("recoveryId"), str) or not record["recoveryId"]
                or type(record.get("attempt")) is not int or record["attempt"] not in (0, 1)
                or record.get("phase") not in {"closing", "starting", "awaiting_login", "login_timeout", "cancelled", "completed"}
                or not isinstance(record.get("target"), dict) or not isinstance(record.get("fingerprints"), dict)):
            raise AccessibilitySafetyError("invalid recovery reservation; refusing a new restart")
        if record["attempt"] == 0 and record["phase"] not in {"cancelled", "completed"}:
            raise AccessibilitySafetyError("invalid unreserved recovery phase; refusing a new restart")
        target = record["target"]
        if not target and record["attempt"] == 0:
            return record
        if (type(target.get("pid")) is not int or target["pid"] <= 0
                or not all(isinstance(target.get(key), str) and target[key] for key in ("processStartTime", "processPath", "version"))):
            raise AccessibilitySafetyError("invalid recovery process identity; refusing a new restart")
        return record

    def _publish(self, stage, reason="GATE_RECOVERING", detail="", **extra):
        self.state.update(stage=stage, reasonCode=reason, detail=detail, **extra)
        self._emit(dict(self.state))
        return dict(self.state)

    def _save(self, record, phase):
        record = dict(record, phase=phase, checkedAt=datetime.now(timezone.utc).isoformat())
        _write_atomic(self.progress_path, record)
        return record

    def _check(self, *, login=False):
        if self._stop.is_set():
            raise InterruptedError("Gate recovery cancelled")
        if not login and time.monotonic() >= self._deadline:
            raise TimeoutError("Gate recovery exceeded its startup deadline")

    def _paths(self):
        paths = {self.journal.path}
        paths.update(self.temp_dir.glob("wuge-wechat-agent-*-safety.json.gate"))
        paths.update(self.temp_dir.glob("wuge-wechat-agent-*-safety.json.gate.tmp"))
        paths.add(self.journal.path.with_name(self.journal.path.name + ".tmp"))
        return sorted((p for p in paths if p.exists()), key=lambda p: str(p).casefold())

    def _archive(self, paths, reason):
        archived = self.state.setdefault("archives", [])
        for path in paths:
            self._check()
            destination = GateLeaseJournal(path).archive(reason, recovery_id=self.state["recoveryId"])
            if destination:
                archived.append(destination)

    @staticmethod
    def _identity(candidate):
        return tuple(candidate.get(key) for key in ("pid", "processStartTime", "processPath", "version"))

    def _login_ready(self, candidate):
        reader = getattr(self.backend, "login_window_ready", None)
        if callable(reader):
            return reader(candidate)
        window = self.backend.window_inspection()
        return (window.get("pid") == candidate["pid"] and window.get("windowClass") == "mmui::MainWindow"
                and self.backend.window_responsive(window.get("hwnd", 0)))

    def _wait_login(self, reservation):
        self._publish("awaiting_login", "GATE_WAITING_LOGIN", "等待微信登录", attempt=1)
        deadline = time.monotonic() + self.login_timeout
        while time.monotonic() < deadline:
            self._check(login=True)
            try:
                candidate = self.backend.verified_wechat_process()
            except WechatStartupPending:
                candidate = None
            if candidate:
                get_weixin_profile(candidate["version"])
                if candidate["processPath"] != reservation["target"]["processPath"]:
                    raise AccessibilitySafetyError("restarted Weixin installation identity changed")
                if self._login_ready(candidate):
                    self._save(reservation, "completed")
                    return self._publish("completed", "", "租约恢复完成")
            self._stop.wait(min(0.25, max(0, deadline - time.monotonic())))
        self._save(reservation, "login_timeout")
        return self._publish("failed", "GATE_LOGIN_TIMEOUT", "等待登录超时，请登录后检测微信恢复")

    def run(self, stop: threading.Event, emit: Callable[[dict[str, Any]], None]):
        self._stop, self._emit = stop, emit
        self._deadline = time.monotonic() + 15
        try:
            self._check()
            self._publish("checking")
            try:
                peers = tuple(self.backend.legacy_agent_pids())
            except Exception as exc:
                raise AccessibilitySafetyError(f"cannot verify existing Agent processes: {exc}") from exc
            if peers:
                return self._publish("blocked", "AGENT_ALREADY_RUNNING", "另一个 Agent 仍在操作微信")
            previous = self._load_progress()
            if previous and previous.get("phase") != "completed":
                self.state.update(recoveryId=previous["recoveryId"], attempt=previous["attempt"])
            else:
                previous = None
                self.state["recoveryId"] = uuid.uuid4().hex
            paths = self._paths()
            entries, unsafe = [], []
            for path in paths:
                self._check()
                try:
                    entries.append(classify_gate_lease(self.backend, GateLeaseJournal(path)))
                except GateRecoveryRequired as exc:
                    unsafe.append({"source": str(path), "action": "restart", "reason": str(exc)})
            self.state["classifications"] = [
                {"source": str(entry["journal"].path), "action": entry["action"], "reason": entry["reason"],
                 "identity": {key: entry.get("record", {}).get(key) for key in ("pid", "processStartTime", "version", "windowsSessionId", "logonId", "logonTime")}}
                for entry in entries
            ] + unsafe
            try:
                validate_lease_group(entries)
            except GateRecoveryRequired as exc:
                unsafe.append({"action": "restart", "reason": str(exc)})
                self.state["classifications"].append(unsafe[-1])
            if not unsafe:
                self._publish("restoring")
                for entry in entries:
                    self._check()
                    apply_gate_lease(self.backend, entry, recovery_id=self.state["recoveryId"])
                    archive = getattr(entry["journal"], "last_archive", "")
                    if archive:
                        self.state.setdefault("archives", []).append(archive)
                if previous and previous["attempt"] == 0:
                    self._save(previous, "completed")
                    return self._publish("completed", "", "遗留记录已安全处理，未执行自动重启")
                if previous and previous.get("phase") in {"awaiting_login", "login_timeout", "starting", "cancelled"}:
                    phase = previous["phase"]
                    if not self.allow_restart or phase in {"login_timeout", "cancelled"}:
                        try:
                            candidate = self.backend.verified_wechat_process()
                        except WechatStartupPending:
                            candidate = None
                        if candidate and self._login_ready(candidate) and candidate["processPath"] == previous["target"]["processPath"]:
                            self._save(previous, "completed")
                            return self._publish("completed", "", "已确认微信登录")
                        if phase == "cancelled":
                            return self._publish("blocked", "GATE_RECOVERY_CANCELLED", "恢复已取消，请手动登录后检测恢复")
                        if phase == "login_timeout":
                            return self._publish("blocked", "GATE_LOGIN_TIMEOUT", "等待登录已超时，请登录后检测恢复")
                        return self._publish("blocked", "GATE_WAITING_LOGIN", "等待微信登录")
                    return self._wait_login(previous)
                if previous:
                    self._save(previous, "completed")
                return self._publish("completed", "", "租约检查完成")
            candidate = self.backend.verified_wechat_process()
            if candidate is None:
                self._archive(paths, "no_live_weixin")
                if previous:
                    self._save(previous, "completed")
                return self._publish("completed", "", "原微信已退出，遗留记录已归档")
            get_weixin_profile(candidate["version"])
            if previous and (previous["attempt"] >= 1 or previous["phase"] == "cancelled"):
                target = previous.get("target", {})
                old_alive = bool(target) and self.backend.process_exists(target["pid"])
                same_old = old_alive and self.backend.process_start_time(target["pid"]) == target["processStartTime"]
                fingerprints = previous.get("fingerprints", {})
                if target and not same_old and all(fingerprints.get(str(path)) == hashlib.sha256(path.read_bytes()).hexdigest() for path in paths):
                    self._archive(paths, "previous_restart_target_exited")
                    self._save(previous, "completed")
                    return self._publish("completed", "", "原故障进程已退出，遗留记录已归档")
                if previous["phase"] == "cancelled":
                    return self._publish("blocked", "GATE_RECOVERY_CANCELLED", "恢复已取消，请手动处理微信后检测恢复")
                return self._publish("blocked", "GATE_RESTART_LIMIT", "本次故障已尝试重启一次，请手动处理后检测恢复")
            if not self.allow_restart:
                return self._publish("blocked", "GATE_RESTART_REQUIRED", "遗留租约需通过微信重启恢复")
            self._check()
            reservation = {"recoveryId": self.state["recoveryId"], "attempt": 1,
                           "target": candidate, "classifications": self.state["classifications"],
                           "fingerprints": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
            reservation = self._save(reservation, "closing")
            self._publish("restarting", "GATE_RESTARTING", "正在重启微信", attempt=1, target=candidate)
            self._check()
            current = self.backend.verified_wechat_process()
            if current is None or self._identity(current) != self._identity(candidate):
                raise AccessibilitySafetyError("Weixin process identity changed before restart")
            self.backend.request_close(candidate)
            deadline = min(self._deadline, time.monotonic() + 5)
            while self.backend.process_exists(candidate["pid"]) and time.monotonic() < deadline:
                self._check()
                self._stop.wait(0.1)
            self._check()
            if self.backend.process_exists(candidate["pid"]):
                if self.backend.process_start_time(candidate["pid"]) != candidate["processStartTime"]:
                    raise AccessibilitySafetyError("Weixin PID was reused before termination")
                self.backend.terminate_process_tree(candidate["pid"], wait_seconds=1)
            if self.backend.process_exists(candidate["pid"]):
                raise AccessibilitySafetyError("old Weixin is still alive; lease must not be discarded")
            self._archive(paths, "verified_weixin_restarted")
            self._check()
            reservation = self._save(reservation, "starting")
            self._check()
            self.backend.start_process(candidate["processPath"])
            reservation = self._save(reservation, "awaiting_login")
            return self._wait_login(reservation)
        except InterruptedError as exc:
            try:
                reservation = self._load_progress()
                if reservation is None:
                    # Persist cancellation even before a restart was reserved.
                    try:
                        candidate = self.backend.verified_wechat_process()
                    except WechatStartupPending:
                        candidate = None
                    reservation = {"recoveryId": self.state["recoveryId"] or uuid.uuid4().hex,
                                   "attempt": 0, "target": candidate or {},
                                   "fingerprints": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self._paths()}}
                if reservation.get("phase") != "completed":
                    self._save(reservation, "cancelled")
                self.state.update(recoveryId=reservation["recoveryId"], attempt=reservation["attempt"])
            except Exception as persist_error:
                return self._publish("blocked", "GATE_RECOVERY_BLOCKED", f"cannot persist recovery cancellation: {persist_error}")
            return self._publish("blocked", "GATE_RECOVERY_CANCELLED", str(exc))
        except TimeoutError as exc:
            return self._publish("failed", "GATE_RECOVERY_TIMEOUT", str(exc))
        except Exception as exc:
            reason = "AGENT_ALREADY_RUNNING" if "another Agent" in str(exc) else "GATE_RECOVERY_BLOCKED"
            return self._publish("blocked", reason, str(exc))


__all__ = ["GateRecoveryManager"]
