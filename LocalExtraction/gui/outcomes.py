# LocalExtraction/gui/outcomes.py
"""What an extraction added to a database, as a result card — the same for the local PDFs and the
papers from the web. The database is looked at before the run (`snapshot`) and after it: what is new
is what the run did."""

from __future__ import annotations

from typing import Callable, List, Optional, Set, Tuple

import pandas as pd

from .. import database
from .result_card import BAD, DONE, FAILED, NOTHING, WARNING, Outcome, Stat, number

_TRANSPORT = (("activation_energy", "activation_energy_eV", "activation energies", "eV"),
              ("ionic_conductivity", "ionic_conductivity_S_cm", "ionic conductivities", "S/cm"),
              ("electronic_conductivity", "electronic_conductivity_S_cm", "electronic conductivities", "S/cm"),
              ("diffusion_coefficient", "diffusion_coefficient_cm2_s", "diffusion coefficients", "cm²/s"))


def snapshot(output_dir: str) -> Set[str]:
    """The papers a database holds now."""
    papers = database.table(output_dir, "papers")
    return set(papers["paper_id"]) if "paper_id" in papers else set()


def _new(frame: pd.DataFrame, new: Set[str]) -> pd.DataFrame:
    return frame[frame["paper_id"].isin(new)] if "paper_id" in frame and len(frame) else frame.iloc[0:0]


def _values(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in frame or not len(frame):
        return frame.iloc[0:0]
    return frame.assign(_v=pd.to_numeric(frame[column], errors="coerce")).dropna(subset=["_v"])


def _short(title: str, limit: int = 90) -> str:
    title = str(title)
    return title if len(title) <= limit else title[:limit - 1].rstrip() + "…"


def extraction_outcome(output_dir: str, before: Set[str], *, failed: int = 0, stopped: bool = False,
                       started: Optional[float] = None, pdfs_pending: Optional[int] = None,
                       actions: Optional[List[Tuple[str, Callable[[], None]]]] = None,
                       prefix: str = "") -> Outcome:
    """The card of an extraction into `output_dir`, `before` being `snapshot` of it before the run."""
    papers = database.table(output_dir, "papers")
    every = set(papers["paper_id"]) if "paper_id" in papers else set()
    new = every - before
    tables = {name: database.table(output_dir, name) for name, _, _, _ in _TRANSPORT}
    titles = dict(zip(papers["paper_id"], papers["title"])) if {"paper_id", "title"} <= set(papers.columns) else {}
    materials = database.table(output_dir, "materials")

    if not new and not failed:
        detail = (f"Every PDF is already in the database ({number(len(every))} article{'s' if len(every) != 1 else ''})."
                  if every else "There was no PDF to read.")
        return Outcome("Nothing new to extract", NOTHING, prefix + detail, actions=list(actions or []), started=started)

    stats = [Stat(number(len(new)), "articles read", hint=f"{number(len(every))} in the database")]
    highlights: List[str] = []
    gave = set()
    for name, column, label, unit in _TRANSPORT:
        rows = _new(tables[name], new)
        gave |= set(rows["paper_id"]) if "paper_id" in rows else set()
        if name in ("activation_energy", "ionic_conductivity") or len(rows):
            stats.append(Stat(number(len(rows)), label, hint=f"{number(len(tables[name]))} in all"))
        found = _values(rows, column)
        if len(found) and name == "activation_energy":
            for _, row in found.sort_values("_v").drop_duplicates("material_formula").head(3).iterrows():
                highlights.append(f"Low activation energy: {row['material_formula']} — {row[column]} eV  "
                                  f"({_short(titles.get(row['paper_id'], row['paper_id']))})")
        elif len(found) and name == "ionic_conductivity":
            row = found.sort_values("_v", ascending=False).iloc[0]
            highlights.append(f"Highest ionic conductivity: {row['material_formula']} — {row[column]} S/cm  "
                              f"({_short(titles.get(row['paper_id'], row['paper_id']))})")
    stats.append(Stat(number(len(_new(materials, new))), "materials", hint=f"{number(len(materials))} in all"))
    if failed:
        stats.append(Stat(number(failed), "PDFs not read", accent=BAD, hint="see the log"))
    silent = len(new - gave)
    if silent:
        highlights.append(f"{number(silent)} of the new articles gave no transport value (their methods, tables "
                          "and figures are recorded).")

    if stopped:
        status, title = WARNING, "Extraction stopped"
        detail = "The articles read before the stop are saved; the next run reads the rest."
    elif failed and not new:
        status, title, detail = FAILED, "Extraction failed", f"{number(failed)} PDF(s) could not be read: see the log."
    elif failed:
        status, title = WARNING, "Extraction finished, with problems"
        detail = f"{number(failed)} PDF(s) could not be read (see the log); the others are in the database."
    else:
        status, title = DONE, "Extraction finished"
        detail = f"{number(len(new))} new article{'s' if len(new) != 1 else ''} read into {output_dir}."
    if pdfs_pending:
        detail += f" {number(pdfs_pending)} PDF(s) are left to read."
    return Outcome(title, status, prefix + detail, stats, highlights, list(actions or []), started)
