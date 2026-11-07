"""Start the 3D inspection viewer (Qt + PyVista window, Open3D for the data).

The original Plotly viewer is unchanged: run main.py for it, or use the
"Open in Plotly" button inside this app.
"""

import sys

from PySide6.QtWidgets import QApplication

from viewer.settings import Settings
from viewer.style import apply_theme
from viewer.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("3D Inspection Viewer")
    apply_theme(app)

    window = MainWindow(Settings())
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
