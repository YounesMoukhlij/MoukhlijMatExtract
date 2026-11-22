# LocalExtraction/duplicates.py
"""One measurement, counted once: the same value of the same material found several times — repeated in one paper
(abstract, text, table), or quoted by later papers — is traced back to the row it came from.

Rows are one measurement when they have:
  - the same material (Classification's key: the composition, so Li1.3Al0.3Ti1.7(PO4)3 and Li1.3Ti1.7Al0.3(PO4)3 are
    one), the same property, transport component, origin and, for activation energies, kind of energy;
  - the same value: within 1 % (or 0.002 eV) for activation energies, within 2 % for conductivities and diffusion
    coefficients (they span decades: compared as ratios) — the tolerances of the evaluation;
  - compatible temperatures (no more than 10 K apart when both are given).

Of each measurement, the original is the row a paper reports as its own result (attribution “this work”), from the
earliest paper (publication year), then the most confident row. The others are marked:
  - "same paper":  the same paper repeats its value;
  - "cited":       another paper quotes it (attribution “cited”);
  - "possible":    another paper reports the same value as its own — perhaps a reused measurement, perhaps two
                   measurements that agree: flagged, never merged.
A measurement only cited (its original paper is not in the database) has a cited row as its representative, with
original_paper left empty.

Columns added: measurement_id, duplicate_of (the row id of the original), duplicate_kind, n_papers (how many papers
report the measurement), original_paper. A row is a duplicate to drop when its kind is "same paper" or "cited"
(is_duplicate)."""

from __future__ import annotations

import csv
import hashlib
import math
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

COLUMNS = ("measurement_id", "duplicate_of", "duplicate_kind", "n_papers", "original_paper")
DROPPED = ("same paper", "cited")
VALUE_COLUMNS = {"activation_energy": ("activation_energy_eV", False),
                 "ionic_conductivity": ("ionic_conductivity_S_cm", True),
                 "electronic_conductivity": ("electronic_conductivity_S_cm", True),
                 "diffusion_coefficient": ("diffusion_coefficient_cm2_s", True)}
LINEAR_TOLERANCE = (0.01, 0.002)   # 1 % of the value, or 0.002 eV
LOG_TOLERANCE = 0.0086             # log10 of a ratio of 2 %
TEMPERATURE_TOLERANCE = 10.0       # K
_ONE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(K|°C|C)\b")
_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)\s*(K|°C|C)\b")


def is_duplicate(row: Dict[str, object]) -> bool:
    return str(row.get("duplicate_kind", "")) in DROPPED


def _number(text: object) -> Optional[float]:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def temperature(text: str) -> Optional[Tuple[float, float]]:
    """(low, high) in K, or None: “room temperature”, “298.1 K”, “253-373 K”, “25 °C”."""
    text = (text or "").strip()
    if not text:
        return None
    if "room" in text.lower():
        return 298.15, 298.15
    match = _RANGE.search(text)
    if match:
        shift = 0.0 if match.group(3) == "K" else 273.15
        return float(match.group(1)) + shift, float(match.group(2)) + shift
    match = _ONE.search(text)
    if match:
        value = float(match.group(1)) + (0.0 if match.group(2) == "K" else 273.15)
        return value, value
    return None


def _same_temperature(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> bool:
    if a is None or b is None:
        return True
    return abs(a[0] - b[0]) <= TEMPERATURE_TOLERANCE and abs(a[1] - b[1]) <= TEMPERATURE_TOLERANCE


def same_value(a: float, b: float, log: bool) -> bool:
    if log:
        return a > 0 and b > 0 and abs(math.log10(a) - math.log10(b)) <= LOG_TOLERANCE
    return abs(a - b) <= max(LINEAR_TOLERANCE[0] * max(abs(a), abs(b)), LINEAR_TOLERANCE[1])


def material_of(row: Dict[str, object]) -> str:
    key = str(row.get("material_key", "") or "").strip()
    if key:
        return key
    formula = str(row.get("material_formula", "") or "").strip()
    try:
        from Classification.classify import composition, material_key
        return material_key(composition(str(row.get("composition", "") or "")), formula)
    except Exception:
        return "formula:" + "".join(formula.split())


def row_key(row: Dict[str, object], column: str) -> str:
    """A row's id: its paper, page, sentence, value and material (the id of the Verify tab, for any property)."""
    text = "|".join((str(row.get("paper_id", "")).strip(), str(row.get("page", "")).strip(),
                     " ".join(str(row.get("sentence", "")).split()), str(row.get(column, "")).strip(),
                     str(row.get("material_formula", "") or "").strip()))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _year(row: Dict[str, object], years: Dict[str, int]) -> int:
    for name in ("publication_year", "year"):
        value = _number(row.get(name))
        if value:
            return int(value)
    return years.get(str(row.get("paper_id", "")), 9999)


def mark(rows: Sequence[Dict[str, object]], prop: str, years: Optional[Dict[str, int]] = None) -> List[Dict[str, object]]:
    """The rows (of one property's table, or of several databases' tables of that property), each with the columns
    of COLUMNS; in the order given."""
    column, log = VALUE_COLUMNS[prop]
    years = years or {}
    out = [dict(r) for r in rows]
    buckets: Dict[Tuple[str, ...], List[int]] = {}
    for index, row in enumerate(out):
        for name in COLUMNS:
            row[name] = ""
        value = _number(row.get(column))
        if value is None:
            continue
        key = (material_of(row), str(row.get("transport_component", "")).strip(),
               str(row.get("data_origin", "")).strip(),
               str(row.get("energy_kind", "")).strip() if prop == "activation_energy" else "")
        buckets.setdefault(key, []).append(index)

    def preference(index: int):
        row = out[index]
        own = str(row.get("attribution", "")).strip() != "cited"
        confidence = _number(row.get("confidence")) or 0.0
        return (not own, _year(row, years), -confidence, index)

    counter = 0
    for indices in buckets.values():
        groups: List[Tuple[float, Optional[Tuple[float, float]], List[int]]] = []
        for index in sorted(indices, key=preference):
            row = out[index]
            value, when = _number(row.get(column)), temperature(str(row.get("temperature", "")))
            for first_value, first_when, members in groups:
                if same_value(first_value, value, log) and _same_temperature(first_when, when):
                    members.append(index)
                    break
            else:
                groups.append((value, when, [index]))
        for _, _, members in groups:
            counter += 1
            original = out[members[0]]
            own = str(original.get("attribution", "")).strip() != "cited"
            ident = row_key(original, column)
            papers = {str(out[i].get("paper_id", "")) for i in members}
            for i in members:
                row = out[i]
                row["measurement_id"] = f"m{counter:05d}"
                row["n_papers"] = len(papers)
                row["original_paper"] = str(original.get("paper_id", "")) if own else ""
                if i == members[0]:
                    continue
                row["duplicate_of"] = ident
                if str(row.get("paper_id", "")) == str(original.get("paper_id", "")):
                    row["duplicate_kind"] = "same paper"
                elif str(row.get("attribution", "")).strip() == "cited":
                    row["duplicate_kind"] = "cited"
                else:
                    row["duplicate_kind"] = "possible"
    return out


def unique(rows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    """The rows that are not duplicates (marked rows)."""
    return [r for r in rows if not is_duplicate(r)]


def years_of(folders: Iterable[Path]) -> Dict[str, int]:
    """paper_id -> publication year, from the papers.csv of each database."""
    found: Dict[str, int] = {}
    for folder in folders:
        path = Path(folder) / "papers.csv"
        if not path.is_file():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                year = _number(row.get("publication_year"))
                if year and row.get("paper_id") and row["paper_id"] not in found:
                    found[row["paper_id"]] = int(year)
    return found


def summary(marked: Sequence[Dict[str, object]]) -> Dict[str, int]:
    kinds = [str(r.get("duplicate_kind", "")) for r in marked if r.get("measurement_id")]
    return {"values": len(kinds), "measurements": len({r["measurement_id"] for r in marked if r.get("measurement_id")}),
            "same paper": kinds.count("same paper"), "cited": kinds.count("cited"), "possible": kinds.count("possible"),
            "unique values": len(kinds) - kinds.count("same paper") - kinds.count("cited")}


def report(folders: Sequence[Path], out: Optional[Path] = None) -> Dict[str, Dict[str, int]]:
    """Marks the values of these databases (together: a value quoted in one, measured in another, is found) and
    writes duplicates_<property>.csv (every value with its marks) into `out`. Returns the summary by property."""
    folders = [Path(f) for f in folders]
    years = years_of(folders)
    result: Dict[str, Dict[str, int]] = {}
    for prop in VALUE_COLUMNS:
        rows: List[Dict[str, object]] = []
        for folder in folders:
            path = folder / f"{prop}.csv"
            if path.is_file():
                with open(path, encoding="utf-8-sig", newline="") as f:
                    rows += [{**r, "database": folder.name} for r in csv.DictReader(f)]
        if not rows:
            continue
        marked = mark(rows, prop, years)
        result[prop] = summary(marked)
        if out is not None:
            Path(out).mkdir(parents=True, exist_ok=True)
            column = VALUE_COLUMNS[prop][0]
            keep = ("database", "paper_id", "material_formula", column, "temperature", "transport_component",
                    "data_origin", "attribution", "page", "sentence")
            with open(Path(out) / f"duplicates_{prop}.csv", "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["row_id", *COLUMNS, *keep], extrasaction="ignore")
                writer.writeheader()
                for row in sorted(marked, key=lambda r: (str(r.get("measurement_id")) or "~", bool(r["duplicate_of"]))):
                    writer.writerow({"row_id": row_key(row, column), **row})
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m LocalExtraction.duplicates",
                                     description="Finds the values counted more than once in results folders (repeated "
                                                 "in a paper, quoted by others) and traces each back to its original.")
    parser.add_argument("folders", nargs="+", type=Path, help="Results folders (web_output, local_output …)")
    parser.add_argument("--out", type=Path, help="Write duplicates_<property>.csv here")
    args = parser.parse_args(argv)
    for prop, counts in report(args.folders, args.out).items():
        print(f"{prop}: {counts['values']} values, {counts['measurements']} measurements — {counts['same paper']} "
              f"repeated in their paper, {counts['cited']} quoted from another, {counts['possible']} possible "
              f"(same value in two papers' own results)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
