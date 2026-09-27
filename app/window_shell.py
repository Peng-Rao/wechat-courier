"""Native window frame and backdrop lifecycle, independent of automation."""

import logging
import os
import sys

from PySide6.QtCore import QEvent, QMargins, QObject, Property, Qt, QTimer, Signal, Slot, qVersion
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent, QWindow

from app import win32_helper as wh


def native_frame_supported(platform_name: str, windows_build: int, qt_version: str) -> bool:
    try:
        version = tuple(int(part) for part in qt_version.split(".")[:2])
    except (ValueError, TypeError, AttributeError):
        return False
    return platform_name == "windows" and windows_build >= 22000 and version >= (6, 9)


def configure_native_renderer(*, native_supported: bool | None = None) -> None:
    """Configure before QGuiApplication creates its D3D swap chains."""
    if native_supported is None:
        build = sys.getwindowsversion().build if sys.platform == "win32" else 0
        native_supported = native_frame_supported("windows" if build else "", build, qVersion())
    if native_supported:
        # Qt's flip swap chain makes this non-layered DWM client surface opaque.
        # The legacy D3D11 swap chain preserves alpha without WS_EX_LAYERED.
        os.environ["QT_D3D_NO_FLIP"] = "1"


class WindowShellController(QObject):
    flagsChanged = Signal()
    nativeFrameEnabledChanged = Signal()
    fallbackReasonChanged = Signal()
    backdropAvailableChanged = Signal()
    interactiveMoveStarted = Signal()

    def __init__(self, parent=None, *, native_supported: bool | None = None):
        super().__init__(parent)
        if native_supported is None:
            application = QGuiApplication.instance()
            platform = application.platformName() if isinstance(application, QGuiApplication) else ""
            build = sys.getwindowsversion().build if sys.platform == "win32" else 0
            native_supported = native_frame_supported(platform, build, qVersion())
        self._native = bool(native_supported)
        self._fallback_reason = "" if self._native else "Native rounded frame requires Windows 11 and Qt 6.9+"
        self._window = None
        self._hwnd = 0
        self._attaching = False
        self._layout_mode = "normal"
        self._visuals = None
        self._backdrop_available = True

    @Property(int, notify=flagsChanged)
    def initialWindowFlags(self):
        if self._native:
            return int(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint
                       | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        return int(Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
                   | Qt.WindowMinMaxButtonsHint)

    @Property(bool, notify=nativeFrameEnabledChanged)
    def nativeFrameEnabled(self):
        return self._native

    @Property(str, notify=fallbackReasonChanged)
    def fallbackReason(self):
        return self._fallback_reason

    @Property(bool, notify=backdropAvailableChanged)
    def backdropAvailable(self):
        return self._backdrop_available

    def attach(self, window: QWindow) -> bool:
        if self._attaching:
            return False
        self._attaching = True
        try:
            if window is not self._window:
                self.detach()
                self._window = window
                window.installEventFilter(self)
                window.visibilityChanged.connect(self._visibility_changed)
                window.destroyed.connect(self._window_destroyed)
                if self._native and isinstance(window, QWindow):
                    # Qt's Windows platform reads this before creating the HWND.
                    # Match its cached margins to our one-pixel non-client border.
                    inset = wh.native_resize_inset(round(window.devicePixelRatio() * 96))
                    margin = 1 - inset
                    window.setProperty("_q_windowsCustomMargins", QMargins(margin, margin, margin, margin))
            hwnd = int(window.winId())
            if self._hwnd == hwnd:
                return True
            self._unhook()
            install = wh.install_native_window_hit_test if self._native else wh.install_frameless_window_hit_test
            installed = install(hwnd)
            if self._native and (not installed or not wh.extend_native_frame(hwnd) or not wh.set_window_corner_preference(
                    hwnd, self._layout_mode == "normal")):
                wh.uninstall_window_hit_test(hwnd)
                self._native = False
                self._fallback_reason = "DWM rounded frame initialization failed; using legacy shell"
                logging.getLogger(__name__).warning(self._fallback_reason)
                window.setFlags(Qt.WindowType(self.initialWindowFlags))
                self.flagsChanged.emit()
                self.nativeFrameEnabledChanged.emit()
                self.fallbackReasonChanged.emit()
                hwnd = int(window.winId())
                installed = wh.install_frameless_window_hit_test(hwnd)
            self._hwnd = hwnd if installed else 0
            if installed:
                wh.set_window_interaction_callback(hwnd, self.interactiveMoveStarted.emit)
            if self._visuals is not None:
                self.applyVisuals(*self._visuals)
            return bool(installed)
        finally:
            self._attaching = False

    @Slot(bool, bool, int)
    def applyVisuals(self, is_dark: bool, glass_enabled: bool, glass_opacity: int) -> None:
        self._visuals = (is_dark, glass_enabled, max(45, min(90, glass_opacity)))
        if self._hwnd:
            wh.set_immersive_dark_mode(self._hwnd, is_dark)
            available = wh.apply_window_backdrop(self._hwnd, *self._visuals)
            if self._backdrop_available != available:
                self._backdrop_available = available
                self.backdropAvailableChanged.emit()

    @Slot(str)
    def setLayoutMode(self, mode: str) -> None:
        if mode not in {"normal", "left", "right", "maximized", "fullscreen"}:
            raise ValueError(f"Unknown window layout: {mode}")
        self._layout_mode = mode
        if self._native and self._hwnd:
            wh.set_window_corner_preference(self._hwnd, mode == "normal")

    def _visibility_changed(self, visibility):
        if visibility == QWindow.Maximized:
            self.setLayoutMode("maximized")
        elif visibility == QWindow.FullScreen:
            self.setLayoutMode("fullscreen")
        elif visibility == QWindow.Windowed and self._layout_mode in {"maximized", "fullscreen"}:
            self.setLayoutMode("normal")

    def _unhook(self):
        if self._hwnd:
            wh.uninstall_window_hit_test(self._hwnd)
            self._hwnd = 0

    def _window_destroyed(self):
        self._unhook()
        self._window = None

    def detach(self) -> None:
        self._unhook()
        if self._window is not None:
            try:
                self._window.removeEventFilter(self)
                self._window.visibilityChanged.disconnect(self._visibility_changed)
                self._window.destroyed.disconnect(self._window_destroyed)
            except RuntimeError:
                pass
            self._window = None

    def eventFilter(self, watched, event):
        if watched is self._window and event.type() == QEvent.PlatformSurface and not self._attaching:
            if event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed:
                self._unhook()
            else:
                QTimer.singleShot(0, self._reattach)
        return False

    def _reattach(self):
        if self._window is not None:
            self.attach(self._window)
