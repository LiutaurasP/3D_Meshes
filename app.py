"""Start Subdron Sonar Studio (Qt + PyVista window, Open3D for the data).

The original Plotly viewer is unchanged: run main.py for it, or use the
"Open in Plotly" button inside this app.
"""

import sys
from datetime import datetime

from viewer.branding import APP_NAME, LOGO_PATH, PROJECT_EXTENSION, VERSION, apply_identity, set_process_name

set_process_name()  # before Qt starts, so the menu bar shows the app's name

from PySide6.QtCore import QEvent, QObject, Qt, QTimer  # noqa: E402
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
    elif kind == StartScreen.TUTORIAL:
        QTimer.singleShot(150, window.start_tutorial)  # once the window is on screen


class FileOpener(QObject):
    """macOS sends a double-clicked .subdron file as an event, not on the command line."""

    def __init__(self):
        super().__init__()
        self.window = None
        self.pending = []  # files that arrive before the window exists

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FileOpen and event.file().endswith(PROJECT_EXTENSION):
            if self.window is None:
                self.pending.append(event.file())
            else:
                self.window.open_project(event.file())
            return True
        return False


def self_test(window):
    """--self-test: build the example scene, align, detect, print the result and quit.

    Used to check that a packaged app really works (python packaging/build.py runs it).
    """
    from PySide6.QtCore import QTimer

    def wait(condition, then, waited=0):
        if condition():
            then()
        elif waited > 120_000:
            print("SELF-TEST FAILED: timed out", flush=True)
            QApplication.exit(1)
        else:
            QTimer.singleShot(200, lambda: wait(condition, then, waited + 200))

    def detect():
        window.detect_changes()
        wait(lambda: window.change_result is not None, done)

    def tools():
        """Everything that needs extra parts of VTK, Qt or the file libraries in the packaged app."""
        import tempfile
        from pathlib import Path

        folder = Path(tempfile.mkdtemp())
        window.scene.set_minimap(True)
        window.play_change_animation()
        window.export_report(str(folder / "report.pdf"))
        window.export_turntable(str(folder / "spin.gif"), count=4)
        window.export_areas("csv", str(folder / "areas.csv"))
        window.export_aligned_scan(str(folder / "b.laz"))
        window.write_project(folder / "test.subdron")
        from scan_formats import read_scan

        read_scan(folder / "b.laz")
        window.start_display_mode(fullscreen=False)
        QTimer.singleShot(1500, lambda: finish(folder))

    def finish(folder):
        window.display_mode.stop()
        names = sorted(p.name for p in folder.iterdir())
        areas = len(window.change_result.areas)
        complete = names == ["areas.csv", "b.laz", "report.pdf", "spin.gif", "test.subdron"]
        print(f"SELF-TEST {'OK' if areas and complete else 'FAILED'}: aligned, {areas} changed area(s), "
              f"files {names}", flush=True)
        window.skip_save_prompt = True
        QApplication.exit(0 if areas and complete else 1)

    def done():
        try:
            tools()
        except Exception as error:  # shown in the build output
            print(f"SELF-TEST FAILED: {type(error).__name__}: {error}", flush=True)
            QApplication.exit(1)

    def start():
        window.sidebar.animate.setChecked(False)
        window.align()
        wait(window.is_aligned, detect)

    worker = window._data_worker  # the first scene is built right away, later ones in the background
    wait(lambda: worker is None or worker.isFinished(), start)


def main():
    app = QApplication(sys.argv)
    opener = FileOpener()
    app.installEventFilter(opener)
    apply_identity(app)
    if "--self-test" in sys.argv:
        app.setOrganizationName("SubdronSelfTest")  # own settings: never touches recent files or preferences
    apply_theme(app)

    splash = QSplashScreen(splash_pixmap())
    splash.show()
    app.processEvents()

    from viewer.window import MainWindow

    window = MainWindow(Settings())
    from viewer import crashlog

    crashlog.install(lambda text, detail: window.notify(text, detail, "error", seconds=8))
    window.show()
    splash.finish(window)
    app.processEvents()  # a file double clicked in the Finder arrives now
    opener.window = window

    # A project file given on the command line (or double clicked) is opened directly
    projects = opener.pending + [arg for arg in sys.argv[1:] if arg.endswith(PROJECT_EXTENSION)]
    if "--self-test" in sys.argv:
        self_test(window)
    elif projects:
        window.open_project(projects[0], ask=False)
    elif not offer_recovery(window) and prefs.get("show_start_screen"):
        show_start_screen(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
