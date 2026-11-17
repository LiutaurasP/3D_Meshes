"""Squircles: rounded rectangles whose corners curve in smoothly, like Apple's.

A plain rounded rectangle switches from a straight edge to a quarter circle all at once, which
the eye notices as a small kink. A squircle eases into the curve: the corner starts earlier
and its curvature grows gradually (the same corner as Figma's "corner smoothing", which
follows Apple's icons). smoothing 0 is a plain circle arc, 0.6 is about what Apple uses.

    path = squircle(QRectF(0, 0, 300, 120), radius=14)
    painter.drawPath(path)
"""

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath


def _corner(radius, smoothing):
    """The top right corner, with the corner point at (0, 0), coming in from the left and going down.

    Returns the points as [(kind, points)]: a curve from the edge into the arc, the arc (as short
    lines), and a curve out of the arc onto the next edge.
    """
    p = (1 + smoothing) * radius  # how far before the corner the curve starts
    arc = 90 * (1 - smoothing)  # degrees of real circle left in the middle
    alpha = (90 - arc) / 2
    beta = 45 * smoothing
    p3_p4 = radius * math.tan(math.radians(alpha / 2))
    c = p3_p4 * math.cos(math.radians(beta))
    d = c * math.tan(math.radians(beta))
    arc_length = math.sin(math.radians(arc / 2)) * radius * math.sqrt(2)
    b = (p - arc_length - c - d) / 3
    a = 2 * b
    centre = (-radius, radius)
    start_angle = 45 + arc / 2  # degrees, counter-clockwise from 3 o'clock, y up
    end_angle = 45 - arc / 2

    def on_circle(angle):
        r = math.radians(angle)
        return (centre[0] + radius * math.cos(r), centre[1] - radius * math.sin(r))

    first = on_circle(start_angle)
    last = on_circle(end_angle)
    steps = 8
    arc_points = [on_circle(start_angle + (end_angle - start_angle) * i / steps) for i in range(1, steps + 1)]
    return [
        ("move", [(-p, 0.0)]),
        ("cubic", [(-p + a, 0.0), (-p + a + b, 0.0), first]),
        ("lines", arc_points),
        ("cubic", [(0.0, p - a - b), (0.0, p - a), (0.0, p)]),
    ], last


def squircle(rect, radius, smoothing=0.6):
    """QPainterPath of a rectangle with squircle corners."""
    rect = QRectF(rect)
    width, height = rect.width(), rect.height()
    limit = min(width, height) / 2
    radius = max(0.0, min(radius, limit))
    if radius <= 0.5:
        path = QPainterPath()
        path.addRect(rect)
        return path
    # Not enough room for the smoothing: use less of it (as Figma does)
    if (1 + smoothing) * radius > limit:
        smoothing = max(0.0, min(limit / radius - 1, smoothing))
    segments, _ = _corner(radius, smoothing)
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    # Turn the top right corner into each of the four corners (clockwise from the top right)
    corners = [
        (lambda x, y: (right + x, top + y)),  # top right
        (lambda x, y: (right - y, bottom + x)),  # bottom right
        (lambda x, y: (left - x, bottom - y)),  # bottom left
        (lambda x, y: (left + y, top - x)),  # top left
    ]
    path = QPainterPath()
    for number, place in enumerate(corners):
        for kind, points in segments:
            mapped = [QPointF(*place(*point)) for point in points]
            if kind == "move":
                if number == 0:
                    path.moveTo(mapped[0])
                else:
                    path.lineTo(mapped[0])  # the straight edge between two corners
            elif kind == "cubic":
                path.cubicTo(*mapped)
            else:
                for point in mapped:
                    path.lineTo(point)
    path.closeSubpath()
    return path
