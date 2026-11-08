"""Text of the Guide page in the side panel. Each chapter is (title, html, open at start)."""

from viewer.style import ACCENT_HOVER, FIELD, FIELD_BORDER, TEXT, TEXT_DIM


def key(text):
    return (f'<span style="background-color:{FIELD}; color:{TEXT}; '
            f'border:1px solid {FIELD_BORDER};">&nbsp;{text}&nbsp;</span>')


def dim(text):
    return f'<span style="color:{TEXT_DIM};">{text}</span>'


def keys_table(rows):
    cells = "".join(
        f'<tr><td style="padding:3px 12px 3px 0; white-space:nowrap;">{keys}</td>'
        f'<td style="padding:3px 0; color:{TEXT_DIM};">{what}</td></tr>'
        for keys, what in rows
    )
    return f'<table cellspacing="0">{cells}</table>'


def steps(items):
    rows = "".join(
        f'<tr><td style="padding:4px 10px 4px 0; color:{ACCENT_HOVER}; font-weight:600;" valign="top">{i}</td>'
        f'<td style="padding:4px 0;">{text}</td></tr>'
        for i, text in enumerate(items, start=1)
    )
    return f'<table cellspacing="0">{rows}</table>'


P = '<p style="margin:0 0 8px 0;">'


CHAPTERS = [
    ("What this app does", P +
     "It compares two underwater scans of the same place, made at different times: "
     "<b>Scan A</b> (before) and <b>Scan B</b> (after). It lines them up and "
     "then shows what changed between them, like scour holes, fallen objects or damaged walls."
     "</p>" + P + dim(
         "Until real scan data is available, the app comes with simulated underwater "
         "scenes in which the real change is known, so you can check how well everything works.") + "</p>",
     True),

    ("Quick start", steps([
        "Pick a scene under <b>Scene</b>, for example <i>Quay wall – dropped object</i>.",
        "Press <b>Align B to A</b> and watch scan B slide onto scan A.",
        "Press <b>Detect changes</b>. Changed points light up and every changed area gets a box.",
        "Click an area in the list to fly the camera to it.",
        "Tick <b>Show true change</b> under Display to compare with the real change.",
    ]), True),

    ("Moving around", P +
     "<b>Orbit mode</b> (default): drag to rotate around the scene, " + key("Shift") +
     " + drag to pan, scroll to zoom.</p>" + P +
     "<b>Fly mode</b> (" + key("M") + " to switch): move like in a game with " + key("W") + key("A") + key("S") + key("D") +
     ", go down and up with " + key("Q") + " / " + key("E") + ", hold " + key("Shift") + " to go faster. "
     "Drag to look around, scroll to change the speed.</p>" + P + dim(
         "WASD also works in orbit mode. Fly mode is best for going inside scenes like the flooded tunnel.") + "</p>",
     False),

    ("Keyboard shortcuts", P + dim("On Windows and Linux use Ctrl where the Mac uses Cmd.") + "</p>" + keys_table([
        (key("Cmd") + " " + key("Z"), "undo"),
        (key("Cmd") + " " + key("Shift") + " " + key("Z") + " / " + key("Ctrl") + " " + key("Y"), "redo"),
        (key("Cmd") + " " + key("S"), "save the project"),
        (key("Cmd") + " " + key("O"), "open a project"),
        (key("Cmd") + " " + key("N"), "new project"),
        (key("Cmd") + " " + key("L"), "align B to A"),
        (key("Cmd") + " " + key("D"), "detect changes"),
        (key("]") + " " + key("["), "next / previous changed area"),
        (key("W") + key("A") + key("S") + key("D"), "move"),
        (key("Q") + " " + key("E"), "down / up"),
        (key("Shift"), "move faster"),
        (key("M"), "switch orbit / fly"),
        (key("1") + " " + key("2"), "show or hide scan A / B"),
        (key("R"), "reset the view"),
        (key("Space"), "show or hide this panel"),
        (key("F1"), "open this guide"),
        (key("Cmd") + " " + key("K"), "command palette: type to find any command"),
        (key("B"), "before / after swipe"),
        (key("X"), "cross section"),
        (key("T"), "measure a distance"),
        (key("N"), "pin a note in 3D"),
        (key("L") + " / " + key("Shift") + " " + key("L"), "delete points / keep only points with a lasso"),
        (key("Cmd") + " " + key("Shift") + " " + key("R"), "export the change report (PDF)"),
        (key("Cmd") + " " + key("1") + " … " + key("9"), "fly to a saved view"),
        (key("Cmd") + " " + key("/"), "list of all shortcuts (searchable)"),
        (key("Cmd") + " " + key(","), "settings"),
    ]), False),

    ("Projects: saving and opening", P +
     "<b>File → Save</b> stores the whole session in one <b>.subdron</b> file: the scene and its "
     "settings, the alignment, the detected changes, colours, the camera position and how this "
     "panel looks. <b>File → Open</b> brings all of it back exactly as it was.</p>" + P +
     "Scans you imported from files are stored <b>inside</b> the project, so it still opens when "
     "the original files are moved, or on another computer. Example scenes are rebuilt from "
     "their settings, which keeps those projects tiny.</p>" + P + dim(
         "A dot or asterisk in the window title means there are unsaved changes. "
         "Recently used projects are under File → Open Recent.") + "</p>" + P +
     "<b>Your work is safe:</b> unsaved changes are saved in the background every few minutes "
     "(Settings). If the app ever closes unexpectedly, it offers to restore them on the next start.</p>"
     + P + "<b>Drag and drop:</b> drop a <b>.subdron</b> file on the window to open it, or two scan "
     "files to import them (the first by name becomes scan A).</p>",
     False),

    ("Undo and redo", P +
     "Almost everything can be undone: showing and hiding scans, colours, the scene and its "
     "settings, the position of scan B, aligning, detecting changes and the display options. "
     "<b>Edit → Undo</b> says what it will undo, for example <i>Undo Align B to A</i>.</p>" + P + dim(
         "The camera is not part of undo, so undoing a colour change doesn't make the view jump. "
         "Quick repeated changes, like dragging a slider, are undone in one step.") + "</p>",
     False),

    ("Example scenes", P +
     "Every scene is two simulated sonar scans of the same place, with a known change in between. "
     "The list shows the size of each scene.</p>" + keys_table([
         ("<b>Size</b>", "number of points per scan"),
         ("<b>Sensor noise</b>", "measurement error close to the sonar (it grows with distance)"),
         ("<b>Stray points</b>", "share of false echoes in the water, like fish or bubbles"),
         ("<b>Ping stripes</b>", "the stripy density pattern of the sonar pings"),
         ("<b>Variation</b>", "another random version of the same scene (" + dim("Random") + " picks one)"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim("Changes apply right away, there is nothing to confirm.") + "</p>",
     False),

    ("Scan B position", P +
     "A real scan is never made from exactly the same spot twice. The <b>Scan B position</b> "
     "card simulates that: scan B is <b>turned</b> (degrees) and <b>shifted</b> (metres) "
     "compared to A.</p>" + keys_table([
         ("<b>Same as A</b>", "no difference at all, B lies exactly on A"),
         ("<b>Random position</b>", "a new random turn and shift"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "<b>Align B to A</b> has to undo this. A bigger difference is harder: try a large turn "
         "and see when the alignment stops working.") + "</p>",
     False),

    ("Aligning the scans", P +
     "Two scans are never made from exactly the same position, so B first has to be moved onto A. "
     "<b>Align B to A</b> does this with ICP: it pairs every point of B with the closest point of A "
     "and moves B a little closer, round after round.</p>" + keys_table([
         ("<b>Match distance</b>", "points further apart than this are not paired up"),
         ("<b>Max rounds</b>", "ICP stops earlier when nothing changes any more"),
         ("<b>RMSE</b>", "average distance of the pairs, lower is better"),
         ("<b>Fitness</b>", "share of points that found a partner"),
         ("<b>Point to point</b>", "pairs points with points, best for walls"),
         ("<b>Point to plane</b>", "measures to the surface, best for open seabed and tunnels"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "Each scene picks the method that suits it. Long flat walls need many rounds (about 200), "
         "there is little to hold on to along the wall. Big changes can pull the alignment a few "
         "centimetres off.") + "</p>",
     False),

    ("Finding changes", P +
     "<b>Detect changes</b> measures how far every point is from the other scan's surface. "
     "Points further than the <b>threshold</b> count as changed and are grouped into areas.</p>" + keys_table([
         ("<b>Auto threshold</b>", "picked from the noise in the data (recommended)"),
         ("<b>Smallest area</b>", "smaller groups of changed points are ignored as noise"),
         ("<b>+ added</b>", "something new: an object, sediment, a bulge"),
         ("<b>&minus; removed</b>", "something gone: scour, a hole, a missing rock"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "Always align first, otherwise the misalignment itself looks like change. "
         "For example scenes the panel also says how much of the true change was found.") + "</p>",
     False),

    ("Comparing tools", keys_table([
        ("<b>Before / after</b> " + key("B"), "scan A left of a divider, scan B right of it; drag the divider "
                                              "across the view to wipe between them"),
        ("<b>Cross section</b> " + key("X"), "click two points on the scan: a side view of A and B along that "
                                             "line opens, red where material was added, blue where it was removed"),
        ("<b>Measure</b> " + key("T"), "click two points: the distance appears in 3D, the status shows the "
                                       "horizontal and vertical part"),
        ("<b>Note</b> " + key("N"), "click a place and type a note; it is pinned there in 3D, saved in "
                                    "the project and listed in the report (Analyze → Notes flies to it)"),
        ("<b>Esc</b>", "cancels a tool before the second click"),
        ("<b>Saved views</b>", "Camera → Save view… stores the camera; click it later to fly back "
                               "(also " + key("Cmd") + " " + key("1") + " … " + key("9") + ", saved in the project)"),
        ("<b>Command palette</b> " + key("Cmd") + " " + key("K"), "type a few letters, for example "
                                                                  "\"algn\", and press Enter"),
        ("<b>History</b>", "the History tab lists every step; click one to jump back to it"),
    ]), False),

    ("Cleaning scans", keys_table([
        ("<b>Delete points</b> " + key("L"), "draw around fish, bubbles or anything else that does not belong; "
                                             "everything inside the outline is removed, at every depth"),
        ("<b>Keep only</b> " + key("Shift") + " " + key("L"), "draw around the part you want to compare; "
                                                              "the rest is removed (crop)"),
        ("<b>Remove stray points</b>", "Edit menu: removes single points far away from their neighbours"),
        ("<b>Protect a scan</b>", "hide it first (" + key("1") + " / " + key("2") + "): hidden scans are never cleaned"),
        ("<b>Undo</b>", key("Cmd") + " " + key("Z") + " puts every removed point back exactly where it was"),
        ("<b>Very big scans</b>", "above 8 million points the view draws an evenly spread part, alignment, "
                                  "detection and measuring still use every point (Settings → Draw at most)"),
    ]), False),

    ("Sharing results", keys_table([
        ("<b>Change report</b>", "File → Export → Change Report (PDF): summary, a picture of the scene, "
                                 "a table and close-ups of the changed areas, and your notes"),
        ("<b>Turntable</b>", "File → Export → Turntable Animation: the camera circles once around the "
                             "scene, saved as a GIF that plays in any browser or presentation"),
        ("<b>Screenshot</b>", "File → Export → Screenshot saves exactly what the 3D view shows"),
    ]) + '<p style="margin:8px 0 0 0;">' + dim("Run Detect Changes first, so the report can list the changed areas.")
     + "</p>", False),

    ("Colours and highlights", keys_table([
        ("<b>Per scan</b>", "A and B in their own colour (click a swatch to change it)"),
        ("<b>Depth</b>", "depth below the water surface, shallow red to deep blue"),
        ("<b>Change</b>", "after Detect changes: blue removed, white unchanged, red added"),
        ("<b>Changed points</b>", "highlight of what was detected, colour can be picked"),
        ("<b>Show true change</b>", "where the change really is (example scenes only)"),
        ("<b>Background</b>", "click the swatch in Clouds to change it"),
        ("<b>Depth shading</b>", "gives dense scans more relief (eye-dome lighting)"),
        ("<b>Status bar</b>", "shows x, y and depth of the point under the mouse"),
    ]), False),

    ("Using your own scans", P +
     "Use <b>File → Import Two Scans</b> or drop two files on the window: the earlier scan is A, the later "
     "one B. The Import window shows what each file is and lets you check the settings.</p>" + keys_table([
         ("<b>Point clouds</b>", "LAS, LAZ, E57, PLY, PCD, PTS"),
         ("<b>Text tables</b>", "XYZ, TXT, CSV, DAT with any separator: pick which column is x, y, z "
                                "and intensity, the preview shows the result"),
         ("<b>Depth grids</b>", "GeoTIFF and ESRI ASCII grids: one point per cell"),
         ("<b>Meshes</b>", "OBJ, STL, PLY meshes: points are spread over the surface"),
         ("<b>Units</b>", "metres, centimetres, millimetres, feet or US survey feet"),
         ("<b>Depth direction</b>", "found automatically; choose it yourself if the seabed comes out upside down"),
         ("<b>Survey coordinates</b>", "big UTM numbers are shifted for smooth drawing, the status bar, notes "
                                       "and the report still show the real ones"),
         ("<b>Intensity</b>", "if the files have it: Colours → Intensity shows the sonar return strength"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "Raw multibeam recordings (.xtf, .gsf, .s7k, .all) have to be processed in your sonar software "
         "first: export the cleaned survey as LAS/LAZ, XYZ or CSV.") + "</p>",
     False),

    ("Tips and troubleshooting", keys_table([
        ("<b>Everything is changed</b>", "align first, or the threshold is too low"),
        ("<b>Nothing is found</b>", "the change may be smaller than the noise: lower the threshold"),
        ("<b>Alignment looks off</b>", "try the other Method, raise Max rounds or the Match distance"),
        ("<b>Lots of tiny areas</b>", "raise Smallest area, big scans find many small fringe pieces"),
        ("<b>Too slow</b>", "use fewer points; ICP already thins big scans to 50k points"),
        ("<b>Lost in the scene</b>", "press " + key("R") + " to reset the view"),
    ]), False),
]
