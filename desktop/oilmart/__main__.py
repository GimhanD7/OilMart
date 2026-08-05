import sys

from .db import initialize, make_engine
from .seed import seed


def main():
    try:
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QApplication, QDialog
        from .ui import LoginDialog
        from .dashboard import MainWindow
    except ImportError as exc:
        raise SystemExit("PyQt6 is required. Run: pip install -r desktop/requirements.txt") from exc
    factory = initialize(make_engine())
    with factory() as session:
        seed(session, include_demo_data=False)
    app = QApplication(sys.argv)
    app.setApplicationName("OilMart POS")
    # Inter is not guaranteed to exist on a customer's Windows machine.  Qt's
    # stylesheet font fallback is inconsistent across deployment plugins, so
    # use the native Windows UI face explicitly and let Qt substitute only if
    # it is genuinely unavailable.
    app.setFont(QFont("Segoe UI", 10))
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
