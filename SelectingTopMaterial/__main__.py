# SelectingTopMaterial/__main__.py
"""python -m SelectingTopMaterial   (or, from the project folder: python SelectingTopMaterial)"""

import sys
from pathlib import Path

if not __package__:  # started as "python SelectingTopMaterial": the folder is not a package Python knows yet
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from SelectingTopMaterial.cli import main

sys.exit(main())
