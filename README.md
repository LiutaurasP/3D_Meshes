to launch iOS/Linux: 
1) "bash setup.sh" in the terminal to download dependencies
2) run main.py

to launch Windows:
1) ".\setup.ps1" in the terminal to download dependencies.
2) run main.py

Desktop viewer:
run app.py (after the setup above). It uses Qt + PyVista for the window and Open3D for the data.
The Plotly viewer from main.py still works as before.
Quick check that the viewer works on your machine: python tests/smoke_test.py
