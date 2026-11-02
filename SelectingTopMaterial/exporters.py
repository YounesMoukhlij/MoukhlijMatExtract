# SelectingTopMaterial/exporters.py
"""Writing the ranking down: the tables one opens (CSV, a workbook) and the whole of it for a
program (JSON).

    top_materials.csv    the materials that pass, best first
    all_materials.csv    every material with its class, the rejected ones too
    values.csv           every activation energy behind them, with its own class and where it was read
    selection.xlsx       the three tables and the rule, in one workbook
    selection.json       everything, nested: each material with its values

Every cell is answered: what the database does not say is "not reported", a material with nothing
to check says "ok". A file is written beside its place and moved onto it when complete, so that an
interrupted run never leaves half a table."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import loader
from .about import NAME, VERSION
from .criteria import POLICIES
from .models import NOT_REPORTED, Measurement, RankedMaterial, Selection
from .palette import REJECTED, class_colours, ink_on

SEPARATOR = " | "  # between the several answers of one cell, as in the database


def tally(answers: Iterable[str]) -> str:
    """What several values say of one thing: the answer when they agree, otherwise each answer
    with how many give it — "simulation (2) | experimental (1)"."""
    counts = Counter(answer for answer in answers if answer != NOT_REPORTED)
    if not counts:
        return NOT_REPORTED
    if len(counts) == 1:
        return next(iter(counts))
    return SEPARATOR.join(f"{answer} ({count})" for answer, count in
                          sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def structures(values: Iterable[Measurement]) -> str:
    """Every structure label the values carry, the most frequent first."""
    counts = Counter(label.strip() for value in values if value.structure != NOT_REPORTED
                     for label in value.structure.split("|") if label.strip())
    return SEPARATOR.join(sorted(counts, key=lambda label: (-counts[label], label))) or NOT_REPORTED


def material_row(material: RankedMaterial) -> dict[str, Any]:
    """A material as one line of a table."""
    values, evidence = material.values, material.evidence
    return {
        "rank": material.rank,
        "material": material.material,
        "class": material.energy_class.name,
        "activation_energy_eV": material.energy_eV,
        "Ea_min_eV": material.energy_min_eV,
        "Ea_max_eV": material.energy_max_eV,
        "n_values": len(values),
        "n_papers": len(material.papers),
        "class_of_values": SEPARATOR.join(f"{name} {count}" for name, count in material.votes),
        "checks": SEPARATOR.join(material.checks) or "ok",
        "confidence": material.confidence,
        "structure": structures(values),
        "data_origin": tally(v.data_origin for v in values),
        "transport_component": tally(v.transport_component for v in values),
        "attribution": tally(v.attribution for v in values),
        "temperature": tally(v.temperature for v in values),
        "papers": SEPARATOR.join(dict.fromkeys(v.paper_id for v in values)),
        "articles": SEPARATOR.join(dict.fromkeys(v.paper_title for v in values)),
        "source_paper": evidence.paper_id,
        "source_title": evidence.paper_title,
        "source_page": evidence.page,
        "source_sentence": evidence.sentence,
    }


def value_row(material: RankedMaterial, value: Measurement, selection: Selection) -> dict[str, Any]:
    """One activation energy as one line of a table, under the material it counts for."""
    return {
        "rank": material.rank,
        "material": material.material,
        "material_class": material.energy_class.name,
        "activation_energy_eV": value.energy_eV,
        "value_class": selection.criteria.classify(value.energy_eV).name,
        "reported_as": value.reported_as,
        "material_formula": value.material,
        "structure": value.structure,
        "temperature": value.temperature,
        "pressure": value.pressure,
        "data_origin": value.data_origin,
        "transport_component": value.transport_component,
        "attribution": value.attribution,
        "confidence": value.confidence,
        "paper_id": value.paper_id,
        "title": value.paper_title,
        "doi": value.doi,
        "year": value.year,
        "extracted_from": value.extracted_from,
        "page": value.page,
        "source": value.source,
        "section": value.section,
        "database": value.database,
        "sentence": value.sentence,
    }


def material_rows(materials: Iterable[RankedMaterial]) -> list[dict[str, Any]]:
    return [material_row(material) for material in materials]


def value_rows(selection: Selection) -> list[dict[str, Any]]:
    return [value_row(material, value, selection) for material in selection.materials for value in material.values]


def rule_rows(selection: Selection) -> list[tuple[str, Any]]:
    """What the ranking was made with and from, as (what, answer) lines."""
    criteria = selection.criteria
    rows: list[tuple[str, Any]] = [(c.name, f"{c.rule} — {_count(selection.count(c), 'material')}")
                                   for c in criteria.classes]
    rows += [
        ("Ea of a material", f"{selection.policy}: {POLICIES[selection.policy]}"),
        ("One material is", "one phase of a composition" if selection.by_phase else "one composition, whatever its phase"),
        ("Values taking part", f"{selection.filters.describe()} ({selection.values_used} of {selection.values_read})"),
        ("Borderline", f"within {criteria.borderline_margin:g} eV of a limit"),
        ("Low confidence", f"mean confidence of the values below {criteria.low_confidence:g}"),
        ("Criteria file", criteria.source),
    ]
    rows += [(f"Read from {report.path}", loader.describe(report)) for report in selection.databases]
    rows += [("Note", note) for note in selection.notes]
    rows += [("Written", selection.generated_at), ("Program", f"{NAME} {VERSION}")]
    return rows


def payload(selection: Selection) -> dict[str, Any]:
    """The whole ranking as plain data: what selection.json holds and what the report draws."""
    criteria = selection.criteria
    return {
        "program": {"name": NAME, "version": VERSION},
        "generated_at": selection.generated_at,
        "criteria": {
            "unit": "eV", "file": criteria.source,
            "classes": [{"name": c.name, "rule": c.rule, "from_eV": c.lower,
                         "below_eV": None if c is criteria.rejected else c.below, "accepted": c.accepted,
                         "materials": selection.count(c)} for c in criteria.classes],
            "policy": selection.policy, "policy_meaning": POLICIES[selection.policy],
            "borderline_margin_eV": criteria.borderline_margin, "low_confidence": criteria.low_confidence,
        },
        "one_material_is": "phase" if selection.by_phase else "composition",
        "filters": {"description": selection.filters.describe(), **asdict(selection.filters)},
        "databases": [{**asdict(report), "summary": loader.describe(report)} for report in selection.databases],
        "notes": list(selection.notes),
        "summary": {"materials": len(selection.materials), "top_materials": len(selection.top),
                    "rejected": len(selection.rejected), "values_read": selection.values_read,
                    "values_used": selection.values_used, "papers": selection.papers_used},
        "materials": [{**material_row(material), "accepted": material.accepted, "checks": list(material.checks),
                       "class_of_values": dict(material.votes),
                       "papers": list(dict.fromkeys(value.paper_id for value in material.values)),
                       "values": [_without(value_row(material, value, selection), "rank", "material", "material_class")
                                  for value in material.values]}
                      for material in selection.materials],
    }


def write_csv(selection: Selection, out_dir: Path, top: int | None = None) -> list[Path]:
    """The three tables as CSV files (UTF-8 with the mark Excel needs to read them right)."""
    tables = {
        "top_materials.csv": material_rows(selection.top[:top]),
        "all_materials.csv": material_rows(selection.materials),
        "values.csv": value_rows(selection),
    }
    headers = {"top_materials.csv": _MATERIAL_COLUMNS, "all_materials.csv": _MATERIAL_COLUMNS,
               "values.csv": _VALUE_COLUMNS}
    written = []
    for name, rows in tables.items():
        def save(path: Path, rows: list[dict[str, Any]] = rows, columns: Sequence[str] = headers[name]) -> None:
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        written.append(write_file(out_dir / name, save))
    return written


def write_json(selection: Selection, out_dir: Path) -> Path:
    def save(path: Path) -> None:
        path.write_text(json.dumps(payload(selection), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return write_file(out_dir / "selection.json", save)


def write_xlsx(selection: Selection, out_dir: Path, top: int | None = None) -> Path:
    """The workbook: the materials that pass, all of them, every value, and the rule. Raises
    ImportError when openpyxl is not installed (the other files do not need it)."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    criteria = selection.criteria
    colours = dict(zip((c.name for c in criteria.classes), class_colours(len(criteria.classes) - 1) + [REJECTED]))
    header_font, header_fill = Font(bold=True), PatternFill("solid", fgColor="F0EFEC")
    header_border = Border(bottom=Side(style="thin", color="C3C2B7"))

    def put(page: Any, line: int, index: int, answer: Any) -> Any:
        """A cell holding the answer as it is: a sentence of a PDF can carry characters a
        workbook refuses, or begin with "=", which a workbook would take for a formula."""
        cell = page.cell(row=line, column=index)
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", answer) if isinstance(answer, str) else answer
        if isinstance(answer, str) and answer.startswith("="):
            cell.data_type = "s"
        return cell

    def sheet(title: str, columns: Sequence[str], rows: list[dict[str, Any]], class_columns: Sequence[str]) -> None:
        page = workbook.create_sheet(title)
        for index, column in enumerate(columns, start=1):
            head = put(page, 1, index, column)
            head.font, head.fill, head.border = header_font, header_fill, header_border
            cells = [put(page, line, index, row[column]) for line, row in enumerate(rows, start=2)]
            longest = max([len(column)] + [len(str(cell.value)) for cell in cells])
            page.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 9), 60)
            for cell in cells:
                if column in class_columns:
                    colour = colours[cell.value]
                    cell.fill = PatternFill("solid", fgColor=colour[1:].upper())
                    cell.font = Font(bold=True, color=ink_on(colour)[1:].upper())
                    cell.alignment = Alignment(horizontal="center")
                elif column.endswith("_eV"):
                    cell.number_format = "0.000"
                elif column == "confidence":
                    cell.number_format = "0.00"
        page.freeze_panes = "C2"  # the header, the rank and the material stay in sight
        page.auto_filter.ref = page.dimensions

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet("Top materials", _MATERIAL_COLUMNS, material_rows(selection.top[:top]), ("class",))
    sheet("All materials", _MATERIAL_COLUMNS, material_rows(selection.materials), ("class",))
    sheet("Values", _VALUE_COLUMNS, value_rows(selection), ("material_class", "value_class"))

    about = workbook.create_sheet("Rule")
    put(about, 1, 1, "Selection of the top materials by activation energy").font = Font(bold=True, size=13)
    for line, (what, answer) in enumerate(rule_rows(selection), start=3):
        label = put(about, line, 1, what)
        put(about, line, 2, answer)
        label.font = header_font
        if what in colours:
            label.fill = PatternFill("solid", fgColor=colours[what][1:].upper())
            label.font = Font(bold=True, color=ink_on(colours[what])[1:].upper())
    about.column_dimensions["A"].width, about.column_dimensions["B"].width = 28, 110

    return write_file(out_dir / "selection.xlsx", lambda path: workbook.save(path))


def write_file(path: Path, save: Callable[[Path], None]) -> Path:
    """Writes a file whole or not at all: beside its place first, then onto it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name(f".{path.name}.part")
    try:
        save(draft)
        os.replace(draft, path)
    except PermissionError:
        raise PermissionError(f"{path} cannot be written — is it open in another program? "
                              f"Close it and run again.") from None
    finally:
        draft.unlink(missing_ok=True)
    return path


def _without(row: dict[str, Any], *columns: str) -> dict[str, Any]:
    return {column: answer for column, answer in row.items() if column not in columns}


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


_MATERIAL_COLUMNS = (
    "rank", "material", "class", "activation_energy_eV", "Ea_min_eV", "Ea_max_eV", "n_values", "n_papers",
    "class_of_values", "checks", "confidence", "structure", "data_origin", "transport_component", "attribution",
    "temperature", "papers", "articles", "source_paper", "source_title", "source_page", "source_sentence")
_VALUE_COLUMNS = (
    "rank", "material", "material_class", "activation_energy_eV", "value_class", "reported_as", "material_formula",
    "structure", "temperature", "pressure", "data_origin", "transport_component", "attribution", "confidence",
    "paper_id", "title", "doi", "year", "extracted_from", "page", "source", "section", "database", "sentence")
