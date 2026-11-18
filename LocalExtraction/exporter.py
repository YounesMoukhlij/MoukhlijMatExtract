# LocalExtraction/exporter.py

import csv
import html
import io
import json
import logging
import os
import re
import shutil
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from .chemistry import ChemistryEngine, common_radii
from .models import ExtractedField, Material, PaperData, TableRecord, as_written
from .provenance import extracted_with
from .review import needs_check
from .energy import energy_kind
from .scope import DOMAINS, ELECTROLYTE, material_scope
from .species import mobile_species, paper_ion, plausibility
from .study import technique

# Characters XML (and therefore .xlsx) cannot store.
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Paper-level (not tied to a single material) categorized property dicts on PaperData.
CATEGORY_FIELDS = [
    "electrochemical", "thermodynamic", "mechanical", "structural", "electronic", "thermal",
    "spectroscopy", "dft", "aimd", "ml", "synthesis", "characterization", "battery_perf", "interfaces",
]


# The values of one transport quantity each get a table of their own, every column answered for
# every row: (property, table, column of the number, its unit).
QUANTITY_TABLES = (
    ("Activation_Energy", "activation_energy", "activation_energy_eV", "eV"),
    ("Ionic_Conductivity", "ionic_conductivity", "ionic_conductivity_S_cm", "S/cm"),
    ("Electronic_Conductivity", "electronic_conductivity", "electronic_conductivity_S_cm", "S/cm"),
    ("Diffusion_Coefficient", "diffusion_coefficient", "diffusion_coefficient_cm2_s", "cm**2/s"),
)
# The tables of the relational schema, as CSV files and as sheets of the workbook.
TABLE_NAMES = ["papers", "materials", "properties", *(table for _, table, _, _ in QUANTITY_TABLES), "unassigned_values",
               "methods", "relations", "tables", "figures", "equations", "workflow", "summary"]
# What a cell of a row holds for a column the program did not write when the row was written: a row
# carried over from an earlier version, or a row added to a column someone added by hand.
NOT_RECORDED = "not recorded (written by an earlier version of MoukhlijMatExtract)"
ADDED_BY_HAND = "not filled (a column added by hand)"
# Columns a later version added that `upgrade` can work out for the rows an earlier version wrote.
UPGRADABLE = {"extracted_with", "mobile_ion", "plausibility", "needs_check", "equation_basis", "energy_kind"}
EARLIER_VERSION = "an earlier version of MoukhlijMatExtract (before the version was recorded with each paper)"
# The rebuilds of a folder whose papers have not all been brought back yet (see `archive`).
_PENDING_REBUILDS = "rebuild_pending.json"
_BASIS_ORDER = ("structure", "temperature", "pressure", "origin", "component", "ion", "kind")
# The answers counted in n_assumed: the conditions of a value. (The kind of an activation energy is a
# reading of what the value is, not a condition it holds under.)
_CONDITION_BASIS = ("structure", "temperature", "pressure", "origin", "component", "ion")
_EXCEL_CELL_LIMIT = 32767  # the characters one cell of a workbook can hold


# The quantities whose values are only those of a candidate electrolyte when the material is one (scope.py). Not
# the electronic conductivity: that of an electrode is the point.
_SCOPED = ("Activation_Energy", "Ionic_Conductivity", "Diffusion_Coefficient")


def _position(sentence: str, raw_value: str) -> Optional[int]:
    """Where a value's number stands in its sentence (its first occurrence), or None."""
    number = raw_value.split(" ", 1)[0]
    at = sentence.find(number) if number and number not in ("NONE", "nan") else -1
    return at if at >= 0 else None

_VALUE_CONTEXT = ["temperature", "pressure", "data_origin", "attribution", "n_assumed", "basis"]
_QUANTITY_COLUMNS = ["paper_id", "material_formula", "{value}", "reported_as", "extracted_from", "page", "plausibility",
                     "needs_check",
                     "composition", "structure", "ionic_radii", "temperature", "pressure", "data_origin",
                     "transport_component", "mobile_ion", "attribution", "n_assumed", "basis", "confidence", "source", "section", "sentence", "raw_value",
                     "material_id", "material_link"]
# The columns of every table, so that a table with no row yet is still written with its header.
COLUMNS: Dict[str, List[str]] = {
    "papers": ["paper_id", "filename", "title", "authors", "journal", "doi", "publication_year", "metadata_basis",
               "n_materials", "n_relations", "n_references", "origin", "source_service", "source_url", "license",
               "retrieved_at", "file_sha256", "openalex_id", "extracted_with"],
    "materials": ["paper_id", "material_id", "raw_formula", "normalized_formula", "elements", "elements_basis", "structure",
                  "structure_basis", "ionic_radii", "ionic_radii_basis", "is_known_alias", "confidence", "extracted_from",
                  "page", "section"],
    "properties": ["paper_id", "material_id", "material_formula", "composition", "structure", "ionic_radii",
                   "material_link", "category", "property_name", "raw_value", "normalized_value", "unit",
                   "extracted_from", "page", *_VALUE_CONTEXT, "confidence", "source", "section", "sentence"],
    # The activation energy says, next to the paper's word for it, what kind of energy it is (energy.py).
    **{table: [column for name in _QUANTITY_COLUMNS
               for column in ([value] if name == "{value}" else
                              [name, "energy_kind"] if name == "needs_check" and table == "activation_energy" else [name])]
       for _, table, value, _ in QUANTITY_TABLES},
    "unassigned_values": ["paper_id", "category", "property_name", "raw_value", "normalized_value", "unit",
                          "extracted_from", "page", *_VALUE_CONTEXT, "confidence", "source", "section", "sentence"],
    "methods": ["paper_id", "category", "property_name", "raw_value", "normalized_value", "unit", "extracted_from",
                "page", "confidence", "source", "section", "sentence"],
    "relations": ["paper_id", "material_id", "material_formula", "category", "property_name", "value", "unit",
                  "confidence", "extraction_method", "extracted_from", "page", "source", "section", "sentence"],
    "tables": ["paper_id", "table_number", "caption", "caption_basis", "page", "section", "headers", "rows",
               "material_column"],
    "figures": ["paper_id", "figure_number", "caption", "page", "section", "referenced_materials",
                "referenced_properties", "referenced_tables", "referenced_equations", "mentioned_methods"],
    "equations": ["paper_id", "equation_type", "equation_text", "equation_basis", "page", "section", "variables",
                  "variables_basis", "context_sentence"],
    "workflow": ["paper_id", "step_order", "stage", "evidence_sentence", "page", "section"],
    "summary": ["paper_id", "title", "publication_year", "origin", "n_materials", "materials",
                *(f"n_{table}" for _, table, _, _ in QUANTITY_TABLES), "n_other_properties", "highlights"],
}
# Every table but papers and summary (which have it already) carries the article's title right after
# its id, so a row can be read without looking the paper up.
_TITLED = [name for name in COLUMNS if name not in ("papers", "summary")]
for _name in _TITLED:
    COLUMNS[_name] = ["paper_id", "title", *COLUMNS[_name][1:]]
del _name


def article_title(title: Any, filename: Any) -> str:
    """The title of a paper as the tables give it: the one it states, else its file name (said so)."""
    text = str(title).strip() if title is not None and not (isinstance(title, float) and title != title) else ""
    if text and text not in ("NONE", NOT_RECORDED):
        return html.unescape(text)  # "Halide&#x02010;Eutectic" as some services give it → "Halide‐Eutectic"
    name = os.path.splitext(os.path.basename(str(filename or "")))[0]
    return f"{name} (file name: no title found in the paper)" if name else "no title found in the paper"


_NONE_LISTED = "none named in the caption"
# A header pdfplumber makes up for a column it found no name for: "Column", "Column_2", "(a)_3".
_MADE_UP_HEADER = re.compile(r"^(?:Column|\([a-z]\))(?:_\d+)?$")
# What the variables of an equation recognised by its name are, when its text gives none.
_USUAL_VARIABLES = {
    "Arrhenius": "σ | T | Ea | kB", "Nernst-Einstein": "σ | D | n | q | kB | T", "MSD/Diffusion": "D | MSD | t",
    "Einstein Relation": "D | MSD | t", "NEB": "E | reaction coordinate", "Butler-Volmer": "j | j0 | η | α | T",
    "Fick's Law": "J | D | c | x", "Vegard's Law": "a | x",
}


# The standard form of each law, for a sentence that names the law without writing it ("the Arrhenius
# plots show …"): the equations table then holds an equation in every row, and says which were written.
STANDARD_FORMS = {
    "Arrhenius": "σT = σ0 · exp(−Ea / (kB·T))",
    "Nernst-Einstein": "σ = n·q²·D / (kB·T)",
    "MSD/Diffusion": "D = MSD(t) / (2·d·t)   (d = 3 dimensions: D = MSD / 6t)",
    "Einstein Relation": "D = lim(t→∞) MSD(t) / (6·t)",
    "NEB": "Ea = E(saddle point) − E(initial site), along the minimum-energy path",
    "Butler-Volmer": "j = j0 · [exp(αa·F·η / (R·T)) − exp(−αc·F·η / (R·T))]",
    "Fick's Law": "J = −D · ∂c/∂x   (second law: ∂c/∂t = D · ∂²c/∂x²)",
    "Vegard's Law": "a(A1−x Bx) = (1 − x) · a(A) + x · a(B)",
}
WRITTEN = "written in the paper"
_MATH = re.compile(r"=|∝|exp\s*\(|\bln\s*\(|√|∑|∫")


def equation_columns(equation_type: str, text: str) -> Tuple[str, str]:
    """(equation_text, equation_basis): the equation as the paper writes it, or — when the text is a
    sentence that only names the law — the law's standard form, said so."""
    text = (text or "").strip()
    is_sentence = len(re.findall(r"[A-Za-z]{3,}", text)) >= 7 or not _MATH.search(text)
    if is_sentence and equation_type in STANDARD_FORMS:
        return (STANDARD_FORMS[equation_type],
                f"the standard form of the {equation_type} {'method' if equation_type == 'NEB' else 'law'} the "
                f"sentence names (the paper does not write it there)")
    return text, WRITTEN


def _equation_rows(table: pd.DataFrame) -> pd.DataFrame:
    """Rows of earlier versions, which held the naming sentence as the equation: the same as new ones."""
    if "equation_text" not in table.columns or "equation_type" not in table.columns:
        return table
    pairs = [equation_columns(kind, text) for kind, text in zip(table["equation_type"], table["equation_text"])]
    table = table.copy()
    if "context_sentence" in table.columns:
        empty = table["context_sentence"].isin(["", "NONE"])
        table.loc[empty, "context_sentence"] = table.loc[empty, "equation_text"]
    table["equation_text"] = [p[0] for p in pairs]
    table["equation_basis"] = [p[1] for p in pairs]
    return table


def _written_values(node: Any) -> Any:
    """A paper of database.json with every raw_value as the paper writes it (earlier versions stored
    "('1.65', 'eV')")."""
    if isinstance(node, dict):
        return {k: (as_written(v) if k == "raw_value" and isinstance(v, str) else _written_values(v))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_written_values(v) for v in node]
    return node

class UnreadableTable(RuntimeError):
    """A file of the database that cannot be read. It is never written over — that would lose its
    rows: the run stops before anything is written, and says which file it is."""


def _decoded(path: str) -> str:
    """A file's text: UTF-8 as this program writes it, or Windows-1252 as a spreadsheet may save it."""
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")  # every byte is a character: the text as it is


def _delimiter(text: str) -> str:
    """',' as written here; ';' or a tab when a spreadsheet in another locale saved the file."""
    header = text.split("\n", 1)[0]
    return max((",", ";", "\t"), key=header.count)


def read_table(path: str) -> pd.DataFrame:
    """A table of the database as it is on disk, every cell as the text written — also after it was
    opened and saved in a spreadsheet (';' between the columns, Windows-1252). Raises
    UnreadableTable instead of pretending it is empty."""
    try:
        text = _decoded(path)
    except OSError as error:
        raise UnreadableTable(f"{path} cannot be opened ({error}).") from error
    if not text.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(text), sep=_delimiter(text), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, ValueError) as error:
        raise UnreadableTable(
            f"{os.path.basename(path)} in {os.path.dirname(path) or '.'} cannot be read ({str(error).strip()}). Nothing "
            "was written, so none of its rows are lost. If it was edited in a spreadsheet, save it again as CSV; or move "
            "it out of the folder to start that table anew.") from error


def _header(path: str) -> List[str]:
    text = _decoded(path)
    first = text.split("\n", 1)[0].strip("\r")
    return next(csv.reader([first], delimiter=_delimiter(text)), []) if first else []


def _write_atomically(path: str, write) -> None:
    """The new file is written next to the old one and then takes its place: a crash leaves the old
    file whole, never half a table."""
    part = path + ".part"
    write(part)
    os.replace(part, path)


class StrictExporter:
    """Builds the normalized relational schema (schema section 16: papers/materials/properties/
    relations/tables/figures/equations/workflow) and writes it as linked CSV files, a multi-sheet
    Excel workbook, and nested JSON — plus the original flat one-row-per-paper summary CSV kept
    for backward-compatible quick scanning (schema rule: don't remove working functionality).

    Every table only has columns that apply to each of its rows, and every cell is answered — from
    the paper, from OpenAlex, from the composition, or with the likeliest default, the `basis`
    columns saying which:
      properties             the values of materials (a number, for a material, with its context)
      activation_energy      the activation energies among them, one column in eV whatever the paper called it
      ionic_conductivity     the ionic conductivities, in S/cm
      electronic_conductivity  the electronic conductivities, in S/cm
      diffusion_coefficient  the diffusion coefficients, in cm²/s
      unassigned_values      the values no material could be established for
      methods                how the study was done and what it mentions: DFT/AIMD/ML settings, synthesis, techniques
      summary                one line per paper: its materials and how many values of each kind
    """

    def __init__(self, output_dir: str, domain: str = ELECTROLYTE):
        """`domain` ("electrolyte", "cathode", "anode") is what the database is about: it decides which values of
        a material of another kind are flagged (scope.py)."""
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}: one of {', '.join(DOMAINS)}")
        self.output_dir = output_dir
        self.domain = domain
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def add_titles(output_dir: str) -> int:
        """Adds the `title` column to the tables of a database written before it existed, from its
        papers.csv — nothing is extracted again, and the workbook is written anew. Returns how many
        tables were given it."""
        papers_path = os.path.join(output_dir, "papers.csv")
        if not os.path.exists(papers_path) or os.path.getsize(papers_path) == 0:
            return 0
        lacking = []
        for name in _TITLED:
            path = os.path.join(output_dir, f"{name}.csv")
            try:
                header = _header(path) if os.path.exists(path) and os.path.getsize(path) else []
            except OSError:
                continue
            if header and "paper_id" in header and "title" not in header:
                lacking.append(path)
        if not lacking:
            return 0
        papers = read_table(papers_path)
        titles = {row["paper_id"]: article_title(row.get("title"), row.get("filename") or row["paper_id"])
                  for _, row in papers.iterrows()} if "paper_id" in papers else {}
        for path in lacking:
            frame = read_table(path)
            frame.insert(1, "title", [titles.get(pid) or article_title("", pid) for pid in frame["paper_id"]])
            _write_atomically(path, lambda part, frame=frame: frame.to_csv(part, index=False, encoding="utf-8-sig"))
        if os.path.exists(os.path.join(output_dir, "database.xlsx")):
            StrictExporter(output_dir).export_excel()
        logging.info(f"Added the article title to {len(lacking)} table(s) of {output_dir}.")
        return len(lacking)

    @classmethod
    def is_outdated(cls, output_dir: str) -> bool:
        """Whether the folder holds a database written by an earlier version: one of its tables is
        missing, or lacks a column this version writes. New papers cannot be added to it without
        leaving those columns open for the papers already there: it has to be rebuilt (`archive`)."""
        papers = os.path.join(output_dir, "papers.csv")
        if not os.path.exists(papers) or os.path.getsize(papers) == 0:
            return False
        try:
            cls.add_titles(output_dir)  # a missing title column is added, not a reason to rebuild
        except (OSError, UnreadableTable) as error:
            logging.warning(f"The article titles could not be added to {output_dir}: {error}")
        for name in TABLE_NAMES:
            path = os.path.join(output_dir, f"{name}.csv")
            if not os.path.exists(path):
                return True
            try:
                if set(COLUMNS[name]) - set(_header(path)):
                    return True
            except OSError:
                return False  # it is said when the table is read, not taken for an earlier version
        return False

    @classmethod
    def lacking(cls, output_dir: str) -> Optional[Dict[str, List[str]]]:
        """The columns this version writes that each table of the folder lacks; None when a table is
        missing altogether (then the database cannot be brought up to date: it has to be rebuilt)."""
        lacking: Dict[str, List[str]] = {}
        for name in TABLE_NAMES:
            path = os.path.join(output_dir, f"{name}.csv")
            if not os.path.exists(path):
                return None
            header = _header(path)
            missing = [column for column in COLUMNS[name] if column not in header]
            if missing:
                lacking[name] = missing
        return lacking

    @classmethod
    def can_upgrade(cls, output_dir: str) -> bool:
        """Whether a database of an earlier version can take new articles as it is: every column it lacks
        can be worked out for its rows from the rows themselves (`upgrade`)."""
        try:
            lacking = cls.lacking(output_dir)
        except OSError:
            return False
        return lacking is not None and all(set(columns) <= UPGRADABLE for columns in lacking.values())

    @classmethod
    def upgrade(cls, output_dir: str) -> str:
        """Brings a database of an earlier version up to date in place, so that new articles are added to
        it: the columns it lacks are filled for the rows already there — the moving ion and the
        plausibility of each value worked out from its own sentence, material and number (as this
        version does for a new value), the standard form of each equation, and, for each paper, that an
        earlier version read it. Nothing is extracted again. The files as they were are copied first into
        a dated sub-folder ("previous_<date>"). Returns that sub-folder."""
        lacking = cls.lacking(output_dir)
        if lacking is None or not all(set(columns) <= UPGRADABLE for columns in lacking.values()):
            raise ValueError(f"{output_dir} cannot be brought up to date: it has to be rebuilt")
        if not lacking:
            return ""
        kept = os.path.join(output_dir, "previous_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(kept)
        for name in os.listdir(output_dir):
            if name.endswith(".csv") or name in ("database.json", "database.xlsx"):
                shutil.copy2(os.path.join(output_dir, name), os.path.join(kept, name))
        quantity = {table: (prop, value) for prop, table, value, _ in QUANTITY_TABLES}
        frames = {name: read_table(os.path.join(output_dir, f"{name}.csv")) for name in lacking}
        # The ion each paper's values name most, as the extraction finds it for a new paper.
        sentences: Dict[str, List[str]] = {}
        for table in quantity:
            frame = frames.get(table)
            if frame is None:
                frame = read_table(os.path.join(output_dir, f"{table}.csv"))
            if {"paper_id", "sentence"} <= set(frame.columns):
                for pid, sentence in zip(frame["paper_id"], frame["sentence"]):
                    sentences.setdefault(str(pid), []).append(str(sentence))
        main_ions = {pid: paper_ion(found) for pid, found in sentences.items()}
        for name, missing in lacking.items():
            frame = frames[name]
            if name == "papers" and "extracted_with" in missing:
                frame["extracted_with"] = EARLIER_VERSION
            if name == "equations" and "equation_basis" in missing:
                frame = _equation_rows(frame)
            if name in quantity:
                prop, value = quantity[name]
                ions, notes = [], []
                for _, row in frame.iterrows():
                    formula = str(row.get("material_formula", "") or "")
                    ion, why = mobile_species(prop, str(row.get("sentence", "") or ""),
                                              "" if formula in ("NONE", "nan") else formula,
                                              *main_ions.get(str(row.get("paper_id", "")), (None, 0)))
                    ions.append(ion)
                    notes.append(why)
                if "mobile_ion" in missing:
                    frame["mobile_ion"] = ions
                    if "basis" in frame.columns:
                        frame["basis"] = [f"{basis} | ion: {why}" if str(basis) not in ("", "NONE", "nan")
                                          else f"ion: {why}" for basis, why in zip(frame["basis"], notes)]
                if "energy_kind" in missing:
                    # From each row's own words: its name for the quantity, its sentence and its origin (the
                    # paper's other sentences are not in the table, so a method named only there is not seen).
                    frame["energy_kind"] = [energy_kind(str(reported), str(sentence), str(origin), technique(str(sentence)),
                                                        None, _position(str(sentence), str(raw)))[0]
                                            for reported, sentence, origin, raw in zip(
                                                frame.get("reported_as", [""] * len(frame)), frame.get("sentence", [""] * len(frame)),
                                                frame.get("data_origin", [""] * len(frame)), frame.get("raw_value", [""] * len(frame)))]
                if "plausibility" in missing:
                    blank = [""] * len(frame)
                    notes = [material_scope(str(formula), str(composition), str(sentence), _position(str(sentence), str(raw)))
                             if prop in _SCOPED else ""
                             for formula, composition, sentence, raw in zip(
                                 frame.get("material_formula", blank), frame.get("composition", blank),
                                 frame.get("sentence", blank), frame.get("raw_value", blank))]
                    frame["plausibility"] = [plausibility(prop, number, ion, reported, note)
                                             for number, ion, reported, note in zip(frame.get(value, blank),
                                                                                    frame["mobile_ion"],
                                                                                    frame.get("reported_as", blank), notes)]
                if "needs_check" in missing:
                    frame["needs_check"] = [needs_check(row.get("plausibility", ""), row.get("confidence", ""),
                                                        row.get("material_link", ""), row.get("sentence", ""),
                                                        row.get("material_formula", "")) for _, row in frame.iterrows()]
            order = [c for c in COLUMNS[name] if c in frame.columns] + [c for c in frame.columns if c not in COLUMNS[name]]
            frame = cls._strict_none(frame[order])
            path = os.path.join(output_dir, f"{name}.csv")
            _write_atomically(path, lambda part, frame=frame: frame.to_csv(part, index=False, encoding="utf-8-sig"))
        if os.path.exists(os.path.join(output_dir, "database.xlsx")):
            cls(output_dir).export_excel()
        logging.info(f"Brought the database of {output_dir} up to date ({', '.join(sorted(lacking))}); "
                     f"the files as they were are in {kept}.")
        return kept

    @staticmethod
    def archive(output_dir: str) -> str:
        """Moves the database files of a folder into a dated sub-folder of it, so that the database
        can be rebuilt from the PDFs without anything being deleted. Returns that sub-folder ("" if
        there was nothing to move). The rebuild then brings back every paper of it — those whose
        PDF is no longer at hand too, from that sub-folder (`pending_rebuilds`, `carry_over`)."""
        files = [name for name in (os.listdir(output_dir) if os.path.isdir(output_dir) else [])
                 if name.endswith(".csv") or name in ("database.json", "database.xlsx")]
        if not files:
            return ""
        kept = os.path.join(output_dir, "previous_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(kept)
        for name in files:
            os.replace(os.path.join(output_dir, name), os.path.join(kept, name))
        if "papers.csv" in files:
            pending = StrictExporter.pending_rebuilds(output_dir)
            with open(os.path.join(output_dir, _PENDING_REBUILDS), "w", encoding="utf-8") as f:
                json.dump({"from": [os.path.basename(p) for p in pending] + [os.path.basename(kept)]}, f, indent=2)
        return kept

    @staticmethod
    def pending_rebuilds(output_dir: str) -> List[str]:
        """The archived databases (oldest first) a rebuild of this folder has not brought back yet."""
        path = os.path.join(output_dir, _PENDING_REBUILDS)
        try:
            with open(path, encoding="utf-8") as f:
                names = json.load(f).get("from", [])
        except (OSError, ValueError, AttributeError):
            return []
        return [os.path.join(output_dir, name) for name in names if os.path.isdir(os.path.join(output_dir, name))]

    @staticmethod
    def rebuild_done(output_dir: str) -> None:
        path = os.path.join(output_dir, _PENDING_REBUILDS)
        if os.path.exists(path):
            os.remove(path)

    # ------------------------------------------------------------------
    # Normalized table builders
    # ------------------------------------------------------------------
    # Every per-value table (properties, activation_energy, relations) describes a value the same
    # way, through these three column groups: what it was obtained for, under which conditions,
    # and where in the paper it sits.
    @staticmethod
    def _composition(elements: Dict[str, Any]) -> str:
        """Element -> amount as JSON with the elements in alphabetical order, so that one
        composition is one text however the paper ordered its formula."""
        return json.dumps({symbol: elements[symbol] for symbol in sorted(elements)}, ensure_ascii=False) \
            if elements else "NONE"

    @classmethod
    def composition_of(cls, m: Optional[Material], formula: str = "") -> Tuple[str, str]:
        """The composition of a material, and how it is known. A mixture whose shares the paper
        leaves open ("xLi2S-(100-x)SiS2") is given its elements with the shares open."""
        if m is not None and m.elements:
            return cls._composition(m.elements), "the formula"
        symbols = sorted(set(re.findall(r"[A-Z][a-z]?", m.normalized_formula if m else formula)))
        return json.dumps({symbol: "open" for symbol in symbols}, ensure_ascii=False), \
            "the elements of the formula (a mixture whose shares the paper leaves open)"

    @staticmethod
    def radii_of(m: Optional[Material], formula: str = "") -> Tuple[str, str]:
        """The ionic radii of a material's ions, and how they are known."""
        if m is not None and m.ionic_radii:
            return json.dumps(m.ionic_radii, ensure_ascii=False), "Shannon radii of the oxidation states that balance the formula"
        symbols = sorted(set(re.findall(r"[A-Z][a-z]?", m.normalized_formula if m else formula)))
        radii = common_radii(symbols)
        return json.dumps(radii, ensure_ascii=False), ("assumed (Shannon radii of each element's most common oxidation "
                                                       "state: no oxidation states balance the formula)")

    @classmethod
    def _material_columns(cls, f: ExtractedField, materials: Dict[str, Material]) -> Dict[str, Any]:
        """The material the value was obtained for. `structure` is the value's own — the form of
        the material it is quoted for."""
        m = materials.get(f.material_id)
        structure = f.structure
        if structure == "NONE":
            structure = m.structure if m else ChemistryEngine.compound_class({}, f.material_formula)
        return {
            "material_id": f.material_id, "material_formula": f.material_formula,
            "composition": cls.composition_of(m, f.material_formula)[0],
            "structure": structure,
            "ionic_radii": cls.radii_of(m, f.material_formula)[0],
        }

    @staticmethod
    def species_of(f: ExtractedField) -> str:
        """The species that moves; a value of an earlier run, read back without one, gets it now."""
        if f.mobile_ion != "NONE":
            return f.mobile_ion
        f.mobile_ion, f.basis["ion"] = mobile_species(f.property_name, f.source_sentence,
                                                      f.material_formula if f.material_formula != "NONE" else "")
        return f.mobile_ion

    @staticmethod
    def basis_text(f: ExtractedField) -> str:
        """Where each part of a value's context comes from, as one line:
        "structure: stated | temperature: paper (...) | pressure: assumed (...) | origin: ..."."""
        return " | ".join(f"{name}: {f.basis[name]}" for name in _BASIS_ORDER if name in f.basis) or "NONE"

    @classmethod
    def _condition_columns(cls, f: ExtractedField, component: bool = False) -> Dict[str, Any]:
        """Under which conditions the value holds. `component` (bulk / grain boundary / surface /
        total) only for the tables of a transport quantity, where it applies to every row."""
        return {
            "temperature": f.temperature, "pressure": f.pressure, "data_origin": f.data_origin,
            **({"transport_component": f.transport_component} if component else {}),
            "attribution": f.attribution,
            # How many of the answers above (and the structure) are defaults rather than read from the paper.
            "n_assumed": sum(1 for name in _CONDITION_BASIS if (component or name != "component")
                             and f.basis.get(name, "").startswith("assumed")),
            "basis": cls.basis_text(f),
        }

    @staticmethod
    def source_text(f: ExtractedField) -> str:
        """Where in the paper the value sits, in words: "Text", "Text, citing Figure 4b", "Figure 3
        caption", "Table 2, row: LLZO | column: Ea (eV)"."""
        if f.source_type == "Table":
            where = f.source_label if f.source_label != "NONE" else "Table"
            where += f", {f.source_detail}" if f.source_detail != "NONE" else ""
        elif f.source_label != "NONE":
            where = f"{f.source_label} caption"
        else:
            where = f.source_type
        return where + (f", citing {f.cited_refs}" if f.cited_refs != "NONE" else "")

    @classmethod
    def _part_columns(cls, f: ExtractedField) -> Dict[str, Any]:
        """The part of the paper a value was read from — its running text, a table, or the caption
        of a figure — and the page."""
        return {"extracted_from": f.source_type, "page": f.source_page}

    @classmethod
    def _source_columns(cls, f: ExtractedField) -> Dict[str, Any]:
        """The same, in full: also which table or figure, and the section."""
        return {**cls._part_columns(f), "source": cls.source_text(f), "section": f.source_section}

    @classmethod
    def sentence_of(cls, f: ExtractedField) -> str:
        """The sentence a value was read from; for a cell of a table, which cell it is."""
        if f.source_sentence not in ("", "NONE"):
            return f.source_sentence
        return f"read from {cls.source_text(f)}"

    @staticmethod
    def unit_of(f: ExtractedField) -> str:
        """The unit of a value; for a value that has none, what it is instead."""
        if f.unit not in ("", "NONE"):
            return f.unit
        if re.fullmatch(r"\s*[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?\s*", str(f.normalized_value)):
            return "dimensionless"
        return "no unit (a name)"

    @staticmethod
    def _listed(items: List[str]) -> str:
        return " | ".join(items) or _NONE_LISTED

    @staticmethod
    def _table_row(t: TableRecord) -> Optional[Dict[str, Any]]:
        """A table as tables.csv lists it; None for what PDF extraction took for a table but is
        none: no caption and no row with two filled cells under real headers (figure text, a
        reference list, an empty grid)."""
        filled = [row for row in t.rows if sum(1 for value in row.values() if str(value).strip()) >= 2]
        real = [h for h in t.headers if str(h).strip() and not _MADE_UP_HEADER.match(str(h).strip())]
        captioned = t.caption not in ("", "NONE")
        if not captioned and (not filled or not real or (len(t.headers) == 1 and len(str(t.headers[0])) > 60)):
            return None
        caption, basis = (t.caption, "stated") if captioned else (
            f"Table {t.table_number}: " + ", ".join(real[:6]), "made from its headers (no caption is printed with it)")
        if t.material_column not in ("", "NONE"):
            material_column = t.material_column
        else:
            material_column = "none (its rows are not materials)"
        return {"table_number": t.table_number, "caption": caption, "caption_basis": basis, "page": t.page,
                "section": t.section, "headers": json.dumps(t.headers, ensure_ascii=False),
                "rows": json.dumps(t.rows, ensure_ascii=False), "material_column": material_column}

    @classmethod
    def _summary_row(cls, paper: PaperData, counts: Dict[str, int], other: int) -> Dict[str, Any]:
        """One line on a paper: what it is, its materials, and how many values of each kind it gave."""
        meta = paper.metadata
        names = list(dict.fromkeys(m.normalized_formula for m in paper.materials))
        best = []
        for prop, table, value, unit in QUANTITY_TABLES:
            found = [c for c in getattr(paper, "electrochemical", {}).get(prop, []) if c.material_id != "NONE"]
            if found:
                pick = min if prop == "Activation_Energy" else max
                top = pick(found, key=lambda c: float(c.normalized_value.split(" ", 1)[0]))
                best.append(f"{prop.replace('_', ' ').lower()}: {top.normalized_value} ({top.material_formula})")
        return {
            "paper_id": paper.pid, "title": html.unescape(meta.get("title", ExtractedField.empty()).normalized_value),
            "publication_year": meta.get("publication_year", ExtractedField.empty()).normalized_value,
            "origin": paper.origin, "n_materials": len(names),
            "materials": " | ".join(names[:12]) + (" | …" if len(names) > 12 else "") if names else "no material named",
            **{f"n_{table}": counts.get(table, 0) for _, table, _, _ in QUANTITY_TABLES},
            "n_other_properties": other,
            "highlights": " · ".join(best) or "no transport value tied to a material",
        }

    @classmethod
    def _build_rows(cls, papers: List[PaperData], domain: str = ELECTROLYTE) -> Dict[str, List[Dict[str, Any]]]:
        tables: Dict[str, List[Dict[str, Any]]] = {name: [] for name in TABLE_NAMES}
        quantity = {prop: (table, value) for prop, table, value, _ in QUANTITY_TABLES}
        titles: Dict[str, str] = {}

        for paper in papers:
            pid = paper.pid
            materials = {m.material_id: m for m in paper.materials}
            meta = paper.metadata

            def meta_val(key: str) -> str:
                return meta.get(key, ExtractedField.empty()).normalized_value

            provenance = paper.provenance
            tables["papers"].append({
                "paper_id": pid, "filename": paper.filename,
                "title": html.unescape(meta_val("title")), "authors": meta_val("authors"), "journal": meta_val("journal"),
                "doi": meta_val("doi"), "publication_year": meta_val("publication_year"),
                "metadata_basis": meta_val("basis"),
                "n_materials": len(paper.materials), "n_relations": len(paper.relations),
                "n_references": len(paper.references),
                "origin": paper.origin,
                **{key: provenance.get(key, "NONE") for key in (
                    "source_service", "source_url", "license", "retrieved_at", "file_sha256", "openalex_id")},
                # The version and language model that read it: a database grows over many runs.
                "extracted_with": extracted_with(),
            })

            for m in paper.materials:
                elements, elements_basis = cls.composition_of(m)
                radii, radii_basis = cls.radii_of(m)
                tables["materials"].append({
                    "paper_id": pid, "material_id": m.material_id, "raw_formula": m.raw_formula,
                    "normalized_formula": m.normalized_formula,
                    "elements": elements, "elements_basis": elements_basis,
                    "structure": m.structure, "structure_basis": m.structure_basis,
                    "ionic_radii": radii, "ionic_radii_basis": radii_basis,
                    "is_known_alias": m.is_known_alias, "confidence": round(m.confidence, 3),
                    "extracted_from": m.source_type, "page": m.source_page, "section": m.source_section,
                })

            counts: Dict[str, int] = {}
            other = 0
            for cat_field in CATEGORY_FIELDS:
                for prop, cands in (getattr(paper, cat_field, {}) or {}).items():
                    for c in cands:
                        # A value, then where it was read: the part of the paper and the page come right after it.
                        value = {"raw_value": c.raw_value, "normalized_value": c.normalized_value, "unit": cls.unit_of(c),
                                 **cls._part_columns(c)}
                        where = {"confidence": round(c.confidence, 3), "source": cls.source_text(c),
                                 "section": c.source_section, "sentence": cls.sentence_of(c)}
                        named = {"paper_id": pid, "category": cat_field.upper(), "property_name": prop}
                        if not c.basis:  # a setting of the study or a bare mention: it has no context
                            tables["methods"].append({**named, **value, **where})
                            continue
                        if c.material_id == "NONE":
                            tables["unassigned_values"].append({**named, **value, **cls._condition_columns(c), **where})
                            continue
                        tables["properties"].append({
                            "paper_id": pid, **cls._material_columns(c, materials),
                            "material_link": c.material_link, "category": cat_field.upper(), "property_name": prop,
                            **value, **cls._condition_columns(c), **where,
                        })
                        if prop not in quantity:
                            other += 1
                            continue
                        # The table of its quantity. Papers describe one quantity under many names —
                        # "activation energy", "Ea", "migration barrier" ... (config.EA_TERM); "reported_as"
                        # keeps the paper's own word. One numeric column, so the table sorts and plots as it is.
                        table, number = quantity[prop]
                        columns = cls._material_columns(c, materials)
                        counts[table] = counts.get(table, 0) + 1
                        note = (material_scope(columns["material_formula"], columns["composition"], cls.sentence_of(c),
                                               _position(cls.sentence_of(c), str(c.raw_value)), domain)
                                if prop in _SCOPED else "")
                        plausible = plausibility(prop, c.normalized_value, cls.species_of(c), c.reported_as, note)
                        tables[table].append({
                            "paper_id": pid, "material_formula": columns["material_formula"],
                            number: float(c.normalized_value.split(" ", 1)[0]),
                            "plausibility": plausible,
                            "needs_check": needs_check(plausible, c.confidence, c.material_link, cls.sentence_of(c),
                                                       columns["material_formula"]),
                            "reported_as": c.reported_as if c.reported_as != "NONE" else prop.replace("_", " ").lower(),
                            **({"energy_kind": c.energy_kind if c.energy_kind != "NONE" else "unspecified"}
                               if table == "activation_energy" else {}),
                            **cls._part_columns(c),
                            "composition": columns["composition"], "structure": columns["structure"],
                            "ionic_radii": columns["ionic_radii"],
                            **cls._condition_columns(c, component=True), "mobile_ion": cls.species_of(c),
                            "confidence": round(c.confidence, 3),
                            "source": cls.source_text(c), "section": c.source_section, "sentence": cls.sentence_of(c),
                            "raw_value": c.raw_value, "material_id": c.material_id, "material_link": c.material_link,
                        })

            for r in paper.relations:
                tables["relations"].append({
                    "paper_id": pid, "material_id": r.material_id, "material_formula": r.material_formula,
                    "category": r.category, "property_name": r.property_name,
                    "value": r.property_value.normalized_value, "unit": cls.unit_of(r.property_value),
                    "confidence": round(r.confidence, 3), "extraction_method": r.extraction_method,
                    **cls._source_columns(r.property_value),
                    "sentence": r.source_sentence if r.source_sentence not in ("", "NONE") else cls.sentence_of(r.property_value),
                })

            for t in paper.tables:
                row = cls._table_row(t)
                if row is not None:
                    tables["tables"].append({"paper_id": pid, **row})

            for f in paper.figures:
                tables["figures"].append({
                    "paper_id": pid, "figure_number": f.figure_number, "caption": f.caption,
                    "page": f.page, "section": f.section,
                    "referenced_materials": cls._listed(f.referenced_materials),
                    "referenced_properties": cls._listed(f.referenced_properties),
                    "referenced_tables": cls._listed(f.referenced_tables),
                    "referenced_equations": cls._listed(f.referenced_equations),
                    "mentioned_methods": cls._listed(f.mentioned_methods),
                })

            for e in paper.equations:
                variables, basis = (" | ".join(e.variables), "its text") if e.variables else (
                    _USUAL_VARIABLES.get(e.equation_type, "none (a relation between named quantities)"),
                    "the usual variables of this equation (its text names none)")
                equation_text, equation_basis = equation_columns(e.equation_type, e.equation_text)
                tables["equations"].append({
                    "paper_id": pid, "equation_type": e.equation_type, "equation_text": equation_text,
                    "equation_basis": equation_basis, "page": e.page, "section": e.section, "variables": variables, "variables_basis": basis,
                    "context_sentence": e.context_sentence if e.context_sentence not in ("", "NONE") else e.equation_text,
                })

            for w in paper.workflow:
                tables["workflow"].append({
                    "paper_id": pid, "step_order": w.order, "stage": w.stage,
                    "evidence_sentence": w.evidence_sentence, "page": w.page, "section": w.section,
                })

            tables["summary"].append(cls._summary_row(paper, counts, other))

            titles[pid] = article_title(meta_val("title"), paper.filename)

        for name in _TITLED:
            for row in tables[name]:
                row["title"] = titles.get(row.get("paper_id"), "no title found in the paper")
        return tables

    # ------------------------------------------------------------------
    # Export: CSV (one file per table), Excel (one sheet per table), JSON (nested per paper)
    # ------------------------------------------------------------------
    def export(self, new_dataset: List[PaperData], excel: bool = True) -> None:
        """Adds `new_dataset` to the database files: its rows go after those already there, which
        are kept as they are. A paper written again (the same paper id) replaces its own earlier
        rows, so no paper is ever in a table twice. A long run calls this after every batch of
        papers with `excel=False` and builds the workbook once at the end (`export_excel`): merging
        each batch into the workbook would re-read all of it every time, and by 800 papers that
        alone takes half a minute per batch."""
        if not new_dataset:
            return
        frames = {name: self._strict_none(pd.DataFrame(rows, columns=COLUMNS[name]))
                  for name, rows in self._build_rows(new_dataset, self.domain).items()}
        self._append(frames, [self._paper_to_nested_dict(p) for p in new_dataset], {p.pid for p in new_dataset})
        if excel:
            self.export_excel()

    def carry_over(self, archived: str, paper_ids: Set[str]) -> int:
        """Adds the rows of these papers from an archived database (a `previous_<date>` folder): the
        papers a rebuild could not extract again, their PDF being no longer at hand. A column this
        version writes and the archived one did not is answered NOT_RECORDED. Returns how many
        papers were brought back."""
        frames: Dict[str, pd.DataFrame] = {}
        for name in TABLE_NAMES:
            path = os.path.join(archived, f"{name}.csv")
            old = read_table(path) if os.path.exists(path) else pd.DataFrame()
            rows = old[old["paper_id"].isin(paper_ids)] if "paper_id" in old.columns else pd.DataFrame()
            frames[name] = self._strict_none(rows.reindex(columns=COLUMNS[name], fill_value=NOT_RECORDED)
                                             if len(rows) else pd.DataFrame(columns=COLUMNS[name]))
        brought = set(frames["papers"]["paper_id"])
        records = [r for r in self._read_json(os.path.join(archived, "database.json"))
                   if (r.get("paper_id") or r.get("filename")) in brought]
        self._append(frames, records, set())
        return len(brought)

    def _append(self, frames: Dict[str, pd.DataFrame], records: List[Dict[str, Any]], replaced: Set[str]) -> None:
        """Every table and the JSON are read before anything is written: a file that cannot be read
        stops it all (UnreadableTable) and every file stays as it was. papers.csv is written last,
        so a paper counts as done only once all of its rows are in."""
        self.add_titles(self.output_dir)  # the rows already there get their title too
        merged = {name: self._merge(os.path.join(self.output_dir, f"{name}.csv"), frame, replaced)
                  for name, frame in frames.items()}
        json_path = os.path.join(self.output_dir, "database.json")
        papers = [p for p in self._read_json(json_path) if (p.get("paper_id") or p.get("filename")) not in replaced]
        # In paper order, whatever order the workers finished the papers in: the same papers give the same files,
        # byte for byte (the checksums of a release). A paper's own rows keep their order.
        papers = sorted(papers + records, key=lambda p: str(p.get("paper_id") or p.get("filename") or ""))
        _write_atomically(json_path, lambda part: self._dump_json(part, papers))
        for name in sorted(merged, key=lambda name: name == "papers"):
            frame = merged[name]
            if "paper_id" in frame.columns:
                frame = frame.sort_values("paper_id", kind="mergesort", key=lambda ids: ids.astype(str)).reset_index(drop=True)
            _write_atomically(os.path.join(self.output_dir, f"{name}.csv"),
                              lambda part, frame=frame: frame.to_csv(part, index=False, encoding="utf-8-sig"))
        from .schema import write_csv  # what every column holds, next to the tables (schema imports this module)
        write_csv(self.output_dir)

    @staticmethod
    def _read_json(path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError) as error:
            raise UnreadableTable(
                f"{path} cannot be read ({error}). Nothing was written, so none of its papers are lost; move it "
                "out of the folder to start the JSON anew (the CSV files keep every paper).") from error
        papers = existing.get("papers", []) if isinstance(existing, dict) else existing
        return [_written_values(p) for p in papers]

    @staticmethod
    def _dump_json(path: str, papers: List[Dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"papers": papers}, f, indent=2, ensure_ascii=False)

    def export_excel(self) -> None:
        """Builds the workbook from the CSV files, which hold the merged database."""
        path = os.path.join(self.output_dir, "database.xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name in TABLE_NAMES:
                file = os.path.join(self.output_dir, f"{name}.csv")
                if not os.path.exists(file):
                    continue
                try:
                    table = read_table(file)  # as written: pandas would read some texts ("NA", "null") as an empty cell
                except UnreadableTable as error:
                    logging.warning(f"The workbook has no {name} sheet: {error}")
                    continue
                table = self._strict_none(table)
                too_long = table.apply(lambda col: col.map(lambda v: isinstance(v, str) and len(v) > _EXCEL_CELL_LIMIT))
                if too_long.values.any():
                    logging.info(f"{int(too_long.values.sum())} cell(s) of the {name} sheet hold more text than a "
                                 f"workbook cell can and are cut short there; {name}.csv has them in full.")
                    table = table.apply(lambda col: col.map(
                        lambda v: v[:_EXCEL_CELL_LIMIT - 1] + "…" if isinstance(v, str) and len(v) > _EXCEL_CELL_LIMIT else v))
                table.to_excel(writer, sheet_name=name[:31], index=False)
            from .schema import rows
            pd.DataFrame(rows()).to_excel(writer, sheet_name="data_dictionary", index=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _merge(cls, path: str, new_df: pd.DataFrame, replaced: Iterable[str] = ()) -> pd.DataFrame:
        """The table on disk followed by the new rows. The rows of a paper written again are taken
        out first; a column only one side has is answered on the other (NOT_RECORDED for the rows
        written before this version added it, ADDED_BY_HAND for the new rows of a column added by
        hand, which is kept). Raises UnreadableTable rather than lose the rows on disk."""
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return new_df
        old = read_table(path)
        if not len(old.columns):
            return new_df
        replaced = set(replaced)
        if replaced and "paper_id" in old.columns:
            old = old[~old["paper_id"].isin(replaced)]
        if "raw_value" in old.columns:  # rows of earlier versions: "('1.65', 'eV')" -> "1.65 eV"
            old = old.assign(raw_value=old["raw_value"].map(as_written))
        if os.path.basename(path) == "equations.csv" and "equation_basis" not in old.columns:
            old = _equation_rows(old)
        new_df = new_df.copy()
        for column in new_df.columns:
            if column not in old.columns:
                old[column] = NOT_RECORDED
        for column in old.columns:
            if column not in new_df.columns:
                new_df[column] = ADDED_BY_HAND
        columns = list(new_df.columns)
        return cls._strict_none(pd.concat([old[columns], new_df[columns]], ignore_index=True))

    @staticmethod
    def _strict_none(df: pd.DataFrame) -> pd.DataFrame:
        """Enforces the strict-NONE policy (schema section 17): never NaN/null/empty string."""
        if df.empty:
            return df
        df = df.astype(object).where(df.notna(), "NONE").replace("", "NONE")
        # Control characters left over from PDF extraction make openpyxl raise IllegalCharacterError
        # and abort the whole workbook export, so they are stripped from every text cell.
        return df.apply(lambda col: col.map(
            lambda v: _ILLEGAL_XML_CHARS.sub("", v) if isinstance(v, str) else v))

    @classmethod
    def _paper_to_nested_dict(cls, paper: PaperData) -> Dict[str, Any]:
        def field_dict(f: ExtractedField) -> Dict[str, Any]:
            # Source, material and measurement context; like the transport keys, each is only
            # written when it was established.
            context = {
                "source_label": f.source_label, "source_detail": f.source_detail, "cited_refs": f.cited_refs,
                "material_id": f.material_id, "material_formula": f.material_formula,
                "material_link": f.material_link, "structure": f.structure,
                "temperature": f.temperature, "pressure": f.pressure,
                "data_origin": f.data_origin, "data_origin_evidence": f.data_origin_evidence,
                "reported_as": f.reported_as, "attribution": f.attribution, "mobile_ion": f.mobile_ion,
            }
            return {
                "raw_value": f.raw_value, "normalized_value": f.normalized_value, "unit": f.unit,
                "confidence": round(f.confidence, 3), **cls._part_columns(f), "section": f.source_section,
                "sentence": f.source_sentence,
                **{key: value for key, value in context.items() if value != "NONE"},
                **({"basis": f.basis} if f.basis else {}),
                **({"transport_component": f.transport_component,
                    "transport_component_evidence": f.transport_component_evidence,
                    "dominant_component": f.dominant_component}
                   if f.transport_component != "NONE" else {}),
            }

        return {
            "paper_id": paper.pid, "filename": paper.filename,
            "origin": paper.origin, "provenance": paper.provenance,
            "metadata": {k: field_dict(v) for k, v in paper.metadata.items()},
            "materials": [
                {
                    "material_id": m.material_id, "raw_formula": m.raw_formula,
                    "normalized_formula": m.normalized_formula, "elements": m.elements,
                    "structure": m.structure, "structure_basis": m.structure_basis, "ionic_radii": m.ionic_radii,
                    "is_known_alias": m.is_known_alias, "confidence": round(m.confidence, 3),
                    "page": m.source_page, "section": m.source_section,
                    "properties": [field_dict(p) for p in m.properties],
                }
                for m in paper.materials
            ],
            "paper_level_properties": {
                cat_field.upper(): {prop: [field_dict(c) for c in cands] for prop, cands in
                                     (getattr(paper, cat_field, {}) or {}).items() if cands}
                for cat_field in CATEGORY_FIELDS
            },
            "relations": [
                {
                    "material_id": r.material_id, "material_formula": r.material_formula,
                    "category": r.category, "property_name": r.property_name,
                    "value": r.property_value.normalized_value, "unit": r.property_value.unit,
                    "structure": r.property_value.structure, "temperature": r.property_value.temperature,
                    "pressure": r.property_value.pressure, "data_origin": r.property_value.data_origin,
                    "transport_component": r.property_value.transport_component,
                    "confidence": round(r.confidence, 3), "extraction_method": r.extraction_method,
                    "extracted_from": r.property_value.source_type, "page": r.source_page,
                    "source_label": r.property_value.source_label, "sentence": r.source_sentence,
                }
                for r in paper.relations
            ],
            "tables": [asdict(t) for t in paper.tables],
            "figures": [asdict(f) for f in paper.figures],
            "equations": [asdict(e) for e in paper.equations],
            "workflow": [asdict(w) for w in paper.workflow],
            "references": paper.references,
        }
