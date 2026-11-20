# Evaluation/baseline.py
"""A keyword baseline for the benchmark: what a simple pattern search finds in the same papers, so that the score of
MoukhlijMatExtract has a floor to be judged against. It reads each annotated paper's PDF, sentence by sentence, and
takes every number with the right unit in a sentence that names the property:

  - activation energy: “activation energy” or “Ea” and a value in eV, meV or kJ/mol;
  - ionic conductivity: “conductivity” and a value in S/cm or mS/cm (1.2 × 10−3, 1.2e-3 …);
  - diffusion coefficient: “diffusion” / “diffusivity” and a value in cm²/s.

The material is the first formula-like word of the sentence (Li7La3Zr2O12), or none. No component, origin or
attribution is guessed: the baseline is meant to be simple, and is described so in the benchmark's report."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

import pandas as pd

from .compare import to_database_unit
from .score import Annotation, Item

DESCRIPTION = ("Keyword baseline: a number with the property's unit in a sentence that names the property "
               "(“activation energy”/“Ea”, “conductivity”, “diffusion”); the first formula-like word of the sentence "
               "as the material; no component, origin or attribution.")

_SENTENCE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(])")
# A value with a power of ten: 1.2 × 10−3, 10−4 (no mantissa), 1.2e-3, or a plain 0.012; never the digits of an
# exponent or of a word (the look-behind).
_NOT_INSIDE = r"(?<![\w.^])(?<!10[−–-])(?<!10[−–-]\s)(?<!\^[−–-])"
_SCALED = (_NOT_INSIDE + r"(?:(?:(\d+(?:[.,]\d+)?)\s*[×x·*]\s*)?10\s*(?:\^\s*|(?=[-−–]))([-−–]?\s*\d+)"
           r"|(\d+(?:[.,]\d+)?)(?:\s*[eE]\s*([-−–+]?\d+))?)")
_NUMBER = _NOT_INSIDE + r"(\d+(?:[.,]\d+)?)"
_PATTERNS = {
    "activation_energy": (re.compile(r"activation\s+energ|\bE\s?a\b", re.IGNORECASE),
                          re.compile(_NUMBER + r"\s*(meV|eV|kJ\s*/?\s*mol(?:\s*[-−–]?\s*1|⁻¹)?)(?![a-zA-Z])")),
    "ionic_conductivity": (re.compile(r"conductivit", re.IGNORECASE),
                           re.compile(_SCALED + r"\s*(mS|S)\s*(?:/\s*cm|cm\s*[-−–]\s*1|cm⁻¹)")),
    "diffusion_coefficient": (re.compile(r"diffusi", re.IGNORECASE),
                              re.compile(_SCALED + r"\s*cm\s*(?:2|²)\s*(?:/\s*s|s\s*[-−–]\s*1|s⁻¹)")),
}
_FORMULA = re.compile(r"\b((?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}(?:\([A-Z][a-z]?\d*\)\d*)*(?:[A-Z][a-z]?\d*(?:\.\d+)?)*)\b")
_MINUS = str.maketrans({"−": "-", "–": "-"})


def paper_folders(source: str) -> List[Path]:
    """Where the PDFs of a results folder are: web_output_garnet → WebScraping/papers_garnet, local_output →
    LocalExtraction/papers (then every papers folder of the project)."""
    from .about import PROJECT_ROOT
    folders = []
    if source.startswith("web_output"):
        folders.append(PROJECT_ROOT / "WebScraping" / ("papers" + source[len("web_output"):]))
    if source.startswith("local_output"):
        folders.append(PROJECT_ROOT / "LocalExtraction" / ("papers" + source[len("local_output"):]))
    folders += sorted((PROJECT_ROOT / "WebScraping").glob("papers*")) + [PROJECT_ROOT / "LocalExtraction" / "papers"]
    return [f for f in dict.fromkeys(folders) if f.is_dir()]


def pdf_paths(workbook: Path) -> Dict[str, Path]:
    """The PDF of each paper of the workbook, where it is on this computer: its Papers sheet's pdf link (file:…,
    a hyperlink behind “open the PDF”), else the file named after the paper in the papers folder of its source."""
    try:
        import openpyxl
        sheet = openpyxl.load_workbook(workbook, read_only=False)["Papers"]
    except (OSError, KeyError, ValueError):
        return {}
    head = [c.value for c in sheet[1]]
    if "paper_id" not in head:
        return {}
    found: Dict[str, Path] = {}
    for row in sheet.iter_rows(min_row=2):
        paper = str(row[head.index("paper_id")].value or "")
        if not paper:
            continue
        link = ""
        if "pdf" in head:
            cell = row[head.index("pdf")]
            link = (cell.hyperlink.target if cell.hyperlink is not None else "") or str(cell.value or "")
        if link.startswith("file:"):
            path = Path(unquote(urlparse(link).path))
            if path.is_file():
                found[paper] = path
                continue
        source = str(row[head.index("source")].value or "") if "source" in head else ""
        for folder in paper_folders(source):
            if (folder / paper).is_file():
                found[paper] = folder / paper
                break
    return found


def _value(match: re.Match, prop: str) -> Optional[float]:
    groups = match.groups()
    if prop == "activation_energy":
        number, unit = float(groups[0].replace(",", ".")), groups[1]
    else:
        mantissa, power, plain, exponent = groups[:4]
        if power is not None:
            number = float((mantissa or "1").replace(",", ".")) * 10 ** int(power.translate(_MINUS).replace(" ", ""))
        else:
            number = float(plain.replace(",", "."))
            if exponent:
                number *= 10 ** int(exponent.translate(_MINUS))
        unit = (groups[4] + "/cm") if prop == "ionic_conductivity" else "cm2/s"
    value, _ = to_database_unit(prop, repr(number), unit.replace(" ", ""))
    return value


def material_in(sentence: str) -> str:
    for match in _FORMULA.finditer(sentence):
        word = match.group(1)
        if any(ch.isdigit() for ch in word) and len(re.findall(r"[A-Z]", word)) >= 2:
            return word
    return ""


def find_in_text(text: str, paper: str = "", title: str = "") -> List[Item]:
    """Every value the patterns find in a text (one paper)."""
    items: List[Item] = []
    for sentence in _SENTENCE.split(" ".join(text.split())):
        for prop, (names, numbers) in _PATTERNS.items():
            if not names.search(sentence):
                continue
            for match in numbers.finditer(sentence):
                value = _value(match, prop)
                if value is not None:
                    items.append(Item(paper, prop, material_in(sentence), value, title=title, sentence=sentence[:300]))
    return items


def predict(annotation: Annotation, workbook: Path) -> List[Item]:
    """The baseline's values for the papers annotated (their PDFs read where they are on this computer)."""
    import pymupdf
    pdfs = pdf_paths(workbook)
    items: List[Item] = []
    for paper in annotation.done:
        path = pdfs.get(paper)
        if path is None:
            continue
        try:
            with pymupdf.open(path) as document:
                text = " ".join(page.get_text("text") for page in document)
        except Exception:
            continue
        items.extend(find_in_text(text, paper, annotation.titles.get(paper, "")))
    return items


def missing_pdfs(annotation: Annotation, workbook: Path) -> List[str]:
    found = pdf_paths(workbook)
    return [paper for paper in annotation.done if paper not in found]


def to_csv(items: List[Item], path: Path) -> None:
    pd.DataFrame([{"paper_id": i.paper, "property": i.prop, "material": i.material, "value": f"{i.value:.6g}",
                   "unit": "", "sentence": i.sentence} for i in items],
                 columns=["paper_id", "property", "material", "value", "unit", "sentence"]).to_csv(
        path, index=False, encoding="utf-8-sig")
