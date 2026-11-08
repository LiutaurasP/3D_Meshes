"""Name, version and icon of the application, and making the OS use them."""

import sys
from pathlib import Path

APP_NAME = "Subdron Sonar Studio"
ORGANIZATION = "Subdron"
VERSION = "0.1.0"
PROJECT_EXTENSION = ".subdron"
PROJECT_FILTER = f"{APP_NAME} projects (*{PROJECT_EXTENSION})"

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS / "app_icon.png"
LOGO_PATH = ASSETS / "subdron_wordmark.png"  # white letters on transparent


def set_process_name():
    """Show the app's name instead of "Python" in the macOS menu bar / Windows taskbar.

    Has to run before the QApplication is created.
    """
    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle  # pyobjc, installed on macOS only

            bundle = NSBundle.mainBundle()
            for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
                if info is not None:
                    info["CFBundleName"] = APP_NAME
        except ImportError:
            pass  # without pyobjc the menu bar just says Python
    elif sys.platform == "win32":
        try:
            import ctypes

            # Own taskbar entry and icon instead of the generic Python one
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORGANIZATION}.SonarStudio")
        except (AttributeError, OSError):
            pass


def apply_identity(app):
    """Name, organisation and icon on the QApplication (used for settings, dialogs, Dock)."""
    from PySide6.QtGui import QIcon

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)
    app.setOrganizationDomain("subdron.com")
    app.setApplicationVersion(VERSION)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
