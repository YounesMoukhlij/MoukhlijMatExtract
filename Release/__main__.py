"""python -m Release       (or: mme-release; make release)"""

import sys
from pathlib import Path

if not __package__:  # started as "python Release": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from Release.cli import main

sys.exit(main())
