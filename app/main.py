from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.bootstrap import AppBootstrap


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 未安装，当前只能完成 Phase A/Phase B 代码骨架。后续安装依赖后即可运行桌面窗口。")
        return 1

    from ui.main_window import MainWindow

    bootstrap = AppBootstrap(ROOT_DIR)
    container = bootstrap.build()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.bind_services(container)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
