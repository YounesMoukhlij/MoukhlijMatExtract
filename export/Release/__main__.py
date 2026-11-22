"""python -m Release       (or: mme-release; make release)"""

import sys
from pathlib import Path

if not __package__:  # started as "python Release": make the project root importable
    _root = Path(__file__).resolve().parents[2]  # the repository: its packages are in core/, export/, app/
    sys.path[0:1] = [str(_root / group) for group in ("core", "export", "app")]

from Release.cli import main

sys.exit(main())
