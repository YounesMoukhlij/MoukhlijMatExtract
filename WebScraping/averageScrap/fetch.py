# WebScraping/fetch.py
"""Getting the file. For each approved paper the downloader walks the resolver's options, best
first, and keeps the first one that turns out to be the paper: a real PDF (not the paywall page a
server sometimes sends under a .pdf name) whose first pages carry the paper's title (not a
supplement, a cover sheet or another article). A refusal (401/403) or a robots.txt "Disallow" just
means "next option" — nothing here tries to get around one."""

import hashlib
import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional, Tuple
from urllib.parse import urljoin

import pymupdf
import requests

from WebScraping.averageScrap.http import Disallowed, PoliteClient
from WebScraping.averageScrap.ids import file_stem
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, FAILED, Candidate
from WebScraping.averageScrap.resolve import FetchOption, Resolver
from WebScraping.averageScrap.sidecar import write_sidecar

# Fraction of a title's words that must be found in the first pages for the file to count as the paper.
_MIN_TITLE_MATCH = 0.5
# Below this much text in the first pages the title cannot be judged (a scan): the file is accepted.
_MIN_TEXT_TO_JUDGE = 800
_STOPWORDS = {"with", "from", "that", "this", "using", "based", "into", "their", "toward", "towards", "through",
              "under", "over", "between", "after", "within", "study", "analysis", "approach", "new"}
# A publisher's API that answers "too many requests" has used up an allowance that will not come
# back in a few seconds: the source is switched off for the rest of the run.
_ALLOWANCE = {"elsevier": "its weekly quota is used up", "wiley": "it allows no more requests for now"}


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
    def _read(self, response: requests.Response) -> Optional[bytes]:
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > self.max_bytes:
                return None
        return bytes(data)

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
            if status != 200:
                return None, f"HTTP {status}"
            kind = (response.headers.get("Content-Type") or "").lower()
            body = self._read(response)
            if body is None:
                return None, f"larger than {self.max_bytes // (1024 * 1024)} MB"
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
    def fetch(self, candidate: Candidate) -> Outcome:
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
            if not check.ok:
                tried.append(f"{option.service}: {check.reason}")
                continue
            return self._save(candidate, option, data, check)
        if not offered:
            return Outcome(candidate.key, CLOSED, error="no legal copy found: needs a manual PDF")
        return Outcome(candidate.key, FAILED, error="; ".join(tried)[:500])

    def _save(self, candidate: Candidate, option: FetchOption, data: bytes, check: PdfCheck) -> Outcome:
        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, f"{file_stem(candidate.key)}.pdf")
        part = path + ".part"
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)  # the PDF appears whole or not at all
        sha256 = hashlib.sha256(data).hexdigest()
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
