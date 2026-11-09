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
from urllib.parse import urljoin

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


class Downloader:
    def __init__(self, folder: str, client: PoliteClient, resolver: Resolver, max_mb: int = 60):
        self.folder, self.client, self.resolver = folder, client, resolver
        self.max_bytes = max_mb * 1024 * 1024
        self._disabled = set()
        self._lock = threading.Lock()

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

    def _attempt(self, option: FetchOption) -> Tuple[Optional[bytes], str]:
        """The bytes an option gives, or (None, why not)."""
        try:
            response = self.client.get(option.url, headers=option.headers or None, stream=True, api=option.api,
                                       no_retry={429} if option.service in _ALLOWANCE else ())
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
                                                         license=option.license))
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

    def fetch(self, candidate: Candidate) -> Outcome:
        existing = self._on_disk(candidate)
        if existing and self._legal_record(existing):
            with open(existing, "rb") as f:
                data = f.read()
            check = check_pdf(data, candidate.title)
            if check.ok:
                logging.info(f"Already fetched: {candidate.key} ({os.path.basename(existing)} is in the folder) "
                             "— download skipped.")
                return self._save(candidate, FetchOption("already in the folder", f"file://{existing}"), data,
                                  check, path=existing)
        tried, offered = [], False
        for option in self.resolver.options(candidate):
            if option.service in self._disabled:
                continue
            offered = True
            data, reason = self._attempt(option)
            if data is None:
                tried.append(f"{option.service}: {reason}")
                continue
            check = check_pdf(data, candidate.title)
            if check.ok and option.service in _FIRST_PAGE_WHEN_NOT_ENTITLED and check.pages == 1:
                # What a publisher's API sends a reader its subscription does not cover: the first page.
                check = PdfCheck(False, f"only the first page ({NOT_ENTITLED_MARK}: the university's network or "
                                        "ELSEVIER_INSTTOKEN is needed, and a subscription to the journal)", 1)
            if not check.ok:
                tried.append(f"{option.service}: {check.reason}")
                continue
            return self._save(candidate, option, data, check)
        refused = list(dict.fromkeys([*self.resolver.refused(),
                                      *(t.split(":", 1)[0] for t in tried if _NOT_NOW.search(t))]))
        if refused:  # not an answer: a lookup or a site said "not now"
            return Outcome(candidate.key, FAILED, error="; ".join(tried)[:500] or "not checked: " + ", ".join(refused),
                           refused=refused)
        if not offered:
            return Outcome(candidate.key, CLOSED, error="no legal copy found: needs a manual PDF")
        return Outcome(candidate.key, FAILED, error="; ".join(tried)[:500])

    def _save(self, candidate: Candidate, option: FetchOption, data: bytes, check: PdfCheck,
              path: Optional[str] = None) -> Outcome:
        """Saves the PDF (unless `path`: it is there already) and its sidecar."""
        os.makedirs(self.folder, exist_ok=True)
        path_given = path is not None
        if path is None:
            path = os.path.join(self.folder, f"{file_stem(candidate.key)}.pdf")
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
