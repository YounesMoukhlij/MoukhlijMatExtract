# Classification/stats.py
"""The statistics of a classification, as charts (LocalExtraction/stats.py): the materials of each crystal-structure
type and structure family, and the activation energy each family reaches. Read from Classification/all_materials.csv,
never changed."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from LocalExtraction.stats import Chart, number, ordered, rows


def classification_charts(folder: Path) -> List[Chart]:
    """The charts of a classification folder; [] when it holds no classification yet."""
    folder = Path(folder)
    materials = rows(folder / "all_materials.csv")
    if not materials:
        return []
    note = f"From the classification ({folder / 'all_materials.csv'})"
    charts: List[Chart] = []
    for key, column, name in (("crystal-structures", "crystal_structure", "crystal-structure type"),
                              ("structure-families", "structure_family", "structure family")):
        counts = Counter((r.get(column) or "").strip() or "unclassified" for r in materials)
        labels, values = ordered(counts, top=14)
        if values:
            charts.append(Chart(key, f"{labels[0]}: the largest {name} ({values[0]:,.0f} of {len(materials):,} "
                                     "materials)", "barh", labels, values, unit="materials", accent=0, note=note))
    energies: Dict[str, List[float]] = defaultdict(list)
    for r in materials:
        energy = number(r.get("Ea_median_eV"))
        if energy is not None:
            energies[(r.get("structure_family") or "").strip() or "unclassified"].append(energy)
    families = sorted((statistics.median(v), f, len(v)) for f, v in energies.items() if len(v) >= 3)
    if families:
        charts.append(Chart("family-energies", f"{families[0][1]} has the lowest median activation energy "
                                               f"({families[0][0]:.2f} eV over {families[0][2]} materials)",
                            "barh", [f"{f} ({n})" for _, f, n in families], [e for e, _, _ in families],
                            unit="median activation energy of its materials (eV)", accent=0,
                            note=note + "; families with 3 materials or more, (n) = materials"))
    return charts
