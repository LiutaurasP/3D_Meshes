"""Error log: unexpected errors are written to a file instead of disappearing.

The log is in the app's data folder (Help → Show Log File). Each error is also shown
as a small notification, never as a window that has to be clicked away.
"""

import logging
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("sonar_studio")


def log_folder():
    from PySide6.QtCore import QStandardPaths

    return Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "Logs"


def log_path(folder=None):
    return Path(folder or log_folder()) / "sonar-studio.log"


def install(notify=None, folder=None):
    """Start logging to the file and catch unexpected errors. notify(text, detail) shows one."""
    from viewer.branding import APP_NAME, VERSION

    path = log_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.info("%s %s started on %s, Python %s", APP_NAME, VERSION, platform.platform(), platform.python_version())

    def report(kind, value, trace):
        text = "".join(traceback.format_exception(kind, value, trace))
        logger.error("Unexpected error\n%s", text)
        sys.__stderr__.write(text)
        if notify is not None:
            try:
                notify("Something went wrong", f"{kind.__name__}: {value} · details are in the log (Help menu)")
            except Exception:  # the notification itself must never cause another error
                pass

    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
    return path
