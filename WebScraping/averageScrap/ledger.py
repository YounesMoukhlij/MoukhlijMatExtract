# WebScraping/ledger.py
"""The ledger: one row per paper the web project has heard of, in a small SQLite file next to the
PDFs (WebScraping/papers/ledger.sqlite). It is what makes a long run resumable — a crash, a Ctrl-C or a
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
# A search already run in full is not run again for this many days (new papers come out; after that,
# or with --refresh, it is run again).
SEARCH_KEPT_DAYS = 30
# What a person may write in the `decision` column of the review list.
_YES_WORDS = {"yes", "y", "1", "true", "ok", "x", "approve", "approved"}
_NO_WORDS = {"no", "n", "0", "false", "reject", "rejected"}


def read_answer(text: str) -> Optional[str]:
    """A decision cell as yes, no or "" (still waiting); None when it cannot be read."""
    answer = (text or "").strip().lower()
    return YES if answer in _YES_WORDS else NO if answer in _NO_WORDS else "" if not answer else None


@dataclass
class Candidate:
    key: str
    # What the sources told us.
    doi: str = ""
    arxiv_id: str = ""
    openalex_id: str = ""
    title: str = ""
    abstract: str = ""
    abstract_from: str = ""  # the service that gave the abstract: openalex | arxiv | crossref | openaire | ...
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
    # The services already asked for the abstract the search record lacked (each one is asked once).
    abstract_asked: List[str] = field(default_factory=list)
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


_LIST_FIELDS = {"authors", "oa_urls", "found_by", "flags", "abstract_asked"}
# Set by screening and fetching, never by a source: a source finding the same paper again must not undo them.
_STATE_FIELDS = {"abstract_asked", "score", "why", "flags", "access", "decision", "status", "file", "sha256",
                 "source_used", "source_url", "retrieved_at", "error", "attempts"}
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


def abstract_basis(candidate: Candidate) -> str:
    """Where the abstract came from, in words for the review list: the service that gave it; for a
    paper filed before this was recorded, the first source that found it (the one whose record
    was kept), marked as inferred; for a paper without one, who was asked."""
    if candidate.abstract:
        if candidate.abstract_from:
            return candidate.abstract_from
        first = (candidate.found_by[0].split(":", 1)[0].strip() if candidate.found_by else "") or "the search record"
        return f"{'openalex' if first == 'list' else first} (inferred: the first source that found it)"
    if candidate.abstract_asked:
        return f"none found (asked: {', '.join(candidate.abstract_asked)})"
    return "none in the search record (not asked yet)"


def _union(old: List[str], new: Iterable[str]) -> List[str]:
    return list(dict.fromkeys([*old, *new]))


def _merge(old: Candidate, new: Candidate) -> Candidate:
    """What two sources say about one paper, combined: the first source's value wins unless it was
    empty; lists add up; the state of the paper (screening, fetching) is never touched. An abstract
    comes with the name of the service that gave it."""
    for f in fields(Candidate):
        if f.name in _STATE_FIELDS or f.name in ("key", "abstract_from"):
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
            if f.name == "abstract":
                old.abstract_from = new.abstract_from
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
            # The searches already run in full: (source, query, years, preprints) -> how deep, and when.
            self._db.execute("CREATE TABLE IF NOT EXISTS searches (search TEXT PRIMARY KEY, depth INTEGER, at TEXT)")

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

    # ------------------------------------------------------------------
    # The searches already done
    # ------------------------------------------------------------------
    def searched(self, search: str, depth: int, max_age_days: float = SEARCH_KEPT_DAYS) -> Optional[str]:
        """When `search` was last run in full at least `depth` results deep, less than `max_age_days`
        ago ("2026-10-29"); None when it has to be run (never was, not as deep, or too long ago)."""
        with self._lock:
            row = self._db.execute("SELECT depth, at FROM searches WHERE search = ?", (search,)).fetchone()
        if row is None or (row["depth"] or 0) < depth:
            return None
        try:
            at = datetime.fromisoformat(row["at"])
        except (TypeError, ValueError):
            return None
        if (datetime.now(timezone.utc) - at).total_seconds() > max_age_days * 86400:
            return None
        return at.date().isoformat()

    def mark_searched(self, search: str, depth: int) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO searches (search, depth, at) VALUES (?, ?, ?)",
                             (search, depth, _now()))

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
                       "doi", "key", "state", "abstract", "abstract_from"]

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
                                 " ".join(c.flags), c.why, c.doi, c.key, c.status, c.abstract, abstract_basis(c)])
        return sum(1 for c in rows if c.status == SCREENED)

    @staticmethod
    def _read_review(path: str) -> List[Dict[str, str]]:
        # A spreadsheet in a French or Moroccan locale saves "CSV" with ';' between the columns, and
        # older Excel versions in Windows-1252 rather than UTF-8: accept what they produce.
        with open(path, "rb") as f:
            raw = f.read()
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
            answer = read_answer(row.get("decision") or "")
            if answer == YES:
                self.update(key, decision=YES, status=APPROVED)
                outcome["approved"] += 1
            elif answer == NO:
                self.update(key, decision=NO, status=REJECTED)
                outcome["rejected"] += 1
            elif answer == "":
                outcome["waiting"] += 1
            else:
                outcome["unreadable"] += 1
        return outcome

    def take_decisions(self, path: str) -> int:
        """Copies the decisions written in the review list into the ledger without making them
        final — no paper is approved or rejected by it. It is what lets the window show a list
        that was edited in a spreadsheet. Returns how many decisions changed."""
        changed = 0
        if not os.path.exists(path):
            return changed
        for row in self._read_review(path):
            key = (row.get("key") or "").strip()
            candidate = self.get(key) if key else None
            answer = read_answer(row.get("decision") or "")
            if candidate is not None and candidate.status in (SCREENED, APPROVED, REJECTED) \
                    and answer in (YES, NO) and answer != candidate.decision:
                self.update(key, decision=answer)
                changed += 1
        return changed
