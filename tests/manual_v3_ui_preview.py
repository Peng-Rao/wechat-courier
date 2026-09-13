from __future__ import annotations

import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.backend import BackendController
from app.friend_import import load_friend_records


def render(output: Path, workspace: int = 0) -> int:
    application = QGuiApplication.instance() or QGuiApplication(sys.argv)
    settings = QSettings(str(output.with_suffix(".ini")), QSettings.IniFormat)
    backend = BackendController(version="0.3.0", settings=settings)
    backend.agent._connected = True
    backend.agent.applyInspection(
        {
            "connected": True,
            "version": "4.1.13.65",
            "supported": True,
            "detail": "微信版本已验证",
        }
    )
    backend.message.recipientsText = "25届初二-郑子轩妈妈\n张永琪爸爸\n王小明"
    backend.message.templateText = (
        "{name}，您好！\n\n本周六上午 9:30 将举行家长交流会，请您提前十分钟到场。"
    )
    backend.friends.model.replace_records(
        load_friend_records(
            [
                ["账号", "打招呼语", "备注"],
                ["18896904196", "你好，方便认识一下吗？", "王老师"],
                ["wxid_demo_02", "", "李先生"],
                ["19170745267", "你好，看到资料想认识一下", ""],
                ["18896904196", "重复示例", ""],
                ["wxid_contact_05", "", "陈女士"],
            ]
        )
    )

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    qml_path = REPO_ROOT / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 2
    window = engine.rootObjects()[0]
    app_root = window.findChild(QObject, "appRoot")
    if app_root is not None:
        app_root.setProperty("workspaceIndex", workspace)

    def capture():
        try:
            screen = window.screen() or application.primaryScreen()
            image = screen.grabWindow(int(window.winId()))
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(output))
        finally:
            application.quit()

    QTimer.singleShot(1_400, capture)
    result = application.exec()
    backend.shutdown()
    return result


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "v3-preview.png").resolve()
    selected_workspace = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    raise SystemExit(render(target, selected_workspace))
