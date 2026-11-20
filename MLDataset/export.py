# MLDataset/export.py
"""Datasets for machine learning, made from the databases of MoukhlijMatExtract: one property, one family of
materials, one transport component, one origin, filtered for quality, written to ~/MoukhlijMatExtract/Ready for ML/.

A family is a class the Classification part wrote (a crystal-structure type such as garnet or NASICON, or a structure
family such as oxide or sulfide), or a whole database (web_output_garnet_nasicon …). Each dataset folder holds:

  - dataset.csv   one row per material: the target (median of its values; log10 too for conductivities and
                  diffusion coefficients), their spread, how many values and papers stand behind it;
  - values.csv    every value kept, with its paper, page and sentence, to check any of them;
  - excluded.csv  every value left out, and why;
  - README.md     a datasheet: what was selected, how, the counts, and what to keep in mind when training;
  - settings.json the settings, to make the same dataset again (mme-ml-export … or the window).

Activation energies take the checks made by hand in the Verify tab: a value marked wrong is left out, a corrected
one is taken as corrected, and “verified only” keeps the checked ones alone."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

READY = "Ready for ML"
CLASS_KINDS = (("crystal_structure", "crystal structure"), ("structure_families", "structure family"))
ANY = "any"


@dataclass(frozen=True)
class Property:
    key: str
    label: str
    table: str
    column: str
    unit: str
    log: bool  # spans orders of magnitude: log10 is the target to learn


PROPERTIES: Dict[str, Property] = {
    "Ea": Property("Ea", "Activation energy", "activation_energy", "activation_energy_eV", "eV", False),
    "sigma": Property("sigma", "Ionic conductivity", "ionic_conductivity", "ionic_conductivity_S_cm", "S/cm", True),
    "sigma_e": Property("sigma_e", "Electronic conductivity", "electronic_conductivity", "electronic_conductivity_S_cm",
                        "S/cm", True),
    "D": Property("D", "Diffusion coefficient", "diffusion_coefficient", "diffusion_coefficient_cm2_s", "cm2/s", True),
}
COMPONENTS = ("bulk", "grain_boundary", "total", "surface")
ORIGINS = ("experimental", "simulation")
ATTRIBUTIONS = ("this work", "cited")
ROOM = (288.0, 308.0)  # K: what counts as room temperature when a number is given


@dataclass(frozen=True)
class Family:
    key: str      # crystal_structure/garnet | structure_families/oxide | database:WebScraping/web_output
    name: str     # garnet
    kind: str     # crystal structure | structure family | database
    folder: Path

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kind})"


@dataclass
class Settings:
    family: str                       # Family.key, or a name (garnet) that find_family resolves
    target: str = "Ea"                # a key of PROPERTIES
    component: str = ANY              # bulk | grain_boundary | total | surface | any
    origin: str = ANY                 # experimental | simulation | any
    attribution: str = "this work"    # this work | cited | any
    energy_kind: str = "arrhenius"    # activation energies only: arrhenius | migration_barrier | … | any
    mobile_ion: str = ANY             # Li+ | Na+ | … | any
    temperature: str = ANY            # any | room | "300-400" (K): conductivities and diffusion coefficients
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    plausible_only: bool = True       # leave out the values the extraction flagged (plausibility “check: …”)
    no_needs_check: bool = False      # also leave out those it marked worth a look (needs_check “yes: …”)
    min_confidence: float = 0.0
    verified_only: bool = False       # activation energies: only the values checked by hand (Verify tab)
    per_material: bool = True         # one row per material (else one row per value in dataset.csv)
    min_values: int = 1               # a material needs at least this many values
    name: str = ""                    # the dataset's folder name (made from the settings when empty)


@dataclass
class Selection:
    kept: List[Dict[str, str]] = field(default_factory=list)
    excluded: List[Tuple[Dict[str, str], str]] = field(default_factory=list)

    def reasons(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for _, why in self.excluded:
            counts[why] = counts.get(why, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))

    def materials(self) -> int:
        return len({material_of(row) for row in self.kept})

    def papers(self) -> int:
        return len({row.get("paper_id", "") for row in self.kept})


# ------------------------------------------------------------------------------------------------- finding the data
def home() -> Path:
    from LocalExtraction.about import PROJECT_HOME
    return Path(PROJECT_HOME)


def families(root: Optional[Path] = None) -> List[Family]:
    """Every family a dataset can be made of: the classes of Classification/, then the databases."""
    root = Path(root or home())
    found: List[Family] = []
    for folder, kind in CLASS_KINDS:
        base = root / "Classification" / folder
        if base.is_dir():
            for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir() and any((child / f"{p.table}.csv").is_file() for p in PROPERTIES.values()):
                    found.append(Family(f"{folder}/{child.name}", child.name, kind, child))
    for part in ("WebScraping", "LocalExtraction"):
        base = root / part
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and (child.name.startswith("web_output") or child.name.startswith(("local_output", "output_"))) \
                        and any((child / f"{p.table}.csv").is_file() for p in PROPERTIES.values()):
                    found.append(Family(f"database:{part}/{child.name}", f"{part}/{child.name}", "database", child))
    return found


def find_family(wanted: str, root: Optional[Path] = None) -> Family:
    """A family by its key (crystal_structure/garnet), or by its name alone (garnet, NASICON, oxide …)."""
    every = families(root)
    for family in every:
        if family.key == wanted:
            return family
    named = [f for f in every if f.name.lower() == wanted.lower()]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        raise ValueError(f"“{wanted}” names several families: " + ", ".join(f.key for f in named) + ". Give its key.")
    raise ValueError(f"No family “{wanted}”. Families: " + ", ".join(f.name for f in every)
                     + " (run Classification first for the crystal structures and structure families).")


def read_rows(family: Family, target: str) -> List[Dict[str, str]]:
    path = family.folder / f"{PROPERTIES[target].table}.csv"
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def counts(family: Family) -> Dict[str, int]:
    """How many values of each property the family holds."""
    return {key: len(read_rows(family, key)) for key in PROPERTIES}


# ------------------------------------------------------------------------------------------------- the selection
def number(text: object) -> Optional[float]:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)\s*(K|°C|C)\b")
_ONE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(K|°C|C)\b")


def temperature_K(text: str) -> Tuple[Optional[float], Optional[float], bool]:
    """(low, high, at room temperature) in kelvin from the temperature column: “room temperature”, “298.1 K”,
    “600-1200 K”, “25 °C”. (None, None, False) when it says nothing usable."""
    text = (text or "").strip()
    if not text:
        return None, None, False
    if "room" in text.lower():
        return 298.15, 298.15, True
    match = _RANGE.search(text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        if match.group(3) != "K":
            low, high = low + 273.15, high + 273.15
        return low, high, ROOM[0] <= low and high <= ROOM[1]
    match = _ONE.search(text)
    if match:
        value = float(match.group(1)) + (0 if match.group(2) == "K" else 273.15)
        return value, value, ROOM[0] <= value <= ROOM[1]
    return None, None, False


def material_of(row: Dict[str, str]) -> str:
    """What makes rows one material: Classification's key when the table has it, else the same key made from the
    composition (Li1.3Al0.3Ti1.7(PO4)3 and Li1.3Ti1.7Al0.3(PO4)3 are one), else the formula as it is spelled."""
    key = (row.get("material_key") or "").strip()
    if key:
        return key
    formula = (row.get("material_formula") or "").strip()
    try:
        from Classification.classify import composition, material_key
        return material_key(composition(row.get("composition", "") or ""), formula)
    except Exception:
        return formula


def _verdicts(root: Path):
    """The checks by hand, by database name (Verification/<database>.csv)."""
    from LocalExtraction.verification import Verifications
    cache: Dict[str, object] = {}

    def of(database: str):
        if database not in cache:
            cache[database] = Verifications(root / "Verification" / f"{database}.csv")
        return cache[database]
    return of


def select(settings: Settings, root: Optional[Path] = None) -> Selection:
    """The values the settings keep, and those they leave out with the reason."""
    root = Path(root or home())
    family = find_family(settings.family, root)
    prop = PROPERTIES[settings.target]
    rows = read_rows(family, settings.target)
    chosen = Selection()
    verdicts = _verdicts(root)
    database_name = family.folder.name if family.kind == "database" else ""
    low_T, high_T = _temperature_window(settings.temperature)
    from LocalExtraction.verification import apply, row_id
    for row in rows:
        row = dict(row)
        verdict = None
        if settings.target == "Ea":
            verdict = verdicts(row.get("database") or database_name).get(row_id(row))
            fixed = apply(row, verdict)
            if fixed is None:
                chosen.excluded.append((row, "marked wrong by hand"))
                continue
            row = dict(fixed)
        row["verification"] = verdict.verdict if verdict else ""
        why = _why_not(row, settings, prop, low_T, high_T)
        if why:
            chosen.excluded.append((row, why))
        else:
            chosen.kept.append(row)
    if settings.min_values > 1:
        per: Dict[str, int] = {}
        for row in chosen.kept:
            per[material_of(row)] = per.get(material_of(row), 0) + 1
        few = [row for row in chosen.kept if per[material_of(row)] < settings.min_values]
        chosen.kept = [row for row in chosen.kept if per[material_of(row)] >= settings.min_values]
        chosen.excluded += [(row, f"its material has fewer than {settings.min_values} values") for row in few]
    return chosen


def _temperature_window(text: str) -> Tuple[Optional[float], Optional[float]]:
    text = (text or ANY).strip().lower()
    if text in (ANY, "", "room"):
        return None, None
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if not match:
        raise ValueError(f"temperature “{text}”: write any, room, or a range in kelvin such as 300-400")
    return float(match.group(1)), float(match.group(2))


def _why_not(row: Dict[str, str], s: Settings, prop: Property, low_T, high_T) -> str:
    value = number(row.get(prop.column))
    if value is None:
        return "no readable value"
    if prop.log and value <= 0:
        return "not a positive value"
    if s.component != ANY and row.get("transport_component", "") != s.component:
        return f"component is {row.get('transport_component') or 'not stated'}"
    if s.origin != ANY and row.get("data_origin", "") != s.origin:
        return f"origin is {row.get('data_origin') or 'not stated'}"
    if s.attribution != ANY and row.get("attribution", "") != s.attribution:
        return f"result of {row.get('attribution') or 'not stated'}"
    if s.target == "Ea" and s.energy_kind != ANY and row.get("energy_kind", "") != s.energy_kind:
        return f"kind of energy is {row.get('energy_kind') or 'not stated'}"
    if s.mobile_ion != ANY and row.get("mobile_ion", "") != s.mobile_ion:
        return f"mobile ion is {row.get('mobile_ion') or 'not stated'}"
    if s.plausible_only and (row.get("plausibility") or "").startswith("check"):
        return "flagged by the extraction (plausibility)"
    if s.no_needs_check and (row.get("needs_check") or "").startswith("yes"):
        return "marked worth a look (needs_check)"
    if s.min_confidence and (number(row.get("confidence")) or 0.0) < s.min_confidence:
        return f"confidence below {s.min_confidence:g}"
    if s.verified_only and s.target == "Ea" and not row.get("verification"):
        return "not checked by hand"
    if s.target != "Ea" and s.temperature != ANY:
        low, high, room = temperature_K(row.get("temperature", ""))
        if s.temperature.strip().lower() == "room":
            if not room:
                return "not at room temperature"
        elif low is None:
            return "temperature not stated"
        elif low < low_T or high > high_T:
            return f"temperature outside {low_T:g}-{high_T:g} K"
    if s.value_min is not None and value < s.value_min:
        return f"value below {s.value_min:g}"
    if s.value_max is not None and value > s.value_max:
        return f"value above {s.value_max:g}"
    return ""


# ------------------------------------------------------------------------------------------------- writing
def safe_name(text: str) -> str:
    """A folder name that stays inside Ready for ML: no path separators, no “..”."""
    name = re.sub(r"[^A-Za-z0-9._+-]+", "_", text.strip()).strip("._")
    return name


def default_name(s: Settings, family: Family) -> str:
    parts = [family.name, s.target, s.component, s.origin]
    if s.target == "Ea" and s.energy_kind != ANY:
        parts.append(s.energy_kind)
    if s.mobile_ion != ANY:
        parts.append(s.mobile_ion.replace("+", ""))
    if s.target != "Ea" and s.temperature != ANY:
        parts.append("RT" if s.temperature == "room" else s.temperature + "K")
    if s.verified_only:
        parts.append("verified")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", "_".join(p for p in parts if p and p != ANY)) or "dataset"


VALUE_COLUMNS = ("material", "material_formula", "crystal_structure", "structure_family", "value", "unit", "log10_value",
                 "transport_component", "data_origin", "attribution", "energy_kind", "mobile_ion", "temperature",
                 "temperature_K", "confidence", "plausibility", "needs_check", "verification", "paper_id", "title",
                 "page", "extracted_from", "sentence", "database")
DATASET_COLUMNS = ("material", "material_formula", "crystal_structure", "structure_family", "target", "unit",
                   "log10_target", "mean", "std", "min", "max", "n_values", "n_papers", "verified_values", "group",
                   "paper_ids")


def generate(settings: Settings, root: Optional[Path] = None, out: Optional[Path] = None) -> Path:
    """Writes the dataset folder (replacing one of the same name, whole or not at all). Returns its path."""
    root = Path(root or home())
    family = find_family(settings.family, root)
    settings.family = family.key
    prop = PROPERTIES[settings.target]
    chosen = select(settings, root)
    if not chosen.kept:
        raise ValueError("No value passes these settings: loosen a filter.")
    name = safe_name(settings.name) or default_name(settings, family)
    base = Path(out) if out else root / READY
    target = base / name
    staging = base / f".{name}.writing"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    values = [_value_row(row, prop) for row in chosen.kept]
    _write(staging / "values.csv", VALUE_COLUMNS, values)
    _write(staging / "dataset.csv", DATASET_COLUMNS if settings.per_material else VALUE_COLUMNS,
           _per_material(values, prop) if settings.per_material else values)
    _write(staging / "excluded.csv", ("why", *VALUE_COLUMNS),
           [{"why": why, **_value_row(row, prop)} for row, why in chosen.excluded])
    (staging / "settings.json").write_text(json.dumps({**asdict(settings), "name": name, **_about()}, indent=2,
                                                      ensure_ascii=False), encoding="utf-8")
    (staging / "README.md").write_text(_datasheet(settings, family, prop, chosen, name), encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    staging.replace(target)
    return target


def _value_row(row: Dict[str, str], prop: Property) -> Dict[str, str]:
    value = number(row.get(prop.column))
    low, high, _ = temperature_K(row.get("temperature", ""))
    return {"material": material_of(row), "material_formula": row.get("material_formula", ""),
            "crystal_structure": row.get("crystal_structure", ""), "structure_family": row.get("structure_family", ""),
            "value": "" if value is None else f"{value:.6g}", "unit": prop.unit,
            "log10_value": f"{math.log10(value):.4f}" if prop.log and value and value > 0 else "",
            **{c: row.get(c, "") for c in ("transport_component", "data_origin", "attribution", "energy_kind",
                                            "mobile_ion", "temperature")},
            "temperature_K": "" if low is None else f"{(low + high) / 2:.1f}",
            **{c: row.get(c, "") for c in ("confidence", "plausibility", "needs_check", "verification", "paper_id",
                                            "title", "page", "extracted_from", "sentence", "database")}}


def _per_material(values: List[Dict[str, str]], prop: Property) -> List[Dict[str, str]]:
    by: Dict[str, List[Dict[str, str]]] = {}
    for row in values:
        by.setdefault(row["material"], []).append(row)
    out = []
    for material, rows in sorted(by.items()):
        numbers = [float(r["value"]) for r in rows]
        middle = statistics.median(numbers)
        first = rows[0]
        out.append({"material": material, "material_formula": first["material_formula"],
                    "crystal_structure": first["crystal_structure"], "structure_family": first["structure_family"],
                    "target": f"{middle:.6g}", "unit": prop.unit,
                    "log10_target": f"{math.log10(middle):.4f}" if prop.log and middle > 0 else "",
                    "mean": f"{statistics.fmean(numbers):.6g}",
                    "std": f"{statistics.stdev(numbers):.4g}" if len(numbers) > 1 else "",
                    "min": f"{min(numbers):.6g}", "max": f"{max(numbers):.6g}", "n_values": len(numbers),
                    "n_papers": len({r["paper_id"] for r in rows}),
                    "verified_values": sum(1 for r in rows if r["verification"]),
                    "group": first["crystal_structure"] or first["structure_family"] or material,
                    "paper_ids": "; ".join(sorted({r["paper_id"] for r in rows}))})
    return out


def _write(path: Path, columns: Iterable[str], rows: List[Dict[str, object]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _about() -> Dict[str, str]:
    try:
        from LocalExtraction.about import version
        number_ = version() or ""
    except Exception:
        number_ = ""
    return {"made_with": f"MoukhlijMatExtract {number_}".strip(), "made_at": datetime.now().isoformat(timespec="seconds")}


def _datasheet(s: Settings, family: Family, prop: Property, chosen: Selection, name: str) -> str:
    target_text = f"log10 of the {prop.label.lower()} ({prop.unit})" if prop.log else f"{prop.label.lower()} ({prop.unit})"
    reasons = "\n".join(f"| {why} | {n} |" for why, n in chosen.reasons().items()) or "| (none) | 0 |"
    filters = [("Family", family.label), ("Property", f"{prop.label} ({prop.unit})"),
               ("Transport component", s.component), ("Origin", s.origin), ("Result of", s.attribution)]
    if s.target == "Ea":
        filters.append(("Kind of energy", s.energy_kind))
    else:
        filters.append(("Temperature", "room temperature" if s.temperature == "room" else s.temperature))
    filters += [("Mobile ion", s.mobile_ion), ("Value range", f"{s.value_min if s.value_min is not None else '—'} to "
                                                             f"{s.value_max if s.value_max is not None else '—'}"),
                ("Flagged values left out", "yes" if s.plausible_only else "no"),
                ("Values marked worth a look left out", "yes" if s.no_needs_check else "no"),
                ("Minimum confidence", f"{s.min_confidence:g}"),
                ("Checked by hand only", "yes" if s.verified_only else "no"),
                ("Minimum values per material", str(s.min_values)),
                ("Rows of dataset.csv", "one per material (median of its values)" if s.per_material else "one per value")]
    table = "\n".join(f"| {k} | {v} |" for k, v in filters)
    return f"""# {name}

A dataset for machine learning made by MoukhlijMatExtract ({_about()['made_at'][:10]}).

**Target:** {target_text}. **{chosen.materials()} materials**, {len(chosen.kept)} values from {chosen.papers()} papers;
{len(chosen.excluded)} values left out.

## Files

| File | What it holds |
| --- | --- |
| `dataset.csv` | {"one row per material: `target` is the median of its values (`log10_target` for conductivities and diffusion coefficients), with their spread, number of values and papers, and a `group` column" if s.per_material else "one row per value"} |
| `values.csv` | every value kept, with its paper, page and sentence |
| `excluded.csv` | every value left out, with why |
| `settings.json` | the settings: `mme-ml-export --settings settings.json` makes the same dataset again |

## Selection

| Setting | Value |
| --- | --- |
{table}

## Values left out

| Why | Values |
| --- | --- |
{reasons}

## Before training

- **Labels are extracted, not curated.** Values were read from papers automatically; their measured accuracy is in
  MoukhlijMatExtract's docs/LIMITATIONS.md. Prefer the values checked by hand (`verification` column, the Verify tab).
- **Split by group, not by row.** Several rows of one material, or of one structure type, in both training and test
  sets inflate the score: use the `group` (or `material`) column for grouped cross-validation.
- **Features are yours to add.** The formulas (`material_formula`) are there to compute composition descriptors
  (for example with matminer).
- **Spread is information.** `std`, `min`, `max` and `n_papers` say how far papers disagree on a material.
"""
