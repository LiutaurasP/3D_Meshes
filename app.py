"""Start Subdron Sonar Studio (Qt + PyVista window, Open3D for the data).

The original Plotly viewer is unchanged: run main.py for it, or use the
"Open in Plotly" button inside this app.
"""

import sys
from datetime import datetime

from viewer.branding import APP_NAME, LOGO_PATH, PROJECT_EXTENSION, VERSION, apply_identity, set_process_name

set_process_name()  # before Qt starts, so the menu bar shows the app's name

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen  # noqa: E402

from viewer import prefs  # noqa: E402
from viewer.settings import Settings  # noqa: E402
from viewer.style import apply_theme  # noqa: E402


def splash_pixmap():
    """Navy card with the subdron logo, the product name and the version."""
    ratio = QApplication.primaryScreen().devicePixelRatio()
    width, height = 520, 300
    pixmap = QPixmap(int(width * ratio), int(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor("#0d162c"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    logo = QPixmap(str(LOGO_PATH))
    logo_width = 300
    logo_height = logo.height() * logo_width / logo.width()
    painter.drawPixmap(int((width - logo_width) / 2), 70, int(logo_width), int(logo_height), logo)
    painter.setPen(QColor("#e6e7eb"))
    font = QFont()
    font.setPixelSize(20)
    font.setWeight(QFont.DemiBold)
    painter.setFont(font)
    painter.drawText(0, 170, width, 30, Qt.AlignHCenter, "Sonar Studio")
    font.setPixelSize(12)
    font.setWeight(QFont.Normal)
    painter.setFont(font)
    painter.setPen(QColor("#9a9da7"))
    painter.drawText(0, height - 40, width, 20, Qt.AlignHCenter, f"Version {VERSION}")
    painter.end()
    return pixmap


def offer_recovery(window):
    """After a crash: offer the work that was autosaved but never saved."""
    from viewer.window import recovery_path

    path = recovery_path()
    if not path.exists():
        return False
    when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %Y, %H:%M")
    answer = QMessageBox.question(
        window, APP_NAME,
        f"{APP_NAME} didn't close normally last time.\n\nDo you want to restore the unsaved work from {when}?",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    if answer != QMessageBox.Yes:
        path.unlink()
        return False
    window.open_project(str(path), ask=False)
    window.project_path = None  # it's a recovered copy: Save asks where to put it
    window.history.stack.resetClean()  # still counts as unsaved
    window._update_title()
    window.notify("Unsaved work restored", f"from {when}", "success")
    return True


def show_start_screen(window):
    from viewer.dialogs import StartScreen

    screen = StartScreen(window._recent(), window)
    if not screen.exec():
        return
    kind, value = screen.choice
    if kind == StartScreen.OPEN:
        window.open_project_dialog()
    elif kind == StartScreen.RECENT:
        window.open_project(value, ask=False)
    elif kind == StartScreen.EXAMPLE:
        window.pick_scene(value)
        window.history.clear()


def main():
    app = QApplication(sys.argv)
    apply_identity(app)
    apply_theme(app)

    splash = QSplashScreen(splash_pixmap())
    splash.show()
    app.processEvents()

    from viewer.window import MainWindow

    window = MainWindow(Settings())
    window.show()
    splash.finish(window)

    # A project file given on the command line (or double clicked later) is opened directly
    projects = [arg for arg in sys.argv[1:] if arg.endswith(PROJECT_EXTENSION)]
    if projects:
        window.open_project(projects[0], ask=False)
    elif not offer_recovery(window) and prefs.get("show_start_screen"):
        show_start_screen(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
