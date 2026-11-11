# WebScraping/http.py
"""HTTP for the web project. It says who is asking, spaces its requests per host, retries what is
worth retrying, honours robots.txt (and its Crawl-delay) for anything that is not an API, and never
tries to get around a refusal: a 401/403 or a robots.txt "Disallow" is an answer, not an obstacle."""

import logging
import re
import threading
import time
from typing import Any, Callable, Container, Dict, Optional
from urllib.parse import unquote, urlsplit

import requests

from LocalExtraction import runcontrol  # waits that Pause holds and Stop ends

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
    # Added later: Zenodo allows 60 requests a minute without a key, PLOS 10 a minute, Dimensions 30, BASE 60.
    "zenodo.org": 1.1, "api.datacite.org": 0.5, "api.plos.org": 6.5, "ntrs.nasa.gov": 1.0, "api.figshare.com": 0.5,
    "share.osf.io": 1.0, "buscador.lareferencia.info": 1.0, "theses.fr": 0.5, "api.lens.org": 1.5,
    "api.base-search.net": 1.0, "app.dimensions.ai": 2.0, "doi.org": 0.2,
}
_DEFAULT_INTERVAL = 1.0
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_MAX_WAIT = 60.0
# A site that answers 429 ("too many requests") has a limit per network address and wants a real pause:
# it is asked again after 15, 30 then 60 s (unless it says how long), and from then on that host gets
# one request every _SLOWED seconds at least — doubled at each new 429, up to _MAX_SLOWED — for the rest
# of the run, instead of the same pace that ran into the limit.
_SLOWED = 6.0
_MAX_SLOWED = 30.0


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


class _Robots:
    """robots.txt as RFC 9309 reads it: groups of rules for the user agents named above them (a blank line does
    not end a group; groups for the same agent are merged), "*" in a rule for any characters and "$" for the end
    of the path, and the longest matching rule wins (an Allow when they are as long). "Disallow: /*_pdf" keeps
    programs away from every PDF of J-STAGE.

    Read here rather than with Python's urllib.robotparser: its reading changed between patch releases (3.13.17
    follows RFC 9309 its own way and has no default entry any more), and this program must obey the same rules
    whatever Python runs it."""

    _cache: Dict[str, "re.Pattern"] = {}

    def __init__(self) -> None:
        self.disallow_all = False  # no robots.txt could be read for a server error: nothing is fetched
        self.allow_all = False
        self._rules: Dict[str, list] = {}     # user agent (lower case) -> [(path, allowed?)]
        self._delays: Dict[str, float] = {}   # user agent -> crawl delay, in seconds

    @classmethod
    def _pattern(cls, path: str) -> "re.Pattern":
        if path not in cls._cache:
            body = re.escape(path).replace(r"\*", ".*")
            cls._cache[path] = re.compile(body[:-2] + "$" if body.endswith(r"\$") else body)
        return cls._cache[path]

    def parse(self, lines) -> None:
        agents: list = []
        in_rules = False  # a user-agent line after rules opens a new group
        for raw in lines:
            line = str(raw).split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:
                    agents, in_rules = [], False
                agents.append(value.lower())
                self._rules.setdefault(value.lower(), [])
            elif key in ("allow", "disallow"):
                in_rules = True
                for agent in agents:
                    self._rules[agent].append((value, key == "allow"))
            elif key == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    continue
                for agent in agents:
                    self._delays[agent] = delay

    def _group(self, useragent: str) -> Optional[str]:
        """The group this program obeys: the one naming it by its whole name (RFC 9309: "Extract" is another
        bot, not this one), else the one for every bot ("*")."""
        name = useragent.split("/")[0].lower()
        if name in self._rules:
            return name
        return "*" if "*" in self._rules else None

    def crawl_delay(self, useragent: str) -> Optional[float]:
        group = self._group(useragent)
        return self._delays.get(group) if group else None

    def can_fetch(self, useragent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        group = self._group(useragent)
        if group is None:
            return True
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        best = None  # (length of the rule, allowed?)
        for rule, allowance in self._rules[group]:
            rule = unquote(rule)
            if rule and self._pattern(rule).match(path):
                best = max(best or (-1, False), (len(rule), allowance))
        return True if best is None else best[1]


def _backoff(attempt: int) -> float:
    return min(_MAX_WAIT, 2.0 ** attempt)


def _rate_backoff(attempt: int) -> float:
    """The wait after a 429 that did not say how long: 15, 30, 60 s."""
    return min(_MAX_WAIT, 15.0 * 2 ** (attempt - 1))


def _retry_after(response) -> float:
    try:
        return min(_MAX_WAIT, float(response.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 0.0


class PoliteClient:
    """GET requests for every service of the web project, shared by all worker threads."""

    def __init__(self, contact: str = "", session: Optional[requests.Session] = None, timeout: float = 30.0,
                 sleep: Callable[[float], None] = runcontrol.sleep, clock: Callable[[], float] = time.monotonic):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = f"{PRODUCT}/{VERSION}" + (f" (mailto:{contact})" if contact else "")
        self.timeout = timeout
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._next: Dict[str, float] = {}
        self._robots: Dict[str, Optional[_Robots]] = {}
        self._crawl_delay: Dict[str, float] = {}
        self._slowed: Dict[str, float] = {}  # host -> the interval a 429 asked for (this run)

    # ------------------------------------------------------------------
    # Spacing
    # ------------------------------------------------------------------
    def _wait(self, host: str) -> None:
        interval = max(_MIN_INTERVAL.get(host, _DEFAULT_INTERVAL), self._crawl_delay.get(host, 0.0),
                       self._slowed.get(host, 0.0))
        with self._lock:  # reserve a slot under the lock, sleep outside it so other hosts aren't held up
            now = self._clock()
            slot = max(now, self._next.get(host, 0.0))
            self._next[host] = slot + interval
        if slot > now:
            self._sleep(slot - now)

    # ------------------------------------------------------------------
    # robots.txt (RFC 9309: no robots.txt or a 4xx = everything allowed; a 5xx or no answer = nothing)
    # ------------------------------------------------------------------
    def _load_robots(self, base: str) -> Optional[_Robots]:
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
        return self._send(host, no_retry, lambda: self.session.get(url, params=params, headers=headers, stream=stream,
                                                                   timeout=self.timeout))

    def post_json(self, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None, data: Optional[str] = None) -> Any:
        """POST to an API (a JSON `body`, or a text `data`), with the same spacing and retries as get;
        its JSON answer. An error status raises HttpError."""
        host = urlsplit(url).netloc.lower()
        response = self._send(host, (), lambda: self.session.post(
            url, json=body if data is None else None, data=data.encode("utf-8") if data is not None else None,
            headers=headers, timeout=self.timeout))
        if response.status_code != 200:
            raise HttpError(url, response.status_code, response.text[:200].replace("\n", " "))
        return response.json()

    def _send(self, host: str, no_retry: Container[int], send: Callable[[], requests.Response]) -> requests.Response:
        """One request (`send`), spaced from the last one to its host, sent again on a busy answer."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._wait(host)
            try:
                response = send()
            except requests.RequestException:
                if attempt == _MAX_ATTEMPTS:
                    raise
                self._sleep(_backoff(attempt))
                continue
            if response.status_code == 429:
                self._slow_down(host)
            if response.status_code in _RETRY_STATUS and response.status_code not in no_retry \
                    and attempt < _MAX_ATTEMPTS:
                delay = _retry_after(response) or (_rate_backoff(attempt) if response.status_code == 429
                                                   else _backoff(attempt))
                logging.debug(f"{host} answered {response.status_code}; retrying in {delay:.0f}s")
                response.close()
                self._sleep(delay)
                continue
            return response
        raise RuntimeError("unreachable")  # the loop always returns or raises

    def pause(self, seconds: float) -> None:
        """A wait of the run (the watcher's): Pause holds it and Stop ends it, like the client's own."""
        self._sleep(seconds)

    def _slow_down(self, host: str) -> None:
        """A 429 from `host`: fewer requests to it for the rest of the run."""
        with self._lock:
            before = max(_MIN_INTERVAL.get(host, _DEFAULT_INTERVAL), self._slowed.get(host, 0.0))
            after = min(_MAX_SLOWED, max(_SLOWED, 2 * before))
            if after <= self._slowed.get(host, 0.0):
                return
            self._slowed[host] = after
        logging.info(f"{host} asked to slow down (HTTP 429, too many requests from this network): one request "
                     f"every {after:g} s to it for the rest of this run.")

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise HttpError(url, response.status_code, response.text[:200].replace("\n", " "))
        return response.json()
