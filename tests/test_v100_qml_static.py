from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def qml(name):
    return (ROOT / "qml" / "components" / name).read_text(encoding="utf-8")


def test_message_editor_and_previews_have_real_scroll_containers():
    text = qml("MessageWorkspace.qml")
    assert 'objectName: "messageRecipientsScrollBar"' in text
    assert 'objectName: "messageTemplateScrollBar"' in text
    assert 'objectName: "messagePreviewScrollView"' in text
    assert "attachmentPreviews" in text
    assert "AttachmentImageViewer" in text
    assert "useForward" not in text


def test_range_controls_and_source_risk_location_are_present():
    text = qml("FriendWorkspace.qml")
    for name in ("friendRangeStart", "friendRangeEnd", "selectFriendRangeButton", "clearFriendSelectionButton"):
        assert f'objectName: "{name}"' in text
    assert "selectRange(" in text
    assert "selectFirstValid" not in text
    assert "riskStopItemId" in text


def test_both_monitors_use_shared_clock_local_time_and_risk_highlight():
    text = qml("TaskMonitor.qml")
    assert "elapsedLabel" in text
    assert "waitingRemaining" in text
    assert "localTime" in text
    assert "timestamp.slice" not in text
    assert "riskStopItemId" in text
    assert "sourceRow" in text
