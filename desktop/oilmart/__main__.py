import sys

from .db import initialize, make_engine
from .seed import seed


def main():
    try:
        from PyQt6.QtWidgets import QApplication, QDialog
        from .ui import LoginDialog
        from .dashboard import MainWindow
    except ImportError as exc:
        raise SystemExit("PyQt6 is required. Run: pip install -r desktop/requirements.txt") from exc
    factory = initialize(make_engine())
    with factory() as session:
        seed(session)
    app = QApplication(sys.argv)
    app.setApplicationName("OilMart POS")
    login = LoginDialog(factory)
    if login.exec() != QDialog.DialogCode.Accepted or login.user is None:
        return
    window = MainWindow(factory, login.user)
    window.show()
    if not window.ensure_shift():
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        # Ctrl+C is an intentional shutdown, not an application failure.
        raise SystemExit(0)
