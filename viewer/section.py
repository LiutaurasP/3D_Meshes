"""Cross section: the shape of scan A and scan B along a line drawn on the scene.

Points within a narrow corridor around the vertical plane through the line
are shown from the side (distance along the line vs height), the way
inspectors compare two scans of a scour hole or a sand bank.
"""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from viewer.style import BACKGROUND, CARD, CARD_BORDER, PANEL_STYLE, TEXT, TEXT_DIM


def section_points(points, start, end, half_width):
    """(distance along the line, height) of the points close to the vertical plane through start-end."""
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    direction = end[:2] - start[:2]
    length = np.linalg.norm(direction)
    if length < 1e-6:
        return np.empty(0), np.empty(0), 0.0
    direction /= length
    offset = points[:, :2] - start[:2]
    along = offset @ direction
    across = offset @ np.array([-direction[1], direction[0]])
    keep = (np.abs(across) <= half_width) & (along >= 0) & (along <= length)
    return along[keep], points[keep, 2], length


def binned_profile(distance, height, length, step):
    """Median height per step along the line (NaN where there are no points)."""
    edges = np.arange(0.0, length + step, step)
    centers = (edges[:-1] + edges[1:]) / 2
    index = np.digitize(distance, edges) - 1
    medians = np.full(len(centers), np.nan)
    for i in range(len(centers)):
        values = height[index == i]
        if len(values):
            medians[i] = np.median(values)
    return centers, medians


def compute_section(points_a, points_b, start, end, half_width=None):
    """Everything the chart needs, also used by tests."""
    length = float(np.linalg.norm(np.asarray(end)[:2] - np.asarray(start)[:2]))
    if half_width is None:
        half_width = max(0.15, length / 150)  # a narrow corridor, wider for long lines
    da, za, _ = section_points(points_a, start, end, half_width)
    db, zb, _ = section_points(points_b, start, end, half_width)
    step = max(length / 120, 0.05)
    centers, median_a = binned_profile(da, za, length, step)
    _, median_b = binned_profile(db, zb, length, step)
    difference = median_b - median_a
    valid = ~np.isnan(difference)
    biggest = None
    if valid.any():
        i = np.nanargmax(np.abs(difference))
        biggest = (float(centers[i]), float(difference[i]))
    return {"a": (da, za), "b": (db, zb), "length": length, "centers": centers,
            "median_a": median_a, "median_b": median_b, "difference": difference, "biggest": biggest,
            "half_width": half_width}


class SectionWindow(QDialog):
    """Floating window with the cross section chart (stays open while you keep working)."""

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle("Cross Section")
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.resize(820, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.RichText)
        layout.addWidget(self.summary)
        self.figure = Figure(facecolor=BACKGROUND)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)

    def show_section(self, section, color_a, color_b):
        figure = self.figure
        figure.clear()
        ax = figure.add_subplot(111)
        ax.set_facecolor(CARD)
        for side in ax.spines.values():
            side.set_color(CARD_BORDER)
        ax.tick_params(colors=TEXT_DIM, labelsize=9)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.grid(True, color=CARD_BORDER, linewidth=0.6)

        (da, za), (db, zb) = section["a"], section["b"]
        ax.scatter(da, za, s=3, color=color_a[:3], alpha=0.55, linewidths=0, label="Scan A (before)")
        ax.scatter(db, zb, s=3, color=color_b[:3], alpha=0.55, linewidths=0, label="Scan B (after)")
        ax.plot(section["centers"], section["median_a"], color=color_a[:3], linewidth=1.6)
        ax.plot(section["centers"], section["median_b"], color=color_b[:3], linewidth=1.6)
        a, b = section["median_a"], section["median_b"]
        ax.fill_between(section["centers"], a, b, where=b < a, color="#4a7bd8", alpha=0.25, interpolate=True)
        ax.fill_between(section["centers"], a, b, where=b > a, color="#d84a4a", alpha=0.25, interpolate=True)
        ax.set_xlabel("Distance along the line (m)")
        ax.set_ylabel("Height (m, 0 = water surface)")
        ax.set_xlim(0, section["length"])
        legend = ax.legend(loc="best", fontsize=9, facecolor=CARD, edgecolor=CARD_BORDER)
        for text in legend.get_texts():
            text.set_color(TEXT)
        figure.tight_layout()
        self.canvas.draw()

        detail = f"{section['length']:.1f} m long, corridor ±{section['half_width']:.2f} m · " \
                 f"{len(da):,} + {len(db):,} points"
        if section["biggest"] is not None:
            where, how_much = section["biggest"]
            kind = "higher" if how_much > 0 else "lower"
            detail += f" · biggest difference: B is <b>{abs(how_much):.2f} m {kind}</b> at {where:.1f} m"
        self.summary.setText(f"<span style='color:{TEXT_DIM}'>{detail}</span><br>"
                             f"<span style='color:#d86a6a'>red</span> = material added, "
                             f"<span style='color:#6a8fd8'>blue</span> = material removed")
        self.show()
        self.raise_()
