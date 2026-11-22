# WebScraping/averageScrap/download_log.py
"""The record of every download: one line per paper tried, in download_log.csv of the job's papers folder — when,
in which run, what came of it in plain words (downloaded, not downloaded, waiting), where the copy came from or why
there is none, and what can be done. Written by every download, from the window or the terminal; read by the
Downloads tab of the Web scraping window. Lines are only ever added: the record of earlier runs is kept."""

import csv
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

from WebScraping.averageScrap import by_hand
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, EXTRACTED, FAILED, Candidate

LOG_NAME = "download_log.csv"
COLUMNS = ("time", "run", "result", "doi", "title", "year", "journal", "source", "why", "what_to_do", "file",
           "link", "detail", "key")
GOT, MISSED, WAITING = "downloaded", "not downloaded", "waiting"
WAIT_WHY = "a site was busy or limited requests"
WAIT_TODO = "Nothing: it is tried again at the end of this download, or by the next one."
_lock = threading.Lock()


def path_of(folder: str) -> str:
    return os.path.join(folder, LOG_NAME)


def result_of(c: Candidate) -> str:
    """What came of a paper's download, in one word: downloaded, not downloaded, or waiting."""
    if c.status in (DOWNLOADED, EXTRACTED):
        return GOT
    if c.status == FAILED and (c.error or "").startswith("waiting"):
        return WAITING
    return MISSED


def entry(c: Candidate, run: str, when: Optional[datetime] = None) -> Dict[str, str]:
    """The line of the log for a paper, as it stands in the ledger after its download."""
    result = result_of(c)
    if result == GOT:
        why, todo = "", ""
    elif result == WAITING:
        why, todo = WAIT_WHY, WAIT_TODO
    else:
        reason = by_hand.reason_of(c) if c.status in (FAILED, CLOSED) else by_hand.NOT_FOUND
        why, todo = reason, by_hand.REASONS[reason]
    return {"time": (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), "run": run, "result": result,
            "doi": c.doi, "title": c.title, "year": str(c.year or ""), "journal": c.journal,
            "source": c.source_used if result == GOT else "", "why": why, "what_to_do": todo,
            "file": c.file if result == GOT else "",
            "link": f"https://doi.org/{c.doi}" if c.doi else (c.landing_url or ""),
            "detail": (c.error or "")[:300] if result != GOT else "", "key": c.key}


def add(folder: str, row: Dict[str, str]) -> None:
    """Appends one line (the header first, for a new log). A log that cannot be written is said, not fatal."""
    path = path_of(folder)
    with _lock:
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerow(row)


def read(folder: str) -> List[Dict[str, str]]:
    """Every line of the log, oldest first. Empty when there is none yet. A line still being written by a running
    download (read half-way: its last column, the key, missing) is left for the next reading."""
    try:
        with open(path_of(folder), encoding="utf-8-sig", newline="") as f:
            return [row for row in csv.DictReader(f) if row.get("key") and row.get("result")]
    except OSError:
        return []


def last_run(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """The lines of the latest run. A paper tried again later in the same run keeps its last line only."""
    if not rows:
        return []
    run = rows[-1]["run"]
    latest: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if row["run"] == run:
            latest[row["key"]] = row
    return list(latest.values())
