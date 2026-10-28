"""نقطه‌ی ورود Telegram Date Studio."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow
    from src.ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    apply_theme(app)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
