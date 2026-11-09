"""python -m WebScraping            search the open sources, download, extract — from the terminal
   python -m WebScraping gui        the same, in a window

`gui` opens the Web scraping window; everything else is the command line (WebScraping.averageScrap.cli)."""

import sys
from pathlib import Path

if not __package__:  # started as "python WebScraping": make the project root importable
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

argv = sys.argv[1:]
if argv and argv[0] == "gui":  # the window, with its options (--job, --output, --workers, --verbose)
    from WebScraping.webgui import main as gui_main
    gui_main(argv[1:])
    sys.exit(0)

from WebScraping.averageScrap.cli import main

sys.exit(main(argv))
