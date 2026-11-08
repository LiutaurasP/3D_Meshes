"""Import Scans dialog: what each file is, which columns hold x / y / z, units and depth direction."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scan_formats import DELIMITERS, UNITS, ImportOptions, probe, sniff_text
from viewer.dialogs import styled
from viewer.widgets import Card, Form, hint, spin

DEPTH_CHOICES = (
    ("Find out automatically", None),
    ("Heights: below the water is negative", False),
    ("Depths: positive numbers going down", True),
)
UNIT_NAMES = {"m": "Metres", "cm": "Centimetres", "mm": "Millimetres", "ft": "Feet (international)",
              "US ft": "US survey feet"}


class TextColumns(QWidget):
    """Preview of a text table with a choice of separator, header lines and columns."""

    def __init__(self, path, layout):
        super().__init__()
        self.path = path
        self.layout_info = layout
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        form = Form()
        self.delimiter = QComboBox()
        for value, name in DELIMITERS.items():
            self.delimiter.addItem(name, "whitespace" if value is None else value)
        self.delimiter.setCurrentIndex(list(DELIMITERS).index(layout.delimiter))
        form.row("Separator", self.delimiter)
        self.skip = form.row("Header lines", spin(0, 1000, layout.skip_rows, 1))
        box.addLayout(form)

        self.table = QTableWidget()
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setFixedHeight(118)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.columns = {}
        for key, label in (("x", "X / Easting"), ("y", "Y / Northing"), ("z", "Z / Depth"), ("intensity", "Intensity")):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(QLabel(label))
            combo = QComboBox()
            column.addWidget(combo)
            row.addLayout(column)
            self.columns[key] = combo
        box.addLayout(row)

        self.delimiter.currentIndexChanged.connect(self._reread)
        self.skip.valueChanged.connect(self._reread)
        self._fill(layout)

    def _reread(self):
        """Separator or header lines changed: show the table as it would now be read."""
        from scan_formats import _split

        delimiter = self.delimiter.currentData()
        delimiter = None if delimiter == "whitespace" else delimiter
        with open(self.path, "r", errors="replace") as handle:
            lines = [line.rstrip("\n") for line, _ in zip(handle, range(400)) if line.strip()]
        skip = int(self.skip.value())
        rows = [_split(line, delimiter) for line in lines[skip:skip + 12]]
        if not rows:
            return
        layout = self.layout_info
        width = max(len(r) for r in rows)
        header = _split(lines[skip - 1], delimiter) if skip and skip <= len(lines) else None
        names = header if header and len(header) == width else [f"Column {i + 1}" for i in range(width)]
        from scan_formats import guess_columns

        layout = type(layout)(delimiter, skip, names, rows, guess_columns(names, rows, width), width)
        self._fill(layout)

    def _fill(self, layout):
        self.table.setColumnCount(layout.n_columns)
        self.table.setRowCount(len(layout.preview))
        self.table.setHorizontalHeaderLabels(layout.names)
        for r, row in enumerate(layout.preview):
            for c, value in enumerate(row[:layout.n_columns]):
                self.table.setItem(r, c, QTableWidgetItem(value))
        for key, combo in self.columns.items():
            combo.blockSignals(True)
            combo.clear()
            if key == "intensity":
                combo.addItem("None", None)
            for index, name in enumerate(layout.names):
                combo.addItem(name, index)
            chosen = layout.columns.get(key)
            combo.setCurrentIndex(combo.findData(chosen) if chosen is not None else 0)
            combo.blockSignals(False)

    def options(self):
        columns = {key: combo.currentData() for key, combo in self.columns.items()}
        if columns.get("intensity") is None:
            columns.pop("intensity", None)
        return {"columns": columns, "delimiter": self.delimiter.currentData(), "skip_rows": int(self.skip.value())}

    def problem(self):
        chosen = [self.columns[k].currentData() for k in "xyz"]
        if len(set(chosen)) < 3:
            return "X, Y and Z must be three different columns"
        return ""


class ImportDialog(QDialog):
    def __init__(self, paths, parent=None):
        """paths: {"Scan A": path, "Scan B": path}"""
        super().__init__(parent)
        styled(self)
        self.setWindowTitle("Import Scans")
        self.setMinimumWidth(640)
        self.paths = dict(paths)
        self.text = {}
        self.probes = {name: probe(path) for name, path in self.paths.items()}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        roles = {"Scan A": "earlier, the reference", "Scan B": "later, compared with A"}
        for name, path in self.paths.items():
            info = self.probes[name]
            card = Card(f"{name} ({roles.get(name, '')})")
            card.add(QLabel(f"<b>{Path(path).name}</b><br><span style='color:#9a9da7'>{info.kind}</span>"))
            if info.error:
                warning = hint(info.error)
                warning.setStyleSheet("color: #e8796b;")
                card.add(warning)
            elif info.layout is not None:
                columns = TextColumns(path, info.layout)
                self.text[name] = columns
                card.add(columns)
            layout.addWidget(card)

        common = Card("Units and depth")
        form = Form()
        self.unit = QComboBox()
        for key in UNITS:
            self.unit.addItem(UNIT_NAMES[key], key)
        form.row("Numbers are in", self.unit)
        self.depth = QComboBox()
        for label, value in DEPTH_CHOICES:
            self.depth.addItem(label, value)
        form.row("Z values are", self.depth, "Automatic: positive values all over are taken as depths")
        self.mesh_points = None
        if any(p.mesh for p in self.probes.values()):
            self.mesh_points = form.row("Points per mesh", spin(10_000, 5_000_000, 300_000, 50_000),
                                        "Meshes are turned into points spread over the surface")
        common.add(form)
        common.add(hint("Very large coordinates (UTM and similar) are handled automatically: the status bar, "
                        "notes and exports keep showing the real survey coordinates."))
        layout.insertWidget(0, common)  # matters for every file, so it comes first
        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.problem = QLabel()
        self.problem.setStyleSheet("color: #e8796b;")
        self.problem.hide()
        outer.addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not any(p.error for p in self.probes.values()))
        self.resize(720, min(860, 380 + 300 * len(self.text)))

    def accept(self):
        for name, columns in self.text.items():
            problem = columns.problem()
            if problem:
                self.problem.setText(f"{name}: {problem}")
                self.problem.show()
                return
        super().accept()

    def options(self):
        """{"Scan A": ImportOptions, "Scan B": ImportOptions}"""
        result = {}
        for name in self.paths:
            values = {"unit": self.unit.currentData(), "depth_down": self.depth.currentData()}
            if self.mesh_points is not None:
                values["mesh_points"] = int(self.mesh_points.value())
            if name in self.text:
                values.update(self.text[name].options())
            result[name] = ImportOptions(**values)
        return result


def default_options(paths):
    """What the dialog would choose without any changes (used when it is not shown)."""
    result = {}
    for name, path in paths.items():
        values = {"depth_down": None}
        info = probe(path)
        if info.layout is not None:
            layout = sniff_text(path)
            values.update(columns=layout.columns, skip_rows=layout.skip_rows,
                          delimiter="whitespace" if layout.delimiter is None else layout.delimiter)
        result[name] = ImportOptions(**values)
    return result
