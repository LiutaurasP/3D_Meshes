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


def summary_card(number, learned, keys):
    return dict(eyebrow=f"Chapter {number} of 6  ·  done", heading=f"Chapter {number}: done.",
                body=learned, keys=keys, button="Next chapter" if number < 6 else "Finish")


class AdvancedTutorial(TutorialBase):
    """The Storm Season: everything beyond the basics, in six chapters."""

    MENU_PATH = "the Guide (or Help → Advanced Tutorial)"
    ORDER = ["welcome",
             "c1", "c1_scans", "c1_timeline", "c1_animation", "c1_done",
             "c2", "c2_fish", "c2_lasso", "c2_undo", "c2_redo", "c2_palette", "c2_history", "c2_done",
             "c3", "c3_colours", "c3_swipe", "c3_minimap", "c3_done",
             "c4", "c4_section", "c4_section_read", "c4_measure", "c4_measured", "c4_heightmap", "c4_done",
             "c5", "c5_areas", "c5_tags", "c5_note", "c5_done",
             "c6", "c6_details", "c6_report", "c6_display", "end"]
    CONTINUE = {"welcome", "c1", "c1_done", "c2", "c2_fish", "c2_history", "c2_done", "c3", "c3_done", "c4",
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

    # Start and end

    def setup(self):
        from viewer import prefs
        from viewer.pipeline import example_series
        from datasets import HIDDEN_SCENES

        window = self.window
        self.saved_minimap_pref = prefs.get("show_minimap")
        series = example_series(HIDDEN_SCENES[SERIES_KEY].default_points, SERIES_KEY)
        window._on_series_ready(series)  # shows spring against a year later, then aligns and detects
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
        if self.scene.swipe:
            window.sidebar.swipe.setChecked(False)
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

    def on_continue(self):
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

    def show_panel(self, page, widget=None, highlight=False):
        window = self.window
        window.dock.show()
        self._show_tab(page, highlight)
        if widget is not None:
            window.sidebar.pages.widget(page).ensureWidgetVisible(widget, 20, 40)
            QTimer.singleShot(0, lambda: window.sidebar.pages.widget(page).ensureWidgetVisible(widget, 20, 40))

    def fish_count(self):
        cloud = self.window.clouds.get("Scan B")
        if cloud is None or not len(cloud.points):
            return 0
        matrix = self.scene.matrices["Scan B"]
        points = np.asarray(cloud.points) @ matrix[:3, :3].T + matrix[:3, 3]
        near = np.hypot(points[:, 0] - FISH[0], points[:, 1] - FISH[1]) < 6.0
        off_pile = np.hypot(points[:, 0], points[:, 1]) > 3.8
        return int(np.count_nonzero(near & off_pile & (points[:, 2] > -26.0)))

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
            "c1_timeline": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Scrub through the year.",
                body=body("The <b>Timeline</b> in the side panel holds all four scans. Drag its slider through "
                          "summer and autumn, then back to the end.",
                          "Each comparison is aligned and checked for changes automatically. Watch the blue ring of "
                          "missing sand grow."),
                keys=[("Drag", "drag"), ("the Timeline slider", None)]),
            "c1_animation": dict(
                eyebrow="Chapter 1  ·  A year in four scans", heading="Now watch it happen.",
                body="Press <b>P</b> to play the change: the missing sand sinks away and whatever is new rises "
                     "out of the old seabed.",
                keys=[("P", "P"), ("play the change", None)]),
            "c1_done": summary_card(1, "You stepped through a year of scans and watched the seabed change.",
                                    [("Timeline", "t"), ("P", "p")]),

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
                keys=[(COMMAND, "command"), ("Z", "Z")]),
            "c2_redo": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Nothing is ever lost.",
                body=f"And <b>{COMMAND} {SHIFT} Z</b> redoes it: the fish are gone again.",
                keys=[(COMMAND, "command"), (SHIFT, "shift"), ("Z", "Z")]),
            "c2_palette": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="The one shortcut to remember.",
                body=body(f"<b>{COMMAND} K</b> opens the command palette: every command in the app, found by "
                          f"typing a few letters.",
                          "Open it, type <b>stray</b> and press Enter. That removes single echoes floating far "
                          "from everything else."),
                keys=[(COMMAND, "command"), ("K", "K"), ("then type  stray", None)]),
            "c2_history": dict(
                eyebrow="Chapter 2  ·  Clean up", heading="Every step, on record.",
                body="The <b>History</b> tab lists everything you did. Click any earlier step to travel back to "
                     "it, and click a later one to come forward again.",
                button="Continue"),
            "c2_done": summary_card(2, "You cleaned a scan without ever losing a point.",
                                    [("L", "l"), (f"{COMMAND} Z", "z"), (f"{COMMAND} K", "k")]),

            "c3": chapter_card(3, body(
                "Back to the whole year: spring against the scan after the storms.",
                "Three ways to see a change more clearly.")),
            "c3_colours": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Colour it by change.",
                body="In the side panel, set <b>Colours</b> to <b>Change</b>. Blue is where something is gone, red "
                     "where something was added, and the stronger the colour, the bigger the change.",
                keys=[("Colours", "colours"), ("→", None), ("Change", "change")]),
            "c3_swipe": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Before and after, side by side.",
                body="Press <b>B</b> for the before / after swipe, then drag the white line across the "
                     "foundation: spring on the left, after the storms on the right.",
                keys=[("B", "B"), ("then drag the line", None)]),
            "c3_minimap": dict(
                eyebrow="Chapter 3  ·  Look closer", heading="Where am I?",
                body=f"Press <b>{SHIFT} M</b> for the minimap: the site from above, with you on it. Click "
                     f"anywhere on it to fly there.",
                keys=[(SHIFT, "shift"), ("M", "M"), ("then click on the map", None)]),
            "c3_done": summary_card(3, "Colours, the swipe and the minimap: three ways to see more.",
                                    [("Colours", "c"), ("B", "b"), (f"{SHIFT} M", "m")]),

            "c4": chapter_card(4, body(
                "Seeing a hole is one thing. The operator will want numbers: how deep, how wide, where exactly.",
                "Out with the tools.")),
            "c4_section": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Cut through the hole.",
                body="Press <b>X</b>, then click on the rocks near the pile and on the flat sand beyond the hole. "
                     "That cuts a slice through both scans, right across the scour.",
                keys=[("X", "X"), ("then click twice, across the hole", None)]),
            "c4_section_read": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="Read the slice.",
                body="The blue line is the seabed last spring, the orange one after the storms. The gap between "
                     "them is the sand the currents carried away.",
                button="Continue"),
            "c4_measure": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="How deep is it?",
                body="Press <b>T</b>, click the flat sand at the edge of the hole, then its deepest point.",
                keys=[("T", "T"), ("then click the edge and the bottom", None)]),
            "c4_measured": dict(
                eyebrow="Chapter 4  ·  Measure it", heading=f"{depth:.1f} metres down." if depth else "Measured.",
                body="The line shows the distance, and the notification splits it into horizontal and vertical. "
                     "Measurements stay in the scene until you clear them.",
                button="Continue"),
            "c4_heightmap": dict(
                eyebrow="Chapter 4  ·  Measure it", heading="The whole site from above.",
                body="Press <b>H</b> for the height difference map: blue where the seabed went down, red where it "
                     "came up. The scour ring stands out, deepest where the current comes from.",
                keys=[("H", "H")], button="Continue"),
            "c4_done": summary_card(4, "A slice, a measurement and a map: the numbers behind the picture.",
                                    [("X", "x"), ("T", "t2"), ("H", "h")]),

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
            "c5_done": summary_card(5, "Volumes, confidence, tags and a note: the change is judged.",
                                    [("Areas", "a"), ("N", "n")]),

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
                keys=[(COMMAND, "command"), (SHIFT, "shift"), ("R", "R")]),
            "c6_display": dict(
                eyebrow="Chapter 6  ·  Hand it over", heading="One more thing.",
                body=f"Presenting this to the operator? Press <b>{COMMAND} {SHIFT} P</b> for Display Mode. Any key "
                     f"brings you back.",
                keys=[(COMMAND, "command"), (SHIFT, "shift"), ("P", "P")]),
            "end": dict(
                big=True, position="center", eyebrow="Advanced tutorial complete", heading="Storm season: survived.",
                body=body("Timeline, cleaning, comparing, measuring, judging and reporting: you've used all of it.",
                          "Everything is unlocked now. Stay at the wind farm and explore, or press Esc to go back "
                          "to the harbour quay."),
                button="Keep exploring", leave_text="Esc  ·  back to the harbour quay"),
        }

    # Entering a step: set the scene up for it

    def enter(self, name):
        window = self.window
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
            self.visited = set()
            self.show_panel(0, window.sidebar.timeline_card, highlight=True)
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
            self.show_panel(3, highlight=True)
            self.clickable = [window.sidebar.pages.widget(3)]
        elif name in ("c3", "c4", "c5", "c6"):
            self.need(SPRING, AFTER)
            if name != "c3":  # back to the normal colours with the yellow highlight after chapter 3
                window.sidebar.color_mode.setCurrentText("Per scan")
                window.sidebar.show_changes.setChecked(True)
        elif name == "c3_colours":
            self.look((0, 0, -28.5), 48.0, -100, 38)
            self.show_panel(0, window.sidebar.color_mode)
            self.clickable = [window.sidebar.color_mode]
        elif name == "c3_swipe":
            self._swipe_moved = False
        elif name == "c3_minimap":
            self._minimap_flown = False
        elif name == "c4_section":
            self.look(SCOUR, 26.0, 290, 50)  # from the side, so the pile doesn't stand in the way
        elif name == "c4_section_read":
            pass
        elif name == "c4_heightmap":
            self._map_opened = False
        elif name == "c4_measure":
            self.measured_before = len(window.measurements)
        elif name == "c5_areas":
            self.show_panel(1, highlight=True)
            scour = self.scour_area()
            if scour is not None:
                window.sidebar.areas_panel.select(self.area_index(scour))
        elif name == "c5_tags":
            self.show_panel(1, highlight=True)
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
            name, label = ("Scan A", "1") if key == Qt.Key_1 else ("Scan B", "2")
            if name in self.revealed or self.ping is not None:
                return True
            self.revealed.add(name)
            self.card.mark(label, "done")

            def revealed():
                self._busy = False
                if self.revealed >= {"Scan A", "Scan B"}:
                    self.advance(delay=600)

            self._reveal(name, turn=12.0 if name == "Scan A" else 0.0, then=revealed)
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
            self.card.mark("X", "done")
            return True
        if step == "c4_measure" and key == Qt.Key_T and not command:
            window.start_tool("measure")
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

    def jump_to_chapter(self, number):
        """From the welcome card straight into a chapter (the earlier ones count as done)."""
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
                    self.advance(delay=700)
        elif step == "c1_animation" and self._animated:
            if not window.change_animation.active:
                self._busy = False
                self.advance(delay=500)
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
            self.advance(delay=900)
        elif step == "c3_swipe" and self.scene.swipe:
            moved = abs(self.scene.swipe["fraction"] - 0.5)
            self.card.set_task(moved / 0.2)
            if moved >= 0.2:
                self.advance(delay=900)
        elif step == "c3_minimap" and self.scene.minimap is not None:
            start = getattr(self, "_minimap_view", None)
            if start is not None and np.linalg.norm(np.subtract(view["focal_point"], start["focal_point"])) > 2.0:
                self.advance(delay=1400)
        elif step == "c4_section" and window.section_window is not None and window.section_window.isVisible():
            self.advance(delay=600)
        elif step == "c4_measure" and len(window.measurements) > self.measured_before:
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
        if step == "c4_section_read" and window.section_window is not None:
            window.section_window.hide()
        if step == "c4_heightmap" and getattr(window, "height_map_window", None) is not None:
            window.height_map_window.hide()
        if step == "c2_history" or step == "c5_tags" or step == "c1_timeline":
            for button in window.sidebar.switch.buttons:
                button.setStyleSheet("")
        super().advance(delay, to)
