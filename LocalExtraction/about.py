# LocalExtraction/about.py
"""The name and author of the program, the project folder every part works in, and where Project 1
reads and writes unless told otherwise."""

import os
import sys
import textwrap
from pathlib import Path

NAME = "MoukhlijMatExtract"
ABBREVIATION = "MME"
FULL_NAME = f"{NAME} ({ABBREVIATION})"
AUTHOR = "Younes Moukhlij"
CREDIT_TEXT = (f"{FULL_NAME} — Created by {AUTHOR} "
               "(Software Engineering student at 1337 Coding School, "
               "PhD researcher at FPK, USMS)")
DESCRIPTION = (
    "Turns a folder of battery-materials PDFs (solid electrolytes, cathodes, anodes) into a structured, queryable database: "
    "parses text, tables, figures and equations (with OCR fallback for scanned pages), extracts "
    "materials and their properties, and exports linked CSV, Excel and JSON."
)

# The "About" of the windows: the project and its author, and where to find them.
REPOSITORY = "https://github.com/YounesMoukhlij/MoukhlijMatExtract"
# The project's website: how to use the program, step by step, and an overview of the project. Every window links to
# it (its footer); the main window announces it when it opens.
WEBSITE = "https://moukhlijmatextract.vercel.app"
CONTACT_EMAIL = "younes.moukhlij@usms.ac.ma"
LICENSE_NAME = "GNU AGPL-3.0-or-later"
ABOUT_PROJECT = (
    f"{FULL_NAME} is an open-source research tool for mining the scientific literature on solid-state "
    "electrolytes. It reads papers — your own PDFs, or articles found and retrieved online from open "
    "sources — and extracts their ion-transport data (activation energies, ionic and electronic "
    "conductivities, diffusion coefficients) into a structured database, recording the source of every "
    "value. The materials are then ranked by activation energy and classified by crystal-structure type "
    "and structure family, to support the data-driven screening of candidate electrolytes."
)
ABOUT_AUTHOR = (
    f"{AUTHOR} is a PhD researcher working on solid-state electrolytes at the Faculté Polydisciplinaire de "
    "Khouribga (FPK), Université Sultan Moulay Slimane (USMS), and a software-engineering student at "
    f"1337 Coding School. {ABBREVIATION} brings the two together: software engineering put to work for "
    "materials research."
)
CITE_TEXT = f"If you use {ABBREVIATION} in your research, please cite it (CITATION.cff in the repository)."


def command_name(command: str, module: str) -> str:
    """The name to show in a part's help: its mme-* command when started that way (mme-rank), or when the
    manual reads the help (MME_AS_COMMAND: the manual shows the commands a user types), else how it was
    started (python -m SelectingTopMaterial)."""
    if os.environ.get("MME_AS_COMMAND") or Path(sys.argv[0]).name.startswith(command):
        return command
    return f"python -m {module}"


def version_text(command: str = "") -> str:
    """What `--version` prints, the same for every command: "MoukhlijMatExtract 1.0.3 (mme-rank)"."""
    return f"MoukhlijMatExtract {version() or 'dev'}" + (f" ({command})" if command else "")


def version() -> str:
    """The installed version of the package; "" when it is run from a copy that is not installed."""
    try:
        from importlib.metadata import version as installed
        return installed("moukhlijmatextract")
    except Exception:  # PackageNotFoundError, or no metadata at all
        return ""


# Every command works inside ~/MoukhlijMatExtract, whatever folder it is started from, so the parts
# always find each other's files. The folders each part makes there, if missing, when it starts:
PROJECT_HOME = Path.home() / NAME
PART_FOLDERS = {
    "local": ("LocalExtraction/papers", "LocalExtraction/local_output"),
    "web": ("WebScraping/papers", "WebScraping/web_output"),
    "dois": ("WebScraping/Fetch_DOIs",),
    "rank": ("SelectingTopMaterial/results",),
    "classify": ("Classification/crystal_structure", "Classification/structure_families"),
    "eval": ("Evaluation",),
}

# Relative to PROJECT_HOME.
DEFAULT_INPUT = os.path.join("LocalExtraction", "papers")
DEFAULT_OUTPUT = os.path.join("LocalExtraction", "local_output")


def require_tk(command: str) -> None:
    """Stops with how to install Tk, the window toolkit, when this Python was built without it (Homebrew's
    Python, some Linux ones), in place of a traceback. The terminal commands do not need it."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise SystemExit(
            f"{command} needs Tk, the window toolkit, which this Python does not have. Install it, then try again:\n"
            f"  macOS (Homebrew Python): brew install python-tk@{version}\n"
            "  Ubuntu/Debian:           sudo apt install python3-tk\n"
            "The terminal commands (mme-local extract, mme-web run, mme-rank, mme-classify, …) work without it.")


def found_here(path):
    """A path named on the command line, made ready for the move into PROJECT_HOME. Relative paths are read from
    the home folder, so one naming a file there is kept as it is; one naming a file only in the folder the command
    was started from (configs/my_job.yaml of a source checkout) is made absolute, so the move does not lose it.
    Anything else is left as it is, for the command to say what is missing."""
    if not path:
        return path
    given = Path(path)
    if given.is_absolute() or (PROJECT_HOME / given).exists() or not given.exists():
        return path
    return type(path)(given.resolve()) if isinstance(path, Path) else str(given.resolve())


def enter_project_home(*parts: str) -> Path:
    """Makes ~/MoukhlijMatExtract and the folders of these parts (keys of PART_FOLDERS) when they are
    missing, then works from there, so every relative path of the project lands inside it."""
    PROJECT_HOME.mkdir(parents=True, exist_ok=True)
    for part in parts:
        for folder in PART_FOLDERS[part]:
            (PROJECT_HOME / folder).mkdir(parents=True, exist_ok=True)
    # configs/ (the job files, made when missing) and docs/ (the manuals, kept up to date), shipped with the package.
    from mme_home import populate
    populate(PROJECT_HOME)
    os.chdir(PROJECT_HOME)
    from .crashlog import install
    install()  # an error the program did not expect: written to ~/MoukhlijMatExtract/logs/, said where
    return PROJECT_HOME


def print_banner(title: str, description: str) -> None:
    """Prints a small decorated header to the console: the title, a one-line description and the
    author credit (see CREDIT_TEXT for the plain-text version used in --help, where box-drawing
    characters would look out of place)."""
    body_lines = (
        textwrap.wrap(description, width=58)
        + [""]
        + [
            AUTHOR,
            "Software Engineering student · 1337 Coding School",
            "PhD Researcher · FPK, USMS",
        ]
    )
    width = max(len(title), *(len(l) for l in body_lines)) + 4

    print("╭" + "─" * width + "╮")
    print("│ " + title.center(width - 2) + " │")
    print("├" + "─" * width + "┤")
    for l in body_lines:
        print("│ " + l.center(width - 2) + " │")
    print("╰" + "─" * width + "╯")
