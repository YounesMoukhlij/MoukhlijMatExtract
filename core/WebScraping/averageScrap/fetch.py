# WebScraping/fetch.py
"""Getting the file. For each approved paper the downloader walks the resolver's options, best
first, and keeps the first one that turns out to be the paper: a real PDF (not the paywall page a
server sometimes sends under a .pdf name) whose first pages carry the paper's title (not a
supplement, a cover sheet or another article). A refusal (401/403) or a robots.txt "Disallow" just
means "next option" — nothing here tries to get around one."""

import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import requests

from LocalExtraction import runcontrol

from WebScraping.averageScrap.http import Disallowed, PoliteClient
from WebScraping.averageScrap.ids import file_stem
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, FAILED, Candidate
from WebScraping.averageScrap.resolve import FetchOption, Resolver
from WebScraping.averageScrap.sidecar import sidecar_path, write_sidecar

# Fraction of a title's words that must be found in the first pages for the file to count as the paper.
_MIN_TITLE_MATCH = 0.5
# Below this much text in the first pages the title cannot be judged (a scan): the file is accepted.
_MIN_TEXT_TO_JUDGE = 800
_STOPWORDS = {"with", "from", "that", "this", "using", "based", "into", "their", "toward", "towards", "through",
              "under", "over", "between", "after", "within", "study", "analysis", "approach", "new"}
# A publisher's API that answers "too many requests" has used up an allowance that will not come
# back in a few seconds: the source is switched off for the rest of the run.
DOWNLOAD_SECONDS = 300  # a PDF not in whole after this long is given up (a site sending a byte at a time)
# A try that failed for now, not for good: too many requests, a busy server, no answer, a crawl.
_NOT_NOW = re.compile(r'HTTP (?:408|425|429|5\d\d)\b|network error|too slow')
# What a sidecar says of a copy whose source is not known: no legal source is on record for it.
UNRECORDED_SOURCES = {"", "already in the folder", "a file of this computer"}
_ALLOWANCE = {"elsevier": "its weekly quota is used up", "wiley": "it allows no more requests for now"}
# Publisher APIs that answer a request the subscription does not cover with the article's first page only.
_FIRST_PAGE_WHEN_NOT_ENTITLED = {"elsevier"}
# What a publisher's refusal (403) means, said where the paper's failure is shown.
NOT_ENTITLED_MARK = "not entitled"
_NOT_ENTITLED = {
    "elsevier": f"{NOT_ENTITLED_MARK}: closed Elsevier papers download only on your university's network (campus or "
                "VPN) or with ELSEVIER_INSTTOKEN, and only if the university subscribes to the journal",
    "wiley": f"{NOT_ENTITLED_MARK}: closed Wiley papers download only on your university's network (campus or VPN), "
             "and only if the university subscribes to the journal"}
# A site that refuses this many downloads in a row (HTTP 403) refuses programs, not one paper: it is not asked
# again for the rest of the run. Asking it on for every paper of the publisher would only waste the run and get
# the network flagged. A 403 is an answer: nothing tries to get around it, the paper goes on the list of
# papers to download by hand (HAND_LIST).
BLOCK_AFTER = 3
SITE_BLOCKED_MARK = "refuses automated downloads"
# A site whose next request may not go for this many seconds (it asked to slow down, or its robots.txt asks for a
# crawl delay) is not waited for: the paper's other sources are asked meanwhile, and the paper comes back to that site
# at the end of the batch, when it has had its rest.
DEFER_SECONDS = 10.0
# Addresses that only send a request on to the publisher (a DOI link): the site that refused is the one they led to.
_REDIRECTORS = {"doi.org", "dx.doi.org", "hdl.handle.net", "linkinghub.elsevier.com"}


class SiteBlocks:
    """The sites that refused downloads (HTTP 403) several times in a row during this run, shared by the
    worker threads and by the watcher's rounds. Any download a site lets through clears its count."""

    def __init__(self, after: int = BLOCK_AFTER):
        self.after = after
        self._refusals = {}
        self._blocked = set()
        self._lock = threading.Lock()

    def refused(self, host: str) -> None:
        with self._lock:
            if host in self._blocked:
                return
            self._refusals[host] = self._refusals.get(host, 0) + 1
            if self._refusals[host] < self.after:
                return
            self._blocked.add(host)
        logging.warning(f"{host} refused {self.after} downloads in a row (HTTP 403): it {SITE_BLOCKED_MARK}, so it is "
                        "not asked again in this run. Its papers are tried at the other sources, and those found nowhere "
                        f"else go on the list to download by hand ({HAND_LIST}).")

    def answered(self, host: str) -> None:
        with self._lock:
            self._refusals.pop(host, None)

    def blocked(self, host: str) -> bool:
        with self._lock:
            return host in self._blocked

    def hosts(self) -> List[str]:
        with self._lock:
            return sorted(self._blocked)


# The papers sites refused with HTTP 403, to open in a browser and save into the papers folder (harvest.py).
HAND_LIST = "to_download_by_hand.csv"


@dataclass
class PdfCheck:
    ok: bool
    reason: str = ""
    pages: int = 0
    title_match: float = 1.0


def _fold(text: str) -> str:
    """Lower case, ligatures and accents folded, words broken by a line-end hyphen joined."""
    text = unicodedata.normalize("NFKC", text).replace("­", "")
    return re.sub(r'-\s*\n\s*|-\s{1,2}(?=[a-z])', '', text.lower())


def _title_overlap(title: str, text: str) -> float:
    words = [w for w in re.findall(r'[a-z]{4,}', _fold(title)) if w not in _STOPWORDS]
    if len(words) < 3:
        return 1.0  # too little to judge by
    body = _fold(text)
    return sum(1 for w in words if w in body) / len(words)


def check_pdf(data: bytes, title: str = "") -> PdfCheck:
    """Is this the paper? A PDF that opens, is long enough to be an article, and (when the title
    is known and the text can be read) shows most of the title's words in its first pages."""
    if b"%PDF-" not in data[:1024]:
        return PdfCheck(False, "not a PDF (a web page, most likely)")
    try:
        import pymupdf  # loaded with the first PDF to check, not when the web window opens
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        return PdfCheck(False, f"the PDF cannot be opened ({type(error).__name__})")
    try:
        pages = document.page_count
        text = " ".join(document[i].get_text("text") for i in range(min(3, pages)))
    except Exception as error:
        return PdfCheck(False, f"the PDF cannot be read ({type(error).__name__})")
    finally:
        document.close()
    if pages < 2 and len(text) < 1500:
        return PdfCheck(False, "too short to be an article", pages)
    ratio = _title_overlap(title, text) if title and len(text) >= _MIN_TEXT_TO_JUDGE else 1.0
    if ratio < _MIN_TITLE_MATCH:
        return PdfCheck(False, f"its first pages do not carry the title ({ratio:.0%} of its words): another document?",
                        pages, ratio)
    return PdfCheck(True, "", pages, ratio)


class _PdfLinkFinder(HTMLParser):
    """The PDF link a publisher or repository page declares for search engines (Highwire tags)."""

    def __init__(self):
        super().__init__()
        self.url = ""

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta" and a.get("name", "").lower() == "citation_pdf_url" and a.get("content"):
            self.url = self.url or a["content"]
        elif tag == "link" and a.get("type", "").lower() == "application/pdf" and a.get("href") \
                and "alternate" in a.get("rel", "").lower():
            self.url = self.url or a["href"]


@dataclass
class Outcome:
    key: str
    status: str                 # downloaded | closed | failed
    file: str = ""
    sha256: str = ""
    service: str = ""
    url: str = ""
    license: str = ""
    pages: int = 0
    title_match: float = 1.0
    error: str = ""
    # The services and sites that refused (too many requests, busy, no answer) while this paper was
    # looked for: it was not really checked, and the watcher checks it again later.
    refused: List[str] = field(default_factory=list)
    # The lookups not asked about this paper, being left alone for a few minutes after failing again and again: the
    # paper was not checked there, but it is not held for them — filed with what the others answered, asked next run.
    skipped: List[str] = field(default_factory=list)
    # The links left for later, their site wanting time (DEFER_SECONDS, or a 429): the paper is not filed yet — it is
    # taken up again at the end of the batch (Downloader.fetch with `resume`), on these links only.
    later: List[FetchOption] = field(default_factory=list)
    # What the first pass found, for the second: why each link it tried failed, the lookups that refused, and how many
    # links it skipped for a blocked site.
    tried: List[str] = field(default_factory=list)
    lookups_refused: List[str] = field(default_factory=list)
    blocked_skips: int = 0
    # Every site that had this paper was skipped, being blocked for the run (SiteBlocks): the paper itself
    # was not asked for, so the try does not count against it.
    not_asked: bool = False


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


class Downloader:
    def __init__(self, folder: str, client: PoliteClient, resolver: Resolver, max_mb: int = 60,
                 blocks: Optional[SiteBlocks] = None):
        self.folder, self.client, self.resolver = folder, client, resolver
        self.max_bytes = max_mb * 1024 * 1024
        self._disabled = set()
        self._lock = threading.Lock()
        self.blocks = blocks if blocks is not None else SiteBlocks()

    def _disable(self, service: str, reason: str) -> None:
        with self._lock:
            if service not in self._disabled:
                self._disabled.add(service)
                logging.warning(f"Not using {service} for the rest of this run: {reason}.")

    # ------------------------------------------------------------------
    # One option
    # ------------------------------------------------------------------
    def _read(self, response: requests.Response) -> Tuple[Optional[bytes], str]:
        """The body of a download, or (None, why not). It is read as it comes — whatever has arrived,
        not a full block — so that a site sending a few bytes at a time cannot hold the step: Pause and
        Stop are answered between two pieces, and a download has DOWNLOAD_SECONDS at most."""
        data = bytearray()
        started = time.monotonic()
        raw = getattr(response, "raw", None)
        if hasattr(raw, "read1"):
            read = lambda: raw.read1(65536, decode_content=True)  # noqa: E731
        else:  # an older urllib3, or an answer without a connection behind it: block by block
            pieces = response.iter_content(65536)
            read = lambda: next(pieces, b"")  # noqa: E731
        while True:
            runcontrol.check()  # Pause holds a download here; Stop ends it
            try:
                chunk = read()
            except Exception as error:  # urllib3's own errors, as requests would have raised them
                raise requests.ConnectionError(error) from error
            if not chunk:
                return bytes(data), ""
            data.extend(chunk)
            if len(data) > self.max_bytes:
                return None, f"larger than {self.max_bytes // (1024 * 1024)} MB"
            if time.monotonic() - started > DOWNLOAD_SECONDS:
                return None, f"too slow: not in whole after {DOWNLOAD_SECONDS // 60} minutes"

    def _attempt(self, option: FetchOption, patient: bool = True) -> Tuple[Optional[bytes], str]:
        """The bytes an option gives, or (None, why not). Not `patient`, a "too many requests" (429) comes straight
        back, instead of being waited out: the link is left for later and the other sources are asked meanwhile."""
        try:
            response = self.client.get(option.url, headers=option.headers or None, stream=True, api=option.api,
                                       no_retry={429} if option.service in _ALLOWANCE or not patient else ())
        except Disallowed:
            return None, "robots.txt does not allow it"
        except requests.RequestException as error:
            return None, f"network error ({type(error).__name__})"
        try:
            status = response.status_code
            if option.service in _ALLOWANCE and status == 429:
                self._disable(option.service, _ALLOWANCE[option.service])
            if option.service == "elsevier" and status == 401:
                self._disable("elsevier", "the API key was refused (is ELSEVIER_API_KEY right?)")
            if status == 403 and option.service in _NOT_ENTITLED:
                return None, f"HTTP 403 ({_NOT_ENTITLED[option.service]})"
            if option.service not in _NOT_ENTITLED:  # a publisher API's 403 is about the subscription, not programs
                # The site that answered: where the request ended, after the redirects of a DOI link.
                answered_by = _host(getattr(response, "url", "") or option.url)
                if answered_by not in _REDIRECTORS:
                    if status == 403:
                        self.blocks.refused(answered_by)
                    elif status == 200:
                        self.blocks.answered(answered_by)
            if status != 200:
                return None, f"HTTP {status}"
            kind = (response.headers.get("Content-Type") or "").lower()
            try:
                body, why = self._read(response)
            except requests.RequestException as error:  # the connection dropped during the download
                return None, f"network error ({type(error).__name__})"
            if body is None:
                return None, why
            if "xml" in kind or "json" in kind:
                return None, (f"answered with {kind.split(';')[0]}, not a PDF (a reader for it is not built yet)"
                              if option.service == "elsevier" else f"answered with {kind.split(';')[0]}, not a PDF")
            if "html" in kind or body[:20].lstrip().lower().startswith((b"<!doctype", b"<html")):
                if option.landing:  # a landing page: follow the PDF link it declares, once
                    finder = _PdfLinkFinder()
                    finder.feed(body.decode("utf-8", errors="replace"))
                    if finder.url:
                        return self._attempt(FetchOption(option.service, urljoin(option.url, finder.url),
                                                         license=option.license), patient)
                    return None, "a web page that links to no PDF"
                return None, "a web page, not a PDF"
            return body, ""
        finally:
            response.close()

    # ------------------------------------------------------------------
    # One paper
    # ------------------------------------------------------------------
    def _on_disk(self, candidate: Candidate) -> Optional[str]:
        """The PDF of this paper already in the folder — saved by an earlier run, or put there under
        its DOI ("/" made "_", as earlier versions named them). None if there is none."""
        names = [f"{file_stem(candidate.key)}.pdf"]
        if candidate.doi:
            names.append(f"{candidate.doi.replace('/', '_')}.pdf")
        for name in dict.fromkeys(names):
            path = os.path.join(self.folder, name)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
        return None

    @staticmethod
    def _legal_record(path: str) -> bool:
        """Whether a PDF in the folder came with the record of the legal source it was downloaded from
        (its sidecar names one). A PDF without one — put there by hand, or by an earlier tool — is not
        taken as fetched: a legal copy is looked for, and replaces it when one is found."""
        try:
            with open(sidecar_path(path), encoding="utf-8") as f:
                service = str(json.load(f).get("source_service") or "").strip()
        except (OSError, ValueError, AttributeError):
            return False
        return service not in UNRECORDED_SOURCES

    def fetch(self, candidate: Candidate, resume: Optional[Outcome] = None) -> Outcome:
        """The paper's PDF from the first of its options that gives it. A site that wants time (DEFER_SECONDS, or
        a "too many requests") is not waited for: its link is left for later and the other options are tried; when
        none gave the paper, the outcome carries the links left (`later`) and the paper is not filed yet. `resume`
        (that outcome) takes the paper up again on those links only, waiting for each site's turn."""
        if resume is not None:
            return self._walk(candidate, iter(resume.later), patient=True, tried=list(resume.tried), offered=True,
                              skipped=resume.blocked_skips, earlier=resume)
        existing = self._on_disk(candidate)
        if existing and self._legal_record(existing):
            with open(existing, "rb") as f:
                data = f.read()
            check = check_pdf(data, candidate.title)
            if check.ok:
                logging.info(f"Already fetched: {candidate.key} ({os.path.basename(existing)} is in the folder) "
                             "— download skipped.")
                from LocalExtraction.fileurls import file_url  # a link right on every system
                return self._save(candidate, FetchOption("already in the folder", file_url(existing)), data,
                                  check, path=existing)
        return self._walk(candidate, self.resolver.options(candidate), patient=False, tried=[], offered=False, skipped=0)

    def _walk(self, candidate: Candidate, options, patient: bool, tried: List[str], offered: bool, skipped: int,
              earlier: Optional[Outcome] = None) -> Outcome:
        later: List[FetchOption] = []
        for option in options:
            if option.service in self._disabled:
                continue
            offered = True
            host = _host(option.url)
            if option.service not in _NOT_ENTITLED and self.blocks.blocked(host):
                tried.append(f"{option.service}: {host} {SITE_BLOCKED_MARK} (HTTP 403), skipped this run")
                skipped += 1
                continue
            if not patient and option.service not in _ALLOWANCE and self.client.wait_for(host) > DEFER_SECONDS:
                later.append(option)  # its site wants time: the other options first
                continue
            data, reason = self._attempt(option, patient)
            if data is None:
                if reason == "HTTP 429" and not patient and option.service not in _ALLOWANCE:
                    later.append(option)  # "too many requests": the other options first, this one again at the end
                    continue
                tried.append(f"{option.service}: {reason}")
                continue
            check = check_pdf(data, candidate.title)
            if check.ok and option.service in _FIRST_PAGE_WHEN_NOT_ENTITLED and check.pages == 1:
                # What a publisher's API sends a reader its subscription does not cover: the first page.
                check = PdfCheck(False, f"only the first page ({NOT_ENTITLED_MARK}: "
                                        + ("the institutional token is set, but your university's subscription does "
                                           "not cover this journal — your library can say which journals it has)"
                                           if os.environ.get("ELSEVIER_INSTTOKEN", "").strip() else
                                           "the university's network or ELSEVIER_INSTTOKEN is needed, and a "
                                           "subscription to the journal)"), 1)
            if not check.ok:
                tried.append(f"{option.service}: {check.reason}")
                continue
            return self._save(candidate, option, data, check)
        lookups_refused = earlier.lookups_refused if earlier is not None else self.resolver.refused()
        lookups_skipped = earlier.skipped if earlier is not None else self.resolver.skipped()
        if later:  # not filed yet: taken up again at the end of the batch, on these links
            hosts = ", ".join(dict.fromkeys(_host(option.url) for option in later))
            return Outcome(candidate.key, FAILED, error=f"left for later: {hosts} asked for time", later=later,
                           tried=tried, lookups_refused=lookups_refused, skipped=lookups_skipped, blocked_skips=skipped)
        refused = list(dict.fromkeys([*lookups_refused, *(t.split(":", 1)[0] for t in tried if _NOT_NOW.search(t))]))
        if refused:  # not an answer: a lookup or a site said "not now"
            return Outcome(candidate.key, FAILED, error="; ".join(tried)[:500] or "not checked: " + ", ".join(refused),
                           refused=refused, skipped=lookups_skipped)
        if not offered:
            return Outcome(candidate.key, CLOSED, error="no legal copy found: needs a manual PDF", skipped=lookups_skipped)
        return Outcome(candidate.key, FAILED, error="; ".join(tried)[:500], not_asked=skipped == len(tried) > 0,
                       skipped=lookups_skipped)

    def _save(self, candidate: Candidate, option: FetchOption, data: bytes, check: PdfCheck,
              path: Optional[str] = None) -> Outcome:
        return save_copy(self.folder, candidate, option, data, check, path)


def save_copy(folder: str, candidate: Candidate, option: FetchOption, data: bytes, check: PdfCheck,
              path: Optional[str] = None) -> Outcome:
    """Saves the PDF of a paper in `folder` under its DOI-based name (unless `path`: it is there already),
    with its sidecar: where it came from (`option`), when, and its checksum."""
    os.makedirs(folder, exist_ok=True)
    path_given = path is not None
    if path is None:
        path = os.path.join(folder, f"{file_stem(candidate.key)}.pdf")
        part = path + ".part"
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)  # the PDF appears whole or not at all
    sha256 = hashlib.sha256(data).hexdigest()
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # A file already in the folder keeps its own record of where it came from, when it has one.
    if not (path_given and os.path.exists(sidecar_path(path))):
        write_sidecar(path, {
            "key": candidate.key, "arxiv_id": candidate.arxiv_id,
            # A preprint without a journal DOI has the one arXiv gives it.
            "doi": candidate.doi or (f"10.48550/arXiv.{candidate.arxiv_id}" if candidate.arxiv_id else ""),
            "openalex_id": candidate.openalex_id, "title": candidate.title, "authors": candidate.authors,
            "journal": candidate.journal, "publisher": candidate.publisher, "year": candidate.year,
            "work_type": candidate.work_type, "is_preprint": candidate.is_preprint,
            "oa_status": candidate.oa_status, "license": option.license or candidate.license,
            "source_service": option.service, "source_url": option.url, "retrieved_at": retrieved,
            "sha256": sha256, "bytes": len(data), "pages": check.pages, "title_match": round(check.title_match, 2),
            "found_by": candidate.found_by,
        })
    return Outcome(candidate.key, DOWNLOADED, file=os.path.basename(path), sha256=sha256, service=option.service,
                   url=option.url, license=option.license or candidate.license, pages=check.pages,
                   title_match=check.title_match)
