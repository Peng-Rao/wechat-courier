from __future__ import annotations

import csv
import copy
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QSettings, QTimer, Signal, Slot

from .agent.client import AgentClient
from .agent.workflows import normalize_identity
from .models import extract_greeting_name
from .task_models import (
    FriendImportModel,
    RuntimeLogModel,
    TaskDisplayItem,
    TaskItemModel,
)


MESSAGE_STEP_LABELS = {
    "window_bound": "已绑定微信窗口",
    "search_ready": "搜索入口已就绪",
    "target_selected": "已选择目标",
    "target_verified": "目标校验通过",
    "composer_ready": "输入框已就绪",
    "content_inserted": "内容已写入",
    "send_triggered": "已触发发送",
    "send_verified": "发送结果已确认",
}
FRIEND_STEP_LABELS = {
    "window_bound": "已绑定微信窗口",
    "add_friend_window_ready": "添加好友窗口已就绪",
    "account_inserted": "账号已写入",
    "account_searched": "已搜索账号",
    "profile_verified": "资料核对通过",
    "request_form_ready": "申请窗口已就绪",
    "fields_verified": "申请内容已核对",
    "submit_verified": "提交结果已确认",
}


class MessageController(QObject):
    recipientsTextChanged = Signal(str)
    templateTextChanged = Signal(str)
    useForwardChanged = Signal(bool)
    filePathsChanged = Signal(list)
    intervalMinChanged = Signal(float)
    intervalMaxChanged = Signal(float)
    previewChanged = Signal()

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._recipients = ""
        self._template = ""
        self._use_forward = False
        self._files: list[str] = []
        self._interval_min = float(settings.value("message/intervalMin", 2.0))
        self._interval_max = float(settings.value("message/intervalMax", 3.0))

    def _get_recipients(self):
        return self._recipients

    def _set_recipients(self, value):
        value = str(value)
        if value == self._recipients:
            return
        self._recipients = value
        self.recipientsTextChanged.emit(value)
        self.previewChanged.emit()

    recipientsText = Property(
        str, _get_recipients, _set_recipients, notify=recipientsTextChanged
    )

    def _get_template(self):
        return self._template

    def _set_template(self, value):
        value = str(value)
        if value == self._template:
            return
        self._template = value
        self.templateTextChanged.emit(value)
        self.previewChanged.emit()

    templateText = Property(str, _get_template, _set_template, notify=templateTextChanged)

    def _get_forward(self):
        return self._use_forward

    def _set_forward(self, value):
        value = bool(value)
        if value == self._use_forward:
            return
        self._use_forward = value
        self.useForwardChanged.emit(value)

    useForward = Property(bool, _get_forward, _set_forward, notify=useForwardChanged)

    @Property(list, notify=filePathsChanged)
    def filePaths(self):
        return list(self._files)

    def _get_interval_min(self):
        return self._interval_min

    def _set_interval_min(self, value):
        value = max(0.0, min(float(value), self._interval_max))
        if value == self._interval_min:
            return
        self._interval_min = value
        self._settings.setValue("message/intervalMin", value)
        self.intervalMinChanged.emit(value)

    intervalMin = Property(
        float, _get_interval_min, _set_interval_min, notify=intervalMinChanged
    )

    def _get_interval_max(self):
        return self._interval_max

    def _set_interval_max(self, value):
        value = max(self._interval_min, float(value))
        if value == self._interval_max:
            return
        self._interval_max = value
        self._settings.setValue("message/intervalMax", value)
        self.intervalMaxChanged.emit(value)

    intervalMax = Property(
        float, _get_interval_max, _set_interval_max, notify=intervalMaxChanged
    )

    @Property(int, notify=recipientsTextChanged)
    def recipientCount(self):
        return len(self.recipients())

    @Property(str, notify=previewChanged)
    def previewTarget(self):
        recipients = self.recipients()
        return recipients[0] if recipients else ""

    @Property(str, notify=previewChanged)
    def previewMessage(self):
        target = self.previewTarget
        if not target:
            return ""
        try:
            return self._template.format(name=extract_greeting_name(target))
        except (KeyError, ValueError):
            return self._template

    def recipients(self) -> list[str]:
        result = []
        seen = set()
        for line in self._recipients.splitlines():
            target = line.strip()
            identity = normalize_identity(target)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            result.append(target)
        return result

    def build_items(self) -> list[dict[str, str]]:
        items = []
        for target in self.recipients():
            greeting = extract_greeting_name(target)
            try:
                message = self._template.format(name=greeting)
            except (KeyError, ValueError):
                message = self._template
            items.append(
                {
                    "itemId": uuid.uuid4().hex,
                    "target": target,
                    "message": message,
                }
            )
        return items

    @Slot(str)
    def addFile(self, file_url: str) -> None:
        path = file_url.replace("file:///", "")
        if sys.platform == "win32":
            path = path.lstrip("/")
        if path and path not in self._files:
            self._files.append(path)
            self.filePathsChanged.emit(list(self._files))
            self.previewChanged.emit()

    @Slot(int)
    def removeFile(self, index: int) -> None:
        if 0 <= index < len(self._files):
            self._files.pop(index)
            self.filePathsChanged.emit(list(self._files))
            self.previewChanged.emit()


class FriendController(QObject):
    defaultGreetingChanged = Signal(str)
    defaultRemarkChanged = Signal(str)
    intervalMinChanged = Signal(float)
    intervalMaxChanged = Signal(float)

    DEFAULT_GREETING = "你好，我是五阿哥，方便认识一下吗？"
    DEFAULT_REMARK = "新联系人"

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._model = FriendImportModel(self)
        self._default_greeting = str(
            settings.value("friends/defaultGreeting", self.DEFAULT_GREETING)
        )
        self._default_remark = str(
            settings.value("friends/defaultRemark", self.DEFAULT_REMARK)
        )
        self._interval_min = float(settings.value("friends/intervalMin", 15.0))
        self._interval_max = float(settings.value("friends/intervalMax", 30.0))

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    def _get_greeting(self):
        return self._default_greeting

    def _set_greeting(self, value):
        value = str(value)
        if value == self._default_greeting:
            return
        self._default_greeting = value
        self._settings.setValue("friends/defaultGreeting", value)
        self.defaultGreetingChanged.emit(value)

    defaultGreeting = Property(
        str, _get_greeting, _set_greeting, notify=defaultGreetingChanged
    )

    def _get_remark(self):
        return self._default_remark

    def _set_remark(self, value):
        value = str(value)
        if value == self._default_remark:
            return
        self._default_remark = value
        self._settings.setValue("friends/defaultRemark", value)
        self.defaultRemarkChanged.emit(value)

    defaultRemark = Property(str, _get_remark, _set_remark, notify=defaultRemarkChanged)

    def _get_interval_min(self):
        return self._interval_min

    def _set_interval_min(self, value):
        value = max(5.0, min(300.0, float(value)))
        value = min(value, self._interval_max)
        if value == self._interval_min:
            return
        self._interval_min = value
        self._settings.setValue("friends/intervalMin", value)
        self.intervalMinChanged.emit(value)

    intervalMin = Property(
        float, _get_interval_min, _set_interval_min, notify=intervalMinChanged
    )

    def _get_interval_max(self):
        return self._interval_max

    def _set_interval_max(self, value):
        value = max(5.0, min(300.0, float(value)))
        value = max(value, self._interval_min)
        if value == self._interval_max:
            return
        self._interval_max = value
        self._settings.setValue("friends/intervalMax", value)
        self.intervalMaxChanged.emit(value)

    intervalMax = Property(
        float, _get_interval_max, _set_interval_max, notify=intervalMaxChanged
    )

    @Slot(str, result=bool)
    def importFile(self, path: str) -> bool:
        return self._model.importFile(path)

    def build_items(self) -> list[dict[str, Any]]:
        return self._model.selected_payload(
            self._default_greeting, self._default_remark
        )

    @Slot(str, result=bool)
    def createTemplate(self, file_url: str) -> bool:
        path = file_url.replace("file:///", "")
        if sys.platform == "win32":
            path = path.lstrip("/")
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill

            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "好友导入"
            worksheet.append(["账号", "打招呼语", "备注"])
            worksheet.append(["18896904196", "你好，方便认识一下吗？", "示例联系人"])
            worksheet.freeze_panes = "A2"
            worksheet.column_dimensions["A"].width = 24
            worksheet.column_dimensions["B"].width = 42
            worksheet.column_dimensions["C"].width = 24
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="07C160")
                cell.alignment = Alignment(vertical="center")
            worksheet.row_dimensions[1].height = 24
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            workbook.save(path)
            workbook.close()
            return True
        except Exception:
            return False


class SettingsController(QObject):
    unknownPolicyChanged = Signal(str)
    agentRestartLimitChanged = Signal(int)
    wechatRecoveryModeChanged = Signal(str)
    loginTimeoutChanged = Signal(int)
    appearanceChanged = Signal()

    def __init__(self, owner, settings: QSettings, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._settings = settings
        self._unknown_policy = str(
            settings.value("task/unknownPolicy", "continue")
        )
        self._agent_restart_limit = int(settings.value("recovery/agentRestarts", 2))
        self._wechat_mode = str(settings.value("recovery/wechatMode", "confirm"))
        self._login_timeout = int(settings.value("recovery/loginTimeout", 90))
        owner.isDarkChanged.connect(lambda _value: self.appearanceChanged.emit())
        owner.glassEnabledChanged.connect(lambda _value: self.appearanceChanged.emit())
        owner.glassOpacityChanged.connect(lambda _value: self.appearanceChanged.emit())

    def _get_unknown_policy(self):
        return self._unknown_policy

    def _set_unknown_policy(self, value):
        value = str(value)
        if value not in {"continue", "stop"} or value == self._unknown_policy:
            return
        self._unknown_policy = value
        self._settings.setValue("task/unknownPolicy", value)
        self.unknownPolicyChanged.emit(value)

    unknownPolicy = Property(
        str, _get_unknown_policy, _set_unknown_policy, notify=unknownPolicyChanged
    )

    def _get_restart_limit(self):
        return self._agent_restart_limit

    def _set_restart_limit(self, value):
        value = max(0, min(2, int(value)))
        if value == self._agent_restart_limit:
            return
        self._agent_restart_limit = value
        self._settings.setValue("recovery/agentRestarts", value)
        self.agentRestartLimitChanged.emit(value)

    agentRestartLimit = Property(
        int,
        _get_restart_limit,
        _set_restart_limit,
        notify=agentRestartLimitChanged,
    )

    def _get_wechat_mode(self):
        return self._wechat_mode

    def _set_wechat_mode(self, value):
        value = str(value)
        if value not in {"confirm", "manual", "silent"} or value == self._wechat_mode:
            return
        self._wechat_mode = value
        self._settings.setValue("recovery/wechatMode", value)
        self.wechatRecoveryModeChanged.emit(value)

    wechatRecoveryMode = Property(
        str,
        _get_wechat_mode,
        _set_wechat_mode,
        notify=wechatRecoveryModeChanged,
    )

    def _get_login_timeout(self):
        return self._login_timeout

    def _set_login_timeout(self, value):
        value = max(30, min(300, int(value)))
        if value == self._login_timeout:
            return
        self._login_timeout = value
        self._settings.setValue("recovery/loginTimeout", value)
        self.loginTimeoutChanged.emit(value)

    loginTimeout = Property(
        int, _get_login_timeout, _set_login_timeout, notify=loginTimeoutChanged
    )

    isDark = Property(
        bool,
        lambda self: self._owner.isDark,
        lambda self, value: setattr(self._owner, "isDark", bool(value)),
        notify=appearanceChanged,
    )
    glassEnabled = Property(
        bool,
        lambda self: self._owner.glassEnabled,
        lambda self, value: setattr(self._owner, "glassEnabled", bool(value)),
        notify=appearanceChanged,
    )
    glassOpacity = Property(
        int,
        lambda self: self._owner.glassOpacity,
        lambda self, value: setattr(self._owner, "glassOpacity", int(value)),
        notify=appearanceChanged,
    )


class AgentController(QObject):
    stateChanged = Signal()
    inspectionChanged = Signal()
    notificationReceived = Signal(str, object)
    errorOccurred = Signal(str)
    helloReceived = Signal(object)
    connectionLost = Signal()
    replyReceived = Signal(int, object)
    rpcErrorReceived = Signal(int, int, str)

    def __init__(self, client: AgentClient | None = None, parent=None):
        super().__init__(parent)
        self._client = client or AgentClient(parent=self)
        self._state = str(getattr(self._client, "state", "stopped"))
        self._connected = bool(getattr(self._client, "connected", False))
        self._wechat_connected = False
        self._wechat_supported = False
        self._uia_ready = False
        self._restorable = False
        self._wechat_version = ""
        self._detail = "等待检测微信"
        self._inspect_request_id = 0
        self._client.stateChanged.connect(self._on_state)
        self._client.connectedChanged.connect(self._on_connected)
        self._client.replyReceived.connect(self._on_reply)
        self._client.rpcError.connect(self._on_rpc_error)
        self._client.notificationReceived.connect(self.notificationReceived)
        self._client.processError.connect(self.errorOccurred)
        if hasattr(self._client, "helloReceived"):
            self._client.helloReceived.connect(self.helloReceived)

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(bool, notify=stateChanged)
    def connected(self):
        return self._connected

    @Property(bool, notify=inspectionChanged)
    def wechatConnected(self):
        return self._wechat_connected

    @Property(bool, notify=inspectionChanged)
    def wechatSupported(self):
        return self._wechat_supported

    @Property(bool, notify=inspectionChanged)
    def uiaReady(self):
        return self._uia_ready

    @Property(bool, notify=inspectionChanged)
    def restorable(self):
        return self._restorable

    @Property(str, notify=inspectionChanged)
    def wechatVersion(self):
        return self._wechat_version

    @Property(str, notify=inspectionChanged)
    def detail(self):
        return self._detail

    @Property(bool, notify=inspectionChanged)
    def automationReady(self):
        return (
            self._connected
            and self._wechat_connected
            and self._wechat_supported
            and (self._uia_ready or self._restorable)
        )

    @Slot()
    def start(self) -> None:
        self._client.start()

    @Slot()
    def restart(self) -> None:
        restart = getattr(self._client, "restart", None)
        if restart is not None:
            restart()
            return
        self._client.close()
        self._client.start()

    @Slot(result=int)
    def inspect(self) -> int:
        if not self._connected:
            return 0
        self._inspect_request_id = self._client.call("wechat.inspect")
        return self._inspect_request_id

    @Slot(object)
    def applyInspection(self, result: dict[str, Any]) -> None:
        self._wechat_connected = bool(result.get("connected", False))
        self._wechat_supported = bool(result.get("supported", False))
        self._uia_ready = bool(result.get("uiaReady", False))
        self._restorable = bool(result.get("restorable", False))
        self._wechat_version = str(result.get("version", ""))
        self._detail = str(result.get("detail", ""))
        self.inspectionChanged.emit()

    def call(self, method: str, params: dict[str, Any] | None = None) -> int:
        return self._client.call(method, params or {})

    @Slot(str)
    def _on_state(self, state: str) -> None:
        self._state = state
        self.stateChanged.emit()

    @Slot(bool)
    def _on_connected(self, connected: bool) -> None:
        was_connected = self._connected
        self._connected = connected
        self.stateChanged.emit()
        self.inspectionChanged.emit()
        if connected:
            self.inspect()
        else:
            self._wechat_connected = False
            self._wechat_supported = False
            self._uia_ready = False
            self._restorable = False
            self._detail = "Agent 已断开"
            if was_connected:
                self.connectionLost.emit()

    @Slot(int, object)
    def _on_reply(self, request_id: int, result: Any) -> None:
        if request_id == self._inspect_request_id and isinstance(result, dict):
            self.applyInspection(result)
        self.replyReceived.emit(request_id, result)

    @Slot(int, int, str)
    def _on_rpc_error(self, request_id: int, code: int, message: str) -> None:
        self.rpcErrorReceived.emit(request_id, code, message)
        self.errorOccurred.emit(message)

    def close(self) -> None:
        shutdown = getattr(self._client, "shutdown", None)
        if shutdown is not None:
            shutdown()
        else:
            if self._connected:
                try:
                    self._client.call("agent.shutdown")
                except Exception:
                    pass
            self._client.close()


class TaskController(QObject):
    phaseChanged = Signal()
    activeChanged = Signal()
    progressChanged = Signal()
    currentStepChanged = Signal()
    errorChanged = Signal()
    recoveryRequiredChanged = Signal()

    def __init__(
        self,
        agent: AgentController,
        message: MessageController,
        friends: FriendController,
        settings: SettingsController,
        parent=None,
    ):
        super().__init__(parent)
        self._agent = agent
        self._message = message
        self._friends = friends
        self._settings = settings
        self._items = TaskItemModel(self)
        self._logs = RuntimeLogModel(self)
        self._phase = "idle"
        self._active = False
        self._task_id = ""
        self._kind = ""
        self._done = 0
        self._total = 0
        self._current_step = ""
        self._error = ""
        self._original_payload: dict[str, Any] | None = None
        self._completed_item_ids: set[str] = set()
        self._recovery_offset = 0
        self._restart_attempts = 0
        self._pending_resume = False
        self._recovery_required = False
        self._recovery_detail = ""
        self._wechat_restart_attempted = False
        self._pending_start_request_id = 0
        self._login_deadline = 0.0
        self._inspection_grace = QTimer(self)
        self._inspection_grace.setSingleShot(True)
        self._inspection_grace.setInterval(6_000)
        self._inspection_grace.timeout.connect(self._check_reconnect_inspection)
        self._recovery_poll = QTimer(self)
        self._recovery_poll.setInterval(2_000)
        self._recovery_poll.timeout.connect(self._poll_wechat_recovery)
        self._agent.notificationReceived.connect(self._on_notification)
        self._agent.errorOccurred.connect(self._set_error)
        self._agent.connectionLost.connect(self._on_connection_lost)
        self._agent.helloReceived.connect(self._on_agent_hello)
        self._agent.inspectionChanged.connect(self._resume_if_ready)
        self._agent.replyReceived.connect(self._on_agent_reply)
        self._agent.rpcErrorReceived.connect(self._on_agent_rpc_error)

    @Property(QObject, constant=True)
    def items(self):
        return self._items

    @Property(QObject, constant=True)
    def runtimeLogs(self):
        return self._logs

    @Property(str, notify=phaseChanged)
    def phase(self):
        return self._phase

    @Property(bool, notify=activeChanged)
    def active(self):
        return self._active

    @Property(str, notify=phaseChanged)
    def kind(self):
        return self._kind

    @Property(int, notify=progressChanged)
    def done(self):
        return self._done

    @Property(int, notify=progressChanged)
    def total(self):
        return self._total

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._done / self._total if self._total else 0.0

    @Property(str, notify=currentStepChanged)
    def currentStepCode(self):
        return self._current_step

    @Property(str, notify=currentStepChanged)
    def currentStepLabel(self):
        labels = MESSAGE_STEP_LABELS if self._kind == "message_send" else FRIEND_STEP_LABELS
        return labels.get(self._current_step, "等待任务开始")

    @Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @Property(bool, notify=recoveryRequiredChanged)
    def recoveryRequired(self):
        return self._recovery_required

    @Property(str, notify=recoveryRequiredChanged)
    def recoveryDetail(self):
        return self._recovery_detail

    def _set_recovery_required(self, required: bool, detail: str = "") -> None:
        changed = (
            required != self._recovery_required or detail != self._recovery_detail
        )
        self._recovery_required = required
        self._recovery_detail = detail
        if changed:
            self.recoveryRequiredChanged.emit()

    def _set_phase(self, phase: str) -> None:
        if phase != self._phase:
            self._phase = phase
            self.phaseChanged.emit()

    def _set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.activeChanged.emit()

    @Slot(str)
    def _set_error(self, error: str) -> None:
        self._error = error
        self.errorChanged.emit()

    def _start(self, kind: str, items: list[dict[str, Any]], options: dict[str, Any]) -> bool:
        if self._active:
            self._set_error("已有任务正在执行")
            return False
        if not self._agent.automationReady:
            self._set_error("仅支持已验证并已连接的微信 4.1.13.65")
            return False
        if not items:
            self._set_error("没有可执行的数据")
            return False
        self._task_id = uuid.uuid4().hex
        self._kind = kind
        self._done = 0
        self._total = len(items)
        self._current_step = ""
        self._error = ""
        self._logs.clear()
        self._items.replace(
            TaskDisplayItem(
                target=item.get("target") or item.get("account", ""),
                item_id=item["itemId"],
            )
            for item in items
        )
        payload = {
            "taskId": self._task_id,
            "kind": kind,
            "items": items,
            "options": options,
        }
        self._original_payload = copy.deepcopy(payload)
        self._completed_item_ids.clear()
        self._recovery_offset = 0
        self._restart_attempts = 0
        self._pending_resume = False
        self._set_recovery_required(False)
        self._wechat_restart_attempted = False
        self._inspection_grace.stop()
        self._recovery_poll.stop()
        try:
            self._pending_start_request_id = self._agent.call(
                "task.start", payload
            )
        except Exception as exc:
            self._pending_start_request_id = 0
            self._set_error(str(exc))
            return False
        self._set_active(True)
        self._set_phase("running")
        self.phaseChanged.emit()
        self.progressChanged.emit()
        self.currentStepChanged.emit()
        return True

    @Slot()
    def _on_connection_lost(self) -> None:
        if not self._active or self._phase == "stopping":
            return
        if (
            self._original_payload
            and self._original_payload.get("options", {}).get("useForward")
        ):
            self._pending_resume = False
            self._set_active(False)
            self._set_phase("error")
            self._set_error(
                "合并转发任务已中断，为避免重复上传或转发，不会自动恢复"
            )
            self._agent.restart()
            return
        if self._restart_attempts >= self._settings.agentRestartLimit:
            self._set_active(False)
            self._set_phase("error")
            self._set_error("Agent 已断开，自动重启次数已用尽；任务已停止")
            return
        self._restart_attempts += 1
        self._pending_resume = False
        self._set_phase("recovering")
        self._set_error(
            f"Agent 连接中断，正在进行第 {self._restart_attempts} 次安全恢复"
        )
        self._agent.restart()

    @Slot(object)
    def _on_agent_hello(self, hello: dict[str, Any]) -> None:
        recovery = hello.get("recovery") if isinstance(hello, dict) else None
        if not self._active:
            if recovery:
                self._agent.call("recovery.approve", {"decision": "discard"})
            return
        if self._phase != "recovering":
            return
        if recovery:
            if recovery.get("taskId") != self._task_id:
                self._set_active(False)
                self._set_phase("error")
                self._set_error("发现其他任务的未决安全记录，已停止自动恢复")
                return
            self._mark_boundary_item_unknown(recovery)
            self._agent.call(
                "recovery.approve", {"decision": "mark_unknown"}
            )
        self._pending_resume = True
        self._inspection_grace.start()
        self._resume_if_ready()

    def _mark_boundary_item_unknown(self, recovery: dict[str, Any]) -> None:
        item_id = str(recovery.get("itemId", ""))
        if not item_id or item_id in self._completed_item_ids:
            return
        boundary = str(recovery.get("boundary", ""))
        step = "submit_verified" if boundary.startswith("submit") else "send_verified"
        detail = (
            "Agent 在提交后中断，本条标记为结果未知且不会再次提交"
            if self._kind == "friend_add"
            else "Agent 在发送后中断，本条标记为结果未知且不会自动重发"
        )
        event = {
            "taskId": self._task_id,
            "itemId": item_id,
            "step": step,
            "outcome": "unknown",
            "detail": detail,
            "done": min(self._total, self._done + 1),
            "total": self._total,
            "timestamp": str(recovery.get("timestamp", "")),
        }
        self._items.apply_event(event)
        self._logs.append_event(event)
        if self._kind == "friend_add":
            self._friends.model.apply_event(event)
        self._completed_item_ids.add(item_id)
        self._done = event["done"]
        self._current_step = step
        self.progressChanged.emit()
        self.currentStepChanged.emit()

    @Slot()
    def _resume_if_ready(self) -> None:
        if not self._pending_resume or not self._active:
            return
        if not self._agent.automationReady or self._original_payload is None:
            return
        self._inspection_grace.stop()
        self._recovery_poll.stop()
        self._set_recovery_required(False)
        remaining = [
            item
            for item in self._original_payload["items"]
            if item["itemId"] not in self._completed_item_ids
        ]
        if not remaining:
            self._pending_resume = False
            self._set_active(False)
            self._set_phase("done")
            self._set_error("")
            return
        payload = copy.deepcopy(self._original_payload)
        payload["items"] = remaining
        self._recovery_offset = self._done
        try:
            self._pending_start_request_id = self._agent.call(
                "task.start", payload
            )
        except Exception as exc:
            self._pending_start_request_id = 0
            self._set_active(False)
            self._set_phase("error")
            self._set_error(f"恢复任务失败：{exc}")
            return
        self._pending_resume = False
        self._set_phase("running")
        self._set_error("")

    @Slot(int, object)
    def _on_agent_reply(self, request_id: int, result: Any) -> None:
        if request_id != self._pending_start_request_id:
            return
        self._pending_start_request_id = 0
        if isinstance(result, dict) and result.get("accepted", True):
            return
        self._set_active(False)
        self._set_phase("error")
        self._set_error("Agent 未接受任务")

    @Slot(int, int, str)
    def _on_agent_rpc_error(
        self, request_id: int, _code: int, message: str
    ) -> None:
        if request_id != self._pending_start_request_id:
            return
        self._pending_start_request_id = 0
        self._pending_resume = False
        self._set_active(False)
        self._set_phase("error")
        self._set_error(message)

    @Slot()
    def _check_reconnect_inspection(self) -> None:
        if not self._pending_resume or not self._active or self._agent.automationReady:
            return
        mode = self._settings.wechatRecoveryMode
        if mode == "manual":
            self._fail_recovery("微信 UIA 仍不可用，请手动重启微信后重新开始任务")
            return
        if mode == "silent":
            self._request_wechat_restart()
            return
        self._set_phase("awaiting_recovery")
        self._set_recovery_required(
            True,
            "Agent 已恢复，但微信 UIA 仍不可用。是否重启微信并等待重新登录？",
        )

    @Slot()
    def approveWechatRestart(self) -> None:
        if not self._recovery_required:
            return
        self._request_wechat_restart()

    def _request_wechat_restart(self) -> None:
        if self._wechat_restart_attempted or not self._active:
            return
        self._wechat_restart_attempted = True
        self._set_recovery_required(False)
        self._set_phase("waiting_login")
        self._set_error("正在重启微信并等待登录")
        self._login_deadline = time.monotonic() + self._settings.loginTimeout
        try:
            self._agent.call(
                "recovery.approve",
                {
                    "decision": "restart_wechat",
                    "loginTimeout": self._settings.loginTimeout,
                },
            )
        except Exception as exc:
            self._fail_recovery(f"请求重启微信失败：{exc}")
            return
        self._recovery_poll.start()

    @Slot()
    def stopRecovery(self) -> None:
        if not self._active:
            return
        self._agent.call("recovery.approve", {"decision": "stop"})
        self._fail_recovery("用户取消微信恢复，任务已安全停止")

    def _poll_wechat_recovery(self) -> None:
        if not self._active or not self._pending_resume:
            self._recovery_poll.stop()
            return
        if self._agent.automationReady:
            self._resume_if_ready()
            return
        if time.monotonic() >= self._login_deadline:
            self._fail_recovery("等待微信登录超时，任务已停止")
            return
        self._agent.inspect()

    def _fail_recovery(self, detail: str) -> None:
        self._inspection_grace.stop()
        self._recovery_poll.stop()
        self._pending_resume = False
        self._set_recovery_required(False)
        self._set_active(False)
        self._set_phase("error")
        self._set_error(detail)

    @Slot(result=bool)
    def startMessage(self) -> bool:
        items = self._message.build_items()
        if not self._message.templateText and not self._message.filePaths:
            self._set_error("消息内容和附件不能同时为空")
            return False
        return self._start(
            "message_send",
            items,
            {
                "intervalMin": self._message.intervalMin,
                "intervalMax": self._message.intervalMax,
                "unknownPolicy": self._settings.unknownPolicy,
                "useForward": self._message.useForward,
                "filePaths": self._message.filePaths,
            },
        )

    @Slot(result=bool)
    def startFriends(self) -> bool:
        if self._active:
            self._set_error("已有任务正在执行")
            return False
        return self._start(
            "friend_add",
            self._friends.build_items(),
            {
                "intervalMin": self._friends.intervalMin,
                "intervalMax": self._friends.intervalMax,
                "unknownPolicy": self._settings.unknownPolicy,
            },
        )

    @Slot()
    def pause(self) -> None:
        if self._active and self._phase == "running":
            self._agent.call("task.pause", {"taskId": self._task_id})
            self._set_phase("paused")

    @Slot()
    def resume(self) -> None:
        if self._active and self._phase == "paused":
            self._agent.call("task.resume", {"taskId": self._task_id})
            self._set_phase("running")

    @Slot()
    def stop(self) -> None:
        if self._active:
            self._agent.call("task.stop", {"taskId": self._task_id})
            self._set_phase("stopping")

    @Slot(str, object)
    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "task.event" and params.get("taskId") == self._task_id:
            params = dict(params)
            if self._recovery_offset:
                params["done"] = min(
                    self._total,
                    self._recovery_offset + int(params.get("done", 0)),
                )
                params["total"] = self._total
            previous_done = self._done
            self._items.apply_event(params)
            self._logs.append_event(params)
            if self._kind == "friend_add":
                self._friends.model.apply_event(params)
            self._done = int(params.get("done", self._done))
            self._total = int(params.get("total", self._total))
            self._current_step = str(params.get("step", ""))
            if self._done > previous_done:
                self._completed_item_ids.add(str(params.get("itemId", "")))
            self.progressChanged.emit()
            self.currentStepChanged.emit()
            if self._current_step in {"send_verified", "submit_verified"}:
                self._agent.call(
                    "recovery.approve",
                    {
                        "decision": "acknowledge",
                        "taskId": self._task_id,
                        "itemId": str(params.get("itemId", "")),
                    },
                )
        elif method == "task.finished" and params.get("taskId") == self._task_id:
            self._pending_start_request_id = 0
            raw_done = int(params.get("done", 0))
            self._done = min(
                self._total,
                self._recovery_offset + raw_done,
            )
            self._set_active(False)
            self._set_phase("done")
            self.progressChanged.emit()
        elif method == "agent.status":
            status = str(params.get("status", ""))
            if status == "recovered" and self._pending_resume:
                self._agent.inspect()
            elif status == "recovery_failed" and self._pending_resume:
                self._fail_recovery(
                    "微信恢复失败：" + str(params.get("detail", "未知错误"))
                )

    @Slot(str, result=str)
    def stepLabel(self, code: str) -> str:
        return {**MESSAGE_STEP_LABELS, **FRIEND_STEP_LABELS}.get(code, code)

    @Slot(str, result=bool)
    def exportResults(self, file_url: str) -> bool:
        path = file_url.replace("file:///", "")
        if sys.platform == "win32":
            path = path.lstrip("/")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["目标", "结果", "步骤", "详情", "耗时"])
                for item in self._items._items:
                    writer.writerow(
                        [
                            item.target,
                            item.result,
                            self.stepLabel(item.step_code),
                            item.detail,
                            item.duration,
                        ]
                    )
            return True
        except Exception as exc:
            self._set_error(str(exc))
            return False


__all__ = [
    "AgentController",
    "FriendController",
    "FRIEND_STEP_LABELS",
    "MessageController",
    "MESSAGE_STEP_LABELS",
    "SettingsController",
    "TaskController",
]
