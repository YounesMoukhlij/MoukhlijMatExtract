"""python -m Evaluation sheet | score | agree      (or: mme-eval …; make eval-sheet, eval-score, eval-agree)"""

import sys
from pathlib import Path

if not __package__:  # started as "python Evaluation": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from Evaluation.cli import main

sys.exit(main())
