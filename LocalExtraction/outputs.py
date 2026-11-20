# LocalExtraction/outputs.py
"""What each part of the project writes, and deleting it — the "Delete outputs…" buttons of the windows.

Only what a part writes is offered: never the PDFs put in LocalExtraction/papers, nor the job file
or the API keys. What is deleted goes to the Trash (the Recycle Bin on Windows) so it can be got
back; only when no Trash can be reached is it deleted for good, and the window says so first.

A part that is running — or a window holding a file open (the ledger of the web search) — says so
here (`register`), and its outputs cannot be deleted until it is done."""

from __future__ import annotations

import os
import shutil
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .about import PROJECT_HOME

try:
    from send2trash import send2trash
except ImportError:  # not installed: deleted for good (the window says so before)
    send2trash = None

TO_TRASH = send2trash is not None

# The files the ranking and the classification write: only these are deleted from their folders.
_RANKING = ("bulk", "grain_boundary", "total", "surface", "not_reported", "summary.csv",  # one folder per component
            "top_materials.csv", "all_materials.csv", "values.csv", "selection.json", "selection.xlsx",  # earlier versions
            "report.html", ".mme_done.json")
_CLASSES = ("crystal_structure", "structure_families", "all_materials.csv", ".mme_done.json",
            ".crystal_structure.writing", ".structure_families.writing")


@dataclass(frozen=True)
class Group:
    """One kind of output of a part: a folder whose whole content is output, or named files in one."""
    key: str
    label: str
    folder: str                       # relative to the project folder
    names: Tuple[str, ...] = ()      # only these names in it; empty: everything in it

    def path(self, home: Path) -> Path:
        return Path(home) / self.folder

    def items(self, home: Path = PROJECT_HOME) -> List[Path]:
        """What there is to delete: the files and folders at the top of the group, that exist."""
        folder = self.path(home)
        if not folder.is_dir():
            return []
        if self.names:
            return [folder / name for name in self.names if (folder / name).exists()]
        return sorted(folder.iterdir())


PARTS: Dict[str, Tuple[str, Tuple[Group, ...]]] = {
    "local": ("1 · Local extraction", (
        Group("database", "The extracted database (tables, workbook, look-up cache)",
              os.path.join("LocalExtraction", "local_output")),)),
    "web": ("2 · Web scraping", (
        Group("dois", "The DOI list of Fetch DOIs (dois.csv, dois.txt, the searches done)",
              os.path.join("WebScraping", "Fetch_DOIs"),
              ("dois.csv", "dois.txt", "dois.searched.json", "dois.tmp", "dois.txt.tmp", "dois.searched.json.tmp")),
        Group("papers", "The downloaded PDFs, their records and the ledger of the search",
              os.path.join("WebScraping", "papers")),
        Group("database", "The extracted web database (tables, workbook, look-up cache)",
              os.path.join("WebScraping", "web_output")))),
    "rank": ("3 · Ranking", (
        Group("results", "The ranking (tables, workbook, report)",
              os.path.join("SelectingTopMaterial", "results"), _RANKING),)),
    "classify": ("4 · Classification", (
        Group("classes", "The class databases (crystal_structure/, structure_families/, all_materials.csv)",
              "Classification", _CLASSES),)),
    "ml": ("5 · ML datasets", (
        Group("datasets", "The datasets prepared for machine learning (Ready for ML/)", "Ready for ML"),)),
}


def size_of(items: Sequence[Path]) -> Tuple[int, int]:
    """(number of files, bytes) under these files and folders."""
    files = size = 0
    for item in items:
        if item.is_file():
            files, size = files + 1, size + item.stat().st_size
            continue
        for root, _, names in os.walk(item):
            for name in names:
                try:
                    size += os.path.getsize(os.path.join(root, name))
                    files += 1
                except OSError:
                    pass
    return files, size


def readable_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} bytes"


# ---------------------------------------------------------------------------
# What is in use
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_in_use: List[Tuple[str, Tuple[str, ...], "weakref.WeakMethod", str]] = []


def register(part: str, check: Callable[[], bool], why: str, groups: Sequence[str] = ()) -> None:
    """A window says that while `check()` (a method of it) is true, these groups of `part` (all of
    them when none is named) are in use, for the reason `why`. Forgotten when the window is gone."""
    with _lock:
        _in_use.append((part, tuple(groups), weakref.WeakMethod(check), why))


def in_use(part: str, group: str) -> Optional[str]:
    """Why a group of a part cannot be deleted now; None when it can."""
    with _lock:
        _in_use[:] = [entry for entry in _in_use if entry[2]() is not None]
        entries = list(_in_use)
    for owner, groups, check, why in entries:
        method = check()
        if owner == part and (not groups or group in groups) and method is not None:
            try:
                if method():
                    return why
            except Exception:  # a window being destroyed
                continue
    return None


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------
def delete(items: Sequence[Path]) -> List[Tuple[Path, str]]:
    """Moves these files and folders to the Trash (or deletes them when there is none). Returns
    the ones that could not be deleted, with why."""
    failed = []
    for item in items:
        try:
            if send2trash is not None:
                send2trash(str(item))
            elif item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        except Exception as error:  # one file that cannot go must not stop the others
            failed.append((item, f"{type(error).__name__}: {error}"))
    return failed
