# LocalExtraction/provenance.py
"""How a result was made, so it can be made again: the software, its version and git commit, the
language model, Tesseract, Python and every package that shapes the output — and the settings, inputs
and outputs of each run.

Two records:
  papers.csv, column extracted_with — for each paper, the version and language model that read it (a
      database grows over many runs, perhaps under several versions);
  run_manifest.json, in every results folder — one entry per run: when, how long, with which settings
      and environment, what went in and what came out (row counts and SHA-256 of every file)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MANIFEST = "run_manifest.json"
# The packages whose version can change what is extracted, ranked or classified.
PACKAGES = ("moukhlijmatextract", "spacy", "en-core-web-sm", "en-core-sci-sm", "scispacy", "PyMuPDF", "pdfplumber",
            "pytesseract", "opencv-python-headless", "Pillow", "pandas", "numpy", "pint", "pymatgen", "openpyxl",
            "requests", "PyYAML")
ROOT = Path(__file__).resolve().parent.parent  # the project folder (or site-packages)


def _version(package: str) -> Optional[str]:
    try:
        from importlib.metadata import version
        return version(package)
    except Exception:
        return None


@lru_cache(maxsize=1)
def git_commit() -> Dict[str, Any]:
    """The commit of the code that runs, and whether it holds changes not committed; {} outside a
    git checkout (an installed package)."""
    if not (ROOT / ".git").exists():
        return {}
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=5,
                                  check=True).stdout.strip()
        return {"commit": git("rev-parse", "HEAD"), "uncommitted_changes": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {}


@lru_cache(maxsize=1)
def tesseract() -> str:
    try:
        import pytesseract
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return "not found (scanned pages are not read)"


def language_model() -> str:
    """The spaCy model the extraction reads sentences with, e.g. "en_core_web_sm 3.8.0" — results differ
    from one model to another, so it is recorded with each paper. Loads the extractor if needed."""
    from . import extractor
    return extractor.NLP_MODEL


def software() -> str:
    from .about import version
    return f"MoukhlijMatExtract {version() or '(not installed: run from the source folder)'}"


def extracted_with() -> str:
    """For papers.csv: "MoukhlijMatExtract 1.0.3 · en_core_web_sm 3.8.0" (+ the commit when the code is a
    git checkout)."""
    text = f"{software()} · {language_model()}"
    commit = git_commit()
    if commit:
        text += f" · commit {commit['commit'][:10]}{' with uncommitted changes' if commit['uncommitted_changes'] else ''}"
    return text


def environment(with_model: bool = True) -> Dict[str, Any]:
    """Everything of the computer and the software that can change a result."""
    env: Dict[str, Any] = {
        "software": software(),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "packages": {p: v for p in PACKAGES if (v := _version(p))},
        "tesseract": tesseract(),
    }
    if with_model:
        env["language_model"] = language_model()
    commit = git_commit()
    if commit:
        env["git"] = commit
    return env


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def outputs(folder: Path, names: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Rows (for a CSV), size and SHA-256 of each result file of the folder and its sub-folders, by
    path inside it (the earlier databases kept in previous_<date>/, hidden files and the manifest itself
    left out)."""
    folder = Path(folder)
    wanted = set(names) if names is not None else None

    def kept(path: Path) -> bool:
        inside = path.relative_to(folder)
        return (path.is_file() and path.name != MANIFEST and path.suffix != ".part"
                and not any(part.startswith((".", "previous_")) for part in inside.parts)
                and (wanted is None or path.name in wanted or str(inside) in wanted))

    files = sorted(p for p in folder.rglob("*") if kept(p))
    result = {}
    for path in files:
        entry: Dict[str, Any] = {"bytes": path.stat().st_size, "sha256": file_digest(path)}
        if path.suffix == ".csv":
            try:
                import pandas as pd
                entry["rows"] = len(pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig"))
            except Exception:
                pass
        result[path.relative_to(folder).as_posix()] = entry  # “total/values.csv” on every system: portable records
    return result


def command_line() -> str:
    """How the run was started: "mme-local --input …", "python -m LocalExtraction extract …"."""
    if not sys.argv or not sys.argv[0]:
        return ""
    started = Path(sys.argv[0])
    name = f"python -m {started.parent.name}" if started.name == "__main__.py" else started.name
    return " ".join([name, *sys.argv[1:]])


class Run:
    """One run of a part, recorded in <folder>/run_manifest.json when it ends:

        run = Run("extraction", folder, settings={...})
        ...
        run.finish(counts={...})"""

    def __init__(self, part: str, folder: Path, settings: Dict[str, Any], with_model: bool = False):
        self.part, self.folder, self.settings = part, Path(folder), settings
        self.with_model = with_model
        self.started = datetime.now(timezone.utc)
        self._clock = time.monotonic()

    def finish(self, counts: Optional[Dict[str, Any]] = None, files: Optional[Iterable[str]] = None,
               status: str = "finished") -> Path:
        entry = {
            "part": self.part,
            "status": status,
            "started": self.started.isoformat(timespec="seconds"),
            "seconds": round(time.monotonic() - self._clock, 1),
            "command": command_line(),
            "settings": self.settings,
            "environment": environment(self.with_model),
            "counts": counts or {},
            "outputs": outputs(self.folder, files),
        }
        return append(self.folder, entry)


def append(folder: Path, entry: Dict[str, Any]) -> Path:
    """Adds a run to the folder's manifest (written whole, then moved into place: never half written)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MANIFEST
    runs: List[Dict[str, Any]] = []
    if path.exists():
        try:
            runs = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError):
            broken = path.with_name(f"{MANIFEST}.unreadable-{datetime.now():%Y%m%d%H%M%S}")
            os.replace(path, broken)  # kept, not lost
    runs.append(entry)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps({"about": "One entry per run of MoukhlijMatExtract on this folder: the "
                                               "settings, the environment and the files it left.",
                                     "runs": runs}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temporary, path)
    return path
