"""Draws the app icon (assets/app_icon.png): the "s" of the subdron wordmark,
white on a rounded navy square. Run again after changing colours or sizes."""

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

NAVY = "#0d162c"
SIZE = 1024


def draw(size=SIZE):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.098
    square = QPainterPath()
    square.addRoundedRect(QRectF(margin, margin, size - 2 * margin, size - 2 * margin), size * 0.18, size * 0.18)
    p.fillPath(square, QColor(NAVY))

    # The "s": three straight bars joined by half circles, flat ends top right and bottom left
    stroke = size * 0.098
    left, right = size * 0.31, size * 0.69
    top, bottom = size * 0.335, size * 0.665
    middle = (top + bottom) / 2
    r = (middle - top) / 2
    s = QPainterPath(QPointF(right, top))
    s.lineTo(left + r, top)
    s.arcTo(QRectF(left, top, 2 * r, 2 * r), 90, 180)
    s.lineTo(right - r, middle)
    s.arcTo(QRectF(right - 2 * r, middle, 2 * r, 2 * r), 90, -180)
    s.lineTo(left, bottom)
    pen = QPen(QColor("white"), stroke, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawPath(s)
    p.end()
    return image


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = Path(__file__).with_name("app_icon.png")
    draw().save(str(out))
    print("saved", out)
