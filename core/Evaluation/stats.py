# Evaluation/stats.py
"""The statistics of an evaluation, as charts (LocalExtraction/stats.py): precision, recall and F1 of each property
against the annotated papers, and — once a benchmark was run — every method side by side. Read from the scores folder
(metrics.json) and Evaluation/benchmark/benchmark.csv, never changed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from LocalExtraction.stats import Chart, number, rows

_NAMES = {"activation_energy": "Activation energy", "ionic_conductivity": "Ionic conductivity",
          "electronic_conductivity": "Electronic conductivity", "diffusion_coefficient": "Diffusion coefficient",
          "all": "All properties"}


def evaluation_charts(scores: Path, benchmark: Path = None) -> List[Chart]:
    """The charts of a scores folder (and of a benchmark folder, when given and filled); [] when nothing was scored."""
    charts: List[Chart] = []
    try:
        metrics = json.loads((Path(scores) / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metrics = {}
    for level, words in (("value", "the right value"), ("record", "the right value for the right material")):
        scopes = (metrics.get("levels") or {}).get(level) or {}
        names = [s for s in ("all", *sorted(k for k in scopes if k != "all")) if s in scopes]
        if not names:
            continue
        series = {measure.capitalize() if measure != "f1" else "F1":
                  [float(scopes[s].get(measure) or 0.0) for s in names] for measure in ("precision", "recall", "f1")}
        overall = scopes.get("all") or {}
        charts.append(Chart(f"scores-{level}", f"F1 {100 * float(overall.get('f1') or 0):.0f} % for {words} "
                                               f"({metrics.get('papers', 0)} annotated papers)",
                            "grouped", [_NAMES.get(s, s) for s in names], series=series, percent=True,
                            note=f"From {Path(scores) / 'metrics.json'}; the 95 % intervals are in report.md"))
    if benchmark is not None:
        table = [r for r in rows(Path(benchmark) / "benchmark.csv") if r.get("property") == "all"
                 and r.get("level") == "record"]
        if table:
            table.sort(key=lambda r: -(number(r.get("f1")) or 0))
            charts.append(Chart("benchmark", f"{table[0].get('system')} leads with F1 "
                                             f"{100 * (number(table[0].get('f1')) or 0):.0f} %",
                                "barh", [r.get("system") or "?" for r in table],
                                [number(r.get("f1")) or 0.0 for r in table], percent=True, accent=0,
                                unit="F1, the right value for the right material",
                                note=f"From {Path(benchmark) / 'benchmark.csv'} (every property, the same papers)"))
    return charts
