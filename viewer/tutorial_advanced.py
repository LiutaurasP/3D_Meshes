"""Advanced tutorial "The Storm Season": the deeper tools on a wind turbine foundation scanned four times.

Six chapters, each opened by a title card and closed by a short summary:
  1 A year in four scans   Timeline slider, change animation (P)
  2 Clean up               lasso (L), undo / redo, command palette (Cmd+K), History
  3 Look closer            change colours, before / after swipe (B), minimap (Shift+M)
  4 Measure it             cross section (X), measuring (T), height map (H)
  5 Judge it               Areas tab: volumes, confidence, tags and status, notes (N)
  6 Hand it over           report details, PDF report (Cmd+Shift+R), Display Mode (Cmd+Shift+P)

The welcome card can jump straight to any chapter. The basics (turning, sliding, flying, Space)
are unlocked from the start; everything else unlocks chapter by chapter.
"""

from pathlib import Path

import numpy as np
from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from viewer.tutorial import COMMAND, TutorialBase, body

SERIES_KEY = "wind_turbine_storm"
SPRING, SUMMER, AUTUMN, AFTER = range(4)
FISH = np.array([7.5, -6.0, -21.5])  # where the school of fish swims (scene coordinates)
ANCHOR = np.array([5.1, 4.2, -27.3])
CURRENT = np.array([np.cos(np.radians(200)), np.sin(np.radians(200)), 0.0])  # the side the current comes from
SCOUR = CURRENT * 11.0 + np.array([0, 0, -29.4])  # deepest part of the scour hole
SHIFT = "⇧"
NOTE_TEXT = "Anchor and chain caught on the rock protection. Ask the operator to have it removed."

CHAPTERS = [
    ("A year in four scans", "Timeline · change animation"),
    ("Clean up", "lasso · undo · command palette · History"),
    ("Look closer", "change colours · before / after swipe · minimap"),
    ("Measure it", "cross section · measuring · height map"),
    ("Judge it", "volumes · confidence · tags · notes"),
    ("Hand it over", "PDF report · Display Mode"),
]


def chapter_card(number, story):
    title, contents = CHAPTERS[number - 1]
    return dict(big=True, position="center", eyebrow=f"Chapter {number} of 6  ·  {contents}", heading=title,
                body=story, button="Begin")


def keycaps(*keys):
    """Keys written like small key caps inside the text (for reading, not pressing)."""
    cap = ("<span style='background-color:#262a36; color:#e6e7eb; font-weight:600; font-size:18px;'>"
           "&nbsp;{}&nbsp;</span>")
    return " <span style='color:#62656e;'>+</span> ".join(cap.format(key) for key in keys)


def summary_card(number, learned, items):
    """What the chapter taught, as a short reference: [(keys or a name, what it does)]."""
    rows = "".join(
        f"<tr><td style='padding:3px 16px 3px 0; white-space:nowrap;'>"
        f"{keycaps(*what) if isinstance(what, tuple) else f'<b>{what}</b>'}</td>"
        f"<td style='padding:3px 0; color:#9a9da7;'>{meaning}</td></tr>"
        for what, meaning in items)
    return dict(eyebrow=f"Chapter {number} of 6  ·  what you learned", heading=f"Chapter {number} complete.",
                body=f"<p style='margin:0px 0px 6px 0px;'>{learned}</p><table cellspacing='0'>{rows}</table>",
                button="Next chapter" if number < 6 else "Finish")


class AdvancedTutorial(TutorialBase):
    """The Storm Season: everything beyond the basics, in six chapters."""

    MENU_PATH = "the Guide (or Help → Advanced Tutorial)"
    ORDER = ["welcome",
             "c1", "c1_scans", "c1_align", "c1_detect", "c1_timeline", "c1_animation", "c1_done",
             "c2", "c2_fish", "c2_lasso", "c2_undo", "c2_redo", "c2_palette", "c2_history", "c2_done",
             "c3", "c3_colours", "c3_swipe", "c3_minimap", "c3_done",
             "c4", "c4_explain", "c4_section", "c4_section_read", "c4_measure", "c4_measured", "c4_heightmap",
             "c4_done",
             "c5", "c5_areas", "c5_tags", "c5_note", "c5_done",
             "c6", "c6_details", "c6_report", "c6_display", "end"]
    CONTINUE = {"welcome", "c1", "c1_done", "c2", "c2_fish", "c2_history", "c2_done", "c3", "c3_done", "c4",
                "c4_explain",
                "c4_section_read", "c4_measured", "c4_heightmap", "c4_done", "c5", "c5_areas", "c5_done", "c6",
                "c6_details"}

    def __init__(self, window):
        super().__init__(window)
        self.unlocked = {"rotate", "pan", "fly", "panel"}  # the basics are known already
        self.open_files = True  # open the PDF when it is written (tests switch this off)
        self.display_fullscreen = None  # Display Mode as set in its settings (tests: False)
        self.report_path = None
        self.revealed = set()
        self.visited = set()
        self.waiting_for = None  # (older, newer): comparison that has to be aligned and detected first
        self.targets = []  # points the user is asked to click (chapter 4)
        self.looking = set()  # steps that are done and wait for Continue (time to look)
        # Counts taken when a step starts (they exist from the start, so jumping into a chapter is safe)
        self.fish_before = self.points_before = self.measured_before = self.notes_before = 0
        self.target_actors = []

    # Start and end

    def setup(self):
        from viewer import prefs
        from viewer.pipeline import example_series
        from datasets import SCENES

        window = self.window
        self.saved_minimap_pref = prefs.get("show_minimap")
        window.use_icp_method(SCENES[SERIES_KEY].icp_method)  # open seabed: slide along the surface
        series = example_series(SCENES[SERIES_KEY].default_points, SERIES_KEY)
        # Chapter 1 aligns and compares by hand, step by step: the Timeline's automatic mode waits until then
        self.saved_auto = window.sidebar.timeline_auto.isChecked()
        window.sidebar.timeline_auto.setChecked(False)
        window._on_series_ready(series)  # spring against a year later, not aligned yet
        for name in window.clouds:
            window.set_visible(name, False)
        self.scene.look_from("Iso", animate=False)
        self.scene.plotter.camera.Zoom(1.25)
        self.scene.plotter.render()
        self.home = self.scene.current_view()
        self.waiting_for = (SPRING, AFTER)

    def after_finish(self, completed):
        from viewer import prefs

        window = self.window
        prefs.set("show_minimap", self.saved_minimap_pref)
        window.sidebar.timeline_auto.setChecked(self.saved_auto)
        if self.scene.swipe:
            window.sidebar.swipe.setChecked(False)
        self.clear_targets()
        for helper in ("section_window", "height_map_window"):
            if getattr(window, helper, None) is not None:
                getattr(window, helper).hide()
        if completed and getattr(self, "stay_on_site", False):
            for name in window.clouds:
                window.set_visible(name, True)
            window.dock.show()
            window.history.clear()
            window._update_title()
        else:
            window.dock.setVisible(self.saved["dock"])
            if window.series is not None:
                window.leave_series()
            window.open_default_scene()

    def done_look_around(self):
        """The task of this step is done: celebrate, show Continue and let the user look as long as they like."""
        if self.step in self.looking:
            return
        self.looking.add(self.step)
        self._busy = False
        self.card.celebrate()
        self.card.set_task(1.0)  # the card fills up and the shine sweeps across
        self.card.show_button("Continue")

    def on_continue(self):
        if self.step in self.looking and not self.confirming:
            self.advance()
            return
        if getattr(self, "_shown_waiting", False):
            return  # the scans are still being aligned and compared
        if self.step == "c4_heightmap" and not getattr(self, "_map_opened", False):
            return  # open the map first
        if self.step == self.ORDER[-1] and not self.confirming:
            self.stay_on_site = True
        super().on_continue()

    def ask_leave(self):
        if self.step == self.ORDER[-1]:
            self.stay_on_site = False
            self.finish(completed=True)
            return
        super().ask_leave()

    # Helpers

    def ready(self):
        """The comparison the step needs is aligned and its changes are detected."""
        window = self.window
        return (window.series_pair == self.waiting_for and window.is_aligned()
                and window.change_result is not None
                and not (window._change_worker is not None and window._change_worker.isRunning()))

    def need(self, older, newer):
        """Show this comparison (aligned and detected); the step waits until it is ready."""
        self.waiting_for = (older, newer)
        for name in self.window.clouds:
            if not self.scene.is_visible(name):
                self.window.set_visible(name, True)
        if self.window.series_pair != (older, newer):
            self.window.compare_scans(older, newer)

    def look(self, focal, distance, azimuth_deg, elevation_deg, animate=True):
        """Fly the camera to look at a point from a direction (degrees around and above)."""
        az, el = np.radians(azimuth_deg), np.radians(elevation_deg)
        offset = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]) * distance
        view = {"position": tuple(np.asarray(focal) + offset), "focal_point": tuple(focal), "up": (0.0, 0.0, 1.0),
                "view_angle": self.scene.plotter.camera.view_angle}
        self.scene.go_to_view(view, animate)

    def need_panel(self, page, widget=None, highlight=False):
        """This step works in the side panel. Closed? Then the card first asks for Space, and the step goes on
        once the panel is open (it never opens by itself)."""
        if self.window.dock.isVisible():
            self.show_panel(page, widget, highlight)
            return
        self._panel_wanted = (page, widget, highlight)  # the card asks for Space, see card_content()

    PANEL_STEPS = {"c1_timeline", "c2_history", "c3_colours", "c5_areas", "c5_tags"}  # they work in the side panel

    def card_content(self, name):
        content = dict(self.steps()[name])
        if name in self.PANEL_STEPS and not self.window.dock.isVisible():
            content["keys"] = [("Space", "space"), ("open the side panel", None)]
            content.pop("button", None)
        return content

    def panel_toggled(self):
        wanted = getattr(self, "_panel_wanted", None)
        if wanted is None or not self.window.dock.isVisible():
            return
        self._panel_wanted = None
        self.card.mark("space", "done")
        self.show_panel(*wanted)
        self.card.set_content(dict(self.steps()[self.step]), animate=False)  # the step's own keys again
        self.card.celebrate()

    def show_panel(self, page, widget=None, highlight=False):
        window = self.window
        self._show_tab(page, highlight)
        if widget is not None:
            window.sidebar.pages.widget(page).ensureWidgetVisible(widget, 20, 40)
            QTimer.singleShot(0, lambda: window.sidebar.pages.widget(page).ensureWidgetVisible(widget, 20, 40))

    def surface(self, xy):
        """The seabed under a spot (x, y), from the newer scan as it is shown."""
        cloud = self.window.clouds["Scan B"]
        matrix = self.scene.matrices["Scan B"]
        points = np.asarray(cloud.points) @ matrix[:3, :3].T + matrix[:3, 3]
        near = np.hypot(points[:, 0] - xy[0], points[:, 1] - xy[1]) < 0.8
        z = float(np.median(points[near, 2])) if near.any() else -28.0
        return np.array([xy[0], xy[1], z])

    def show_targets(self, spots, line=False):
        """Numbered dots on the seabed that show where to click. They pop up one after another
        (with a little bounce), then the line between them appears, and the dots keep breathing gently."""
        import time

        self.clear_targets()
        self.targets = [self.surface(spot) for spot in spots]
        self._target_line = line
        self._target_shown = 0
        self._target_clock = time.monotonic()
        self.target_timer = QTimer(self)
        self.target_timer.setInterval(16)
        self.target_timer.timeout.connect(self._animate_targets)
        self.target_timer.start()

    TARGET_GAP = 0.45  # seconds between the dots popping up
    TARGET_POP = 0.38  # seconds for one pop

    def _animate_targets(self):
        import time

        import pyvista as pv

        plotter = self.scene.plotter
        ratio = self.scene.widget.devicePixelRatioF()
        lifted = [point + np.array([0, 0, 0.15]) for point in self.targets]
        elapsed = time.monotonic() - self._target_clock
        while self._target_shown < len(lifted) and elapsed >= self._target_shown * self.TARGET_GAP:
            index = self._target_shown
            dot = plotter.add_points(lifted[index][None, :], color=(1.0, 1.0, 1.0), point_size=1,
                                     render_points_as_spheres=True, reset_camera=False,
                                     name=f"tutorial target {index}", pickable=False)
            label = plotter.add_point_labels(lifted[index][None, :] + np.array([0, 0, 1.4]), [str(index + 1)],
                                             font_size=34, bold=True, text_color="white",
                                             shape_color=(0.24, 0.5, 0.96), shape_opacity=0.95, show_points=False,
                                             always_visible=True, reset_camera=False,
                                             name=f"tutorial target label {index}")
            self.target_actors += [dot, label]
            self._target_dots = getattr(self, "_target_dots", []) + [(dot, index * self.TARGET_GAP)]
            self._target_shown += 1
            if self._target_shown == len(lifted) and self._target_line:
                self.target_actors.append(plotter.add_mesh(
                    pv.Line(lifted[0], lifted[1]), color=(0.85, 0.9, 1.0), line_width=2 * ratio, opacity=0.6,
                    reset_camera=False, name="tutorial target line", pickable=False))
        for dot, born in getattr(self, "_target_dots", []):
            age = elapsed - born
            if age < self.TARGET_POP:  # pop: grow past the final size, then settle (ease out with overshoot)
                t = age / self.TARGET_POP
                scale = 1 + 5.0 * (t - 1) ** 3 + 4.0 * (t - 1) ** 2
            else:  # breathe gently, so the eye keeps finding them
                scale = 1 + 0.12 * np.sin((age - self.TARGET_POP) * 2 * np.pi / 1.6)
            dot.GetProperty().SetPointSize(max(1.0, 26 * ratio * scale))
        plotter.render()

    def clear_targets(self):
        timer = getattr(self, "target_timer", None)
        if timer is not None:
            timer.stop()
        for actor in getattr(self, "target_actors", []):
            self.scene.plotter.remove_actor(actor, render=False)
        self.target_actors = []
        self._target_dots = []
        self.targets = []
        self.scene.plotter.render()

    def fish_count(self):
        cloud = self.window.clouds.get("Scan B")
        if cloud is None or not len(cloud.points):
            return 0
        matrix = self.scene.matrices["Scan B"]
        points = np.asarray(cloud.points) @ matrix[:3, :3].T + matrix[:3, 3]
        near = np.hypot(points[:, 0] - FISH[0], points[:, 1] - FISH[1]) < 6.0
        off_pile = np.hypot(points[:, 0], points[:, 1]) > 5.0  # the pile's surface is 3 m out, each scan a bit shifted
        return int(np.count_nonzero(near & off_pile & (points[:, 2] > -25.5)))

    def total_points(self):
        return sum(len(cloud.points) for cloud in self.window.clouds.values())

    def last_edit(self):
        stack = self.window.history.stack
        return stack.text(stack.index() - 1) if stack.index() > 0 else ""

    def areas(self):
        result = self.window.change_result
        return result.areas if result is not None else []

    def area_index(self, area):
        return next(i for i, other in enumerate(self.areas()) if other is area)

    def scour_area(self):
        removed = [a for a in self.areas() if a.kind == "removed"]
        return max(removed, key=lambda a: a.n_points) if removed else None

    def anchor_area(self):
        added = [a for a in self.areas() if a.kind == "added"]
        if not added:
            return None
        return min(added, key=lambda a: np.linalg.norm(((np.asarray(a.low) + a.high) / 2)[:2] - ANCHOR[:2]))

    # Steps

    def steps(self):
        scour, anchor = self.scour_area(), self.anchor_area()
        scour_volume = abs(scour.volume) if scour is not None and scour.volume is not None else 0
        scour_error = scour.volume_error if scour is not None and scour.volume_error is not None else 0
        anchor_volume = anchor.volume if anchor is not None and anchor.volume is not None else 0
        measured = getattr(self.window, "last_measurement", None)
        depth = abs(measured[2]) if measured else 0
        distance = measured[0] if measured else 0
        section = getattr(self.window, "last_section", None) or {}
        section_length = section.get("length", 0)
        section_depth = abs(section["biggest"][1]) if section.get("biggest") else 0  # (where, how much)
        return {
            "welcome": dict(
                big=True, position="center", eyebrow="Advanced tutorial  ·  about 15 minutes",
                heading="The Storm Season.",
                body=body("North Sea, 28 metres down: the foundation of a wind turbine. A Subdron scanned it "
                          "four times in one year. Then the winter storms came.",
                          "Your job: find out what happened down there, and hand the operator a report. Along the "
                          "way you'll learn everything beyond the basics."),
                keys=[("Enter", "enter"), ("start", None), ("1 – 6", "chapters"), ("jump to a chapter", None)],
                button="Start"),

            "c1": chapter_card(1, body(
                "A wind turbine stands on a single steel pile, 6 metres wide, rammed into the sand. Around it lies a "
                "ring of rocks against scour: currents dig the sand away from anything that stands in their way.",
                "Four scans, one year. Let's see what the sea has been up to.")),
            "c1_scans": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Spring, and a year later.",
                body=f"Press <b>1</b> for the first scan, last spring. Then press <b>2</b> for the latest one, "
                     f"after the storms.",
                keys=[("1", "1"), ("spring", None), ("2", "2"), ("a year later", None)]),
            "c1_align": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="First, line them up.",
                body=f"The two scans don't sit on top of each other yet: no two dives start from exactly the "
                     f"same spot. Press <b>{COMMAND} + L</b> and watch the latest scan slide into place.",
                keys=[(COMMAND, "command"), ("+", None), ("L", "L"), ("align the scans", None)]),
            "c1_detect": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Now, what changed in a year?",
                body=f"Press <b>{COMMAND} + D</b> to compare the two scans point by point. Keep an eye on the "
                     f"sand around the foundation.",
                keys=[(COMMAND, "command"), ("+", None), ("D", "D"), ("find the changes", None)]),
            "c1_timeline": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Scrub through the year.",
                body=body("A ring of sand has washed away around the rocks. When did that happen? The "
                          "<b>Timeline</b> in the side panel holds all four scans: drag its slider through summer "
                          "and autumn, then back to the end.",
                          "From now on the Timeline aligns and compares every pair for you, the same two steps you "
                          "just did."),
                keys=[("Drag", "drag"), ("the Timeline slider", None)]),
            "c1_animation": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Now watch it happen.",
                body="Press <b>P</b> to play the change: the missing sand sinks away and whatever is new rises "
                     "out of the old seabed.",
                keys=[("P", "P"), ("play the change", None)]),
            "c1_done": summary_card(1, "You stepped through a year of scans and watched the seabed change.",
                                    [("Timeline slider", "steps through the scans of a series"),
                                     (("P",), "plays the change as an animation")]),

            "c2": chapter_card(2, body(
                "Real scans are never clean. Fish, bubbles and stray echoes all end up as points, and they get in "
                "the way when you look for real changes.",
                "Time to tidy up the autumn scan.")),
            "c2_fish": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Something's swimming in here.",
                body=body("This is summer against autumn. That orange cloud floating above the seabed is a school "
                          "of fish that swam through the sonar beam.",
                          "Change detection marks it as new, but it's not what we're looking for."),
                button="Continue"),
            "c2_lasso": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Lasso them out.",
                body="Press <b>L</b>, then hold the mouse button and draw a loop around the fish. Every point "
                     "inside the loop is deleted.",
                keys=[("L", "L"), ("then draw around the fish", None)]),
            "c2_undo": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Changed your mind?",
                body=f"Press <b>{COMMAND} Z</b>. Every edit can be undone, and the points come back exactly "
                     f"where they were.",
                keys=[(COMMAND, "command"), ("+", None), ("Z", "Z")]),
            "c2_redo": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Nothing is ever lost.",
                body=f"And <b>{COMMAND} {SHIFT} Z</b> redoes it: the fish are gone again.",
                keys=[(COMMAND, "command"), ("+", None), (SHIFT, "shift"), ("+", None), ("Z", "Z")]),
            "c2_palette": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="The one shortcut to remember.",
                body=body(f"<b>{COMMAND} K</b> opens the command palette: every command in the app, found by "
                          f"typing a few letters.",
                          "Open it, type <b>stray</b> and press Enter. That removes single echoes floating far "
                          "from everything else."),
                keys=[(COMMAND, "command"), ("+", None), ("K", "K"), ("then type  stray", None)]),
            "c2_history": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Every step, on record.",
                body="The <b>History</b> tab lists everything you did. Click any earlier step to travel back to "
                     "it, and click a later one to come forward again.",
                button="Continue"),
            "c2_done": summary_card(2, "You cleaned a scan without ever losing a point.",
                                    [(("L",), "lasso: draw a loop, the points inside are deleted"),
                                     ((COMMAND, "Z"), "undo"), ((COMMAND, SHIFT, "Z"), "redo"),
                                     ((COMMAND, "K"), "command palette: find any command by typing"),
                                     ("History tab", "go back to any earlier step")]),

            "c3": chapter_card(3, body(
                "Back to the whole year: spring against the scan after the storms.",
                "Three ways to see a change more clearly.")),
            "c3_colours": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Colour it by change.",
                body="In the side panel, set <b>Colours</b> to <b>Change</b>. Blue is where something is gone, red "
                     "where something was added, and the stronger the colour, the bigger the change.",
                keys=[("Colours", "colours"), ("then", None), ("Change", "change")]),
            "c3_swipe": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Before and after, side by side.",
                body="Press <b>B</b> for the before / after swipe, then drag the white line across the "
                     "foundation: spring on the left, after the storms on the right.",
                keys=[("B", "B"), ("then drag the line", None)]),
            "c3_minimap": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Where am I?",
                body=f"Press <b>{SHIFT} M</b> for the minimap: the site from above, with you on it. Click "
                     f"anywhere on it to fly there.",
                keys=[(SHIFT, "shift"), ("+", None), ("M", "M"), ("then click on the map", None)]),
            "c3_done": summary_card(3, "Three ways to see a change more clearly.",
                                    [("Colours: Change", "blue where something is gone, red where something was added"),
                                     (("B",), "before / after swipe"),
                                     ((SHIFT, "M"), "minimap: click it to fly there")]),

            "c4": chapter_card(4, body(
                "Seeing a hole is one thing. The operator will want numbers: how deep, how wide, where exactly.",
                "Out with the tools.")),
            "c4_explain": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Slice through the seabed.",
                body=body("A <b>cross section</b> works like cutting a cake: you draw a line across the seabed, "
                          "and the app shows the height of both scans along that line, one above the other. "
                          "A hole is easy to see that way, and easy to put a number on.",
                          "We've marked a good line for you: <b>dot 1</b> on the rocks next to the pile, "
                          "<b>dot 2</b> on the flat sand beyond the hole."),
                button="Continue"),
            "c4_section": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Cut the slice.",
                body="Press <b>X</b>, then click <b>dot 1</b> and then <b>dot 2</b>. A click close to a dot is "
                     "enough.",
                keys=[("X", "X"), ("then", None), ("1", "1"), ("2", "2")]),
            "c4_section_read": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Read the slice.",
                body=body(f"The new window shows your line from dot 1 on the left to dot 2 on the right, "
                          f"{section_length:.0f} m long. The <b>blue</b> line is the seabed last spring, the "
                          f"<b>orange</b> line after the storms.",
                          f"Where orange drops below blue, sand is gone: up to <b>{section_depth:.1f} m</b> along "
                          f"this line."),
                button="Continue"),
            "c4_measure": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Now, the measuring tape.",
                body="Press <b>T</b>, click <b>dot 1</b> on the flat sand, then <b>dot 2</b> at the bottom of the "
                     "hole. You get the straight distance between them, and how much of it goes down.",
                keys=[("T", "T"), ("then", None), ("1", "1"), ("2", "2")]),
            "c4_measured": dict(
                eyebrow="Chapter 4  ·  Measure it", heading=f"{depth:.1f} metres deep." if depth else "Measured.",
                body=body(f"The line between the dots is {distance:.1f} m long, and {depth:.1f} m of it goes "
                          f"straight down: that's how deep the currents dug.",
                          "Measurements stay in the scene until you clear them (Analyze → Clear Measurements)."),
                button="Continue"),
            "c4_heightmap": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="The whole site from above.",
                body="Press <b>H</b> for the height difference map: blue where the seabed went down, red where it "
                     "came up. The scour ring stands out, deepest where the current comes from.",
                keys=[("H", "H")], button="Continue"),
            "c4_done": summary_card(4, "A slice, a measurement and a map: the numbers behind the picture.",
                                    [(("X",), "cross section: click two points, see both scans along that line"),
                                     (("T",), "measure: click two points, get the distance and the height"),
                                     (("H",), "height difference map of the whole site")]),

            "c5": chapter_card(5, body(
                "The software found the changes. Now it's your call: what is it, and does someone need to act?",
                "That judgement goes into the report.")),
            "c5_areas": dict(
                eyebrow="Chapter 5  ·  Judge it", heading="Every change, measured.",
                body=body(f"The <b>Areas</b> tab lists each change with its volume. The scour: about "
                          f"<b>{scour_volume:.0f} m³</b> of sand gone, give or take {scour_error:.0f} m³. The "
                          f"anchor and its chain: about <b>{anchor_volume:.1f} m³</b>.",
                          "<i>Clear</i>, <i>likely</i> or <i>uncertain</i> says how far the change stands out from "
                          "the sonar's own noise."),
                button="Continue"),
            "c5_tags": dict(
                eyebrow="Chapter 5  ·  Judge it", heading="Put a name on it.",
                body="Select the big <b>removed</b> area and set its Tag to <b>Scour</b> and its Status to "
                     "<b>Open</b>. Then select the <b>added</b> area and tag it <b>Debris</b>.",
                keys=[("Scour", "scour"), ("Open", "open"), ("Debris", "debris")]),
            "c5_note": dict(
                eyebrow="Chapter 5  ·  Judge it", heading="Leave a note.",
                body="Press <b>N</b> and click on the anchor, right in front of you. The note is pinned in 3D and "
                     "goes into the report.",
                keys=[("N", "N"), ("then click on the anchor", None)]),
            "c5_done": summary_card(5, "Every change is measured, judged and labelled.",
                                    [("Areas tab", "volumes, confidence, tags, status and comments"),
                                     (("N",), "pin a note in 3D, it goes into the report")]),

            "c6": chapter_card(6, body(
                "The operator is waiting. Time to put it all into a report, and to show it off.",
                "Last chapter.")),
            "c6_details": dict(
                eyebrow="Chapter 6  ·  Hand it over", heading="Who is it for?",
                body=body("Every report starts with the details: client, site, inspector, remarks. We've filled "
                          "them in for this job. Normally they're asked for when you export.",
                          "<span style='color:#62656e'>Client: North Sea Wind (example) · Site: turbine B-07 "
                          "foundation · Reference: storm season check</span>"),
                button="Continue"),
            "c6_report": dict(
                eyebrow="Chapter 6  ·  Hand it over", heading="Write the report.",
                body=f"Press <b>{COMMAND} {SHIFT} R</b>. The PDF gets an overview, a close-up of every area, the "
                     f"table with volumes and tags, the height map and your note. It opens when it's ready.",
                keys=[(COMMAND, "command"), ("+", None), (SHIFT, "shift"), ("+", None), ("R", "R")]),
            "c6_display": dict(
                eyebrow="Chapter 6  ·  Hand it over", heading="One more thing.",
                body=f"Presenting this to the operator? Press <b>{COMMAND} {SHIFT} P</b> for Display Mode. Any key "
                     f"brings you back.",
                keys=[(COMMAND, "command"), ("+", None), (SHIFT, "shift"), ("+", None), ("P", "P")]),
            "end": dict(
                big=True, position="center", eyebrow="Advanced tutorial complete", heading="Storm season: survived.",
                body=body("Timeline, cleaning, comparing, measuring, judging and reporting: you've used all of it.",
                          "Everything is unlocked now. Stay at the wind farm and explore, or press Esc to go back "
                          "to the harbour quay."),
                button="Keep exploring", leave_text="Back to the harbour quay    Esc"),
        }

    # Entering a step: set the scene up for it

    def enter(self, name):
        window = self.window
        self._panel_wanted = None
        chapter = int(name[1]) if name[0] == "c" and name[1].isdigit() else 0
        if name in ("c2", "c3", "c4", "c5", "c6"):
            self.unlocked |= {"rotate", "pan", "fly", "panel"}
            for scan in window.clouds:
                window.set_visible(scan, True)
        if name == "c1_scans":
            for scan in window.clouds:
                window.set_visible(scan, False)
            self.revealed = set()
        elif name == "c1_timeline":
            window.sidebar.timeline_auto.setChecked(True)
            self.visited = set()
            self.need_panel(0, window.sidebar.timeline_card, highlight=True)
            self.clickable = [window.sidebar.timeline_card]
        elif name == "c1_animation":
            self.need(SPRING, AFTER)
            self._animated = False
        elif name == "c2":
            self.need(SUMMER, AUTUMN)
        elif name == "c2_fish":
            self.need(SUMMER, AUTUMN)
            self.look(FISH, 24.0, 51, -4)  # from the side and a little below, the pile beside the fish, not behind
        elif name == "c2_lasso":
            self.fish_before = self.fish_count()
            self.points_before = self.total_points()
        elif name == "c2_history":
            self.need_panel(3, highlight=True)
            self.clickable = [window.sidebar.pages.widget(3)]
        elif name in ("c3", "c4", "c5", "c6"):
            self.need(SPRING, AFTER)
            if name != "c3":  # back to the normal colours after chapter 3
                window.sidebar.color_mode.setCurrentText("Per scan")
                # Chapter 4 measures the seabed itself: the yellow highlight would cover the dots to click
                window.sidebar.show_changes.setChecked(name != "c4")
        elif name == "c3_colours":
            self.look((0, 0, -28.5), 48.0, -100, 38)
            self.need_panel(0, window.sidebar.color_mode)
            self.clickable = [window.sidebar.color_mode]
        elif name == "c3_swipe":
            self._swipe_moved = False
        elif name == "c3_minimap":
            self._minimap_flown = False
        elif name == "c4_explain":
            # Seen from above, so it's clear where the dots are; the line runs from the rocks across the hole
            self.show_targets([CURRENT * 7.0, CURRENT * 16.0], line=True)
            self.look(CURRENT * 11.5 + np.array([0, 0, -28.5]), 30.0, 290, 68)
        elif name == "c4_section":
            if not self.targets:
                self.show_targets([CURRENT * 7.0, CURRENT * 16.0], line=True)
                self.look(CURRENT * 11.5 + np.array([0, 0, -28.5]), 30.0, 290, 68)
        elif name == "c4_heightmap":
            self._map_opened = False
        elif name == "c4_measure":
            self.measured_before = len(window.measurements)
            self.show_targets([CURRENT * 16.0, CURRENT * 11.0])  # the flat sand, the bottom of the hole
            self.look(CURRENT * 13.5 + np.array([0, 0, -28.5]), 22.0, 290, 35)
        elif name == "c5_areas":
            self.need_panel(1, highlight=True)
            scour = self.scour_area()
            if scour is not None:
                window.sidebar.areas_panel.select(self.area_index(scour))
        elif name == "c5_tags":
            self.need_panel(1, highlight=True)
            self.clickable = [window.sidebar.areas_panel]
        elif name == "c5_note":
            self.notes_before = len(window.notes)
            self.look(ANCHOR, 13.0, -40, 50)
        elif name == "c6_details":
            from viewer import prefs

            window.set_report_details({
                "client": "North Sea Wind (example)", "site": "Turbine B-07 foundation",
                "inspector": prefs.get("inspector_name") or "Tutorial", "reference": "Storm season check",
                "remarks": "Edge scour around the rock protection after the storm season, deepest on the current "
                           "side. Anchor and chain caught on the rock protection."})
        elif name == "c6_report":
            self.report_path = None
        elif name == "c6_display":
            self._display_started = False
        if chapter and name == f"c{chapter}" and chapter > 1 and window.dock.isVisible():
            self._show_tab(0, highlight=False)
        if name in ("c1_timeline",):
            self.card.set_task(0.0)

    # Keys

    def handle_key(self, step, key, command, event):
        window = self.window
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        if step == "welcome" and Qt.Key_1 <= key <= Qt.Key_6:
            self.jump_to_chapter(key - Qt.Key_0)
            return True
        if step == "c1_scans" and key in (Qt.Key_1, Qt.Key_2):
            self.reveal_scan("Scan A" if key == Qt.Key_1 else "Scan B")
            return True
        if step == "c1_align" and key == Qt.Key_L and command:
            self.card.mark("command", "done")
            self.card.mark("L", "done")
            self._busy = True
            window.align()
            return True
        if step == "c1_detect" and key == Qt.Key_D and command:
            self.card.mark("command", "done")
            self.card.mark("D", "done")
            self._busy = True
            window.detect_changes()
            return True
        if step == "c1_animation" and key == Qt.Key_P and self.ready():
            if window.play_change_animation():
                self.card.mark("P", "done")
                self._animated = True
                self._busy = True
            return True
        if step == "c2_lasso" and key == Qt.Key_L and not command:
            self.card.mark("L", "done")
            window.start_tool("lasso_delete")
            return True
        if step in ("c2_lasso", "c2_undo") and key == Qt.Key_Z and command and not shift:
            window.history.stack.undo()
            self.card.mark("Z", "done")
            return True
        if step == "c2_redo" and key == Qt.Key_Z and command and shift:
            window.history.stack.redo()
            self.card.mark("Z", "done")
            return True
        if step == "c2_palette" and key == Qt.Key_K and command:
            self.card.mark("K", "done")
            QTimer.singleShot(0, window.show_palette)  # a dialog of its own: keys work normally in it
            return True
        if step == "c3_swipe" and key == Qt.Key_B and not command:
            window.sidebar.swipe.setChecked(not window.sidebar.swipe.isChecked())
            self.card.mark("B", "done")
            return True
        if step == "c3_minimap" and key == Qt.Key_M and shift and not command:
            window.set_minimap(True)
            self.card.mark("M", "done")
            self.card.mark("shift", "done")
            self._minimap_view = self.scene.current_view()
            return True
        if step == "c4_section" and key == Qt.Key_X and not command:
            window.start_tool("section")
            window._pick["snap_to"] = list(self.targets)
            self.card.mark("X", "done")
            return True
        if step == "c4_measure" and key == Qt.Key_T and not command:
            window.start_tool("measure")
            window._pick["snap_to"] = list(self.targets)
            self.card.mark("T", "done")
            return True
        if step == "c4_heightmap" and key == Qt.Key_H and not command:
            window.show_height_map()
            self._map_opened = True
            self.card.mark("H", "done")
            self.card.celebrate()
            return True
        if step == "c5_note" and key == Qt.Key_N and not command:
            window.start_tool("note")
            window._pick["text"] = NOTE_TEXT  # pinned without asking for the text
            self.card.mark("N", "done")
            return True
        if step == "c6_report" and key == Qt.Key_R and command and shift:
            self.card.mark("R", "done")
            self._busy = True
            QTimer.singleShot(50, self.write_report)
            return True
        if step == "c6_display" and key == Qt.Key_P and command and shift:
            self.card.mark("P", "done")
            self._busy = True
            self._display_started = True
            self.card.hide()
            window.start_display_mode(self.display_fullscreen)
            return True
        return None

    def reveal_scan(self, name):
        """Ping a scan in (chapter 1). A second key pressed during the first ping is kept for afterwards."""
        if name in self.revealed:
            return
        if self.ping is not None:
            self.queued = name
            return
        self.revealed.add(name)
        self.card.mark("1" if name == "Scan A" else "2", "done")

        def revealed():
            self._busy = False
            waiting, self.queued = getattr(self, "queued", None), None
            if waiting and waiting not in self.revealed:
                self.reveal_scan(waiting)
            elif self.revealed >= {"Scan A", "Scan B"}:
                self.advance(delay=600)

        self._reveal(name, turn=12.0 if name == "Scan A" else 0.0, then=revealed)

    def key_while_busy(self, step, key):
        if step == "c1_scans" and key in (Qt.Key_1, Qt.Key_2):
            self.reveal_scan("Scan A" if key == Qt.Key_1 else "Scan B")

    def jump_to_chapter(self, number):
        """From the welcome card straight into a chapter (the earlier ones count as done)."""
        if number == 1:
            self.advance(to="c1")  # chapter 1 aligns and compares by hand
            return
        self.window.sidebar.timeline_auto.setChecked(True)
        if not self.window.is_aligned():
            self.window._detect_after_align = True
            self.window.align()
        self.revealed = {"Scan A", "Scan B"}
        for name in self.window.clouds:
            self.window.set_visible(name, True)
        self.advance(to=f"c{number}")

    def write_report(self):
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "Tutorial"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Storm season report.pdf"
        pages = self.window.export_report(str(path))
        self.report_path = path if pages else None
        if self.report_path and self.open_files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if self.active:
            self.advance(delay=900)

    # Watching

    def tick(self, step, before, view):
        window = self.window
        if step == "c1_align" and self._busy and window.is_aligned():
            self._busy = False
            self.advance(delay=900)
            return
        if step == "c1_detect" and self._busy and window.change_result is not None:
            self.done_look_around()  # time to look at the ring
            return
        if step in self.looking:
            return
        if self._busy and step not in ("c1_animation", "c6_display"):
            return
        waiting = step in ("c1_animation", "c2", "c2_fish", "c3", "c4", "c5", "c6") and not self.ready()
        if waiting != getattr(self, "_shown_waiting", False):
            self._shown_waiting = waiting
            self.card.set_hint("One moment: aligning and comparing the scans…" if waiting else "")
            self.card.next.setEnabled(not waiting)
        if waiting:
            return

        if step == "c1_timeline":
            if window.series_pair is not None:
                self.visited.add(window.series_pair[1])
            seen = len(self.visited & {SUMMER, AUTUMN})
            back = window.series_pair == (SPRING, AFTER)
            self.card.set_task((seen + (1 if back and seen == 2 else 0)) / 3)
            if seen == 2 and back:
                self.waiting_for = (SPRING, AFTER)
                if self.ready():
                    self.done_look_around()
        elif step == "c1_animation" and self._animated:
            if not window.change_animation.active:
                self.done_look_around()
        elif step == "c2_lasso" and self.fish_before:
            left = self.fish_count() / self.fish_before
            self.card.set_task(1 - left)
            lost = self.points_before - self.total_points()
            too_much = lost > 3 * self.fish_before + 1000  # the loop caught a lot of seabed as well
            if left < 0.15 and too_much:
                self.card.set_hint(f"That loop caught some seabed too. Press {COMMAND} Z and draw again, "
                                   f"around the fish only.")
            elif left < 0.15:
                self.card.set_hint("")
                self.advance(delay=800)
        elif step == "c2_undo" and self.fish_count() >= 0.9 * self.fish_before:
            self.advance(delay=700)
        elif step == "c2_redo" and self.fish_count() < 0.15 * self.fish_before:
            self.advance(delay=700)
        elif step == "c2_palette" and self.last_edit() == "Remove Stray Points":
            self.advance(delay=800)
        elif step == "c3_colours" and self.scene.settings.color_mode == "Change":
            window.sidebar.show_changes.setChecked(False)  # the yellow highlight would hide the colours
            self.card.mark("colours", "done")
            self.card.mark("change", "done")
            self.done_look_around()
        elif step == "c3_swipe" and self.scene.swipe:
            moved = abs(self.scene.swipe["fraction"] - 0.5)
            self.card.set_task(moved / 0.2)
            if moved >= 0.2:
                self.done_look_around()  # keep swiping as long as you like
        elif step == "c3_minimap" and self.scene.minimap is not None:
            start = getattr(self, "_minimap_view", None)
            if start is not None and np.linalg.norm(np.subtract(view["focal_point"], start["focal_point"])) > 2.0:
                self.done_look_around()
        elif step in ("c4_section", "c4_measure"):
            picked = len(window._pick["points"]) if window._pick is not None else 0
            if picked >= 1:
                self.card.mark("1", "done")
            if step == "c4_section" and window.section_window is not None and window.section_window.isVisible():
                self.card.mark("2", "done")
                self.advance(delay=700)
            elif step == "c4_measure" and len(window.measurements) > self.measured_before:
                self.card.mark("2", "done")
                self.advance(delay=700)
        elif step == "c5_tags":
            scour, anchor = self.scour_area(), self.anchor_area()
            marks = {"scour": scour is not None and scour.tag == "Scour",
                     "open": scour is not None and scour.status == "Open",
                     "debris": anchor is not None and anchor.tag == "Debris"}
            for chip, done in marks.items():
                self.card.mark(chip, "done" if done else "idle")
            self.card.set_task(sum(marks.values()) / 3)
            if all(marks.values()):
                self.advance(delay=800)
        elif step == "c5_note" and len(window.notes) > self.notes_before:
            self.advance(delay=900)
        elif step == "c6_display" and self._display_started:
            display = getattr(window, "display_mode", None)
            if display is not None and not display.active:
                self._display_started = False
                self._busy = False
                self.card.show()
                self.advance()

    # Leaving a step: tidy up what it opened

    def advance(self, delay=0, to=None):
        window = self.window
        step = self.step
        if step == "c3_swipe" and self.scene.swipe:
            QTimer.singleShot(delay, lambda: window.sidebar.swipe.setChecked(False))
        if step == "c3_minimap":
            QTimer.singleShot(delay, lambda: window.set_minimap(False))
        if step == "c4_section_read":
            self.clear_targets()
            if window.section_window is not None:
                window.section_window.hide()
            if getattr(window, "_section_line", None):  # the slice's line would get in the way of measuring
                self.scene.remove_overlay(window._section_line)
                window._section_line = None
        if step == "c4_measured":
            self.clear_targets()
        if step == "c4_heightmap" and getattr(window, "height_map_window", None) is not None:
            window.height_map_window.hide()
        if step == "c2_history" or step == "c5_tags" or step == "c1_timeline":
            for button in window.sidebar.switch.buttons:
                button.setStyleSheet("")
        super().advance(delay, to)
