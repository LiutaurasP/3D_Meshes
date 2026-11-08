"""Small notifications that fade in at the bottom of the window and disappear by themselves."""

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from viewer.style import ACCENT, CARD, TEXT, TEXT_DIM

KIND_COLORS = {"info": ACCENT, "success": "#3fb27f", "warning": "#e0a43a"}


class Toast(QWidget):
    """A floating notification above the main window.

    It is its own small frameless window (not a child of the 3D view),
    because the OpenGL view would draw over normal child widgets.
    """

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.owner = parent

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        layout.addWidget(self.body)

        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)

    def show_message(self, text, detail="", kind="info", seconds=3.5):
        color = KIND_COLORS.get(kind, ACCENT)
        detail_html = f"<br><span style='color:{TEXT_DIM}'>{detail}</span>" if detail else ""
        self.body.setText(f"<span style='color:{TEXT}; font-weight:600'>{text}</span>{detail_html}")
        self.body.setStyleSheet(
            f"background:{CARD}; border:1px solid {color}; border-radius:8px; padding:10px 16px; font-size:13px;")
        self.adjustSize()
        self._place()
        self.fade.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.fade.setDuration(180)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(0.97)
        self.fade.start()
        self.timer.start(int(seconds * 1000))

    def _place(self):
        """Bottom centre of the 3D view, just above the status bar."""
        view = self.owner.centralWidget()
        corner = view.mapToGlobal(QPoint(0, 0))
        x = corner.x() + (view.width() - self.width()) // 2
        y = corner.y() + view.height() - self.height() - 24
        self.move(x, y)

    def _fade_out(self):
        self.fade.stop()
        self.fade.setDuration(400)
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(0.0)
        self.fade.finished.connect(self._hide_once)
        self.fade.start()

    def _hide_once(self):
        self.fade.finished.disconnect(self._hide_once)
        if self.windowOpacity() == 0.0:
            self.hide()
