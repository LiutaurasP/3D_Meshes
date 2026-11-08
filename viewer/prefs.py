"""App preferences (Settings… dialog), stored by the operating system via QSettings."""

from PySide6.QtCore import QSettings

DEFAULTS = {
    "show_start_screen": True,
    "autosave_minutes": 2,  # 0 = off
    "depth_shading": False,
    "sphere_limit_millions": 1.5,  # above this many points, draw plain points (faster)
    "display_limit_millions": 8.0,  # above this many points, draw an evenly spread part of them
    "restore_last_layout": True,
    "inspector_name": "",  # filled into new change reports
    # Display Mode
    "display_speed": "Normal",
    "display_direction": "Counter-clockwise",
    "display_changes": True,  # show change highlights and area boxes
    "display_notes": True,
    "display_tour": True,  # fly between the saved views, if there are any
    "display_fullscreen": True,
    "display_caption": "",
}


def get(key):
    value = QSettings().value(f"prefs/{key}", DEFAULTS[key])
    default = DEFAULTS[key]
    # QSettings gives strings back on some platforms
    if isinstance(default, bool):
        return value in (True, "true", "1", 1)
    if isinstance(default, int):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    return value


def set(key, value):  # noqa: A001 (same name as the builtin, used as prefs.set)
    QSettings().setValue(f"prefs/{key}", value)
