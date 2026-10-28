"""python -m WebScraping            method 1 (open-source search) from the terminal
   python -m WebScraping gui        the two-method chooser window

Run from the project root. `gui` opens the chooser (search open sources, or moukhlij4scraping);
everything else is the command line of method 1 (WebScraping.averageScrap.cli)."""

import sys
from pathlib import Path

if not __package__:  # started as "python WebScraping": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

argv = sys.argv[1:]
if argv and argv[0] == "gui":
    from WebScraping.webgui import main as gui_main
    gui_main()
    sys.exit(0)

from WebScraping.averageScrap.cli import main

sys.exit(main(argv))
