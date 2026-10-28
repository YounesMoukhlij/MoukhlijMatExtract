# SelectingTopMaterial/about.py
"""The name and version of the program, and where it lives in the project."""

from pathlib import Path

NAME = "SelectingTopMaterial"
VERSION = "1.0.0"

PACKAGE_DIR = Path(__file__).resolve().parent     # where the code and its data (criteria.toml) live
# The databases and the results live in the folder the user runs in — not where the package is
# installed — so an installed copy reads part 1/2's database and writes its own results there too.
PROJECT_ROOT = Path.cwd()
DEFAULT_RESULTS = PROJECT_ROOT / NAME / "results"
