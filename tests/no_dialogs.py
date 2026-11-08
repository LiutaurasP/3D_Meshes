"""Make sure an automated test can never get stuck on a window that waits for a click.

Native file pickers (Save / Open) and message boxes block until someone answers. In a
test nobody does, so the run would hang. block_dialogs() replaces all of them: they
return "cancelled" straight away and print what would have been asked.
"""

from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

blocked = []  # what would have been shown, for checks


def _note(kind, args):
    title = next((a for a in args if isinstance(a, str)), "")
    blocked.append((kind, title))
    print(f"[test] blocked {kind}: {title}", flush=True)


def block_dialogs():
    def file_dialog(kind, empty):
        return staticmethod(lambda *args, **kwargs: (_note(kind, args), empty)[1])

    QFileDialog.getSaveFileName = file_dialog("save file dialog", ("", ""))
    QFileDialog.getOpenFileName = file_dialog("open file dialog", ("", ""))
    QFileDialog.getOpenFileNames = file_dialog("open files dialog", ([], ""))
    QFileDialog.getExistingDirectory = file_dialog("folder dialog", "")

    def message(kind, answer):
        return staticmethod(lambda *args, **kwargs: (_note(kind, args), answer)[1])

    QMessageBox.question = message("question", QMessageBox.Discard)  # "don't save", never "Save"
    QMessageBox.warning = message("warning", QMessageBox.Ok)
    QMessageBox.information = message("information", QMessageBox.Ok)
    QMessageBox.critical = message("error", QMessageBox.Ok)
    QInputDialog.getText = staticmethod(lambda *args, **kwargs: (_note("text input", args), ("", False))[1])
    QInputDialog.getMultiLineText = staticmethod(
        lambda *args, **kwargs: (_note("text input", args), ("", False))[1])

    def no_exec(self, *args, **kwargs):
        _note("dialog", [self.windowTitle()])
        return QDialog.Rejected

    QDialog.exec = no_exec
