"""Height difference map: the scene from above, coloured by how much higher or lower B is than A."""

import io

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import TwoSlopeNorm
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from viewer.style import BACKGROUND, CARD, CARD_BORDER, PANEL_STYLE, TEXT, TEXT_DIM
from volumes import height_difference_grid


def compute_map(points_a, points_b, offset, lod=None, max_cells=400):
    grid, extent, cell = height_difference_grid(points_a, points_b, max_cells=max_cells)
    if lod:
        grid = np.where(np.abs(grid) < lod, 0.0, grid)  # inside the noise: shown as unchanged
    extent = [extent[0] + offset[0], extent[1] + offset[0], extent[2] + offset[1], extent[3] + offset[1]]
    return grid, extent, cell


def draw_map(figure, grid, extent, cell, areas=(), offset=(0, 0, 0), dark=True):
    """Draw onto a matplotlib figure (dark for the app, light for the PDF report)."""
    face, ink, dim, edge = (CARD, TEXT, TEXT_DIM, CARD_BORDER) if dark else ("white", "#1d2230", "#6b7080", "#d9dce3")
    figure.clear()
    figure.set_facecolor(BACKGROUND if dark else "white")
    ax = figure.add_subplot(111)
    ax.set_facecolor(face)
    # Colour range from the typical size of the real changes, so a 70 cm scour still
    # shows up next to a 2.5 m container (bigger values are drawn in the darkest colour)
    changed = np.abs(grid[np.isfinite(grid) & (grid != 0)])
    limit = float(np.percentile(changed, 75)) if changed.size else 1.0
    limit = max(limit, 0.05)
    image = ax.imshow(grid, origin="lower", extent=extent, cmap="RdBu_r",
                      norm=TwoSlopeNorm(vcenter=0, vmin=-limit, vmax=limit), interpolation="nearest")
    for number, area in enumerate(areas[:20], start=1):
        x, y = area.center[0] + offset[0], area.center[1] + offset[1]
        ax.annotate(str(number), (x, y), color=ink, fontsize=8, ha="center", va="center", weight="bold",
                    bbox=dict(boxstyle="circle,pad=0.2", fc=face, ec=edge, alpha=0.85))
    ax.set_aspect("equal")
    ax.set_xlabel("x / easting (m)", color=dim)
    ax.set_ylabel("y / northing (m)", color=dim)
    ax.tick_params(colors=dim, labelsize=8)
    ax.ticklabel_format(useOffset=False, style="plain")
    for side in ax.spines.values():
        side.set_color(edge)
    bar = figure.colorbar(image, ax=ax, fraction=0.04, pad=0.02, extend="both")
    bar.set_label("B minus A (m): red higher, blue lower", color=dim)
    bar.ax.tick_params(colors=dim, labelsize=8)
    bar.outline.set_edgecolor(edge)
    figure.tight_layout()


def map_image(grid, extent, cell, areas=(), offset=(0, 0, 0), width_px=1600):
    """The map as a QImage (light colours, for the PDF report), shaped like the site."""
    shape = (extent[3] - extent[2]) / max(extent[1] - extent[0], 1e-6)
    figure = Figure(figsize=(8, min(max(8 * shape * 0.9 + 1.0, 2.8), 7.5)), dpi=width_px / 8)
    draw_map(figure, grid, extent, cell, areas, offset, dark=False)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=width_px / 8)
    return QImage.fromData(buffer.getvalue())


class HeightMapWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle("Height Difference Map")
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.resize(860, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.figure = Figure(facecolor=BACKGROUND)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.save = QPushButton("Save as Image…")
        self.save.clicked.connect(self._save)
        row.addWidget(self.save)
        layout.addLayout(row)
        self.last = None

    def show_map(self, grid, extent, cell, areas, offset, lod):
        self.last = (grid, extent, cell, areas, offset)
        draw_map(self.figure, grid, extent, cell, areas, offset, dark=True)
        self.canvas.draw()
        noise = f" Differences smaller than the level of detection ({lod * 100:.1f} cm) are shown as 0." if lod else ""
        self.summary.setText(f"<span style='color:{TEXT_DIM}'>Seen from above, {cell:.2f} m cells. "
                             f"Numbers are the changed areas.{noise} Vertical walls are better judged "
                             f"in 3D or with a cross section.</span>")
        self.show()
        self.raise_()

    def _save(self):
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "Save Map", str(Path.home() / "height difference.png"),
                                              "PNG image (*.png)")
        if path and self.last:
            figure = Figure(figsize=(10, 6.5), dpi=200)
            draw_map(figure, *self.last, dark=False)
            figure.savefig(path, dpi=200)
