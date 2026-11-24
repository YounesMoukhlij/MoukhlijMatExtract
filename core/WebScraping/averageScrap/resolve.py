# WebScraping/resolve.py
"""Where a legal copy of a paper may be had. A resolver does not download anything: it lists the
places to try, best first, and the downloader tries them in order until one gives a real PDF.
The order comes from the job (`fetch.sources`); a source that does not apply to a paper — Elsevier's
API for a Nature paper, Unpaywall without a contact email — simply offers nothing.

Three kinds of source:
  - a publisher's own interface for programs: `elsevier` and `wiley` (each needs a free key),
    `aps` (its open-access articles, no key), and `crossref`, the links publishers register there
    for text mining;
  - the open links the discovery services know: `openalex`, `unpaywall`, `arxiv`;
  - the repositories authors and funders deposit in, asked by DOI: `pmc` (PubMed Central's
    open-access set), `osti` (US Department of Energy), `hal` (France), `zenodo` (CERN's repository),
    `datacite` (the copies university and research-centre repositories register with DataCite),
    `openaire` (Europe), `core` (the world's repositories; a free key) — and `semanticscholar` and
    `ads` (a free token), which know the arXiv version of a journal paper;
  - `publisher`: the article's own page at an open-access journal (MDPI, Frontiers, PLOS, Copernicus,
    BMC, …), which declares its PDF for search engines and robots alike.
A source is only asked once the ones before it gave nothing that could be kept, so these lookups
cost nothing for a paper whose first link works."""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from WebScraping.averageScrap.elsevier import Elsevier
from WebScraping.averageScrap.http import HttpError, PoliteClient
from WebScraping.averageScrap.ids import aps_doi, arxiv_id, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.ads import API as ADS
from WebScraping.averageScrap.sources.ads import preprint_of
from WebScraping.averageScrap.sources.common import NOT_A_COPY as _NOT_A_COPY
from WebScraping.averageScrap.sources.common import spell_license as _license
from WebScraping.averageScrap.sources.core import API as CORE
from WebScraping.averageScrap.sources.crossref import API as CROSSREF
from WebScraping.averageScrap.sources.datacite import SAME_WORK as _SAME_WORK
from WebScraping.averageScrap.wiley import Wiley

UNPAYWALL = "https://api.unpaywall.org/v2"
MISSING_EMAIL, REFUSED_EMAIL = "missing", "refused"  # Resolver.email_problem


def email_advice(email: str, problem: str, in_job_file: bool = False) -> str:
    """What to tell the user when Unpaywall — which finds most of the free copies — could not be asked.
    `in_job_file`: the address comes from the job file's contact_email (it wins over API keys…)."""
    why = ("no contact e-mail is set" if problem == MISSING_EMAIL or not email else
           f"it refused the contact e-mail “{email}”: it accepts only a real address of your own "
           "(not example.com, not a typo)")
    where = ("Change contact_email in the job file (configs/sse.yaml, a text file) to your own academic or "
             "professional e-mail — or empty it to use the one of “API keys…”" if in_job_file else
             "Set your own academic or professional e-mail in “API keys…” → “Your contact e-mail”")
    return (f"Unpaywall, the service that finds most of the free copies, was not asked: {why}.\n\n"
            f"{where}, then press “3 · Download” again: the papers not found are tried again.")


NOT_FOUND_ADVICE = (
    "Your e-mail is not the reason: every real address gets the same answer from the open sources, so "
    "another one would not find more. What can help:\n"
    "  • the Elsevier and Wiley keys (and an institutional token) in “API keys…”, for the journals your "
    "university subscribes to;\n"
    "  • running the download from your university's network or VPN, where those subscriptions apply;\n"
    "  • your library, or a request to the authors — put the PDF in WebScraping/papers/ and “4 · Extract” "
    "reads it.")
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1/paper"
# Up to 500 papers in one request (Semantic Scholar's batch endpoint): a download of 1,749 papers asks 4 times, not
# 1,749 — one request a paper ran into its limit ("too many requests", HTTP 429) download after download.
SEMANTIC_SCHOLAR_BATCH = f"{SEMANTIC_SCHOLAR}/batch?fields=externalIds,openAccessPdf"
S2_BATCH_SIZE = 500
SPRINGER_OA = "https://api.springernature.com/openaccess/json"
OPENALEX_WORKS = "https://api.openalex.org/works"
# What ties a paper to the US Department of Energy, in OpenAlex's records: the DOE (OpenAlex funder F4320306084) or one
# of its offices among the funders, or a DOE national laboratory among the authors' institutions.
DOE_FUNDER_IDS = frozenset({"F4320306084"})
_DOE_FUNDER = re.compile(r"\b(u\.?\s?s\.?|united states)\b.*department of energy|^department of energy$|"
                         r"office of science$|basic energy sciences|energy efficiency and renewable energy|"
                         r"advanced research projects agency.energy|arpa-e|vehicle technologies office|"
                         r"national nuclear security administration", re.IGNORECASE)
_DOE_LAB = re.compile(r"argonne|oak ridge national|lawrence berkeley|lawrence livermore|pacific northwest national|"
                      r"sandia national|los alamos|brookhaven|idaho national|national renewable energy laborator|"
                      r"ames (national )?laborator|slac|fermi national|princeton plasma|savannah river|"
                      r"national energy technology laborator|jefferson lab|thomas jefferson national|"
                      r"center for nanophase materials", re.IGNORECASE)


def doe_linked(work: Dict[str, Any]) -> bool:
    """Whether an OpenAlex work (its funders and authorships) is tied to the US Department of Energy."""
    for funder in work.get("funders") or []:
        if str(funder.get("id") or "").rsplit("/", 1)[-1] in DOE_FUNDER_IDS or _DOE_FUNDER.search(funder.get("display_name") or ""):
            return True
    for award in work.get("awards") or []:
        if _DOE_FUNDER.search(award.get("funder_display_name") or ""):
            return True
    for authorship in work.get("authorships") or []:
        for institution in authorship.get("institutions") or []:
            if _DOE_LAB.search(institution.get("display_name") or ""):
                return True
    return False
SPRINGER_PREFIXES = ("10.1007/", "10.1023/", "10.1038/", "10.1057/", "10.1134/", "10.1140/", "10.1186/")
SPRINGER_LINK_PREFIXES = ("10.1007/", "10.1023/", "10.1134/", "10.1140/")  # the journals link.springer.com serves
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PMC_CLOUD = "https://pmc-oa-opendata.s3.amazonaws.com"
OSTI = "https://www.osti.gov/api/v1/records"
HAL = "https://api.archives-ouvertes.fr/search/"
OPENAIRE = "https://api.openaire.eu/graph/v1/researchProducts"
APS = "https://harvest.aps.org/v2/journals/articles"
DOI_HANDLE = "https://doi.org/api/handles"  # where a DOI points, without visiting the page
ZENODO = "https://zenodo.org/api/records"
DATACITE = "https://api.datacite.org/dois"
# Journals whose every article is open access (by DOI prefix): their page is asked for its PDF even
# when no index has said the paper is open.
OPEN_PUBLISHERS = ("10.3390/",       # MDPI
                   "10.3389/",       # Frontiers
                   "10.1371/",       # PLOS
                   "10.1155/",       # Hindawi
                   "10.5194/",       # Copernicus
                   "10.1186/",       # BioMed Central, SpringerOpen
                   "10.7717/",       # PeerJ
                   "10.7554/",       # eLife
                   "10.3762/",       # Beilstein
                   "10.21468/",      # SciPost
                   "10.1038/s41467-", "10.1038/s41598-", "10.1038/s41524-", "10.1038/s41699-",  # Nature Communications, Scientific Reports, npj
                   "10.1107/s2052252",  # IUCrJ
                   "10.1039/d0ra", "10.1039/d1ra", "10.1039/d2ra", "10.1039/d3ra", "10.1039/d4ra", "10.1039/d5ra",  # RSC Advances
                   "10.1039/d0ya", "10.1039/d1ya", "10.1039/d2ya", "10.1039/d3ya", "10.1039/d4ya", "10.1039/d5ya",  # Energy Advances
                   "10.1149/2754-2734",  # ECS Advances
                   )
_OPEN_COLOURS = {"gold", "hybrid", "bronze", "diamond"}  # open at the publisher's site (green is a repository copy)

# The PDF of one version of an article in PubMed Central's cloud copy: "PMC7902639.1/PMC7902639.1.pdf".
_PMC_PDF = re.compile(r'<Key>((PMC\d+)\.(\d+)/\2\.\3\.pdf)</Key>')
# The text-mining links of Elsevier and Wiley need their keys: the `elsevier` and `wiley` sources use them.
_OWN_SOURCE = {"api.elsevier.com", "api.wiley.com"}
_MAX_COPIES = 5   # repository pages tried for one paper
_PATIENCE = 3     # lookups in a row a service may fail (too many requests, an error, no answer) before it is left alone
# How long a service that failed _PATIENCE times running is left alone: then it is asked again. Left alone for the whole
# run, one bad minute of Europe PMC at the start of a 14-hour download kept every paper of the run from it.
_BENCH_SECONDS = 10 * 60
# Services that answer slowly but do answer: the seconds one of their answers may take (the client's 30 s otherwise).
# Europe PMC took 12 to 39 s for one DOI query (November 2026) — past 30 s it was taken for down.
_TIMEOUTS = {"Europe PMC": 90.0}
# A copy CORE serves from core.ac.uk ("https://core.ac.uk/download/669539435.pdf"): the site and CORE's own download
# endpoint turn programs away (a browser challenge), but CORE's API says which repository the copy was harvested from.
_CORE_COPY = re.compile(r"^https?://core\.ac\.uk/(?:download|reader)/(?:pdf/)?(\d+)(?:\.pdf)?/?$", re.IGNORECASE)
CORE_OUTPUTS = "https://api.core.ac.uk/v3/outputs"


# arXiv's own bulk copy of every PDF, kept current in a public Google Cloud bucket (the one the arXiv dataset on
# Kaggle points to, for bulk access): the same files as arxiv.org/pdf, without the 15 s arxiv.org asks between two.
ARXIV_BULK_LIST = "https://storage.googleapis.com/storage/v1/b/arxiv-dataset/o"
ARXIV_BULK_FILES = "https://storage.googleapis.com/arxiv-dataset/"
_ARXIV_LINK = re.compile(r"^https?://(?:www\.|export\.)?arxiv\.org/(?:pdf|abs)/(.+?)(?:v\d+)?(?:\.pdf)?$", re.IGNORECASE)


def arxiv_bulk_prefix(identifier: str) -> str:
    """Where the PDFs of an arXiv paper are in the bulk copy, without the version: "2401.00001" →
    "arxiv/arxiv/pdf/2401/2401.00001v"; "cond-mat/0101001" → "arxiv/cond-mat/pdf/0101/0101001v". "" when the
    identifier is neither form."""
    identifier = re.sub(r"v\d+$", "", (identifier or "").strip())
    new = re.fullmatch(r"(\d{4})\.\d{4,5}", identifier)
    if new:
        return f"arxiv/arxiv/pdf/{new.group(1)}/{identifier}v"
    old = re.fullmatch(r"([a-z-]+)(?:\.[A-Za-z-]+)?/((\d{4})\d{3})", identifier)
    if old:
        return f"arxiv/{old.group(1)}/pdf/{old.group(3)}/{old.group(2)}v"
    return ""


@dataclass
class FetchOption:
    service: str                 # which source offered it: openalex | arxiv | pmc | osti | hal | elsevier | ...
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    license: str = ""
    api: bool = False            # a call to an API under its own terms: robots.txt is not consulted
    landing: bool = False        # a web page that may point to the PDF (citation_pdf_url), not the PDF itself


class Resolver:
    def __init__(self, client: PoliteClient, sources: List[str], contact: str = "",
                 elsevier: Optional[Elsevier] = None, wiley: Optional[Wiley] = None):
        self.client, self.sources, self.contact = client, sources, contact
        self.elsevier, self.wiley = elsevier, wiley
        key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        self._semantic_scholar_key = {"x-api-key": key} if key else None
        # Semantic Scholar's answers asked ahead for a whole download (prefetch): DOI -> its record, None when it does
        # not know the paper. A DOI not in it is asked on its own.
        self._s2_known: Dict[str, Optional[Dict[str, Any]]] = {}
        key = os.environ.get("CORE_API_KEY", "").strip()
        self._core_key = {"Authorization": f"Bearer {key}"} if key else None
        self._springer_oa_key = os.environ.get("SPRINGER_NATURE_OA_KEY", "").strip()
        key = os.environ.get("ADS_API_TOKEN", "").strip()
        self._ads_token = {"Authorization": f"Bearer {key}"} if key else None
        self._warned_unpaywall = False
        # Why Unpaywall could not be asked, if so: no contact e-mail, or one it refuses (a made-up or
        # mistyped address — any real address gets the same answers). The window tells the user.
        self.email_problem = ""
        self._lock = threading.Lock()
        self._failed: Dict[str, int] = {}  # service -> lookups in a row that got no usable answer
        self._benched_at: Dict[str, float] = {}  # service -> when it was left alone (_BENCH_SECONDS)
        self._clock = time.monotonic
        # The services that refused while this thread looked up its paper, and those it did not ask (left alone).
        self._local = threading.local()
        # The services that did not answer at all this run (down, not busy): a few minutes' wait will not bring
        # them back, so the papers only they refused are left for the next run (harvest.worth_waiting).
        self.down: set = set()

    def options(self, candidate: Candidate) -> Iterator[FetchOption]:
        self._local.refused = []
        self._local.skipped = []
        seen = set()
        for service in self.sources:
            for option in getattr(self, f"_{service}")(candidate):
                link = _ARXIV_LINK.match(option.url)
                if link:  # an arXiv PDF: first from arXiv's bulk copy, which asks for no pause between two files
                    bulk = self._arxiv_bulk(link.group(1))
                    if bulk and bulk not in seen:
                        seen.add(bulk)
                        yield FetchOption(option.service, bulk, license="arxiv")
                core = _CORE_COPY.match(option.url)
                if core:  # a copy on core.ac.uk: first from the repository CORE harvested it from
                    for url in self._core_origins(core.group(1), candidate):
                        if url not in seen:
                            seen.add(url)
                            yield FetchOption("repository", url, license=option.license, landing=True)
                if option.url not in seen:
                    seen.add(option.url)
                    yield option

    def _arxiv_bulk(self, identifier: str) -> str:
        """The newest version of an arXiv paper's PDF in arXiv's bulk copy; "" when it is not there (yet)."""
        prefix = arxiv_bulk_prefix(identifier)
        if not prefix:
            return ""
        data = self._ask("arXiv bulk copy", ARXIV_BULK_LIST, {"prefix": prefix, "fields": "items(name)"})
        names = [item.get("name") or "" for item in (data or {}).get("items") or []]
        versions = [(int(m.group(1)), name) for name in names
                    for m in [re.fullmatch(re.escape(prefix) + r"(\d+)\.pdf", name)] if m]
        return ARXIV_BULK_FILES + max(versions)[1] if versions else ""

    def _core_origins(self, identifier: str, c: Candidate) -> List[str]:
        """The files of the repositories CORE harvested its copy number `identifier` from (CORE's API, which needs
        CORE_API_KEY): the deposit itself, served by its repository, not CORE's copy of it. The publisher's page
        and the DOI link are left out — they are tried as such."""
        if not self._core_key:
            return []
        data = self._ask("CORE", f"{CORE_OUTPUTS}/{identifier}", headers=self._core_key)
        if not isinstance(data, dict) or normalize_doi(data.get("doi") or "") not in ("", c.doi):
            return []
        publisher = urlsplit(c.landing_url).netloc.lower()
        origins: List[str] = []
        for url in data.get("sourceFulltextUrls") or []:
            host = urlsplit(url or "").netloc.lower()
            if host and host not in _NOT_A_COPY and host not in ("doi.org", "dx.doi.org", "core.ac.uk", publisher) \
                    and url not in origins:
                origins.append(url)
        return origins[:_MAX_COPIES]

    def skipped(self) -> List[str]:
        """The services not asked about the current paper: left alone for a few minutes after failing again and again
        (_BENCH_SECONDS). The paper was not checked there; it is not held for them either — the next download asks."""
        return list(dict.fromkeys(getattr(self._local, "skipped", [])))

    def refused(self) -> List[str]:
        """The services that refused the current paper's own lookup (too many requests, busy, no answer): the
        paper was not really checked there, and is to be checked again."""
        return list(dict.fromkeys(getattr(self._local, "refused", [])))

    def _note_refused(self, service: str) -> None:
        refused = getattr(self._local, "refused", None)
        if refused is not None:
            refused.append(service)

    def _note_skipped(self, service: str) -> None:
        skipped = getattr(self._local, "skipped", None)
        if skipped is not None:
            skipped.append(service)

    def _ask(self, service: str, url: str, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> Any:
        """What a lookup service answers about a paper, or None: a service that does not know the
        paper offers nothing. One that is out of requests or out of order — still, after the
        client's own retries, and for several papers running — is left alone for _BENCH_SECONDS,
        so that a long run does not wait on it paper after paper; then it is asked again."""
        with self._lock:
            if self._failed.get(service, 0) >= _PATIENCE:
                if self._clock() - self._benched_at.get(service, 0.0) < _BENCH_SECONDS:
                    self._note_skipped(service)  # left alone for now: this paper is not checked there
                    return None
                self._failed[service] = 0  # its time is up: asked again
                logging.info(f"Asking {service} again, after {_BENCH_SECONDS // 60} minutes left alone.")
        try:
            answer = self.client.get_json(url, params=params, headers=headers, timeout=_TIMEOUTS.get(service))
        except HttpError as error:
            if error.status == 429 or error.status >= 500:
                self._note_refused(service)
                self._strike(service, "it allows no more requests for now" if error.status == 429
                             else f"it keeps answering HTTP {error.status}")
            else:
                logging.debug(f"{service} has nothing: {error}")  # "not found" is an answer
            return None
        except requests.RequestException:
            # No answer even after the client's own retries (minutes of waiting): the service is
            # down, and asking it again for each paper would cost those minutes paper after paper.
            self._note_refused(service)
            with self._lock:
                self.down.add(service)
            self._strike(service, "it does not answer", at_once=True)
            return None
        except ValueError:
            self._strike(service, "its answers cannot be read")
            return None
        with self._lock:
            self._failed[service] = 0
            self.down.discard(service)  # it answers again
        return answer

    def _strike(self, service: str, why: str, at_once: bool = False) -> None:
        with self._lock:
            before = self._failed.get(service, 0)
            if before >= _PATIENCE:
                return
            self._failed[service] = _PATIENCE if at_once else before + 1
            if self._failed[service] == _PATIENCE:
                self._benched_at[service] = self._clock()
                logging.warning(f"Not asking {service} for the next {_BENCH_SECONDS // 60} minutes: {why}. The papers "
                                "looked up meanwhile are filed with what the other sources answered, and the next "
                                "download asks it again.")

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

    def _springeroa(self, c: Candidate) -> Iterator[FetchOption]:
        """Springer Nature's Open Access API, asked by DOI, knows the paper only when it is open access (it answers
        404 otherwise): then its PDF, from link.springer.com, whose robots.txt allows /content/."""
        if not (self._springer_oa_key and c.doi):
            return
        publisher = c.publisher.lower()
        if not (c.doi.startswith(SPRINGER_PREFIXES) or "springer" in publisher or "nature" in publisher
                or "biomed central" in publisher):
            return
        data = self._ask("Springer Nature", SPRINGER_OA, {"q": f"doi:{c.doi}", "api_key": self._springer_oa_key})
        records = (data or {}).get("records") or []
        if any(normalize_doi(record.get("doi") or "") == c.doi for record in records):
            licence = c.license or "open access (Springer Nature)"
            if c.doi.startswith(SPRINGER_LINK_PREFIXES):  # hosted on link.springer.com: the PDF itself
                yield FetchOption("springeroa", f"https://link.springer.com/content/pdf/{c.doi}.pdf", license=licence)
            else:  # Nature, BMC: their own sites, whose article page names its PDF
                yield FetchOption("springeroa", f"https://doi.org/{c.doi}", license=licence, landing=True)

    def _aps(self, c: Candidate) -> Iterator[FetchOption]:
        """The American Physical Society serves its open-access articles to programs here (its web
        pages turn scripts away); any other article is answered with a refusal."""
        if c.doi.startswith("10.1103/"):
            yield FetchOption("aps", f"{APS}/{aps_doi(c.doi)}", {"Accept": "application/pdf"}, license=c.license, api=True)

    def _crossref(self, c: Candidate) -> Iterator[FetchOption]:
        """The links a publisher registered with Crossref for text mining: its PDF, or a page that
        points to it. They are followed like any page — its robots.txt is obeyed; a subscriber's
        link answers anyone else with a refusal."""
        if not c.doi:
            return
        data = self._ask("Crossref", f"{CROSSREF}/{c.doi}", {"mailto": self.contact} if self.contact else None)
        message = (data or {}).get("message") or {}
        license = next((_license(entry.get("URL") or "") for entry in message.get("license") or []
                        if _license(entry.get("URL") or "").startswith("cc")), "") or c.license
        for link in message.get("link") or []:
            url, kind = link.get("URL") or "", (link.get("content-type") or "").lower()
            if link.get("intended-application") != "text-mining" or not url or urlsplit(url).netloc.lower() in _OWN_SOURCE \
                    or "xml" in kind or "plain" in kind:
                continue
            yield FetchOption("crossref", url, license=license, landing=kind != "application/pdf")

    # ------------------------------------------------------------------
    # The open links the discovery services know
    # ------------------------------------------------------------------
    def _openalex(self, c: Candidate) -> Iterator[FetchOption]:
        """The links the search records carry: the files, then the repository pages that hold a copy
        (offered as "repository"), then the paper's own page when it is open."""
        for url in c.oa_urls:
            yield FetchOption("openalex", url, license=c.license)
        for url in c.copy_pages[:_MAX_COPIES]:
            yield FetchOption("repository", url, license=c.license, landing=True)
        if c.landing_url and c.access == "open":
            yield FetchOption("openalex", c.landing_url, license=c.license, landing=True)

    def _unpaywall(self, c: Candidate) -> Iterator[FetchOption]:
        if not c.doi:
            return
        if not self.contact:
            if not self._warned_unpaywall:
                logging.warning("Unpaywall is skipped: it requires a contact email "
                                "(contact_email in the job file, or MME_EMAIL).")
                self._warned_unpaywall = True
                self.email_problem = MISSING_EMAIL
            return
        if self.email_problem:
            return  # it refused the address: asking again for every paper would only be refused again
        try:
            data = self.client.get_json(f"{UNPAYWALL}/{c.doi}", params={"email": self.contact})
        except HttpError as error:
            if error.status == 422:  # Unpaywall's answer to an address that is not a real one of your own
                with self._lock:
                    first, self.email_problem = not self.email_problem, REFUSED_EMAIL
                if first:
                    logging.warning(f"Unpaywall refused the contact e-mail “{self.contact}”: it accepts only a real "
                                    "address of your own (not example.com, not a typo). Set your own academic or "
                                    "professional address (API keys…, or MME_EMAIL), then download again. Unpaywall "
                                    "is skipped for the rest of this run.")
                return
            if error.status == 429 or error.status >= 500:
                self._note_refused("Unpaywall")
            logging.debug(f"Unpaywall has nothing for {c.doi}: {error}")
            return
        except requests.RequestException:
            self._note_refused("Unpaywall")
            return
        for location in [data.get("best_oa_location"), *(data.get("oa_locations") or [])]:
            if not location:
                continue
            if location.get("url_for_pdf"):
                yield FetchOption("unpaywall", location["url_for_pdf"], license=location.get("license") or "")
            elif location.get("url_for_landing_page"):
                yield FetchOption("unpaywall", location["url_for_landing_page"], landing=True,
                                  license=location.get("license") or "")

    def _publisher(self, c: Candidate) -> Iterator[FetchOption]:
        """The article's page at its publisher, when the article is open there (an open-access journal,
        or an index that says so): the page declares its PDF (citation_pdf_url), which is followed once.
        Where the DOI points is asked of the DOI system first, so that the publisher's own robots.txt
        is the one consulted."""
        if not c.doi or not (c.doi.startswith(OPEN_PUBLISHERS) or c.oa_status in _OPEN_COLOURS
                             or c.license.startswith("cc")):
            return
        data = self._ask("doi.org", f"{DOI_HANDLE}/{c.doi}", {"type": "URL"})
        page = next((v.get("data", {}).get("value") for v in (data or {}).get("values") or []
                     if v.get("type") == "URL"), "")
        if page and urlsplit(page).netloc.lower() not in _OWN_SOURCE:
            yield FetchOption("publisher", page, license=c.license, landing=True)

    def _zenodo(self, c: Candidate) -> Iterator[FetchOption]:
        """The copy of a journal article its authors deposited in Zenodo under the article's DOI."""
        if not c.doi:
            return
        data = self._ask("Zenodo", ZENODO, {"q": f'doi:"{c.doi}"', "size": 5})
        for record in ((data or {}).get("hits") or {}).get("hits") or []:
            meta = record.get("metadata") or {}
            if normalize_doi(record.get("doi") or meta.get("doi") or "") != c.doi or meta.get("access_right") != "open":
                continue
            for file in record.get("files") or []:
                link = (file.get("links") or {}).get("self") or ""
                if (file.get("key") or "").lower().endswith(".pdf") and link:
                    yield FetchOption("zenodo", link, license=_license((meta.get("license") or {}).get("id") or ""))

    def _datacite(self, c: Candidate) -> Iterator[FetchOption]:
        """The copies university and research-centre repositories registered with DataCite as another
        form of the article (its accepted manuscript, its preprint): the repository's page of each."""
        if not c.doi:
            return
        data = self._ask("DataCite", DATACITE, {"query": f'relatedIdentifiers.relatedIdentifier:"{c.doi}"',
                                                "page[size]": 10})
        copies: List[str] = []
        for record in (data or {}).get("data") or []:
            attributes = record.get("attributes") or {}
            if ((attributes.get("types") or {}).get("resourceTypeGeneral") or "") == "Dataset":
                continue
            related = {normalize_doi(r.get("relatedIdentifier") or "") for r in attributes.get("relatedIdentifiers") or []
                       if r.get("relationType") in _SAME_WORK}
            for url in [*(attributes.get("contentUrl") or []), attributes.get("url") or ""]:
                if c.doi in related and url and url not in copies:
                    copies.append(url)
        for url in copies[:_MAX_COPIES]:
            yield FetchOption("datacite", url, landing=not url.lower().endswith(".pdf"))

    def _arxiv(self, c: Candidate) -> Iterator[FetchOption]:
        if c.arxiv_id:
            yield FetchOption("arxiv", f"https://arxiv.org/pdf/{c.arxiv_id}", license="arxiv")

    def prefetch(self, candidates: List[Candidate]) -> int:
        """Semantic Scholar asked about the DOIs of these papers ahead, S2_BATCH_SIZE in one request (its batch
        endpoint), instead of one request a paper during the download. Returns how many DOIs it answered for. A batch
        it refuses or that fails ends the prefetch: the papers left are asked one by one, as before."""
        if "semanticscholar" not in self.sources:
            return 0
        dois = list(dict.fromkeys(c.doi for c in candidates if c.doi and c.doi not in self._s2_known))
        answered = 0
        for start in range(0, len(dois), S2_BATCH_SIZE):
            chunk = dois[start:start + S2_BATCH_SIZE]
            try:
                records = self.client.post_json(SEMANTIC_SCHOLAR_BATCH, {"ids": [f"DOI:{doi}" for doi in chunk]},
                                                headers=self._semantic_scholar_key)
            except (HttpError, requests.RequestException, ValueError) as error:
                logging.info(f"Semantic Scholar: the batch of {len(chunk)} DOIs was not answered ({error}); the papers "
                             "left are asked one by one.")
                break
            if not isinstance(records, list) or len(records) != len(chunk):
                logging.info("Semantic Scholar: its batch answer could not be read; the papers left are asked one by one.")
                break
            with self._lock:
                for doi, record in zip(chunk, records):
                    self._s2_known[doi] = record if isinstance(record, dict) else None
            answered += len(chunk)
        if answered:
            logging.info(f"Semantic Scholar: {answered:,} DOI(s) asked in {-(-answered // S2_BATCH_SIZE)} request(s).")
        return answered

    def _semanticscholar(self, c: Candidate) -> Iterator[FetchOption]:
        """The arXiv version of a journal paper, which Semantic Scholar matches to it, and the
        repository copy it knows of. (The publisher's own link it lists for an open-access paper is
        the one OpenAlex gave already.) Its answer asked ahead (prefetch) when there is one."""
        if not c.doi:
            return
        if c.doi in self._s2_known:
            data = self._s2_known[c.doi]
        else:
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

    def _ads(self, c: Candidate) -> Iterator[FetchOption]:
        """The arXiv version NASA ADS matched to a journal paper, and the scan of an older article it
        keeps itself. Needs ADS_API_TOKEN."""
        if not (self._ads_token and c.doi):
            return
        data = self._ask("NASA ADS", ADS, {"q": f'doi:"{c.doi}"', "fl": "bibcode,identifier,esources", "rows": 1},
                         self._ads_token)
        for doc in ((data or {}).get("response") or {}).get("docs") or []:
            preprint = preprint_of(doc)
            if preprint:
                yield FetchOption("ads", f"https://arxiv.org/pdf/{preprint}", license="arxiv")
            if "ADS_PDF" in (doc.get("esources") or []) and doc.get("bibcode"):
                yield FetchOption("ads", f"https://ui.adsabs.harvard.edu/link_gateway/{doc['bibcode']}/ADS_PDF")

    # ------------------------------------------------------------------
    # The repositories authors and funders deposit in
    # ------------------------------------------------------------------
    def _pmc(self, c: Candidate) -> Iterator[FetchOption]:
        """PubMed Central's open-access set, from the copy NCBI keeps in the cloud for programs (its
        web pages turn scripts away): the paper's PMC number, then the PDF of its newest version."""
        if not c.doi:
            return
        # "lite" (the PMC number and the DOI are all this needs): several times quicker than "core".
        data = self._ask("Europe PMC", EUROPE_PMC, {"query": f'DOI:"{c.doi}"', "format": "json",
                                                    "resultType": "lite", "pageSize": 3})
        for record in ((data or {}).get("resultList") or {}).get("result") or []:
            number = record.get("pmcid") or ""
            if number and (record.get("doi") or "").lower() == c.doi:
                file = self._pmc_file(number)
                if file:
                    yield FetchOption("pmc", f"{PMC_CLOUD}/{file}",
                                      license=_license(record.get("license") or "") or c.license)
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
        """The accepted manuscript a US Department of Energy grant has its authors deposit. Asked only of the papers
        OpenAlex links to the DOE (a DOE funder, or an author of a DOE national laboratory): OSTI holds no other, and
        asking it of every paper ran into its limits — hundreds of papers then waited on it for nothing."""
        if not c.doi or not self._doe_linked(c):
            return
        records = self._ask("OSTI", OSTI, {"doi": c.doi})
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict) and (record.get("doi") or "").lower() == c.doi:
                for link in record.get("links") or []:
                    if link.get("rel") == "fulltext" and link.get("href"):
                        yield FetchOption("osti", link["href"], license="public access (US DOE)")

    def _doe_linked(self, c: Candidate) -> bool:
        """Whether OpenAlex links the paper to the US Department of Energy. When OpenAlex does not know the paper or
        does not answer, the answer is yes: OSTI is asked rather than a DOE paper missed."""
        cache = self.__dict__.setdefault("_doe_cache", {})
        if c.doi in cache:
            return cache[c.doi]
        params: Dict[str, Any] = {"select": "funders,authorships"}
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if key:
            params["api_key"] = key
        if self.contact:
            params["mailto"] = self.contact
        try:  # not _ask: a busy OpenAlex must not make the paper wait; OSTI is then simply asked
            work = self.client.get_json(f"{OPENALEX_WORKS}/doi:{c.doi}", params=params)
        except Exception:
            work = None
        if not isinstance(work, dict) or not work.get("id") and not work.get("funders") and not work.get("authorships"):
            linked = True
        else:
            linked = doe_linked(work)
        cache[c.doi] = linked
        if not linked:
            logging.debug(f"OSTI not asked for {c.doi}: OpenAlex links it to no DOE funder or laboratory")
        return linked

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

    def _core(self, c: Candidate) -> Iterator[FetchOption]:
        """The copies CORE holds of a paper, harvested from the repositories it was deposited in (a
        file, or the page of the repository that has it). Needs CORE_API_KEY."""
        if not (self._core_key and c.doi):
            return
        data = self._ask("CORE", CORE, {"q": f'doi:"{c.doi}"', "limit": 5}, self._core_key)
        copies: List[str] = []
        for work in (data or {}).get("results") or []:
            url = work.get("downloadUrl") or ""
            if normalize_doi(work.get("doi") or "") == c.doi and url and url not in copies \
                    and urlsplit(url).netloc.lower() not in _NOT_A_COPY:
                copies.append(url)
        for url in copies[:_MAX_COPIES]:
            yield FetchOption("core", url, landing=True)
