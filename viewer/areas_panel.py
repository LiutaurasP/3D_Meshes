"""Areas tab: every changed area in a table, with a tag, a status and a comment for each."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from viewer import style
from viewer.widgets import Card, Form, hint
from volumes import area_volume_text

TAGS = ("", "Debris", "Scour", "Sediment", "Damage", "Structure", "Marine growth", "False alarm")
STATUSES = ("", "Open", "Checked", "Resolved")
FILTERS = (("All areas", lambda a: True), ("Open (not checked yet)", lambda a: a.status in ("", "Open")),
           ("Added", lambda a: a.kind == "added"), ("Removed", lambda a: a.kind == "removed"),
           ("Moved objects", lambda a: getattr(a, "_move", None) is not None),
           ("Without false alarms", lambda a: a.tag != "False alarm"))
MOVED = QColor(style.MOVED)
ADDED, REMOVED = QColor(style.ADDED), QColor(style.REMOVED)


class NumberItem(QTableWidgetItem):
    """Sorts by a number instead of by its text."""

    def __init__(self, text, value):
        super().__init__(text)
        self.value = value

    def __lt__(self, other):
        return (self.value if self.value is not None else float("-inf")) < \
               (other.value if getattr(other, "value", None) is not None else float("-inf"))


class AreasPanel(QWidget):
    def __init__(self, on_select, on_edit, on_track=None, on_not_move=None):
        """on_select(area index), on_edit(area index, field, value), on_track(track number),
        on_not_move(area index): "Not a move" was clicked for a moved object"""
        super().__init__()
        self.on_select, self.on_edit, self.on_track, self.on_not_move = on_select, on_edit, on_track, on_not_move
        self.tracks = []
        self.moves = []
        self.overview = False  # huge scans: the areas were found on the overview (✓ / ≈ marks)
        self.areas = []
        self.current = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = Card("Changed areas")
        self.summary = hint("Run Detect Changes to list the changed areas here.")
        card.add(self.summary)
        self.filter = QComboBox()
        for label, _ in FILTERS:
            self.filter.addItem(label)
        self.filter.currentIndexChanged.connect(lambda _: self._fill())
        form = Form()
        form.row("Show", self.filter)
        card.add(form)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Change", "Volume", "Tag", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.AscendingOrder)  # Qt starts with descending: show area 1 first
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(260)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selected)
        card.add(self.table)
        layout.addWidget(card)

        self.detail_card = Card("Selected area")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        self.detail_card.add(self.detail)
        form = Form()
        self.tag = QComboBox()
        self.tag.addItems([t or "–" for t in TAGS])
        self.tag.activated.connect(lambda i: self._edit("tag", TAGS[i]))
        form.row("Tag", self.tag)
        self.status = QComboBox()
        self.status.addItems([s or "–" for s in STATUSES])
        self.status.activated.connect(lambda i: self._edit("status", STATUSES[i]))
        form.row("Status", self.status)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("For example: diver check planned")
        self.comment.editingFinished.connect(lambda: self._edit("comment", self.comment.text().strip()))
        form.row("Comment", self.comment)
        self.detail_card.add(form)
        from viewer.widgets import button

        self.not_move_button = button("Not a move", tooltip="These are two separate changes: something removed "
                                                           "here and something added there")
        self.not_move_button.clicked.connect(lambda: self.current is not None and self.on_not_move
                                             and self.on_not_move(self.current))
        self.not_move_button.setVisible(False)
        self.detail_card.add(self.not_move_button)
        self.detail_card.add(hint("Tags, status and comments are saved in the project and listed in the report. "
                                  "Areas tagged False alarm are left out of the volume totals."))
        self.detail_card.setVisible(False)
        layout.addWidget(self.detail_card)

        # A scan series compared with its first scan: the same area in every scan
        self.time_card = Card("Through time")
        self.time_summary = hint()
        self.time_card.add(self.time_summary)
        self.time_table = QTableWidget(0, 4)
        self.time_table.setHorizontalHeaderLabels(["#", "Trend", "Now", "Rate"])
        self.time_table.verticalHeader().hide()
        self.time_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.time_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.time_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.time_table.setShowGrid(False)
        header = self.time_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.time_table.cellClicked.connect(self._track_clicked)
        self.time_card.add(self.time_table)
        self.time_card.add(hint("Click an area for its chart: volume and depth in every scan."))
        self.time_card.setVisible(False)
        layout.addWidget(self.time_card)
        layout.addStretch()

    # Filling

    def show_areas(self, areas, summary="", moves=(), overview=False):
        self.overview = overview
        self.areas = list(areas or [])
        self.moves = list(moves or [])
        for area in self.areas:
            area._move = None
        for move in self.moves:  # both areas of a moved object point to it; only "where it was" is listed
            self.areas[move.removed]._move = move
            if move.added != move.removed:
                self.areas[move.added]._move = move
        if not self.areas:
            self.summary.setText(summary or "Run Detect Changes to list the changed areas here.")
        else:
            counts = {}
            for area in self.areas:
                key = area.status or "Open"
                counts[key] = counts.get(key, 0) + 1
            parts = ", ".join(f"{n} {k.lower()}" for k, n in sorted(counts.items()))
            text = f"{len(self.areas)} areas: {parts}. Click one to fly there."
            if self.overview:
                from large_scans import measured

                done = sum(1 for area in self.areas if measured(area) == "full detail")
                text += (f"<br>✓ measured with every point ({done} of {len(self.areas)}) · "
                         f"≈ value from the overview, not measured in full detail yet")
            self.summary.setText(text)
        self._fill()

    def _fill(self):
        keep = FILTERS[self.filter.currentIndex()][1]
        selected = self.current
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for index, area in enumerate(self.areas):
            move = getattr(area, "_move", None)
            if not keep(area) or (move is not None and index == move.added != move.removed):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            number = NumberItem(str(index + 1), index)
            number.setData(Qt.UserRole, index)
            kind = QTableWidgetItem(area.kind + ("?" if area.confidence not in (None, "clear") else ""))
            kind.setForeground(ADDED if area.kind == "added" else REMOVED)
            volume = NumberItem(area_volume_text(area).split(" ±")[0], area.volume)
            if move is not None:
                kind = QTableWidgetItem("moved" + ("?" if move.confidence != "clear" else ""))
                kind.setForeground(MOVED)
                volume = NumberItem(f"{move.distance:.1f} m", move.distance)
            from large_scans import MARKS, measured

            where = measured(area, self.overview)
            if where:
                kind.setText(f"{kind.text()} {MARKS[where]}")
                kind.setToolTip({"full detail": "Measured with every point (full detail)",
                                 "overview": "Value from the overview: not measured in full detail yet",
                                 "not in full detail": "Seen on the overview, but not there in full detail"}[where])
            items = [number, kind, volume, QTableWidgetItem(area.tag), QTableWidgetItem(area.status)]
            if area.tag == "False alarm":
                for item in items:
                    item.setForeground(QColor(style.TEXT_FAINT))
            for column, item in enumerate(items):
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        if selected is not None:
            self.select(selected, notify=False)

    def select(self, index, notify=True):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == index:
                self.table.blockSignals(not notify)
                self.table.selectRow(row)
                self.table.blockSignals(False)
                self._show_detail(index)
                return

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        index = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        self._show_detail(index)
        self.on_select(index)

    def _show_detail(self, index):
        self.current = index
        area = self.areas[index]
        length, width, height = area.size
        volume = area_volume_text(area) or "not measured"
        sure = {"clear": "clearly real", "likely": "likely real", "uncertain": "close to the noise"}.get(area.confidence, "")
        text = (f"<b>Area {index + 1}: {area.kind}</b> {sure}<br>"
                f"<span style='color:{style.TEXT_DIM}'>Up to {area.peak:+.2f} m · {volume} · "
                f"{length:.1f} × {width:.1f} × {height:.1f} m · {area.n_points:,} points</span>")
        move = getattr(area, "_move", None)
        if move is not None:
            from displaced import describe

            sure = {"clear": "the same shape fits closely", "likely": "the shape fits well",
                    "possible": "the shape fits partly (it turned and shows other sides)"}[move.confidence]
            size = " × ".join(f"{v:.1f}" for v in move.size)
            text = (f"<b>Area {move.removed + 1}: moved object</b><br>{describe(move)}<br>"
                    f"<span style='color:{style.TEXT_DIM}'>About {size} m · {sure} (within {move.fit:.0f} cm). "
                    + (f"Now at area {move.added + 1}." if move.added != move.removed
                       else "It moved less than its own size.") + "</span>")
        if getattr(area, "part", ""):
            text += f"<br><span style='color:{style.TEXT_DIM}'>On: {area.part}</span>"
        detail = getattr(area, "detail", None)
        if getattr(area, "detail_only", False):
            text += f"<br><span style='color:{style.TEXT_DIM}'>Found in full detail (too small for the overview).</span>"
        elif detail and detail > 0:
            text += f"<br><span style='color:{style.TEXT_DIM}'>✓ Measured in full detail ({detail:,} points).</span>"
        elif detail == -1:
            text += f"<br><span style='color:{style.TEXT_DIM}'>✗ Seen on the overview, but not there in full detail.</span>"
        elif self.overview:
            text += (f"<br><span style='color:{style.TEXT_DIM}'>≈ Values from the overview: not measured in full detail "
                     "yet.</span>")
        self.detail.setText(text)
        self.not_move_button.setVisible(move is not None)
        self.tag.setCurrentIndex(TAGS.index(area.tag) if area.tag in TAGS else 0)
        self.status.setCurrentIndex(STATUSES.index(area.status) if area.status in STATUSES else 0)
        self.comment.setText(area.comment)
        self.detail_card.setVisible(True)

    # Through time

    def show_tracks(self, tracks, names, dates):
        """Areas followed through a scan series (empty hides the card)."""
        from viewer.trend import Sparkline, rate_text, track_color
        from volumes import format_volume

        self.tracks = list(tracks) if names else []
        self.time_card.setVisible(bool(self.tracks))
        self.time_table.setRowCount(0)
        if not self.tracks:
            return
        count = len(names)
        growing = sum(1 for t in self.tracks if abs(t.volumes(count)[-1]) > abs(t.volumes(count)[max(count - 2, 0)]))
        self.time_summary.setText(f"{len(self.tracks)} areas followed through all {count} scans"
                                  f" (compared with {names[0]}) · {growing} still growing")
        for row, track in enumerate(self.tracks):
            self.time_table.insertRow(row)
            volumes = track.volumes(count)
            number = QTableWidgetItem(str(track.number))
            number.setData(Qt.UserRole, track.number)
            number.setForeground(QColor(track_color(track)))
            now = volumes[-1]
            self.time_table.setItem(row, 0, number)
            self.time_table.setItem(row, 1, QTableWidgetItem(""))
            self.time_table.setCellWidget(row, 1, Sparkline(volumes, track_color(track)))
            self.time_table.setItem(row, 2, QTableWidgetItem(f"{'+' if now >= 0 else '−'}{format_volume(abs(now))}"))
            self.time_table.setItem(row, 3, QTableWidgetItem(rate_text(track, count, dates) or "–"))
        rows = sum(self.time_table.rowHeight(r) for r in range(self.time_table.rowCount()))
        self.time_table.setFixedHeight(self.time_table.horizontalHeader().height() + rows + 6)

    def _track_clicked(self, row, column):
        item = self.time_table.item(row, 0)
        if item is not None and self.on_track is not None:
            self.on_track(item.data(Qt.UserRole))

    def _edit(self, field, value):
        if self.current is None or getattr(self.areas[self.current], field) == value:
            return
        self.on_edit(self.current, field, value)
