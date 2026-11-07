from dataclasses import dataclass, field


@dataclass
class ViewSettings:
    """How things are drawn. Nothing in here changes the data itself."""

    point_size: float = 3.0
    show_axes: bool = True
    background: tuple = (0.11, 0.12, 0.14, 1.0)

    # Same colors as the Plotly viewer so both views are easy to compare
    color_a: tuple = (0.25, 0.41, 0.88, 1.0)  # royal blue
    color_b: tuple = (1.0, 0.55, 0.0, 1.0)  # dark orange


@dataclass
class DataSettings:
    """Parameters used to build the inspections shown in the viewer."""

    # Simulated pose difference of the second inspection (same as main.py)
    rotation_deg: tuple = (5.0, -6.0, 3.0)
    translation: tuple = (0.2, 0.1, -0.15)

    # ICP (same value as registration.py)
    max_correspondence_distance: float = 0.5
    animate_alignment: bool = True


@dataclass
class Settings:
    view: ViewSettings = field(default_factory=ViewSettings)
    data: DataSettings = field(default_factory=DataSettings)
