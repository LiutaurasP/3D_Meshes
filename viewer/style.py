"""Look of the app: one dark theme that looks the same on macOS, Windows and Linux."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

ICONS = (Path(__file__).resolve().parent / "icons").as_posix()  # forward slashes work on Windows too

# Colours
BACKGROUND = "#121317"  # behind the cards
CARD = "#1b1c21"
CARD_BORDER = "#26282e"
FIELD = "#23252b"
FIELD_BORDER = "#31333a"
FIELD_HOVER = "#2b2d34"
TEXT = "#e6e7eb"
TEXT_DIM = "#9a9da7"
TEXT_FAINT = "#62656e"
ACCENT = "#3d7ff5"
ACCENT_HOVER = "#5590f7"
ACCENT_DISABLED = "#27354f"

RADIUS = 8
FIELD_RADIUS = 6


def apply_theme(app):
    """Fusion style with a dark palette, so dialogs and menus match the panel."""
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.Window: BACKGROUND,
        QPalette.WindowText: TEXT,
        QPalette.Base: FIELD,
        QPalette.AlternateBase: CARD,
        QPalette.Text: TEXT,
        QPalette.Button: FIELD,
        QPalette.ButtonText: TEXT,
        QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: CARD,
        QPalette.ToolTipText: TEXT,
        QPalette.PlaceholderText: TEXT_FAINT,
        QPalette.Link: ACCENT_HOVER,
        QPalette.Mid: FIELD_BORDER,
        QPalette.Dark: BACKGROUND,
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(TEXT_FAINT))
    app.setPalette(palette)


PANEL_STYLE = f"""
#panel, #page {{
    background: {BACKGROUND};
}}
QScrollArea {{
    border: none;
    background: {BACKGROUND};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0;
}}
QScrollBar::handle:vertical {{
    background: {FIELD_BORDER};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QLabel {{
    color: {TEXT};
}}

/* Cards */
#card {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: {RADIUS + 2}px;
}}
#cardHeader {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0;
    text-align: left;
}}
#cardHeader:hover {{
    color: {TEXT};
}}
#formLabel {{
    color: {TEXT_DIM};
}}
#description, #hint {{
    color: {TEXT_DIM};
}}
#hint {{
    font-size: 12px;
}}
#axisLabel {{
    color: {TEXT_FAINT};
    font-size: 11px;
    font-weight: 600;
}}
#keycap {{
    color: {TEXT_DIM};
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: 4px;
    padding: 0 6px;
    font-size: 11px;
}}
#divider {{
    background: {CARD_BORDER};
    max-height: 1px;
    min-height: 1px;
}}

/* Buttons */
QPushButton {{
    background: {FIELD};
    color: {TEXT};
    border: 1px solid {FIELD_BORDER};
    border-radius: {FIELD_RADIUS}px;
    padding: 0 12px;
    min-height: 28px;
}}
QPushButton:hover {{
    background: {FIELD_HOVER};
}}
QPushButton:pressed {{
    background: {CARD};
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background: {CARD};
    border-color: {CARD_BORDER};
}}
QPushButton#primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primary:disabled {{
    background: {ACCENT_DISABLED};
    border-color: {ACCENT_DISABLED};
    color: {TEXT_DIM};
}}

/* Settings / Guide switch */
#segment {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: {RADIUS + 1}px;
}}
#segmentButton {{
    background: transparent;
    border: none;
    border-radius: {FIELD_RADIUS}px;
    color: {TEXT_DIM};
    font-weight: 600;
    min-height: 28px;
}}
#segmentButton:hover {{
    color: {TEXT};
}}
#segmentButton:checked {{
    background: {FIELD_HOVER};
    color: {TEXT};
}}

/* Inputs */
QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {FIELD};
    color: {TEXT};
    border: 1px solid {FIELD_BORDER};
    border-radius: {FIELD_RADIUS}px;
    padding-left: 8px;
    padding-right: 8px;
    min-height: 28px;
    selection-background-color: {ACCENT};
}}
/* Number fields have no arrow buttons; without this Qt squeezes the text into a sliver */
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
    subcontrol-origin: border;
}}
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    background: {FIELD_HOVER};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {TEXT_FAINT};
    background: {CARD};
}}
QComboBox {{
    padding-right: 28px;
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: url({ICONS}/chevron-down.svg);
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {FIELD_BORDER};
    selection-background-color: {ACCENT};
    outline: none;
    padding: 4px;
}}

QCheckBox {{
    color: {TEXT};
    spacing: 8px;
    min-height: 24px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #4a4d56;
    background: {FIELD};
}}
QCheckBox::indicator:hover {{
    border-color: {TEXT_DIM};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({ICONS}/check.svg);
}}
QCheckBox::indicator:disabled {{
    background: {CARD};
    border-color: {CARD_BORDER};
}}
QCheckBox::indicator:checked:disabled {{
    background: {ACCENT_DISABLED};
    border-color: {ACCENT_DISABLED};
}}
QCheckBox:disabled {{
    color: {TEXT_FAINT};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {FIELD_BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {TEXT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QProgressBar {{
    background: {FIELD};
    border: none;
    border-radius: 2px;
    min-height: 4px;
    max-height: 4px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 2px;
}}

QListWidget {{
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: {FIELD_RADIUS}px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    color: {TEXT};
    padding: 6px 6px;
    border-radius: 4px;
}}
QListWidget::item:hover {{
    background: {FIELD_HOVER};
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: #ffffff;
}}

/* Guide */
#guideText {{
    color: {TEXT};
    font-size: 13px;
}}
"""
