# WebScraping/stats.py
"""The statistics of a web job, as charts (LocalExtraction/stats.py): how far its papers went (found → proposed →
downloaded → extracted → with an activation energy), who found them, where the copies came from, why the others were
not had, the publishers, the years, the searches day by day — then the charts of its database. Everything is read
from the job's ledger, download log and database, never changed."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from LocalExtraction.stats import Chart, database_charts, ordered, rows, share

from .ledger import CLOSED, DOWNLOADED, EXTRACTED, FAILED

_HAD = (DOWNLOADED, EXTRACTED)
_STATUS_NAMES = {"new": "Found, not scored yet", "screened": "Proposed, waiting for review", "approved": "Approved, "
                 "to download", "rejected": "Not proposed", "downloaded": "Downloaded", "extracted": "Extracted",
                 "failed": "No copy found (to retry)", "closed": "No legal copy (to get by hand)"}


def _ledger(folder: str) -> List[Tuple[str, str, str, int, str]]:
    """(status, decision, publisher, year, found_by) of every paper of the job's ledger, read without changing it."""
    path = os.path.join(folder, "ledger.sqlite")
    if not os.path.exists(path):
        return []
    db = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=30)
    try:
        return [(s or "new", d or "", (p or "").strip() or "unknown", int(y or 0), f or "[]")
                for s, d, p, y, f in db.execute("SELECT status, decision, publisher, year, found_by FROM candidates")]
    except sqlite3.DatabaseError:
        return []
    finally:
        db.close()


def _searches_per_day(folder: str) -> Counter:
    path = os.path.join(folder, "ledger.sqlite")
    if not os.path.exists(path):
        return Counter()
    db = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=30)
    try:
        return Counter(day for (day,) in db.execute(
            "SELECT substr(at, 1, 10) FROM searches WHERE search NOT LIKE 'snowball|%'") if day)
    except sqlite3.DatabaseError:
        return Counter()
    finally:
        db.close()


def _source_of(found: str) -> str:
    """"openalex: garnet …" → "openalex"; "arxiv: … (through OpenAlex)" → "arxiv"."""
    return found.split(":", 1)[0].strip() or "?"


def web_charts(job_name: str, papers_folder: str, output: str) -> List[Chart]:
    """The charts of a web job: its ledger (in `papers_folder`), its download log, then its database (`output`)."""
    ledger = _ledger(papers_folder)
    database = Path(output)
    charts: List[Chart] = []
    where = f"the ledger of {job_name}"
    if ledger:
        found = len(ledger)
        proposed = sum(1 for _, d, _, _, _ in ledger if d == "yes")
        had = sum(1 for s, _, _, _, _ in ledger if s in _HAD)
        extracted = len(rows(database / "papers.csv"))
        with_ea = len({r.get("paper_id") for r in rows(database / "activation_energy.csv")})
        stages = [("Found by the searches", found), ("Proposed by the screening", proposed),
                  ("Legal copies downloaded", had), ("Papers extracted", extracted),
                  ("With at least one activation energy", with_ea)]
        ratio = f"1 in {found / with_ea:,.0f} papers found yields an activation energy" if with_ea else \
            f"{found:,} papers found, {had:,} downloaded"
        charts.append(Chart("corpus-funnel", ratio, "funnel", [s for s, _ in stages], [float(n) for _, n in stages],
                            accent=len(stages) - 1, note=f"From {where} and its database; papers extracted can "
                                                         "include some downloaded by an earlier run"))

        statuses = Counter(s for s, _, _, _, _ in ledger)
        labels, values = ordered(statuses)
        charts.append(Chart("ledger-status", f"{proposed:,} of {found:,} papers found were proposed "
                                             f"({share(proposed, found)})",
                            "barh", [_STATUS_NAMES.get(l, l) for l in labels], values, unit="papers",
                            note=f"From {where}: where each paper is now"))

        per_source: Counter = Counter()
        for *_, found_by in ledger:
            try:
                sources = {_source_of(entry) for entry in json.loads(found_by)}
            except (TypeError, ValueError):
                continue
            per_source.update(sources)
        if per_source:
            labels, values = ordered(per_source, top=14)
            charts.append(Chart("found-per-source", f"{labels[0]} found the most papers ({values[0]:,.0f})",
                                "barh", labels, values, unit="papers (a paper found by several sources counts in each)",
                                accent=0, note=f"From {where} (found_by)"))

        years = Counter(y for _, _, _, y, _ in ledger if 1950 <= y <= 2100)
        if years:
            span = list(range(min(years), max(years) + 1))
            peak = max(span, key=lambda y: years.get(y, 0))
            charts.append(Chart("found-by-year", f"Most papers found were published in {peak} "
                                                 f"({years[peak]:,} of {found:,})",
                                "bar", [str(y) for y in span], [float(years.get(y, 0)) for y in span], unit="papers",
                                accent=span.index(peak), note=f"From {where} (year of publication)"))

        by_publisher: Dict[str, Counter] = defaultdict(Counter)
        for status, decision, publisher, _, _ in ledger:
            if decision == "yes":
                by_publisher[publisher]["proposed"] += 1
                by_publisher[publisher]["downloaded"] += status in _HAD
        top = sorted(by_publisher.items(), key=lambda kv: -kv[1]["proposed"])[:10]
        if top:
            name, c = top[0]
            charts.append(Chart("publishers", f"{name}: {share(c['downloaded'], c['proposed'])} of its "
                                              f"{c['proposed']:,} proposed papers downloaded",
                                "grouped", [n for n, _ in top],
                                series={"Proposed": [float(c["proposed"]) for _, c in top],
                                        "Downloaded": [float(c["downloaded"]) for _, c in top]},
                                unit="papers", note=f"From {where}: the ten publishers with the most papers proposed"))

        failed_keys = {s for s in (FAILED, CLOSED)}
        not_had = sum(1 for s, _, _, _, _ in ledger if s in failed_keys)
        last_why: Dict[str, str] = {}
        for r in rows(Path(papers_folder) / "download_log.csv"):
            if r.get("result") in ("failed", "closed", "waiting", "not found") or r.get("why"):
                last_why[r.get("key") or r.get("doi") or ""] = r.get("why") or r.get("result") or "?"
        whys = Counter(last_why.values())
        whys.pop("", None)
        if whys:
            labels, values = ordered(whys, top=7)
            charts.append(Chart("download-failures", f"{not_had:,} papers had no copy yet; the most common reason: "
                                                     f"{labels[0]}", "barh", labels, values,
                                unit="papers (the last attempt of each)", accent=0,
                                note=f"From the download log of {job_name} (download_log.csv)"))

    copies = Counter(r.get("source_service") or "unknown" for r in rows(database / "papers.csv"))
    if copies:
        labels, values = ordered(copies, top=10)
        charts.append(Chart("copies-per-source", f"{labels[0]} gave the most legal copies "
                                                 f"({share(values[0], sum(values))})",
                            "barh", labels, values, unit="papers extracted", accent=0,
                            note=f"From the database of {job_name} (papers.csv, source_service)"))

    days = _searches_per_day(papers_folder)
    if days:
        span = sorted(days)
        charts.append(Chart("searches-per-day", f"{sum(days.values()):,} searches finished, the last on {span[-1]}",
                            "bar", span, [float(days[d]) for d in span], unit="searches finished",
                            note=f"From {where} (each search finished in full; skipped ones are not counted again)"))

    return charts + database_charts(database, f"the database of {job_name}")
