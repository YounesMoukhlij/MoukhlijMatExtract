# WebScraping/averageScrap/watcher.py
"""The watcher of the web scraping. A website that limits requests ("too many requests", HTTP 429), is
busy (HTTP 5xx) or does not answer refuses a check that would have worked a little later: the search
of one keyword in one source, or the lookups and the download of one DOI. Such a check is not taken
for an answer ("nothing found", "no legal copy"): the watcher puts it on its watch list (kept in the
ledger, so it survives the end of the run), checks it again after a pause — 2, 5, 10 then 15 minutes
— and leaves what is still refused after the last round for the next run, which checks it first.
A search refused more than MAX_TRIES times (over every run: a service out of its quota, or gone) is given up: it
stays on the list, is not asked again for SEARCH_KEPT_DAYS days (like a search answered), then is tried once more.

It also counts what was checked, and says it at the end: how many keywords and searches, how many
DOIs, how each ended, what a later try brought, what is still waiting — for this run, and in total."""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

import requests

from LocalExtraction import runcontrol
from WebScraping.averageScrap.http import HttpError
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, EXTRACTED, FAILED, SEARCH_KEPT_DAYS, Ledger

SEARCH, DOWNLOAD = "search", "download"
ROUNDS_MINUTES = (2, 5, 10, 15)  # the pauses before each new check of what was refused, within one run
MAX_TRIES = 6                    # refusals of one check (over every run) before it is given up
_TICK = 10                       # seconds between two updates of the countdown


def _given_up(row: Dict) -> bool:
    """A search refused more than MAX_TRIES times, the last time less than SEARCH_KEPT_DAYS days ago."""
    if (row.get("tries") or 0) <= MAX_TRIES:
        return False
    try:
        last = datetime.fromisoformat(row.get("last_at") or "")
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - last).total_seconds() < SEARCH_KEPT_DAYS * 86400


def is_refusal(error: BaseException) -> bool:
    """Whether a failure is a site's "not now" (worth asking again later) rather than an answer:
    too many requests, a busy or failing server, a connection that broke or timed out."""
    if isinstance(error, HttpError):
        return error.status in (408, 425, 429) or error.status >= 500
    return isinstance(error, requests.RequestException)


def refusal_text(error: BaseException) -> str:
    if isinstance(error, HttpError):
        return {429: "too many requests (HTTP 429)", 503: "busy (HTTP 503)"}.get(error.status, f"HTTP {error.status}")
    return f"no answer ({type(error).__name__})"


@dataclass
class Tally:
    """What this run checked."""
    keywords: Set[str] = field(default_factory=set)        # keywords asked of at least one source
    keywords_done: Set[str] = field(default_factory=set)   # ... answered in full by at least one source
    searches_asked: int = 0        # keyword x source, asked (each try counts once)
    searches_answered: int = 0
    searches_refused: int = 0
    searches_later: int = 0        # answered on a later try (a check the watcher made again)
    searches_skipped: int = 0      # answered in full by an earlier run (within 30 days)
    dois: Set[str] = field(default_factory=set)            # DOIs (papers) whose download was tried
    downloaded: Set[str] = field(default_factory=set)
    no_copy: Set[str] = field(default_factory=set)
    failed: Set[str] = field(default_factory=set)
    refused: Set[str] = field(default_factory=set)         # refused at least once this run
    later: Set[str] = field(default_factory=set)           # downloaded on a later try


class Watcher:
    def __init__(self, ledger: Ledger, sleep: Callable[[float], None] = runcontrol.sleep,
                 say: Callable[[str], None] = logging.info):
        self.ledger, self.sleep, self.say = ledger, sleep, say
        self.tally = Tally()

    # ------------------------------------------------------------------
    # The watch list
    # ------------------------------------------------------------------
    def defer(self, kind: str, item: str, service: str, reason: str) -> int:
        """A refused check, to be made again; returns how many times it has been refused (all runs)."""
        return self.ledger.watch_add(kind, item, service, reason)

    def done(self, kind: str, item: str, service: Optional[str] = None) -> bool:
        """A check made (answered either way): off the list. True if it had been waiting."""
        return self.ledger.watch_remove(kind, item, service)

    def pending(self, kind: str) -> List[Dict[str, str]]:
        """What waits to be checked again (a search given up does not)."""
        return [row for row in self.ledger.watch_list(kind) if not (kind == SEARCH and _given_up(row))]

    def given_up(self, kind: str, item: str, service: str) -> bool:
        """Whether this search was refused more than MAX_TRIES times and is left alone for now."""
        row = self.ledger.watch_get(kind, item, service)
        return kind == SEARCH and row is not None and _given_up(row)

    def given_up_count(self) -> int:
        return sum(1 for row in self.ledger.watch_list(SEARCH) if _given_up(row))

    def forget(self, kind: str, keep: Callable[[Dict[str, str]], bool]) -> None:
        """Drops what no longer belongs to the job (a keyword or source taken out of it)."""
        for row in self.ledger.watch_list(kind):
            if not keep(row):
                self.ledger.watch_remove(kind, row["item"], row["service"])

    # ------------------------------------------------------------------
    # The rounds
    # ------------------------------------------------------------------
    def wait(self, minutes: float, what: str, number: int) -> None:
        """The pause before round `number`: Pause holds it, Stop ends it (StepStopped)."""
        total = len(ROUNDS_MINUTES)
        left = int(minutes * 60)
        logging.info(f"Watcher: {what} refused by a site that limits or did not answer requests — checked again in "
                     f"{minutes:g} min (round {number} of {total}). Stop leaves them for the next run.")
        while left > 0:
            self.say(f"Watcher: {what} waiting — next check in {left // 60}:{left % 60:02d} "
                     f"(round {number} of {total}). Stop leaves them for the next run.")
            step = min(_TICK, left)
            self.sleep(step)
            left -= step

    # ------------------------------------------------------------------
    # The counts
    # ------------------------------------------------------------------
    def start(self, kind: str) -> None:
        """A new search (or download) step: its counts start from zero; the other kind's are kept, so
        that a run that searches then downloads reports both."""
        fresh = Tally()
        names = ("keywords", "keywords_done", "searches_asked", "searches_answered", "searches_refused",
                 "searches_later", "searches_skipped") if kind == SEARCH else \
            ("dois", "downloaded", "no_copy", "failed", "refused", "later")
        for name in names:
            setattr(self.tally, name, getattr(fresh, name))

    def searched(self, keyword: str, answered: bool, later: bool) -> None:
        t = self.tally
        t.keywords.add(keyword)
        t.searches_asked += 1
        if answered:
            t.searches_answered += 1
            t.keywords_done.add(keyword)
            t.searches_later += later
        else:
            t.searches_refused += 1

    def fetched(self, key: str, status: str, refused: bool, later: bool) -> None:
        t = self.tally
        t.dois.add(key)
        for group in (t.downloaded, t.no_copy, t.failed):
            group.discard(key)  # its last try is what counts
        if refused:
            t.refused.add(key)
        elif status == DOWNLOADED:
            t.downloaded.add(key)
            if later:
                t.later.add(key)
        elif status == CLOSED:
            t.no_copy.add(key)
        else:
            t.failed.add(key)

    def report(self) -> List[str]:
        """The watcher's report: this run, then every run together."""
        t = self.tally
        searches_waiting = self.pending(SEARCH)
        dois_waiting = self.pending(DOWNLOAD)
        waiting_keywords = {row["item"] for row in searches_waiting}
        lines = ["Watcher report — this run:"]
        if t.searches_asked or t.searches_skipped:
            lines.append(f"  keywords checked: {len(t.keywords):,} ({len(t.keywords_done):,} answered by at least one "
                         f"source; {len(waiting_keywords & t.keywords):,} with a source still waiting)")
            lines.append(f"  searches (keyword × source): {t.searches_asked:,} asked, {t.searches_answered:,} answered, "
                         f"{t.searches_refused:,} refused, {t.searches_later:,} answered on a later try; "
                         f"{t.searches_skipped:,} already done in the last 30 days")
        if t.dois:
            still = {row["item"] for row in dois_waiting} & t.dois
            lines.append(f"  DOIs checked: {len(t.dois):,} — {len(t.downloaded):,} downloaded "
                         f"({len(t.later):,} on a later try), {len(t.no_copy):,} with no legal copy, "
                         f"{len(t.failed):,} failed, {len(still):,} still refused (waiting)")
        if len(lines) == 1:
            lines.append("  nothing checked")
        counts = self.ledger.counts()
        checked = sum(counts.get(s, 0) for s in (DOWNLOADED, EXTRACTED, CLOSED, FAILED))
        lines.append("In total (every run): "
                     f"{self.ledger.searched_queries():,} keywords answered in full by at least one source; "
                     f"{checked:,} DOIs checked ({counts.get(DOWNLOADED, 0) + counts.get(EXTRACTED, 0):,} downloaded, "
                     f"{counts.get(CLOSED, 0):,} with no legal copy, {counts.get(FAILED, 0):,} to try again); "
                     f"waiting on the watch list: {len(searches_waiting):,} searches "
                     f"({len({r['item'] for r in searches_waiting}):,} keywords) and {len(dois_waiting):,} DOIs.")
        given_up = self.given_up_count()
        if given_up:
            lines.append(f"Given up for {SEARCH_KEPT_DAYS} days (refused more than {MAX_TRIES} times): {given_up:,} searches.")
        return lines
