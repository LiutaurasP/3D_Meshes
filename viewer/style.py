"""Look of the app: colours, type, shapes. One place, so everything matches.

Themes: each one is five colours (the background, cards, fields, the accent and the text);
every other colour is mixed from those, so a theme can't end up with a colour that doesn't
belong. The theme is picked in Settings and used from the next start: use_theme() runs before
the windows are built, and the rest of the app reads the colours from here.

Shapes: corners are concentric. A shape inside another one has the outer radius minus the
gap between them (nested()), so nested corners run parallel. The big surfaces (cards,
tutorial cards, notifications, the command palette) are drawn as squircles, see shapes.py.

Type: Geist (the font Subdron uses on its website), bundled with the app, one scale of sizes.
"""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

ICONS = (Path(__file__).resolve().parent / "icons").as_posix()  # forward slashes work on Windows too
FONTS = Path(__file__).resolve().parent / "assets" / "fonts"

# Every theme also picks the colours of the two scans in the 3D view (scan A, scan B, and the steps in
# between for a series of scans): ones that look natural with the theme, stand apart from each other
# and from the yellow of the changed points.
THEMES = {
    # From subdron.com: deep navy background, navy panels, a bright sonar blue
    "subdron": {"name": "Subdron", "base": "#040917", "surface": "#0e1b33", "raised": "#16243d",
                "accent": "#3d95ff", "text": "#e9f1ff", "view": "#040917",
                "scan_a": "#4069e0", "scan_b": "#ff8c00", "scan_mid": ["#2ebdc7", "#9ecc4d"]},
    # The app's first look, refined: neutral dark grey with a classic blue
    "midnight": {"name": "Midnight", "base": "#111216", "surface": "#1a1b20", "raised": "#23252b",
                 "accent": "#3d7ff5", "text": "#e6e7eb", "view": "#040509",
                 "scan_a": "#4069e0", "scan_b": "#ff8c00", "scan_mid": ["#2ebdc7", "#9ecc4d"]},
    # Neutral graphite with a calm teal
    "graphite": {"name": "Graphite", "base": "#141415", "surface": "#1d1d1f", "raised": "#28282b",
                 "accent": "#26a69a", "text": "#ececee", "view": "#0b0b0c",
                 "scan_a": "#4aa3df", "scan_b": "#ff7b54", "scan_mid": ["#45c4b0", "#b6d36b"]},
    # Cool blue-grey with a soft periwinkle
    "slate": {"name": "Slate", "base": "#0f141b", "surface": "#18202b", "raised": "#212b38",
              "accent": "#7a9cf2", "text": "#e4e9f1", "view": "#0a0e13",
              "scan_a": "#7c8df5", "scan_b": "#f2a65a", "scan_mid": ["#5cc8d7", "#a8d58a"]},
    # Deep water: dark teal with a bright cyan
    "abyss": {"name": "Abyss", "base": "#03111a", "surface": "#0a2230", "raised": "#12303f",
              "accent": "#1fb8c4", "text": "#e3f5f7", "view": "#020c12",
              "scan_a": "#3fc1d0", "scan_b": "#ff7e67", "scan_mid": ["#6fd6a8", "#c8d77a"]},
    # Dark aubergine with a violet
    "violet": {"name": "Violet", "base": "#110e19", "surface": "#1b1726", "raised": "#252033",
               "accent": "#8f73f5", "text": "#ece8f5", "view": "#0a0811",
               "scan_a": "#9a7cff", "scan_b": "#ffa066", "scan_mid": ["#e183d6", "#ff8f9f"]},
    # Light panels for projectors and bright rooms. The 3D view stays dark in every theme: the scan colours,
    # the yellow changes and the white overlays (logo, colour bars) need a dark background
    "daylight": {"name": "Daylight", "base": "#eef1f6", "surface": "#ffffff", "raised": "#f3f5f9",
                 "accent": "#2563eb", "text": "#18202e", "view": "#1c2330",
                 "scan_a": "#3b82f6", "scan_b": "#f97316", "scan_mid": ["#14b8a6", "#84cc16"]},
}
DEFAULT_THEME = "subdron"

# Colours that carry a meaning: the same in every theme
ADDED = "#e8796b"  # material added (red, as in the reports)
REMOVED = "#6a9ff0"  # material removed (blue)
MOVED = "#5ad7ff"  # a moved object
SUCCESS = "#3fb27f"
WARNING = "#e0a43a"
DANGER = "#e8796b"

# Type scale (pixels)
FONT_FAMILY = "Geist"
SIZE_TINY = 11
SIZE_SMALL = 12
SIZE_BODY = 13
SIZE_TITLE = 14
SIZE_HEADING = 17

# Shapes: radii of the outermost surfaces; everything inside is nested() from them
CARD_RADIUS = 14
DIALOG_RADIUS = 18  # floating surfaces: tutorial cards, the command palette
FIELD_RADIUS = 8
RADIUS = FIELD_RADIUS  # older name
SMOOTHING = 0.6  # squircle corners, like Apple's (0 = plain circle arcs)


def nested(outer, gap, minimum=3):
    """Radius of a shape that sits `gap` pixels inside a shape with radius `outer` (concentric corners)."""
    return max(outer - gap, minimum)


def mix(color, other, amount):
    """`amount` of color over other (0 = other, 1 = color), as #rrggbb."""
    a, b = QColor(color), QColor(other)
    channels = [round(a.red() * amount + b.red() * (1 - amount)), round(a.green() * amount + b.green() * (1 - amount)),
                round(a.blue() * amount + b.blue() * (1 - amount))]
    return "#" + "".join(f"{c:02x}" for c in channels)


def rgb(color):
    """#rrggbb -> (r, g, b) in 0..1 for the 3D view."""
    c = QColor(color)
    return (c.redF(), c.greenF(), c.blueF())


def rgba(color, alpha):
    """For style sheets: the colour with an alpha (0..1)."""
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.2f})"


THEME = DEFAULT_THEME


def use_theme(key):
    """Make a theme the current one. Call before the windows are built (they read the colours once)."""
    global THEME, BACKGROUND, CARD, CARD_BORDER, FIELD, FIELD_BORDER, FIELD_HOVER, TEXT, TEXT_DIM, TEXT_FAINT
    global ACCENT, ACCENT_HOVER, ACCENT_PRESSED, ACCENT_DISABLED, ACCENT_SOFT, ACCENT_TEXT, CHECK_BORDER
    global BRAND, VIEW_BACKGROUND, LABEL_FILL, PANEL_STYLE, SCAN_A, SCAN_B, SCAN_STOPS
    THEME = key if key in THEMES else DEFAULT_THEME
    theme = THEMES[THEME]
    base, surface, raised, accent, text = (theme[k] for k in ("base", "surface", "raised", "accent", "text"))
    BACKGROUND = base  # behind the cards
    CARD = surface
    CARD_BORDER = mix(text, surface, 0.09)
    FIELD = raised
    FIELD_BORDER = mix(text, raised, 0.13)
    FIELD_HOVER = mix(text, raised, 0.06)
    CHECK_BORDER = mix(text, raised, 0.28)
    TEXT = text
    TEXT_DIM = mix(text, surface, 0.66)
    TEXT_FAINT = mix(text, surface, 0.40)
    ACCENT = accent
    ACCENT_HOVER = mix("#ffffff", accent, 0.14)
    ACCENT_PRESSED = mix("#000000", accent, 0.12)
    ACCENT_DISABLED = mix(accent, surface, 0.30)
    ACCENT_SOFT = mix(accent, surface, 0.16)  # a quiet tint of the accent (selected rows, highlighted cards)
    ACCENT_TEXT = "#ffffff"
    BRAND = surface  # start screen and splash: the theme's own navy / grey
    VIEW_BACKGROUND = theme["view"]
    LABEL_FILL = rgb(mix(text, surface, 0.04))  # labels in the 3D view
    SCAN_A, SCAN_B = rgb(theme["scan_a"]), rgb(theme["scan_b"])  # default colours of the two scans
    SCAN_STOPS = [SCAN_A, *(rgb(c) for c in theme["scan_mid"]), SCAN_B]  # a series: oldest to newest
    PANEL_STYLE = panel_style()


def theme_colors(key):
    """The main colours of any theme (not only the current one), for the previews in Settings."""
    theme = THEMES.get(key, THEMES[DEFAULT_THEME])
    base, surface, raised, accent, text = (theme[k] for k in ("base", "surface", "raised", "accent", "text"))
    return {"base": base, "surface": surface, "raised": raised, "accent": accent, "text": text,
            "border": mix(text, surface, 0.09), "dim": mix(text, surface, 0.45),
            "soft": mix(accent, surface, 0.22), "view": theme["view"], "scan_a": theme["scan_a"],
            "scan_b": theme["scan_b"]}


def theme_names():
    return [(key, theme["name"]) for key, theme in THEMES.items()]


def load_fonts():
    """Add the bundled Geist font (four weights). Returns True if it is available."""
    found = False
    for file in sorted(FONTS.glob("Geist-*.ttf")):
        found |= QFontDatabase.addApplicationFont(str(file)) >= 0
    return found and FONT_FAMILY in QFontDatabase.families()


_CHART_FONT = None


def chart_fonts():
    """Use Geist in the matplotlib charts too (height map, cross section, trend), once."""
    global _CHART_FONT
    if _CHART_FONT is not None:
        return _CHART_FONT
    _CHART_FONT = False
    try:
        import matplotlib
        from matplotlib import font_manager

        files = sorted(FONTS.glob("Geist-*.ttf"))
        for file in files:
            font_manager.fontManager.addfont(str(file))
        if files:
            matplotlib.rcParams["font.family"] = [FONT_FAMILY, "DejaVu Sans"]
            _CHART_FONT = True
    except Exception:  # charts fall back to matplotlib's own font
        pass
    return _CHART_FONT


def apply_theme(app):
    """Fusion style with the theme's palette and font, so dialogs and menus match the panel."""
    app.setStyle("Fusion")
    if load_fonts():
        font = QFont(FONT_FAMILY)
        font.setPixelSize(SIZE_BODY)
        app.setFont(font)
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
        QPalette.HighlightedText: ACCENT_TEXT,
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
    app.setStyleSheet(f"QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {FIELD_BORDER};"
                      f" border-radius: {nested(FIELD_RADIUS, 2)}px; padding: 5px 8px; }}")


def panel_style():
    list_padding = 4
    segment_padding = 3
    return f"""
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
QScrollBar::handle:vertical:hover {{
    background: {CHECK_BORDER};
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

/* Cards: the shape itself is painted (a squircle, see widgets.Surface) */
#card {{
    background: transparent;
    border: none;
}}
#cardHeader {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-size: {SIZE_TITLE}px;
    font-weight: 600;
    padding: 0;
    text-align: left;
}}
#cardHeader:hover {{
    color: {ACCENT};
}}
#formLabel {{
    color: {TEXT_DIM};
}}
#description, #hint {{
    color: {TEXT_DIM};
}}
#hint {{
    font-size: {SIZE_SMALL}px;
}}
#axisLabel {{
    color: {TEXT_FAINT};
    font-size: {SIZE_TINY}px;
    font-weight: 600;
}}
#keycap {{
    color: {TEXT_DIM};
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: 5px;
    padding: 0 6px;
    font-size: {SIZE_TINY}px;
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
    color: {ACCENT_TEXT};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primary:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton#primary:disabled {{
    background: {ACCENT_DISABLED};
    border-color: {ACCENT_DISABLED};
    color: {TEXT_DIM};
}}

/* Settings / Areas / Guide / History switch: the buttons sit {segment_padding}px inside the frame */
#segment {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: {FIELD_RADIUS + segment_padding}px;
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
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {{
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
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QLineEdit:hover {{
    background: {FIELD_HOVER};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {{
    border-color: {ACCENT};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled {{
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
    padding: {list_padding}px;
}}

QCheckBox {{
    color: {TEXT};
    spacing: 8px;
    min-height: 24px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid {CHECK_BORDER};
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

/* Lists and tables: items sit {list_padding}px inside the frame, so their corners are nested */
QListWidget {{
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: {FIELD_RADIUS}px;
    padding: {list_padding}px;
    outline: none;
}}
QListWidget::item {{
    color: {TEXT};
    padding: 6px 6px;
    border-radius: {nested(FIELD_RADIUS, list_padding)}px;
}}
QListWidget::item:hover {{
    background: {FIELD_HOVER};
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
}}
QTableWidget, QUndoView {{
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: {FIELD_RADIUS}px;
    gridline-color: {CARD_BORDER};
    outline: none;
    selection-background-color: {ACCENT_SOFT};
}}
QTableWidget::item {{
    padding: 2px 4px;
}}
QTableWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};  /* readable on the soft tint in light and dark themes */
}}
QHeaderView {{
    background: transparent;
}}
QHeaderView::section {{
    background: {FIELD};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {FIELD_BORDER};
    padding: 5px 6px;
    font-size: {SIZE_SMALL}px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {FIELD};
    border: none;
}}

/* Guide */
#guideText {{
    color: {TEXT};
    font-size: {SIZE_BODY}px;
}}
"""


use_theme(DEFAULT_THEME)
