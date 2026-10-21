# SelectingTopMaterial/loader.py
"""Reading the activation energies back from the results folders MoukhlijMatExtract writes
(LocalExtraction/local_output/ and WebScraping/web_output/).

Only the files are read — activation_energy.csv, and papers.csv beside it for titles and DOIs —
never the code that wrote them, so the selection keeps working whatever the extraction becomes,
and nothing here can change a database. A folder written by an earlier version has other columns
(source_type for extracted_from, no n_assumed): what a row does not say is left "not reported"."""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from .models import NOT_REPORTED, DatabaseReport, Measurement

# The results folders of a project, from its root, in the order they are trusted when two of them
# hold the same paper: the local articles, then the ones fetched from the web.
KNOWN_DATABASES = ("LocalExtraction/local_output", "WebScraping/web_output")
TABLE, PAPERS, UNASSIGNED = "activation_energy.csv", "papers.csv", "unassigned_values.csv"

_FORMULA_COLUMNS = ("material_formula", "normalized_formula", "formula", "material")
_ENERGY_COLUMNS = ("activation_energy_eV", "activation_energy", "Ea_eV", "Ea")
_MISSING = {"", "none", "nan", "null", "n/a", "na", "unspecified", "unknown"}
_DEFAULT_CONFIDENCE = 0.5

_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y "
    "Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re "
    "Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg "
    "Cn Nh Fl Mc Lv Ts Og".split())
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")

_CRYSTAL_SYSTEMS = ("cubic", "tetragonal", "orthorhombic", "monoclinic", "hexagonal", "trigonal",
                    "rhombohedral", "triclinic")
_DISORDERED = ("amorphous", "glass-ceramic", "glass", "glassy")
_GREEK = {"α": "α", "alpha": "α", "β": "β", "ꞵ": "β", "beta": "β", "γ": "γ", "gamma": "γ", "δ": "δ", "delta": "δ"}
_GREEK_PHASE = re.compile(rf"({'|'.join(_GREEK)})(?:[\s\-−‐–]*(?:phase|form|type|polymorph))?", re.IGNORECASE)


def discover(project_root: Path) -> list[Path]:
    """The results folders of a project that hold activation energies."""
    return [project_root / name for name in KNOWN_DATABASES if (project_root / name / TABLE).is_file()]


def polymorph(structure: str) -> str:
    """The phase a structure names — "cubic | garnet" → "cubic", "β-phase" → "β-phase" — and
    nothing when it only names a family (garnet, NASICON): two phases of one composition are two
    materials to whoever asks for them apart, a family is not."""
    for label in (part.strip() for part in structure.split("|")):
        lowered = label.casefold()
        if lowered in _CRYSTAL_SYSTEMS or lowered in _DISORDERED:
            return lowered
        greek = _GREEK_PHASE.fullmatch(label)
        if greek:
            return f"{_GREEK[greek.group(1).casefold()]}-phase"
    return ""


def material_key(formula: str, composition: str = "") -> tuple[str, tuple[str, ...]]:
    """What makes two rows the same material, and the elements it is made of: the composition
    when the database gives it — Li1.3Al0.3Ti1.7(PO4)3 and Li1.3Ti1.7Al0.3(PO4)3 are one
    material — otherwise the formula as it is spelled."""
    try:
        amounts = json.loads(composition) if composition else None
    except ValueError:
        amounts = None
    if isinstance(amounts, dict) and amounts:
        parts = []
        for element, amount in sorted(amounts.items()):
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                parts.append(f"{element}{round(float(amount), 4):g}")
            else:  # a variable composition: Na1-xLa1-xZrxCl4 has "1-x" of Na
                parts.append(f"{element}[{''.join(str(amount).split())}]")
        return " ".join(parts), tuple(sorted(amounts))
    spelled = "".join(formula.translate(_SUBSCRIPTS).split())
    elements = sorted({symbol for symbol in re.findall(r"[A-Z][a-z]?", spelled) if symbol in _ELEMENTS})
    return f"formula:{spelled}", tuple(elements)


def load(databases: Sequence[Path], root: Path | None = None) -> tuple[list[Measurement], list[DatabaseReport]]:
    """Every activation energy of the folders, each paper counted once.

    A paper that several folders hold — an earlier copy of a database, or an article that sits in
    LocalExtraction/papers/ and was fetched from the web as well — is read from the first
    folder that has it, so that one result never weighs twice in a ranking."""
    values: list[Measurement] = []
    reports: list[DatabaseReport] = []
    claimed: dict[str, str] = {}  # paper → the folder its values are taken from
    for path in databases:
        found, report, covered = _load_database(Path(path), root, claimed)
        values.extend(found)
        reports.append(report)
        for paper in covered:
            claimed.setdefault(paper, report.name)
    return values, reports


def _load_database(path: Path, root: Path | None,
                   claimed: dict[str, str]) -> tuple[list[Measurement], DatabaseReport, set[str]]:
    table = path if path.is_file() else path / TABLE
    folder = table.parent
    report = DatabaseReport(name=folder.name or str(folder), path=_shown(folder, root))
    if not folder.is_dir():
        return [], replace(report, problem="folder not found"), set()
    try:
        rows = _read(table)
    except FileNotFoundError:
        return [], replace(report, problem=f"no {TABLE} in it — run the extraction first"), set()
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        return [], replace(report, problem=f"{table.name} cannot be read ({error})"), set()

    columns = set(rows[0]) if rows else set()
    if rows and not (columns & set(_FORMULA_COLUMNS) and columns & set(_ENERGY_COLUMNS)):
        return [], replace(report, rows=len(rows),
                           problem=f"{table.name} has no {_FORMULA_COLUMNS[0]} / {_ENERGY_COLUMNS[0]} column"), set()

    papers = _papers(folder)
    covered = {about["key"] for about in papers.values()}
    kept: dict[tuple, Measurement] = {}
    already_read = repeated = unreadable = 0
    for row in rows:
        value = _measurement(row, papers, report.name)
        if value is None:
            unreadable += 1
            continue
        covered.add(value.paper_key)
        if value.paper_key in claimed:
            already_read += 1
            continue
        # A paper states its result in the abstract, then again in the text: one value, not two.
        same = (value.paper_key, value.material_key, value.polymorph, round(value.energy_eV, 6),
                value.data_origin, value.transport_component)
        if same in kept:
            repeated += 1
            if value.confidence <= kept[same].confidence:
                continue
        kept[same] = value

    found = list(kept.values())
    return found, replace(
        report, rows=len(rows), values=len(found), papers=len({v.paper_key for v in found}),
        already_read=already_read, repeated=repeated, unreadable=unreadable,
        unassigned=_unassigned(folder, papers, claimed)), covered


def _measurement(row: dict[str, str], papers: dict[str, dict[str, str]], database: str) -> Measurement | None:
    """One row of activation_energy.csv; nothing when it names no material or gives no energy
    above zero — such a row cannot be ranked."""
    formula = _cell(row, *_FORMULA_COLUMNS)
    energy = _number(_cell(row, *_ENERGY_COLUMNS))
    if not formula or energy is None or energy <= 0:
        return None
    confidence = _number(_cell(row, "confidence"))
    structure = _cell(row, "structure")
    paper_id = _cell(row, "paper_id") or "unknown paper"
    about = papers.get(paper_id, {})
    key, elements = material_key(formula, _cell(row, "composition"))
    return Measurement(
        material=formula, material_key=key, elements=elements, energy_eV=energy,
        reported_as=_cell(row, "reported_as") or "activation energy",
        structure=structure or NOT_REPORTED, polymorph=polymorph(structure),
        temperature=_cell(row, "temperature") or NOT_REPORTED,
        pressure=_cell(row, "pressure") or NOT_REPORTED,
        data_origin=_cell(row, "data_origin") or NOT_REPORTED,
        transport_component=_cell(row, "transport_component") or NOT_REPORTED,
        attribution=_cell(row, "attribution") or NOT_REPORTED,
        confidence=_DEFAULT_CONFIDENCE if confidence is None else min(max(confidence, 0.0), 1.0),
        paper_id=paper_id, paper_key=about.get("key", paper_id),
        paper_title=about.get("title") or paper_id, doi=about.get("doi") or NOT_REPORTED,
        year=about.get("year") or NOT_REPORTED, database=database,
        extracted_from=_cell(row, "extracted_from", "source_type") or NOT_REPORTED,
        page=_cell(row, "page") or NOT_REPORTED, source=_cell(row, "source") or NOT_REPORTED,
        section=_cell(row, "section") or NOT_REPORTED, sentence=_cell(row, "sentence") or NOT_REPORTED)


def _papers(folder: Path) -> dict[str, dict[str, str]]:
    """What papers.csv says of each paper of the folder; a folder without one still ranks, its
    papers then being known by their file names only."""
    try:
        rows = _read(folder / PAPERS)
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    papers: dict[str, dict[str, str]] = {}
    for row in rows:
        paper_id = _cell(row, "paper_id", "filename")
        if not paper_id or paper_id in papers:
            continue
        given = _cell(row, "doi")
        doi = _doi(given)
        # A paper is matched across folders by a real DOI only; what the database says instead of
        # one ("no DOI printed in the paper") is still what is shown.
        papers[paper_id] = {"key": f"doi:{doi}" if doi else paper_id, "doi": doi or given,
                            "title": _cell(row, "title"), "year": _cell(row, "publication_year", "year")}
    return papers


def _unassigned(folder: Path, papers: dict[str, dict[str, str]], claimed: dict[str, str]) -> int:
    """How many activation energies the extraction found but tied to no material: they are in
    the database, they cannot be ranked, and whoever reads the ranking should know they exist."""
    try:
        rows = _read(folder / UNASSIGNED)
    except (OSError, UnicodeDecodeError, csv.Error):
        return 0
    count = 0
    for row in rows:
        paper_id = _cell(row, "paper_id")
        if "activation" in _cell(row, "property_name").casefold() \
                and papers.get(paper_id, {}).get("key", paper_id) not in claimed:
            count += 1
    return count


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _cell(row: dict[str, str], *names: str) -> str:
    """The first of the named columns the row answers; "" when it answers none (the database
    writes NONE for that)."""
    for name in names:
        text = (row.get(name) or "").strip()
        if text.casefold() not in _MISSING:
            return text
    return ""


def _number(text: str) -> float | None:
    text = text.strip().replace("−", "-")
    if "," in text and "." not in text:  # 0,25 — a decimal comma
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _doi(text: str) -> str:
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", text.strip(), flags=re.IGNORECASE).casefold()
    return doi if doi.startswith("10.") else ""


def _shown(path: Path, root: Path | None) -> str:
    """A folder as it is named in the reports: from the project, when it is inside it."""
    try:
        return str(path.resolve().relative_to(root.resolve())) if root else str(path)
    except ValueError:
        return str(path)


def describe(report: DatabaseReport) -> str:
    """One line on what a folder gave: "20 values · 7 papers", with what was left aside."""
    if report.problem:
        return report.problem
    if not report.rows:
        return "holds no activation energy yet"
    if not report.values and report.already_read == report.rows:
        return f"nothing new: its {_count(report.rows, 'value')} are of papers already read from another folder"
    parts = [f"{_count(report.values, 'value')} · {_count(report.papers, 'paper')}"]
    if report.already_read:
        parts.append(f"{_count(report.already_read, 'value')} of papers already read from another folder")
    if report.repeated:
        parts.append(f"{_count(report.repeated, 'repeated value')} counted once")
    if report.unreadable:
        parts.append(f"{_count(report.unreadable, 'row')} without a material or a usable energy")
    return " · ".join(parts)


def _count(number: int, noun: str, plural: str = "") -> str:
    return f"{number} {noun if number == 1 else plural or noun + 's'}"


def unassigned_note(reports: Iterable[DatabaseReport]) -> str:
    """What to say of the activation energies that could not take part, if there are any."""
    count = sum(report.unassigned for report in reports)
    if not count:
        return ""
    return (f"{_count(count, 'activation energy', 'activation energies')} of the database "
            f"{'is' if count == 1 else 'are'} tied to no material and cannot be ranked (see {UNASSIGNED}).")
