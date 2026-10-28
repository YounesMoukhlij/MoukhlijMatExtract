# WebScraping/http.py
"""HTTP for the web project. It says who is asking, spaces its requests per host, retries what is
worth retrying, honours robots.txt (and its Crawl-delay) for anything that is not an API, and never
tries to get around a refusal: a 401/403 or a robots.txt "Disallow" is an answer, not an obstacle."""

import logging
import re
import threading
import time
from typing import Any, Callable, Container, Dict, Optional
from urllib import robotparser
from urllib.parse import unquote, urlsplit

import requests

PRODUCT = "MoukhlijMatExtract"
VERSION = "1.0.0"

# Seconds between two requests to the same host. APIs state their own limits; any other host (a
# publisher, a repository) gets a conservative default, or the Crawl-delay of its robots.txt if
# that is longer (arxiv.org asks generic crawlers for 15 s).
_MIN_INTERVAL = {
    "api.openalex.org": 0.2, "export.arxiv.org": 3.0, "api.unpaywall.org": 0.25,
    "api.elsevier.com": 0.5, "api.crossref.org": 0.25,
    # Wiley allows 60 requests in 10 minutes; Semantic Scholar one a second, shared by everyone without a key.
    "api.wiley.com": 10.0, "api.semanticscholar.org": 1.1,
    "www.ebi.ac.uk": 0.3, "pmc-oa-opendata.s3.amazonaws.com": 0.2, "api.archives-ouvertes.fr": 0.3,
    "api.openaire.eu": 0.6,
    # The search services added to OpenAlex and arXiv: their own stated limits, or a polite pace.
    "doaj.org": 0.5, "api.jstage.jst.go.jp": 1.0, "api.core.ac.uk": 1.0, "api.springernature.com": 1.0,
    "api.adsabs.harvard.edu": 0.5, "ieeexploreapi.ieee.org": 1.0, "api.clarivate.com": 1.0,
}
_DEFAULT_INTERVAL = 1.0
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_MAX_WAIT = 60.0


class HttpError(RuntimeError):
    """A request that ended in an error status."""

    def __init__(self, url: str, status: int, detail: str = ""):
        super().__init__(f"HTTP {status} for {url}" + (f": {detail}" if detail else ""))
        self.url, self.status = url, status


class Disallowed(RuntimeError):
    """The site's robots.txt does not allow this URL to be fetched."""


# A robots.txt read as RFC 9309 says: a blank line (or a line of comment) does not end a group of rules.
# Python's parser takes it for the end, and so drops the rules written after one — PLOS writes
# "Crawl-delay: 30", a blank line, then "Disallow: */search".
def rule_lines(text: str) -> list:
    return [line for line in text.splitlines() if line.split("#", 1)[0].strip()]


class _Robots(robotparser.RobotFileParser):
    """robots.txt as RFC 9309 reads it. Python's parser takes a rule's path literally and the first
    rule that matches; a robots.txt also writes "*" (any characters) and "$" (the end of the path) —
    "Disallow: /*_pdf" keeps programs away from every PDF of J-STAGE — and the longest matching rule
    wins (an Allow when they are as long)."""

    _cache: Dict[str, "re.Pattern"] = {}

    @classmethod
    def _pattern(cls, path: str) -> "re.Pattern":
        if path not in cls._cache:
            body = re.escape(path).replace(r"\*", ".*")
            cls._cache[path] = re.compile(body[:-2] + "$" if body.endswith(r"\$") else body)
        return cls._cache[path]

    def can_fetch(self, useragent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        if not self.last_checked:
            return False
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        # The rules naming this program by its whole name (RFC 9309; Python's applies_to matches a part of
        # it, so a rule for some bot called "Extract" would be taken for one about this program).
        name = useragent.split("/")[0].lower()
        entry = next((e for e in self.entries if any(a.lower() == name for a in e.useragents)), self.default_entry)
        if entry is None:
            return True
        best = None  # (length of the rule, allowed?)
        for line in entry.rulelines:
            rule = unquote(line.path)
            if rule and self._pattern(rule).match(path):
                best = max(best or (-1, False), (len(rule), line.allowance))
        return True if best is None else best[1]


def _backoff(attempt: int) -> float:
    return min(_MAX_WAIT, 2.0 ** attempt)


def _retry_after(response) -> float:
    try:
        return min(_MAX_WAIT, float(response.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 0.0


class PoliteClient:
    """GET requests for every service of the web project, shared by all worker threads."""

    def __init__(self, contact: str = "", session: Optional[requests.Session] = None, timeout: float = 30.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = f"{PRODUCT}/{VERSION}" + (f" (mailto:{contact})" if contact else "")
        self.timeout = timeout
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._next: Dict[str, float] = {}
        self._robots: Dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._crawl_delay: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Spacing
    # ------------------------------------------------------------------
    def _wait(self, host: str) -> None:
        interval = max(_MIN_INTERVAL.get(host, _DEFAULT_INTERVAL), self._crawl_delay.get(host, 0.0))
        with self._lock:  # reserve a slot under the lock, sleep outside it so other hosts aren't held up
            now = self._clock()
            slot = max(now, self._next.get(host, 0.0))
            self._next[host] = slot + interval
        if slot > now:
            self._sleep(slot - now)

    # ------------------------------------------------------------------
    # robots.txt (RFC 9309: no robots.txt or a 4xx = everything allowed; a 5xx or no answer = nothing)
    # ------------------------------------------------------------------
    def _load_robots(self, base: str) -> Optional[robotparser.RobotFileParser]:
        parser = _Robots()
        try:
            response = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
        except requests.RequestException:
            parser.disallow_all = True
            return parser
        if response.status_code == 200:
            parser.parse(rule_lines(response.text))
            delay = parser.crawl_delay(PRODUCT)
            if delay:
                self._crawl_delay[urlsplit(base).netloc.lower()] = float(delay)
            return parser
        if response.status_code >= 500:
            parser.disallow_all = True
            return parser
        return None

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            self._robots[base] = self._load_robots(base)
        parser = self._robots[base]
        return True if parser is None else parser.can_fetch(PRODUCT, url)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------
    def get(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
            stream: bool = False, api: bool = True, no_retry: Container[int] = ()) -> requests.Response:
        """GET with spacing and retries. A page or a file (`api=False`) is only fetched if the
        site's robots.txt allows it. Statuses in `no_retry` come straight back (an exhausted quota
        will not clear in a few seconds). Returns the last response whatever its status; only a
        network failure that outlasts the retries raises."""
        host = urlsplit(url).netloc.lower()
        if not api:
            if not self.allowed(url):
                raise Disallowed(f"robots.txt of {host} does not allow {url}")
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._wait(host)
            try:
                response = self.session.get(url, params=params, headers=headers, stream=stream,
                                            timeout=self.timeout)
            except requests.RequestException:
                if attempt == _MAX_ATTEMPTS:
                    raise
                self._sleep(_backoff(attempt))
                continue
            if response.status_code in _RETRY_STATUS and response.status_code not in no_retry \
                    and attempt < _MAX_ATTEMPTS:
                delay = _retry_after(response) or _backoff(attempt)
                logging.debug(f"{host} answered {response.status_code}; retrying in {delay:.0f}s")
                response.close()
                self._sleep(delay)
                continue
            return response
        raise RuntimeError("unreachable")  # the loop always returns or raises

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise HttpError(url, response.status_code, response.text[:200].replace("\n", " "))
        return response.json()
