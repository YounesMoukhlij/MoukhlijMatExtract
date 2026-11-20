# Evaluation/gold.py
"""mme-eval gold: the annotated papers as a public gold-standard dataset, for others to score their own tools on.

Written to Evaluation/gold_standard/<name>/:
  - gold.csv              every reference value, one per row: what a person found in the paper (correct and partly
                          correct extractions, corrected; values the program missed). The sentence is kept only for
                          papers whose licence allows sharing (CC BY …), as mme-release does
  - papers.csv            the papers annotated: DOI, title, year, licence, how many reference values, annotator
  - annotation_guide.md   how the values were judged: the evaluation protocol and the workbook's Guide sheet
  - agreement.json        Cohen's kappa and the F1 of two annotators (when a second workbook is given)
  - README.md             the datasheet: what, how, by whom, the columns, the licence, how to cite and to use it
  - .zenodo.json          the deposit's metadata for Zenodo (upload the folder; the form is filled from it)
  - SHA256SUMS            a checksum of every file

The annotations are released under CC BY 4.0: values and bibliographic data are facts, the sentences are quoted only
from openly licensed papers."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from LocalExtraction.about import AUTHOR, NAME as PROGRAM, REPOSITORY, version

from .about import DEFAULT_SOURCES, PROJECT_ROOT, PROPERTIES
from .score import AnnotationError, agreement, read_annotation

LICENSE = "CC-BY-4.0"
GOLD_COLUMNS = ("paper_id", "doi", "property", "material", "value", "unit", "component", "origin", "kind", "page",
                "sentence")
PAPER_COLUMNS = ("paper_id", "doi", "title", "year", "license", "reference_values", "annotator")
_SOURCE_DIR = Path(__file__).resolve().parents[1]


def _text(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


def database_folders(annotation, extra: Sequence[Path] = ()) -> List[Path]:
    """The databases the workbook's papers came from (their licences are in papers.csv)."""
    folders = [Path(p) for p in extra] + list(DEFAULT_SOURCES)
    for name in sorted(set(annotation.sources.values())):
        if name:
            folders += [PROJECT_ROOT / "WebScraping" / name, PROJECT_ROOT / "LocalExtraction" / name, Path(name)]
    seen, found = set(), []
    for folder in folders:
        key = str(folder.resolve()) if folder.exists() else ""
        if key and key not in seen and (folder / "papers.csv").exists():
            seen.add(key)
            found.append(folder)
    return found


def guide_text(workbook: Path) -> str:
    """The evaluation protocol (docs/EVALUATION_PROTOCOL.md) and the Guide sheet of the workbook."""
    parts = ["# Annotation guide", "",
             "How the reference values of this dataset were judged. Section 1 is the protocol written before the "
             "papers were drawn; section 2 is the guide the annotators read in the workbook.", ""]
    for place in (_SOURCE_DIR / "docs" / "EVALUATION_PROTOCOL.md", PROJECT_ROOT / "docs" / "EVALUATION_PROTOCOL.md"):
        if place.is_file():
            body = place.read_text(encoding="utf-8")
            parts += ["## 1 · Evaluation protocol", ""] + ["#" + line if line.startswith("#") else line
                                                           for line in body.splitlines()] + [""]
            break
    try:
        guide = pd.read_excel(workbook, sheet_name="Guide", header=None, dtype=str).fillna("")
    except (ValueError, KeyError, OSError):
        guide = None
    if guide is not None:
        parts += ["## 2 · The workbook's guide", ""]
        for _, row in guide.iterrows():
            cells = [c.strip() for c in row.tolist() if str(c).strip()]
            if cells:
                parts.append(" — ".join(cells) + "  ")
        parts.append("")
    return "\n".join(parts)


def _missed_pages(workbook: Path) -> Dict[Tuple[str, str, str], str]:
    try:
        missed = pd.read_excel(workbook, sheet_name="Missed", dtype=str).fillna("")
    except (ValueError, KeyError, OSError):
        return {}
    return {(r["paper_id"], r["property"], r.get("material", "")): _text(r.get("page", "")) for _, r in missed.iterrows()}


def rows(annotation, workbook: Path, licenses: Dict[str, Tuple[str, str]]) -> Tuple[List[Dict], List[Dict], int]:
    """The rows of gold.csv and papers.csv, and how many sentences were withheld."""
    from Release.release import shareable
    papers = pd.read_excel(workbook, sheet_name="Papers", dtype=str).fillna("")
    papers = papers[papers["paper_id"].isin(annotation.done)]
    values = pd.read_excel(workbook, sheet_name="Values", dtype=str).fillna("")
    page_of = {r["row_id"]: _text(r.get("page", "")) for _, r in values.iterrows() if r.get("row_id")}
    missed_pages = _missed_pages(workbook)
    doi_of = {r["paper_id"]: _text(r.get("doi", "")) for _, r in papers.iterrows()}
    withheld = 0
    gold_rows = []
    for item in sorted(annotation.gold, key=lambda i: (annotation.done.index(i.paper), i.prop, i.material, i.value)):
        sentence = item.sentence
        if sentence and not shareable(licenses.get(item.paper, ("not stated", ""))[0]):
            sentence, withheld = "", withheld + 1
        page = page_of.get(item.row_id, "") if item.row_id else missed_pages.get((item.paper, item.prop, item.material), "")
        gold_rows.append({"paper_id": item.paper, "doi": doi_of.get(item.paper, ""), "property": item.prop,
                          "material": item.material, "value": f"{item.value:.6g}", "unit": PROPERTIES[item.prop][1],
                          "component": item.component, "origin": item.origin, "kind": item.kind, "page": page,
                          "sentence": sentence})
    count = {p: sum(r["paper_id"] == p for r in gold_rows) for p in annotation.done}
    paper_rows = [{"paper_id": r["paper_id"], "doi": _text(r.get("doi", "")), "title": _text(r.get("title", "")),
                   "year": _text(r.get("year", "")), "license": licenses.get(r["paper_id"], ("not stated", ""))[0],
                   "reference_values": count.get(r["paper_id"], 0), "annotator": _text(r.get("annotator", ""))}
                  for _, r in papers.iterrows()]
    return gold_rows, paper_rows, withheld


def creators() -> List[Dict[str, str]]:
    """The authors of CITATION.cff, as Zenodo wants them."""
    path = _SOURCE_DIR / "CITATION.cff"
    try:
        import yaml
        authors = yaml.safe_load(path.read_text(encoding="utf-8")).get("authors") or []
    except Exception:
        authors = []
    found = []
    for a in authors:
        person = {"name": f"{a.get('family-names', '')}, {a.get('given-names', '')}".strip(", ")}
        if a.get("affiliation"):
            person["affiliation"] = a["affiliation"]
        if a.get("orcid"):
            person["orcid"] = str(a["orcid"]).rstrip("/").rsplit("/", 1)[-1]
        found.append(person)
    return found or [{"name": AUTHOR}]


def zenodo(name: str, papers: int, values: int, kappa: Optional[float]) -> Dict:
    agreement_text = f" Inter-annotator agreement: Cohen's kappa {kappa:.2f}." if kappa is not None else ""
    return {
        "title": f"Gold-standard ion-transport values of {papers} solid-electrolyte papers ({name})",
        "upload_type": "dataset",
        "description": (f"{values} reference values (activation energies, ionic and electronic conductivities, "
                        f"diffusion coefficients) checked by hand in {papers} papers on solid-state electrolytes, "
                        f"with the material, component and origin of each, the page and — for openly licensed papers "
                        f"— the sentence. Made to measure the accuracy of {PROGRAM} and of other text-mining tools."
                        f"{agreement_text} See README.md for the columns and annotation_guide.md for the method."),
        "creators": creators(),
        "license": LICENSE.lower(),
        "keywords": ["solid-state electrolytes", "text mining", "gold standard", "ionic conductivity",
                     "activation energy", "benchmark"],
        "related_identifiers": [{"identifier": REPOSITORY, "relation": "isSupplementTo", "resource_type": "software"}],
        "version": dt.date.today().isoformat(),
    }


def readme(name: str, papers: List[Dict], gold_rows: List[Dict], withheld: int, agreed: Optional[Dict]) -> str:
    kinds = {k: sum(r["kind"] == k for r in gold_rows) for k in ("correct", "partly", "missed")}
    props = {p: sum(r["property"] == p for r in gold_rows) for p in PROPERTIES}
    lines = [f"# Gold standard: {name}", "",
             f"{len(gold_rows)} values of ion transport found by hand in {len(papers)} papers on solid-state "
             f"electrolytes, to score text-mining tools on. Made with {PROGRAM} {version() or ''} "
             f"({REPOSITORY}) on {dt.date.today().isoformat()}.", "",
             "## What is in it", "",
             "| Property | Values |", "|---|---:|"] + [f"| {p.replace('_', ' ')} | {n} |" for p, n in props.items() if n]
    lines += ["", "How each value was found:", "",
              f"- **correct** ({kinds['correct']}): extracted by the program and judged right by the annotator;",
              f"- **partly** ({kinds['partly']}): extracted, with a field wrong; the row holds the corrected value;",
              f"- **missed** ({kinds['missed']}): in the paper, not extracted; added by the annotator.", "",
              "Extractions judged wrong are not reference values and are not in gold.csv. Recall measured on this set "
              "is therefore bounded by what the annotators found, which the protocol asks them to look for page by "
              "page (annotation_guide.md).", "",
              "## Files", "",
              "- `gold.csv`: one reference value per row.",
              "- `papers.csv`: the papers (DOI, title, year, licence, number of reference values, annotator).",
              "- `annotation_guide.md`: the protocol and the guide the annotators followed.",
              ]
    if agreed:
        lines.append("- `agreement.json`: the agreement of two annotators on the papers both judged.")
    lines += ["- `SHA256SUMS`: checksums (`shasum -a 256 -c SHA256SUMS`).", "",
              "## Columns of gold.csv", "",
              "| Column | Meaning |", "|---|---|",
              "| paper_id | the paper (the key of papers.csv) |",
              "| doi | its DOI, when it has one |",
              "| property | activation_energy, ionic_conductivity, electronic_conductivity or diffusion_coefficient |",
              "| material | the formula of the sample the value belongs to, as written in the paper |",
              "| value | the value in the unit of the next column (converted from the paper's) |",
              "| unit | eV, S/cm or cm2/s |",
              "| component | bulk, grain boundary or total, when known |",
              "| origin | experimental or computed, when known |",
              "| kind | correct, partly or missed (above) |",
              "| page | the page of the PDF it is on, when known |",
              "| sentence | the sentence, for openly licensed papers only |", "",
              "## Matching a tool's output", "",
              "A value is matched when it is the same property of the same paper, within 1 % (or 0.002 eV) for "
              "activation energies and within 2 % for conductivities and diffusion coefficients; at the record level "
              "the material must agree as well. `mme-eval benchmark --tool NAME=your.csv` does this against the "
              "workbook it was made from.", ""]
    if agreed:
        kappa = agreed.get("kappa")
        lines += ["## Agreement", "",
                  f"Two annotators judged {agreed.get('papers', 0)} papers each: Cohen's kappa "
                  f"{'–' if kappa is None else f'{kappa:.2f}'} on {agreed.get('rows', 0)} extracted values; F1 of one "
                  f"reference set against the other {agreed.get('record_f1') or 0:.2f} (record level).", ""]
    lines += ["## Licence and copyright", "",
              f"The annotations are released under {LICENSE}. Values and bibliographic data are facts. Sentences are "
              "quoted only from papers under a licence that allows it (CC BY and similar)"
              + (f"; {withheld} sentences of other papers were left out — read them in the paper, at the page given."
                 if withheld else ".") + " The papers themselves are not included: find them by DOI.", "",
              "## Citing", "",
              f"Cite this dataset by its Zenodo DOI, and the software by its CITATION.cff ({REPOSITORY}).", ""]
    return "\n".join(lines)


def _write_csv(path: Path, columns: Sequence[str], data: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(data)


def checksums(folder: Path) -> Path:
    lines = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(folder).as_posix()}")
    out = folder / "SHA256SUMS"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def export(workbook: Path, out: Path, second: Optional[Path] = None, name: Optional[str] = None,
           sources: Sequence[Path] = ()) -> Path:
    """Writes the dataset; returns its folder. Raises AnnotationError when no paper is done."""
    workbook = Path(workbook)
    annotation = read_annotation(workbook)
    if not annotation.done:
        raise AnnotationError(f"No paper of {workbook} is marked done yet: annotate some papers first.")
    from Release.release import licenses_of
    licenses = licenses_of(database_folders(annotation, sources))
    name = name or workbook.stem
    folder = Path(out) / name
    folder.mkdir(parents=True, exist_ok=True)
    gold_rows, paper_rows, withheld = rows(annotation, workbook, licenses)
    _write_csv(folder / "gold.csv", GOLD_COLUMNS, gold_rows)
    _write_csv(folder / "papers.csv", PAPER_COLUMNS, paper_rows)
    (folder / "annotation_guide.md").write_text(guide_text(workbook), encoding="utf-8")
    agreed = None
    if second:
        result = agreement(annotation, read_annotation(Path(second)))
        agreed = {k: v for k, v in result.items() if k in ("papers", "rows", "kappa", "raw_agreement", "value_f1",
                                                           "record_f1", "confusion")}
        (folder / "agreement.json").write_text(json.dumps(agreed, indent=2, default=str), encoding="utf-8")
    elif (folder / "agreement.json").exists():
        (folder / "agreement.json").unlink()
    (folder / "README.md").write_text(readme(name, paper_rows, gold_rows, withheld, agreed), encoding="utf-8")
    (folder / ".zenodo.json").write_text(json.dumps(zenodo(name, len(paper_rows), len(gold_rows),
                                                           (agreed or {}).get("kappa")), indent=2), encoding="utf-8")
    checksums(folder)
    return folder
