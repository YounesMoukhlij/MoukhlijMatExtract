# WebScraping/harvest.py
"""The web project end to end: discover -> screen -> (your review) -> fetch -> extract.

Every stage is resumable because every step is recorded in the ledger (WebScraping/papers/ledger.sqlite):
run it again after a crash, a Ctrl-C or a review and it carries on, never fetching a paper twice."""

import csv
from collections import Counter
import logging
import os
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import requests

from LocalExtraction.exporter import read_table
from LocalExtraction import runcontrol
from WebScraping.averageScrap import screening
from WebScraping.averageScrap import abstracts, by_hand, download_log, learn, sources
from WebScraping.averageScrap.elsevier import Elsevier
from WebScraping.averageScrap.fetch import HAND_LIST, NOT_ENTITLED_MARK, Downloader, Outcome, SiteBlocks
from WebScraping.averageScrap.http import HttpError, PoliteClient
from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.job import KEY_SIGNUP, Job
from WebScraping.averageScrap.ledger import (DOI_LIST, APPROVED, CLOSED, DOWNLOADED, EXTRACTED, FAILED, SCREENED, SEARCH_KEPT_DAYS, YES,
                                             Candidate, Ledger)
from WebScraping.averageScrap.resolve import NOT_FOUND_ADVICE, Resolver, email_advice
from WebScraping.averageScrap.sidecar import read_provenance
from WebScraping.averageScrap.sources.arxiv import ArXiv
from WebScraping.averageScrap.sources.openalex import OpenAlex
from WebScraping.averageScrap.watcher import DOWNLOAD, MAX_TRIES as MAX_WATCH_TRIES, ROUNDS_MINUTES, SEARCH, Watcher, \
    is_refusal, refusal_text
from WebScraping.averageScrap.wiley import Wiley

STAGES = ("discover", "fetch", "extract")
# A source that cuts this many searches in a row short with "too many requests" (after the client's own
# pauses) is left alone for the rest of the run, so that a source blocking this network for an hour
# does not cost minutes per query, query after query.
_RATE_LIMITED_IN_A_ROW = 3
MAX_ATTEMPTS = 3  # a paper that fails this many times is given up on (status "closed"); a later run can retry it by hand


# The steps of the search, in order: (key, what it does).
SEARCH_STEPS = (("dois", "Fetch DOIs: the keywords asked of OpenAlex, Crossref, Semantic Scholar and arXiv for DOIs"),
                ("keywords", "Keyword search: the keywords asked of every search source"),
                ("check", "Check the new papers — the DOI list's among them: OpenAlex record, abstract"),
                ("snowball", "Citation snowballing: the references of the papers kept, and the papers citing them"),
                ("screen", "Score each paper on the topic and propose the ones to download"))


def _say_step(step: Optional[str]) -> None:
    for number, (key, what) in enumerate(SEARCH_STEPS, 1):
        if key == step:
            logging.info(f"--- Search, step {number} of {len(SEARCH_STEPS)}: {what}")


def _count_lines(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


class _Lines:
    """A stdout that hands each line it is given to a function."""

    def __init__(self, write_line: Callable[[str], None]):
        self._write_line, self._part = write_line, ""

    def write(self, text: str) -> int:
        self._part += text
        *lines, self._part = self._part.split("\n")
        for line in lines:
            if line.strip():
                self._write_line(line.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


NOT_ENTITLED_ADVICE = (
    "{n} closed paper(s) were refused by Elsevier or Wiley: not entitled from this network. Their keys download "
    "the closed papers your university subscribes to only on its network — on campus, or through a VPN that "
    "sends everything through it — or, for Elsevier, anywhere with the institutional token (ELSEVIER_INSTTOKEN, "
    "from your library). Run “3 · Download” again from there: these papers are tried again.")


# The papers a busy service refused are tried again at the end of a download one after another, at least this many
# seconds apart (more when a service asked for more: Semantic Scholar's 429s, one request every 30 s).
LATER_SPACING = 5.0
# The longest the papers tried again at the end may take, per round: at most this many seconds of spacing. The rest stay
# on the watch list for the next download, which tries them first. (900 papers 30 s apart is 7.5 hours a round.)
LATER_ROUND_SECONDS = 30 * 60
# Lookups that only add to what the others find: their "not now" alone does not hold a paper for the rounds at the
# end. Semantic Scholar gives an arXiv version or a repository copy, which the other services mostly know already
# (2 of 30 papers it had refused in a run had a green copy, none an arXiv version), and it refuses often (HTTP 429).
# Such a paper is filed with what the other services answered — the next download asks the lookup again.
# Springer Nature's Open Access API is the same kind of lookup, on a daily quota (Basic plan): once used up, waiting
# minutes changes nothing, so its papers are filed and asked again by the next download.
SUPPLEMENTARY_LOOKUPS = frozenset({"Semantic Scholar", "Springer Nature"})


def refusers(rows: List[Dict[str, str]]) -> str:
    """The services that refused these waiting papers, the most frequent first: "Semantic Scholar, OSTI"."""
    counts = Counter(name.strip() for row in rows for name in (row.get("reason") or "").split(",") if name.strip())
    return ", ".join(name for name, _ in counts.most_common()) or "a busy service"


def worth_waiting(rows: List[Dict[str, str]], down: set) -> List[Dict[str, str]]:
    """The waiting downloads a round of the watcher can bring: those a busy site refused ("too many requests",
    a server error), which a few minutes may clear. A paper refused only by services that did not answer at all
    this run waits for the next run instead: it stays on the watch list, which that run checks first."""
    def services(row: Dict[str, str]) -> set:
        return {name.strip() for name in (row.get("reason") or "").split(",") if name.strip()}
    return [row for row in rows if not services(row) or not services(row) <= down]


class Harvest:
    def __init__(self, job: Job, output_dir: str, client: Optional[PoliteClient] = None,
                 ledger: Optional[Ledger] = None):
        self.job, self.output_dir = job, output_dir
        self.folder = job.fetch.folder
        os.makedirs(self.folder, exist_ok=True)
        self.client = client or PoliteClient(job.email())
        self.email_problem = ""  # set by fetch(): why Unpaywall could not be asked (resolve.email_advice)
        self.blocks: Optional[SiteBlocks] = None  # set by fetch(): the sites refusing programs during this run
        self.ledger = ledger or Ledger(os.path.join(self.folder, "ledger.sqlite"))
        self.review_path = os.path.join(self.folder, "candidates.csv")
        self.by_hand_folder = by_hand.inbox(self.folder)  # where the PDFs saved by hand in a browser are put
        self.taken_in = 0  # the PDFs of the by_hand folder the last download took in
        # What a download says of the papers a busy service refused (a line of the window; also logged).
        self.on_notice: Optional[Callable[[str], None]] = None
        self.elsevier = Elsevier.from_env() if "elsevier" in job.fetch.sources else None
        self.wiley = Wiley.from_env() if "wiley" in job.fetch.sources else None
        # What a site refused, checked again later; and the count of what was checked (watcher.py).
        self.watcher = Watcher(self.ledger, sleep=self.client.pause)
        # The steps of the search, as they begin (SEARCH_STEPS keys; None: the search is over): the window
        # shows them, the terminal prints them. And where the lines Fetch DOIs prints go (None: stdout).
        self.on_step: Callable[[Optional[str]], None] = _say_step
        self.on_line: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # 1. Discover
    # ------------------------------------------------------------------
    def _ids(self) -> Iterator[Candidate]:
        """The papers named in the job's ids_file: one DOI, DOI link or arXiv id per line."""
        path = self.job.search.ids_file
        if not path:
            return
        openalex, arxiv = OpenAlex(self.client, self.job.email()), ArXiv(self.client)
        with open(path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
        for line in lines:
            doi, identifier = normalize_doi(line), arxiv_id(line)
            known = candidate_key(doi, identifier)
            if known and self.ledger.get(known) is not None:  # looked up by an earlier run
                logging.info(f"ids_file: {line} is already in the ledger — skipped.")
                yield Candidate(key=known, found_by=["list"])
                continue
            found = (openalex.lookup(doi) if doi and not identifier else None) \
                or (arxiv.lookup(identifier) if identifier else None) \
                or (openalex.lookup(doi) if doi else None)
            if found is None:  # unknown to both: keep it anyway, Unpaywall or Elsevier may still have it
                key = candidate_key(doi, identifier)
                if not key:
                    logging.warning(f"ids_file: cannot read an identifier from {line!r}")
                    continue
                found = Candidate(key=key, doi=doi, arxiv_id=identifier, found_by=["list"])
            found.found_by = [*found.found_by, "list"] if "list" not in found.found_by else found.found_by
            yield found

    def add_dois(self, csv_path: str, txt_path: str = "") -> Tuple[int, int]:
        """The DOIs of a DOI list (Fetch DOIs' dois.csv, with each DOI's title, year, authors and journal;
        else the bare DOIs of dois.txt) as new candidates, checked like the papers the keywords found:
        `check_new` (or the search) gets each one's OpenAlex record and abstract, then screening scores
        it. A DOI the ledger knows already is left as it is. Returns (DOIs in the list, new candidates)."""
        rows: List[Dict[str, str]] = []
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = [row for row in csv.DictReader(f) if (row.get("doi") or "").strip()]
        except OSError:
            pass
        if not rows and txt_path:
            try:
                with open(txt_path, encoding="utf-8") as f:
                    rows = [{"doi": line.strip()} for line in f if line.strip()]
            except OSError:
                pass
        def known(value: Optional[str]) -> str:  # "not listed by OpenAlex or Crossref" and the like: unknown
            value = (value or "").strip()
            return "" if value.lower().startswith("not ") else value

        candidates = []
        for row in rows:
            doi = normalize_doi(row["doi"])
            key = candidate_key(doi, "") if doi else ""
            if not key:
                continue
            year = known(row.get("year"))
            candidates.append(Candidate(
                key=key, doi=doi, title=known(row.get("title")), year=int(year) if year.isdigit() else 0,
                journal=known(row.get("venue")),
                authors=[known(a) for a in (row.get("authors") or "").split(";") if known(a)],
                found_by=[DOI_LIST]))
        added = self.ledger.add_new(candidates)
        logging.info(f"DOI list: {len(candidates):,} DOIs, {added:,} new — checked like the papers the keywords "
                     f"found (OpenAlex record, abstract, topic score); {len(candidates) - added:,} were candidates "
                     "already.")
        return len(candidates), added

    def check_new(self) -> int:
        """The papers not checked yet (new: a DOI list just taken in): each one's OpenAlex record and
        abstract, then its topic score. Returns how many are proposed for download now. Stopped while
        it looks them up, they stay new and the next search goes on with them."""
        s = self.job.search
        found = abstracts.complete(self.ledger, self.client, s.abstract_sources, self.job.email())
        if found is not None:
            logging.info(f"Abstracts: {found} found for papers whose record had none.")
        self.screen(approve=False)
        return sum(1 for c in self.ledger.all(SCREENED, APPROVED) if c.decision == YES)

    def collect_dois(self, job_path: str = "") -> int:
        """Fetch DOIs, the first step of the search (search.collect_dois): the job's keywords asked of
        OpenAlex, Crossref, Semantic Scholar and arXiv; the DOIs they give go to the DOI list
        (search.doi_list), which the search then takes in. Returns how many DOIs were new to the list."""
        import contextlib
        from WebScraping.Fetch_DOIs import get_dois
        s = self.job.search
        txt = os.path.splitext(s.doi_list)[0] + ".txt"
        before = _count_lines(txt)
        argv = ["--out", s.doi_list] + (["--job", job_path] if job_path and os.path.exists(job_path) else [])
        writer = contextlib.redirect_stdout(_Lines(self.on_line)) if self.on_line else contextlib.nullcontext()
        with writer:
            try:
                get_dois.main(argv)
            except SystemExit as error:  # its own way to say it cannot run (no keywords, ...)
                if error.code not in (None, 0):
                    logging.warning(f"Fetch DOIs could not run: {error.code}")
        new = _count_lines(txt) - before
        logging.info(f"Fetch DOIs: {new:,} new DOI(s) in the list ({_count_lines(txt):,} in all).")
        return new

    def discover(self, refresh: bool = False, job_path: str = "", collect_dois: Optional[bool] = None) -> int:
        """Asks every source every query, then completes what was found (OpenAlex's record of a paper
        another source found, the abstracts the records lacked). Returns how many papers were new to
        the ledger. A query a source already answered in full (as deep, for the same years) less than
        SEARCH_KEPT_DAYS ago is skipped, unless `refresh`."""
        s = self.job.search
        added = 0
        self.watcher.start(SEARCH)
        try:
            # Fetch DOIs first (mme-web, search.collect_dois); the window has its own button for it, and
            # its search uses the DOIs saved (collect_dois=False).
            if (s.collect_dois if collect_dois is None else collect_dois) and s.doi_list:
                self.on_step("dois")
                self.collect_dois(job_path)
                runcontrol.check()  # stopped during Fetch DOIs: the search ends here
            self.on_step("keywords")
            added = self._search_all(refresh)
            listed = new = 0
            for candidate in self._ids():
                runcontrol.check()
                listed += 1
                new += self.ledger.add(candidate)
            if listed:
                logging.info(f"ids_file: {listed} listed, {new} new")
            added += new
            self.on_step("check")
            if s.doi_list:  # the DOIs Fetch DOIs collected: checked like the papers the keywords found
                if os.path.exists(s.doi_list) or os.path.exists(os.path.splitext(s.doi_list)[0] + ".txt"):
                    added += self.add_dois(s.doi_list, os.path.splitext(s.doi_list)[0] + ".txt")[1]
                else:
                    logging.info(f"doi_list: there is no {s.doi_list} yet — Fetch DOIs (mme-dois) collects it.")
            if s.snowball:  # the papers kept so far bring the papers they cite and those citing them
                self.on_step("snowball")
                added += self.snowball(refresh)
            found = abstracts.complete(self.ledger, self.client, s.abstract_sources, self.job.email())
            if found is not None:
                logging.info(f"Abstracts: {found} found for papers whose record had none.")
        except runcontrol.StepStopped:
            logging.info("Search stopped — the papers found so far are kept; a search cut short is run again "
                         "next time.")
        self.log_report()
        return added

    def snowball(self, refresh: bool = False) -> int:
        """Citation snowballing on OpenAlex. Each paper kept so far (decision "yes") that has an OpenAlex record
        gives the papers it cites and, the most cited first, up to search.snowball_citing papers citing it —
        within the job's years and kinds of work. What is new goes into the ledger and is screened like the papers
        the keywords found. A paper snowballed less than SEARCH_KEPT_DAYS ago is not asked again, unless
        `refresh`. Returns how many papers were new."""
        from .sources.openalex import OpenAlex
        s = self.job.search

        def search(seed: str) -> str:
            return f"snowball|{seed}|{s.years}|{s.include_preprints}"

        seeds = sorted({c.openalex_id for c in self.ledger.all() if c.decision == "yes" and c.openalex_id})
        todo = [seed for seed in seeds if refresh or not self.ledger.searched(search(seed), s.snowball_citing)]
        if not todo:
            logging.info(f"Snowballing: nothing new to ask ({len(seeds)} paper(s) kept, all snowballed in the last "
                         f"{SEARCH_KEPT_DAYS} days).")
            return 0
        source = OpenAlex(self.client, self.job.email())
        cited = citing = 0
        try:
            for _, candidate in source.references(todo, s.years, s.include_preprints):
                cited += self.ledger.add(candidate)
            for seed in todo:
                runcontrol.check()  # between two papers: Pause holds here, Stop ends it
                for candidate in source.citing(seed, s.years, s.snowball_citing, s.include_preprints):
                    citing += self.ledger.add(candidate)
                self.ledger.mark_searched(search(seed), s.snowball_citing)
        except (HttpError, requests.RequestException, ValueError) as error:
            logging.warning(f"Snowballing stopped early: {error}. What it found is kept; the papers not done are "
                            "asked next time.")
        logging.info(f"Snowballing {len(todo)} kept paper(s): {cited} new paper(s) among their references, {citing} "
                     "among the papers citing them — screened like the others.")
        return cited + citing

    def _search_all(self, refresh: bool) -> int:
        """Every source asked every query (discover's first part), then — when a site refused some of
        them — the watcher's rounds. Returns how many papers were new."""
        s = self.job.search
        # What waits from an earlier run and no longer belongs to the job is forgotten.
        self.watcher.forget(SEARCH, lambda row: row["item"] in s.queries and row["service"] in s.sources)
        added = 0
        for name in s.sources:
            source = self._source(name)
            if source is None:
                continue
            added += self._search_queries(source, name, s.queries, refresh)
        return added + self._recheck_searches(refresh)

    def _source(self, name: str):
        """The search source of that name, or None (said why) when its key is missing."""
        s = self.job.search
        source = sources.make(name, self.client, self.job.email(), s.arxiv_categories)
        if not source.available():
            signup = KEY_SIGNUP.get(source.key_name, "")
            logging.info(f"{name}: skipped — {source.key_name} is not set in ~/MoukhlijMatExtract/.env"
                         + (f" ({signup})" if signup else ""))
            return None
        return source

    def _search_queries(self, source, name: str, queries: List[str], refresh: bool, later: bool = False,
                        give_up_after: int = _RATE_LIMITED_IN_A_ROW) -> int:
        """One source asked these queries. A source that refuses `give_up_after` in a row is not asked
        the rest: they go on the watch list unasked."""
        added, refused = 0, 0
        for index, query in enumerate(queries):
            if refused >= give_up_after:
                rest = [q for q in queries[index:] if refresh or not self.ledger.searched(self._search_key(name, q),
                                                                                           self.job.search.max_per_query)]
                for q in rest:
                    self.watcher.defer(SEARCH, q, name, "not asked: the source kept refusing")
                logging.warning(f"{name}: it keeps refusing (too many requests, or no answer), so it is not asked the "
                                f"{len(rest)} other search(es) now; the watcher keeps them and asks again later.")
                break
            state, new = self._search_one(source, name, query, refresh, later)
            if state == "key":
                break
            refused = refused + 1 if state == "refused" else 0
            added += new
        return added

    def _search_key(self, name: str, query: str) -> str:
        s = self.job.search
        return f"{name}|{query.strip().lower()}|{s.years}|{s.include_preprints}"

    def _search_one(self, source, name: str, query: str, refresh: bool, later: bool = False) -> Tuple[str, int]:
        """One query asked of one source: "done", "skipped" (answered by an earlier run), "refused" (on
        the watch list), "broken" (an answer that could not be read) or "key" (the key was refused).
        Also how many papers were new."""
        s = self.job.search
        search = self._search_key(name, query)
        when = None if refresh else self.ledger.searched(search, s.max_per_query)
        if when:
            logging.info(f"{name}: {query!r} already searched on {when} — skipped "
                         f"(searched again after {SEARCH_KEPT_DAYS} days, or with --refresh).")
            self.watcher.done(SEARCH, query, name)
            self.watcher.tally.searches_skipped += 1
            return "skipped", 0
        runcontrol.check()  # between two searches: Pause holds here, Stop ends the search
        found = new = 0
        state = "done"
        try:
            for candidate in source.search(query, s.years, s.max_per_query, s.include_preprints):
                found += 1
                new += self.ledger.add(candidate)
            self.ledger.mark_searched(search, s.max_per_query)  # answered in full: not asked again
            self.watcher.done(SEARCH, query, name)
        except (HttpError, requests.RequestException) as error:
            if isinstance(error, HttpError) and error.status in (401, 403):
                key = getattr(source, "key_name", "")  # OpenAlex and arXiv have none
                said = (f"the key was refused (HTTP {error.status}) — is {key} right?" if key
                        else f"it refused the search (HTTP {error.status}).")
                logging.warning(f"{name}: {said} This source is skipped for the rest of the run.")
                return "key", new
            if is_refusal(error):
                tries = self.watcher.defer(SEARCH, query, name, refusal_text(error))
                if tries > MAX_WATCH_TRIES:  # refused run after run: a source that is gone, not busy
                    self.watcher.done(SEARCH, query, name)
                    logging.warning(f"{name}: the search for {query!r} was refused {tries} times — given up.")
                else:
                    logging.warning(f"{name}: {refusal_text(error)} — the search for {query!r} was cut short. What it "
                                    "found is kept; the watcher asks again later.")
                state = "refused"
            else:
                logging.warning(f"{name}: the search for {query!r} stopped early: {error}")
                state = "broken"
        except (ET.ParseError, ValueError) as error:
            logging.warning(f"{name}: the search for {query!r} stopped early: {error}")
            state = "broken"
        self.watcher.searched(query, answered=state == "done", later=later)
        logging.info(f"{name}: {query!r} -> {found} found, {new} new")
        return state, new

    def _recheck_searches(self, refresh: bool) -> int:
        """The watcher's rounds for the searches a site refused: a pause, then each one asked again
        (a source that refuses twice in a round is left for the next round)."""
        added = 0
        for number, minutes in enumerate(ROUNDS_MINUTES, 1):
            waiting = self.watcher.pending(SEARCH)
            if not waiting:
                break
            self.watcher.wait(minutes, f"{len(waiting)} search(es)", number)
            by_source: Dict[str, List[str]] = {}
            for row in waiting:
                by_source.setdefault(row["service"], []).append(row["item"])
            for name, queries in by_source.items():
                source = self._source(name)
                if source is not None:
                    added += self._search_queries(source, name, queries, refresh, later=True, give_up_after=2)
        return added

    # ------------------------------------------------------------------
    # 2. Screen
    # ------------------------------------------------------------------
    def screen(self, approve: bool = False) -> int:
        """Scores what is new, proposes a decision for each paper and writes the review list.
        Returns how many papers wait for a decision."""
        before = self.ledger.counts()
        screening.screen(self.ledger, self.job.screen, elsevier_ok=self.elsevier is not None,
                         approve=approve or not self.job.screen.review, wiley_ok=self.wiley is not None)
        after = self.ledger.counts()
        if after == before and os.path.exists(self.review_path):
            return after.get(SCREENED, 0)  # nothing new was scored: the review list (and edits not read yet) kept
        learn.refresh(self.ledger)  # the papers waiting ordered by the model of the decisions by hand
        return self.ledger.write_review(self.review_path)

    def rescreen(self) -> Dict[str, int]:
        """Decides again, with the job's screening settings of now, the papers not downloaded yet (screening.rescreen),
        and writes the review list the download reads. Returns the counts of screening.rescreen."""
        counts = screening.rescreen(self.ledger, self.job.screen, elsevier_ok=self.elsevier is not None,
                                    wiley_ok=self.wiley is not None)
        learn.refresh(self.ledger)
        self.ledger.write_review(self.review_path)
        logging.info(f"Re-screened {counts['rescored']:,} paper(s) not downloaded yet with the job's settings: "
                     f"{counts['proposed']:,} newly proposed, {counts['dropped']:,} no longer proposed.")
        return counts

    # ------------------------------------------------------------------
    # 3. Fetch
    # ------------------------------------------------------------------
    def _record(self, candidate: Candidate, outcome: Outcome, later: bool = False) -> str:
        """Files how a paper's download ended; returns its status ("waiting" when a site refused)."""
        if outcome.refused and outcome.status != DOWNLOADED and set(outcome.refused) <= SUPPLEMENTARY_LOOKUPS:
            # Only a supplementary lookup said "not now": the paper is filed with what the others answered (on the
            # hand list with its real reason), not held for the rounds. The try does not count against it, and the
            # next download asks the lookup again.
            self.watcher.done(DOWNLOAD, candidate.key)
            note = f"not checked: {', '.join(outcome.refused)} refused (too many requests) — asked again next download"
            self.ledger.update(candidate.key, status=FAILED,
                               error=(f"{outcome.error}; {note}" if outcome.error else note)[:500])
            self.watcher.fetched(candidate.key, FAILED, refused=False, later=later)
            return FAILED
        if outcome.refused and outcome.status != DOWNLOADED:
            services = ", ".join(outcome.refused)
            tries = self.watcher.defer(DOWNLOAD, candidate.key, "", services)
            if tries <= MAX_WATCH_TRIES:  # not an answer: the try does not count against the paper
                self.ledger.update(candidate.key, status=FAILED, error=(
                    f"waiting: {services} refused (too many requests, busy or no answer) — the watcher checks it "
                    f"again later. {outcome.error}")[:500])
                self.watcher.fetched(candidate.key, FAILED, refused=True, later=later)
                return "waiting"
            logging.info(f"{candidate.key}: refused {tries} times by {services} — counted as a failed try.")
        self.watcher.done(DOWNLOAD, candidate.key)
        attempts = candidate.attempts + 1
        if outcome.status == DOWNLOADED:
            self.ledger.update(candidate.key, status=DOWNLOADED, file=outcome.file, sha256=outcome.sha256,
                               source_used=outcome.service, source_url=outcome.url,
                               license=outcome.license or candidate.license, error="", attempts=attempts,
                               retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            status = DOWNLOADED
        elif outcome.status == FAILED and (NOT_ENTITLED_MARK in outcome.error or outcome.not_asked):
            # Refused for where the request came from, not for the paper — or not asked at all, its sites being
            # blocked for the run: the try does not count, and the paper is tried again by the next download
            # (from the university's network, or once the site lets programs through again, it may come).
            status = FAILED
            self.ledger.update(candidate.key, status=status, error=outcome.error)
        else:
            gave_up = outcome.status == CLOSED or attempts >= MAX_ATTEMPTS
            status = CLOSED if gave_up else FAILED
            self.ledger.update(candidate.key, status=status, error=outcome.error, attempts=attempts)
        self.watcher.fetched(candidate.key, status, refused=False, later=later)
        return status

    def fetch(self, limit: Optional[int] = None, stop_event: Optional[threading.Event] = None,
              progress_callback: Optional[Callable[[Candidate, Outcome, int, int], None]] = None) -> Dict[str, int]:
        """Takes the review list's decisions, then fetches every approved paper (and retries the ones
        that failed before, those the watcher was waiting for first). The papers a site refused are
        checked again in the watcher's rounds. Returns how the fetched papers ended — downloaded,
        closed (no legal copy), failed, waiting (still refused). `progress_callback` (optional) is
        called after each paper as `callback(candidate, outcome, done, total)`."""
        self.watcher.start(DOWNLOAD)
        self.run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # the run each line of download_log.csv belongs to
        decided = self.ledger.apply_decisions(self.review_path)
        logging.info(f"Review list: {decided['approved']} approved, {decided['rejected']} rejected, "
                     f"{decided['waiting']} still waiting for a decision.")
        taken = self.taken_in = by_hand.take_in(self.folder, self.ledger, self.hand_list_path)
        if taken:
            logging.info(f"By hand: {taken} PDF(s) of {self.by_hand_folder} taken in, with their source recorded.")
        for candidate in self.ledger.all(DOWNLOADED, EXTRACTED):
            logging.info(f"Already fetched: {candidate.key} ({candidate.file or 'in the folder'}) — skipped.")
        watched = {row["item"] for row in self.watcher.pending(DOWNLOAD)}
        retry = [c for c in self.ledger.all(FAILED) if c.attempts < MAX_ATTEMPTS]
        retry.sort(key=lambda c: c.key not in watched)  # what the watcher waits for goes first
        todo = self.ledger.all(APPROVED) + retry
        if limit is not None:
            todo = todo[:limit]
        self.email_problem = ""
        self.not_entitled = 0  # papers a publisher refused: the subscription is not reached from here
        self.blocks = SiteBlocks()  # the sites that refuse programs (HTTP 403), left alone for the rest of this run
        self.down: set = set()  # the services that did not answer at all this run
        if not todo:
            logging.info("Nothing to fetch.")
            self.write_hand_list()
            return {DOWNLOADED: 0, CLOSED: 0, FAILED: 0, "waiting": 0}
        logging.info(f"Fetching {len(todo)} paper(s) into {self.folder} ...")
        tried = {c.key for c in todo}
        rounds = 0
        try:
            self._fetch_batch(todo, stop_event, progress_callback)
            # The papers a busy service refused ("too many requests"): tried again at the end, after a pause that
            # grows round by round, one after another and spaced, at the pace the services asked for.
            for number, minutes in enumerate(ROUNDS_MINUTES, 1):
                if stop_event is not None and stop_event.is_set():
                    break
                pending = [row for row in self.watcher.pending(DOWNLOAD) if row["item"] in tried]
                worth = worth_waiting(pending, self.down)
                waiting = [row["item"] for row in worth]
                if not waiting:
                    if pending:
                        self.notice(f"{len(pending)} paper(s) wait only on services that did not answer at all "
                                    f"({', '.join(sorted(self.down))}): the next “3 · Download” tries them first.")
                    break
                spacing = self.later_spacing()
                room = max(1, int(LATER_ROUND_SECONDS // spacing))
                if len(waiting) > room:  # a round never runs for hours: the least-tried first, the rest next download
                    tries = {row["item"]: int(row.get("tries") or 0) for row in worth}
                    waiting = sorted(waiting, key=lambda key: tries.get(key, 0))[:room]
                    self.notice(f"{len(worth) - room} paper(s) left for the next “3 · Download”: at {spacing:g} s apart, "
                                f"only {room} fit in this round's {LATER_ROUND_SECONDS // 60} minutes.")
                slowed = self.client.slowed()
                asked = ("Asked to slow down: " + ", ".join(f"{host} (one request every {seconds:g} s)"
                                                             for host, seconds in sorted(slowed.items())) + ". "
                         if slowed else "")
                self.notice(f"{len(waiting)} paper(s) not downloaded yet: {refusers(worth)} refused them (too many "
                            f"requests, or busy). {asked}They are tried again at the end of this download, one after "
                            f"another, {spacing:g} s apart — round {number} of {len(ROUNDS_MINUTES)}, in {minutes:g} min.")
                self.watcher.wait(minutes, f"{len(waiting)} DOI(s)", number)
                again = [c for c in (self.ledger.get(key) for key in waiting) if c is not None]
                self._fetch_batch(again, stop_event, progress_callback, later=True, spacing=spacing)
                rounds = number
            still = [row for row in self.watcher.pending(DOWNLOAD) if row["item"] in tried]
            if rounds and still:
                self.notice(f"{len(still)} paper(s) still refused by {refusers(still)} after {rounds} round(s) at the end "
                            "of this download: they stay on the watch list, and the next “3 · Download” tries them first.")
            elif rounds:
                self.notice("The papers a busy service refused were tried again at the end of this download: none is "
                            "left waiting.")
        except runcontrol.StepStopped:
            logging.info("Stopped — what was downloaded is kept; the DOIs the watcher was waiting for stay on its "
                         "list for the next run.")
        t = self.watcher.tally
        results = {DOWNLOADED: len(t.downloaded & tried), CLOSED: len(t.no_copy & tried), FAILED: len(t.failed & tried),
                   "waiting": len({row["item"] for row in self.watcher.pending(DOWNLOAD)} & tried)}
        missed = results[CLOSED] + results[FAILED]
        if self.email_problem:
            logging.warning(email_advice(self.job.email(), self.email_problem, bool(self.job.contact_email))
                            .replace("\n\n", " "))
        elif missed:
            logging.info(f"{missed} paper(s) without a legal copy found. " + NOT_FOUND_ADVICE.replace("\n", " "))
        if self.not_entitled:
            logging.warning(NOT_ENTITLED_ADVICE.format(n=self.not_entitled))
        self.write_hand_list()
        self.log_report()
        return results

    def notice(self, text: str) -> None:
        """What the download says of the papers a busy service refused: in the log, and in a line of the window."""
        logging.info(text)
        if self.on_notice is not None:
            try:
                self.on_notice(text)
            except Exception as error:  # what shows it must not stop the download
                logging.debug(f"on_notice raised: {error}")

    def later_spacing(self) -> float:
        """The seconds between two papers tried again at the end: the slowest pace a service asked for this run."""
        return max([LATER_SPACING, *self.client.slowed().values()])

    @property
    def hand_list_path(self) -> str:
        return os.path.join(self.folder, HAND_LIST)

    def write_hand_list(self) -> int:
        """Writes every paper the downloads could not get (HAND_LIST, in the papers folder): its link, why it was
        missed and what can be done (by_hand.missed_rows). A PDF saved from the link into the by_hand folder,
        under any name, is taken in by the next download with its source recorded. A paper whose PDF is in the
        folder already is left out, so the list shrinks as the PDFs come in. Returns how many papers it lists
        (0: the file is removed)."""
        rows = by_hand.missed_rows(self.folder, self.ledger)
        by_hand.write_hand_list(self.hand_list_path, rows)
        if rows:
            counts = Counter(row["reason"] for row in rows)
            logging.info(f"{len(rows)} paper(s) not downloaded automatically — "
                         + ", ".join(f"{n} {reason.lower()}" for reason, n in counts.most_common())
                         + f". The list, with each paper's link and what to do: {self.hand_list_path}. A PDF saved "
                         f"into {self.by_hand_folder} (any name) is taken in by the next “3 · Download”, its source recorded.")
        return len(rows)

    def log_report(self) -> None:
        """The watcher's report, in the log: what was checked this run and in total, what still waits."""
        for line in self.watcher.report():
            logging.info(line)

    def _fetch_batch(self, todo: List[Candidate], stop_event: Optional[threading.Event],
                     progress_callback: Optional[Callable[[Candidate, Outcome, int, int], None]],
                     later: bool = False, spacing: float = 0.0) -> int:
        """Downloads these papers with a new resolver (a service left alone in an earlier round is asked again):
        in parallel, or — `spacing` given, for the papers tried again at the end — one after another, `spacing`
        seconds apart (a Pause holds the wait, a Stop ends it). Returns how many ended without a copy."""
        resolver = Resolver(self.client, self.job.fetch.sources, self.job.email(), self.elsevier, self.wiley)
        if self.blocks is None:
            self.blocks = SiteBlocks()
        downloader = Downloader(self.folder, self.client, resolver, self.job.fetch.max_pdf_mb, blocks=self.blocks)
        missed = 0

        def finish(candidate: Candidate, outcome: Optional[Outcome], done: int) -> None:
            nonlocal missed
            if outcome is None:
                return
            if outcome.status != DOWNLOADED and NOT_ENTITLED_MARK in outcome.error:
                self.not_entitled = getattr(self, "not_entitled", 0) + 1
            status = self._record(candidate, outcome, later)
            missed += status in (CLOSED, FAILED)
            try:  # the paper's line in download_log.csv: what came of it, from where or why not, what to do
                recorded = self.ledger.get(candidate.key) or candidate
                download_log.add(self.folder, download_log.entry(recorded, getattr(self, "run_id", "")))
            except Exception as error:  # the record must not stop the download
                logging.warning(f"download_log.csv could not be written: {error}")
            detail = (f"via {outcome.service}" if outcome.status == DOWNLOADED else
                      f"refused by {', '.join(outcome.refused)} — tried again at the end of this download"
                      if status == "waiting" else outcome.error[:120])
            logging.info(f"[{done}/{len(todo)}] {status}: {candidate.key} {detail}")
            if progress_callback is not None:
                try:
                    progress_callback(candidate, outcome, done, len(todo))
                except Exception as error:  # what shows the progress must not stop the run
                    logging.warning(f"progress_callback raised for {candidate.key}: {error}")

        def run(candidate: Candidate) -> Optional[Outcome]:
            try:
                return runcontrol.task(stop_event, downloader.fetch, candidate)()
            except runcontrol.StepStopped:  # stopped while it was under way: tried again next run
                raise
            except Exception as error:  # one bad paper must not stop a long run
                return Outcome(candidate.key, FAILED, error=f"{type(error).__name__}: {error}")

        if spacing:
            for done, candidate in enumerate(todo, 1):
                if done > 1:
                    self.client.pause(spacing)
                if stop_event is not None and stop_event.is_set():
                    break
                finish(candidate, run(candidate), done)
        else:
            with ThreadPoolExecutor(max_workers=self.job.fetch.workers) as pool:
                futures = {pool.submit(run, c): c for c in todo}
                for done, future in enumerate(as_completed(futures), 1):
                    try:
                        outcome = future.result()
                    except runcontrol.StepStopped:  # stopped while it was under way: tried again next run
                        outcome = None
                    finish(futures[future], outcome, done)
                    if stop_event is not None and stop_event.is_set():
                        for pending in futures:
                            pending.cancel()
                        logging.info("Stop requested — the papers not yet started were cancelled; the next download "
                                     "goes on with them.")
                        break
        self.email_problem = self.email_problem or resolver.email_problem
        self.down = getattr(self, "down", set()) | resolver.down
        return missed

    # ------------------------------------------------------------------
    # 4. Extract
    # ------------------------------------------------------------------
    def extract(self, max_workers: int = 4, stop_event: Optional[threading.Event] = None,
                progress_callback: Optional[Callable] = None) -> int:
        """Runs the Project 1 pipeline over the fetched PDFs, with the metadata the sources gave."""
        from LocalExtraction.pipeline import NaLiXPipeline  # spaCy and the PDF models: loaded when needed, not
        # when the web window opens
        pipeline = NaLiXPipeline(
            self.folder, self.output_dir, provenance=read_provenance(self.folder),
            properties=self.job.extract.properties or None, require_material=self.job.extract.require_material,
            origin="web", lookup=True, domain=self.job.extract.domain)
        added = pipeline.execute(max_workers=max_workers, stop_event=stop_event, progress_callback=progress_callback)
        self._mark_extracted()
        return added

    def _mark_extracted(self) -> None:
        path = os.path.join(self.output_dir, "papers.csv")
        if not os.path.exists(path):
            return
        try:
            done = set(read_table(path)["filename"])
        except Exception as error:
            logging.debug(f"Could not read {path} to mark extracted papers: {error}")
            return
        for candidate in self.ledger.all(DOWNLOADED):
            if candidate.file in done:
                self.ledger.update(candidate.key, status=EXTRACTED)

    # ------------------------------------------------------------------
    # The whole run
    # ------------------------------------------------------------------
    def summary(self) -> str:
        counts = self.ledger.counts()
        order = ("new", "screened", "approved", "rejected", "downloaded", "extracted", "closed", "failed")
        return ", ".join(f"{counts[s]} {s}" for s in order if counts.get(s)) or "empty"

    def run(self, start: str = "discover", approve: bool = False, limit: Optional[int] = None, workers: int = 4,
            job_path: str = "", stop_event: Optional[threading.Event] = None, refresh: bool = False) -> int:
        """See _run. The computer is kept from going to sleep while it runs (runcontrol.stay_awake)."""
        with runcontrol.stay_awake("MoukhlijMatExtract is searching, downloading and extracting papers"):
            return self._run(start, approve, limit, workers, job_path, stop_event, refresh)

    def _run(self, start: str = "discover", approve: bool = False, limit: Optional[int] = None, workers: int = 4,
             job_path: str = "", stop_event: Optional[threading.Event] = None, refresh: bool = False) -> int:
        """`start` is the first stage to run: "discover" (everything, up to the review if the job asks
        for one), "fetch" (after the review: fetch the approved papers, then extract) or "extract"."""
        if start not in STAGES:
            raise ValueError(f"unknown stage {start!r}; choose from {STAGES}")
        stopped = lambda: stop_event is not None and stop_event.is_set()  # noqa: E731
        if start == "discover":
            added = self.discover(refresh=refresh, job_path=job_path)
            self.on_step("screen")
            waiting = self.screen(approve=approve)  # what was found before a stop is scored too
            self.on_step(None)
            logging.info(f"Ledger: {self.summary()} ({added} new this run).")
            if stopped():
                return 0
            if self.job.screen.review and not approve:
                print(f"\nReview the candidates in {self.review_path} ({waiting} waiting for a decision).\n"
                      "Set the `decision` column to yes or no, save the file, then fetch what you approved:\n"
                      f"    python -m WebScraping --job {job_path or '<job file>'} --stage fetch\n"
                      "(or add --yes to approve every proposal without looking).")
                return 0
        if start in ("discover", "fetch"):
            self.fetch(limit=limit, stop_event=stop_event)
            if stopped():
                return 0
        self.extract(max_workers=workers, stop_event=stop_event)
        logging.info(f"Ledger: {self.summary()}.")
        return 0
