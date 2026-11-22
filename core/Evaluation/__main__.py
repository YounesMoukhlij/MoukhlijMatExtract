"""python -m Evaluation sheet | score | agree      (or: mme-eval …; make eval-sheet, eval-score, eval-agree)"""

import sys
from pathlib import Path

if not __package__:  # started as "python Evaluation": make the project root importable
    _root = Path(__file__).resolve().parents[2]  # the repository: its packages are in core/, export/, app/
    sys.path[0:1] = [str(_root / group) for group in ("core", "export", "app")]

from Evaluation.cli import main

sys.exit(main())
