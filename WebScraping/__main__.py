"""python -m WebScraping   (or, from the project folder: python WebScraping)"""

import sys
from pathlib import Path

if not __package__:  # started as "python WebScraping": the folder is not a package Python knows yet
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from WebScraping.cli import main

sys.exit(main())
