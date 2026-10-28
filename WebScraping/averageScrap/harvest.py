# WebScraping/harvest.py
"""The web project end to end: discover -> screen -> (your review) -> fetch -> extract.

Every stage is resumable because every step is recorded in the ledger (WebScraping/papers/ledger.sqlite):
run it again after a crash, a Ctrl-C or a review and it carries on, never fetching a paper twice."""

import logging
import os
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List, Optional

import requests

from LocalExtraction.exporter import read_table
from LocalExtraction.pipeline import NaLiXPipeline
from WebScraping.averageScrap import screening
from WebScraping.averageScrap import abstracts, sources
from WebScraping.averageScrap.elsevier import Elsevier
from WebScraping.averageScrap.fetch import Downloader, Outcome
from WebScraping.averageScrap.http import HttpError, PoliteClient
from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.job import KEY_SIGNUP, Job
from WebScraping.averageScrap.ledger import APPROVED, CLOSED, DOWNLOADED, EXTRACTED, FAILED, Candidate, Ledger
from WebScraping.averageScrap.resolve import Resolver
from WebScraping.averageScrap.sidecar import read_provenance
from WebScraping.averageScrap.sources.arxiv import ArXiv
from WebScraping.averageScrap.sources.openalex import OpenAlex
from WebScraping.averageScrap.wiley import Wiley

STAGES = ("discover", "fetch", "extract")
MAX_ATTEMPTS = 3  # a paper that fails this many times is given up on (status "closed"); a later run can retry it by hand


class Harvest:
    def __init__(self, job: Job, output_dir: str, client: Optional[PoliteClient] = None,
                 ledger: Optional[Ledger] = None):
        self.job, self.output_dir = job, output_dir
        self.folder = job.fetch.folder
        os.makedirs(self.folder, exist_ok=True)
        self.client = client or PoliteClient(job.email())
        self.ledger = ledger or Ledger(os.path.join(self.folder, "ledger.sqlite"))
        self.review_path = os.path.join(self.folder, "candidates.csv")
        self.elsevier = Elsevier.from_env() if "elsevier" in job.fetch.sources else None
        self.wiley = Wiley.from_env() if "wiley" in job.fetch.sources else None

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

    def discover(self) -> int:
        """Asks every source every query, then completes what was found (OpenAlex's record of a paper
        another source found, the abstracts the records lacked). Returns how many papers were new to
        the ledger."""
        s = self.job.search
        added = 0
        for name in s.sources:
            source = sources.make(name, self.client, self.job.email(), s.arxiv_categories)
            if not source.available():
                signup = KEY_SIGNUP.get(source.key_name, "")
                logging.info(f"{name}: skipped — {source.key_name} is not set in WebScraping/averageScrap/.env"
                             + (f" (free: {signup})" if signup else ""))
                continue
            for query in s.queries:
                found = new = 0
                try:
                    for candidate in source.search(query, s.years, s.max_per_query, s.include_preprints):
                        found += 1
                        new += self.ledger.add(candidate)
                except HttpError as error:
                    if error.status in (401, 403):
                        logging.warning(f"{name}: the key was refused (HTTP {error.status}) — is {source.key_name} "
                                        "right? This source is skipped for the rest of the run.")
                        break
                    logging.warning(f"{name}: the search for {query!r} stopped early: {error}")
                except (requests.RequestException, ET.ParseError, ValueError) as error:
                    logging.warning(f"{name}: the search for {query!r} stopped early: {error}")
                logging.info(f"{name}: {query!r} -> {found} found, {new} new")
                added += new
        listed = new = 0
        for candidate in self._ids():
            listed += 1
            new += self.ledger.add(candidate)
        if listed:
            logging.info(f"ids_file: {listed} listed, {new} new")
        found = abstracts.complete(self.ledger, self.client, s.abstract_sources, self.job.email())
        if found is not None:
            logging.info(f"Abstracts: {found} found for papers whose record had none.")
        return added + new

    # ------------------------------------------------------------------
    # 2. Screen
    # ------------------------------------------------------------------
    def screen(self, approve: bool = False) -> int:
        """Scores what is new, proposes a decision for each paper and writes the review list.
        Returns how many papers wait for a decision."""
        screening.screen(self.ledger, self.job.screen, elsevier_ok=self.elsevier is not None,
                         approve=approve or not self.job.screen.review, wiley_ok=self.wiley is not None)
        return self.ledger.write_review(self.review_path)

    # ------------------------------------------------------------------
    # 3. Fetch
    # ------------------------------------------------------------------
    def _record(self, candidate: Candidate, outcome: Outcome) -> None:
        attempts = candidate.attempts + 1
        if outcome.status == DOWNLOADED:
            self.ledger.update(candidate.key, status=DOWNLOADED, file=outcome.file, sha256=outcome.sha256,
                               source_used=outcome.service, source_url=outcome.url,
                               license=outcome.license or candidate.license, error="", attempts=attempts,
                               retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        else:
            gave_up = outcome.status == CLOSED or attempts >= MAX_ATTEMPTS
            self.ledger.update(candidate.key, status=CLOSED if gave_up else FAILED, error=outcome.error,
                               attempts=attempts)

    def fetch(self, limit: Optional[int] = None, stop_event: Optional[threading.Event] = None,
              progress_callback: Optional[Callable[[Candidate, Outcome, int, int], None]] = None) -> Dict[str, int]:
        """Takes the review list's decisions, then fetches every approved paper (and retries the ones
        that failed before). Returns how the fetched papers ended. `progress_callback` (optional) is
        called after each paper as `callback(candidate, outcome, done, total)`."""
        decided = self.ledger.apply_decisions(self.review_path)
        logging.info(f"Review list: {decided['approved']} approved, {decided['rejected']} rejected, "
                     f"{decided['waiting']} still waiting for a decision.")
        todo = self.ledger.all(APPROVED) + [c for c in self.ledger.all(FAILED) if c.attempts < MAX_ATTEMPTS]
        if limit is not None:
            todo = todo[:limit]
        results: Dict[str, int] = {DOWNLOADED: 0, CLOSED: 0, FAILED: 0}
        if not todo:
            logging.info("Nothing to fetch.")
            return results
        logging.info(f"Fetching {len(todo)} paper(s) into {self.folder} ...")
        resolver = Resolver(self.client, self.job.fetch.sources, self.job.email(), self.elsevier, self.wiley)
        downloader = Downloader(self.folder, self.client, resolver, self.job.fetch.max_pdf_mb)
        with ThreadPoolExecutor(max_workers=self.job.fetch.workers) as pool:
            futures = {pool.submit(downloader.fetch, c): c for c in todo}
            for done, future in enumerate(as_completed(futures), 1):
                candidate = futures[future]
                try:
                    outcome = future.result()
                except Exception as error:  # one bad paper must not stop a long run
                    outcome = Outcome(candidate.key, FAILED, error=f"{type(error).__name__}: {error}")
                self._record(candidate, outcome)
                results[outcome.status] = results.get(outcome.status, 0) + 1
                detail = f"via {outcome.service}" if outcome.status == DOWNLOADED else outcome.error[:120]
                logging.info(f"[{done}/{len(todo)}] {outcome.status}: {candidate.key} {detail}")
                if progress_callback is not None:
                    try:
                        progress_callback(candidate, outcome, done, len(todo))
                    except Exception as error:  # what shows the progress must not stop the run
                        logging.warning(f"progress_callback raised for {candidate.key}: {error}")
                if stop_event is not None and stop_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    logging.info("Stop requested — the papers not yet started were cancelled.")
                    break
        return results

    # ------------------------------------------------------------------
    # 4. Extract
    # ------------------------------------------------------------------
    def extract(self, max_workers: int = 4, stop_event: Optional[threading.Event] = None,
                progress_callback: Optional[Callable] = None) -> int:
        """Runs the Project 1 pipeline over the fetched PDFs, with the metadata the sources gave."""
        pipeline = NaLiXPipeline(
            self.folder, self.output_dir, provenance=read_provenance(self.folder),
            properties=self.job.extract.properties or None, require_material=self.job.extract.require_material,
            origin="web", lookup=True)
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
            job_path: str = "", stop_event: Optional[threading.Event] = None) -> int:
        """`start` is the first stage to run: "discover" (everything, up to the review if the job asks
        for one), "fetch" (after the review: fetch the approved papers, then extract) or "extract"."""
        if start not in STAGES:
            raise ValueError(f"unknown stage {start!r}; choose from {STAGES}")
        if start == "discover":
            added = self.discover()
            waiting = self.screen(approve=approve)
            logging.info(f"Ledger: {self.summary()} ({added} new this run).")
            if self.job.screen.review and not approve:
                print(f"\nReview the candidates in {self.review_path} ({waiting} waiting for a decision).\n"
                      "Set the `decision` column to yes or no, save the file, then fetch what you approved:\n"
                      f"    python -m WebScraping --job {job_path or '<job file>'} --stage fetch\n"
                      "(or add --yes to approve every proposal without looking).")
                return 0
        if start in ("discover", "fetch"):
            self.fetch(limit=limit, stop_event=stop_event)
        self.extract(max_workers=workers, stop_event=stop_event)
        logging.info(f"Ledger: {self.summary()}.")
        return 0
