# web/resolve.py
"""Where a legal copy of a paper may be had. A resolver does not download anything: it lists the
places to try, best first, and the downloader tries them in order until one gives a real PDF.
The order comes from the job (`fetch.sources`); a source that does not apply to a paper — Elsevier's
API for a Nature paper, Unpaywall without a contact email — simply offers nothing.

Three kinds of source:
  - a publisher's own interface for programs: `elsevier` and `wiley` (each needs a free key) and
    `aps` (its open-access articles, no key);
  - the open links the discovery services know: `openalex`, `unpaywall`, `arxiv`;
  - the repositories authors and funders deposit in, asked by DOI: `pmc` (PubMed Central's
    open-access set), `osti` (US Department of Energy), `hal` (France), `openaire` (Europe) — and
    `semanticscholar`, which knows the arXiv version of a journal paper.
A source is only asked once the ones before it gave nothing that could be kept, so these lookups
cost nothing for a paper whose first link works."""

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from web.elsevier import Elsevier
from web.http import HttpError, PoliteClient
from web.ids import aps_doi, arxiv_id
from web.ledger import Candidate
from web.wiley import Wiley

UNPAYWALL = "https://api.unpaywall.org/v2"
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1/paper"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PMC_CLOUD = "https://pmc-oa-opendata.s3.amazonaws.com"
OSTI = "https://www.osti.gov/api/v1/records"
HAL = "https://api.archives-ouvertes.fr/search/"
OPENAIRE = "https://api.openaire.eu/graph/v1/researchProducts"
APS = "https://harvest.aps.org/v2/journals/articles"

# The PDF of one version of an article in PubMed Central's cloud copy: "PMC7902639.1/PMC7902639.1.pdf".
_PMC_PDF = re.compile(r'<Key>((PMC\d+)\.(\d+)/\2\.\3\.pdf)</Key>')
# What OpenAIRE lists beside the copies of a paper: its DOI link, indexes, and sites that are either
# no repository (ResearchGate, Academia) or turn scripts away (the PubMed Central web pages).
_NOT_A_COPY = {"doi.org", "dx.doi.org", "pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
               "europepmc.org", "doaj.org", "www.researchgate.net", "www.academia.edu"}
_MAX_COPIES = 5   # repository pages tried for one paper
_PATIENCE = 3     # lookups in a row a service may fail (too many requests, an error, no answer) before it is left alone


@dataclass
class FetchOption:
    service: str                 # which source offered it: openalex | arxiv | pmc | osti | hal | elsevier | ...
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    license: str = ""
    api: bool = False            # a call to an API under its own terms: robots.txt is not consulted
    landing: bool = False        # a web page that may point to the PDF (citation_pdf_url), not the PDF itself


def _license(text: str) -> str:
    """A Creative Commons licence as the other sources spell it: "CCBYNCND", "CC BY" and "cc by-nc-nd"
    are "cc-by-nc-nd", "cc-by" and "cc-by-nc-nd". Anything else is kept as the service wrote it."""
    text = (text or "").strip()
    code = re.sub(r'[\s-]+', '', text.lower())
    return "-".join(re.findall(r'cc|by|nc|nd|sa', code)) if re.fullmatch(r'cc(?:by|nc|nd|sa)+', code) else text


class Resolver:
    def __init__(self, client: PoliteClient, sources: List[str], contact: str = "",
                 elsevier: Optional[Elsevier] = None, wiley: Optional[Wiley] = None):
        self.client, self.sources, self.contact = client, sources, contact
        self.elsevier, self.wiley = elsevier, wiley
        key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        self._semantic_scholar_key = {"x-api-key": key} if key else None
        self._warned_unpaywall = False
        self._lock = threading.Lock()
        self._failed: Dict[str, int] = {}  # service -> lookups in a row that got no usable answer

    def options(self, candidate: Candidate) -> Iterator[FetchOption]:
        seen = set()
        for service in self.sources:
            for option in getattr(self, f"_{service}")(candidate):
                if option.url not in seen:
                    seen.add(option.url)
                    yield option

    def _ask(self, service: str, url: str, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> Any:
        """What a lookup service answers about a paper, or None: a service that does not know the
        paper offers nothing. One that is out of requests or out of order — still, after the
        client's own retries, and for several papers running — is left alone for the rest of the
        run, so that a long run does not wait on it paper after paper."""
        with self._lock:
            if self._failed.get(service, 0) >= _PATIENCE:
                return None
        try:
            answer = self.client.get_json(url, params=params, headers=headers)
        except HttpError as error:
            if error.status == 429 or error.status >= 500:
                self._strike(service, "it allows no more requests for now" if error.status == 429
                             else f"it keeps answering HTTP {error.status}")
            else:
                logging.debug(f"{service} has nothing: {error}")  # "not found" is an answer
            return None
        except (requests.RequestException, ValueError) as error:
            self._strike(service, "it does not answer" if isinstance(error, requests.RequestException)
                         else "its answers cannot be read")
            return None
        with self._lock:
            self._failed[service] = 0
        return answer

    def _strike(self, service: str, why: str) -> None:
        with self._lock:
            self._failed[service] = self._failed.get(service, 0) + 1
            if self._failed[service] == _PATIENCE:
                logging.warning(f"Not asking {service} for the rest of this run: {why}.")

    # ------------------------------------------------------------------
    # A publisher's own interface for programs
    # ------------------------------------------------------------------
    def _elsevier(self, c: Candidate) -> Iterator[FetchOption]:
        if self.elsevier and c.doi and Elsevier.applies(c):
            yield FetchOption("elsevier", Elsevier.url(c.doi), self.elsevier.headers("application/pdf"),
                              license="Elsevier subscription (text-and-data-mining terms)", api=True)

    def _wiley(self, c: Candidate) -> Iterator[FetchOption]:
        if self.wiley and c.doi and Wiley.applies(c):
            yield FetchOption("wiley", Wiley.url(c.doi), self.wiley.headers(),
                              license=c.license or "Wiley (text-and-data-mining terms)", api=True)

    def _aps(self, c: Candidate) -> Iterator[FetchOption]:
        """The American Physical Society serves its open-access articles to programs here (its web
        pages turn scripts away); any other article is answered with a refusal."""
        if c.doi.startswith("10.1103/"):
            yield FetchOption("aps", f"{APS}/{aps_doi(c.doi)}", {"Accept": "application/pdf"}, license=c.license, api=True)

    # ------------------------------------------------------------------
    # The open links the discovery services know
    # ------------------------------------------------------------------
    def _openalex(self, c: Candidate) -> Iterator[FetchOption]:
        for url in c.oa_urls:
            yield FetchOption("openalex", url, license=c.license)
        if c.landing_url and c.access == "open":
            yield FetchOption("openalex", c.landing_url, license=c.license, landing=True)

    def _unpaywall(self, c: Candidate) -> Iterator[FetchOption]:
        if not c.doi:
            return
        if not self.contact:
            if not self._warned_unpaywall:
                logging.warning("Unpaywall is skipped: it requires a contact email "
                                "(contact_email in the job file, or AUTOMATEXTRACT_EMAIL).")
                self._warned_unpaywall = True
            return
        try:
            data = self.client.get_json(f"{UNPAYWALL}/{c.doi}", params={"email": self.contact})
        except HttpError as error:
            logging.debug(f"Unpaywall has nothing for {c.doi}: {error}")
            return
        for location in [data.get("best_oa_location"), *(data.get("oa_locations") or [])]:
            if not location:
                continue
            if location.get("url_for_pdf"):
                yield FetchOption("unpaywall", location["url_for_pdf"], license=location.get("license") or "")
            elif location.get("url_for_landing_page"):
                yield FetchOption("unpaywall", location["url_for_landing_page"], landing=True,
                                  license=location.get("license") or "")

    def _arxiv(self, c: Candidate) -> Iterator[FetchOption]:
        if c.arxiv_id:
            yield FetchOption("arxiv", f"https://arxiv.org/pdf/{c.arxiv_id}", license="arxiv")

    def _semanticscholar(self, c: Candidate) -> Iterator[FetchOption]:
        """The arXiv version of a journal paper, which Semantic Scholar matches to it, and the
        repository copy it knows of. (The publisher's own link it lists for an open-access paper is
        the one OpenAlex gave already.)"""
        if not c.doi:
            return
        data = self._ask("Semantic Scholar", f"{SEMANTIC_SCHOLAR}/DOI:{c.doi}",
                         {"fields": "externalIds,openAccessPdf"}, self._semantic_scholar_key)
        if not isinstance(data, dict):
            return
        preprint = arxiv_id(str((data.get("externalIds") or {}).get("ArXiv") or ""))
        if preprint:
            yield FetchOption("semanticscholar", f"https://arxiv.org/pdf/{preprint}", license="arxiv")
        copy = data.get("openAccessPdf") or {}
        if copy.get("url") and (copy.get("status") or "").upper() == "GREEN":  # a page or the file itself
            yield FetchOption("semanticscholar", copy["url"], license=_license(copy.get("license") or ""), landing=True)

    # ------------------------------------------------------------------
    # The repositories authors and funders deposit in
    # ------------------------------------------------------------------
    def _pmc(self, c: Candidate) -> Iterator[FetchOption]:
        """PubMed Central's open-access set, from the copy NCBI keeps in the cloud for programs (its
        web pages turn scripts away): the paper's PMC number, then the PDF of its newest version."""
        if not c.doi:
            return
        data = self._ask("Europe PMC", EUROPE_PMC, {"query": f'DOI:"{c.doi}"', "format": "json",
                                                    "resultType": "core", "pageSize": 3})
        for record in ((data or {}).get("resultList") or {}).get("result") or []:
            number = record.get("pmcid") or ""
            if number and (record.get("doi") or "").lower() == c.doi:
                file = self._pmc_file(number)
                if file:
                    yield FetchOption("pmc", f"{PMC_CLOUD}/{file}", license=_license(record.get("license") or ""))
                return

    def _pmc_file(self, number: str) -> str:
        try:
            listing = self.client.get(f"{PMC_CLOUD}/", params={"list-type": "2", "prefix": f"{number}.", "max-keys": "1000"})
        except requests.RequestException:
            return ""
        if listing.status_code != 200:
            return ""
        versions: List[Tuple[int, str]] = [(int(version), key) for key, _, version in _PMC_PDF.findall(listing.text)]
        return max(versions)[1] if versions else ""

    def _osti(self, c: Candidate) -> Iterator[FetchOption]:
        """The accepted manuscript a US Department of Energy grant has its authors deposit."""
        if not c.doi:
            return
        records = self._ask("OSTI", OSTI, {"doi": c.doi})
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict) and (record.get("doi") or "").lower() == c.doi:
                for link in record.get("links") or []:
                    if link.get("rel") == "fulltext" and link.get("href"):
                        yield FetchOption("osti", link["href"], license="public access (US DOE)")

    def _hal(self, c: Candidate) -> Iterator[FetchOption]:
        """The file its authors deposited in HAL, the French open archive."""
        if not c.doi:
            return
        data = self._ask("HAL", HAL, {"q": f'doiId_s:"{c.doi}"', "fl": "doiId_s,fileMain_s,licence_s", "rows": 3, "wt": "json"})
        for document in ((data or {}).get("response") or {}).get("docs") or []:
            if document.get("fileMain_s"):
                yield FetchOption("hal", document["fileMain_s"], license=document.get("licence_s") or "")

    def _openaire(self, c: Candidate) -> Iterator[FetchOption]:
        """The copies in the repositories OpenAIRE harvests (university and national archives,
        Zenodo): each is a page that says where its file is, or the file itself."""
        if not c.doi:
            return
        data = self._ask("OpenAIRE", OPENAIRE, {"pid": c.doi})
        publisher = urlsplit(c.landing_url).netloc.lower()
        copies: List[Tuple[str, str]] = []
        for product in (data or {}).get("results") or []:
            for instance in product.get("instances") or []:
                for url in instance.get("urls") or []:
                    host = urlsplit(url).netloc.lower()
                    if host and host not in _NOT_A_COPY and host != publisher and url not in dict(copies):
                        copies.append((url, instance.get("license") or ""))
        copies.sort(key=lambda copy: ".pdf" not in copy[0].lower())  # a file before a page; otherwise as listed
        for url, license in copies[:_MAX_COPIES]:
            yield FetchOption("openaire", url, license=_license(license), landing=True)
