"""python -m LocalExtraction   (or, from the project folder: python LocalExtraction)"""

import sys
from pathlib import Path

if not __package__:  # started as "python LocalExtraction": the folder is not a package Python knows yet
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from LocalExtraction.cli import main

sys.exit(main())
