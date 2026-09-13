# -*- coding: utf-8 -*-
"""WxAuto — PySide6 + QML 群发助手 入口"""
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance

from app.backend import BackendController
from app.demo import is_demo_mode
from app import win32_helper

try:
    from app._version import __version__
except Exception:
    __version__ = "0.0.0"


def get_qml_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "qml")
    return os.path.join(os.path.dirname(__file__), "qml")


def get_assets_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "assets")
    return os.path.join(os.path.dirname(__file__), "assets")


def main():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"

    app = QGuiApplication(sys.argv)
    app.setApplicationName("五阿哥微信助手")
    app.setApplicationVersion(__version__)

    icon_path = os.path.join(get_assets_dir(), "app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 创建后端
    backend = BackendController(__version__, auto_start_agent=True)
    app.aboutToQuit.connect(backend.shutdown)

    # QML 引擎
    engine = QQmlApplicationEngine()

    # 注入 backend 为上下文属性
    engine.rootContext().setContextProperty("backend", backend)

    qml_main = os.path.join(get_qml_dir(), "main.qml")
    engine.load(QUrl.fromLocalFile(qml_main))

    root_objects = engine.rootObjects()
    if not root_objects:
        sys.exit(-1)

    if sys.platform == "win32":
        win32_helper.install_frameless_window_hit_test(int(root_objects[0].winId()))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
