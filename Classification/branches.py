# Classification/branches.py
"""The classification by property, written by the same click as the classes: every family, then every property
alone, then every transport component, then every origin — one table per branch, never two quantities mixed.

    ① family      crystal (garnet, NASICON …) and chemical (oxide, sulfide …) — the class folders just written
    ② property    activation energy · ionic conductivity · diffusion coefficient · electronic conductivity
    ③ type        bulk · grain boundary · total
    ④ origin      experimental · simulation
    ⑤ quality     the defaults of the ML datasets: the papers' own results, the values the extraction flagged
                  left out, Arrhenius activation energies only, conductivities and diffusion coefficients at room
                  temperature, the checks of the Verify tab applied
    ⑥ a table     Classification/by_property/<axis>/<family>/<property>/<type>/<origin>/
                  dataset.csv (one row per material) and values.csv (every value, with its sentence and page)

A branch no value reaches is not written. by_property/tree.csv lists every branch written, with its counts and its
range of values; by_property/README.md shows the same as a tree."""

from __future__ import annotations

import csv
import shutil
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from MLDataset import export
from MLDataset.export import ANY, PROPERTIES, Family, Settings

FOLDER = "by_property"
AXES = (("crystal_structure", "crystal family"), ("structure_families", "chemical family"))
PLURAL = {"crystal_structure": "Crystal families", "structure_families": "Chemical families"}
# Which end of a property is the better one: a low activation energy and electronic conductivity, a high ionic
# conductivity and diffusion coefficient.
BEST_IS_LOW = {"Ea": True, "sigma": False, "sigma_e": True, "D": False}
COMPONENTS = ("bulk", "grain_boundary", "total")
ORIGINS = ("experimental", "simulation")
TREE_COLUMNS = ("axis", "family", "property", "unit", "component", "origin", "n_materials", "n_values", "n_papers",
                "min", "median", "max", "best_material", "folder")
_WORDS = {"bulk": "bulk", "grain_boundary": "grain boundary", "total": "total", "experimental": "experimental",
          "simulation": "simulation"}


@dataclass
class Branch:
    axis: str
    family: str
    target: str
    component: str
    origin: str
    materials: int
    values: int
    papers: int
    low: float
    middle: float
    high: float
    best_material: str
    folder: str

    def row(self) -> Dict[str, object]:
        prop = PROPERTIES[self.target]
        return {"axis": self.axis, "family": self.family, "property": prop.label, "unit": prop.unit,
                "component": self.component, "origin": self.origin, "n_materials": self.materials,
                "n_values": self.values, "n_papers": self.papers, "min": f"{self.low:.6g}",
                "median": f"{self.middle:.6g}", "max": f"{self.high:.6g}", "best_material": self.best_material,
                "folder": self.folder}


def settings_for(family: Family, target: str, component: str, origin: str) -> Settings:
    """The settings of one branch: the ML datasets' defaults (⑤)."""
    return Settings(family=family.key, target=target, component=component, origin=origin, attribution="this work",
                    energy_kind="arrhenius" if target == "Ea" else ANY,
                    temperature=ANY if target == "Ea" else "room", plausible_only=True)


def families_in(out_dir: Path) -> List[Family]:
    found = []
    for axis, kind in AXES:
        base = Path(out_dir) / axis
        if base.is_dir():
            for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir() and any((child / f"{p.table}.csv").is_file() for p in PROPERTIES.values()):
                    found.append(Family(f"{axis}/{child.name}", child.name, kind, child))
    return found


def write_all(out_dir: Path, home: Optional[Path] = None,
              progress: Optional[Callable[[int, int, str], None]] = None) -> List[Branch]:
    """Writes Classification/by_property/ from the class folders in `out_dir`, whole or not at all (built aside,
    then put in place). `home`: where Verification/ is (the main folder). `progress` gets (families done, families,
    the family just done). Returns the branches written."""
    out_dir = Path(out_dir)
    home = Path(home) if home is not None else export.home()
    staging = out_dir / f".{FOLDER}.writing"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    branches: List[Branch] = []
    every = families_in(out_dir)
    for done, family in enumerate(every, 1):
        if progress is not None:
            progress(done - 1, len(every), family.name)
        axis = family.key.split("/", 1)[0]
        for target, prop in PROPERTIES.items():
            rows = export.read_rows(family, target)
            if not rows:
                continue
            for component in COMPONENTS:
                for origin in ORIGINS:
                    chosen = export.select(settings_for(family, target, component, origin), home, family=family,
                                           rows=rows)
                    if not chosen.kept:
                        continue  # ⑥ a branch no value reaches is not written
                    relative = Path(axis) / family.name / prop.table / component / origin
                    folder = staging / relative
                    folder.mkdir(parents=True)
                    values = [export._value_row(row, prop) for row in chosen.kept]
                    per_material = export._per_material(values, prop)
                    export._write(folder / "values.csv", export.VALUE_COLUMNS, values)
                    export._write(folder / "dataset.csv", export.DATASET_COLUMNS, per_material)
                    numbers = sorted(float(r["target"]) for r in per_material)
                    pick = min if BEST_IS_LOW[target] else max
                    best = pick(per_material, key=lambda r: float(r["target"]))
                    branches.append(Branch(axis, family.name, target, component, origin, len(per_material),
                                           len(values), chosen.papers(), numbers[0], statistics.median(numbers),
                                           numbers[-1], best["material_formula"] or best["material"],
                                           str(Path(FOLDER) / relative)))
    if progress is not None and every:
        progress(len(every), len(every), every[-1].name)
    export._write(staging / "tree.csv", TREE_COLUMNS, [b.row() for b in branches])
    (staging / "README.md").write_text(overview(branches), encoding="utf-8")
    target_folder = out_dir / FOLDER
    if target_folder.exists():
        shutil.rmtree(target_folder)
    staging.replace(target_folder)
    return branches


def read_tree(out_dir: Path) -> List[Dict[str, str]]:
    """The branches of the last classification by property (tree.csv); empty before the first one."""
    try:
        with open(Path(out_dir) / FOLDER / "tree.csv", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def overview(branches: List[Branch]) -> str:
    lines = ["# Classification by property", "",
             "Every family, every property alone, every transport component, every origin: one table per branch "
             "(`dataset.csv`: one row per material; `values.csv`: every value with its sentence and page).", "",
             "Quality: the papers' own results; values the extraction flagged left out; Arrhenius activation energies "
             "only; conductivities and diffusion coefficients at room temperature; the checks of the Verify tab "
             "applied. Branches no value reaches are not written.", ""]
    for axis, kind in AXES:
        mine = [b for b in branches if b.axis == axis]
        if not mine:
            continue
        lines += [f"## {PLURAL[axis]}", ""]
        for family in dict.fromkeys(b.family for b in mine):
            lines.append(f"- **{family}**")
            for target, prop in PROPERTIES.items():
                of = [b for b in mine if b.family == family and b.target == target]
                if not of:
                    continue
                lines.append(f"  - {prop.label} ({prop.unit})")
                for b in of:
                    lines.append(f"    - {_WORDS[b.component]} · {_WORDS[b.origin]}: {b.materials} materials, "
                                 f"{b.values} values, {b.papers} papers · {b.low:.3g}–{b.high:.3g} "
                                 f"(best: {b.best_material})")
        lines.append("")
    if not branches:
        lines.append("No branch: no value passes the quality filters yet.")
    return "\n".join(lines) + "\n"
