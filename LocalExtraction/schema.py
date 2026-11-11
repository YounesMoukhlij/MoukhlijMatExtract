# LocalExtraction/schema.py
"""The data dictionary: what every table and every column of a MoukhlijMatExtract database holds, in
one place. It is written next to every database (data_dictionary.csv, and a sheet of database.xlsx)
and as docs/DATA_DICTIONARY.md:

    python -m LocalExtraction.schema            # rewrites docs/DATA_DICTIONARY.md

A test checks that every column the program writes is described here."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

from .exporter import COLUMNS, QUANTITY_TABLES, TABLE_NAMES

TABLES: Dict[str, str] = {
    "papers": "One row per paper: its bibliographic record, where the file came from, and what read it.",
    "materials": "Every material a paper names, with its composition, structure and ionic radii.",
    "properties": "Every value of a material, of any property (the four transport quantities too), with its context.",
    "activation_energy": "The activation energies (migration barriers, Ea, …), one numeric column in eV.",
    "ionic_conductivity": "The ionic conductivities, one numeric column in S/cm.",
    "electronic_conductivity": "The electronic conductivities, one numeric column in S/cm.",
    "diffusion_coefficient": "The diffusion coefficients, one numeric column in cm²/s.",
    "unassigned_values": "Values no material could be established for.",
    "methods": "How each study was done: DFT / AIMD / ML settings, synthesis, techniques (no material, no context).",
    "relations": "Every material ↔ value link, with the method that made it.",
    "tables": "The tables of the papers: caption, headers, rows.",
    "figures": "The figure captions and what they name.",
    "equations": "The equations of the papers, or the standard form of a law a sentence names.",
    "workflow": "The ordered steps of each study's experimental or computational workflow.",
    "summary": "One line per paper: its materials, how many values of each quantity, its highlights.",
}

# column -> (type or unit, description). A column means the same in every table it is in, unless
# PER_TABLE says otherwise.
COLUMN: Dict[str, Tuple[str, str]] = {
    "paper_id": ("text", "The paper: its PDF file name (the key that joins every table)."),
    "title": ("text", "The article's title, as the paper (else OpenAlex) states it; the file name marked "
                      "“no title found in the paper” otherwise."),
    "filename": ("text", "The PDF file name."),
    "authors": ("text", "The authors, separated by “; ”."),
    "journal": ("text", "The journal or venue."),
    "doi": ("text", "The DOI, lower case."),
    "publication_year": ("year", "The year of publication."),
    "metadata_basis": ("text", "Where the bibliographic fields come from: the PDF, its text, OpenAlex, Crossref."),
    "n_materials": ("integer", "How many materials the paper names."),
    "n_relations": ("integer", "How many material ↔ value links were made."),
    "n_references": ("integer", "How many references the paper's reference list holds."),
    "origin": ("text", "“local” for a PDF of this computer, “web” for one fetched by Web scraping."),
    "source_service": ("text", "The service the PDF came from (arXiv, PubMed Central, Unpaywall, a publisher, "
                               "“a file of this computer”)."),
    "source_url": ("URL", "Where the PDF was fetched from (file:// for a local file)."),
    "license": ("text", "The license of the copy, as the source states it (cc-by, cc-by-nc-nd, …)."),
    "retrieved_at": ("date-time", "When the copy was fetched (or the file's date)."),
    "file_sha256": ("hex", "SHA-256 of the PDF: the same file under two names is one paper."),
    "openalex_id": ("text", "The paper's OpenAlex id (W…), when found."),
    "extracted_with": ("text", "The software version and the spaCy language model that read the paper (and the "
                               "git commit, from a source checkout)."),
    "material_id": ("text", "The material within its paper (MAT_1, MAT_2, …)."),
    "raw_formula": ("text", "The material as the paper writes it."),
    "normalized_formula": ("text", "One spelling per composition: elements from the least to the most "
                                   "electronegative (Li6PS5Cl, Li10GeP2S12)."),
    "material_formula": ("text", "The material the value belongs to, in its normalized spelling."),
    "elements": ("JSON", "Element amounts of the material, e.g. {\"Li\": 6.0, \"P\": 1.0, \"S\": 5.0, \"Cl\": 1.0}."),
    "elements_basis": ("text", "How the composition is known (the formula, a known alias, a series member)."),
    "composition": ("JSON", "Element amounts of the material, elements in alphabetical order."),
    "structure": ("text", "Crystal system, structure family, polymorph, space group (cubic | garnet | Ia-3d); "
                          "else the kind of compound (thiophosphate, oxide, …)."),
    "structure_basis": ("text", "Where the structure comes from: stated, the context, known for this composition."),
    "ionic_radii": ("JSON", "Shannon ionic radius (Å) of each ion, from the composition (charge-balanced, "
                            "six-fold coordination): {\"Li+\": 0.76, …}."),
    "ionic_radii_basis": ("text", "The oxidation states and coordination assumed for ionic_radii."),
    "is_known_alias": ("boolean", "The material was named by a known abbreviation (LLZO, LGPS, …)."),
    "confidence": ("0–1", "A heuristic score of the extraction (the context of the sentence and of the "
                          "material link). Not a calibrated probability: see mme-eval for its calibration."),
    "extracted_from": ("Text | Table | Figure", "The part of the paper the value was read from (a figure: its "
                                                "caption; plotted points are not read)."),
    "page": ("integer", "The page of the PDF."),
    "section": ("text", "The section of the paper (Abstract, Results, Methods, …)."),
    "sentence": ("text", "The verbatim sentence the value was read from (the caption, for a table cell)."),
    "source": ("text", "Where it was read, in words: “Text, citing Figure 4b”, “Table 2, row: LLZO | column: Ea (eV)”."),
    "material_link": ("text", "How the value was tied to its material (apposition, proximity, table row, "
                              "paragraph topic, …)."),
    "category": ("text", "The kind of property: ELECTROCHEMICAL, STRUCTURAL, DFT, AIMD, ML, SYNTHESIS, …"),
    "property_name": ("text", "The property: Activation_Energy, Ionic_Conductivity, Lattice_Parameter, …"),
    "raw_value": ("text", "The value as the paper writes it (1.16 mS cm−1)."),
    "normalized_value": ("text", "The value in the unit of its property (0.00116 S/cm)."),
    "unit": ("text", "The unit of normalized_value."),
    "value": ("text", "The value, in the unit of the unit column."),
    "temperature": ("text", "The temperature the value holds at: kelvin (298.1 K), room temperature, or the "
                            "fitting range of an activation energy (300-700 K)."),
    "pressure": ("text", "The pressure of the measurement (0.005 GPa) or ambient pressure."),
    "data_origin": ("experimental | simulation", "Measured, or computed (DFT, AIMD/MD, NEB, ML)."),
    "attribution": ("this work | cited", "A result of the paper itself, or one it quotes from another source."),
    "transport_component": ("bulk | grain_boundary | surface | total", "Which part of the sample the transport "
                                                                       "value is for."),
    "mobile_ion": ("text", "The species that moves: Li+, Na+, K+, Ag+, Cu+, Mg2+, Zn2+, Ca2+, Al3+, H+, O2-, F-, "
                           "electron, or another element the sentence says moves (Co)."),
    "plausibility": ("text", "“in range”, or “check: …” for a value outside the range known for ion "
                             "conductors or carried by another species than a conducting ion (left out of the "
                             "ranking by default)."),
    "needs_check": ("text", "“no”, or “yes: …” with why a person should look at the value: out of range, "
                            "unusual formula, doped sample, material from another sentence, table text, low confidence. A pointer "
                            "to the values most worth checking, not a verdict (see docs/LIMITATIONS.md)."),
    "reported_as": ("text", "The paper's own word for the quantity (activation energy, Ea, migration barrier, …)."),
    "energy_kind": ("arrhenius | migration_barrier | bvse | local_hop | vtf | rotation | charge_transfer | "
                    "electron_transfer | reaction | unspecified",
                    "What kind of energy an activation energy is: the Arrhenius slope of long-range transport (impedance, "
                    "molecular dynamics), the static barrier of one hop (NEB), a bond-valence percolation barrier, local "
                    "ion motion (NMR relaxation), a VTF pseudo-activation energy, or no ion migration at all. Values of "
                    "different kinds are different quantities: compare like with like. basis says why (kind: …)."),
    "n_assumed": ("integer", "How many of the context answers (structure, temperature, pressure, origin, "
                             "component, ion) are defaults rather than read from the paper."),
    "basis": ("text", "Where each context answer comes from — stated, context, caption of Figure 3, table, "
                      "paper, known, or assumed (and why): “structure: … | temperature: … | ion: …”."),
    "extraction_method": ("text", "How the material ↔ value link was made (as material_link)."),
    "table_number": ("text", "The table's number in the paper."),
    "caption": ("text", "The caption, verbatim."),
    "caption_basis": ("text", "“stated”, or how a table printed without a caption was named (from its headers)."),
    "headers": ("JSON", "The column headers of the table."),
    "rows": ("JSON", "The rows of the table, header → cell."),
    "material_column": ("text", "The column of the table that names the materials."),
    "figure_number": ("text", "The figure's number in the paper."),
    "referenced_materials": ("text", "The materials the caption names, separated by “ | ”."),
    "referenced_properties": ("text", "The properties the caption names."),
    "referenced_tables": ("text", "The tables the caption points to."),
    "referenced_equations": ("text", "The equations the caption points to."),
    "mentioned_methods": ("text", "The techniques the caption names (XRD, EIS, NMR, …)."),
    "equation_type": ("text", "Arrhenius, Nernst-Einstein, MSD/Diffusion, Einstein Relation, NEB, Butler-Volmer, "
                              "Fick's Law, Vegard's Law, Chemical reaction, Linear fit or Expression."),
    "equation_text": ("text", "The equation as the paper writes it — or the standard form of the law a sentence "
                              "only names (equation_basis says which)."),
    "equation_basis": ("text", "“written in the paper”, or “the standard form of the … law the sentence names”."),
    "variables": ("text", "The variables of the equation, separated by “ | ”."),
    "variables_basis": ("text", "“its text”, or the usual variables of this kind of equation."),
    "context_sentence": ("text", "The sentence the equation stands in (or that names the law)."),
    "step_order": ("integer", "The step's place in the workflow."),
    "stage": ("text", "The workflow stage (Structure Retrieval, DFT Relaxation, AIMD, Arrhenius Fitting, …)."),
    "evidence_sentence": ("text", "The sentence that shows the step."),
    "materials": ("text", "The paper's materials, separated by “ | ”."),
    "n_other_properties": ("integer", "How many values of other properties the paper gave."),
    "highlights": ("text", "The lowest activation energy and the highest conductivities of the paper, with their "
                           "materials."),
}
for _prop, _table, _column, _unit in QUANTITY_TABLES:
    COLUMN[_column] = ("number, " + _unit.replace("**2", "²"),
                       f"The {_table.replace('_', ' ')} in {_unit.replace('**2', '²')}, whatever the paper's unit.")
    COLUMN[f"n_{_table}"] = ("integer", f"How many {_table.replace('_', ' ')} values the paper gave.")

PER_TABLE: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("summary", "origin"): COLUMN["origin"],
}


def describe(table: str, column: str) -> Tuple[str, str]:
    return PER_TABLE.get((table, column)) or COLUMN[column]


def rows() -> List[Dict[str, str]]:
    """The dictionary as rows: table, column, type, description."""
    out = []
    for table in TABLE_NAMES:
        for column in COLUMNS[table]:
            kind, text = describe(table, column)
            out.append({"table": table, "column": column, "type": kind, "description": text})
    return out


def missing() -> List[Tuple[str, str]]:
    """Columns the program writes that the dictionary does not describe (a test keeps this empty)."""
    return [(t, c) for t in TABLE_NAMES for c in COLUMNS[t] if (t, c) not in PER_TABLE and c not in COLUMN]


def write_csv(folder: Path) -> Path:
    import pandas as pd
    path = Path(folder) / "data_dictionary.csv"
    pd.DataFrame(rows(), columns=["table", "column", "type", "description"]).to_csv(path, index=False,
                                                                                    encoding="utf-8-sig")
    return path


def markdown() -> str:
    lines = ["# Data dictionary", "",
             "Every table and column of a MoukhlijMatExtract database (`LocalExtraction/local_output/`, "
             "`WebScraping/web_output/`). The same is written next to each database as `data_dictionary.csv` "
             "and as the `data_dictionary` sheet of `database.xlsx`.", "",
             "No cell is left empty: a value the paper does not give is answered from the context, the "
             "composition or a convention, and the `basis` columns say which (`assumed (…)` for a default).",
             "", "*Generated by `python -m LocalExtraction.schema` — edit `LocalExtraction/schema.py`, not this file.*", ""]
    for table in TABLE_NAMES:
        lines += [f"## `{table}.csv`", "", TABLES[table], "", "| Column | Type / unit | Meaning |", "|---|---|---|"]
        for column in COLUMNS[table]:
            kind, text = describe(table, column)
            escaped = text.replace("|", "\\|")  # a pipe would end the cell
            lines.append(f"| `{column}` | {kind} | {escaped} |")
        lines.append("")
    return "\n".join(lines)


DOC = Path(__file__).resolve().parent.parent / "docs" / "DATA_DICTIONARY.md"


def main() -> int:
    gaps = missing()
    if gaps:
        print("Columns without a description: " + ", ".join(f"{t}.{c}" for t, c in gaps), file=sys.stderr)
        return 1
    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text(markdown(), encoding="utf-8")
    print(f"Wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
