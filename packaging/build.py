"""Build Subdron Sonar Studio as a desktop app.

    python packaging/build.py

macOS:   dist/Subdron Sonar Studio.app   (double click .subdron files to open them)
Windows: dist/Subdron Sonar Studio/Subdron Sonar Studio.exe
         then packaging/windows_installer.iss with Inno Setup for an installer
         that also registers .subdron files

Needs PyInstaller in the same environment: python -m pip install pyinstaller
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ICONS = HERE / "icons"  # made here, not committed


def make_icons():
    """.icns for macOS and .ico for Windows from the app icon PNG."""
    ICONS.mkdir(exist_ok=True)
    image = Image.open(ROOT / "viewer" / "assets" / "app_icon.png").convert("RGBA")
    image.save(ICONS / "app_icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        image.resize((1024, 1024), Image.LANCZOS).save(ICONS / "app_icon.icns")


def main():
    make_icons()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
               str(HERE / "sonar_studio.spec")]
    subprocess.run(command, check=True, cwd=ROOT)
    print("\nDone, the app is in", ROOT / "dist")
    if "--no-self-test" not in sys.argv:  # GitHub's Mac machines cannot draw 3D, the check is skipped there
        self_test()


def self_test():
    """Start the built app once: it aligns and detects the example scene, then quits."""
    name = "Subdron Sonar Studio"
    if sys.platform == "darwin":
        program = ROOT / "dist" / f"{name}.app" / "Contents" / "MacOS" / name
    else:
        program = ROOT / "dist" / name / f"{name}.exe"
    result = subprocess.run([str(program), "--self-test"], capture_output=True, text=True, timeout=300)
    lines = [line for line in result.stdout.splitlines() if line.startswith("SELF-TEST")]
    print(lines[-1] if lines else f"SELF-TEST FAILED (exit {result.returncode})\n{result.stderr[-2000:]}")
    if result.returncode != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
