# WebScraping/abstracts.py
"""Completing what the search found, before screening reads it.

  - A paper another source found (Crossref, Scopus, J-STAGE, ...) is looked up in OpenAlex, which
    says whether and where an open copy exists and whether the paper was retracted.
  - A paper whose record came without an abstract is judged on its title alone — OpenAlex does not
    carry Elsevier's abstracts, for one. The services of `search.abstract_sources` are asked for it,
    in that order, until one has it; each service is asked about a paper once (a service added to the
    job, or given its key, later is asked on the next run). A paper declined for want of an abstract
    is screened again once one is found."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from LocalExtraction import runcontrol
from typing import Callable, Dict, List, Optional, Tuple

import requests

from WebScraping.averageScrap import sources
from WebScraping.averageScrap.http import HttpError, PoliteClient
from WebScraping.averageScrap.ledger import NEW, REJECTED, SCREENED, Candidate, Ledger
from WebScraping.averageScrap.sources.openalex import OpenAlex

_PATIENCE = 3  # answers in a row a service may fail (too many requests, an error, no answer) before it is left alone
_REFUSED = {
    "scopus": "it gives abstracts only on your university's network, or with ELSEVIER_INSTTOKEN",
}


ASKED_OPENALEX = "openalex"  # in abstract_asked: OpenAlex was asked for this paper's record
_OPENALEX_BATCH = 50


def complete_from_openalex(ledger: Ledger, client: PoliteClient, contact: str = "",
                           progress: Optional[Callable[[int, int], None]] = None) -> int:
    """OpenAlex's record merged into every new paper another source found. Returns how many it knew."""
    waiting = {c.doi: c for c in ledger.all(NEW) if c.doi and not c.openalex_id and ASKED_OPENALEX not in c.abstract_asked}
    todo = list(waiting)
    if not todo:
        return 0
    known = 0
    openalex = OpenAlex(client, contact)
    try:
        for start in range(0, len(todo), _OPENALEX_BATCH):
            batch = todo[start:start + _OPENALEX_BATCH]
            for record in openalex.lookup_many(batch):
                ledger.add(record)
                known += 1
            # Asked: a DOI OpenAlex does not know is not asked again by every search.
            for doi in batch:
                paper = ledger.get(waiting[doi].key)
                if paper is not None and ASKED_OPENALEX not in paper.abstract_asked:
                    ledger.update(paper.key, abstract_asked=[*paper.abstract_asked, ASKED_OPENALEX])
            if progress is not None:
                progress(min(start + _OPENALEX_BATCH, len(todo)), len(todo))
            if start and start % (_OPENALEX_BATCH * 40) == 0:
                logging.info(f"OpenAlex: {start:,} of {len(todo):,} new papers looked up …")
    except (HttpError, requests.RequestException, ValueError) as error:
        logging.warning(f"OpenAlex: the lookup of the new papers stopped early ({error}); the rest are looked up "
                        "by the next search.")
    logging.info(f"OpenAlex knew {known} of the {len(todo)} new paper(s) other sources found.")
    return known


class AbstractFinder:
    """Asks the services in order for the abstract of one paper."""

    def __init__(self, client: PoliteClient, names: List[str], contact: str = ""):
        self.services = []
        for name in names:
            service = sources.make(name, client, contact)
            if service.available():
                self.services.append(service)
            else:
                logging.info(f"Abstracts: {service.label} is skipped ({service.key_name} is not set).")
        self._lock = threading.Lock()
        self._failed: Dict[str, int] = {}
        self._off: Dict[str, str] = {}

    def _leave_alone(self, service, why: str) -> None:
        with self._lock:
            if service.name not in self._off:
                self._off[service.name] = why
                logging.warning(f"Abstracts: not asking {service.label} for the rest of this run: {why}.")

    def _strike(self, service, why: str) -> None:
        with self._lock:
            self._failed[service.name] = self._failed.get(service.name, 0) + 1
            if self._failed[service.name] < _PATIENCE:
                return
        self._leave_alone(service, why)

    def pending(self, candidate: Candidate) -> List:
        """The services not yet asked about this paper that can be."""
        return [s for s in self.services if s.name not in candidate.abstract_asked and s.applies(candidate)]

    def find(self, candidate: Candidate) -> Tuple[str, str, List[str]]:
        """(abstract, the service that gave it, the services that answered). A service that could not
        answer — out of requests, down, refusing the key — is not counted as asked: it is asked again
        on the next run."""
        answered: List[str] = []
        for service in self.pending(candidate):
            with self._lock:
                if service.name in self._off:
                    continue
            try:
                text = service.abstract(candidate)
            except HttpError as error:
                if error.status in (401, 403):
                    self._leave_alone(service, _REFUSED.get(service.name, f"it refused the key (HTTP {error.status}): "
                                                                          f"is {service.key_name} right?"))
                    continue
                if error.status == 429 or error.status >= 500:
                    self._strike(service, "it allows no more requests for now" if error.status == 429
                                 else f"it keeps answering HTTP {error.status}")
                    continue
                text = ""  # 400, 404: it does not know the paper — an answer
            except (requests.RequestException, ValueError) as error:
                self._strike(service, "it does not answer" if isinstance(error, requests.RequestException)
                             else "its answers cannot be read")
                continue
            with self._lock:
                self._failed[service.name] = 0
            answered.append(service.name)
            if text:
                return text, service.name, answered
        return "", "", answered


def fill(ledger: Ledger, finder: AbstractFinder, workers: int = 4,
         progress: Optional[Callable[[int, int, int], None]] = None) -> int:
    """Asks for the abstract of every paper that has none. A paper screened on its title alone and
    waiting or declined is screened again (it goes back to "new"). Returns how many abstracts were found."""
    todo = [c for c in ledger.all() if not c.abstract and c.doi and finder.pending(c)]
    if not todo:
        return 0
    logging.info(f"Abstracts: looking for the abstract of {len(todo)} paper(s) that came without one ...")
    found = 0
    lock = threading.Lock()

    def one(candidate: Candidate) -> None:
        nonlocal found
        text, by, answered = finder.find(candidate)
        changes: Dict[str, object] = {"abstract_asked": [*candidate.abstract_asked, *answered]}
        if text:
            changes.update(abstract=text, abstract_from=by)
            if candidate.status in (SCREENED, REJECTED) and "no-abstract" in candidate.flags:
                changes["status"] = NEW  # judged on its title alone: judged again
        ledger.update(candidate.key, **changes)
        with lock:
            found += bool(text)

    control = runcontrol.current()  # the step these lookups are for: they pause and stop with it
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, _ in enumerate(pool.map(lambda c: runcontrol.task(control, one, c)(), todo), 1):
            if progress is not None:
                progress(done, len(todo), found)
            if done % 50 == 0 or done == len(todo):
                logging.info(f"Abstracts: {done}/{len(todo)} asked, {found} found")
    return found


def complete(ledger: Ledger, client: PoliteClient, abstract_sources: List[str], contact: str = "",
             workers: int = 4, records_progress: Optional[Callable[[int, int], None]] = None,
             abstracts_progress: Optional[Callable[[int, int, int], None]] = None) -> Optional[int]:
    """Both steps; returns how many abstracts were found (None when no service is to be asked). The progress
    callbacks get (done, total) of the OpenAlex lookups and (done, total, found) of the abstracts."""
    complete_from_openalex(ledger, client, contact, records_progress)
    if not abstract_sources:
        return None
    return fill(ledger, AbstractFinder(client, abstract_sources, contact), workers, abstracts_progress)
