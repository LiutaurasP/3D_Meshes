from dataclasses import dataclass, field


@dataclass
class ViewSettings:
    """How things are drawn. Nothing in here changes the data itself."""

    point_size: float = 3.0
    show_axes: bool = True
    show_truth: bool = False  # highlight where the real change is (examples only)
    show_changes: bool = True  # highlight what change detection found
    show_areas: bool = True  # boxes and labels around the change areas
    color_mode: str = "Per scan"  # or "Depth" or "Change"
    background: tuple = (0.016, 0.02, 0.035, 1.0)  # almost black, a hint of midnight blue

    # Same colors as the Plotly viewer so both views are easy to compare
    color_a: tuple = (0.25, 0.41, 0.88, 1.0)  # royal blue
    color_b: tuple = (1.0, 0.55, 0.0, 1.0)  # dark orange
    color_truth: tuple = (1.0, 0.0, 0.85, 1.0)  # magenta
    color_changes: tuple = (1.0, 0.85, 0.1, 1.0)  # yellow


@dataclass
class DataSettings:
    """Which data is shown and how it is made."""

    scene: str = "harbour_quay_section"  # the 60 m harbour quay (medium size)
    n_points: int = 300_000
    noise: float = 0.01  # metres
    outliers: float = 0.002  # share of stray points
    stripes: bool = True
    seed: int = 1

    # Simulated pose difference of the second scan
    rotation_deg: tuple = (3.0, -2.0, 2.0)
    translation: tuple = (0.3, -0.2, 0.1)

    # ICP
    max_correspondence_distance: float = 0.5
    max_iterations: int = 300
    max_icp_points: int = 50_000  # bigger scans are thinned out for ICP
    icp_method: str = "point-to-point"  # or "point-to-plane"
    animate_alignment: bool = True

    # Change detection
    change_threshold: float = 0.10  # metres, used when auto_threshold is off
    auto_threshold: bool = True
    min_area_points: int = 15


@dataclass
class Settings:
    view: ViewSettings = field(default_factory=ViewSettings)
    data: DataSettings = field(default_factory=DataSettings)
