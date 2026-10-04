"""Launch the real GUI/Agent with isolated acceptance settings, never mocks."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    if os.environ.get("WECHAT_COURIER_ACCEPTANCE") != "1" or len(sys.argv) != 2:
        raise SystemExit("Use the opt-in GUI acceptance harness")
    from main import main

    main(settings=QSettings(str(Path(sys.argv[1]).resolve()), QSettings.IniFormat))
