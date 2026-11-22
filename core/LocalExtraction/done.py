# LocalExtraction/done.py
"""Remembering that a step was already done, so that running it again on the same input says so
and skips it instead of doing the same work a second time.

A step leaves a small stamp in the folder it wrote: a fingerprint of everything its result depends
on — the input files (their size and modification time), the settings it ran with, and its own code —
and the files it wrote. A later run with the same fingerprint, those files still there, would only
write the same thing again: it is skipped. Any change (a new paper in a database, another option, a
new version of the program, a deleted output file) makes it run again."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

STAMP = ".mme_done.json"


def _files(folder: Path, suffixes: Sequence[str]) -> list[Path]:
    if folder.is_file():
        return [folder]
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in suffixes and not p.name.startswith("."))


def fingerprint(inputs: Iterable[Path], settings: object, code: Iterable[Path] = (),
                suffixes: Sequence[str] = (".csv",)) -> str:
    """One hash of the input files (each folder: its files ending in `suffixes`), the settings
    (anything json can write) and the code (each folder: its .py files)."""
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode())
    for kind, roots, ends in (("in", inputs, suffixes), ("code", code, (".py",))):
        for root in roots:
            root = Path(root)
            for path in _files(root, ends):
                stat = path.stat()
                digest.update(f"{kind}|{path}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def already_done(folder: Path, step: str, print_: str) -> Optional[str]:
    """When `step` was last done in `folder` with this fingerprint and its files are all still
    there: the time it was done ("2026-10-29 14:02 UTC"). None otherwise."""
    try:
        with open(Path(folder) / STAMP, encoding="utf-8") as f:
            entry = json.load(f).get(step) or {}
    except (OSError, ValueError, AttributeError):
        return None
    if entry.get("fingerprint") != print_ or not entry.get("written"):
        return None
    if not all((Path(folder) / name).exists() for name in entry["written"]):
        return None
    return entry.get("at", "an earlier run")


def mark_done(folder: Path, step: str, print_: str, written: Iterable[Path]) -> None:
    """Records that `step` was done in `folder` with this fingerprint and wrote these files."""
    folder = Path(folder)
    path = folder / STAMP
    try:
        with open(path, encoding="utf-8") as f:
            stamps = json.load(f)
        if not isinstance(stamps, dict):
            stamps = {}
    except (OSError, ValueError):
        stamps = {}
    names = []
    for file in written:
        try:
            names.append(Path(file).resolve().relative_to(folder.resolve()).as_posix())  # “/” on every system
        except ValueError:
            continue  # written elsewhere: not this folder's to check
    stamps[step] = {"fingerprint": print_, "written": names,
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    folder.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(stamps, f, indent=2)
    os.replace(temporary, path)
