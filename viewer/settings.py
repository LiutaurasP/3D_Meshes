from dataclasses import dataclass, field


@dataclass
class ViewSettings:
    """How things are drawn. Nothing in here changes the data itself."""

    point_size: float = 3.0
    show_axes: bool = True
    show_truth: bool = False  # highlight where the real change is (examples only)
    color_mode: str = "Per inspection"  # or "Depth"
    background: tuple = (0.11, 0.12, 0.14, 1.0)

    # Same colors as the Plotly viewer so both views are easy to compare
    color_a: tuple = (0.25, 0.41, 0.88, 1.0)  # royal blue
    color_b: tuple = (1.0, 0.55, 0.0, 1.0)  # dark orange
    color_truth: tuple = (1.0, 0.0, 0.85, 1.0)  # magenta


@dataclass
class DataSettings:
    """Which data is shown and how it is made."""

    scene: str = "harbour_wall_scour"
    n_points: int = 30_000
    noise: float = 0.01  # metres
    outliers: float = 0.002  # share of stray points
    stripes: bool = True
    seed: int = 1

    # Simulated pose difference of the second survey
    rotation_deg: tuple = (3.0, -2.0, 2.0)
    translation: tuple = (0.3, -0.2, 0.1)

    # ICP
    max_correspondence_distance: float = 0.5
    max_iterations: int = 300
    max_icp_points: int = 50_000  # bigger scans are thinned out for ICP
    animate_alignment: bool = True


@dataclass
class Settings:
    view: ViewSettings = field(default_factory=ViewSettings)
    data: DataSettings = field(default_factory=DataSettings)
