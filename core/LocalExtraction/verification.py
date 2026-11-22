# LocalExtraction/verification.py
"""A person's check of the extracted activation energies: each value marked correct, wrong, or corrected (its
material, number, kind of energy, component, origin or attribution put right).

    ~/MoukhlijMatExtract/Verification/<database folder>.csv     one row per value checked

The checks are kept outside the database folder, so that rebuilding a database, or deleting its outputs, never
loses a person's work. A value is known by its value id — the paper, the page, the sentence, the number and the
material it was read from — which a new extraction of the same paper gives again.

The ranking reads them (SelectingTopMaterial.loader): a value marked wrong takes no part, a corrected one takes
part as corrected, and "verified values only" ranks the checked values alone."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

CORRECT, WRONG, CORRECTED = "correct", "wrong", "corrected"
VERDICTS = (CORRECT, WRONG, CORRECTED)
# What a correction may put right, as the columns of activation_energy.csv name it.
FIELDS = ("material_formula", "activation_energy_eV", "energy_kind", "transport_component", "data_origin",
          "attribution")
COLUMNS = ("value_id", "verdict", *(f"corrected_{f}" for f in FIELDS), "note", "verified_at",
           # what the value was, for a person reading the file
           "paper_id", "page", *FIELDS, "sentence")
FOLDER = "Verification"


def value_id(paper_id: str, page: str, sentence: str, energy: object, material: str = "") -> str:
    """The identity of an extracted value: its paper, page, sentence, number and material (a table gives its caption
    as the sentence of every row, so two of its materials may share the rest)."""
    try:
        number = f"{round(float(energy), 4):g}"
    except (TypeError, ValueError):
        number = str(energy).strip()
    text = "|".join((str(paper_id).strip(), str(page).strip(), " ".join(str(sentence).split()), number,
                     str(material or "").strip()))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def row_id(row: Dict[str, object]) -> str:
    """value_id of a row of activation_energy.csv."""
    return value_id(row.get("paper_id", ""), row.get("page", ""), row.get("sentence", ""),
                    row.get("activation_energy_eV", ""), row.get("material_formula", ""))


def store_path(database: Path, home: Optional[Path] = None) -> Path:
    """Where the checks of a database are kept: <home>/Verification/<name of the database folder>.csv."""
    if home is None:
        from .about import PROJECT_HOME as home
    return Path(home) / FOLDER / f"{Path(database).resolve().name}.csv"


@dataclass(frozen=True)
class Verdict:
    verdict: str
    corrections: Dict[str, str]   # field → corrected value (only those put right)
    note: str = ""
    verified_at: str = ""


class Verifications:
    """The checks of one database, read from and written to its file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._rows: Dict[str, Dict[str, str]] = {}
        if self.path.is_file():
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("value_id") and row.get("verdict") in VERDICTS:
                        self._rows[row["value_id"]] = {c: row.get(c, "") or "" for c in COLUMNS}

    @classmethod
    def of(cls, database: Path, home: Optional[Path] = None) -> "Verifications":
        return cls(store_path(database, home))

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, value: str) -> bool:
        return value in self._rows

    def get(self, value: str) -> Optional[Verdict]:
        row = self._rows.get(value)
        if row is None:
            return None
        corrections = {f: row[f"corrected_{f}"] for f in FIELDS if row.get(f"corrected_{f}", "").strip()}
        return Verdict(row["verdict"], corrections, row.get("note", ""), row.get("verified_at", ""))

    def counts(self) -> Dict[str, int]:
        return {verdict: sum(r["verdict"] == verdict for r in self._rows.values()) for verdict in VERDICTS}

    def set(self, row: Dict[str, object], verdict: str, corrections: Optional[Dict[str, str]] = None,
            note: str = "") -> str:
        """Records a check of the value of `row` (a row of activation_energy.csv); returns its value id. A correction
        that changes nothing is no correction: the value is then simply correct."""
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}: {', '.join(VERDICTS)}")
        corrections = {f: str(v).strip() for f, v in (corrections or {}).items()
                       if f in FIELDS and str(v).strip() and str(v).strip() != str(row.get(f, "")).strip()}
        if verdict == CORRECTED and not corrections:
            verdict = CORRECT
        if "activation_energy_eV" in corrections:
            float(corrections["activation_energy_eV"])  # a number, or ValueError
        key = row_id(row)
        record = {c: "" for c in COLUMNS}
        record.update({"value_id": key, "verdict": verdict, "note": note.strip(),
                       "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "paper_id": str(row.get("paper_id", "")), "page": str(row.get("page", "")),
                       "sentence": " ".join(str(row.get("sentence", "")).split())})
        for f in FIELDS:
            record[f] = str(row.get(f, ""))
            record[f"corrected_{f}"] = corrections.get(f, "") if verdict == CORRECTED else ""
        self._rows[key] = record
        self._save()
        return key

    def clear(self, value: str) -> None:
        if self._rows.pop(value, None) is not None:
            self._save()

    def digest(self) -> str:
        """A fingerprint of the checks (a ranking made with other checks is another ranking)."""
        text = "\n".join(f"{k}:{r['verdict']}:{','.join(r[f'corrected_{f}'] for f in FIELDS)}"
                         for k, r in sorted(self._rows.items()))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if self._rows else ""

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".part")
        with open(temporary, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(sorted(self._rows.values(), key=lambda r: (r["paper_id"], r["page"], r["value_id"])))
        temporary.replace(self.path)


def apply(row: Dict[str, str], verdict: Optional[Verdict]) -> Optional[Dict[str, str]]:
    """The row as the ranking takes it: None when marked wrong, corrected when corrected. A corrected material loses
    the composition read for the old one (the formula given is read instead)."""
    if verdict is None or verdict.verdict == CORRECT:
        return row
    if verdict.verdict == WRONG:
        return None
    fixed = dict(row)
    fixed.update(verdict.corrections)
    if "material_formula" in verdict.corrections:
        fixed["composition"] = ""
    return fixed


def summary(verifications: Iterable[Verifications]) -> str:
    totals = {v: 0 for v in VERDICTS}
    for store in verifications:
        for verdict, n in store.counts().items():
            totals[verdict] += n
    return (f"{sum(totals.values())} checked by hand: {totals[CORRECT]} correct, {totals[CORRECTED]} corrected, "
            f"{totals[WRONG]} wrong")
