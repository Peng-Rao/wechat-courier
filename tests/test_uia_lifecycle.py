from __future__ import annotations

from src.core import uiautomation as uia


def test_reset_uia_client_releases_the_process_singleton():
    original = uia._AutomationClient._instance
    sentinel = object()
    uia._AutomationClient._instance = sentinel
    try:
        uia.ResetUIAutomationClientInCurrentThread()
        assert uia._AutomationClient._instance is None
    finally:
        uia._AutomationClient._instance = original
