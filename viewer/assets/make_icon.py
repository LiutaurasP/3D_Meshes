"""Builds the artwork in this folder:
- app_icon.png: the "s" of the subdron wordmark, white on a rounded navy square
- subdron_wordmark.png: the wordmark as white letters on transparent
Run again after changing colours or sizes."""

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




def clean_wordmark(source, target):
    """White "subdron" letters on a transparent background, cut out of the pasted logo
    (which has a navy background and thin frame lines from the screenshot)."""
    image = QImage(str(source)).convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    # Only the letters: bright pixels away from the outer frame
    border = 6
    xs, ys = [], []
    for y in range(border, height - border):
        for x in range(border, width - border):
            if QColor(image.pixel(x, y)).lightness() > 140:
                xs.append(x)
                ys.append(y)
    left, right, top, bottom = min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2
    out = QImage(right - left + 1, bottom - top + 1, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            lightness = QColor(image.pixel(x, y)).lightness()
            alpha = max(0, min(255, int((lightness - 45) * 255 / 190)))
            out.setPixelColor(x - left, y - top, QColor(255, 255, 255, alpha))
    out.save(str(target))
    return out.width(), out.height()


if __name__ == "__main__":
    # python make_icon.py  ->  rebuilds app_icon.png and subdron_wordmark.png
    app = QGuiApplication(sys.argv)
    folder = Path(__file__).parent
    draw().save(str(folder / "app_icon.png"))
    print("icon saved")
    print("wordmark", clean_wordmark(folder / "subdron_logo.png", folder / "subdron_wordmark.png"))
