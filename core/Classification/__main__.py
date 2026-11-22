"""python -m Classification        (from the project root; the window: python -m Classification gui)

Part 4 of MoukhlijMatExtract — Crystal and Structure Classification."""

import sys
from pathlib import Path

if not __package__:  # started as "python Classification": make the project root importable
    _root = Path(__file__).resolve().parents[2]  # the repository: its packages are in core/, export/, app/
    sys.path[0:1] = [str(_root / group) for group in ("core", "export", "app")]

from Classification.cli import main

sys.exit(main())
