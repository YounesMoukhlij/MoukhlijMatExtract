# Crystal and Structure Classification/database.py
"""Reading the databases of the two extraction parts, and writing one database per class.

Each class folder is a database of the same shape as the ones it was read from — materials.csv,
the tables of the transport quantities (activation_energy.csv, ionic_conductivity.csv,
electronic_conductivity.csv, diffusion_coefficient.csv), properties.csv, papers.csv — holding only
the materials of that class, so whatever reads a database of MoukhlijMatExtract reads it too:

    python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/NASICON"

The databases themselves are only read."""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .about import COMPOSITION_TYPES, CRYSTAL_STRUCTURE, STRUCTURE_FAMILIES, UNCLASSIFIED
from .classify import Material, classify_the_rest, composition, material_key, number

MATERIALS, ENERGIES, PROPERTIES, PAPERS = "materials", "activation_energy", "properties", "papers"
# The tables of values copied into each class folder: every value of its materials.
VALUE_TABLES = (ENERGIES, "ionic_conductivity", "electronic_conductivity", "diffusion_coefficient", PROPERTIES)
AXES = ((CRYSTAL_STRUCTURE, "structure_type", "crystal_structure"), (STRUCTURE_FAMILIES, "family", "structure_family"))


@dataclass
class Source:
    """One database of the extraction: its folder and the tables the classification reads."""
    name: str
    path: Path
    tables: dict[str, pd.DataFrame]


def _table(folder: Path, name: str) -> pd.DataFrame:
    path = folder / f"{name}.csv"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def read(folder: Path) -> Source | None:
    """The tables of a database; None when the folder holds none (no materials.csv)."""
    if not (folder / f"{MATERIALS}.csv").is_file():
        return None
    return Source(folder.name, folder, {name: _table(folder, name) for name in (MATERIALS, *VALUE_TABLES, PAPERS)})


# ---------------------------------------------------------------------------
# Classifying
# ---------------------------------------------------------------------------
@dataclass
class Classified:
    materials: dict[str, Material]               # material key → the material
    link: dict[tuple[str, str, str], str]        # (database, paper_id, material_id) → material key
    sources: list[Source]


def classify(sources: list[Source]) -> Classified:
    """Every material of the databases, one per composition, each with its two classes."""
    materials: dict[str, Material] = {}
    link: dict[tuple[str, str, str], str] = {}
    for source in sources:
        for row in source.tables[MATERIALS].to_dict("records"):
            amounts = composition(row.get("elements", ""))
            formula = row.get("normalized_formula") or row.get("raw_formula") or ""
            if not formula or formula == "NONE":
                continue
            key = material_key(amounts, formula)
            material = materials.setdefault(key, Material(key, amounts))
            material.add(source.name, row.get("paper_id", ""), formula, row.get("structure", ""))
            link[(source.name, row.get("paper_id", ""), row.get("material_id", ""))] = key
    for material in materials.values():
        material.classify()
    classify_the_rest(list(materials.values()))
    return Classified(materials, link, sources)


def _rows(classified: Classified, table: str) -> pd.DataFrame:
    """A table of every database at once, each row with its database, its material and its two classes."""
    frames = []
    for source in classified.sources:
        frame = source.tables[table]
        if frame.empty:
            continue
        frame = frame.copy()
        keys = [classified.link.get((source.name, paper, material), "")
                for paper, material in zip(frame.get("paper_id", ""), frame.get("material_id", ""))]
        frame["database"] = source.name
        frame["material_key"] = keys
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["database", "material_key"])
    rows = pd.concat(frames, ignore_index=True, sort=False).fillna("NONE")
    rows = rows[rows["material_key"] != ""]
    for _, attribute, column in AXES:
        rows[column] = [getattr(classified.materials[key], attribute) for key in rows["material_key"]]
    return rows


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def folder_name(label: str) -> str:
    """A class as a folder name: as it is written, without what a file system refuses."""
    return re.sub(r'[\\/:*?"<>|]', "_", label).strip() or UNCLASSIFIED


def _sheet_name(label: str, taken: set[str]) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "_", label)[:31] or UNCLASSIFIED
    base, n = name, 2
    while name.casefold() in taken:
        name = f"{base[:28]}~{n}"
        n += 1
    taken.add(name.casefold())
    return name


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write(classified: Classified, out_dir: Path) -> dict[str, pd.DataFrame]:
    """Writes crystal_structure/<type>/ and structure_families/<family>/ — one database each — with
    a summary.csv and a workbook per axis, and all_materials.csv beside them. Returns the summaries.

    An axis folder is written aside first and only then put in the place of the previous one, so
    a class that no longer has a material does not linger and a failed run leaves the old one."""
    out_dir.mkdir(parents=True, exist_ok=True)
    values = {name: _rows(classified, name) for name in VALUE_TABLES}
    energies, properties = values[ENERGIES], values[PROPERTIES]
    papers = pd.concat([s.tables[PAPERS].assign(database=s.name) for s in classified.sources if not s.tables[PAPERS].empty],
                       ignore_index=True, sort=False) if any(not s.tables[PAPERS].empty for s in classified.sources) \
        else pd.DataFrame(columns=["paper_id", "database"])
    papers = papers.fillna("NONE").drop_duplicates("paper_id")  # the most trusted database first

    by_key_energy: dict[str, list[float]] = defaultdict(list)
    for key, value in zip(energies.get("material_key", []), energies.get("activation_energy_eV", [])):
        if number(value) is not None:
            by_key_energy[key].append(number(value))
    by_key_sigma: dict[str, list[float]] = defaultdict(list)
    if not properties.empty and "property_name" in properties:
        conductivity = properties[properties["property_name"] == "Ionic_Conductivity"]
        for key, value in zip(conductivity["material_key"], conductivity["normalized_value"]):
            if number(value) is not None:
                by_key_sigma[key].append(number(value))
    rows = {key: m.row(by_key_energy.get(key, []), by_key_sigma.get(key, [])) for key, m in classified.materials.items()}

    def ordered(keys: list[str]) -> pd.DataFrame:
        frame = pd.DataFrame([rows[key] for key in keys])
        lowest = pd.to_numeric(frame["Ea_min_eV"], errors="coerce")
        return frame.assign(_ea=lowest).sort_values(["_ea", "material"], na_position="last").drop(columns="_ea")

    summaries: dict[str, pd.DataFrame] = {}
    for axis, attribute, column in AXES:
        groups: dict[str, list[str]] = defaultdict(list)
        nested: set[str] = set()
        for key, material in classified.materials.items():
            groups[getattr(material, attribute)].append(key)
            if axis == CRYSTAL_STRUCTURE and material.structure_type_basis.startswith("inferred: its composition type"):
                nested.add(material.structure_type)
        staging = out_dir / f".{axis}.writing"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        summary, sheets = [], {}
        for label in sorted(groups, key=lambda name: (name in nested, -len(groups[name]), name.casefold())):
            keys = set(groups[label])
            place = f"{COMPOSITION_TYPES}/{folder_name(label)}" if label in nested else folder_name(label)
            folder = staging / place
            folder.mkdir(parents=True)
            materials = ordered(groups[label])
            its = {name: (table[table["material_key"].isin(keys)] if not table.empty else table)
                   for name, table in values.items()}
            its_energies, its_properties = its[ENERGIES], its[PROPERTIES]
            its_papers = {paper for key in keys for paper in classified.materials[key].papers}
            _write_csv(materials, folder / f"{MATERIALS}.csv")
            for name, table in its.items():
                _write_csv(table, folder / f"{name}.csv")
            _write_csv(papers[papers["paper_id"].isin(its_papers)], folder / f"{PAPERS}.csv")
            sheets[label] = materials
            best = materials.iloc[0] if len(materials) and number(materials.iloc[0]["Ea_min_eV"]) is not None else None
            summary.append({
                column: label, "n_materials": len(keys), "n_papers": len(its_papers),
                "n_activation_energies": len(its_energies),
                "n_ionic_conductivities": int((its_properties.get("property_name", pd.Series(dtype=str)) == "Ionic_Conductivity").sum()),
                "lowest_Ea_eV": best["Ea_min_eV"] if best is not None else "no activation energy reported",
                "lowest_Ea_material": best["material"] if best is not None else "no activation energy reported",
                "materials": " | ".join(materials["material"].head(8)) + (" | …" if len(materials) > 8 else ""),
                "kind": "composition type (no named structure type)" if label in nested else (
                    "structure type" if axis == CRYSTAL_STRUCTURE else "family of compounds"),
                "folder": f"{axis}/{place}",
            })
        summaries[axis] = pd.DataFrame(summary)
        _write_csv(summaries[axis], staging / "summary.csv")
        _workbook(staging / f"{axis}.xlsx", summaries[axis], sheets)
        target = out_dir / axis
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)

    every = pd.DataFrame(list(rows.values()))
    every = every.sort_values(["crystal_structure", "structure_family", "material"],
                              key=lambda c: c.str.casefold() if c.dtype == object else c)
    _write_csv(every, out_dir / "all_materials.csv")
    return summaries


def _workbook(path: Path, summary: pd.DataFrame, sheets: dict[str, pd.DataFrame]) -> None:
    """The summary and one sheet per class; skipped without openpyxl (the CSV files hold it all)."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return
    taken: set[str] = set()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name=_sheet_name("Summary", taken), index=False)
        for label, frame in sheets.items():
            frame.to_excel(writer, sheet_name=_sheet_name(label, taken), index=False)
