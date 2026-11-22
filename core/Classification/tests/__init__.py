"""The folder of the classification has spaces in its name, so it cannot be imported by it: the
tests know it, as __main__.py does, as the package `Classification`."""

import importlib.util
import sys
from pathlib import Path

if "Classification" not in sys.modules:
    _FOLDER = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_FOLDER.parent))  # the project root: LocalExtraction is imported from there
    _spec = importlib.util.spec_from_file_location("Classification", _FOLDER / "__init__.py",
                                                   submodule_search_locations=[str(_FOLDER)])
    _package = importlib.util.module_from_spec(_spec)
    sys.modules["Classification"] = _package
    _spec.loader.exec_module(_package)
