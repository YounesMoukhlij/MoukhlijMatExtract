# SelectingTopMaterial/about.py
"""The name and version of the program, and where it lives in the project."""

from pathlib import Path

from LocalExtraction.about import PROJECT_HOME, version

NAME = "SelectingTopMaterial"
VERSION = version() or "dev"  # the version of MoukhlijMatExtract it is part of

PACKAGE_DIR = Path(__file__).resolve().parent     # where the code and its data (criteria.toml) live
# The databases and the results live in ~/MoukhlijMatExtract — not where the package is installed,
# nor where it is started from — so it always reads part 1/2's database and writes its results there.
PROJECT_ROOT = PROJECT_HOME
DEFAULT_RESULTS = PROJECT_ROOT / NAME / "results"
