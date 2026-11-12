"""Height difference map: the scene from above, coloured by how much higher or lower B is than A."""

import io

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
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


def compute_wall_map(points_a, points_b, result, offset, max_cells=400):
    """Project the signed change measurements onto an elevation of the wall."""
    xy = points_a[:, :2]
    origin = xy.mean(axis=0)
    centered = xy - origin
    _, axes = np.linalg.eigh(centered.T @ centered)
    direction = axes[:, -1]
    if direction[np.argmax(np.abs(direction))] < 0:
        direction = -direction

    def project(points):
        return np.column_stack(((points[:, :2] - origin) @ direction, -points[:, 2] - offset[2]))

    a, b = project(points_a), project(points_b)
    low = np.minimum(a.min(axis=0), b.min(axis=0))
    high = np.maximum(a.max(axis=0), b.max(axis=0))
    cell = max(np.max(high - low) / max_cells, 0.001)
    columns, rows = np.maximum(1, np.ceil((high - low) / cell).astype(int))
    minimum = np.full((rows, columns), np.inf)
    maximum = np.full((rows, columns), -np.inf)
    for points, distances in ((a, result.distance_a), (b, result.distance_b)):
        x, y = ((points - low) / cell).astype(int).T
        indices = (np.clip(y, 0, rows - 1), np.clip(x, 0, columns - 1))
        values = np.where(np.abs(distances) >= (result.lod or result.threshold), distances, 0.0)
        np.minimum.at(minimum, indices, values)
        np.maximum.at(maximum, indices, values)
    grid = np.where(np.abs(minimum) > np.abs(maximum), minimum, maximum)
    grid[~np.isfinite(grid)] = np.nan

    outlines = []
    for area in result.areas:
        corners = np.array([[x, y, z] for x in (area.low[0], area.high[0])
                            for y in (area.low[1], area.high[1]) for z in (area.low[2], area.high[2])])
        projected = project(corners)
        start = projected.min(axis=0)
        outlines.append((*start, *np.maximum(projected.max(axis=0) - start, cell)))

    extent = [0, columns * cell, low[1] + rows * cell, low[1]]
    outlines = [(x - low[0], y, width, height) for x, y, width, height in outlines]
    return grid, extent, cell, outlines


def draw_map(figure, grid, extent, cell, areas=(), offset=(0, 0, 0), dark=True, wall=False, show_colorbar=True):
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
    image = ax.imshow(grid, origin="upper" if wall else "lower", extent=extent, cmap="RdBu_r",
                      norm=TwoSlopeNorm(vcenter=0, vmin=-limit, vmax=limit), interpolation="nearest")
    if wall:
        for x, depth, width, height in areas:
            ax.add_patch(Rectangle((x, depth), width, height, fill=False, edgecolor=ink, linewidth=0.9))
    for number, area in enumerate(areas[:20], start=1):
        if wall:
            x, y, width, height = area
            x, y = x + width / 2, y + height / 2
        else:
            x, y = area.center[0] + offset[0], area.center[1] + offset[1]
        ax.annotate(str(number), (x, y), color=ink, fontsize=8, ha="center", va="center", weight="bold",
                    bbox=dict(boxstyle="circle,pad=0.2", fc=face, ec=edge, alpha=0.85))
    ax.set_aspect("equal")
    ax.set_xlabel("Distance along wall (m)" if wall else "x / easting (m)", color=dim)
    ax.set_ylabel("Depth (m)" if wall else "y / northing (m)", color=dim)
    ax.tick_params(colors=dim, labelsize=8)
    ax.ticklabel_format(useOffset=False, style="plain")
    for side in ax.spines.values():
        side.set_color(edge)
    if show_colorbar:
        bar = figure.colorbar(image, ax=ax, fraction=0.04, pad=0.02, extend="both")
        bar.set_label("Change (m) · red added / blue removed" if wall else "B minus A (m): red higher, blue lower",
                      color=dim)
        bar.ax.tick_params(colors=dim, labelsize=8)
        bar.outline.set_edgecolor(edge)
    figure.tight_layout()


def map_image(grid, extent, cell, areas=(), offset=(0, 0, 0), width_px=1600, wall=False):
    """The map as a QImage (light colours, for the PDF report), shaped like the site."""
    shape = abs(extent[3] - extent[2]) / max(extent[1] - extent[0], 1e-6)
    figure = Figure(figsize=(8, min(max(8 * shape * 0.9 + 1.0, 2.8), 7.5)), dpi=width_px / 8)
    draw_map(figure, grid, extent, cell, areas, offset, dark=False, wall=wall)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=width_px / 8)
    return QImage.fromData(buffer.getvalue())


class HeightMapWindow(QDialog):
    def __init__(self, parent, wall=False):
        super().__init__(parent, Qt.Tool)
        self.wall = wall
        self.setWindowTitle("Unrolled Wall View" if wall else "Height Difference Map")
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.resize(860, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        if not wall:
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
        draw_map(self.figure, grid, extent, cell, areas, offset, wall=self.wall, show_colorbar=not self.wall)
        self.canvas.draw()
        if not self.wall:
            noise = f" Differences smaller than the level of detection ({lod * 100:.1f} cm) are shown as 0." if lod else ""
            summary = (f"Seen from above, {cell:.2f} m cells. Numbers are the changed areas.{noise} "
                       "Vertical walls are better judged in the unrolled wall view or with a cross section.")
            self.summary.setText(f"<span style='color:{TEXT_DIM}'>{summary}</span>")
        self.show()
        self.raise_()

    def _save(self):
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        filename = "unrolled wall.png" if self.wall else "height difference.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save Map", str(Path.home() / filename),
                                              "PNG image (*.png)")
        if path and self.last:
            figure = Figure(figsize=(10, 6.5), dpi=200)
            draw_map(figure, *self.last, dark=False, wall=self.wall)
            figure.savefig(path, dpi=200)
