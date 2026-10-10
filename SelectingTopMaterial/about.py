# SelectingTopMaterial/about.py
"""The name and version of the program, and where it lives in the project."""

from pathlib import Path

NAME = "SelectingTopMaterial"
VERSION = "1.0.0"

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_RESULTS = PACKAGE_DIR / "results"
