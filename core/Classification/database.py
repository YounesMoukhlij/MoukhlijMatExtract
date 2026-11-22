# Classification/database.py
"""Reading the databases of the two extraction parts, and writing one database per class.

Each class folder is a database of the same shape as the ones it was read from — materials.csv,
the tables of the transport quantities (activation_energy.csv, ionic_conductivity.csv,
electronic_conductivity.csv, diffusion_coefficient.csv), properties.csv, papers.csv — holding only
the materials of that class, so whatever reads a database of MoukhlijMatExtract reads it too:

    python -m SelectingTopMaterial --source Classification/crystal_structure/NASICON

The databases themselves are only read."""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from LocalExtraction.exporter import COLUMNS, article_title

from .about import CRYSTAL_STRUCTURE, STRUCTURE_FAMILIES, UNCLASSIFIED
from .classify import (COMPONENT_WORDS, COMPONENTS, NO_FAMILY, Material, classify_the_rest, composition, material_key,
                       number)

MATERIALS, ENERGIES, PROPERTIES, PAPERS = "materials", "activation_energy", "properties", "papers"
# The tables of values copied into each class folder: every value of its materials.
VALUE_TABLES = (ENERGIES, "ionic_conductivity", "electronic_conductivity", "diffusion_coefficient", PROPERTIES)
AXES = ((CRYSTAL_STRUCTURE, "structure_type", "crystal_structure"), (STRUCTURE_FAMILIES, "family", "structure_family"))
# The tables whose values say which transport component they describe (bulk, grain_boundary, surface, total):
# split by it, each class has one database per component inside its folder.
TRANSPORT_TABLES = (ENERGIES, "ionic_conductivity", "electronic_conductivity", "diffusion_coefficient")
_IONIC = "ionic_conductivity"
# Written beside summary.csv: each class's activation energies by transport component.
BY_COMPONENT = "activation_energy_by_component"
_NOT_GIVEN = "not given by the database"  # a component or its basis a database of an earlier version does not have


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


def partly_rebuilt(folder: Path) -> bool:
    """A rebuild of the database was stopped part-way (the extraction removes this file at its end):
    it lacks papers until that part is run again."""
    return (Path(folder) / "rebuild_pending.json").exists()


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
        # No row in any database: the table is still written with its own header.
        given = next((list(s.tables[table].columns) for s in classified.sources if len(s.tables[table].columns)), [])
        known = given or COLUMNS.get(table, [])
        return pd.DataFrame(columns=[*known, "database", "material_key", *(column for _, _, column in AXES)])
    rows = pd.concat(frames, ignore_index=True, sort=False).fillna("NONE")
    rows = rows[rows["material_key"] != ""]
    for _, attribute, column in AXES:
        rows[column] = [getattr(classified.materials[key], attribute) for key in rows["material_key"]]
    return rows


# ---------------------------------------------------------------------------
# Activation energies by transport component
# ---------------------------------------------------------------------------
def energies_of(classified: Classified) -> pd.DataFrame:
    """Every activation energy of the databases with a number, each with its material and the two
    classes of it, its value as a number (`Ea_eV`), the transport component it describes
    (`component`: bulk, grain_boundary, surface, total) and whether the paper states that component
    or the extraction assumed it (`component_basis`: stated / assumed, from the `basis` column)."""
    rows = _rows(classified, ENERGIES)
    if rows.empty:
        return rows.assign(Ea_eV=pd.Series(dtype=float), component=pd.Series(dtype=str),
                           component_basis=pd.Series(dtype=str), material=pd.Series(dtype=str))
    rows = rows.assign(Ea_eV=[number(v) for v in rows.get("activation_energy_eV", pd.Series([""] * len(rows)))])
    rows = rows[rows["Ea_eV"].notna()].copy()
    rows["component"] = component_of(rows)
    basis = rows["basis"].astype(str) if "basis" in rows else pd.Series("", index=rows.index)
    rows["component_basis"] = basis.str.extract(r"component: (stated|assumed)", expand=False).fillna(_NOT_GIVEN)
    rows["material"] = [classified.materials[key].name for key in rows["material_key"]]
    return rows.reset_index(drop=True)


def component_of(rows: pd.DataFrame) -> pd.Series:
    """The transport component of each row of a table of values, in one spelling ("grain boundary" →
    grain_boundary); _NOT_GIVEN for a database of an earlier version, which does not record it."""
    component = rows["transport_component"] if "transport_component" in rows else pd.Series("", index=rows.index)
    component = component.astype(str).str.strip().str.lower().str.replace(" ", "_")
    return component.where(~component.isin(["", "none", "nan"]), _NOT_GIVEN)


def components_in(*tables: pd.DataFrame) -> list[str]:
    """The transport components these tables hold values of: bulk, grain_boundary, total in that
    order, then any other (surface)."""
    found = {c for table in tables if len(table) for c in component_of(table)} - {_NOT_GIVEN}
    return [c for c in COMPONENTS if c in found] + sorted(found - set(COMPONENTS))


def component_stats(energies: pd.DataFrame, by: str) -> pd.DataFrame:
    """For each value of `by` (a class column, or material_key) and each transport component: how
    many activation energies, of how many materials, the lowest and whose, the median and the
    highest, and of how many the paper itself states the component."""
    columns = [by, "component", "n_values", "n_materials", "min_eV", "min_material", "median_eV", "max_eV",
               "n_component_stated", "n_component_assumed"]
    if energies.empty:
        return pd.DataFrame(columns=columns)
    out = []
    for (group, component), frame in energies.groupby([by, "component"], sort=False):
        best = frame.loc[frame["Ea_eV"].idxmin()]
        out.append({by: group, "component": component, "n_values": len(frame),
                    "n_materials": frame["material_key"].nunique(), "min_eV": round(float(best["Ea_eV"]), 4),
                    "min_material": best["material"], "median_eV": round(float(frame["Ea_eV"].median()), 4),
                    "max_eV": round(float(frame["Ea_eV"].max()), 4),
                    "n_component_stated": int((frame["component_basis"] == "stated").sum()),
                    "n_component_assumed": int((frame["component_basis"] == "assumed").sum())})
    return pd.DataFrame(out, columns=columns)


def sub_class_table(stats: pd.DataFrame, column: str, classes: list[str],
                    places: dict[tuple[str, str], str]) -> pd.DataFrame:
    """Every class with its sub-classes under it — NASICON: bulk, grain boundary, total — one line
    each, with the activation energies of that component (an answer saying there is none, for a
    sub-class with no activation energy) and its folder."""
    mine = {(row[column], row["component"]): row for row in stats.to_dict("records")} if len(stats) else {}
    lines = []
    for label in classes:
        components = [*COMPONENTS, *sorted(c for (group, c) in mine if group == label and c not in COMPONENTS)]
        for component in components:
            row = mine.get((label, component))
            none = f"no {COMPONENT_WORDS.get(component, component)} activation energy reported"
            lines.append({column: label, "component": component, **({k: v for k, v in row.items()
                                                                       if k not in (column, "component")} if row else {
                "n_values": 0, "n_materials": 0, "min_eV": none, "min_material": none, "median_eV": none,
                "max_eV": none, "n_component_stated": 0, "n_component_assumed": 0}),
                "folder": places.get((label, component), "no folder (no value of this component)")})
    return pd.DataFrame(lines, columns=[column, "component", "n_values", "n_materials", "min_eV", "min_material",
                                        "median_eV", "max_eV", "n_component_stated", "n_component_assumed", "folder"])


def component_columns(stats: pd.DataFrame, by: str, group: str) -> dict[str, object]:
    """One class's activation energies side by side for bulk, grain boundary and total, as the
    columns of its line in summary.csv: count, lowest (and whose), median."""
    mine = {row["component"]: row for row in stats[stats[by] == group].to_dict("records")} if len(stats) else {}
    columns: dict[str, object] = {}
    for component in COMPONENTS:
        row, none = mine.get(component), f"no {COMPONENT_WORDS[component]} value reported"
        columns[f"n_Ea_{component}"] = row["n_values"] if row else 0
        columns[f"Ea_{component}_min_eV"] = row["min_eV"] if row else none
        columns[f"Ea_{component}_min_material"] = row["min_material"] if row else none
        columns[f"Ea_{component}_median_eV"] = row["median_eV"] if row else none
    return columns


def material_rows(classified: Classified, energies: pd.DataFrame,
                  conductivities: dict[str, list[float]]) -> dict[str, dict[str, object]]:
    """Every material's line of materials.csv, from these activation energies (all of them, or the
    ones a filter kept)."""
    overall: dict[str, list[float]] = defaultdict(list)
    by_component: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key, value, component in zip(energies.get("material_key", []), energies.get("Ea_eV", []),
                                     energies.get("component", [])):
        overall[key].append(float(value))
        by_component[key][component].append(float(value))
    return {key: m.row(overall.get(key, []), conductivities.get(key, []), by_component.get(key))
            for key, m in classified.materials.items()}


def conductivities_of(classified: Classified) -> dict[str, list[float]]:
    """The ionic conductivities of each material, in S/cm."""
    properties = _rows(classified, PROPERTIES)
    found: dict[str, list[float]] = defaultdict(list)
    if not properties.empty and "property_name" in properties:
        conductivity = properties[properties["property_name"] == "Ionic_Conductivity"]
        for key, value in zip(conductivity["material_key"], conductivity["normalized_value"]):
            if number(value) is not None:
                found[key].append(number(value))
    return found


def class_groups(classified: Classified, attribute: str, axis: str) -> dict[str, list[str]]:
    """The materials of each class of one axis, the largest class first. On the crystal axis the
    classes are the known crystal families: a material of none of them is in no class of it (it is
    in all_materials.csv, and in its structure family)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for key, material in classified.materials.items():
        label = getattr(material, attribute)
        if not (axis == CRYSTAL_STRUCTURE and label == NO_FAMILY):
            groups[label].append(key)
    return {label: groups[label] for label in sorted(groups, key=lambda name: (-len(groups[name]), name.casefold()))}


def class_kind(axis: str, label: str) -> str:
    """What a class is: a crystal family, a state of no crystal structure, or a family of compounds."""
    if axis != CRYSTAL_STRUCTURE:
        return "family of compounds"
    return "state (no crystal structure)" if label in ("amorphous", "glass-ceramic") else "crystal family"


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


def _write_csv(frame: pd.DataFrame, path: Path, titles: dict[str, str] | None = None) -> None:
    (frame if titles is None else titled(frame, titles)).to_csv(path, index=False, encoding="utf-8-sig")


def titled(frame: pd.DataFrame, titles: dict[str, str]) -> pd.DataFrame:
    """A table with the name of its articles: `title` after `paper_id`, `articles` after `papers`
    (the titles of the papers a material's values come from) — when it does not have them yet."""
    def title(paper: str) -> str:
        return titles.get(paper) or article_title("", paper)
    if "paper_id" in frame.columns and "title" not in frame.columns:
        frame = frame.copy()
        frame.insert(list(frame.columns).index("paper_id") + 1, "title", [title(p) for p in frame["paper_id"]])
    if "papers" in frame.columns and "articles" not in frame.columns:
        frame = frame.copy()
        frame.insert(list(frame.columns).index("papers") + 1, "articles",
                     [" | ".join(title(p.strip()) for p in str(v).split(" | ") if p.strip()) for v in frame["papers"]])
    return frame


def write(classified: Classified, out_dir: Path) -> dict[str, pd.DataFrame]:
    """Writes crystal_structure/<type>/ and structure_families/<family>/ — one database each — with
    a summary.csv and a workbook per axis, and all_materials.csv beside them. Returns the summaries.

    An axis folder is written aside first and only then put in the place of the previous one, so
    a class that no longer has a material does not linger and a failed run leaves the old one. The
    returned dict also holds, under "<axis>/activation_energy_by_component", each class's sub-classes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    values = {name: _rows(classified, name) for name in VALUE_TABLES}
    papers = pd.concat([s.tables[PAPERS].assign(database=s.name) for s in classified.sources if not s.tables[PAPERS].empty],
                       ignore_index=True, sort=False) if any(not s.tables[PAPERS].empty for s in classified.sources) \
        else pd.DataFrame(columns=["paper_id", "database"])
    papers = papers.fillna("NONE").drop_duplicates("paper_id")  # the most trusted database first
    titles = {row["paper_id"]: article_title(row.get("title"), row.get("filename") or row["paper_id"])
              for _, row in papers.iterrows()}

    energies = energies_of(classified)
    rows = material_rows(classified, energies, conductivities_of(classified))

    def ordered(keys: list[str]) -> pd.DataFrame:
        return titled(_lowest_first(pd.DataFrame([rows[key] for key in keys])), titles)

    summaries: dict[str, pd.DataFrame] = {}
    for axis, attribute, column in AXES:
        groups = class_groups(classified, attribute, axis)
        stats = component_stats(energies, column)
        staging = out_dir / f".{axis}.writing"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        summary, sheets = [], {}
        places: dict[tuple[str, str], str] = {}  # (class, component) → its folder
        for label in groups:
            keys = set(groups[label])
            place = folder_name(label)
            folder = staging / place
            folder.mkdir(parents=True)
            materials = ordered(groups[label])
            its = {name: (table[table["material_key"].isin(keys)] if not table.empty else table)
                   for name, table in values.items()}
            its_properties = its[PROPERTIES]
            its_energies = energies[energies["material_key"].isin(keys)]
            its_papers = {paper for key in keys for paper in classified.materials[key].papers}
            _write_csv(materials, folder / f"{MATERIALS}.csv")
            for name, table in its.items():
                _write_csv(table, folder / f"{name}.csv", titles)
            _write_csv(papers[papers["paper_id"].isin(its_papers)], folder / f"{PAPERS}.csv")
            for component in _component_folders(folder, keys, its, papers, classified, titles):
                places[(label, component)] = f"{axis}/{place}/{component}"
            sheets[label] = materials
            best = materials.iloc[0] if len(materials) and number(materials.iloc[0]["Ea_min_eV"]) is not None else None
            summary.append({
                column: label, "n_materials": len(keys), "n_papers": len(its_papers),
                "n_activation_energies": len(its_energies),
                "n_ionic_conductivities": int((its_properties.get("property_name", pd.Series(dtype=str)) == "Ionic_Conductivity").sum()),
                "lowest_Ea_eV": best["Ea_min_eV"] if best is not None else "no activation energy reported",
                "lowest_Ea_material": best["material"] if best is not None else "no activation energy reported",
                **component_columns(stats, column, label),
                "materials": " | ".join(materials["material"].head(8)) + (" | …" if len(materials) > 8 else ""),
                "kind": class_kind(axis, label),
                "folder": f"{axis}/{place}",
            })
        summaries[axis] = pd.DataFrame(summary)
        _write_csv(summaries[axis], staging / "summary.csv")
        by_component = sub_class_table(stats, column, list(summaries[axis][column]), places)
        summaries[f"{axis}/{BY_COMPONENT}"] = by_component
        _write_csv(by_component, staging / f"{BY_COMPONENT}.csv")
        _workbook(staging / f"{axis}.xlsx", summaries[axis], sheets, by_component)
        target = out_dir / axis
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)

    every = titled(pd.DataFrame(list(rows.values())), titles)
    every = every.sort_values(["crystal_structure", "structure_family", "material"],
                              key=lambda c: c.str.casefold() if c.dtype == object else c)
    _write_csv(every, out_dir / "all_materials.csv")
    return summaries


def _lowest_first(frame: pd.DataFrame) -> pd.DataFrame:
    """Materials, the lowest activation energy first (those with none last)."""
    if frame.empty:
        return frame
    lowest = pd.to_numeric(frame["Ea_min_eV"], errors="coerce")
    return frame.assign(_ea=lowest).sort_values(["_ea", "material"], na_position="last").drop(columns="_ea")


def sub_classes(*tables: pd.DataFrame) -> list[str]:
    """The sub-classes of every class: bulk, grain_boundary and total — always, a class with no value
    of one has it empty — then any other component its values describe (surface)."""
    return [*COMPONENTS, *(c for c in components_in(*tables) if c not in COMPONENTS)]


def _component_folders(folder: Path, keys: set[str], its: dict[str, pd.DataFrame], papers: pd.DataFrame,
                       classified: Classified, titles: dict[str, str] | None = None) -> list[str]:
    """Inside a class folder, its sub-classes: one database per transport component — NASICON/bulk/,
    NASICON/grain_boundary/, NASICON/total/ — each holding the values of that component only (the
    activation energies, ionic and electronic conductivities and diffusion coefficients that
    describe it), the materials they are of, and their papers. Every class has the three; one with no
    value of a component has its folder with the tables' headers and no row. Returns the components."""
    present = sub_classes(*(its[name] for name in TRANSPORT_TABLES))
    header = _component_row(classified.materials[next(iter(keys))].row([], []), "")
    for component in present:
        tables = {name: its[name][component_of(its[name]) == component] if len(its[name]) else its[name]
                  for name in TRANSPORT_TABLES}
        keys_of_component = sorted({key for table in tables.values() for key in table.get("material_key", [])})
        energies, sigma, papers_of = defaultdict(list), defaultdict(list), defaultdict(set)
        for key, value in zip(tables[ENERGIES].get("material_key", []), tables[ENERGIES].get("activation_energy_eV", [])):
            if number(value) is not None:
                energies[key].append(number(value))
        for key, value in zip(tables[_IONIC].get("material_key", []), tables[_IONIC].get("ionic_conductivity_S_cm", [])):
            if number(value) is not None:
                sigma[key].append(number(value))
        for table in tables.values():
            for key, paper in zip(table.get("material_key", []), table.get("paper_id", [])):
                papers_of[key].add(paper)
        rows = []
        for key in keys_of_component:
            row = classified.materials[key].row(energies[key], sigma[key])
            row.update(n_papers=len(papers_of[key]), papers=" | ".join(sorted(papers_of[key])))
            rows.append(_component_row(row, component))
        place = folder / component
        place.mkdir()
        _write_csv(_lowest_first(pd.DataFrame(rows, columns=list(header))), place / f"{MATERIALS}.csv", titles or {})
        for name, table in tables.items():
            _write_csv(table, place / f"{name}.csv", titles or {})
        cited = {paper for found in papers_of.values() for paper in found}
        _write_csv(papers[papers["paper_id"].isin(cited)], place / f"{PAPERS}.csv")
    return present


def _component_row(row: dict[str, object], component: str) -> dict[str, object]:
    """A material's line in the folder of one component: its values of that component are its values,
    so the columns of the other components go."""
    row = {name: value for name, value in row.items()
           if not any(name in (f"n_Ea_{c}", f"Ea_{c}_min_eV") for c in COMPONENTS)}
    return {"material": row.pop("material"), "transport_component": component, **row}


def _workbook(path: Path, summary: pd.DataFrame, sheets: dict[str, pd.DataFrame],
              by_component: pd.DataFrame | None = None) -> None:
    """The summary, the activation energies by component, and one sheet per class; skipped without
    openpyxl (the CSV files hold it all)."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return
    taken: set[str] = set()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name=_sheet_name("Summary", taken), index=False)
        if by_component is not None:
            by_component.to_excel(writer, sheet_name=_sheet_name("Ea by component", taken), index=False)
        for label, frame in sheets.items():
            frame.to_excel(writer, sheet_name=_sheet_name(label, taken), index=False)
