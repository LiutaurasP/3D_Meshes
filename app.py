"""Start Subdron Sonar Studio (Qt + PyVista window, Open3D for the data).

The original Plotly viewer is unchanged: run main.py for it, or use the
"Open in Plotly" button inside this app.
"""

import sys

from viewer.branding import apply_identity, set_process_name

set_process_name()  # before Qt starts, so the menu bar shows the app's name

from PySide6.QtWidgets import QApplication  # noqa: E402

from viewer.settings import Settings  # noqa: E402
from viewer.style import apply_theme  # noqa: E402
from viewer.window import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    apply_identity(app)
    apply_theme(app)

    window = MainWindow(Settings())
    window.show()

    # A project file given on the command line (or double clicked later) is opened
    for argument in sys.argv[1:]:
        if argument.endswith(".subdron"):
            window.open_project(argument)
            break

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
