"""Start the Open3D inspection viewer.

The original Plotly viewer is unchanged: run main.py for it, or use the
"Open in Plotly" button inside this app.
"""

import open3d.visualization.gui as gui

from viewer.settings import Settings
from viewer.window import InspectionWindow


def main():
    gui.Application.instance.initialize()
    InspectionWindow(Settings())
    gui.Application.instance.run()


if __name__ == "__main__":
    main()
