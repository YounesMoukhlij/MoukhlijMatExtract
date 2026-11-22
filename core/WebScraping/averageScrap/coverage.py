# WebScraping/averageScrap/coverage.py
"""How much of the literature each job reached: found → screened → proposed → downloaded → extracted, and the same
by publisher — what a Limitations section needs to show the corpus's bias in plain view.

Read from each job's ledger (opened read-only: nothing is changed) and results folder; a job not run yet is listed
with zeros.

    mme-web coverage                  # the tables, into WebScraping/coverage/ of the main folder"""

import csv
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from glob import glob
from typing import Dict, Iterator, List, Optional, Tuple

from .ledger import CLOSED, DOWNLOADED, EXTRACTED, FAILED, NEW

FAMILY_COLUMNS = ("job", "found", "screened", "proposed", "downloaded", "download_rate", "no_copy",
                  "extracted_papers", "activation_energies", "pdf_folder", "results_folder")
PUBLISHER_COLUMNS = ("publisher", "found", "proposed", "downloaded", "download_rate", "no_copy")
_HAD = (DOWNLOADED, EXTRACTED)
_UNKNOWN = "unknown"


def _jobs(configs: str = "configs") -> Iterator[Tuple[str, str, str]]:
    """(job name, PDF folder, results folder) of each job file that can be read."""
    from .about import output_for
    from .job import load_job
    for path in sorted(glob(os.path.join(configs, "*.yaml"))):
        try:
            job = load_job(path)
        except (OSError, ValueError) as error:
            logging.info(f"Coverage: {path} skipped — {error}")
            continue
        yield os.path.splitext(os.path.basename(path))[0], job.fetch.folder, output_for(job)


def _ledger_rows(folder: str) -> List[Tuple[str, str, str]]:
    """(status, decision, publisher) of every paper of a job's ledger, read without changing it."""
    path = os.path.join(folder, "ledger.sqlite")
    if not os.path.exists(path):
        return []
    db = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        return [(s or NEW, d or "", (p or "").strip() or _UNKNOWN)
                for s, d, p in db.execute("SELECT status, decision, publisher FROM candidates")]
    except sqlite3.DatabaseError as error:
        logging.warning(f"Coverage: {path} cannot be read — {error}")
        return []
    finally:
        db.close()


def _rows_of(path: str) -> int:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return max(sum(1 for _ in csv.reader(f)) - 1, 0)
    except OSError:
        return 0


def _rate(had: int, proposed: int) -> Optional[float]:
    return round(had / proposed, 3) if proposed else None


def by_family(configs: str = "configs") -> List[Dict[str, object]]:
    """One row per job file: how far its papers went."""
    out = []
    for name, folder, results in _jobs(configs):
        rows = _ledger_rows(folder)
        proposed = sum(1 for _, decision, _ in rows if decision == "yes")
        downloaded = sum(1 for status, _, _ in rows if status in _HAD)
        out.append({"job": name, "found": len(rows), "screened": sum(1 for s, _, _ in rows if s != NEW),
                    "proposed": proposed, "downloaded": downloaded, "download_rate": _rate(downloaded, proposed),
                    "no_copy": sum(1 for s, _, _ in rows if s in (CLOSED, FAILED)),
                    "extracted_papers": _rows_of(os.path.join(results, "papers.csv")),
                    "activation_energies": _rows_of(os.path.join(results, "activation_energy.csv")),
                    "pdf_folder": folder, "results_folder": results})
    return out


def by_publisher(configs: str = "configs") -> List[Dict[str, object]]:
    """One row per publisher, every job together (a paper two jobs found counts in both), the most proposed first."""
    counts: Dict[str, Counter] = defaultdict(Counter)
    for _, folder, _ in _jobs(configs):
        for status, decision, publisher in _ledger_rows(folder):
            c = counts[publisher]
            c["found"] += 1
            c["proposed"] += decision == "yes"
            c["downloaded"] += status in _HAD
            c["no_copy"] += status in (CLOSED, FAILED)
    rows = [{"publisher": name, "found": c["found"], "proposed": c["proposed"], "downloaded": c["downloaded"],
             "download_rate": _rate(c["downloaded"], c["proposed"]), "no_copy": c["no_copy"]}
            for name, c in counts.items()]
    return sorted(rows, key=lambda r: (-r["proposed"], -r["found"], r["publisher"]))


def _pct(rate: Optional[float]) -> str:
    return "—" if rate is None else f"{100 * rate:.0f} %"


def markdown(families: List[Dict[str, object]], publishers: List[Dict[str, object]], top: int = 25) -> str:
    lines = ["# Coverage of the corpus", "",
             "How far the papers of each job went. *Found*: in the search ledger; *screened*: scored on the job's "
             "words; *proposed*: kept for download; *downloaded*: a legal copy was had; *no copy*: no legal copy was "
             "found (to get by hand); *extracted*: papers and activation energies in the job's database.", "",
             "| Job | Found | Screened | Proposed | Downloaded | No copy | Papers extracted | Activation energies |",
             "|---|---|---|---|---|---|---|---|"]
    for r in families:
        lines.append(f"| {r['job']} | {r['found']} | {r['screened']} | {r['proposed']} | {r['downloaded']} "
                     f"({_pct(r['download_rate'])}) | {r['no_copy']} | {r['extracted_papers']} | "
                     f"{r['activation_energies']} |")
    lines += ["", f"## By publisher (the {min(top, len(publishers))} that proposed the most papers)", "",
              "A publisher whose proposed papers were seldom downloaded is under-represented in the corpus: its "
              "papers are mostly closed to legal automatic retrieval.", "",
              "| Publisher | Found | Proposed | Downloaded | No copy |", "|---|---|---|---|---|"]
    for r in publishers[:top]:
        lines.append(f"| {r['publisher']} | {r['found']} | {r['proposed']} | {r['downloaded']} "
                     f"({_pct(r['download_rate'])}) | {r['no_copy']} |")
    return "\n".join(lines) + "\n"


def write(folder: str = os.path.join("WebScraping", "coverage"), configs: str = "configs") -> str:
    """The two tables (CSV) and the report (Markdown) into `folder`; returns it."""
    families, publishers = by_family(configs), by_publisher(configs)
    os.makedirs(folder, exist_ok=True)
    for name, columns, rows in (("coverage_by_family.csv", FAMILY_COLUMNS, families),
                                ("coverage_by_publisher.csv", PUBLISHER_COLUMNS, publishers)):
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    with open(os.path.join(folder, "coverage.md"), "w", encoding="utf-8") as f:
        f.write(markdown(families, publishers))
    return folder
