# Evaluation/sheet.py
"""The annotation workbook: a random, reproducible sample of papers and every value the program
extracted from them, to be marked correct / partly / wrong by a person reading the paper — plus a sheet
for the values the program missed. The reference ("gold") values come from it; see score.py."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .about import COMPONENTS, ERROR_TYPES, ORIGINS, PROPERTIES, VERDICTS

MISSED_ROWS = 400  # blank rows of the Missed sheet, with their drop-down lists

# The columns of the Values sheet: what the program extracted, then what the annotator fills in.
SHOWN = ["row_id", "paper_no", "paper_id", "title", "property", "material", "value", "unit", "component",
         "origin", "mobile_ion", "plausibility", "temperature", "attribution", "extracted_from", "page", "confidence",
         "sentence"]
TO_FILL = ["verdict", "true_material", "true_value", "true_unit", "true_component", "true_origin",
           "error_type", "note"]
HIDDEN = ["source"]
VALUES_COLUMNS = SHOWN + TO_FILL + HIDDEN
PAPERS_COLUMNS = ["paper_no", "paper_id", "title", "doi", "year", "pdf", "values_extracted", "done", "annotator",
                  "note", "source"]
MISSED_COLUMNS = ["paper_id", "property", "material", "value", "unit", "component", "origin", "page", "sentence",
                  "note"]

GUIDE = """How to annotate — read this once
Goal: a reference set to measure how accurately MoukhlijMatExtract extracts values. Work paper by paper.

1. Papers sheet: open the paper (pdf column; else the DOI). Read the whole paper, tables and figures' captions included.
2. Values sheet: for every row of that paper, set "verdict":
   • correct — a value the paper reports for that material, and every shown field (material, value, unit, component,
     origin) is right.
   • partly — a real value of the paper for that property, but a field is wrong: write the right one in true_material,
     true_value (+ true_unit), true_component or true_origin. Leave the true_ columns of the right fields empty.
   • wrong — not a value of this property for a material of this paper (another property, another species, a cited
     value, a duplicate, …). Pick an error_type.
   For partly and wrong rows, error_type says what went wrong (it feeds the error analysis).
3. Missed sheet: add one row for every value of the four properties the paper reports that is NOT in the Values
   sheet (or is there only as a wrong row): paper_id (drop-down), property, material (formula as written), value,
   unit (eV, meV, kJ/mol; S/cm, mS/cm, S/m; cm2/s, m2/s), component and origin when the paper says.
4. Papers sheet: set done = yes when the paper is finished. Only papers marked done are scored.

What counts as a value: an activation energy, ionic conductivity, electronic conductivity or diffusion coefficient
reported for a specific material, measured or computed in this paper or quoted from another one (quoted values
count, but their attribution is "cited"). Values only in figures count only when the text or a table gives the number.
A value given for several temperatures is one value per temperature.

Double annotation (agreement): give a copy of the workbook to a second person, and compare with
mme-eval agree first.xlsx second.xlsx — journals expect agreement on at least 20 % of the papers.
Then: mme-eval score (the report lands in Evaluation/scores/)."""


@dataclass
class Database:
    folder: Path
    papers: pd.DataFrame
    values: pd.DataFrame  # every extracted value of the four properties, one row each


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except FileNotFoundError:
        return pd.DataFrame()


def read_database(folder: Path) -> Database:
    """The papers and the extracted values of one results folder (local_output, web_output, …)."""
    folder = Path(folder)
    papers = _read(folder / "papers.csv")
    frames = []
    for prop, (column, unit, _log) in PROPERTIES.items():
        table = _read(folder / f"{prop}.csv")
        if table.empty or column not in table:
            continue
        frames.append(pd.DataFrame({
            "paper_id": table["paper_id"], "title": table.get("title", ""), "property": prop,
            "material": table.get("material_formula", ""), "value": table[column], "unit": unit,
            "component": table.get("transport_component", ""), "origin": table.get("data_origin", ""),
            "mobile_ion": table.get("mobile_ion", ""), "plausibility": table.get("plausibility", ""),
            "temperature": table.get("temperature", ""), "attribution": table.get("attribution", ""),
            "extracted_from": table.get("extracted_from", ""), "page": table.get("page", ""),
            "confidence": table.get("confidence", ""), "sentence": table.get("sentence", ""),
            "source": folder.name,
        }))
    values = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SHOWN + HIDDEN)
    return Database(folder, papers, values)


def _paper_key(row) -> str:
    doi = str(row.get("doi", "") or "").strip().lower()
    if doi and doi != "none":
        return "doi:" + doi
    sha = str(row.get("file_sha256", "") or "").strip()
    return "sha:" + sha if sha and sha != "none" else "id:" + str(row.get("paper_id", ""))


def sample_papers(databases: Sequence[Database], count: int, seed: int) -> pd.DataFrame:
    """`count` papers drawn at random — with and without extracted values alike, so the recall is honest —
    the same ones for the same databases and seed. A paper in two databases is taken from the first."""
    rows, seen = [], set()
    for database in databases:
        if database.papers.empty:
            continue
        for _, row in database.papers.iterrows():
            key = _paper_key(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append({**row.to_dict(), "source": database.folder.name, "_key": key})
    rows.sort(key=lambda r: (r["source"], r["paper_id"]))
    chosen = random.Random(seed).sample(rows, min(count, len(rows))) if rows else []
    chosen.sort(key=lambda r: (r["source"], r["paper_id"]))
    return pd.DataFrame(chosen)


def _pdf_link(row) -> str:
    url = str(row.get("source_url", "") or "")
    return url if url.startswith(("file:", "http")) else ""


def build(databases: Sequence[Database], count: int, seed: int) -> Dict[str, pd.DataFrame]:
    """The sheets of the workbook, as tables."""
    papers = sample_papers(databases, count, seed)
    values_by_source = {db.folder.name: db.values for db in databases}
    paper_rows, value_rows = [], []
    for number, (_, paper) in enumerate(papers.iterrows(), start=1):
        all_values = values_by_source.get(paper["source"])
        mine = all_values[all_values["paper_id"] == paper["paper_id"]] if all_values is not None and len(all_values) else []
        paper_rows.append({
            "paper_no": number, "paper_id": paper["paper_id"], "title": paper.get("title", ""),
            "doi": paper.get("doi", "") if paper.get("doi", "") not in ("NONE",) else "",
            "year": paper.get("publication_year", ""), "pdf": _pdf_link(paper), "values_extracted": len(mine),
            "done": "", "annotator": "", "note": "", "source": paper["source"],
        })
        if len(mine):
            order = list(PROPERTIES)
            mine = mine.assign(_order=mine["property"].map(order.index)).sort_values(
                ["_order", "material"], kind="stable")
            for _, value in mine.iterrows():
                value_rows.append({**{c: value.get(c, "") for c in SHOWN if c in value}, "paper_no": number,
                                   "source": paper["source"]})
    values = pd.DataFrame(value_rows, columns=VALUES_COLUMNS)
    values["row_id"] = [f"V{n:05d}" for n in range(1, len(values) + 1)]
    values = values.astype(object).fillna("")
    return {"papers": pd.DataFrame(paper_rows, columns=PAPERS_COLUMNS), "values": values}


def fingerprint(databases: Iterable[Database]) -> str:
    digest = hashlib.sha256()
    for database in databases:
        for name in ["papers", *PROPERTIES]:
            path = database.folder / f"{name}.csv"
            if path.exists():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def write(path: Path, sheets: Dict[str, pd.DataFrame], about: Dict[str, str]) -> None:
    """The workbook: Guide, Papers, Values, Missed, About — with drop-down lists, the columns to fill in
    yellow, a link to each PDF."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    bold, header_fill = Font(bold=True), PatternFill("solid", fgColor="DCE6F1")
    fill_me = PatternFill("solid", fgColor="FFF6CC")
    book = Workbook()

    guide = book.active
    guide.title = "Guide"
    for n, line in enumerate(GUIDE.splitlines(), start=1):
        guide.cell(row=n, column=1, value=line).font = Font(bold=(n == 1), size=13 if n == 1 else 11)
    guide.column_dimensions["A"].width = 130

    def table(title: str, frame: pd.DataFrame, columns: List[str], widths: Dict[str, int], yellow: Iterable[str],
              blank_rows: int = 0):
        sheet = book.create_sheet(title)
        sheet.append(columns)
        for cell in sheet[1]:
            cell.font, cell.fill = bold, header_fill
        for record in frame[columns].itertuples(index=False):
            sheet.append([_cell(v) for v in record])
        last = max(sheet.max_row, 1 + blank_rows)
        for name in yellow:
            col = get_column_letter(columns.index(name) + 1)
            for row in range(2, last + 1):
                sheet[f"{col}{row}"].fill = fill_me
        for name, width in widths.items():
            sheet.column_dimensions[get_column_letter(columns.index(name) + 1)].width = width
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(last, 2)}"
        return sheet, last

    def choose(sheet, columns, name, options, last):
        if last < 2:
            return  # no row to choose for (no value was extracted from the papers drawn)
        col = get_column_letter(columns.index(name) + 1)
        rule = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
        rule.error, rule.errorTitle = "Pick one of the list (or leave it empty).", name
        sheet.add_data_validation(rule)
        rule.add(f"{col}2:{col}{last}")

    papers = sheets["papers"]
    sheet, last = table("Papers", papers, PAPERS_COLUMNS,
                        {"paper_id": 34, "title": 70, "doi": 28, "pdf": 14, "note": 30}, ["done", "annotator", "note"])
    choose(sheet, PAPERS_COLUMNS, "done", ["yes"], last)
    pdf_col = PAPERS_COLUMNS.index("pdf") + 1
    for row in range(2, last + 1):
        cell = sheet.cell(row=row, column=pdf_col)
        if cell.value:
            cell.hyperlink, cell.value, cell.font = cell.value, "open the PDF", Font(color="1F5F99", underline="single")
    sheet.column_dimensions[get_column_letter(PAPERS_COLUMNS.index("source") + 1)].hidden = True

    values = sheets["values"]
    sheet, last = table("Values", values, VALUES_COLUMNS,
                        {"paper_id": 26, "title": 30, "property": 20, "material": 20, "sentence": 90, "true_material": 18,
                         "error_type": 24, "note": 30}, TO_FILL)
    choose(sheet, VALUES_COLUMNS, "verdict", VERDICTS, last)
    choose(sheet, VALUES_COLUMNS, "true_component", COMPONENTS, last)
    choose(sheet, VALUES_COLUMNS, "true_origin", ORIGINS, last)
    choose(sheet, VALUES_COLUMNS, "error_type", ERROR_TYPES, last)
    sentence_col = get_column_letter(VALUES_COLUMNS.index("sentence") + 1)
    for row in range(2, last + 1):
        sheet[f"{sentence_col}{row}"].alignment = Alignment(wrap_text=False, vertical="top")
    sheet.column_dimensions[get_column_letter(VALUES_COLUMNS.index("source") + 1)].hidden = True

    missed = pd.DataFrame(columns=MISSED_COLUMNS)
    sheet, last = table("Missed", missed, MISSED_COLUMNS,
                        {"paper_id": 34, "property": 22, "material": 22, "sentence": 60, "note": 30}, MISSED_COLUMNS,
                        blank_rows=MISSED_ROWS)
    # The paper drop-down reads the Papers sheet (a literal list would pass Excel's 255-character limit).
    paper_col = get_column_letter(PAPERS_COLUMNS.index("paper_id") + 1)
    rule = DataValidation(type="list", formula1=f"=Papers!${paper_col}$2:${paper_col}${len(papers) + 1}",
                          allow_blank=True)
    sheet.add_data_validation(rule)
    rule.add(f"A2:A{last}")
    choose(sheet, MISSED_COLUMNS, "property", list(PROPERTIES), last)
    choose(sheet, MISSED_COLUMNS, "component", COMPONENTS, last)
    choose(sheet, MISSED_COLUMNS, "origin", ORIGINS, last)

    info = book.create_sheet("About")
    for key, value in about.items():
        info.append([key, value])
        info.cell(row=info.max_row, column=1).font = bold
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 110

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    book.save(temporary)
    temporary.replace(path)  # never a half-written workbook


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if isinstance(value, str):
        number = _as_number(value)
        return value if number is None else number
    return value


def _as_number(text: str) -> Optional[float]:
    """"0.31" → 0.31 so Excel shows numbers as numbers (ids and DOIs stay text)."""
    stripped = text.strip()
    if not stripped or stripped[0] == "0" and len(stripped) > 1 and stripped[1] != ".":
        return None
    try:
        number = float(stripped)
    except ValueError:
        return None
    return int(number) if number.is_integer() and "." not in stripped and "e" not in stripped.lower() else number


def _legal_only(databases: Sequence[Database], log: Optional[Path] = None) -> int:
    """Keeps in each database only the papers mme-release would publish (a legal copy recorded, or the
    authors' own PDFs); returns how many were left out."""
    from Release.release import origins_of
    origins = origins_of([db.folder for db in databases], log)
    left_out = 0
    for db in databases:
        if db.papers.empty:
            continue
        keep = db.papers["paper_id"].map(lambda paper_id: origins.get(paper_id, (False, ""))[0])
        left_out += int((~keep).sum())
        db.papers = db.papers[keep].reset_index(drop=True)
        if len(db.values):
            db.values = db.values[db.values["paper_id"].isin(set(db.papers["paper_id"]))].reset_index(drop=True)
    return left_out


def make(sources: Sequence[Path], out: Path, count: int, seed: int, version: str,
         legal_only: bool = False, log: Optional[Path] = None) -> Dict[str, int]:
    databases = [read_database(Path(s)) for s in sources if Path(s).is_dir()]
    papers_in_all = sum(len(db.papers) for db in databases)
    left_out = _legal_only(databases, log) if legal_only else 0
    sheets = build(databases, count, seed)
    about = {
        "made": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "software": f"MoukhlijMatExtract {version}".strip(),
        "databases": " ; ".join(str(db.folder) for db in databases),
        "databases fingerprint": fingerprint(databases),
        "papers in the databases": str(papers_in_all),
        "papers drawn from": ("only those with a legal copy recorded (or the authors' own): "
                              f"{papers_in_all - left_out} of {papers_in_all}") if legal_only else "every paper",
        "papers drawn": str(len(sheets["papers"])),
        "seed": str(seed),
        "values to check": str(len(sheets["values"])),
        "tolerance": "activation energy: 1 % or 0.002 eV; conductivities, diffusion: 2 % (log scale)",
    }
    write(out, sheets, about)
    return {"papers": len(sheets["papers"]), "values": len(sheets["values"]),
            "without_values": int((sheets["papers"]["values_extracted"] == 0).sum()) if len(sheets["papers"]) else 0,
            "left_out": left_out}
