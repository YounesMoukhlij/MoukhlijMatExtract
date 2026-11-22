# SelectingTopMaterial/__main__.py
"""python -m SelectingTopMaterial   (or, from the project folder: python SelectingTopMaterial)"""

import sys
from pathlib import Path

if not __package__:  # started as "python SelectingTopMaterial": the folder is not a package Python knows yet
    _root = Path(__file__).resolve().parents[2]  # the repository: its packages are in core/, export/, app/
    sys.path[0:1] = [str(_root / group) for group in ("core", "export", "app")]

from SelectingTopMaterial.cli import main

sys.exit(main())
