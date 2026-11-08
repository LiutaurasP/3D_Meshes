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
Quick check that the viewer works on your machine: python tests/smoke_test.py

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
