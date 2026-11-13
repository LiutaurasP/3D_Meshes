"""Change report as a PDF: summary, pictures of the scene and of every big change, table, notes.

Drawn with Qt's own PDF writer, so no extra packages are needed.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from viewer.branding import APP_NAME, LOGO_PATH, VERSION

NAVY = QColor("#0d162c")
INK = QColor("#1d2230")
DIM = QColor("#6b7080")
LINE = QColor("#d9dce3")
ADDED = QColor("#c0392b")
REMOVED = QColor("#2f6fd0")

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 42.0


# Collecting what goes into the report (plain data, also used by the tests)


def measured_where(window, area):
    from large_scans import measured

    overview = getattr(window, "overview_shown", lambda: False)()
    return measured(area, overview)


def collect(window):
    """Everything the report says, as plain values."""
    clouds = window.clouds
    a, b = window.target_name, window.source_name
    offset = np.asarray(getattr(window.inspections, "offset", np.zeros(3)), dtype=float)
    info = {
        "title": window.inspections.title,
        "project": Path(window.project_path).stem if window.project_path else "Unsaved project",
        "date": datetime.now().strftime("%d %B %Y, %H:%M"),
        "source": "Imported scan files" if window.loaded_files else "Example scene (simulated data)",
        "files": [Path(p).name for p in window.loaded_files] if window.loaded_files else [],
        "points": {a: len(clouds[a].points), b: len(clouds[b].points)},
        "names": (a, b),
        "alignment": None,
        "detection": None,
        "areas": [],
        "notes": [{**n, "point": [float(v) for v in np.asarray(n["point"]) + offset]} for n in window.notes],
        "kinds": dict(getattr(window.inspections, "kinds", {}) or {}),
        "details": dict(getattr(window, "report_details", {}) or {}),
        "offset": [float(v) for v in offset],
    }
    steps = window.align_steps
    if steps:
        last = steps[-1]
        info["alignment"] = {"rounds": len(steps) - 1, "rmse": float(last.inlier_rmse), "fitness": float(last.fitness)}
    result = window.change_result
    if result is not None:
        info["detection"] = {
            "threshold": float(result.threshold),
            "auto": bool(window.settings.data.auto_threshold),
            "areas": len(result.areas),
            "changed": int(result.n_changed),
            "share": float(result.share_changed),
            "lod": result.lod,
            "added": sum(a.volume_added or 0 for a in result.areas if a.tag != "False alarm"),
            "removed": sum(a.volume_removed or 0 for a in result.areas if a.tag != "False alarm"),
        }
        from displaced import describe, moved_areas

        moves = getattr(result, "moves", None) or []
        moved = moved_areas(moves)
        counted = [a for i, a in enumerate(result.areas) if a.tag != "False alarm" and i not in moved]
        info["detection"]["added"] = sum(a.volume_added or 0 for a in counted)
        info["detection"]["removed"] = sum(a.volume_removed or 0 for a in counted)
        info["moves"] = [{"where": move.removed + 1, "now": move.added + 1, "text": describe(move),
                          "size": [float(v) for v in move.size], "confidence": move.confidence,
                          "from": [float(v) for v in np.asarray(move.old_center) + offset],
                          "to": [float(v) for v in np.asarray(move.new_center) + offset]} for move in moves]
        parts = getattr(window, "_large_parts", None) or []
        if parts:  # huge scans cut into their parts: what changed on each
            from parts import part_of

            per_part = {}
            for index, area in enumerate(result.areas):
                if area.tag == "False alarm":
                    continue
                part = part_of(parts, area.center)
                name = part.name if part is not None else "Elsewhere"
                entry = per_part.setdefault(name, {"count": 0, "added": 0.0, "removed": 0.0, "moved": 0})
                entry["count"] += 1
                if index in moved:
                    entry["moved"] += index in {m.removed for m in moves}
                else:
                    entry["added"] += area.volume_added or 0
                    entry["removed"] += area.volume_removed or 0
            info["parts"] = [(name, entry) for name, entry in per_part.items()]
        for number, area in enumerate(result.areas, start=1):
            info["areas"].append({
                "number": number,
                "kind": area.kind,
                "peak": float(area.peak),
                "size": [float(v) for v in area.size],
                "center": [float(v) for v in np.asarray(area.center) + offset],
                "points": int(area.n_points),
                "volume": area.volume,
                "volume_error": area.volume_error,
                "confidence": area.confidence,
                "tag": area.tag, "status": area.status, "comment": area.comment,
                "measured": measured_where(window, area),
            })
    pair = window.large_pair() if hasattr(window, "large_pair") else None
    if pair is not None and not window.in_large_detail():  # huge scans: say what the numbers are based on
        from large_scans import measured

        stored = {name: store.n_points for name, store in pair.stores.items()}
        info["large"] = {"stored": stored, "cell": pair.cell,
                         "measured": sum(1 for a in info["areas"] if a.get("measured") == "full detail")}
        for area in info["areas"]:
            area.setdefault("measured", "overview")
    info["series"] = collect_series(window)
    return info


def collect_series(window):
    """The scan series and its areas followed through time (None without a series)."""
    series = getattr(window, "series", None)
    if series is None:
        return None
    from series_analysis import format_date
    from viewer.trend import ESTIMATE_MONTHS

    count = len(series.names)
    dates = list(series.dates) + [None] * (count - len(series.dates))
    tracks = []
    for track in getattr(window, "series_tracks", []):
        seen = track.first_seen()
        tracks.append({
            "number": track.number,
            "kind": track.kind,
            "volumes": track.volumes(count),
            "depths": track.depths(count),
            "first_seen": series.names[seen],
            "rate": track.rate(dates, count),
            "estimate": track.estimate(dates, count, ESTIMATE_MONTHS),
        })
    return {
        "names": list(series.names),
        "dates": [format_date(d) for d in dates],
        "points": [len(cloud.points) for cloud in series.clouds],
        "compared": len(window.first_comparisons()),
        "tracks": tracks,
        "estimate_months": ESTIMATE_MONTHS,
    }


def chart_image(track, names, dates, width_px=1400):
    """The chart of one area through time as a QImage (light colours, for paper)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from viewer.trend import trend_chart

    figure = Figure(figsize=(7.2, 4.0), dpi=width_px / 7.2)
    trend_chart(figure, track, names, dates, dark=False)
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    pixels = np.asarray(canvas.buffer_rgba())
    height, width, _ = pixels.shape
    return QImage(pixels.tobytes(), width, height, 4 * width, QImage.Format_RGBA8888).copy()


def snapshot(scene):
    """The 3D view as a QImage."""
    scene.plotter.renderer.ResetCameraClippingRange()
    scene.plotter.ren_win.Render()  # the plotter's own render() is deferred to the event loop
    pixels = np.ascontiguousarray(scene.plotter.screenshot(return_img=True)[:, :, :3])
    height, width, _ = pixels.shape
    return QImage(pixels.data, width, height, 3 * width, QImage.Format_RGB888).copy()


def pictures(window, max_areas=6):
    """Overview of the whole scene and a close-up of the biggest changed areas."""
    scene = window.scene
    before = scene.current_view()
    scene.flight.stop()
    try:
        overview = snapshot(scene)
        close_ups = []
        result = window.change_result
        from viewer.scene import CAMERA_PRESETS

        direction = np.asarray(CAMERA_PRESETS["Iso"], dtype=float)
        direction /= np.linalg.norm(direction)
        for area in (result.areas[:max_areas] if result else []):
            # Far enough back to see the area with some of its surroundings
            reach = max(float(np.linalg.norm(area.size)) * 3.5, 0.15 * scene.size(), 3.0)
            center = np.asarray(area.center, dtype=float)
            scene.go_to_view({"position": center + direction * reach, "focal_point": center,
                              "up": (0.0, 0.0, 1.0)}, animate=False)
            close_ups.append(snapshot(scene))
    finally:
        scene.go_to_view(before, animate=False)
    return overview, close_ups


# Drawing the PDF


class Pages:
    """A4 pages with a cursor that moves down; starts a new page when something does not fit."""

    def __init__(self, path, title):
        self.writer = QPdfWriter(str(path))
        self.writer.setTitle(title)
        self.writer.setCreator(f"{APP_NAME} {VERSION}")
        self.writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
        self.writer.setResolution(72)  # one unit = one point
        self.painter = QPainter(self.writer)
        self.page = 1
        self.y = MARGIN
        self._footer()

    def font(self, size, bold=False, color=INK):
        font = QFont("Helvetica", 1)
        font.setPointSizeF(size)
        font.setBold(bold)
        self.painter.setFont(font)
        self.painter.setPen(color)

    def need(self, height):
        if self.y + height > PAGE_H - MARGIN - 18:
            self.new_page()

    def new_page(self):
        self.writer.newPage()
        self.page += 1
        self.y = MARGIN
        self._footer()

    def _footer(self):
        self.font(7.5, color=DIM)
        self.painter.drawText(QRectF(MARGIN, PAGE_H - MARGIN + 6, PAGE_W - 2 * MARGIN, 12), Qt.AlignLeft,
                              f"{APP_NAME} {VERSION}")
        self.painter.drawText(QRectF(MARGIN, PAGE_H - MARGIN + 6, PAGE_W - 2 * MARGIN, 12), Qt.AlignRight,
                              f"Page {self.page}")

    def text(self, value, size=10, bold=False, color=INK, x=MARGIN, width=None, gap=4):
        width = width or PAGE_W - MARGIN - x
        self.font(size, bold, color)
        bounds = self.painter.boundingRect(QRectF(x, 0, width, 10000), Qt.TextWordWrap, value)
        self.need(bounds.height())
        self.painter.drawText(QRectF(x, self.y, width, bounds.height()), Qt.TextWordWrap, value)
        self.y += bounds.height() + gap

    def heading(self, value, keep=0):
        """keep: height of what follows, so a heading never ends up alone at the bottom of a page."""
        self.need(40 + keep)
        self.y += 10
        self.text(value, 13, bold=True, gap=3)
        self.painter.setPen(QPen(LINE, 0.8))
        self.painter.drawLine(MARGIN, self.y, PAGE_W - MARGIN, self.y)
        self.y += 8

    def image(self, image, x, width, height):
        """Draw the image filling width x height (cropped to that shape), with a thin frame."""
        target = QRectF(x, self.y, width, height)
        ratio = width / height
        w, h = image.width(), image.height()
        if w / h > ratio:
            crop = QRectF((w - h * ratio) / 2, 0, h * ratio, h)
        else:
            crop = QRectF(0, (h - w / ratio) / 2, w, w / ratio)
        self.painter.drawImage(target, image, crop)
        self.painter.setPen(QPen(LINE, 0.8))
        self.painter.drawRect(target)

    def finish(self):
        self.painter.end()


def facts_table(pages, rows):
    """Two columns: label, value."""
    for label, value in rows:
        pages.need(16)
        top = pages.y
        pages.text(label, 9.5, color=DIM, width=150, gap=0)
        pages.y = top
        pages.text(value, 9.5, x=MARGIN + 160, gap=5)


def areas_table(pages, areas, names):
    columns = [("#", 20), ("Change", 56), ("Biggest", 48), ("Volume (m³)", 84), ("Size x × y × z (m)", 92),
               ("Centre x, y (m)", 122), ("Depth", 0)]
    widths = [w for _, w in columns]
    widths[-1] = PAGE_W - 2 * MARGIN - sum(widths[:-1])

    def header():
        pages.need(40)
        x = MARGIN
        pages.font(8.5, bold=True, color=DIM)
        for (label, _), width in zip(columns, widths):
            pages.painter.drawText(QRectF(x, pages.y, width, 14), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += width
        pages.y += 16
        pages.painter.setPen(QPen(LINE, 0.8))
        pages.painter.drawLine(MARGIN, pages.y, PAGE_W - MARGIN, pages.y)
        pages.y += 3

    header()
    for area in areas:
        if pages.y + 16 > PAGE_H - MARGIN - 18:
            pages.new_page()
            header()
        sx, sy, sz = area["size"]
        cx, cy, cz = area["center"]
        kind = "added" if area["kind"] == "added" else "removed"
        volume = ""
        if area.get("volume") is not None:
            from volumes import format_volume

            volume = ("+" if area["volume"] >= 0 else "−") + format_volume(area["volume"]).replace(" m³", "")
            if area.get("volume_error"):
                volume += f" ± {format_volume(area['volume_error']).replace(' m³', '')}"
        if area.get("confidence") and area["confidence"] != "clear":
            kind = f"{kind}?"
        from large_scans import MARKS

        mark = MARKS.get(area.get("measured") or "", "")
        kind = f"{kind} {mark}" if mark else kind
        values = [str(area["number"]), kind, f"{area['peak'] * 100:+.0f} cm", volume,
                  f"{sx:.1f} × {sy:.1f} × {sz:.1f}", f"{cx:.1f}, {cy:.1f}", f"{-cz:.1f} m"]
        x = MARGIN
        for index, (value, width) in enumerate(zip(values, widths)):
            color = (ADDED if kind.startswith("added") else REMOVED) if index == 1 else INK
            pages.font(9, bold=index == 1, color=color)
            pages.painter.drawText(QRectF(x, pages.y, width, 15), Qt.AlignLeft | Qt.AlignVCenter, value)
            x += width
        pages.y += 15
        pages.painter.setPen(QPen(LINE, 0.4))
        pages.painter.drawLine(MARGIN, pages.y, PAGE_W - MARGIN, pages.y)
        pages.y += 1


def simple_table(pages, columns, rows, colors=None):
    """columns: [(label, width)], the last width 0 = the rest of the line. rows: lists of text."""
    widths = [w for _, w in columns]
    widths[-1] = PAGE_W - 2 * MARGIN - sum(widths[:-1])

    def header():
        pages.need(40)
        x = MARGIN
        pages.font(8.5, bold=True, color=DIM)
        for (label, _), width in zip(columns, widths):
            pages.painter.drawText(QRectF(x, pages.y, width, 14), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += width
        pages.y += 16
        pages.painter.setPen(QPen(LINE, 0.8))
        pages.painter.drawLine(MARGIN, pages.y, PAGE_W - MARGIN, pages.y)
        pages.y += 3

    header()
    for number, row in enumerate(rows):
        if pages.y + 16 > PAGE_H - MARGIN - 18:
            pages.new_page()
            header()
        x = MARGIN
        for index, (value, width) in enumerate(zip(row, widths)):
            color = (colors[number] if colors and index == 1 else INK)
            pages.font(9, bold=bool(colors) and index == 1, color=color)
            pages.painter.drawText(QRectF(x, pages.y, width, 15), Qt.AlignLeft | Qt.AlignVCenter, value)
            x += width
        pages.y += 15
        pages.painter.setPen(QPen(LINE, 0.4))
        pages.painter.drawLine(MARGIN, pages.y, PAGE_W - MARGIN, pages.y)
        pages.y += 1


def series_chapter(pages, series, charts):
    """Change over time: the scans with their dates, every area followed through them, and its chart."""
    from volumes import format_volume

    def signed(value):
        return ("+" if value >= 0 else "−") + format_volume(abs(value))

    pages.heading("Change over time", keep=120)
    count = len(series["names"])
    pages.text(f"The same place was scanned {count} times. Every scan was aligned with the first one and compared "
               f"with it, so the volumes add up over time: they are the change since {series['names'][0]}.",
               9, color=DIM, gap=8)
    simple_table(pages, [("Scan", 30), ("Name", 230), ("Date", 110), ("Points", 0)],
                 [[str(k + 1), name, series["dates"][k] or "–", f"{series['points'][k]:,}"]
                  for k, name in enumerate(series["names"])])
    if series["compared"] < count - 1:
        pages.y += 6
        pages.text(f"Only {series['compared']} of {count - 1} scans were compared with the first one. "
                   f"Use Align and compare all in the Scans card to follow every area through time.", 9, color=DIM)
        return
    tracks = series["tracks"]
    if not tracks:
        pages.y += 6
        pages.text("No area changed in a way that could be followed through the scans.", 9, color=DIM)
        return
    pages.y += 10
    dated = all(series["dates"])
    columns = [("#", 20), ("Change", 60), ("First seen in", 150), ("Volume now", 80), ("Per month", 80),
               (f"In {series['estimate_months']} months*", 0)]
    rows, colors = [], []
    for track in tracks:
        rows.append([str(track["number"]), track["kind"], track["first_seen"], signed(track["volumes"][-1]),
                     signed(track["rate"]) if track["rate"] is not None else "–",
                     signed(track["estimate"]) if track["estimate"] is not None else "–"])
        colors.append(ADDED if track["kind"] == "added" else REMOVED)
    simple_table(pages, columns, rows, colors)
    pages.y += 4
    if dated:
        pages.text(f"Per month: from the last two scans. * Estimate: what the volume would be "
                   f"{series['estimate_months']} months after the last scan if it keeps changing at the same rate. "
                   f"It is a simple projection, not a prediction: storms, maintenance or settling can change it.",
                   8.5, color=DIM)
    else:
        pages.text("Rates per month need a date for every scan (enter them in the Scans card).", 8.5, color=DIM)

    width = PAGE_W - 2 * MARGIN
    for index, image in enumerate(charts):
        height = width * image.height() / max(image.width(), 1)
        pages.need(height + 12)
        if index == 0:
            pages.y += 8
        pages.image(image, MARGIN, width, height)
        pages.y += height + 10


def write_pdf(path, info, overview, close_ups, height_map=None, series_charts=None, wall_map=None):
    pages = Pages(path, f"Change report – {info['title']}")
    painter = pages.painter

    # Title band
    painter.fillRect(QRectF(0, 0, PAGE_W, 128), NAVY)
    logo = QImage(str(LOGO_PATH))
    if not logo.isNull():
        height = 26
        painter.drawImage(QRectF(MARGIN, 34, logo.width() * height / logo.height(), height), logo)
    pages.y = 72
    pages.text("Change Report", 22, bold=True, color=QColor("white"), gap=2)
    subtitle = " · ".join(v for v in (info.get("details", {}).get("site"), info["title"]) if v)
    pages.text(f"{subtitle}  ·  {info['date']}", 10, color=QColor("#b8bccb"))
    pages.y = 128 + 22

    a, b = info["names"]
    details = info.get("details", {})
    rows = [(label, details[key]) for key, label in (("client", "Client"), ("site", "Site"),
                                                     ("reference", "Reference"), ("inspector", "Inspector"))
            if details.get(key)]
    rows += [("Project", info["project"]), ("Data", info["source"])]
    if info["files"]:
        kinds = info.get("kinds", {})
        for name, file in zip((a, b), info["files"]):
            rows.append((f"File {name[-1]}", f"{file}" + (f"  ({kinds[name]})" if kinds.get(name) else "")))
    large = info.get("large")
    if large:
        stored = large["stored"]
        rows.append(("Points", f"{a} (before): {stored[a]:,}   ·   {b} (after): {stored[b]:,}"))
        rows.append(("Compared on", f"an overview of one averaged point per {large['cell'] * 100:.0f} cm cube "
                                    f"({info['points'][a]:,} + {info['points'][b]:,} points); "
                                    f"{large['measured']} of {len(info['areas'])} changed areas were measured "
                                    f"again with every point (✓ in the table)"))
    else:
        rows.append(("Points", f"{a} (before): {info['points'][a]:,}   ·   {b} (after): {info['points'][b]:,}"))
    alignment = info["alignment"]
    if alignment:
        rows.append(("Alignment", f"{alignment['rounds']} rounds, remaining error (RMSE) "
                                  f"{alignment['rmse'] * 100:.1f} cm, overlap {alignment['fitness']:.0%}"))
    else:
        rows.append(("Alignment", "Scan B was not aligned to scan A"))
    detection = info["detection"]
    if detection:
        rows.append(("Threshold", f"{detection['threshold'] * 100:.1f} cm" + (" (automatic)" if detection["auto"] else "")))
        rows.append(("Result", f"{detection['areas']} changed area{'s' if detection['areas'] != 1 else ''}, "
                               f"{detection['changed']:,} changed points ({detection['share']:.1%})"))
        if detection.get("lod") is not None:
            from volumes import format_volume

            rows.append(("Volume", f"+{format_volume(detection['added'])} added, "
                                   f"−{format_volume(detection['removed'])} removed"))
            rows.append(("Level of detection", f"{detection['lod'] * 100:.1f} cm (95 %): smaller differences "
                                               f"cannot be told apart from the sonar noise"))
    else:
        rows.append(("Result", "Changes were not detected yet"))
    facts_table(pages, rows)

    if details.get("remarks"):
        pages.y += 6
        pages.text("Remarks", 10.5, bold=True, gap=2)
        pages.text(details["remarks"], 10, gap=4)

    # Overview picture
    pages.y += 8
    height = (PAGE_W - 2 * MARGIN) * 0.56
    pages.need(height + 20)
    pages.image(overview, MARGIN, PAGE_W - 2 * MARGIN, height)
    pages.y += height + 4
    pages.text(info.get("overview_caption", "The scene as shown in the app when the report was made."), 8.5, color=DIM)

    if info["areas"]:
        pages.heading("Changed areas", keep=80)
        pages.text("Sorted by size. Added means new material in the later scan (an object, sediment, a bulge); "
                   "removed means material that is gone (scour, a hole, a missing block). "
                   "Depth is below the water surface.", 9, color=DIM, gap=8)
        areas_table(pages, info["areas"], info["names"])
        if any(a.get("confidence") not in (None, "clear") for a in info["areas"]):
            pages.y += 4
            pages.text("? = the change is close to the level of detection: worth checking again.", 8.5, color=DIM)
        if info.get("large"):
            pages.y += 2
            pages.text("✓ = measured with every point (full detail)   ≈ = value from the overview only   "
                       "✗ = seen on the overview, but not there in full detail", 8.5, color=DIM)
        if info.get("parts"):
            from volumes import format_volume

            pages.heading("Changes per part", keep=60)
            pages.text("The scan was split into its parts automatically (seabed, walls, ships, piles, other "
                       "objects).", 9, color=DIM, gap=8)
            rows = [[name, str(entry["count"]), f"+{format_volume(entry['added'])}",
                     f"−{format_volume(entry['removed'])}", str(entry["moved"]) if entry["moved"] else "–"]
                    for name, entry in info["parts"]]
            simple_table(pages, [("Part", 200), ("Changes", 70), ("Added", 90), ("Removed", 90), ("Moved", 0)], rows)
        if info.get("moves"):
            pages.heading("Moved objects", keep=60)
            pages.text("A block or rock that moved shows up as two changes: removed where it was and added where "
                       "it is now. These pairs were recognised as one object (the same shape fits onto both "
                       "places), so their volume is not counted as added or removed.", 9, color=DIM, gap=8)
            rows = [[str(m["where"]), (f"area {m['now']}" if m["now"] != m["where"] else "–"), m["text"],
                     " × ".join(f"{v:.1f}" for v in m["size"]) + " m", m["confidence"]] for m in info["moves"]]
            simple_table(pages, [("Area", 40), ("Now at", 60), ("Movement", 270), ("Size", 90), ("Fit", 0)], rows)
        inspected = [a for a in info["areas"] if a.get("tag") or a.get("status") or a.get("comment")]
        if inspected:
            pages.heading("Inspection", keep=60)
            for area in inspected:
                pages.need(28)
                label = " · ".join(v for v in (area.get("tag"), area.get("status")) if v)
                top = pages.y
                pages.text(f"Area {area['number']}", 9.5, bold=True, width=60, gap=0)
                pages.y = top
                pages.text(label or "–", 9.5, x=MARGIN + 64, width=150, gap=0)
                pages.y = top
                pages.text(area.get("comment") or "", 9.5, x=MARGIN + 220, gap=6)
            if any(a.get("tag") == "False alarm" for a in inspected):
                pages.text("Areas tagged False alarm are not counted in the volume totals.", 8.5, color=DIM)

    if height_map is not None:
        height = (PAGE_W - 2 * MARGIN) * height_map.height() / max(height_map.width(), 1)
        pages.heading("Height difference map", keep=height + 20)
        pages.image(height_map, MARGIN, PAGE_W - 2 * MARGIN, height)
        pages.y += height + 4
        pages.text("Seen from above: red where scan B is higher (material added), blue where it is lower "
                   "(removed). Numbers are the changed areas. Vertical walls only show as a thin line from above.", 8.5,
                   color=DIM)

    if wall_map is not None:
        width = PAGE_W - 2 * MARGIN
        height = width * wall_map.height() / max(wall_map.width(), 1)
        pages.heading("Unrolled wall view", keep=height + 48)
        pages.image(wall_map, MARGIN, width, height)
        pages.y += height + 4
        pages.text("Distance along the wall is horizontal and depth increases downward. Red shows added material, "
                   "blue shows removed material, and outlines mark detected areas.", 8.5, color=DIM)

    if close_ups:
        width = (PAGE_W - 2 * MARGIN - 14) / 2
        height = width * 0.68
        pages.heading("Close-ups of the biggest changes", keep=height + 26)
        for index, image in enumerate(close_ups):
            column = index % 2
            if column == 0:
                pages.need(height + 26)
            x = MARGIN + column * (width + 14)
            pages.image(image, x, width, height)
            area = info["areas"][index]
            pages.font(9, bold=True, color=ADDED if area["kind"] == "added" else REMOVED)
            painter.drawText(QRectF(x, pages.y + height + 3, width, 14), Qt.AlignLeft,
                             f"Area {area['number']}: {area['kind']} {area['peak'] * 100:+.0f} cm")
            if column == 1 or index == len(close_ups) - 1:
                pages.y += height + 24

    if info.get("series"):
        series_chapter(pages, info["series"], series_charts or [])

    if info["notes"]:
        pages.heading("Notes", keep=40)
        for number, note in enumerate(info["notes"], start=1):
            x, y, z = note["point"]
            pages.need(34)
            top = pages.y
            pages.text(f"{number}.", 10, bold=True, color=QColor("#b85c0f"), width=16, gap=0)
            pages.y = top
            pages.text(note["text"], 10, x=MARGIN + 16, gap=1)
            pages.text(f"at x {x:.1f} m, y {y:.1f} m, depth {-z:.1f} m", 8.5, color=DIM, x=MARGIN + 16, gap=8)

    pages.finish()
    return pages.page


def export_report(window, path):
    """Make the report for the window's current state; returns the number of pages."""
    info = collect(window)
    overview, close_ups = pictures(window)
    height_map = wall_map = None
    if window.change_result is not None:
        from viewer.heightmap import map_image

        grid, extent, cell = window.height_map_data()
        height_map = map_image(grid, extent, cell, window.change_result.areas, window.inspections.offset)
        wall_map = map_image(*window.wall_map_data(), wall=True)
    charts = []
    if info.get("series") and info["series"]["compared"] >= len(window.series.names) - 1:
        charts = [chart_image(track, window.series.names, window.series.dates) for track in window.series_tracks[:6]]
    return write_pdf(path, info, overview, close_ups, height_map, charts, wall_map=wall_map)
