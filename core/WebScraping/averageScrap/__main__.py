"""python -m WebScraping   (or, from the project folder: python WebScraping)"""

import sys
from pathlib import Path

if not __package__:  # started as "python WebScraping": the folder is not a package Python knows yet
    _root = Path(__file__).resolve().parents[3]  # the repository: its packages are in core/, export/, app/
    sys.path[0:1] = [str(_root / group) for group in ("core", "export", "app")]

from WebScraping.averageScrap.cli import main

sys.exit(main())
