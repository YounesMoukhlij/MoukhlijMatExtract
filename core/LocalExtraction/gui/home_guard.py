# LocalExtraction/gui/home_guard.py
"""~/MoukhlijMatExtract deleted while a window is open. The windows work inside it (relative paths, the web search's
ledger), so the next step would fail deep down, or write into files that no longer exist. Each step asks first:
when the folder is gone, a small window says so and offers to make it again — every part's folders, the job files
and the documents — and the step goes on in it."""

from __future__ import annotations

import os
from pathlib import Path


def home_lost() -> bool:
    """Whether the folder the program works in was deleted while it was running."""
    from ..about import PROJECT_HOME
    try:
        here = Path(os.getcwd())
    except OSError:  # the working folder itself was deleted
        return True
    return here == PROJECT_HOME and not PROJECT_HOME.is_dir()


def ensure_home(parent, what: str) -> bool:
    """True when the step can go on: the folder is there, or was just made again. False when the user said no."""
    if not home_lost():
        return True
    from tkinter import messagebox

    from ..about import PART_FOLDERS, PROJECT_HOME, enter_project_home
    try:
        shown = "~/" + str(PROJECT_HOME.relative_to(Path.home()))
    except ValueError:
        shown = str(PROJECT_HOME)
    if not messagebox.askyesno(
            "MoukhlijMatExtract",
            f"{shown} was deleted while this window was open. {what} works in it.\n\nMake it again now, with every "
            "part's folders, the job files and the documents? (What was in it is not brought back: look in the "
            "Trash for it.)", icon="warning", parent=parent):
        return False
    enter_project_home(*PART_FOLDERS)  # the folders, configs/ and docs/; and works from there again
    from WebScraping.averageScrap.about import ensure_default_job
    ensure_default_job()
    return True
