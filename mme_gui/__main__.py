"""python -m mme_gui   (from the project root; or: make gui)"""

import sys
from pathlib import Path

if not __package__:  # started as "python mme_gui": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from mme_gui.hub import main

main()
