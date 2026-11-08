"""Unexpected errors end up in the log file and as a notification."""

import sys

from viewer import crashlog


def test_errors_are_logged_and_shown(tmp_path):
    shown = []
    hook_before = sys.excepthook
    try:
        path = crashlog.install(lambda text, detail: shown.append(detail), folder=tmp_path)
        try:
            raise ValueError("broken scan")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        text = path.read_text()
        assert "started on" in text and "ValueError: broken scan" in text and "Traceback" in text
        assert shown and "broken scan" in shown[0]
    finally:
        sys.excepthook = hook_before
