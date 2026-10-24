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
CRYSTAL_STRUCTURE = "crystal_structure"      # the known crystal families: NASICON, LISICON, garnet, argyrodite, ...
STRUCTURE_FAMILIES = "structure_families"    # oxide, sulfide, halide, oxyhalide, nitride, hydride, ...
UNCLASSIFIED = "unclassified"   # only while a material is being classified: none is left so
