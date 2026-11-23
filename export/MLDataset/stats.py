# MLDataset/stats.py
"""The statistics of a dataset made for machine learning, as charts (LocalExtraction/stats.py): the distribution of
its target, how many values and papers stand behind each material, and why values were left out. Read from the
dataset's folder (dataset.csv, excluded.csv), never changed."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

from LocalExtraction.stats import Chart, number, ordered, rows, share


def dataset_charts(folder: Path) -> List[Chart]:
    """The charts of a dataset folder (~/MoukhlijMatExtract/Ready for ML/<name>); [] when it holds none."""
    folder = Path(folder)
    data = rows(folder / "dataset.csv")
    if not data:
        return []
    note = f"From the dataset {folder.name} (dataset.csv)"
    charts: List[Chart] = []
    unit = (data[0].get("unit") or "").strip()
    targets = [v for r in data for v in [number(r.get("target"))] if v is not None]
    if targets:
        logarithmic = unit.lower().startswith(("s/cm", "cm")) and all(v > 0 for v in targets)
        middle = sorted(targets)[len(targets) // 2]
        charts.append(Chart("target-distribution", f"{len(targets):,} materials, median target "
                                                   f"{middle:.3g} {unit}".rstrip(),
                            "hist", values=targets, unit=f"target{', log10' if logarithmic else ''} ({unit})",
                            log10=logarithmic, bin_width=0.5 if logarithmic else 0.05 if unit == "eV" else 0.0,
                            note=note))
    support = Counter(min(int(number(r.get("n_values")) or 0), 5) for r in data)
    labels = ["1", "2", "3", "4", "5 or more"]
    values = [float(support.get(i, 0)) for i in range(1, 6)]
    if any(values):
        charts.append(Chart("values-per-material", f"{share(values[0], len(data))} of the materials rest on a single "
                                                   "value", "bar", labels, values, unit="materials", accent=0,
                            note=note + " (n_values)"))
    excluded = rows(folder / "excluded.csv")
    if excluded:
        reasons = Counter((r.get("why") or "?").split(":")[0].strip() for r in excluded)
        labels, values = ordered(reasons, top=8)
        charts.append(Chart("excluded", f"{len(excluded):,} values left out, most often: {labels[0]}", "barh", labels,
                            values, unit="values", accent=0, note=f"From the dataset {folder.name} (excluded.csv)"))
    return charts


def latest_dataset(root: Path) -> Path:
    """The dataset folder written last in Ready for ML/ (the folder itself when none)."""
    folders = [p for p in Path(root).iterdir() if (p / "dataset.csv").is_file()] if Path(root).is_dir() else []
    return max(folders, key=lambda p: (p / "dataset.csv").stat().st_mtime) if folders else Path(root)

