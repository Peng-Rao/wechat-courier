"""Native window frame and backdrop lifecycle, independent of automation."""

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QEvent, QMargins, QObject, Property, Qt, QTimer, Signal, Slot, qVersion
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent, QWindow
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

from app import win32_helper as wh


def configure_window_diagnostics(log_dir=None):
    """Keep bounded GUI renderer diagnostics separate from business events."""
    from app.agent.diagnostics import default_log_dir

    logger = logging.getLogger(__name__)
    try:
        directory = Path(log_dir) if log_dir is not None else default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "window-rendering.log"
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(path.resolve()):
                return handler
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8", delay=True)
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return handler
    except OSError:
        logger.warning("Cannot create window renderer diagnostics")
        return None


def native_frame_supported(platform_name: str, windows_build: int, qt_version: str) -> bool:
    try:
        version = tuple(int(part) for part in qt_version.split(".")[:2])
    except (ValueError, TypeError, AttributeError):
        return False
    return platform_name == "windows" and windows_build >= 22000 and version >= (6, 9)


def configure_native_renderer(*, native_supported: bool | None = None) -> None:
    """Select an alpha-capable backend before the first Quick window is created."""
    application = QGuiApplication.instance()
    platform = (application.platformName() if isinstance(application, QGuiApplication)
                else os.environ.get("QT_QPA_PLATFORM", "windows").split(":", 1)[0])
    if native_supported is None:
        build = sys.getwindowsversion().build if sys.platform == "win32" else 0
        native_supported = native_frame_supported(platform, build, qVersion())
    explicit_backend = any(os.environ.get(name) for name in (
        "QSG_RHI_BACKEND", "QT_QUICK_BACKEND", "QMLSCENE_DEVICE"))
    if native_supported and platform == "windows" and not explicit_backend:
        # Legacy D3D11 loses client colors after restore. Qt's dynamic OpenGL
        # loader can fall back to the bundled software implementation.
        QQuickWindow.setGraphicsApi(QSGRendererInterface.OpenGL)


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
        self._frame_available = True
        self._corner_available = True
        self._restore_pending = False
        self._surface_geometry = None
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_surface)

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

    def attach(self, window: QWindow, *, apply_visuals=True) -> bool:
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
                if isinstance(window, QQuickWindow):
                    window.sceneGraphInitialized.connect(self._scene_graph_ready, Qt.QueuedConnection)
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
            if self._native:
                self._frame_available = bool(installed and wh.extend_native_frame(hwnd))
                self._corner_available = bool(installed and wh.set_window_corner_preference(hwnd, self._layout_mode == "normal"))
            if self._native and not (installed and self._frame_available and self._corner_available):
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
            if apply_visuals and self._visuals is not None:
                self.applyVisuals(*self._visuals)
            return bool(installed)
        finally:
            self._attaching = False

    @Slot(bool, bool, int)
    def applyVisuals(self, is_dark: bool, glass_enabled: bool, glass_opacity: int) -> None:
        self._visuals = (is_dark, glass_enabled, max(45, min(90, glass_opacity)))
        if self._hwnd:
            wh.set_immersive_dark_mode(self._hwnd, is_dark)
            available = bool(wh.apply_window_backdrop(self._hwnd, *self._visuals)
                             and self._frame_available and self._corner_available)
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
        if visibility in (QWindow.Hidden, QWindow.Minimized):
            self._restore_pending = True
            self._restore_timer.stop()
            return
        if visibility == QWindow.Maximized:
            self.setLayoutMode("maximized")
        elif visibility == QWindow.FullScreen:
            self.setLayoutMode("fullscreen")
        elif visibility == QWindow.Windowed and self._layout_mode in {"maximized", "fullscreen"}:
            self.setLayoutMode("normal")
        self._schedule_restore()

    def _schedule_restore(self):
        if self._restore_pending and self._window is not None and not self._restore_timer.isActive():
            self._restore_timer.start(0)

    @Slot()
    def _scene_graph_ready(self):
        if self._window is not None and self.sender() is self._window:
            self._restore_pending = True
            self._schedule_restore()

    @Slot()
    def _restore_surface(self):
        window = self._window
        if (not self._restore_pending or window is None or not window.isExposed()
                or window.visibility() in (QWindow.Hidden, QWindow.Minimized)):
            return
        self._restore_pending = False
        old_hwnd = self._hwnd
        bound = self.attach(window)
        geometry = self._surface_geometry
        self._surface_geometry = None
        if (bound and geometry is not None and self._layout_mode not in {"maximized", "fullscreen"}
                and window.geometry() != geometry):
            # Qt recalculates frame margins for a replacement HWND. Preserve the
            # client geometry once; ordinary minimize/hide recovery never resizes.
            window.setGeometry(geometry)
        if bound and old_hwnd == self._hwnd:
            if self._native:
                self._frame_available = wh.extend_native_frame(self._hwnd)
                self._corner_available = wh.set_window_corner_preference(self._hwnd, self._layout_mode == "normal")
            if self._visuals is not None:
                self.applyVisuals(*self._visuals)
        if not (bound and self._frame_available and self._corner_available):
            if self._backdrop_available:
                self._backdrop_available = False
                self.backdropAvailableChanged.emit()
        api = window.rendererInterface().graphicsApi().name if isinstance(window, QQuickWindow) else "unknown"
        logging.getLogger(__name__).info(
            "Window surface restored: qt=%s renderer=%s visibility=%s hwnd=%s "
            "bound=%s frame=%s corner=%s backdrop=%s",
            qVersion(), api, window.visibility().name, self._hwnd,
            bound, self._frame_available, self._corner_available, self._backdrop_available)
        window.update()

    def _unhook(self):
        if self._hwnd:
            wh.uninstall_window_hit_test(self._hwnd)
            self._hwnd = 0

    def _window_destroyed(self):
        self._restore_timer.stop()
        self._restore_pending = False
        self._surface_geometry = None
        self._unhook()
        self._window = None

    def detach(self) -> None:
        self._restore_timer.stop()
        self._restore_pending = False
        self._surface_geometry = None
        self._unhook()
        if self._window is not None:
            try:
                self._window.removeEventFilter(self)
                self._window.visibilityChanged.disconnect(self._visibility_changed)
                self._window.destroyed.disconnect(self._window_destroyed)
                if isinstance(self._window, QQuickWindow):
                    self._window.sceneGraphInitialized.disconnect(self._scene_graph_ready)
            except RuntimeError:
                pass
            self._window = None

    def eventFilter(self, watched, event):
        if watched is self._window and not self._attaching:
            if event.type() == QEvent.PlatformSurface:
                if event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed:
                    self._restore_timer.stop()
                    if self._surface_geometry is None and self._layout_mode not in {"maximized", "fullscreen"}:
                        self._surface_geometry = watched.geometry()
                    self._unhook()
                self._restore_pending = True
                if event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceCreated:
                    # Install the frame before Qt caches the new HWND's margins;
                    # defer backdrop repair and rendering until exposed.
                    self.attach(watched, apply_visuals=False)
                    self._schedule_restore()
            elif event.type() == QEvent.Expose:
                if not watched.isExposed():
                    self._restore_pending = True
                    self._restore_timer.stop()
                else:
                    self._schedule_restore()
        return False
