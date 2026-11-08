"""The menu bar of the main window.

On macOS Qt moves About, Settings and Quit into the app menu (the one named
after the app), on Windows and Linux they stay in File / Help.
"""

from PySide6.QtGui import QAction, QKeySequence

from datasets import SCENES
from viewer.scene import CAMERA_PRESETS, COLOR_MODES, NAVIGATION_MODES


def action(window, text, slot=None, shortcut=None, checkable=False, tip=""):
    item = QAction(text, window)
    if shortcut:
        if isinstance(shortcut, (list, tuple)):
            item.setShortcuts([QKeySequence(s) for s in shortcut])
        else:
            item.setShortcut(QKeySequence(shortcut))
    if checkable:
        item.setCheckable(True)
    if tip:
        item.setStatusTip(tip)
    if slot is not None:
        item.triggered.connect(slot)
    return item


def link_checkbox(item, checkbox):
    """Menu entry and panel checkbox show the same state; using the menu clicks the checkbox
    (so it is recorded for undo like any other change)."""
    item.setCheckable(True)
    item.setChecked(checkbox.isChecked())
    checkbox.toggled.connect(item.setChecked)
    item.triggered.connect(lambda checked: checkbox.setChecked(checked))
    return item


def link_combobox(menu, window, combobox, labels):
    """Radio style menu entries for a dropdown in the panel."""
    from PySide6.QtGui import QActionGroup

    group = QActionGroup(window)
    items = []
    for index, label in enumerate(labels):
        item = action(window, label, checkable=True)
        item.setChecked(combobox.currentIndex() == index)
        item.triggered.connect(lambda _=False, i=index: combobox.setCurrentIndex(i))
        group.addAction(item)
        menu.addAction(item)
        items.append(item)
    combobox.currentIndexChanged.connect(lambda i: 0 <= i < len(items) and items[i].setChecked(True))
    return items


def build_menus(window):
    bar = window.menuBar()
    side = window.sidebar
    actions = {}

    # File
    file_menu = bar.addMenu("&File")
    file_menu.addAction(action(window, "New Project", window.new_project, QKeySequence.New))
    file_menu.addAction(action(window, "Open Project…", window.open_project_dialog, QKeySequence.Open))
    window.recent_menu = file_menu.addMenu("Open Recent")
    window.update_recent_menu()
    file_menu.addSeparator()
    file_menu.addAction(action(window, "Save", window.save_project, QKeySequence.Save))
    file_menu.addAction(action(window, "Save As…", window.save_project_as, QKeySequence.SaveAs))
    file_menu.addSeparator()
    file_menu.addAction(action(window, "Import Two Scans…", window.load_files, "Ctrl+Shift+I"))
    examples = file_menu.addMenu("Example Scenes")
    for key, scene in SCENES.items():
        examples.addAction(action(window, scene.title, lambda _=False, k=key: window.pick_scene(k)))
    export = file_menu.addMenu("Export")
    export.addAction(action(window, "Screenshot…", window.export_screenshot, "Ctrl+Shift+E"))
    export.addAction(action(window, "Change Report (PDF)…", lambda: window.export_report(), "Ctrl+Shift+R"))
    export.addAction(action(window, "Turntable Animation (GIF)…", lambda: window.export_turntable()))
    window.export_menu = export
    file_menu.addSeparator()
    preferences = action(window, "Settings…", window.show_preferences, QKeySequence.Preferences)
    preferences.setMenuRole(QAction.PreferencesRole)
    file_menu.addAction(preferences)
    quit_item = action(window, "Quit", window.close, QKeySequence.Quit)
    quit_item.setMenuRole(QAction.QuitRole)
    file_menu.addAction(quit_item)

    # Edit
    edit = bar.addMenu("&Edit")
    undo = window.history.stack.createUndoAction(window, "Undo")
    undo.setShortcut(QKeySequence("Ctrl+Z"))  # Cmd+Z on Mac (Qt maps Ctrl to Cmd there)
    redo = window.history.stack.createRedoAction(window, "Redo")
    # Mac: Cmd+Shift+Z. Windows / Linux: Ctrl+Y and also Ctrl+Shift+Z
    shortcuts = []
    for key in (QKeySequence(QKeySequence.Redo), QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")):
        if not key.isEmpty() and key not in shortcuts:
            shortcuts.append(key)
    redo.setShortcuts(shortcuts)
    edit.addAction(undo)
    edit.addAction(redo)
    actions["undo"], actions["redo"] = undo, redo
    edit.addSeparator()
    edit.addAction(action(window, "Delete Points with Lasso", lambda: window.start_tool("lasso_delete"), "L"))
    edit.addAction(action(window, "Keep Only Points in Lasso", lambda: window.start_tool("lasso_keep"), "Shift+L"))
    edit.addAction(action(window, "Remove Stray Points", lambda: window.remove_stray_points()))
    window.edit_menu = edit

    # View
    view = bar.addMenu("&View")
    panel = window.dock.toggleViewAction()
    panel.setText("Side Panel")
    panel.setShortcut(QKeySequence("Ctrl+Alt+S"))  # Space works too, see MainWindow.eventFilter
    view.addAction(panel)
    view.addAction(action(window, "Guide", lambda: (window.dock.show(), side.show_page(1)), "F1"))
    view.addSeparator()
    for number, (name, checkbox) in enumerate(side.checkboxes.items(), start=1):
        item = action(window, f"Show {name}", shortcut=str(number))
        view.addAction(link_checkbox(item, checkbox))
    view.addSeparator()
    navigation = view.addMenu("Navigation")
    link_combobox(navigation, window, side.navigation, NAVIGATION_MODES)
    navigation.addSeparator()
    navigation.addAction(action(window, "Switch Orbit / Fly", window.next_navigation, "M"))
    colours = view.addMenu("Colours")
    link_combobox(colours, window, side.color_mode, COLOR_MODES)
    camera = view.addMenu("Camera")
    for preset in CAMERA_PRESETS:
        camera.addAction(action(window, f"{preset} View", lambda _=False, p=preset: window.scene.look_from(p)))
    view.addAction(action(window, "Reset View", lambda: window.scene.look_from("Iso"), "R"))
    window.views_menu = view.addMenu("Saved Views")
    window.update_views_menu()
    view.addSeparator()
    view.addAction(link_checkbox(action(window, "Show Axes"), side.axes))
    view.addAction(link_checkbox(action(window, "Show True Change"), side.truth))
    view.addAction(link_checkbox(action(window, "Show Changed Points"), side.show_changes))
    view.addAction(link_checkbox(action(window, "Show Area Boxes"), side.show_areas))
    view.addAction(link_checkbox(action(window, "Depth Shading"), side.depth_shading))
    view.addAction(link_checkbox(action(window, "Before / After Swipe", shortcut="B"), side.swipe))
    view.addSeparator()
    full = action(window, "Enter Full Screen", window.toggle_full_screen, QKeySequence.FullScreen)
    view.addAction(full)
    window.view_menu = view

    # Scene
    scene = bar.addMenu("&Scene")
    scene.addAction(action(window, "Random Variation", window.new_seed))
    scene.addSeparator()
    scene.addAction(action(window, "Scan B: Random Position", window.random_offset))
    scene.addAction(action(window, "Scan B: Same Position as A", lambda: side.set_offset((0, 0, 0), (0, 0, 0))))

    # Align
    align = bar.addMenu("&Align")
    align.addAction(action(window, "Align B to A", window.align, "Ctrl+L"))
    align.addAction(action(window, "Reset Alignment", window.reset_alignment))
    align.addSeparator()
    method = align.addMenu("Method")
    link_combobox(method, window, side.icp_method, [side.icp_method.itemText(i) for i in range(side.icp_method.count())])
    align.addAction(link_checkbox(action(window, "Animate the Steps"), side.animate))

    # Analyze
    analyze = bar.addMenu("A&nalyze")
    analyze.addAction(action(window, "Detect Changes", window.detect_changes, "Ctrl+D"))
    analyze.addSeparator()
    analyze.addAction(action(window, "Next Changed Area", lambda: window.step_area(1), "]"))
    analyze.addAction(action(window, "Previous Changed Area", lambda: window.step_area(-1), "["))
    analyze.addSeparator()
    analyze.addAction(link_checkbox(action(window, "Automatic Threshold"), side.auto_threshold))
    analyze.addSeparator()
    analyze.addAction(action(window, "Cross Section", lambda: window.start_tool("section"), "X"))
    analyze.addAction(action(window, "Measure Distance", lambda: window.start_tool("measure"), "T"))
    analyze.addAction(action(window, "Clear Measurements", window.clear_measurements))
    analyze.addSeparator()
    analyze.addAction(action(window, "Add Note", lambda: window.start_tool("note"), "N"))
    window.notes_menu = analyze.addMenu("Notes")
    window.update_notes_menu()
    window.analyze_menu = analyze

    # Window
    window_menu = bar.addMenu("&Window")
    window_menu.addAction(action(window, "Command Palette…", window.show_palette, "Ctrl+K"))
    window_menu.addAction(action(window, "History", lambda: (window.dock.show(), side.show_page(2)), "Ctrl+Shift+H"))
    window_menu.addSeparator()
    window_menu.addAction(action(window, "Minimize", window.showMinimized, "Ctrl+M"))
    window_menu.addAction(action(window, "Zoom", window.toggle_maximized))
    window.window_menu = window_menu

    # Help
    help_menu = bar.addMenu("&Help")
    help_menu.addAction(action(window, "Guide", lambda: (window.dock.show(), side.show_page(1))))
    help_menu.addAction(action(window, "Keyboard Shortcuts", window.show_shortcuts, "Ctrl+/"))
    about = action(window, "About Subdron Sonar Studio", window.show_about)
    about.setMenuRole(QAction.AboutRole)
    help_menu.addAction(about)
    window.help_menu = help_menu

    return actions
