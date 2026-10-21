"""python "Crystal and Structure Classification"   (from the project root)

A folder name with spaces cannot be imported by `python -m`, so the folder is run as it is:
Python starts this file, which makes the folder known as the package `Classification` — the name
its modules import each other by — and runs the command line."""

import importlib.util
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent

if __package__ in (None, ""):
    sys.path[0] = str(FOLDER.parent)  # the project root: LocalExtraction is imported from there
    spec = importlib.util.spec_from_file_location("Classification", FOLDER / "__init__.py",
                                                  submodule_search_locations=[str(FOLDER)])
    package = importlib.util.module_from_spec(spec)
    sys.modules["Classification"] = package
    spec.loader.exec_module(package)
    from Classification.cli import main
else:
    from .cli import main

sys.exit(main())
