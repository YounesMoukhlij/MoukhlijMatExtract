# mme_gui/macapp.py
"""MoukhlijMatExtract as a Mac app: ~/Applications/MoukhlijMatExtract.app, which opens the main window with the
program's own name and icon in the Dock, the app switcher and the menu bar.

Why a bundle: macOS names a program that is not an app after its executable (“python3.13”), and the Dock reads that
name when the program starts — renaming it afterwards does not reach the Dock. Started from the bundle, the program is
registered as MoukhlijMatExtract.app, whose name and icon the Dock shows.

The bundle holds no copy of the program: its launcher runs this Python (the one that made it) with this environment's
packages, so updating the project updates the app. Make it again after moving the project or its Python:
`mme-gui --install-app` (or `make app`)."""

from __future__ import annotations

import os
import plistlib
import shutil
import site
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

NAME = "MoukhlijMatExtract"
IDENTIFIER = "org.moukhlijmatextract.mme"
DEFAULT = Path.home() / "Applications" / f"{NAME}.app"
# A Mac app opened from the Finder or the Dock gets a short PATH: the usual places of Tesseract and other tools.
_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def launcher(python: str, site_dirs: list) -> str:
    """The script the app runs: this Python, through a link inside the bundle (so macOS takes the program for the
    app), with this environment's packages, opening the main window."""
    dirs = ", ".join(repr(str(d)) for d in site_dirs)
    return ("#!/bin/sh\n"
            "# MoukhlijMatExtract.app: opens the main window (made by mme-gui --install-app).\n"
            f'export PATH="{_PATH}:$PATH"\n'
            'HERE="$(cd "$(dirname "$0")" && pwd)"\n'
            f'exec "$HERE/python" -c "import site, sys\n'
            f'for d in [{dirs}]: site.addsitedir(d)\n'
            "sys.argv = ['mme-gui']\n"
            "import runpy; runpy.run_module('mme_gui', run_name='__main__')\"\n")


def info(version: str) -> dict:
    return {"CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleExecutable": NAME,
            "CFBundleIdentifier": IDENTIFIER, "CFBundlePackageType": "APPL", "CFBundleIconFile": f"{NAME}.icns",
            "CFBundleShortVersionString": version or "1.0", "CFBundleVersion": version or "1.0",
            "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"}


def icns(png: Path, out: Path) -> bool:
    """The app's icon (.icns) from the program's PNG, with macOS's own sips and iconutil."""
    if not (shutil.which("sips") and shutil.which("iconutil") and png.is_file()):
        return False
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work) / "icon.iconset"
        folder.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(pixels), str(pixels), str(png), "--out", str(folder / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(folder), "-o", str(out)], check=True, capture_output=True)
    return out.is_file()


def build(dest: Optional[Path] = None, python: Optional[str] = None, register: bool = True) -> Path:
    """Writes the app (replacing one already there). Returns its path."""
    if sys.platform != "darwin":
        raise RuntimeError("The Mac app is for macOS; elsewhere, start the program with mme-gui.")
    dest = Path(dest or DEFAULT)
    python = os.path.realpath(python or sys.executable)
    site_dirs = [d for d in site.getsitepackages() if Path(d).is_dir()]
    staging = dest.with_name(f".{dest.name}.writing")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "Contents" / "MacOS").mkdir(parents=True)
    (staging / "Contents" / "Resources").mkdir()
    executable = staging / "Contents" / "MacOS" / NAME
    executable.write_text(launcher(python, site_dirs), encoding="utf-8")
    executable.chmod(0o755)
    os.symlink(python, staging / "Contents" / "MacOS" / "python")
    from LocalExtraction.about import version
    from LocalExtraction.gui.design import ICON
    icns(Path(ICON), staging / "Contents" / "Resources" / f"{NAME}.icns")
    with open(staging / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info(version() or ""), f)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    staging.replace(dest)
    tool = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/"
            "lsregister")
    if register and os.path.exists(tool):  # the Finder and the Dock learn of it (its icon) at once
        subprocess.run([tool, "-f", str(dest)], capture_output=True)
    return dest
