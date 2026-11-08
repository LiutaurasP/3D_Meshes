to launch iOS/Linux: 
1) "bash setup.sh" in the terminal to download dependencies
2) run main.py

to launch Windows:
1) ".\setup.ps1" in the terminal to download dependencies.
2) run main.py

Subdron Sonar Studio (desktop app):
run app.py (after the setup above). It uses Qt + PyVista for the window and Open3D for the data.
Projects are saved as .subdron files (File > Save), with undo / redo for almost every action.
The Plotly viewer from main.py still works as before.
New to the app? The start screen (or Help > Tutorial) has a 5-minute step-by-step tutorial.
Know the basics? The Guide (or Help > Advanced Tutorial) has "The Storm Season": six chapters
on a wind turbine foundation scanned four times (Timeline, cleaning, measuring, reporting).
Quick check that the viewer works on your machine: python tests/smoke_test.py

Tools in the app: before/after swipe (B), cross section (X), measure (T),
notes pinned in 3D (N), saved camera views, command palette (Cmd/Ctrl+K),
History tab. File > Export makes a PDF change report, a turntable GIF or a
screenshot. The Guide tab in the side panel explains everything.

More than two scans of one place (File > Import Scan Series, or drop 3+ files on
the window; they are ordered by the date in their names): the Timeline compares
any two, the Scans card shows all of them at once (keys 1-9), "Align and compare
all" follows every changed area through time (Areas tab: trend, rate per month,
chart), Colours > When changed shows in which scan each spot first changed, and
the PDF report gets a "Change over time" chapter.

Command line (no window), for many scans at once:
    python sonar_cli.py compare before.laz after.laz --out results --report --csv --geojson
    python sonar_cli.py series scans_folder --out results
Reads every format the app reads (LAS/LAZ, E57, PLY, PCD, XYZ/CSV, GeoTIFF, ...),
aligns, detects changes, measures volumes and writes reports, tables and the
aligned scan. series compares every scan with the first and with the one
before and writes series_summary.csv. python sonar_cli.py -h lists all options.

Building the desktop app (packaging/):
    pip install pyinstaller
    python packaging/build.py
macOS gives dist/Subdron Sonar Studio.app, Windows gives
dist/Subdron Sonar Studio/Subdron Sonar Studio.exe. For a Windows installer
that also opens .subdron files on double click, compile
packaging/windows_installer.iss with Inno Setup afterwards.
The app is not signed: on macOS right click > Open the first time.
build.py starts the finished app once with --self-test (align, detect, report,
exports) and fails if anything is missing in the package.
On GitHub: Actions > Build app > Run workflow (or push a tag like v0.2.0)
builds both apps; download them from the run's Artifacts.

Problems: unexpected errors are written to a log file (Help > Show Log File)
instead of closing the app.

Example data (datasets/):
Synthetic underwater scan scenes (harbour wall, sheet pile wall, bridge pier,
harbour basin, quay wall) with a known change between scan A and B. Pick them
in the Scene card of the app, or use them from Python:
    from datasets import generate
    pair = generate("harbour_wall_scour")

Change detection (change_detection.py):
Compares two aligned scans, marks changed points (with a threshold set
automatically from the noise) and groups them into areas:
    from change_detection import detect_changes
    result = detect_changes(cloud_a, aligned_cloud_b)
In the app: align first, then "Detect changes" in the Change detection panel.

Tests: python -m pytest tests (needs: pip install pytest)
