# Crystal and Structure Classification/about.py
"""The name of the part, where it reads, and where it writes."""

from pathlib import Path

NAME = "Crystal and Structure Classification"
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

# The databases the two extraction parts write, the most trusted first (your own PDFs, then the web).
DEFAULT_SOURCES = (PROJECT_ROOT / "LocalExtraction" / "local_output", PROJECT_ROOT / "WebScraping" / "web_output")
DEFAULT_OUT = PACKAGE_DIR

# The two ways a material is classified, and the folder each one is written to.
CRYSTAL_STRUCTURE = "crystal_structure"      # NASICON, LISICON, garnet, argyrodite, LGPS-type, ...
STRUCTURE_FAMILIES = "structure_families"    # oxide, sulfide, halide, oxyhalide, nitride, hydride, ...
UNCLASSIFIED = "unclassified"   # only while a material is being classified: none is left so
# The classes of the last step — a composition type, "A3MX6 halide" — sit in a folder of their own
# inside crystal_structure/, apart from the named structure types.
COMPOSITION_TYPES = "composition_types"
