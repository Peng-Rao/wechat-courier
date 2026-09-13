from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def qml(name):
    return (ROOT / "qml" / "components" / name).read_text(encoding="utf-8")


def test_app_has_two_real_workspaces_and_settings_center():
    app = (ROOT / "qml" / "App.qml").read_text(encoding="utf-8")
    assert "消息群发" in app
    assert "批量加好友" in app
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
    assert "/ 20" in source
    assert "startFriends" in source


def test_monitor_uses_chinese_state_machine_and_runtime_log():
    source = qml("TaskMonitor.qml")
    assert "消息发送状态" in source
    assert "好友申请状态" in source
    assert "currentStepCode" in source
    assert "runtimeLogs" in source
    assert "发送结果已确认" in source
    assert "提交结果已确认" in source


def test_settings_center_contains_task_recovery_and_appearance_sections():
    source = qml("SettingsDialog.qml")
    for label in ("消息群发", "批量加好友", "自动化与恢复", "外观"):
        assert label in source
    assert "glassOpacity" in source
    assert "unknownPolicy" in source


def test_titlebar_displays_agent_and_weixin_health():
    source = qml("WxTitleBar.qml")
    assert "Agent" in source
    assert "微信" in source
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
