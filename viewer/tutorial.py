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
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from viewer.style import ACCENT, TEXT, TEXT_DIM, TEXT_FAINT

SUCCESS = "#3fb27f"
WARNING = "#e0a43a"
MAC = sys.platform == "darwin"
COMMAND = "⌘" if MAC else "Ctrl"
TUTORIAL_SCENE = "tutorial_seafloor"
ENTER_KEYS = (Qt.Key_Return, Qt.Key_Enter)
FLY_KEYS = {Qt.Key_W: "W", Qt.Key_A: "A", Qt.Key_S: "S", Qt.Key_D: "D", Qt.Key_Q: "Q", Qt.Key_E: "E"}
MOUSE_EVENTS = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.MouseMove)


# The card


class KeyChip(QLabel):
    """A key cap (or a mouse action) that lights up when it has been used."""

    def __init__(self, text, wide=False):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(78 if wide else 38)
        self.state = "idle"
        self._glow = 0.0
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setKeyValueAt(0.5, 1.0)
        self.pulse.setEndValue(0.0)
        self.pulse.setDuration(1600)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(self._set_glow)
        self._restyle()

    def start_pulse(self):
        self.pulse.start()

    def _set_glow(self, value):
        self._glow = value
        self._restyle()

    def set_state(self, state):
        """idle, pressed (being held / used) or done."""
        self.state = state
        if state == "done":
            self.pulse.stop()
            self._glow = 0.0
        self._restyle()

    def _restyle(self):
        accent = QColor(ACCENT)
        if self.state == "done":
            fill, border, text = "rgba(63, 178, 127, 0.22)", SUCCESS, "#bdf0d6"
        elif self.state == "pressed":
            fill, border, text = "rgba(61, 127, 245, 0.45)", ACCENT, "#ffffff"
        else:
            glow = self._glow
            fill = f"rgba(61, 127, 245, {0.08 + 0.14 * glow:.3f})"
            border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {0.45 + 0.55 * glow:.3f})"
            text = TEXT
        self.setStyleSheet(
            f"QLabel {{ background: {fill}; color: {text}; border: 1px solid {border};"
            f" border-bottom: 3px solid {border}; border-radius: 7px; padding: 5px 11px;"
            f" font-size: 15px; font-weight: 700; }}")


class TutorialCard(QWidget):
    """The floating text card: small step label, big heading, text, keys and a progress bar."""

    def __init__(self, owner, on_continue, on_leave):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.owner = owner
        self.position = "bottom"
        self.progress = 0.0  # whole tutorial, drawn along the bottom edge
        self.task = None  # progress of the current task (turning, moving), drawn under the keys
        self.border = QColor(ACCENT)
        self._full_heading = ""
        self._typed = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 24)
        layout.setSpacing(10)
        self.eyebrow = QLabel()
        layout.addWidget(self.eyebrow)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        layout.addWidget(self.body)
        layout.addSpacing(4)

        self.keys_row = QHBoxLayout()
        self.keys_row.setSpacing(8)
        layout.addLayout(self.keys_row)
        self.hint = QLabel()
        self.hint.setStyleSheet(f"color: {WARNING}; font-size: 13px;")
        self.hint.hide()
        layout.addWidget(self.hint)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        self.leave = QPushButton("Esc  ·  leave tutorial")
        self.leave.setCursor(Qt.PointingHandCursor)
        self.leave.setStyleSheet(f"QPushButton {{ background: none; border: none; color: {TEXT_FAINT}; font-size: 12px; }}"
                                 f"QPushButton:hover {{ color: {TEXT_DIM}; }}")
        self.leave.clicked.connect(on_leave)
        footer.addWidget(self.leave)
        footer.addStretch()
        self.next = QPushButton("Continue")
        self.next.setCursor(Qt.PointingHandCursor)
        self.next.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: white; border: none; border-radius: 8px;"
            f" padding: 8px 18px; font-size: 14px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: #5590f7; }}")
        self.next.clicked.connect(on_continue)
        footer.addWidget(self.next)
        layout.addLayout(footer)

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

    # Content

    def set_content(self, step, animate=True):
        """step: dict with eyebrow, heading, body, keys [(label, id)], button, position, big."""
        big = step.get("big", False)
        self.position = step.get("position", "bottom")
        self.setFixedWidth(660 if big else 580)
        inner = self.width() - 68  # minus the margins: wrapped text needs its real width to know its height
        for label in (self.heading, self.body, self.hint):
            label.setFixedWidth(inner)
        self.eyebrow.setText(step.get("eyebrow", "").upper())
        self.eyebrow.setStyleSheet(f"color: {ACCENT}; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        size = 38 if big else 25
        self.heading.setStyleSheet(f"color: {TEXT}; font-size: {size}px; font-weight: 700;")
        self.body.setText(f"<div style='line-height: 140%'>{step.get('body', '')}</div>")
        self.body.setStyleSheet(f"color: {TEXT_DIM}; font-size: {16 if big else 15}px;")
        self.hint.hide()
        self.task = None

        while self.keys_row.count():
            item = self.keys_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chips = {}
        for label, name in step.get("keys", []):
            if name is None:  # plain text between the keys
                text = QLabel(label)
                text.setStyleSheet(f"color: {TEXT_DIM}; font-size: 14px; padding: 0 4px;")
                self.keys_row.addWidget(text)
                continue
            chip = KeyChip(label, wide=len(label) > 3)
            chip.start_pulse()
            self.chips[name] = chip
            self.keys_row.addWidget(chip)
        self.keys_row.addStretch()

        button = step.get("button")
        self.next.setVisible(bool(button))
        self.next.setText(f"{button}  ↵" if button else "")
        self.leave.setVisible(step.get("leave", True))
        self.leave.setText(step.get("leave_text", "Esc  ·  leave tutorial"))

        self._full_heading = step.get("heading", "")
        self.heading.setText(self._full_heading)  # full text first, so the size is right
        self.fit_height()
        if animate:
            self._typed = 0
            self.heading.setText("​")
            self.typer.start(max(12, min(28, 650 // max(len(self._full_heading), 1))))
        self.update()

    def fit_height(self):
        """Height from the parts themselves (Qt's own estimate comes out short for wrapped text)."""
        layout = self.layout()
        margins = layout.contentsMargins()
        inner = self.width() - margins.left() - margins.right()
        parts = [self.eyebrow.sizeHint().height(), self.heading.heightForWidth(inner),
                 self.body.heightForWidth(inner), 4]
        if self.chips or self.keys_row.count() > 1:
            parts.append(max(widget.sizeHint().height() for widget in self.findChildren(QLabel)
                             if self.keys_row.indexOf(widget) >= 0))
        if not self.hint.isHidden():
            parts.append(self.hint.heightForWidth(inner))
        parts.append(8 + max(self.next.sizeHint().height(), self.leave.sizeHint().height()))
        height = margins.top() + margins.bottom() + sum(parts) + layout.spacing() * (len(parts) - 1)
        layout.activate()
        self.setFixedHeight(max(height, layout.totalHeightForWidth(self.width())))

    def _type_more(self):
        """Typewriter: the heading appears a few letters at a time."""
        self._typed += 1
        self.heading.setText(self._full_heading[:self._typed] or "​")
        if self._typed >= len(self._full_heading):
            self.typer.stop()

    def set_hint(self, text):
        self.hint.setText(text)
        self.hint.setVisible(bool(text))
        self.fit_height()
        self.place()

    def set_task(self, fraction):
        self.task = None if fraction is None else max(0.0, min(1.0, fraction))
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
        corner = view.mapToGlobal(QPoint(0, 0))
        x = corner.x() + (view.width() - self.width()) // 2
        if self.position == "center":
            y = corner.y() + (view.height() - self.height()) // 2
        else:
            y = corner.y() + view.height() - self.height() - 46
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

        # Progress of the whole tutorial along the bottom edge
        if self.progress > 0:
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(clip)
            bar = QRectF(rect.left(), rect.bottom() - 3, rect.width() * self.progress, 3)
            painter.fillRect(bar, QColor(ACCENT))
            painter.setClipping(False)

        # Progress of the current task, a thin line under the keys
        if self.task is not None and self.keys_row.count():
            top = self.keys_row.geometry().bottom() + 8
            track = QRectF(rect.left() + 28, top, rect.width() - 56, 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.drawRoundedRect(track, 2, 2)
            done = QRectF(track.left(), track.top(), track.width() * self.task, track.height())
            painter.setBrush(QColor(SUCCESS if self.task >= 1 else ACCENT))
            painter.drawRoundedRect(done, 2, 2)


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


def body(*paragraphs):
    return "<br><br>".join(paragraphs)


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
                keys=[(COMMAND, "command"), ("L", "L")]),
            "aligned": dict(
                number=9, eyebrow="Align", heading="A perfect fit.",
                body=aligned, button="Continue"),
            "detect": dict(
                number=10, eyebrow="Find the changes", heading="Now, what changed?",
                body=f"Press {COMMAND} D. Every dot is compared with the other scan, and whatever is new "
                     f"or missing lights up.",
                keys=[(COMMAND, "command"), ("D", "D")]),
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
