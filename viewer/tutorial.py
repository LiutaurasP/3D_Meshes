"""Tutorial: the app explained step by step on a scan of a container on the seafloor.

Everything starts switched off: a black screen, no side panel, no menus. Each step
unlocks one thing (a key, the mouse, the panel) and moves on when it has been used.
At the end the normal default scene opens with everything unlocked.

The text is shown in a card that floats over the 3D view. Like the notifications it is
its own small window, because the OpenGL view would draw over normal child widgets.
"""

import math
import sys
import time

import numpy as np
import pyvista as pv
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from viewer.style import ACCENT, TEXT, TEXT_DIM, TEXT_FAINT

SUCCESS = "#3fb27f"
WARNING = "#e0a43a"
MAC = sys.platform == "darwin"
COMMAND = "⌘" if MAC else "Ctrl"
TUTORIAL_SCENE = "tutorial_seafloor"
ENTER_KEYS = (Qt.Key_Return, Qt.Key_Enter)
FLY_KEYS = {Qt.Key_W: "W", Qt.Key_A: "A", Qt.Key_S: "S", Qt.Key_D: "D", Qt.Key_Q: "Q", Qt.Key_E: "E"}
CONNECTORS = ("+", "then", "or")  # small words between key caps
MOUSE_EVENTS = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.MouseMove)


# The card


def tutorial_font(pixels, weight=QFont.Normal, spacing=0.0):
    """Fonts are set directly (not through style sheets), so text is measured exactly as it is drawn."""
    font = QFont(QApplication.font())
    font.setPixelSize(pixels)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


def text_height(html, font, width):
    """Height of rich text at a width, measured the way QLabel lays it out (no document margin)."""
    document = QTextDocument()
    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    document.setHtml(html)
    document.setTextWidth(width)
    return int(np.ceil(document.size().height()))


def coloured(widget, colour):
    palette = widget.palette()
    palette.setColor(QPalette.WindowText, QColor(colour))
    palette.setColor(QPalette.Text, QColor(colour))
    widget.setPalette(palette)


class KeyChip(QWidget):
    """A key cap (or a mouse action) that lights up when it has been used. It draws itself and has a fixed
    shape: as wide as its text needs (at least square), always the same height."""

    HEIGHT = 44
    FONT_PX = 20
    SIDE_PADDING = 14

    def __init__(self, text, wide=False):
        super().__init__()
        self.label = text
        self.key_font = tutorial_font(self.FONT_PX, QFont.Bold)
        width = QFontMetrics(self.key_font).horizontalAdvance(text) + 2 * self.SIDE_PADDING + 2
        self.setFixedSize(max(width, self.HEIGHT), self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.state = "idle"
        self._glow = 0.0
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setKeyValueAt(0.5, 1.0)
        self.pulse.setEndValue(0.0)
        self.pulse.setDuration(1600)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(self._set_glow)

    def text(self):
        return self.label

    def start_pulse(self):
        self.pulse.start()

    def _set_glow(self, value):
        self._glow = value
        self.update()  # only a repaint: nothing about the layout changes

    def set_state(self, state):
        """idle, pressed (being held / used) or done."""
        self.state = state
        if state == "done":
            self.pulse.stop()
            self._glow = 0.0
        self.update()

    def paintEvent(self, event):
        if self.state == "done":
            fill, border, text = QColor(63, 178, 127, 56), QColor(SUCCESS), QColor("#bdf0d6")
        elif self.state == "pressed":
            fill, border, text = QColor(61, 127, 245, 115), QColor(ACCENT), QColor("#ffffff")
        else:
            fill = QColor(61, 127, 245, int(255 * (0.08 + 0.14 * self._glow)))
            border = QColor(ACCENT)
            border.setAlphaF(0.45 + 0.55 * self._glow)
            text = QColor(TEXT)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(border)  # the thicker lower edge of a key cap
        painter.drawRoundedRect(outer, 8, 8)
        face = outer.adjusted(1, 1, -1, -4)
        painter.setBrush(QColor(14, 19, 33))
        painter.drawRoundedRect(face, 7, 7)
        painter.setBrush(fill)
        painter.drawRoundedRect(face, 7, 7)
        painter.setPen(text)
        painter.setFont(self.key_font)
        painter.drawText(face, Qt.AlignCenter, self.label)


class TutorialCard(QWidget):
    """The floating text card: small step label, big heading, text, keys and a progress bar.

    Every part gets a fixed size measured from its own text and font, and the card's height is the sum of
    those parts and fixed gaps. Nothing is left for Qt to estimate, so the card looks the same every time.
    """

    WIDTH = 1000  # at most; narrower when the 3D view is
    MARGINS = (40, 24, 28, 24)  # left, top, right, bottom
    GAP_TITLE = 6  # blue line → title
    GAP_TEXT = 8  # title → text
    GAP_ROW = 18  # text → keys and button
    GAP_HINT = 10  # keys → hint
    ROW_HEIGHT = KeyChip.HEIGHT

    def __init__(self, owner, on_continue, on_leave):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.owner = owner
        self.position = "bottom"
        self.progress = 0.0  # whole tutorial, drawn along the bottom edge
        self.task = None  # progress of the current task (turning, moving): the card fills up with it
        self._fill = 0.0  # how far the fill is drawn, eases towards the task's progress
        self._shine = -1.0  # the sweep of light across the card when a task is done (-1: none)
        self._shine_clock = None
        self.fill_timer = QTimer(self)
        self.fill_timer.setInterval(16)
        self.fill_timer.timeout.connect(self._animate_fill)
        self.border = QColor(ACCENT)
        self._full_heading = ""
        self._typed = 0
        self._step = {}

        self.fonts = {
            "eyebrow": tutorial_font(11, QFont.Bold, 2.0),
            "heading": tutorial_font(30, QFont.Bold),
            "body": tutorial_font(16),
            "row": tutorial_font(17, QFont.DemiBold),
            "hint": tutorial_font(14),
            "leave": tutorial_font(12),
            "button": tutorial_font(15, QFont.DemiBold),
        }

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetNoConstraint)  # the card sets its own size, see relayout()
        left, top, right, bottom = self.MARGINS
        layout.setContentsMargins(left, top, right, bottom)
        layout.setSpacing(0)

        # The blue line, with a quiet "Leave tutorial  Esc" in the top-right corner
        header = QHBoxLayout()
        header.setSpacing(12)
        self.eyebrow = QLabel()
        self.eyebrow.setFont(self.fonts["eyebrow"])
        coloured(self.eyebrow, ACCENT)
        header.addWidget(self.eyebrow, 1, Qt.AlignVCenter)
        self.leave = QPushButton()
        self.leave.setFont(self.fonts["leave"])
        self.leave.setCursor(Qt.PointingHandCursor)
        self.leave.setStyleSheet(
            f"QPushButton {{ background: none; color: {TEXT_DIM}; border: 1px solid rgba(255, 255, 255, 0.13);"
            f" border-radius: 7px; padding: 0px 10px; }}"
            f"QPushButton:hover {{ color: {TEXT}; border-color: rgba(255, 255, 255, 0.32); }}")
        self.leave.clicked.connect(on_leave)
        header.addWidget(self.leave, 0, Qt.AlignVCenter)
        self.header = header
        layout.addLayout(header)
        layout.addSpacing(self.GAP_TITLE)

        self.heading = QLabel()
        self.heading.setTextFormat(Qt.RichText)
        self.heading.setWordWrap(True)
        self.heading.setFont(self.fonts["heading"])
        coloured(self.heading, TEXT)
        layout.addWidget(self.heading)
        layout.addSpacing(self.GAP_TEXT)

        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        self.body.setWordWrap(True)
        self.body.setFont(self.fonts["body"])
        coloured(self.body, TEXT_DIM)
        layout.addWidget(self.body)

        # Keys on the left, the button on the right, in one row of fixed height
        self.row_space = QSpacerItem(0, self.GAP_ROW, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addItem(self.row_space)
        self.row = QWidget()
        self.keys_row = QHBoxLayout(self.row)
        self.keys_row.setContentsMargins(0, 0, 0, 0)
        self.keys_row.setSpacing(6)
        layout.addWidget(self.row)

        self.hint_space = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addItem(self.hint_space)
        self.hint = QLabel()
        self.hint.setTextFormat(Qt.RichText)
        self.hint.setWordWrap(True)
        self.hint.setFont(self.fonts["hint"])
        coloured(self.hint, WARNING)
        self.hint.hide()
        layout.addWidget(self.hint)
        layout.addStretch()

        self.next = QPushButton("Continue")
        self.next.setFont(self.fonts["button"])
        self.next.setCursor(Qt.PointingHandCursor)
        self.next.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white; border: none; border-radius: 9px; padding: 0px; }}"
            f"QPushButton:hover {{ background: #5590f7; }}")
        self.next.clicked.connect(on_continue)

        self.chips = {}
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.slide = QPropertyAnimation(self, b"pos", self)
        self.typer = QTimer(self)
        self.typer.timeout.connect(self._type_more)
        self.flash = QVariantAnimation(self)
        self.flash.setDuration(900)
        self.flash.setStartValue(0.0)
        self.flash.setKeyValueAt(0.25, 1.0)
        self.flash.setEndValue(0.0)
        self.flash.valueChanged.connect(self._flash_frame)
        self._flash_color = QColor(SUCCESS)
        self._flash = 0.0
        self.setFixedWidth(self.WIDTH)

    # Content

    def set_content(self, step, animate=True):
        """step: dict with eyebrow, heading, body, keys [(label, id)], button, position, big."""
        self._step = step
        self.position = step.get("position", "bottom")
        self.eyebrow.setText(step.get("eyebrow", "").upper())
        text = step.get("body", "")
        if not text.lstrip().startswith("<p"):
            text = body(text)  # a single paragraph: the same spacing as all the others
        self.body.setText(f"<div style='line-height: 125%;'>{text}</div>")
        self.hint.setText("")
        self.hint.hide()
        self.task = None
        self._fill = 0.0
        self._shine = -1.0

        while self.keys_row.count():
            item = self.keys_row.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.next:
                widget.hide()
                widget.deleteLater()
        self.chips = {}
        for label, name in step.get("keys", []):
            if name is None:  # text between or after the keys
                words = QLabel(label)
                words.setFont(self.fonts["row"])
                quiet = label in CONNECTORS  # "+", "then": quiet, the keys are what matters
                coloured(words, TEXT_DIM if quiet else TEXT)
                indent = 0 if quiet else 8
                words.setContentsMargins(indent, 0, 0, 0)
                words.setFixedSize(QFontMetrics(self.fonts["row"]).horizontalAdvance(label) + indent + 4,
                                   self.ROW_HEIGHT)
                words.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.keys_row.addWidget(words, 0, Qt.AlignVCenter)
                continue
            chip = KeyChip(label)
            chip.start_pulse()
            self.chips[name] = chip
            self.keys_row.addWidget(chip, 0, Qt.AlignVCenter)
        self.keys_row.addStretch()
        self.keys_row.addWidget(self.next, 0, Qt.AlignVCenter)

        button = step.get("button")
        self._set_button(button)
        self.leave.setVisible(step.get("leave", True))
        self.leave.setText(step.get("leave_text", "Leave tutorial    Esc"))
        metrics = QFontMetrics(self.fonts["leave"])
        self.leave.setFixedSize(metrics.horizontalAdvance(self.leave.text()) + 22, 26)

        self._full_heading = step.get("heading", "")
        self.heading.setText(self._full_heading)
        self.relayout()
        if animate:
            self._typed = 0
            self.heading.setText("​")
            self.typer.start(max(12, min(28, 650 // max(len(self._full_heading), 1))))
        self.update()

    def _set_button(self, text):
        self.next.setVisible(bool(text))
        if text:
            self.next.setText(f"{text}  ↵")
            width = QFontMetrics(self.fonts["button"]).horizontalAdvance(self.next.text()) + 40
            self.next.setFixedSize(width, 40)

    def relayout(self):
        """Give every part its exact size and the card the sum of them (see the class description)."""
        view = self.owner.centralWidget()
        width = min(self.WIDTH, max(480, view.width() - 40)) if view is not None and view.width() > 0 else self.WIDTH
        left, top, right, bottom = self.MARGINS
        inner = width - left - right
        self._width_used = width

        header = max(QFontMetrics(self.fonts["eyebrow"]).height(), 26 if self.leave.isVisibleTo(self) else 0)
        heading = text_height(self._escape(self._full_heading), self.fonts["heading"], inner) + 2
        text = text_height(self.body.text(), self.fonts["body"], inner) + 2
        self.heading.setFixedSize(inner, heading)
        self.body.setFixedSize(inner, text)

        has_row = bool(self.chips) or self.next.isVisibleTo(self) or self.keys_row.count() > 2
        self.row.setVisible(has_row)
        self.row.setFixedSize(inner, self.ROW_HEIGHT)
        self.row_space.changeSize(0, self.GAP_ROW if has_row else 0, QSizePolicy.Minimum, QSizePolicy.Fixed)

        hint = 0
        if self.hint.text():
            hint = text_height(self.hint.text(), self.fonts["hint"], inner) + 2
            self.hint.setFixedSize(inner, hint)
        self.hint.setVisible(bool(hint))
        self.hint_space.changeSize(0, self.GAP_HINT if hint else 0, QSizePolicy.Minimum, QSizePolicy.Fixed)

        height = top + header + self.GAP_TITLE + heading + self.GAP_TEXT + text
        if has_row:
            height += self.GAP_ROW + self.ROW_HEIGHT
        if hint:
            height += self.GAP_HINT + hint
        height += bottom
        self.setFixedSize(width, height)
        self.layout().invalidate()
        self.layout().activate()

    fit_height = relayout  # older name

    @staticmethod
    def _escape(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _type_more(self):
        """Typewriter: the heading appears a few letters at a time (its space is already set aside)."""
        self._typed += 1
        self.heading.setText(self._escape(self._full_heading[:self._typed]) or "​")
        if self._typed >= len(self._full_heading):
            self.typer.stop()

    def set_hint(self, text):
        if text == self.hint.text():
            return
        self.hint.setText(text)
        self.relayout()
        self.place()

    def show_button(self, text="Continue"):
        """Show the card's button now (the task is done: move on when you're ready)."""
        if self.next.isVisibleTo(self):
            return
        self._set_button(text)
        self.relayout()
        self.place()

    def set_task(self, fraction):
        """Progress of the current task: the card's background fills up from left to right."""
        before = self.task
        self.task = None if fraction is None else max(0.0, min(1.0, fraction))
        if self.task is None:
            self._fill = 0.0
        elif self.task >= 1.0 and (before is None or before < 1.0):
            import time

            self._shine_clock = time.monotonic()  # done: a sweep of light across the card
            self._shine = 0.0
        if not self.fill_timer.isActive():
            self.fill_timer.start()
        self.update()

    SHINE_SECONDS = 0.7

    def _animate_fill(self):
        import time

        target = self.task or 0.0
        self._fill += (target - self._fill) * 0.18  # eases, so steady progress looks smooth
        if abs(target - self._fill) < 0.002:
            self._fill = target
        if self._shine >= 0:
            self._shine = (time.monotonic() - self._shine_clock) / self.SHINE_SECONDS
            if self._shine > 1.0:
                self._shine = -1.0
        if self._fill == target and self._shine < 0:
            self.fill_timer.stop()
        self.update()

    def mark(self, name, state):
        if name in self.chips:
            self.chips[name].set_state(state)

    def celebrate(self, color=SUCCESS):
        """A short glow of the border when a step is done."""
        self._flash_color = QColor(color)
        for chip in self.chips.values():
            chip.set_state("done")
        self.flash.start()

    def _flash_frame(self, value):
        self._flash = value
        self.update()

    # Showing, moving, hiding

    def place(self, animate=False):
        view = self.owner.centralWidget()
        wanted = min(self.WIDTH, max(480, view.width() - 40))
        if self._step and wanted != getattr(self, "_width_used", None):
            self.relayout()  # the view changed width (side panel opened or closed): measure again
        corner = view.mapToGlobal(QPoint(0, 0))
        x = corner.x() + (view.width() - self.width()) // 2
        if self.position == "center":
            y = corner.y() + (view.height() - self.height()) // 2
        else:
            y = corner.y() + view.height() - self.height() - 14  # close to the bottom edge
        target = QPoint(x, y)
        if animate:
            self.slide.stop()
            self.slide.setDuration(420)
            self.slide.setEasingCurve(QEasingCurve.OutCubic)
            self.slide.setStartValue(target + QPoint(0, 22))
            self.slide.setEndValue(target)
            self.slide.start()
        else:
            self.move(target)

    def show_step(self, step):
        """Fade the old text out and the new one in, sliding up a little."""
        if not self.isVisible():
            self.set_content(step)
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
            self.place(animate=True)
            self._fade_to(0.97, 520)
            return
        self.fade.stop()
        self.fade.setDuration(170)
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(0.0)
        self._next_step = step
        self.fade.finished.connect(self._swap)
        self.fade.start()

    def _swap(self):
        self.fade.finished.disconnect(self._swap)
        self.set_content(self._next_step)
        self.place(animate=True)
        self._fade_to(0.97, 380)

    def _fade_to(self, value, duration):
        self.fade.stop()
        self.fade.setDuration(duration)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(value)
        self.fade.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        radius = 18.0

        # Soft glow around the card
        glow = QColor(self._flash_color if self._flash > 0 else self.border)
        for i in range(6, 0, -1):
            glow.setAlphaF((0.035 + 0.09 * self._flash) * (7 - i) / 6)
            painter.setPen(QPen(glow, i * 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(22, 30, 52, 242))
        gradient.setColorAt(1.0, QColor(12, 15, 24, 242))
        border = QColor(self._flash_color if self._flash > 0 else self.border)
        border.setAlphaF(0.45 + 0.5 * self._flash)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, radius, radius)

        # Progress of the current task: a brighter fill from the left with a slanted front edge
        if self.task is not None and self._fill > 0.001:
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.save()
            painter.setClipPath(clip)
            slant = 0.35 * rect.height()  # the front edge leans like a slash
            front = rect.left() + (rect.width() + slant) * self._fill
            finished = self.task >= 1.0 and self._fill > 0.99
            tint = QColor(63, 178, 127, 38) if finished else QColor(120, 160, 255, 36)
            fill = QPainterPath()
            fill.moveTo(rect.left(), rect.top())
            fill.lineTo(front, rect.top())
            fill.lineTo(front - slant, rect.bottom())
            fill.lineTo(rect.left(), rect.bottom())
            fill.closeSubpath()
            painter.fillPath(fill, tint)
            edge = QColor(255, 255, 255, 0 if finished else 34)  # a faint bright line on the front edge
            painter.setPen(QPen(edge, 1.5))
            painter.drawLine(QPointF(front, rect.top()), QPointF(front - slant, rect.bottom()))
            painter.restore()

        # Done: a band of light sweeps across the card once
        if self._shine >= 0:
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.save()
            painter.setClipPath(clip)
            t = 1 - (1 - self._shine) ** 2  # fast start, gentle finish
            width, slant = 90.0, 0.45 * rect.height()
            centre = rect.left() - width + (rect.width() + 2 * width + slant) * t
            band = QLinearGradient(QPointF(centre - width / 2, 0), QPointF(centre + width / 2, 0))
            band.setColorAt(0.0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(220, 255, 235, int(70 * (1 - self._shine * 0.5))))
            band.setColorAt(1.0, QColor(255, 255, 255, 0))
            shine = QPainterPath()
            shine.moveTo(centre - width / 2 + slant, rect.top())
            shine.lineTo(centre + width / 2 + slant, rect.top())
            shine.lineTo(centre + width / 2, rect.bottom())
            shine.lineTo(centre - width / 2, rect.bottom())
            shine.closeSubpath()
            painter.fillPath(shine, band)
            painter.restore()

        # Progress of the whole tutorial along the bottom edge
        if self.progress > 0:
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(clip)
            bar = QRectF(rect.left(), rect.bottom() - 3, rect.width() * self.progress, 3)
            painter.fillRect(bar, QColor(ACCENT))
            painter.setClipping(False)



# Sonar ping: a scan appears in a ring that sweeps outwards from the middle


class PingReveal(QObject):
    """Draws a cloud growing outwards from its middle, with a bright ring at the edge."""

    def __init__(self, scene, name, color, seconds=2.2, turn=0.0, on_done=None):
        super().__init__(scene.widget)
        self.scene = scene
        self.name = name
        self.seconds = seconds
        self.turn = turn  # degrees the camera drifts around the scan meanwhile
        self.on_done = on_done
        points = np.asarray(scene._shown(name, np.asarray(scene.geometries[name].points)))
        matrix = scene.matrices[name]
        points = points @ matrix[:3, :3].T + matrix[:3, 3]
        middle = np.median(points[:, :2], axis=0)
        distance = np.hypot(points[:, 0] - middle[0], points[:, 1] - middle[1])
        order = np.argsort(distance)
        self.points = points[order]
        self.distance = distance[order]
        self.reach = float(self.distance[-1]) * 1.04
        self.base = (np.array(color[:3]) * 255).astype(np.uint8)
        self.middle = middle
        self.level = float(np.median(points[:, 2]))

        self.mesh = pv.PolyData(self.points[:1])
        self.mesh["rgb"] = np.array([self.base])
        size = scene._screen_point_size()
        self.actor = scene.plotter.add_points(self.mesh, scalars="rgb", rgb=True, point_size=size,
                                              render_points_as_spheres=True, reset_camera=False,
                                              name=f"tutorial ping {name}")
        self.ring = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._frame)
        self.started = None

    def start(self):
        self.started = time.monotonic()
        self.timer.start()

    def _frame(self):
        plotter = self.scene.plotter
        t = min((time.monotonic() - self.started) / self.seconds, 1.0)
        eased = 1 - (1 - t) ** 3
        front = self.reach * eased
        count = max(1, int(np.searchsorted(self.distance, front)))
        colors = np.repeat(self.base[None, :], count, axis=0).astype(float)
        edge = np.clip(1 - (front - self.distance[:count]) / (0.09 * self.reach), 0, 1) ** 2
        colors += (np.array([200, 245, 255]) - colors) * edge[:, None] * 0.85
        mesh = pv.PolyData(self.points[:count])
        mesh["rgb"] = colors.astype(np.uint8)
        self.mesh.copy_from(mesh, deep=False)

        if self.ring is not None:
            plotter.remove_actor(self.ring, render=False)
        angles = np.linspace(0, 2 * np.pi, 160)
        circle = np.column_stack([self.middle[0] + front * np.cos(angles), self.middle[1] + front * np.sin(angles),
                                  np.full(angles.shape, self.level + 0.6)])
        ring = pv.lines_from_points(circle)
        self.ring = plotter.add_mesh(ring, color=(0.6, 0.92, 1.0), line_width=2.5, opacity=float(0.85 * (1 - t)),
                                     reset_camera=False, name=f"tutorial ring {self.name}")
        if self.turn:
            plotter.camera.Azimuth(self.turn * (eased - getattr(self, "_turned", 0.0)))
            self._turned = eased
        plotter.render()
        if t >= 1.0:
            self.finish()

    def finish(self):
        self.timer.stop()
        plotter = self.scene.plotter
        for actor in (self.actor, self.ring):
            if actor is not None:
                plotter.remove_actor(actor, render=False)
        self.actor = self.ring = None
        if self.on_done is not None:
            done, self.on_done = self.on_done, None
            done()


# The steps


PARAGRAPH_GAP = 8  # px between paragraphs: about half a line, not a whole empty line


def body(*paragraphs):
    """Paragraphs of a card's text, with a small even gap between them."""
    last = len(paragraphs) - 1
    return "".join(f"<p style='margin:0px 0px {0 if i == last else PARAGRAPH_GAP}px 0px;'>{text}</p>"
                   for i, text in enumerate(paragraphs))


class TutorialBase(QObject):
    """Takes the window over, gives its parts back one by one, and hands it back at the end.

    The steps are defined by a subclass: steps() with the texts, ORDER, and the hooks setup(),
    enter(), handle_key() and tick(). This class does everything they have in common: the card,
    locking the keys and the mouse, moving from step to step, leaving early and giving it all back.
    """

    STEP_COUNT = 0  # numbered steps (without the welcome and the end)
    ORDER = []
    CONTINUE = set()  # steps that Enter or the card's button move on from
    TAB_STEPS = []  # steps that explain the side panel's tabs, in tab order
    HIDE_PANEL = True  # start with the side panel closed
    MENU_PATH = "Help → Tutorial"

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.scene = window.scene
        self.active = False
        self.card = TutorialCard(window, self.on_continue, self.ask_leave)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.step = None
        self.confirming = False
        self.allow = set()  # what the user may do right now: "fly", "rotate", "pan", "panel", "tabs"
        self.unlocked = set()  # mouse and keys stay allowed once their step is done
        self.clickable = []  # widgets of the side panel that may be used in this step
        self._busy = False  # an animation or calculation is running: ignore the keys meanwhile
        self._leaving = None
        self._mouse_down = False
        self._camera = None
        self.used = set()
        self.held = set()  # movement keys that are down right now
        self.ping = None
        self.finished_callback = None

    # Hooks for the subclasses

    def setup(self):
        """Load the tutorial's data once everything is locked."""

    def enter(self, name):
        """A step starts (after its card is shown)."""

    def handle_key(self, step, key, command, event):
        """True: the key was used, False: let it through, None: not for this step (it stays locked)."""
        return None

    def tick(self, step, before, view):
        """Called 25 times a second: check whether the step is done."""

    def key_while_busy(self, step, key):
        """A key pressed while an animation runs (it is not used, unless a subclass remembers it)."""

    def after_finish(self, completed):
        """Everything is unlocked again: what to show now."""

    # Start and end

    def start(self):
        from viewer.scene import NAVIGATION_MODES

        window = self.window
        self.active = True
        window.cancel_tool()
        self.saved = {
            "dock": window.dock.isVisible(),
            "status": window.statusBar().isVisible(),
            "minimap": self.scene.minimap is not None,
            "axes": window.settings.view.show_axes,
            "icp": window.sidebar.icp_method.currentIndex(),
            "page": window.sidebar.pages.currentIndex(),
            "menus": [(item, item.isEnabled()) for item in window.menuBar().actions()],
        }
        window._autosave_timer.stop()
        window.dock.setVisible(not self.HIDE_PANEL)
        window.statusBar().hide()
        if self.saved["minimap"]:
            self.scene.set_minimap(False)
        if self.saved["axes"]:
            self.scene.set_axes_visible(False)
        for item, _ in self.saved["menus"]:
            item.setEnabled(False)
        window.set_navigation(NAVIGATION_MODES[0])
        self.setup()
        QApplication.instance().installEventFilter(self)
        self.timer.start()
        QTimer.singleShot(120, lambda: self.active and self.go(self.ORDER[0]))  # once the view has its new size

    def finish(self, completed):
        """Give everything back."""
        if not self.active:
            return
        window = self.window
        self.active = False
        self.timer.stop()
        if self.ping is not None:
            self.ping.finish()
        QApplication.instance().removeEventFilter(self)
        self.card.hide()
        self.card.deleteLater()
        window.cancel_tool()
        for item, enabled in self.saved["menus"]:
            item.setEnabled(enabled)
        window.statusBar().setVisible(self.saved["status"])
        if self.saved["axes"]:
            self.scene.set_axes_visible(True)
        if self.saved["minimap"] != (self.scene.minimap is not None):
            self.scene.set_minimap(self.saved["minimap"])
        window.sidebar.icp_method.blockSignals(True)
        window.sidebar.icp_method.setCurrentIndex(self.saved["icp"])
        window.sidebar.icp_method.blockSignals(False)
        for button in window.sidebar.switch.buttons:
            button.setStyleSheet("")
        window.sidebar.show_page(0)
        window.restart_autosave()
        self.after_finish(completed)
        if self.finished_callback is not None:
            self.finished_callback(completed)
        window.tutorial = None

    # Steps

    def steps(self):
        return {}

    def go(self, name):
        self.step = name
        self._leaving = None  # set by advance(), so a step can only be left once
        self.confirming = False
        self.used = set()
        self._busy = False
        self._camera = self.scene.current_view()
        self.travel = 0.0
        self.clickable = []
        content = self.steps()[name]
        number = content.get("number")
        if number:
            content["eyebrow"] = f"Step {number} of {self.STEP_COUNT}  ·  {content['eyebrow']}"
        self.card.progress = self.ORDER.index(name) / (len(self.ORDER) - 1)
        self.card.show_step(content)
        self.allow = set(self.unlocked)
        if name in self.TAB_STEPS:
            self.allow |= {"tabs"}
            self._show_tab(self.TAB_STEPS.index(name))
        self.enter(name)

    def advance(self, delay=0, to=None):
        """Celebrate briefly, then go to the next step (only once, however often this is called)."""
        current = self.step
        if self._leaving == current:
            return
        self._leaving = current
        following = to or self.ORDER[self.ORDER.index(current) + 1]
        self._busy = True
        if delay:
            self.card.celebrate()
            QTimer.singleShot(delay, lambda: self.active and self.step == current and self.go(following))
        else:
            self.go(following)

    def on_continue(self):
        if self.confirming or self._busy:
            return
        if self.step == self.ORDER[-1]:
            self.finish(completed=True)
        elif self.step in self.CONTINUE or self.step in self.TAB_STEPS:
            self.advance()

    # Leaving early

    def ask_leave(self):
        if self.step == self.ORDER[-1]:
            self.finish(completed=True)
            return
        self.confirming = True
        self.card.show_step(dict(
            position=self.card.position, eyebrow="Leave the tutorial?", heading="Surfacing already?",
            body=f"You can start the tutorial again any time from {self.MENU_PATH}.",
            keys=[("Enter", "enter"), ("leave", None), ("Esc", "esc"), ("stay", None)], leave=False))

    def stay(self):
        self.confirming = False
        self.go(self.step)

    # Input

    def eventFilter(self, obj, event):
        if not self.active:
            return False
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self.window:
            return False  # a dialog the tutorial opened (command palette, ...) works normally
        kind = event.type()
        if kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.key() == Qt.Key_Q \
                and event.modifiers() & Qt.ControlModifier:
            return False  # quitting the app always works
        if kind == QEvent.ShortcutOverride:
            event.accept()  # no menu shortcut fires during the tutorial, the keys come here instead
            return True
        if kind == QEvent.KeyPress:
            return self._key(event)
        if kind == QEvent.KeyRelease:
            if not event.isAutoRepeat():
                self.held.discard(event.key())
            if event.key() == Qt.Key_Shift:
                self.card.mark("shift", "done" if "shift" in self.used else "idle")
            return False  # releases always go through, so held movement keys stop
        if kind in (QEvent.Move, QEvent.Resize) and obj in (self.window, self.window.centralWidget()):
            QTimer.singleShot(0, self.card.place)
            return False
        if kind in (QEvent.DragEnter, QEvent.Drop):
            return True  # no dropped files during the tutorial
        if kind == QEvent.Wheel:
            return not self._wheel_allowed(obj)
        if obj is self.scene.widget and kind in MOUSE_EVENTS:
            return self._mouse(event)
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and isinstance(obj, QWidget):
            if obj.window() is self.window and obj is not self.window:
                return not self._allowed_click(obj)
        return False

    def _wheel_allowed(self, widget):
        """Zooming stays off, but lists and pages that may be used can scroll."""
        return isinstance(widget, QWidget) and self._in_clickable(widget)

    def _in_clickable(self, widget):
        return any(widget is allowed or allowed.isAncestorOf(widget) for allowed in self.clickable)

    def _allowed_click(self, widget):
        """Outside the 3D view only what the current step uses can be clicked."""
        if self._busy or self.confirming:
            return False
        if "tabs" in self.allow:
            for index, button in enumerate(self.window.sidebar.switch.buttons):
                if widget is button:
                    QTimer.singleShot(0, lambda i=index: self._jump_to_tab(i))
                    return True
        return self._in_clickable(widget)

    def _jump_to_tab(self, index):
        if self.active and self.step in self.TAB_STEPS and index < len(self.TAB_STEPS):
            self.go(self.TAB_STEPS[index])

    def _mouse(self, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            if not self.allow & {"rotate", "pan", "click"} or self._busy:
                return True
            self._mouse_down = True
            self.card.mark("drag", "pressed")
            return False
        if kind == QEvent.MouseButtonRelease:
            was_down = self._mouse_down
            self._mouse_down = False
            if "drag" in self.card.chips and self.step in ("rotate", "pan"):
                self.card.mark("drag", "idle")
            return not was_down
        if kind == QEvent.MouseMove and event.buttons() != Qt.NoButton:
            if not self._mouse_down:
                return True
            if event.modifiers() & Qt.ShiftModifier and "pan" not in self.allow:
                return True  # sliding comes in its own step
            if not self.allow & {"rotate", "pan"} and self.window._pick is None:
                return True  # clicks only: no turning the view yet
        return False

    def _key(self, event):
        key = event.key()
        modifiers = event.modifiers()
        command = bool(modifiers & Qt.ControlModifier)
        if event.isAutoRepeat():
            return not ("fly" in self.allow and key in FLY_KEYS)
        if key == Qt.Key_Escape:
            if self._busy and not self.confirming:
                return True  # wait for the animation or calculation to finish
            if self.confirming:
                self.stay()
            elif self.window._pick is not None:
                self.window.cancel_tool()
            else:
                self.ask_leave()
            return True
        if self.confirming:
            if key in ENTER_KEYS:
                self.finish(completed=False)
            return True
        if self._busy:
            self.key_while_busy(self.step, key)
            return True
        step = self.step

        if key in ENTER_KEYS:
            self.on_continue()
            return True
        if key == Qt.Key_Shift:
            if "pan" in self.allow or "fly" in self.allow:
                self.used.add("shift")
                self.card.mark("shift", "pressed")
            return False
        if key in FLY_KEYS and "fly" in self.allow and not command:
            self.held.add(key)
            letter = FLY_KEYS[key]
            if step == "fly":
                self.used.add(letter)
                self.card.mark(letter, "done")
            return False  # the movement itself is done by the fly controller
        if key == Qt.Key_Space and "panel" in self.allow:
            self.window.toggle_settings_panel()
            if step == "panel" and self.window.dock.isVisible():
                self.card.mark("space", "done")
                self.allow.discard("panel")
                self.advance(delay=500)
            return True
        handled = self.handle_key(step, key, command, event)
        if handled is not None:
            return handled
        if key in (Qt.Key_Control, Qt.Key_Meta):
            if "command" in self.card.chips:
                self.card.mark("command", "pressed")
            return True
        return True  # everything else is still locked

    def _reveal(self, name, turn, then):
        self._busy = True
        color = self.window.colors[name]

        def done():
            self.ping = None
            self.window.set_visible(name, True)
            QTimer.singleShot(250, then)

        self.ping = PingReveal(self.scene, name, color, turn=turn, on_done=done)
        self.ping.start()

    def _show_tab(self, index, highlight=True):
        sidebar = self.window.sidebar
        sidebar.show_page(index)
        for i, button in enumerate(sidebar.switch.buttons):
            button.setStyleSheet(f"#segmentButton {{ border: 1px solid {ACCENT}; }}" if highlight and i == index else "")

    # Watching what happens

    def _tick(self):
        if not self.active or self.confirming:
            return
        view = self.scene.current_view()
        before, self._camera = self._camera, view
        if before is None:
            return
        self.tick(self.step, before, view)

    def watch_turning(self, before, view, degrees, then):
        """Progress of a "turn the view" task: True when done."""
        if self._mouse_down:
            self.travel += angle_between(direction(before), direction(view))
        self.card.set_task(self.travel / degrees)
        return self.travel >= degrees


class Tutorial(TutorialBase):
    """The first tutorial: the basics on a container that fell to the seafloor."""

    STEP_COUNT = 12
    CONTINUE = {"scan_a", "difference", "aligned", "found"}
    TAB_STEPS = ["tab_settings", "tab_areas", "tab_guide", "tab_history"]

    def setup(self):
        from viewer.pipeline import build_inspections
        from viewer.settings import DataSettings

        window = self.window
        if window.series is not None:
            window.leave_series()
        method = window.sidebar.icp_method.findData("point-to-plane")
        window.sidebar.icp_method.blockSignals(True)
        window.sidebar.icp_method.setCurrentIndex(method)
        window.sidebar.icp_method.blockSignals(False)

        # The tutorial scan: no "true change" highlight, it has to be found
        data = DataSettings(scene=TUTORIAL_SCENE, n_points=40_000, rotation_deg=(1.5, -1.0, 6.0),
                            translation=(1.3, -0.9, 0.3))
        inspections = build_inspections(data)
        inspections.truth = {}
        inspections.title = "Tutorial: container on the seafloor"
        window.loaded_files = None
        window._show_inspections(inspections, reset_camera=False)
        for name in window.clouds:
            window.set_visible(name, False)
        self.scene.look_from("Iso", animate=False)
        self.scene.plotter.camera.Zoom(1.15)
        self.scene.plotter.render()
        self.home = self.scene.current_view()

    def after_finish(self, completed):
        from viewer import prefs

        if completed:
            prefs.set("tutorial_done", True)
            self.window.dock.show()  # they know Space now
        else:
            self.window.dock.setVisible(self.saved["dock"])
        self.window.open_default_scene()

    def steps(self):
        aligned = getattr(self, "fit_text", "")
        found = getattr(self, "found_text", "")
        return {
            "welcome": dict(
                big=True, position="center", eyebrow="Tutorial  ·  about 5 minutes", heading="Welcome aboard.",
                body=body("In the next few minutes you'll dive 50 metres down, look around a sonar scan "
                          "of the seafloor, and find something that wasn't there before.",
                          "Everything is switched off for now. We'll turn it on piece by piece."),
                keys=[("1", "1"), ("bring up the first scan", None)]),
            "scan_a": dict(
                number=1, eyebrow="Scan A  ·  the seafloor", heading="50 metres down.",
                body=body("This is a sonar scan of the seafloor, about 50 m below the surface, recorded by a "
                          "Subdron hovering above it.",
                          "Every one of these 40,000 dots is an echo that bounced back off the sand."),
                button="Continue"),
            "rotate": dict(
                number=2, eyebrow="Look around", heading="Take a look around.",
                body="Drag with the mouse to swing the camera around the scan. Go on, all the way round if you like.",
                keys=[("Drag", "drag"), ("with the mouse", None)]),
            "pan": dict(
                number=3, eyebrow="Look around", heading="Slide over.",
                body="Hold Shift while you drag, and the view slides sideways instead of turning.",
                keys=[("Shift", "shift"), ("+", None), ("Drag", "drag")]),
            "fly": dict(
                number=4, eyebrow="Move", heading="Swim through it.",
                body="<b>W A S D</b> take you forward, left, back and right. <b>Q</b> and <b>E</b> go down and up. "
                     "Hold <b>Shift</b> to go faster. Try a few of them.",
                keys=[(letter, letter) for letter in "WASDQE"]),
            "reset": dict(
                number=5, eyebrow="Move", heading="Lost at sea?",
                body="Press R any time and the camera glides back to where you started.",
                keys=[("R", "R"), ("back to the start", None)]),
            "scan_b": dict(
                number=6, eyebrow="Scan B  ·  a few months later", heading="Meanwhile, up on the quay…",
                body="A crane had a bad day. A few months later the Subdron went back down to scan the "
                     "same spot again. Press 2 to bring up the second scan.",
                keys=[("2", "2"), ("bring up the second scan", None)]),
            "difference": dict(
                number=7, eyebrow="Scan B  ·  a few months later", heading="Spot the difference?",
                body=body("Scan B is drawn in orange. Something new is lying in the middle of the seafloor.",
                          "And look closely: the two scans don't sit exactly on top of each other. "
                          "No two dives ever start from exactly the same spot."),
                button="Continue"),
            "toggle": dict(
                number=8, eyebrow="Compare", heading="Before and after.",
                body="Press 1 and 2 to switch each scan off and on again. It's the quickest way to compare "
                     "them by eye.",
                keys=[("1", "1"), ("2", "2")]),
            "align": dict(
                number=9, eyebrow="Align", heading="Line them up.",
                body=f"The software can slide scan B onto scan A by itself, by matching the shape of the "
                     f"seafloor. Press {COMMAND} L and watch it find the fit.",
                keys=[(COMMAND, "command"), ("+", None), ("L", "L")]),
            "aligned": dict(
                number=9, eyebrow="Align", heading="A perfect fit.",
                body=aligned, button="Continue"),
            "detect": dict(
                number=10, eyebrow="Find the changes", heading="Now, what changed?",
                body=f"Press {COMMAND} D. Every dot is compared with the other scan, and whatever is new "
                     f"or missing lights up.",
                keys=[(COMMAND, "command"), ("+", None), ("D", "D")]),
            "found": dict(
                number=10, eyebrow="Find the changes", heading="Found it.",
                body=found, button="Continue"),
            "panel": dict(
                number=11, eyebrow="The side panel", heading="Everything else lives here.",
                body="All settings, results and help are in the side panel. Press Space to open it, and press "
                     "it again whenever you want the room back.",
                keys=[("Space", "space")]),
            "tab_settings": dict(
                number=12, eyebrow="The side panel  ·  1 of 4", heading="Settings",
                body="Everything about what you see: which scene, the scans and their colours, alignment, "
                     "change detection, the camera and the display.",
                button="Next tab"),
            "tab_areas": dict(
                number=12, eyebrow="The side panel  ·  2 of 4", heading="Areas",
                body="Every change that was found, with its size, volume and how sure the software is. "
                     "Click one to fly there, and give it a tag or a comment for the report.",
                button="Next tab"),
            "tab_guide": dict(
                number=12, eyebrow="The side panel  ·  3 of 4", heading="Guide",
                body="The manual, right inside the app: every tool and every shortcut explained. "
                     "If you get stuck later, look here.",
                button="Next tab"),
            "tab_history": dict(
                number=12, eyebrow="The side panel  ·  4 of 4", heading="History",
                body=f"Every step you take is listed here. Click an earlier one to go back in time, or "
                     f"just press {COMMAND} Z.",
                button="Continue"),
            "end": dict(
                big=True, position="center", eyebrow="Tutorial complete", heading="You're ready to dive in.",
                body=body("Next up: a full-size harbour quay, 60 metres long, with seven changes hidden in it. "
                          "Everything is unlocked now.",
                          "You can watch this tutorial again any time from Help → Tutorial. Good hunting!"),
                button="Let's go", leave=False),
        }

    ORDER = ["welcome", "scan_a", "rotate", "pan", "fly", "reset", "scan_b", "difference", "toggle", "align",
             "aligned", "detect", "found", "panel", "tab_settings", "tab_areas", "tab_guide", "tab_history", "end"]

    def enter(self, name):
        self.allow |= {"rotate": {"rotate"}, "pan": {"rotate", "pan"}, "fly": {"fly"},
                       "panel": {"panel"}}.get(name, set())
        if name in ("rotate", "pan", "fly"):
            self.card.set_task(0.0)

    def handle_key(self, step, key, command, event):
        if key == Qt.Key_1 and step == "welcome":
            self.card.mark("1", "done")
            self.card._fade_to(0.0, 450)
            self._reveal("Scan A", turn=24.0, then=lambda: self.advance())
            return True
        if key == Qt.Key_2 and step == "scan_b":
            self.card.mark("2", "done")
            self._reveal("Scan B", turn=0.0, then=lambda: self.advance())
            return True
        if key in (Qt.Key_1, Qt.Key_2) and step == "toggle":
            name = "Scan A" if key == Qt.Key_1 else "Scan B"
            self.window.set_visible(name, not self.scene.is_visible(name))
            label = "1" if key == Qt.Key_1 else "2"
            self.used.add(label)
            self.card.mark(label, "done")
            self._check_toggle()
            return True
        if key == Qt.Key_R and step == "reset":
            self.card.mark("R", "done")
            self.scene.go_to_view(self.home)
            self.advance(delay=1100)
            return True
        if key == Qt.Key_L and command and step == "align":
            self.card.mark("command", "done")
            self.card.mark("L", "done")
            self._busy = True
            self.window.align()
            return True
        if key == Qt.Key_D and command and step == "detect":
            self.card.mark("command", "done")
            self.card.mark("D", "done")
            self._busy = True
            self.window.detect_changes()
            return True
        return None

    def _check_toggle(self):
        both_used = {"1", "2"} <= self.used
        both_on = all(self.scene.is_visible(name) for name in self.window.clouds)
        if both_used and both_on:
            self.card.set_hint("")
            self.advance(delay=700)
        elif both_used:
            self.card.set_hint("Now bring both scans back to carry on.")

    def tick(self, step, before, view):
        if step == "rotate" and not self._busy:
            if self.watch_turning(before, view, 100.0, None):
                self.unlocked.add("rotate")
                self.advance(delay=700)
        elif step == "pan" and not self._busy:
            moved = np.linalg.norm(np.subtract(view["focal_point"], before["focal_point"]))
            if self._mouse_down and angle_between(direction(before), direction(view)) < 0.4:
                self.travel += moved
            self.card.set_task(self.travel / 6.0)
            if self.travel >= 6.0:
                self.unlocked.add("pan")
                self.advance(delay=700)
        elif step == "fly" and not self._busy:
            if self.held and not self._mouse_down:
                self.travel += np.linalg.norm(np.subtract(view["position"], before["position"]))
            letters = len(self.used & set(FLY_KEYS.values()))
            self.card.set_task(min(letters / 4.0, self.travel / 8.0))
            if letters >= 4 and self.travel >= 8.0:
                self.unlocked.add("fly")
                self.advance(delay=700)
        elif step == "align" and self._busy and self.window.is_aligned():
            steps = self.window.align_steps
            moved = np.linalg.norm(np.asarray(steps[-1].transformation)[:3, 3])
            self.fit_text = body(
                f"Scan B slid {moved:.1f} m and turned into place in {len(steps) - 1} small steps. "
                f"The two scans now agree to within about {steps[-1].inlier_rmse * 100:.0f} cm.",
                "That's tighter than the sonar's own noise, so whatever still differs is real.")
            self.advance(delay=900)
        elif step == "detect" and self._busy and self.window.change_result is not None:
            result = self.window.change_result
            if result.areas:
                area = max(result.areas, key=lambda a: a.n_points)
                volume = getattr(area, "volume", None)
                size = f"about {volume:.0f} m³ including the sand it pushed aside" if volume else "big enough to see"
                self.found_text = body(
                    f"A 20 ft shipping container, {size}, lying on the seafloor 50 m down. "
                    f"That's the aftermath of the accident, found automatically.",
                    "Yellow marks the changed points, and the box shows the area with its size.")
                margin = np.array([7.0, 7.0, 2.0])
                lift = np.array([0.0, 0.0, 4.0])  # look a little lower, so the container sits above the card
                self.scene.focus_on(np.asarray(area.low) - margin - lift, np.asarray(area.high) + margin)
            else:
                self.found_text = "Nothing changed this time. Odd, but possible!"
            self.advance(delay=900)


def direction(view):
    vector = np.subtract(view["focal_point"], view["position"])
    return vector / (np.linalg.norm(vector) or 1.0)


def angle_between(a, b):
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))
