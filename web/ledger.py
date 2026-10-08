# web/ledger.py
"""The ledger: one row per paper the web project has heard of, in a small SQLite file next to the
PDFs (papers/web/ledger.sqlite). It is what makes a long run resumable — a crash, a Ctrl-C or a
second run picks up where the last one stopped and never downloads a paper twice — and what answers
"where did this file come from?". The review list (candidates.csv) is a view of it that can be
edited in a spreadsheet; `apply_decisions` reads the edits back."""

import csv
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Lifecycle of a candidate: found -> scored -> (approved | rejected) -> (downloaded | closed | failed) -> extracted.
NEW, SCREENED, APPROVED, REJECTED, DOWNLOADED, CLOSED, FAILED, EXTRACTED = (
    "new", "screened", "approved", "rejected", "downloaded", "closed", "failed", "extracted")

YES, NO = "yes", "no"


@dataclass
class Candidate:
    key: str
    # What the sources told us.
    doi: str = ""
    arxiv_id: str = ""
    openalex_id: str = ""
    title: str = ""
    abstract: str = ""
    year: int = 0
    journal: str = ""
    publisher: str = ""
    authors: List[str] = field(default_factory=list)
    work_type: str = ""      # article | review | preprint | ...
    is_preprint: bool = False
    is_retracted: bool = False
    oa_status: str = ""      # gold | green | hybrid | bronze | diamond | closed
    oa_urls: List[str] = field(default_factory=list)  # direct links to legal copies, best first
    landing_url: str = ""
    license: str = ""
    cited_by: int = 0
    found_by: List[str] = field(default_factory=list)  # "openalex: <query>"
    # What screening decided.
    score: float = 0.0
    why: str = ""
    flags: List[str] = field(default_factory=list)
    access: str = ""         # open | elsevier | closed: how a copy is expected to be had
    decision: str = ""       # yes | no | "" (not screened yet)
    status: str = NEW
    # What fetching did.
    file: str = ""
    sha256: str = ""
    source_used: str = ""    # openalex | unpaywall | arxiv | elsevier
    source_url: str = ""
    retrieved_at: str = ""
    error: str = ""
    attempts: int = 0


_LIST_FIELDS = {"authors", "oa_urls", "found_by", "flags"}
# Set by screening and fetching, never by a source: a source finding the same paper again must not undo them.
_STATE_FIELDS = {"score", "why", "flags", "access", "decision", "status", "file", "sha256", "source_used",
                 "source_url", "retrieved_at", "error", "attempts"}
_COLUMNS = [f.name for f in fields(Candidate)]


def _sql_type(value: Any) -> str:
    return "REAL" if isinstance(value, float) else "INTEGER" if isinstance(value, (bool, int)) else "TEXT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_row(candidate: Candidate) -> Dict[str, Any]:
    row = {}
    for name in _COLUMNS:
        value = getattr(candidate, name)
        row[name] = json.dumps(value, ensure_ascii=False) if name in _LIST_FIELDS else \
            int(value) if isinstance(value, bool) else value
    return row


def _from_row(row: sqlite3.Row) -> Candidate:
    defaults = Candidate(key=row["key"])
    values: Dict[str, Any] = {}
    for name in _COLUMNS:
        value = row[name]
        default = getattr(defaults, name)
        if value is None:
            values[name] = default
        elif name in _LIST_FIELDS:
            values[name] = json.loads(value) if value else []
        elif isinstance(default, bool):
            values[name] = bool(value)
        else:
            values[name] = type(default)(value)
    return Candidate(**values)


def _union(old: List[str], new: Iterable[str]) -> List[str]:
    return list(dict.fromkeys([*old, *new]))


def _merge(old: Candidate, new: Candidate) -> Candidate:
    """What two sources say about one paper, combined: the first source's value wins unless it was
    empty; lists add up; the state of the paper (screening, fetching) is never touched."""
    for f in fields(Candidate):
        if f.name in _STATE_FIELDS or f.name == "key":
            continue
        current, incoming = getattr(old, f.name), getattr(new, f.name)
        if f.name in _LIST_FIELDS:
            setattr(old, f.name, _union(current, incoming))
        elif f.name == "is_retracted":
            old.is_retracted = old.is_retracted or new.is_retracted
        elif f.name == "is_preprint":
            continue  # a property of the record that was seen first
        elif not current and incoming:
            setattr(old, f.name, incoming)
    return old


class Ledger:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create()

    def _create(self) -> None:
        defaults = Candidate(key="")
        columns = ", ".join("key TEXT PRIMARY KEY" if name == "key" else
                            f"{name} {'TEXT' if name in _LIST_FIELDS else _sql_type(getattr(defaults, name))}"
                            for name in _COLUMNS)
        with self._lock, self._db:
            self._db.execute(f"CREATE TABLE IF NOT EXISTS candidates ({columns}, first_seen TEXT, updated TEXT)")
            existing = {row["name"] for row in self._db.execute("PRAGMA table_info(candidates)")}
            for name in _COLUMNS:  # a ledger written by an older version gains the new columns
                if name not in existing:
                    kind = 'TEXT' if name in _LIST_FIELDS else _sql_type(getattr(defaults, name))
                    self._db.execute(f"ALTER TABLE candidates ADD COLUMN {name} {kind}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------
    # Reading and writing candidates
    # ------------------------------------------------------------------
    def get(self, key: str) -> Optional[Candidate]:
        with self._lock:
            row = self._db.execute("SELECT * FROM candidates WHERE key = ?", (key,)).fetchone()
        return _from_row(row) if row else None

    def add(self, candidate: Candidate) -> bool:
        """Files a paper a source found; True if the ledger had not seen it before."""
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM candidates WHERE key = ?", (candidate.key,)).fetchone()
            if row is None:
                values = {**_to_row(candidate), "first_seen": _now(), "updated": _now()}
                names = ", ".join(values)
                self._db.execute(f"INSERT INTO candidates ({names}) VALUES ({', '.join('?' * len(values))})",
                                 list(values.values()))
                return True
            merged = _to_row(_merge(_from_row(row), candidate))
            self._set(candidate.key, {k: v for k, v in merged.items() if k != "key"})
            return False

    def _set(self, key: str, values: Dict[str, Any]) -> None:
        values = {**values, "updated": _now()}
        assignments = ", ".join(f"{name} = ?" for name in values)
        self._db.execute(f"UPDATE candidates SET {assignments} WHERE key = ?", [*values.values(), key])

    def update(self, key: str, **changes: Any) -> None:
        unknown = set(changes) - set(_COLUMNS)
        if unknown:
            raise KeyError(f"no such candidate field: {sorted(unknown)}")
        values = {name: json.dumps(v, ensure_ascii=False) if name in _LIST_FIELDS else int(v) if isinstance(v, bool) else v
                  for name, v in changes.items()}
        with self._lock, self._db:
            self._set(key, values)

    def all(self, *statuses: str) -> List[Candidate]:
        """Every candidate (or those in the given statuses), best score first."""
        with self._lock:
            if statuses:
                marks = ", ".join("?" * len(statuses))
                rows = self._db.execute(f"SELECT * FROM candidates WHERE status IN ({marks}) "
                                        "ORDER BY score DESC, year DESC, key", statuses).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM candidates ORDER BY score DESC, year DESC, key").fetchall()
        return [_from_row(row) for row in rows]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            return {row["status"]: row["n"] for row in
                    self._db.execute("SELECT status, COUNT(*) AS n FROM candidates GROUP BY status")}

    # ------------------------------------------------------------------
    # The review list
    # ------------------------------------------------------------------
    _REVIEW_COLUMNS = ["decision", "score", "access", "oa_status", "year", "title", "journal", "flags", "why",
                       "doi", "key", "state", "abstract"]

    def write_review(self, path: str) -> int:
        """Writes the list a person checks before anything is fetched: every candidate, those still
        waiting for a decision first. Edit the `decision` column (yes/no), save, and run the fetch
        stage — `apply_decisions` reads it back. Returns the number of rows waiting."""
        rows = self.all()
        rows.sort(key=lambda c: (c.status != SCREENED, -c.score, -c.year))
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(self._REVIEW_COLUMNS)
            for c in rows:
                writer.writerow([c.decision, f"{c.score:g}", c.access, c.oa_status, c.year or "", c.title, c.journal,
                                 " ".join(c.flags), c.why, c.doi, c.key, c.status, c.abstract])
        return sum(1 for c in rows if c.status == SCREENED)

    @staticmethod
    def _read_review(path: str) -> List[Dict[str, str]]:
        # A spreadsheet in a French or Moroccan locale saves "CSV" with ';' between the columns, and
        # older Excel versions in Windows-1252 rather than UTF-8: accept what they produce.
        raw = open(path, "rb").read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        header = text.splitlines()[0] if text.strip() else ""
        delimiter = max((",", ";", "\t"), key=header.count)
        return list(csv.DictReader(text.splitlines(), delimiter=delimiter))

    def apply_decisions(self, path: str) -> Dict[str, int]:
        """Reads the `decision` column back: yes approves a paper for fetching, no rejects it, an
        empty cell leaves it waiting. Papers already fetched are not changed."""
        outcome = {"approved": 0, "rejected": 0, "waiting": 0, "unreadable": 0}
        if not os.path.exists(path):
            return outcome
        for row in self._read_review(path):
            key = (row.get("key") or "").strip()
            candidate = self.get(key) if key else None
            if candidate is None or candidate.status not in (SCREENED, APPROVED, REJECTED):
                continue
            answer = (row.get("decision") or "").strip().lower()
            if answer in ("yes", "y", "1", "true", "ok", "x", "approve", "approved"):
                self.update(key, decision=YES, status=APPROVED)
                outcome["approved"] += 1
            elif answer in ("no", "n", "0", "false", "reject", "rejected"):
                self.update(key, decision=NO, status=REJECTED)
                outcome["rejected"] += 1
            elif answer == "":
                outcome["waiting"] += 1
            else:
                outcome["unreadable"] += 1
        return outcome
