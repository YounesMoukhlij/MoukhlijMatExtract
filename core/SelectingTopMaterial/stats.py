# SelectingTopMaterial/stats.py
"""The statistics of a ranking, as charts (LocalExtraction/stats.py): for each transport component (bulk, grain
boundary, total), how many materials fall in each class, the best materials, and how much evidence each rank rests on.
Read from the ranking's results folder (results/<component>/all_materials.csv), never changed."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from LocalExtraction.stats import Chart, number, rows, share

COMPONENTS = (("bulk", "bulk"), ("grain_boundary", "grain boundary"), ("total", "total"))
_TIERS = (("A", "A · 3+ values, 2+ papers"), ("B", "B · 2+ values"), ("C", "C · a single value"))


def ranking_charts(results: Path) -> List[Chart]:
    """The charts of a ranking's results folder; [] when it holds no ranking yet."""
    results = Path(results)
    charts: List[Chart] = []
    for key, name in COMPONENTS:
        materials = rows(results / key / "all_materials.csv")
        if not materials:
            continue
        note = f"From the ranking, {name} component ({results / key / 'all_materials.csv'})"
        energies: Dict[str, List[float]] = defaultdict(list)
        for r in materials:
            energy = number(r.get("activation_energy_eV"))
            if energy is not None:
                energies[r.get("class") or "?"].append(energy)
        classes = sorted(energies, key=lambda c: statistics.median(energies[c]))  # lowest energies first
        counts = [float(len(energies[c])) for c in classes]
        if classes:
            charts.append(Chart(f"classes-{key}", f"{counts[0]:,.0f} of {len(materials):,} materials are "
                                                  f"{classes[0].lower()} ({name}, {share(counts[0], len(materials))})",
                                "bar", classes, counts, unit="materials", accent=0, note=note))
        best = sorted((e, r.get("material") or "?") for r in materials
                      for e in [number(r.get("activation_energy_eV"))] if e is not None)[:15]
        if best:
            charts.append(Chart(f"best-{key}", f"{best[0][1]} has the lowest {name} activation energy "
                                               f"({best[0][0]:.2f} eV)",
                                "barh", [m for _, m in best], [e for e, _ in best], unit="activation energy (eV)",
                                accent=0, note=note + "; the 15 lowest"))
        tiers = Counter(r.get("evidence") or "?" for r in materials)
        if any(tiers.get(t) for t, _ in _TIERS):
            values = [float(tiers.get(t, 0)) for t, _ in _TIERS]
            charts.append(Chart(f"evidence-{key}", f"{share(values[2], len(materials))} of the {name} ranks rest on "
                                                   "a single value", "bar", [label for _, label in _TIERS], values,
                                unit="materials", accent=2, note=note + " (evidence)"))
    return charts
