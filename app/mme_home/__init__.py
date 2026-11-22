# mme_home/__init__.py
"""What a user's ~/MoukhlijMatExtract holds besides the results, made there by the program:

    configs/   the job files of the web search: sse, cathode and anode, and one per family of solid electrolytes
               (garnet, NASICON, LISICON, …, and garnet_nasicon). Made when missing, never written over: they are the
               user's to edit ("Search settings…" in the Web scraping window).
    docs/      the manual, the command reference, the data dictionary, the limitations and the evaluation protocol.
               Brought up to date when the installed version differs: they are read, not edited.

Where they come from: the repository's configs/ and docs/ folders. Building the package copies them into it
(setup.py), so an installed copy has them inside mme_home/; a source checkout reads them from the repository. The
first start of any command or window copies them into the home folder (LocalExtraction.about.enter_project_home);
the main window says when they are missing and makes them again with one button (mme_gui.hub)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

CONFIGS, DOCS = "configs", "docs"
SUFFIX = {CONFIGS: ".yaml", DOCS: ".md"}
MAINTAINER_ONLY = {"PUBLISHING.md"}  # in the repository's docs/, not for a user's folder
_HERE = Path(__file__).resolve().parent
_SOURCE = _HERE.parents[1]  # the repository, when the code runs from a checkout
_IN_SOURCE = {"configs": _SOURCE / "resources" / "configs", "docs": _SOURCE / "docs"}  # where each kind is there


def folder(kind: str) -> Path:
    """Where the shipped files of `kind` are: inside the installed package, or the repository's own folder."""
    inside = _HERE / kind
    return inside if inside.is_dir() else _IN_SOURCE[kind]


def shipped(kind: str) -> List[str]:
    """The names of the files of `kind` (CONFIGS or DOCS) given to a user's folder, sorted."""
    where = folder(kind)
    if not where.is_dir():
        return []
    return sorted(p.name for p in where.iterdir() if p.is_file() and p.suffix == SUFFIX[kind]
                  and p.name not in MAINTAINER_ONLY)


def copy(kind: str, name: str, target: Path, replace: bool = False) -> bool:
    """Copies the shipped file `kind/name` to `target`: when it is missing, or — `replace` — when it differs.
    Returns whether it was written. Never raises (a read-only home must not stop a command)."""
    try:
        source = folder(kind) / name
        if not source.is_file():
            return False
        data = source.read_bytes()
        if target.exists() and (not replace or target.read_bytes() == data):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        return True
    except OSError as error:
        logging.debug(f"Could not write {target}: {error}")
        return False


def populate(home: Path) -> List[Path]:
    """Makes `home`/configs (the job files that are missing) and `home`/docs (every document, brought up to date).
    Returns the files written."""
    home = Path(home)
    written = [home / CONFIGS / name for name in shipped(CONFIGS) if copy(CONFIGS, name, home / CONFIGS / name)]
    written += [home / DOCS / name for name in shipped(DOCS) if copy(DOCS, name, home / DOCS / name, replace=True)]
    if written:
        logging.debug(f"Wrote {len(written)} file(s) of configs/ and docs/ into {home}")
    return written


def status(home: Path) -> Dict[str, object]:
    """What `home` lacks: {"home": exists?, "configs": [missing job files], "docs": [missing documents]}."""
    home = Path(home)
    return {"home": home.is_dir(),
            CONFIGS: [n for n in shipped(CONFIGS) if not (home / CONFIGS / n).is_file()],
            DOCS: [n for n in shipped(DOCS) if not (home / DOCS / n).is_file()]}


def source_path(kind: str, name: str) -> Path:
    """The repository's own file (for the tools that rewrite them: make commands, make dictionary, the generator)."""
    return _SOURCE / kind / name


__all__ = ["CONFIGS", "DOCS", "MAINTAINER_ONLY", "copy", "folder", "populate", "shipped", "source_path", "status"]
