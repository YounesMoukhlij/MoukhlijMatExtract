# LocalExtraction/metadata.py
"""What a paper is — title, authors, journal, DOI, year, license — completed from OpenAlex.

A PDF says little about itself reliably: its embedded title is often the file name of a
typesetter ("SpringerNature_NatCommun_77363_AIP"), its subject field a sentence of the abstract, and
the first DOI printed in it can be one of its references. So what the PDF gives is checked against
OpenAlex, the open index of the scholarly literature:

    1. the DOI found in the PDF (or the arXiv id), looked up directly
    2. otherwise the title, searched for
    3. otherwise the DOI in Crossref, which knows every registered DOI — also a paper too new for
       OpenAlex to index yet

and a work is accepted only if its own title is printed on the first page of the PDF — which also
throws out a DOI that belonged to a reference. What OpenAlex knows replaces what the PDF guessed;
what neither knows is said as such. `basis` records where each paper's description came from.

What was found is kept next to the database (metadata_cache.json, by the checksum of the PDF), so
that rebuilding a database — or a run while OpenAlex cannot be reached — keeps what an earlier run
found. Without a network (or with MME_OFFLINE=1) nothing is looked up and the PDF's own
metadata stands. OPENALEX_API_KEY and MME_EMAIL, when set, are sent along."""

import difflib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, Optional, Tuple

import requests

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
CACHE_NAME = "metadata_cache.json"
_TIMEOUT = 15
_PAUSE_AFTER_OUTAGE = 60.0  # seconds without a try once a service could not be reached
_ARXIV = re.compile(r"arXiv:\s?(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_FIELDS = "id,doi,title,display_name,publication_year,authorships,primary_location,best_oa_location,open_access,ids"


class _Unreachable:
    """What a request gives when the service could not be reached (as opposed to "not found")."""


UNREACHABLE = _Unreachable()
_outage = {"until": 0.0, "said": False}
_outage_lock = threading.Lock()


def _words(text: str) -> str:
    """Text folded for comparison: no accents, no case, words separated by single spaces."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def title_is_printed(title: str, first_page: str) -> bool:
    """Whether a work's title stands on the first page of the PDF: its letters in order, allowing
    for a line break, a hyphen or a ligature PDF extraction has mangled — and for the last line of
    a title that the reading order put elsewhere on the page: 85% of it in one run is enough (the
    title of another paper, a reference say, does not share that much)."""
    wanted, page = _words(title).replace(" ", ""), _words(first_page).replace(" ", "")
    if len(wanted) < 12:
        return False
    if wanted in page:
        return True
    match = difflib.SequenceMatcher(None, wanted, page, autojunk=False).find_longest_match(0, len(wanted), 0, len(page))
    return match.size >= 0.85 * len(wanted)


def _get(url: str, params: Optional[Dict[str, str]] = None) -> Any:
    """The JSON answer of a service; {} for "not found"; None for another refusal; UNREACHABLE
    when the service could not be reached even after asking again."""
    if os.environ.get("MME_OFFLINE"):
        return UNREACHABLE
    with _outage_lock:
        if time.monotonic() < _outage["until"]:
            return UNREACHABLE  # it was down a moment ago: do not wait on it for every paper
    email = os.environ.get("MME_EMAIL", "")
    headers = {"User-Agent": "MoukhlijMatExtract/0.1" + (f" (mailto:{email})" if email else "")}
    if url.startswith(OPENALEX):
        key = os.environ.get("OPENALEX_API_KEY", "")
        params = {**(params or {}), **({"api_key": key} if key else {}), **({"mailto": email} if email else {})} or None
    answer = None
    for attempt in range(4):
        try:
            answer = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        except requests.RequestException as error:
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))  # a dropped connection: ask again
                continue
            with _outage_lock:
                _outage["until"] = time.monotonic() + _PAUSE_AFTER_OUTAGE
                if not _outage["said"]:
                    _outage["said"] = True
                    logging.warning(f"{url.split('/')[2]} cannot be reached ({type(error).__name__}): papers read "
                                    "meanwhile keep the metadata their PDF gives (run again to complete them).")
            return UNREACHABLE
        if answer.status_code not in (429, 500, 502, 503, 504):
            break
        # Too many requests at once (several PDFs are read in parallel), or a busy server: wait, ask again.
        time.sleep(float(answer.headers.get("Retry-After", "") or 0) or 1.5 * (attempt + 1))
    if answer is None or answer.status_code in (429, 500, 502, 503, 504):
        return UNREACHABLE
    if answer.status_code == 404:
        return {}
    if answer.status_code != 200:
        logging.debug(f"{url.split('/')[2]} answered {answer.status_code} for {url}")
        return None
    try:
        return answer.json()
    except ValueError:
        return None


def _describe(work: Dict[str, Any], how: str) -> Dict[str, str]:
    """The metadata of an OpenAlex work, as the columns of papers.csv."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    best = work.get("best_oa_location") or {}
    authors = [a.get("author", {}).get("display_name", "") for a in work.get("authorships") or []]
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    license_ = best.get("license") or location.get("license") or ""
    oa = (work.get("open_access") or {}).get("oa_status", "")
    return {
        "title": work.get("display_name") or work.get("title") or "",
        "authors": "; ".join(a for a in authors if a),
        "journal": source.get("display_name") or "",
        "doi": doi,
        "publication_year": str(work.get("publication_year") or ""),
        "openalex_id": (work.get("id") or "").rsplit("/", 1)[-1],
        "license": license_ or (f"no open license ({oa} access)" if oa else ""),
        "basis": f"OpenAlex ({how}; its title is printed on the first page)",
    }


def _license_name(url: str) -> str:
    """"http://creativecommons.org/licenses/by-nc/4.0/" → "cc-by-nc"; another license as it is given."""
    found = re.search(r"creativecommons\.org/(?:licenses/([a-z-]+)|publicdomain/(zero))", url or "")
    if found:
        return "cc-" + (found.group(1) or "zero")
    return url


def _crossref(doi: str, first_page: str) -> Tuple[Optional[Dict[str, str]], bool]:
    answer = _get(f"{CROSSREF}/{doi}")
    if answer is UNREACHABLE:
        return None, True
    work = (answer or {}).get("message") or {}
    title = " ".join(work.get("title") or [])
    if not title or not title_is_printed(title, first_page):
        return None, False
    authors = [" ".join(part for part in (a.get("given", ""), a.get("family", "")) if part) or a.get("name", "")
               for a in work.get("author") or []]
    dated = (work.get("published") or work.get("issued") or {}).get("date-parts") or [[None]]
    licenses = [item.get("URL", "") for item in work.get("license") or []]
    return {
        "title": title,
        "authors": "; ".join(a for a in authors if a),
        "journal": " ".join(work.get("container-title") or []) or work.get("publisher", ""),
        "doi": (work.get("DOI") or doi).lower(),
        "publication_year": str(dated[0][0] or ""),
        "openalex_id": "",
        "license": _license_name(licenses[0]) if licenses else "",
        "basis": "Crossref (by its DOI; its title is printed on the first page)",
    }, False


def find(doi: str, title: str, first_page: str, trusted_doi: bool = False) -> Tuple[Optional[Dict[str, str]], bool]:
    """What OpenAlex (or Crossref) knows of the paper whose first page this is, and whether a
    service could not be reached on the way — (None, True) means "not known: ask again later",
    (None, False) "no work matches". `trusted_doi`: the DOI was reported by the source the paper
    was fetched from (and the file checked against it), not guessed from the PDF — so the work it
    names is the paper's even where the PDF is an author manuscript whose title differs a little
    from the published one."""
    tries = []
    if doi and doi != "NONE":
        tries.append(("by its DOI", f"{OPENALEX}/doi:{doi}", None))
    arxiv = _ARXIV.search(first_page or "")
    if arxiv:
        tries.append(("by its arXiv id", f"{OPENALEX}/doi:10.48550/arxiv.{arxiv.group(1)}", None))
    if title and title != "NONE" and len(_words(title)) >= 12:
        tries.append(("by its title", OPENALEX, {"search": title[:300], "per-page": "5", "select": _FIELDS}))
    unreachable = False
    for how, url, params in tries:
        answer = _get(url, params)
        if answer is UNREACHABLE:
            unreachable = True
            continue
        if not answer:
            continue
        works = answer.get("results", []) if params else [answer]
        for work in works:
            name = work.get("display_name") or work.get("title") or ""
            if title_is_printed(name, first_page):
                return _describe(work, how), False
            if trusted_doi and how == "by its DOI":
                found = _describe(work, how)
                found["basis"] = "OpenAlex (by the DOI its source reported)"
                return found, False
    if doi and doi != "NONE":
        found, down = _crossref(doi, first_page)
        return found, unreachable or down
    return None, unreachable


def lookup(doi: str, title: str, first_page: str, trusted_doi: bool = False) -> Optional[Dict[str, str]]:
    """find(), without saying why nothing was found."""
    return find(doi, title, first_page, trusted_doi)[0]


class Cache:
    """What was found for each paper — by the checksum of its PDF — kept in a file next to the
    database, so that a rebuild does not ask again and a run while OpenAlex cannot be reached keeps
    what an earlier one found. Shared by the threads of one extraction."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict[str, str]] = {}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._entries = {k: v for k, v in loaded.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def get(self, key: str) -> Optional[Dict[str, str]]:
        with self._lock:
            found = self._entries.get(key)
            return dict(found) if found else None

    def put(self, key: str, found: Dict[str, str]) -> None:
        with self._lock:
            self._entries[key] = dict(found)

    def save(self) -> None:
        with self._lock:
            if not self._entries:
                return
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            partial = self.path + ".part"
            with open(partial, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=1, ensure_ascii=False, sort_keys=True)
            os.replace(partial, self.path)
