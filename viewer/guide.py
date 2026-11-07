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
     "It compares two underwater surveys of the same place, made at different times: "
     "<b>Inspection A</b> (before) and <b>Inspection B</b> (after). It lines them up and "
     "then shows what changed between them, like scour holes, fallen objects or damaged walls."
     "</p>" + P + dim(
         "Until real survey data is available, the app comes with simulated underwater "
         "scenes in which the real change is known, so you can check how well everything works.") + "</p>",
     True),

    ("Quick start", steps([
        "Pick a scene under <b>Scene</b>, for example <i>Quay wall – dropped object</i>.",
        "Press <b>Align B to A</b> and watch survey B slide onto survey A.",
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

    ("Keyboard shortcuts", keys_table([
        (key("W") + key("A") + key("S") + key("D"), "move"),
        (key("Q") + " " + key("E"), "down / up"),
        (key("Shift"), "move faster"),
        (key("M"), "switch orbit / fly"),
        (key("1") + " " + key("2"), "show or hide inspection A / B"),
        (key("R"), "reset the view"),
        (key("Space"), "show or hide this panel"),
        (key("Ctrl") + " / " + key("Cmd") + " + " + key("O"), "open two scans"),
    ]), False),

    ("Example scenes", P +
     "Every scene is two simulated sonar surveys of the same place, with a known change in between. "
     "The list shows the size of each scene.</p>" + keys_table([
         ("<b>Size</b>", "number of points per survey"),
         ("<b>Sensor noise</b>", "measurement error close to the sonar (it grows with distance)"),
         ("<b>Stray points</b>", "share of false echoes in the water, like fish or bubbles"),
         ("<b>Ping stripes</b>", "the stripy density pattern of the sonar pings"),
         ("<b>Variation</b>", "another random version of the same scene (" + dim("Random") + " picks one)"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim("Changes apply right away, there is nothing to confirm.") + "</p>",
     False),

    ("Survey B position", P +
     "A real survey is never made from exactly the same spot twice. The <b>Survey B position</b> "
     "card simulates that: survey B is <b>turned</b> (degrees) and <b>shifted</b> (metres) "
     "compared to A.</p>" + keys_table([
         ("<b>Same as A</b>", "no difference at all, B lies exactly on A"),
         ("<b>Random position</b>", "a new random turn and shift"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "<b>Align B to A</b> has to undo this. A bigger difference is harder: try a large turn "
         "and see when the alignment stops working.") + "</p>",
     False),

    ("Aligning the surveys", P +
     "Two surveys are never made from exactly the same position, so B first has to be moved onto A. "
     "<b>Align B to A</b> does this with ICP: it pairs every point of B with the closest point of A "
     "and moves B a little closer, round after round.</p>" + keys_table([
         ("<b>Match distance</b>", "points further apart than this are not paired up"),
         ("<b>Max rounds</b>", "ICP stops earlier when nothing changes any more"),
         ("<b>RMSE</b>", "average distance of the pairs, lower is better"),
         ("<b>Fitness</b>", "share of points that found a partner"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "Long flat walls need many rounds (about 200), there is little to hold on to along the wall. "
         "Big changes can pull the alignment a few centimetres off.") + "</p>",
     False),

    ("Finding changes", P +
     "<b>Detect changes</b> measures how far every point is from the other survey's surface. "
     "Points further than the <b>threshold</b> count as changed and are grouped into areas.</p>" + keys_table([
         ("<b>Auto threshold</b>", "picked from the noise in the data (recommended)"),
         ("<b>Smallest area</b>", "smaller groups of changed points are ignored as noise"),
         ("<b>+ added</b>", "something new: an object, sediment, a bulge"),
         ("<b>&minus; removed</b>", "something gone: scour, a hole, a missing rock"),
     ]) + '<p style="margin:8px 0 0 0;">' + dim(
         "Always align first, otherwise the misalignment itself looks like change. "
         "For example scenes the panel also says how much of the true change was found.") + "</p>",
     False),

    ("Colours and highlights", keys_table([
        ("<b>Per inspection</b>", "A and B in their own colour (click a swatch to change it)"),
        ("<b>Depth</b>", "depth below the water surface, shallow red to deep blue"),
        ("<b>Change</b>", "after Detect changes: blue removed, white unchanged, red added"),
        ("<b>Changed points</b>", "highlight of what was detected, colour can be picked"),
        ("<b>Show true change</b>", "where the change really is (example scenes only)"),
        ("<b>Background</b>", "click the swatch in Clouds to change it"),
    ]), False),

    ("Using your own scans", P +
     "Use <b>File → Open two scans</b> (or the last entry in the scene list). You are asked for "
     "the earlier scan first (A), then the later one (B). Supported files: "
     "<b>.ply .pcd .xyz .pts</b>.</p>" + P + dim(
         "Then align and detect changes as with the examples. There is no true change to compare "
         "with for your own data.") + "</p>",
     False),

    ("Tips and troubleshooting", keys_table([
        ("<b>Everything is changed</b>", "align first, or the threshold is too low"),
        ("<b>Nothing is found</b>", "the change may be smaller than the noise: lower the threshold"),
        ("<b>Alignment looks off</b>", "raise Max rounds, or try a bigger Match distance"),
        ("<b>Too slow</b>", "use fewer points; ICP already thins big scans to 50k points"),
        ("<b>Lost in the scene</b>", "press " + key("R") + " to reset the view"),
    ]), False),
]
