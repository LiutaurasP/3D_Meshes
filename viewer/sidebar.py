import open3d.visualization.gui as gui

from viewer.scene import CAMERA_PRESETS, NAVIGATION_MODES


HELP_TEXT = (
    "Keys\n"
    "  1 / 2   show or hide a cloud\n"
    "  M       switch orbit / fly\n"
    "  R       reset the view\n"
    "\n"
    "Fly mode\n"
    "  W A S D  move\n"
    "  drag     look around"
)


class Sidebar:
    """Settings panel on the right side of the window.

    The sidebar only builds widgets and forwards events to the window
    through callbacks, it does not touch the scene directly.
    """

    def __init__(self, em, cloud_names, view_settings, callbacks):
        self.callbacks = callbacks
        self.checkboxes = {}

        margin = 0.5 * em
        self.panel = gui.ScrollableVert(0.5 * em, gui.Margins(margin, margin, margin, margin))

        self.panel.add_child(self._clouds_section(em, cloud_names))
        self.panel.add_child(self._camera_section(em))
        self.panel.add_child(self._display_section(em, view_settings))
        self.panel.add_child(self._compare_section(em))
        self.panel.add_child(self._help_section(em))

    # Sections

    def _clouds_section(self, em, cloud_names):
        section = gui.CollapsableVert("Clouds", 0.25 * em, gui.Margins(em, 0, 0, 0))

        for key, name in enumerate(cloud_names, start=1):
            checkbox = gui.Checkbox(f"{name}   [{key}]")
            checkbox.checked = True
            checkbox.set_on_checked(lambda checked, n=name: self.callbacks["visibility"](n, checked))
            self.checkboxes[name] = checkbox
            section.add_child(checkbox)

        return section

    def _camera_section(self, em):
        section = gui.CollapsableVert("Camera", 0.25 * em, gui.Margins(em, 0, 0, 0))

        row = gui.Horiz(0.5 * em)
        row.add_child(gui.Label("Navigation"))
        self.navigation = gui.Combobox()
        for mode in NAVIGATION_MODES:
            self.navigation.add_item(mode)
        self.navigation.set_on_selection_changed(lambda text, index: self.callbacks["navigation"](text))
        row.add_child(self.navigation)
        section.add_child(row)

        presets = gui.Horiz(0.25 * em)
        for preset in CAMERA_PRESETS:
            button = gui.Button(preset)
            button.horizontal_padding_em = 0.4
            button.vertical_padding_em = 0.1
            button.set_on_clicked(lambda p=preset: self.callbacks["camera"](p))
            presets.add_child(button)
        section.add_child(presets)

        reset = gui.Button("Reset view")
        reset.set_on_clicked(lambda: self.callbacks["camera"]("Iso"))
        section.add_child(reset)

        return section

    def _display_section(self, em, view_settings):
        section = gui.CollapsableVert("Display", 0.25 * em, gui.Margins(em, 0, 0, 0))

        row = gui.Horiz(0.5 * em)
        row.add_child(gui.Label("Point size"))
        point_size = gui.Slider(gui.Slider.INT)
        point_size.set_limits(1, 10)
        point_size.int_value = int(view_settings.point_size)
        point_size.set_on_value_changed(lambda value: self.callbacks["point_size"](value))
        row.add_child(point_size)
        section.add_child(row)

        axes = gui.Checkbox("Show axes")
        axes.checked = view_settings.show_axes
        axes.set_on_checked(lambda checked: self.callbacks["axes"](checked))
        section.add_child(axes)

        return section

    def _compare_section(self, em):
        section = gui.CollapsableVert("Compare", 0.25 * em, gui.Margins(em, 0, 0, 0))

        plotly = gui.Button("Open in Plotly")
        plotly.tooltip = "Show the same clouds in the browser viewer (visualize.py)"
        plotly.set_on_clicked(lambda: self.callbacks["plotly"]())
        section.add_child(plotly)

        return section

    def _help_section(self, em):
        section = gui.CollapsableVert("Controls", 0.25 * em, gui.Margins(em, 0, 0, 0))
        section.add_child(gui.Label(HELP_TEXT))
        self.status = gui.Label("")
        section.add_child(self.status)
        return section

    # Keep widgets in sync when something changes from the keyboard

    def set_checked(self, name, checked):
        self.checkboxes[name].checked = checked

    def set_navigation(self, mode):
        self.navigation.selected_index = list(NAVIGATION_MODES).index(mode)

    def set_status(self, text):
        self.status.text = text
