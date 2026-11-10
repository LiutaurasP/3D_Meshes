# PyInstaller recipe for Subdron Sonar Studio. Run packaging/build.py instead of using this directly.

import sys
from pathlib import Path

HERE = Path(SPECPATH)
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from viewer.branding import APP_NAME, ORGANIZATION, PROJECT_EXTENSION, VERSION  # noqa: E402

ICONS = HERE / "icons"
# Made from the names PyVista uses: every VTK module it may load while the app runs
VTK_MODULES = ["vtkmodules." + name for name in (HERE / "vtk_modules.txt").read_text().split()]
BUNDLE_ID = "com.subdron.sonarstudio"
PROJECT_TYPE = "com.subdron.sonarstudio.project"

analysis = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "viewer" / "assets"), "viewer/assets"),
        (str(ROOT / "viewer" / "icons"), "viewer/icons"),
    ],
    # Only the VTK parts PyVista can use (vtk_modules.txt), not all of VTK: about half the size
    hiddenimports=["pyvistaqt", "vtkmodules.util.data_model", "vtkmodules.util.execution_model",
                   "laspy", "lazrs", "pye57", "tifffile",
                   "m3c2", "py4dgeo", "_py4dgeo"] + VTK_MODULES,  # M3C2 is only imported when it is picked
    # Dash and its web server: Open3D imports Dash only for its browser viewer,
    # no_dash.py puts a small stand-in in its place (plotly stays for "Open in Plotly")
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "notebook", "pytest", "pyarrow", "vtk",
              "vtkmodules.all", "dash", "flask", "werkzeug", "itsdangerous", "blinker"],
    runtime_hooks=[str(HERE / "no_dash.py")],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=str(ICONS / ("app_icon.icns" if sys.platform == "darwin" else "app_icon.ico")),
)

app_folder = COLLECT(exe, analysis.binaries, analysis.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        app_folder,
        name=f"{APP_NAME}.app",
        icon=str(ICONS / "app_icon.icns"),
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHumanReadableCopyright": f"© {ORGANIZATION}",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            # .subdron project files open in this app and get its icon in the Finder
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": f"{APP_NAME} Project",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": [PROJECT_TYPE],
                "CFBundleTypeIconFile": "app_icon.icns",
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": PROJECT_TYPE,
                "UTTypeDescription": f"{APP_NAME} Project",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeIconFile": "app_icon.icns",
                "UTTypeTagSpecification": {"public.filename-extension": [PROJECT_EXTENSION.lstrip(".")]},
            }],
        },
    )
