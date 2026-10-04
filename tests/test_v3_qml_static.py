from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def qml(name):
    return (ROOT / "qml" / "components" / name).read_text(encoding="utf-8")


def test_app_has_two_real_workspaces_and_settings_center():
    app = (ROOT / "qml" / "App.qml").read_text(encoding="utf-8")
    assert "消息群发" in app
    assert "自动发送好友申请" in app
    assert "MessageWorkspace" in app
    assert "FriendWorkspace" in app
    assert "SettingsDialog" in app


def test_message_compose_has_preview_but_no_send_log_tab():
    source = qml("MessageWorkspace.qml")
    assert "消息预览" in source
    assert "TaskMonitor" in source
    assert "发送日志" not in source
    assert "startMessage" in source


def test_friend_workspace_has_editable_import_table_and_selection_limit():
    source = qml("FriendWorkspace.qml")
    assert "导入 Excel / CSV" in source
    assert "TableView" in source
    assert "setCell" in source
    assert "selectedCount" in source
    assert "root.friendBackend.batchLimit" in source
    assert "/ 20" not in source
    assert "startFriends" in source
    assert 'status === "working" ? "执行中"' in source
    assert '"预检完成" : "已提交"' in source
    assert "开始添加好友" in source
    assert "将实际提交好友申请" in source
    assert "friendSubmitConfirmDialog" in source
    assert "提交后无法撤回" in source


def test_friend_workspace_exposes_right_click_add_and_delete_actions():
    source = qml("FriendWorkspace.qml")

    assert "function appendManualRecord()" in source
    assert "function removeContextRecord()" in source
    assert "appendEmptyRecord()" in source
    assert "removeRecord(root.contextRow)" in source
    assert "新增一行" in source
    assert "删除此行" in source


def test_active_task_locks_navigation_settings_and_configuration_controls():
    app = (ROOT / "qml" / "App.qml").read_text(encoding="utf-8")
    main = (ROOT / "qml" / "main.qml").read_text(encoding="utf-8")
    titlebar = qml("WxTitleBar.qml")
    friends = qml("FriendWorkspace.qml")
    messages = qml("MessageWorkspace.qml")

    assert "readonly property bool interactionLocked" in app
    assert "if (root.interactionLocked) return" in app
    assert "enabled: !root.interactionLocked" in app
    assert "settingsEnabled:" in main
    assert "property bool settingsEnabled: true" in titlebar
    assert "enabled: root.settingsEnabled" in titlebar
    assert "readonly property bool interactionLocked" in friends
    assert "readonly property bool interactionLocked" in messages
    assert "useForward" not in messages
    assert "enabled: !root.interactionLocked" in messages


def test_monitor_uses_chinese_state_machine_and_runtime_log():
    source = qml("TaskMonitor.qml")
    assert "消息发送状态" in source
    assert "好友申请状态" in source
    assert "currentStepCode" in source
    assert "runtimeLogs" in source
    assert "发送结果已确认" in source
    assert "表单预检已完成" in source
    assert "提交结果已确认" in source
    assert "好友表单预检状态" in source
    assert 'result === "working" ? "执行中"' in source


def test_monitor_distinguishes_completion_from_results_and_gates_recovery():
    source = qml("TaskMonitor.qml")

    assert "处理进度" in source
    assert "成功 " in source
    assert "失败 " in source
    assert "未知 " in source
    assert "successCount" in source
    assert "failureCount" in source
    assert "unknownCount" in source
    assert "safeRetryAvailable" in source
    assert "安全重试本条" in source
    assert "root.agentBackend.windowResponsive" in source
    assert "检测微信恢复" in source
    assert "exportDiagnostics" in source


def test_settings_center_contains_task_recovery_and_appearance_sections():
    source = qml("SettingsDialog.qml")
    for label in ("消息群发", "自动发送好友申请", "自动化与恢复", "外观"):
        assert label in source
    assert "glassOpacity" in source
    assert "unknownPolicy" in source


def test_settings_dialog_guards_every_mutating_callback_while_task_is_active():
    source = qml("SettingsDialog.qml")

    assert "readonly property bool interactionLocked" in source
    assert "function applyIfUnlocked(callback)" in source
    assert source.count("root.applyIfUnlocked(function()") == 16
    assert "onInteractionLockedChanged" in source
    assert "运行中也可修改" not in source


def test_settings_pages_use_the_scroll_viewport_width():
    source = qml("SettingsDialog.qml")

    assert source.count("contentWidth: availableWidth") == 4
    assert source.count("ScrollBar.horizontal.policy: ScrollBar.AlwaysOff") == 4
    assert "Layout.minimumWidth: 0" in source
    assert "Layout.minimumWidth: 184" in source
    assert "Layout.maximumWidth: 184" in source


def test_default_greeting_field_has_room_for_the_full_text():
    source = qml("SettingsDialog.qml")

    greeting_start = source.index('title: "默认打招呼语"')
    greeting_end = source.index('title: "默认后缀"')
    greeting_row = source[greeting_start:greeting_end]
    assert "width: 360" in greeting_row


def test_main_window_fits_available_geometry_before_first_show():
    source = (ROOT / "qml" / "main.qml").read_text(encoding="utf-8")

    assert "visible: false" in source
    assert "opacity: 1" in source
    assert "opacity: 0" not in source
    assert "function initializeWindowGeometry()" in source
    assert "Screen.desktopAvailableWidth" in source
    assert "Screen.desktopAvailableHeight" in source
    assert "root.screen.availableGeometry" not in source
    assert "Qt.callLater(root.initializeWindowGeometry)" in source
    assert "root.show()" in source
    assert "root.opacity =" not in source


def test_titlebar_displays_agent_and_weixin_health():
    source = qml("WxTitleBar.qml")
    assert "Agent 在线" in source
    assert "版本受支持" in source
    assert "自动化已就绪" in source
    assert "windowResponsive" in source
    assert "sessionReady" in source
    assert "wechatVersion" in source
    assert "openSettings" in source


def test_recovery_confirmation_is_chinese_and_requires_explicit_action():
    source = qml("RecoveryDialog.qml")
    app = (ROOT / "qml" / "App.qml").read_text(encoding="utf-8")

    assert "重启微信并继续" in source
    assert "停止任务" in source
    assert "approveWechatRestart" in source
    assert "stopRecovery" in source
    assert "RecoveryDialog" in app
