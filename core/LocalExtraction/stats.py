# LocalExtraction/stats.py
"""The statistics of a part's work, as charts to draw: what each chart shows, its numbers and the finding its title
states. Read from the files a part wrote (never changed); drawn by LocalExtraction/charts.py, shown by the
Statistics window (gui/statistics.py) and saved as 300 dpi PNG and SVG in ~/MoukhlijMatExtract/Statistics/.

This module draws nothing: a chart here is data (`Chart`), so the numbers can be tested without a screen. The charts
of a database (`database_charts`) serve 1 · Local extraction and 2 · Web scraping alike; the other parts add their
own (WebScraping/averageScrap/stats.py, SelectingTopMaterial/stats.py, Classification/stats.py, MLDataset/stats.py,
Evaluation/stats.py)."""

from __future__ import annotations

import csv
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

csv.field_size_limit(2 ** 31 - 1)  # a sentence or a table cell can be long

KINDS = ("bar", "barh", "hist", "funnel", "grouped", "line")


@dataclass
class Chart:
    """One chart: its kind, its numbers and the finding its title states (with its number).

    bar / barh / funnel / line: `labels` and `values`, one each; grouped: `labels` and `series` (name → one value per
    label); hist: `values` are the samples, cut into bins `bin_width` wide (`log10`: the samples are powers of ten,
    drawn as their logarithm). `accent` is the bar the title is about (the others stay grey); `marks` are reference
    lines (value, label) a reader checks the data against; `note` says where the numbers come from."""
    key: str
    title: str
    kind: str
    labels: List[str] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    series: Dict[str, List[float]] = field(default_factory=dict)
    unit: str = ""
    note: str = ""
    accent: Optional[int] = None
    marks: List[Tuple[float, str]] = field(default_factory=list)
    bin_width: float = 0.0
    log10: bool = False
    percent: bool = False

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind of chart {self.kind!r}: one of {', '.join(KINDS)}")


# ---------------------------------------------------------------------------------------------------- reading
def rows(path: Path) -> List[Dict[str, str]]:
    """The rows of a CSV file the program wrote ([] when it is missing or cannot be read)."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def number(text: object) -> Optional[float]:
    """The number at the start of a cell ("0.28", "1.2e-3 S/cm"), None for anything else."""
    try:
        value = float(str(text).strip().split(" ", 1)[0])
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def share(part: float, whole: float) -> str:
    """“37 %” (rounded); “0 %” for an empty whole."""
    return f"{100 * part / whole:.0f} %" if whole else "0 %"


def ordered(counts: Counter, top: int = 0, other: str = "other") -> Tuple[List[str], List[float]]:
    """Labels and counts, the largest first; past `top` labels the rest are summed into `other`."""
    pairs = counts.most_common()
    if top and len(pairs) > top:
        pairs = pairs[:top] + [(other, sum(n for _, n in pairs[top:]))]
    return [str(k) for k, _ in pairs], [float(n) for _, n in pairs]


# ---------------------------------------------------------------------------------------------------- database
PROPERTY_FILES = (("Activation energy", "activation_energy.csv", "activation_energy_eV"),
                  ("Ionic conductivity", "ionic_conductivity.csv", "ionic_conductivity_S_cm"),
                  ("Electronic conductivity", "electronic_conductivity.csv", "electronic_conductivity_S_cm"),
                  ("Diffusion coefficient", "diffusion_coefficient.csv", "diffusion_coefficient_cm2_s"))
COMPONENTS = (("bulk", "Bulk"), ("grain_boundary", "Grain boundary"), ("total", "Total"), ("surface", "Surface"))
# The classes of a solid electrolyte (SelectingTopMaterial/criteria.toml): the reference lines of the Ea histogram.
EA_MARKS = [(0.25, "0.25 eV"), (0.30, "0.30 eV"), (0.40, "0.40 eV")]
_KINDS = {"arrhenius": "Arrhenius slope", "migration_barrier": "Migration barrier (NEB)", "bvse": "Bond-valence (BVSE)",
          "local_hop": "Local hops (NMR)", "vtf": "VTF pseudo-energy", "unspecified": "Not stated",
          "charge_transfer": "Charge transfer", "reaction": "Reaction", "rotation": "Rotation"}


def _in_range(row: Dict[str, str]) -> bool:
    return str(row.get("plausibility", "")).startswith("in range")


def database_charts(folder: Path, what: str = "") -> List[Chart]:
    """The charts of a database (a results folder of 1 · Local extraction or 2 · Web scraping). `what` names it in
    the notes ("the web database of garnet_nasicon"). [] when the folder holds no database yet."""
    folder = Path(folder)
    papers = rows(folder / "papers.csv")
    tables = {label: rows(folder / name) for label, name, _ in PROPERTY_FILES}
    if not papers and not any(tables.values()):
        return []
    where = what or str(folder)
    note = f"From {where} (papers.csv and the four value tables)"
    charts: List[Chart] = []

    counts = [len(tables[label]) for label, _, _ in PROPERTY_FILES]
    with_values = {r.get("paper_id") for table in tables.values() for r in table}
    charts.append(Chart(
        "values-per-property",
        f"{sum(counts):,} values from {len(with_values):,} papers, {counts[0]:,} of them activation energies",
        "bar", [label for label, _, _ in PROPERTY_FILES], [float(n) for n in counts], unit="values", note=note,
        accent=0))

    ea = tables["Activation energy"]
    if ea:
        by_component = Counter(r.get("transport_component") or "unspecified" for r in ea)
        labels = [name for key, name in COMPONENTS if by_component.get(key)]
        values = [float(by_component[key]) for key, _ in COMPONENTS if by_component.get(key)]
        if values:
            top = labels[values.index(max(values))]
            charts.append(Chart("ea-by-component",
                                f"{top} values lead: {share(max(values), len(ea))} of the activation energies",
                                "bar", labels, values, unit="activation energies", accent=values.index(max(values)),
                                note=note + "; a component the paper does not state is assumed (see n_assumed)"))

        pairs = Counter((r.get("data_origin") or "", r.get("attribution") or "") for r in ea)
        cells = [("experimental", "this work", "Measured · own result"), ("experimental", "cited", "Measured · cited"),
                 ("simulation", "this work", "Computed · own result"), ("simulation", "cited", "Computed · cited")]
        own = pairs[("experimental", "this work")]
        charts.append(Chart("ea-origin-attribution",
                            f"{share(own, len(ea))} of the activation energies are the papers' own measurements",
                            "bar", [c[2] for c in cells], [float(pairs[(o, a)]) for o, a, _ in cells],
                            unit="activation energies", note=note, accent=0))

        values_ev = [v for r in ea if _in_range(r) for v in [number(r.get("activation_energy_eV"))] if v is not None]
        if values_ev:
            charts.append(Chart("ea-distribution",
                                f"Median activation energy {statistics.median(values_ev):.2f} eV over "
                                f"{len(values_ev):,} values in range",
                                "hist", values=values_ev, unit="activation energy (eV)", bin_width=0.05,
                                marks=EA_MARKS, note=note + "; values flagged out of range left out; lines: the "
                                                            "electrolyte classes of criteria.toml"))

        kinds = Counter(r.get("energy_kind") or "unspecified" for r in ea)
        labels, values = ordered(kinds, top=7)
        labels = [_KINDS.get(k, k) for k in labels]
        if values:
            charts.append(Chart("ea-kind", f"{labels[0]}: {share(values[0], len(ea))} of the activation energies",
                                "barh", labels, values, unit="activation energies", accent=0, note=note))

        ions = Counter(r.get("mobile_ion") or "not stated" for r in ea)
        labels, values = ordered(ions, top=7)
        if values:
            charts.append(Chart("ea-mobile-ion", f"{labels[0]} moves in {share(values[0], len(ea))} of the activation "
                                                 "energies", "barh", labels, values, unit="activation energies",
                                accent=0, note=note))

        flagged = [r for r in ea if str(r.get("needs_check", "")).startswith("yes")]
        reasons = Counter(reason.strip() for r in flagged
                          for reason in str(r.get("needs_check", ""))[4:].split(";") if reason.strip())
        if reasons:
            labels, values = ordered(reasons, top=7)
            charts.append(Chart("ea-flagged", f"{share(len(flagged), len(ea))} of the activation energies are "
                                              f"flagged for a check, most often: {labels[0]}",
                                "barh", labels, values, unit="activation energies flagged (a value can have several "
                                                             "reasons)", accent=0, note=note + " (needs_check)"))

    sigma = [v for r in tables["Ionic conductivity"] if _in_range(r)
             for v in [number(r.get("ionic_conductivity_S_cm"))] if v is not None and v > 0]
    if sigma:
        median = 10 ** statistics.median(math.log10(v) for v in sigma)
        charts.append(Chart("conductivity-distribution",
                            f"Median ionic conductivity {median:.1e} S/cm over {len(sigma):,} values in range",
                            "hist", values=sigma, unit="ionic conductivity, log10 (S/cm)", bin_width=0.5, log10=True,
                            marks=[(-3.0, "1 mS/cm")], note=note + "; every temperature"))

    years = Counter(int(y) for r in papers for y in [number(r.get("publication_year"))] if y and 1950 <= y <= 2100)
    if years:
        span = list(range(min(years), max(years) + 1))
        peak = max(span, key=lambda y: years.get(y, 0))
        charts.append(Chart("papers-by-year", f"{len(papers):,} papers from {span[0]}–{span[-1]}; most in {peak}",
                            "bar", [str(y) for y in span], [float(years.get(y, 0)) for y in span], unit="papers",
                            accent=span.index(peak), note=f"From {where} (papers.csv, publication_year)"))
    return charts


def note_of(charts: Iterable[Chart]) -> str:
    """One line: how many charts, for a window's status line."""
    n = len(list(charts))
    return f"{n} chart{'s' if n != 1 else ''}"


def series_total(chart: Chart) -> float:
    """Every number of a chart added up (a funnel's first stage; a grouped chart's every value)."""
    if chart.kind == "grouped":
        return float(sum(sum(v) for v in chart.series.values()))
    return float(chart.values[0]) if chart.kind == "funnel" and chart.values else float(sum(chart.values))


def labelled(values: Sequence[float], labels: Sequence[str]) -> List[Tuple[str, float]]:
    return list(zip(labels, values))
