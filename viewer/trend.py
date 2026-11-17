"""Changed areas followed through time: a small trend line for the table and a chart window.

The chart is drawn by trend_chart(), so the PDF report can draw the same chart.
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from viewer import style

style.chart_fonts()
from viewer.style import BACKGROUND, CARD, CARD_BORDER, PANEL_STYLE, TEXT, TEXT_DIM

ADDED, REMOVED = style.ADDED, style.REMOVED
ESTIMATE_MONTHS = 6


def track_color(track):
    return ADDED if track.kind == "added" else REMOVED


def scan_positions(dates, count):
    """x positions of the scans: months since the first scan when every scan has a date, else 0, 1, 2 ..."""
    from series_analysis import months_between

    if len(dates) >= count and all(d is not None for d in dates[:count]):
        return [months_between(dates[0], d) for d in dates[:count]], True
    return list(range(count)), False


def track_summary(track, names, dates):
    """One line about a track: where it was first seen, its volume now and how fast it changes."""
    from series_analysis import format_date
    from volumes import format_volume

    count = len(names)
    volumes = track.volumes(count)
    seen = track.first_seen()
    when = format_date(dates[seen]) if seen < len(dates) and dates[seen] is not None else ""
    text = f"first seen in {names[seen]}" + (f" ({when})" if when else "")
    text += f" · now {'+' if volumes[-1] >= 0 else '−'}{format_volume(abs(volumes[-1]))}"
    rate = track.rate(dates, count)
    if rate is not None:
        text += f" · {'+' if rate >= 0 else '−'}{format_volume(abs(rate))} per month"
    return text


def rate_text(track, count, dates):
    from volumes import format_volume

    rate = track.rate(dates, count)
    if rate is None:
        return ""
    return f"{'+' if rate >= 0 else '−'}{format_volume(abs(rate))}/mo"


def trend_chart(figure, track, names, dates, dark=True):
    """Volume and depth of one track for every scan, plus the estimate if it keeps changing like this."""
    from series_analysis import format_date

    count = len(names)
    figure.clear()
    background, card, border, text, dim = (BACKGROUND, CARD, CARD_BORDER, TEXT, TEXT_DIM) if dark else \
        ("white", "white", "#cccccc", "#222222", "#555555")
    figure.set_facecolor(background)
    x, dated = scan_positions(dates, count)
    volumes = track.volumes(count)
    depths = track.depths(count)
    color = track_color(track)
    axes = figure.subplots(2, 1, sharex=True)
    for ax in axes:
        ax.set_facecolor(card)
        for side in ax.spines.values():
            side.set_color(border)
        ax.tick_params(colors=dim, labelsize=9)
        ax.yaxis.label.set_color(dim)
        ax.xaxis.label.set_color(dim)
        ax.grid(True, color=border, linewidth=0.6)
    volume_ax, depth_ax = axes
    volume_ax.plot(x, volumes, color=color, linewidth=2, marker="o", markersize=5)
    volume_ax.axhline(0, color=dim, linewidth=0.8)
    volume_ax.set_ylabel("Volume (m³)")
    estimate = track.estimate(dates, count, ESTIMATE_MONTHS) if dated else None
    if estimate is not None:
        ahead = x[-1] + ESTIMATE_MONTHS
        volume_ax.plot([x[-1], ahead], [volumes[-1], estimate], color=color, linewidth=1.5, linestyle="--")
        falling = estimate < volumes[-1]  # the label goes on the side of the dashed line that is free
        volume_ax.annotate(f"estimate in {ESTIMATE_MONTHS} months\n(if it keeps going like this)", (ahead, estimate),
                           textcoords="offset points", xytext=(-6, -10 if falling else 8), ha="right",
                           va="top" if falling else "bottom", fontsize=8, color=dim)
    depth_ax.bar(x, depths, width=0.6 if not dated else max(0.6, (x[-1] - x[0]) / (4 * count)),
                 color=[color if d else dim for d in depths], alpha=0.85)
    depth_ax.axhline(0, color=dim, linewidth=0.8)
    depth_ax.set_ylabel("Largest change (m)")
    labels = [names[k] + (f"\n{format_date(dates[k])}" if dated else "") for k in range(count)]
    depth_ax.set_xticks(x)
    depth_ax.set_xticklabels(labels, fontsize=8, color=dim)
    title = f"Area {track.number}: {track.kind}"
    volume_ax.set_title(title, color=text, fontsize=11, loc="left")
    figure.tight_layout()
    return figure


class Sparkline(QWidget):
    """A tiny line of the volume in every scan (for the table)."""

    def __init__(self, values, color, parent=None):
        super().__init__(parent)
        self.values = [float(v) for v in values]
        self.color = QColor(color)
        self.setMinimumSize(72, 22)
        self.setToolTip("Volume in every scan, oldest left")

    def paintEvent(self, event):
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h, pad = self.width(), self.height(), 4
        low, high = min(self.values + [0.0]), max(self.values + [0.0])
        span = (high - low) or 1.0
        points = [QPointF(pad + i * (w - 2 * pad) / (len(self.values) - 1),
                          h - pad - (v - low) / span * (h - 2 * pad)) for i, v in enumerate(self.values)]
        zero = h - pad - (0 - low) / span * (h - 2 * pad)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.drawLine(QPointF(pad, zero), QPointF(w - pad, zero))
        painter.setPen(QPen(self.color, 1.8))
        painter.drawPolyline(QPolygonF(points))
        painter.setBrush(self.color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(points[-1], 2.5, 2.5)
        painter.end()


class TrendWindow(QDialog):
    """Floating window with the chart of one area through time (stays open while you keep working)."""

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle("Area Through Time")
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.figure = Figure(facecolor=BACKGROUND)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        self.track = None

    def show_track(self, track, names, dates):
        self.track = track
        trend_chart(self.figure, track, names, dates)
        self.canvas.draw()
        note = ""
        if not (len(dates) >= len(names) and all(d is not None for d in dates[:len(names)])):
            note = "<br>Give every scan a date in the Scans card to see the rate per month and an estimate."
        self.summary.setText(f"<b>Area {track.number}: {track.kind}</b> "
                             f"<span style='color:{TEXT_DIM}'>{track_summary(track, names, dates)}{note}</span>")
        self.show()
        self.raise_()

