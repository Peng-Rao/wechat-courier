"""Window capability and lifecycle contracts without a WeChat connection."""

import pytest
from PySide6.QtCore import QObject, Qt, Signal

from app import win32_helper as wh


def shell_module():
    from app import window_shell
    return window_shell


@pytest.mark.parametrize("platform,build,version,expected", [
    ("windows", 26200, "6.11.1", True),
    ("windows", 22000, "6.9.0", True),
    ("windows", 19045, "6.11.1", False),
    ("windows", 26200, "6.5.2", False),
    ("offscreen", 26200, "6.11.1", False),
    ("xcb", 26200, "6.11.1", False),
])
def test_native_frame_capability(platform, build, version, expected):
    assert shell_module().native_frame_supported(platform, build, version) is expected


def test_native_flags_keep_qml_caption_controls():
    shell = shell_module().WindowShellController(native_supported=True)
    flags = Qt.WindowType(shell.initialWindowFlags)
    assert not flags & Qt.ExpandedClientAreaHint
    assert flags & Qt.CustomizeWindowHint
    assert not flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowMinMaxButtonsHint
    assert flags & Qt.WindowCloseButtonHint


def test_legacy_flags_preserve_existing_shell():
    shell = shell_module().WindowShellController(native_supported=False)
    flags = Qt.WindowType(shell.initialWindowFlags)
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowMinMaxButtonsHint


class FakeWindow(QObject):
    visibilityChanged = Signal(object)

    def __init__(self, hwnd=123):
        super().__init__()
        self.hwnd = hwnd
        self.flags_value = Qt.Window

    def winId(self):
        return self.hwnd

    def setFlags(self, flags):
        self.flags_value = flags


def mock_native(monkeypatch):
    calls = []
    for name in ("install_native_window_hit_test", "install_frameless_window_hit_test",
                 "uninstall_window_hit_test", "set_window_corner_preference",
                 "extend_native_frame", "apply_window_backdrop", "set_immersive_dark_mode"):
        monkeypatch.setattr(wh, name, lambda *args, name=name: calls.append((name, args)) or True)
    monkeypatch.setattr(wh, "set_window_interaction_callback", lambda *args: None)
    return calls


def test_visuals_wait_for_real_window_handle_and_follow_handle_recreation(monkeypatch):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(True, True, 45)
    assert calls == []
    window = FakeWindow(hwnd=2**33 + 123)
    shell.attach(window)
    assert ("apply_window_backdrop", (window.hwnd, True, True, 45)) in calls
    shell.applyVisuals(False, False, 72)
    assert calls[-1] == ("apply_window_backdrop", (window.hwnd, False, False, 72))
    window.hwnd += 1
    shell.attach(window)
    assert calls[-1] == ("apply_window_backdrop", (window.hwnd, False, False, 72))
    shell.detach()


def test_renderer_configuration_is_process_local_and_platform_gated(monkeypatch):
    module = shell_module()
    monkeypatch.delenv("QT_D3D_NO_FLIP", raising=False)
    module.configure_native_renderer(native_supported=False)
    assert "QT_D3D_NO_FLIP" not in module.os.environ
    module.configure_native_renderer(native_supported=True)
    assert module.os.environ["QT_D3D_NO_FLIP"] == "1"


def test_backdrop_failure_requests_opaque_fallback_without_changing_preference(monkeypatch):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    window = FakeWindow()
    shell.attach(window)
    monkeypatch.setattr(wh, "apply_window_backdrop", lambda *args: False)
    shell.applyVisuals(False, True, 45)
    assert not shell.backdropAvailable
    assert shell._visuals == (False, True, 45)
    monkeypatch.setattr(wh, "apply_window_backdrop", lambda *args: True)
    shell.applyVisuals(True, True, 72)
    assert shell.backdropAvailable
    shell.detach()


def test_attach_is_idempotent_and_detach_releases_hook(monkeypatch):
    module = shell_module()
    calls = mock_native(monkeypatch)
    window = FakeWindow()
    shell = module.WindowShellController(native_supported=True)
    assert shell.attach(window)
    assert shell.attach(window)
    assert calls.count(("install_native_window_hit_test", (123,))) == 1
    shell.detach()
    shell.detach()
    assert calls.count(("uninstall_window_hit_test", (123,))) == 1


def test_layout_modes_apply_rounding_only_in_normal_mode(monkeypatch):
    module = shell_module()
    calls = mock_native(monkeypatch)
    shell = module.WindowShellController(native_supported=True)
    window = FakeWindow()
    assert shell.attach(window)
    for mode, rounded in [("left", False), ("right", False), ("maximized", False),
                          ("fullscreen", False), ("normal", True)]:
        shell.setLayoutMode(mode)
        assert calls[-1] == ("set_window_corner_preference", (123, rounded))
    shell.detach()


def test_new_handle_unhooks_old_before_binding(monkeypatch):
    module = shell_module()
    calls = mock_native(monkeypatch)
    shell = module.WindowShellController(native_supported=True)
    window = FakeWindow()
    assert shell.attach(window)
    window.hwnd = 456
    assert shell.attach(window)
    assert ("uninstall_window_hit_test", (123,)) in calls
    assert calls.index(("uninstall_window_hit_test", (123,))) < calls.index(
        ("install_native_window_hit_test", (456,)))
    shell.detach()


def test_corner_failure_falls_back_without_throwing(monkeypatch):
    module = shell_module()
    calls = mock_native(monkeypatch)
    monkeypatch.setattr(wh, "set_window_corner_preference", lambda *args: False)
    shell = module.WindowShellController(native_supported=True)
    window = FakeWindow()
    assert shell.attach(window)
    assert not shell.nativeFrameEnabled
    assert shell.fallbackReason
    assert ("uninstall_window_hit_test", (123,)) in calls
    assert any(name == "install_frameless_window_hit_test" for name, _ in calls)
    shell.detach()
