"""Undo / redo for the whole app.

Everything goes through one QUndoStack:

- History.watch(widget, label): any change of a panel control (checkbox,
  dropdown, number field, slider) becomes an undo step automatically.
  Quick repeated changes of the same control are merged into one step
  (dragging a slider is one step, not fifty).
- Step: a generic step with two functions (apply the new state, apply the
  old state), used for colour picks, scene changes, alignment and change
  detection.

Commands are pushed *after* the change already happened, so the first
redo() that Qt calls when pushing does nothing.
"""

import time

from PySide6.QtGui import QUndoCommand, QUndoStack
from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QCheckBox, QComboBox

MERGE_SECONDS = 1.5
_ids = {}


def merge_id(key):
    """Small stable integer per merge key (Qt wants an int id for merging)."""
    return _ids.setdefault(key, len(_ids) + 1)


def value_of(widget):
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentIndex()
    return widget.value()


def set_value(widget, value):
    if isinstance(widget, QCheckBox):
        widget.setChecked(value)
    elif isinstance(widget, QComboBox):
        widget.setCurrentIndex(value)
    else:
        widget.setValue(value)


def change_signal(widget):
    if isinstance(widget, QCheckBox):
        return widget.toggled
    if isinstance(widget, QComboBox):
        return widget.currentIndexChanged
    if isinstance(widget, (QAbstractSpinBox, QAbstractSlider)):
        return widget.valueChanged
    raise TypeError(f"Can't watch {type(widget).__name__}")


class Step(QUndoCommand):
    """A step with a function to apply the new and one to apply the old state."""

    def __init__(self, history, text, do, undo, merge_key=None):
        super().__init__(text)
        self.history = history
        self.do = do
        self.undo_ = undo
        self.merge_key = merge_key
        self.created = time.monotonic()
        self._first = True

    def redo(self):
        if self._first:  # already happened when the step was pushed
            self._first = False
            return
        self.history.run(self.do)

    def undo(self):
        self.history.run(self.undo_)

    def id(self):
        return merge_id(self.merge_key) if self.merge_key else -1

    def mergeWith(self, other):
        if other.merge_key != self.merge_key or other.created - self.created > MERGE_SECONDS:
            return False
        self.do = other.do  # keep our "old" state, take the newer "new" state
        self.created = other.created
        return True


class History:
    """The app's undo history."""

    def __init__(self, parent=None):
        self.stack = QUndoStack(parent)
        self.stack.setUndoLimit(200)
        self.applying = False  # True while undo / redo changes things (nothing is recorded then)
        self._last = {}

    def run(self, function):
        self.applying = True
        try:
            function()
        finally:
            self.applying = False

    def push(self, text, do, undo, merge_key=None):
        if not self.applying:
            self.stack.push(Step(self, text, do, undo, merge_key))

    def watch(self, widget, label):
        """Record every change of this control as an undo step."""
        self._last[widget] = value_of(widget)

        def changed(*_):
            new = value_of(widget)
            old = self._last.get(widget, new)
            self._last[widget] = new
            if self.applying or old == new:
                return
            self.push(
                f"Change {label}",
                lambda: set_value(widget, new),
                lambda: set_value(widget, old),
                merge_key=("widget", id(widget)),
            )

        change_signal(widget).connect(changed)

    def resync(self):
        """Remember the current values of all watched controls (after they were set by code)."""
        for widget in self._last:
            self._last[widget] = value_of(widget)

    def clear(self):
        self.stack.clear()
        self.stack.setClean()
        self.resync()
