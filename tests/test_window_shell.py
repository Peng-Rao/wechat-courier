"""Window capability and lifecycle contracts without a WeChat connection."""

import pytest
import os
import subprocess
import sys
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt, Signal
from PySide6.QtGui import QPlatformSurfaceEvent, QWindow
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

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
        self.exposed = True
        self.visibility_value = QWindow.Windowed
        self.updates = 0
        self.geometry_value = QRect(250, 30, 960, 680)
        self.geometry_changes = []

    def winId(self):
        return self.hwnd

    def setFlags(self, flags):
        self.flags_value = flags

    def isExposed(self):
        return self.exposed

    def visibility(self):
        return self.visibility_value

    def update(self):
        self.updates += 1

    def geometry(self):
        return QRect(self.geometry_value)

    def setGeometry(self, value):
        self.geometry_value = QRect(value)
        self.geometry_changes.append(QRect(value))

    def change_visibility(self, value):
        self.visibility_value = value
        self.exposed = value not in (QWindow.Hidden, QWindow.Minimized)
        self.visibilityChanged.emit(value)


class SurfaceEvent(QEvent):
    def __init__(self, kind):
        super().__init__(QEvent.PlatformSurface)
        self.kind = kind

    def surfaceEventType(self):
        return self.kind


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
    calls = []
    monkeypatch.setattr(QQuickWindow, "setGraphicsApi", calls.append)
    for name in ("QSG_RHI_BACKEND", "QT_QUICK_BACKEND", "QMLSCENE_DEVICE", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("QT_D3D_NO_FLIP", raising=False)
    module.configure_native_renderer(native_supported=False)
    assert calls == []
    module.configure_native_renderer(native_supported=True)
    assert calls == [QSGRendererInterface.OpenGL]
    assert "QT_D3D_NO_FLIP" not in module.os.environ


@pytest.mark.parametrize("name,value", [
    ("QSG_RHI_BACKEND", "d3d11"), ("QT_QUICK_BACKEND", "software"),
    ("QMLSCENE_DEVICE", "softwarecontext"), ("QT_QPA_PLATFORM", "offscreen"),
    ("QT_QPA_PLATFORM", "minimal"),
])
def test_explicit_renderer_and_non_native_platform_are_preserved(monkeypatch, name, value):
    calls = []
    monkeypatch.setattr(QQuickWindow, "setGraphicsApi", calls.append)
    monkeypatch.setenv(name, value)
    shell_module().configure_native_renderer(native_supported=True)
    assert calls == []
    assert shell_module().os.environ[name] == value


def test_renderer_uses_actual_qt_platform_before_first_quick_window():
    result = subprocess.run([sys.executable, "-c", '''
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from app.window_shell import configure_native_renderer
app = QGuiApplication(["gate", "-platform", "minimal"])
calls = []
QQuickWindow.setGraphicsApi = calls.append
configure_native_renderer(native_supported=True)
assert app.platformName() == "minimal"
assert calls == [], calls
'''], env={**os.environ, "QT_QPA_PLATFORM": "windows"}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("visibility", [QWindow.Windowed, QWindow.Maximized, QWindow.FullScreen])
def test_restore_coalesces_material_repair_and_one_redraw(qapp, monkeypatch, visibility):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(True, True, 72)
    window = FakeWindow()
    shell.attach(window)
    calls.clear()
    window.change_visibility(QWindow.Minimized)
    QCoreApplication.processEvents()
    assert calls == [] and window.updates == 0
    window.change_visibility(visibility)
    shell.eventFilter(window, QEvent(QEvent.Expose))
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert window.updates == 1
    assert window.geometry_changes == []
    assert calls.count(("extend_native_frame", (123,))) == 1
    assert calls.count(("apply_window_backdrop", (123, True, True, 72))) == 1
    assert shell._layout_mode == {QWindow.Windowed: "normal", QWindow.Maximized: "maximized",
                                 QWindow.FullScreen: "fullscreen"}[visibility]
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert window.updates == 1
    shell.detach()


def test_hidden_restore_waits_for_exposure_without_polling(qapp, monkeypatch):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    window = FakeWindow()
    shell.attach(window)
    calls.clear()
    window.change_visibility(QWindow.Hidden)
    window.visibility_value = QWindow.Windowed
    window.visibilityChanged.emit(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert calls == [] and window.updates == 0
    window.exposed = True
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert window.updates == 1
    shell.detach()


@pytest.mark.parametrize("failure", ["extend_native_frame", "set_window_corner_preference", "apply_window_backdrop"])
def test_restore_material_failure_uses_opaque_background(qapp, monkeypatch, failure):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(False, True, 45)
    window = FakeWindow()
    shell.attach(window)
    monkeypatch.setattr(wh, failure, lambda *args: False)
    window.change_visibility(QWindow.Minimized)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert not shell.backdropAvailable
    assert shell.nativeFrameEnabled
    assert shell._visuals == (False, True, 45)
    assert window.updates == 1
    shell.detach()


def test_theme_change_cannot_clear_failed_frame_recovery(qapp, monkeypatch):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(False, True, 45)
    window = FakeWindow()
    shell.attach(window)
    monkeypatch.setattr(wh, "extend_native_frame", lambda *args: False)
    window.change_visibility(QWindow.Minimized)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    shell.applyVisuals(True, True, 72)
    assert not shell.backdropAvailable
    monkeypatch.setattr(wh, "extend_native_frame", lambda *args: True)
    window.change_visibility(QWindow.Minimized)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert shell.backdropAvailable and shell._visuals == (True, True, 72)
    shell.detach()


@pytest.mark.parametrize("failure", ["extend_native_frame", "set_window_corner_preference"])
def test_new_handle_material_failure_stays_opaque(qapp, monkeypatch, failure):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(False, True, 45)
    window = FakeWindow()
    shell.attach(window)
    window.change_visibility(QWindow.Hidden)
    window.hwnd = 456
    monkeypatch.setattr(wh, failure, lambda *args: False)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert not shell.backdropAvailable
    shell.applyVisuals(True, True, 72)
    assert not shell.backdropAvailable
    assert shell._visuals == (True, True, 72)
    shell.detach()


def test_legacy_restore_reapplies_backdrop(qapp, monkeypatch):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=False)
    shell.applyVisuals(False, True, 72)
    window = FakeWindow()
    shell.attach(window)
    calls.clear()
    window.change_visibility(QWindow.Hidden)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert ("apply_window_backdrop", (123, False, True, 72)) in calls
    assert not any(name == "extend_native_frame" for name, _ in calls)
    assert window.updates == 1
    shell.detach()


@pytest.mark.parametrize("cancel", ["detach", "destroy"])
def test_pending_restore_is_cancelled_with_window(qapp, monkeypatch, cancel):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    window = FakeWindow()
    shell.attach(window)
    window.change_visibility(QWindow.Minimized)
    window.change_visibility(QWindow.Windowed)
    if cancel == "detach":
        shell.detach()
    else:
        window.destroyed.emit()
    calls.clear()
    QCoreApplication.processEvents()
    assert calls == [] and window.updates == 0
    assert shell._window is None
    assert shell._surface_geometry is None


@pytest.mark.parametrize("layout", ["normal", "maximized", "fullscreen"])
def test_surface_recreation_binds_frame_before_exposure_and_preserves_geometry(qapp, monkeypatch, layout):
    calls = mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    shell.applyVisuals(False, False, 72)
    window = FakeWindow()
    shell.attach(window)
    shell.setLayoutMode(layout)
    shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed))
    assert ("uninstall_window_hit_test", (123,)) in calls
    window.hwnd = 456
    window.exposed = False
    window.geometry_value = QRect(250, 8, 962, 703)
    calls.clear()
    shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceCreated))
    QCoreApplication.processEvents()
    assert shell._hwnd == 456
    assert ("install_native_window_hit_test", (456,)) in calls
    assert not any(name == "apply_window_backdrop" for name, _ in calls)
    assert window.updates == 0 and window.geometry_changes == []
    window.exposed = True
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert shell._hwnd == 456 and window.updates == 1
    changes = [QRect(250, 30, 960, 680)] if layout == "normal" else []
    assert window.geometry_changes == changes
    assert shell._surface_geometry is None
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert window.updates == 1 and window.geometry_changes == changes
    shell.detach()


@pytest.mark.parametrize("native", [False, True])
def test_multiple_surface_recreations_keep_first_pending_geometry(qapp, monkeypatch, native):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=native)
    window = FakeWindow()
    shell.attach(window)
    original = window.geometry()
    window.exposed = False
    for hwnd in (456, 789):
        shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed))
        window.geometry_value = QRect(250, 8, 962, 703)
        window.hwnd = hwnd
        shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceCreated))
        QCoreApplication.processEvents()
    window.exposed = True
    shell.eventFilter(window, QEvent(QEvent.Expose))
    QCoreApplication.processEvents()
    assert window.geometry_changes == [original]
    assert shell._hwnd == 789 and window.updates == 1
    shell.detach()


@pytest.mark.parametrize("layout", ["maximized", "fullscreen"])
def test_recreation_does_not_apply_maximized_snapshot_to_normal_window(qapp, monkeypatch, layout):
    mock_native(monkeypatch)
    shell = shell_module().WindowShellController(native_supported=True)
    window = FakeWindow()
    shell.attach(window)
    shell.setLayoutMode(layout)
    window.geometry_value = QRect(0, 0, 1536, 816)
    window.exposed = False
    shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed))
    window.hwnd = 456
    shell.eventFilter(window, SurfaceEvent(QPlatformSurfaceEvent.SurfaceCreated))
    window.geometry_value = QRect(250, 30, 960, 680)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    assert window.geometry_changes == []
    assert window.geometry() == QRect(250, 30, 960, 680)
    shell.detach()


def test_window_diagnostics_persist_only_render_metadata(tmp_path, qapp, monkeypatch):
    module = shell_module()
    handler = module.configure_window_diagnostics(tmp_path)
    mock_native(monkeypatch)
    shell = module.WindowShellController(native_supported=True)
    window = FakeWindow()
    shell.attach(window)
    window.change_visibility(QWindow.Minimized)
    window.change_visibility(QWindow.Windowed)
    QCoreApplication.processEvents()
    shell.detach()
    handler.flush()
    text = (tmp_path / "window-rendering.log").read_text(encoding="utf-8")
    assert "renderer=unknown" in text and "hwnd=123" in text
    assert "qt=" in text and "backdrop=True" in text
    assert "contact" not in text and "message" not in text
    module.logging.getLogger(module.__name__).removeHandler(handler)
    handler.close()


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
