"""python -m Classification        (from the project root; the window: python -m Classification gui)

Part 4 of MoukhlijMatExtract — Crystal and Structure Classification."""

import sys
from pathlib import Path

if not __package__:  # started as "python Classification": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from Classification.cli import main

sys.exit(main())
