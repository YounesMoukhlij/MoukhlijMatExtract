# Evaluation/steps.py
"""The two steps of an evaluation — make the workbook to annotate, score the annotated workbook — as
`mme-eval sheet` / `mme-eval score` and the Evaluate window of parts 1 and 2 run them, so the terminal and
the windows give the same numbers."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from LocalExtraction.about import PROJECT_HOME, version
from LocalExtraction.provenance import Run

# The log of an earlier downloader: a paper it records as coming from a shadow library is not drawn.
EARLIER_LOG = PROJECT_HOME / "WebScraping" / "papers" / "scrape_log.csv"


class NoDatabase(ValueError):
    """None of the results folders holds a database."""


def keep_old(path: Path) -> Path:
    """Moves a workbook out of the way, as <name>.<date-time>.xlsx next to it (it may hold annotations)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    shutil.move(str(path), kept)
    return kept


def make_sheet(sources: Sequence[Path], out: Path, papers: int = 60, seed: int = 7,
               legal_only: bool = True) -> Dict[str, int]:
    """Draws `papers` papers at random from the databases in `sources` and writes the workbook `out`.
    Only the papers mme-release would publish are drawn unless `legal_only` is False."""
    from .sheet import make
    present = [Path(s) for s in sources if (Path(s) / "papers.csv").exists()]
    if not present:
        raise NoDatabase("There is no database to draw from: extract papers first.\nLooked in: "
                         + ", ".join(str(s) for s in sources))
    return make(present, out, papers, seed, version(), legal_only=legal_only, log=EARLIER_LOG if legal_only else None)


def score_sheet(gold: Path, out: Path, sources: Optional[Sequence[Path]] = None, seed: int = 7):
    """Scores the annotated workbook `gold` into the folder `out` (report.md, metrics.json, errors.csv).
    With `sources`, the values now in those results folders are scored (a newer extraction) instead of
    those the workbook was made from. Returns (metrics, paths, annotation, the values scored, a label of them).
    Raises score.AnnotationError for a workbook that cannot be read, or with no paper marked done."""
    from .score import AnnotationError, evaluate, extracted_from_databases, read_annotation, write_report
    annotation = read_annotation(gold)
    if not annotation.done:
        raise AnnotationError(f"No paper of {annotation.path} is marked done yet (Papers sheet, column done = yes).")
    extracted, label = None, "the values in the workbook (the run it was made from)"
    if sources:
        folders = [Path(s) for s in sources]
        missing = [str(f) for f in folders if not (f / "papers.csv").exists()]
        if missing:
            raise AnnotationError("Not a results folder: " + ", ".join(missing))
        extracted = extracted_from_databases(annotation, folders)
        label = "now in " + ", ".join(str(f) for f in folders)
    run = Run("evaluation", out, settings={"workbook": str(annotation.path.resolve()), "scored": label,
                                           "bootstrap_seed": seed})
    metrics = evaluate(annotation, extracted, seed=seed)
    about = {"software": f"MoukhlijMatExtract {version()}".strip(), "bootstrap seed": str(seed)}
    paths = write_report(out, metrics, annotation, label, about)
    run.finish({"papers": metrics["papers"], "reference_values": metrics["gold"], "extracted_values": metrics["extracted"],
                "record_f1": metrics["levels"]["record"]["all"]["f1"], "value_f1": metrics["levels"]["value"]["all"]["f1"]},
               files=[p.name for p in paths.values()])
    return metrics, paths, annotation, extracted if extracted is not None else annotation.extracted, label


def summary_rows(metrics: Dict) -> List[Tuple[str, Optional[float], Optional[float], Optional[float]]]:
    """(name, precision, recall, F1) for each level and property, as the report's first table: "record" is
    the right value for the right material, "value" the right value."""
    return [(f"{level} · {'all' if scope == 'all' else scope.replace('_', ' ')}", s["precision"], s["recall"], s["f1"])
            for level in ("record", "value") for scope, s in metrics["levels"][level].items()]
