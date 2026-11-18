"""Collect DOIs for keywords from the open scholarly sources, and store them in a CSV file (and the
bare DOIs in a text file). In the Web scraping window this is "1 · Fetch DOIs"; "2 · Search" then
searches with the DOIs saved (each checked like the keyword results: OpenAlex record, abstract, score),
and "3 · Download" looks for the legal open-access copy of each (Unpaywall, PubMed Central, arXiv, …).

The keywords are the search queries of the project's job file,
configs/sse.yaml (the one WebScraping searches with), unless others are given
on the command line. The job's years, max_per_query, sources and
contact_email are used too.

Sources: OpenAlex, Crossref, Semantic Scholar and arXiv — open indexes, asked through the
interfaces they offer to programs. Every run adds its new DOIs to the
list already saved (one row per DOI), and the list is saved after each keyword.

How many: --count N adds N new DOIs (1 or more) and stops. Without it there is no
limit: the search goes on until you stop it (Ctrl-C here, Stop in the window) —
what was found is always saved. The new DOIs are shared out over all the
keywords, so they come from the whole topic, not only from the first keyword.

Enough keywords: running the same keywords again mostly finds DOIs already in
the list, so when they run dry the search goes on with more keywords, made of
the job's own topic and property words ("argyrodite" + "ionic conductivity"; for
keywords given on the command line: each one + a property word). --no-expand
keeps to the keywords given.

    python get_dois.py                                  # no limit, until you stop it
    python get_dois.py --count 500                      # 500 new DOIs, then stop
    python get_dois.py "solid electrolyte" "LLZO garnet" --count 50
    python get_dois.py --job configs/my_job.yaml --max 50

Keys are read from ~/MoukhlijMatExtract/.env when it exists (MME_EMAIL,
OPENALEX_API_KEY, SEMANTIC_SCHOLAR_API_KEY); none is required.
"""

import argparse
import csv
import json
import math
import os
import re
import signal
import sys
import threading
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote

import requests
import yaml

if not __package__:  # run as a script (python WebScraping/Fetch_DOIs/get_dois.py): make the project root importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from LocalExtraction import runcontrol  # noqa: E402
from LocalExtraction.about import PROJECT_HOME, command_name, enter_project_home, found_here, version_text  # noqa: E402

HERE = Path(__file__).resolve().parent            # WebScraping/Fetch_DOIs (where the code lives)
# The DOI list and the job file live in ~/MoukhlijMatExtract — not where the package is installed —
# next to the rest of the project's data (and where the scraper looks).
OUTPUT = PROJECT_HOME / "WebScraping" / "Fetch_DOIs" / "dois.csv"
JOB_FILE = PROJECT_HOME / "configs" / "sse.yaml"
# The API keys stay with the installed package (shared across the folders you work in).
ENV_FILE = HERE.parent / "averageScrap" / ".env"

PER_SOURCE = 100       # results asked from each source per keyword, if the job does not say
EXTRA_PER_SOURCE = 50  # results asked per source for a keyword made of topic + property words
EXTRA_MIN_SHARE = 5    # new DOIs one such keyword may add at least (fewer keywords, faster runs)
LOOKUP_EVERY = 50      # extra keywords between two look-ups of the details the sources left out
SEARCH_KEPT_DAYS = 30  # a keyword a source answered in full is not asked again for this many days (--refresh: now)

# The words extra keywords are made of when the job file lists none (screen.topic_words / property_words).
FALLBACK_TOPICS = ["solid electrolyte", "solid-state electrolyte", "superionic conductor", "fast ion conductor",
                   "lithium-ion conductor", "sodium-ion conductor", "argyrodite", "garnet", "NASICON", "LISICON",
                   "LGPS", "perovskite", "antiperovskite", "sulfide electrolyte", "oxide electrolyte",
                   "halide electrolyte", "hydride electrolyte", "polymer electrolyte"]
FALLBACK_PROPERTIES = ["ionic conductivity", "activation energy", "migration barrier", "diffusion coefficient",
                       "ion transport", "Arrhenius", "electrochemical stability"]

COLUMNS = ["doi", "title", "year", "authors", "venue", "keywords",
           "found_by", "doi_basis", "details_from", "link"]
DETAILS = ["title", "year", "authors", "venue"]
SETS = ["keywords", "found_by", "doi_basis", "details_from"]  # "; "-joined in the CSV
NOT_LISTED = "not listed by OpenAlex or Crossref"
# A detail of a DOI saved before its look-up ran (the search was stopped first): the next run looks it up.
NOT_LOOKED_UP = "not looked up yet (the next run looks it up)"

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#&\"'<>]+", re.I)
# Link endings that follow the DOI in publisher URLs, e.g. frontiersin.org/articles/<doi>/full
URL_TAILS = re.compile(r"/(full|abstract|pdf|epdf|meta|html|fulltext|summary)$", re.I)

CROSSREF_FIELDS = "DOI,title,issued,author,container-title,publisher,type,abstract"
OPENALEX_FIELDS = "doi,title,publication_year,authorships,primary_location"
# Research works only: no dictionary entries, errata, peer reviews, ...
OPENALEX_FILTER = "has_doi:true,type:!paratext,type:!reference-entry,type:!erratum,type:!peer-review"
CROSSREF_FILTER = ",".join("type:" + t for t in (
    "journal-article", "proceedings-article", "posted-content", "book-chapter",
    "report", "dissertation"))
KINDS = {"posted-content": "preprint", "dissertation": "thesis", "report": "report"}
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


# ---------------- setup ----------------

def load_env(path):
    """Put the KEY=value lines of path in os.environ (the shell's values win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def load_job(path):
    """What get_dois.py uses of a job file: its queries, years, max_per_query, sources, contact_email,
    and the topic and property words of its screening (to make more keywords when needed)."""
    if not path.exists():
        return {}
    job = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    search, screen = job.get("search") or {}, job.get("screen") or {}

    def words(values):
        return [str(v).strip() for v in values or [] if str(v).strip()]
    return {
        "queries": words(search.get("queries")),
        "years": tuple(search["years"]) if search.get("years") else None,
        "max": search.get("max_per_query"),
        "sources": search.get("sources"),
        "email": job.get("contact_email") or "",
        "topic_words": words(screen.get("topic_words")),
        "doi_list": str(search.get("doi_list") or ""),
        "property_words": words(screen.get("property_words")),
    }


load_env(ENV_FILE)
EMAIL = ""

SESSION = requests.Session()
RETRY_STATUS = (429, 500, 502, 503, 504)  # a rate limit or a busy server: wait, then ask again
RETRIES = 5
MAX_WAIT = 60.0  # seconds; a longer Retry-After is cut to this


def set_contact(email):
    """The e-mail the APIs are told about (it gets you their faster, polite lanes)."""
    global EMAIL
    EMAIL = email
    SESSION.headers["User-Agent"] = f"get_dois.py (mailto:{email})" if email else "get_dois.py"


def _retry_wait(attempt, response=None):
    """Seconds to wait before asking again: the site's Retry-After when it gives one, else 2, 4, 8, ... s."""
    try:
        given = float(response.headers.get("Retry-After", "")) if response is not None else 0.0
    except (TypeError, ValueError):  # absent, or written as a date
        given = 0.0
    if not given and response is not None and response.status_code == 429:
        given = 15.0 * 2 ** attempt  # "too many requests": a real pause (15, 30, 60 s), not a moment
    return min(MAX_WAIT, given or 2.0 * 2 ** attempt)


def get(url, params=None, headers=None):
    """GET, asked again up to RETRIES times on a rate limit, a busy server or a dropped connection.
    The waits are made here, not inside requests, so that Pause holds them and Stop (or Ctrl-C) ends them."""
    for attempt in range(RETRIES + 1):
        try:
            response = SESSION.get(url, params=params, headers=headers, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == RETRIES:
                raise
            runcontrol.sleep(_retry_wait(attempt))
            continue
        if response.status_code in RETRY_STATUS and attempt < RETRIES:
            wait = _retry_wait(attempt, response)
            response.close()
            runcontrol.sleep(wait)
            continue
        response.raise_for_status()
        return response


def mailto():
    return {"mailto": EMAIL} if EMAIL else {}


def openalex_auth():
    key = os.environ.get("OPENALEX_API_KEY", "")
    return {**({"api_key": key} if key else {}), **mailto()}


# ---------------- records ----------------

def clean_doi(text):
    """The first DOI in text (a DOI, a doi.org link, a publisher URL), lowercase, or ''."""
    match = DOI_RE.search(unquote(text or ""))
    if not match:
        return ""
    doi = match.group(0).rstrip(".,;)]}")
    while URL_TAILS.search(doi):
        doi = URL_TAILS.sub("", doi)
    return doi.lower()


def record(doi, title="", year="", authors=(), venue="", basis=""):
    return {
        "doi": clean_doi(doi),
        "title": " ".join(str(title or "").split()),
        "year": str(year or ""),
        "authors": "; ".join(a for a in authors if a),
        "venue": " ".join(str(venue or "").split()),
        "basis": basis,
    }


def first(values):
    return values[0] if values else ""


def simple(text):
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def openalex_record(work, basis):
    source = (work.get("primary_location") or {}).get("source") or {}
    authors = [(a.get("author") or {}).get("display_name") for a in work.get("authorships") or []]
    return record(work.get("doi"), work.get("title"), work.get("publication_year"),
                  authors, source.get("display_name"), basis)


def crossref_record(item, basis):
    parts = (item.get("issued") or {}).get("date-parts") or [[]]
    year = parts[0][0] if parts and parts[0] else ""
    authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
               for a in item.get("author") or []]
    venue = first(item.get("container-title"))
    if not venue and item.get("type") in KINDS:
        # Preprints and theses have no journal: name the server or university.
        venue = f"{KINDS[item['type']]}, {item.get('publisher', 'publisher not given')}"
    return record(item.get("DOI"), first(item.get("title")), year, authors, venue, basis)


def mentions_most(keyword, text):
    """True when two thirds of the keyword's words (3+ letters) are in the text."""
    words = set(re.findall(r"\w{3,}", keyword.lower()))
    text = text.lower()
    return sum(word in text for word in words) >= math.ceil(len(words) * 2 / 3)


# ---------------- sources ----------------
# Each takes the keyword, how many results to ask for and the years (first, last) or None.

def from_openalex(keyword, limit, years):
    filters = OPENALEX_FILTER + (f",publication_year:{years[0]}-{years[1]}" if years else "")
    params = {"search": keyword, "filter": filters, "per-page": min(100, limit),
              "select": OPENALEX_FIELDS, **openalex_auth()}
    paging = "api_key" in params  # OpenAlex refuses (HTTP 401) a page past the first without a key
    found, cursor = [], "*"
    while cursor and len(found) < limit:
        data = get("https://api.openalex.org/works", {**params, "cursor": cursor}).json()
        found += [openalex_record(work, "given by OpenAlex") for work in data["results"]]
        cursor = data["meta"].get("next_cursor") if data["results"] and paging else None
    return found[:limit]


def from_crossref(keyword, limit, years):
    # Crossref matches any one word ("garnet" alone brings geology papers), so
    # keep only the items whose title or abstract has most words of the keyword.
    filters = CROSSREF_FILTER + (f",from-pub-date:{years[0]},until-pub-date:{years[1]}" if years else "")
    found, cursor, seen = [], "*", 0
    while cursor and seen < limit:
        message = get("https://api.crossref.org/works", {
            "query.bibliographic": keyword, "filter": filters, "rows": min(100, limit - seen),
            # with a cursor, Crossref drops relevance order unless asked for it
            "cursor": cursor, "sort": "relevance",
            "select": CROSSREF_FIELDS, **mailto()}).json()["message"]
        items = message["items"]
        seen += len(items)
        found += [crossref_record(item, "given by Crossref") for item in items
                  if mentions_most(keyword, f"{first(item.get('title'))} {item.get('abstract', '')}")
                  and "dictionary" not in first(item.get("container-title")).lower()]
        cursor = message.get("next-cursor") if items else None
    return found


def from_semantic_scholar(keyword, limit, years):
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": key} if key else None
    found, offset = [], 0
    while offset < limit:
        data = get("https://api.semanticscholar.org/graph/v1/paper/search", {
            "query": keyword, "fields": "title,year,venue,authors,externalIds",
            "limit": min(100, limit - offset), "offset": offset,
            **({"year": f"{years[0]}-{years[1]}"} if years else {})}, headers).json()
        papers = data.get("data") or []
        for paper in papers:
            doi = (paper.get("externalIds") or {}).get("DOI")
            if doi:
                found.append(record(doi, paper.get("title"), paper.get("year"),
                                    [a.get("name") for a in paper.get("authors") or []],
                                    paper.get("venue"), "given by Semantic Scholar"))
        offset += len(papers)
        if not papers or "next" not in data:
            break
        runcontrol.sleep(1)  # one request a second
    return found


def from_arxiv(keyword, limit, years):
    query = " AND ".join(f"all:{word}" for word in re.findall(r"[\w-]+", keyword))
    if years:
        query += f" AND submittedDate:[{years[0]}01010000 TO {years[1]}12312359]"
    found = []
    for start in range(0, limit, 100):
        if start:
            runcontrol.sleep(3)  # arXiv asks for 3 s between requests (a wait Pause holds and Stop ends)
        feed = ET.fromstring(get("https://export.arxiv.org/api/query", {
            "search_query": query, "start": start, "max_results": min(100, limit - start),
            "sortBy": "relevance"}).content)
        entries = feed.findall(f"{ATOM}entry")
        for entry in entries:
            arxiv_id = re.sub(r"v\d+$", "", entry.findtext(f"{ATOM}id", "").split("/abs/")[-1])
            journal_doi = entry.findtext(f"{ARXIV}doi", "")
            if journal_doi:
                doi, basis = journal_doi, "journal DOI given by arXiv"
            else:
                doi, basis = f"10.48550/arXiv.{arxiv_id}", "arXiv's own DOI (no journal DOI listed)"
            found.append(record(
                doi, entry.findtext(f"{ATOM}title"), entry.findtext(f"{ATOM}published", "")[:4],
                [a.findtext(f"{ATOM}name") for a in entry.findall(f"{ATOM}author")],
                entry.findtext(f"{ARXIV}journal_ref") or "arXiv (preprint)", basis))
        if len(entries) < 100:
            break
    return found


# (name shown, name in the job's search.sources, function)
SOURCES = [
    ("OpenAlex", "openalex", from_openalex),
    ("Crossref", "crossref", from_crossref),
    ("Semantic Scholar", "semanticscholar", from_semantic_scholar),
    ("arXiv", "arxiv", from_arxiv),
]


# ---------------- stopping ----------------
# Ctrl-C in a terminal and Stop in the window (which ends the process politely) both end the search
# where it is; what was found is then saved. A stop that comes while the list is being changed
# waits for the change to be finished, so the list is never saved half-changed.

class StopRequested(BaseException):
    """The search was stopped; what it found is kept. (A BaseException, like KeyboardInterrupt,
    so that the sources' `except Exception` do not swallow it.)"""


_STOP = threading.Event()      # a stop was asked for
_CRITICAL = threading.Event()  # the list is being changed: a stop waits until the change is done


def _on_stop(signum, frame):
    _STOP.set()
    if not _CRITICAL.is_set():
        raise StopRequested()


def _check_stop():
    if _STOP.is_set():
        raise StopRequested()


def _on_signals(handler):
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, AttributeError, OSError):  # not the main thread, or no such signal here
            pass


# ---------------- table ----------------

def new_row(doi):
    return {"doi": doi, **{f: "" for f in DETAILS}, **{s: set() for s in SETS}}


def missing_details(row):
    return not all(row[f] for f in DETAILS)


def fill(row, rec, label):
    """Fill the row's empty title/year/authors/venue from rec."""
    filled = False
    for field in DETAILS:
        if not row[field] and rec[field]:
            row[field] = rec[field]
            filled = True
    if filled:
        row["details_from"].add(label)


def add_all(rows, records, source, keyword, room=None):
    """Add records to rows; return how many DOIs are new. A DOI already in the list only gains the
    keyword and the source that found it again; at most `room` new DOIs are added (None: no limit)."""
    new = 0
    _CRITICAL.set()  # a stop that comes now waits until the list is whole again
    try:
        for rec in records:
            doi = rec["doi"]
            if not doi:
                continue
            if doi not in rows:
                if room is not None and new >= room:
                    continue  # this keyword's share is in; a later keyword or run may add it
                rows[doi] = new_row(doi)
                new += 1
            row = rows[doi]
            row["keywords"].add(keyword)
            row["found_by"].add(source)
            row["doi_basis"].add(rec["basis"])
            fill(row, rec, source)
    finally:
        _CRITICAL.clear()
    _check_stop()
    return new


def fill_details(rows, only=None):
    """Look up by DOI the titles, years, authors and venues no source gave — of the DOIs in `only`,
    or of every DOI of the list."""
    dois = rows if only is None else [doi for doi in only if doi in rows]
    missing = [doi for doi in dois if missing_details(rows[doi])]
    for i in range(0, len(missing), 50):
        batch = [doi for doi in missing[i:i + 50] if "|" not in doi and "," not in doi]
        try:
            works = get("https://api.openalex.org/works", {
                "filter": "doi:" + "|".join(batch), "per-page": 50,
                "select": OPENALEX_FIELDS, **openalex_auth()}).json()["results"]
        except requests.RequestException:
            continue
        for work in works:
            rec = openalex_record(work, "")
            if rec["doi"] in rows:
                fill(rows[rec["doi"]], rec, "OpenAlex (by DOI)")

    for doi in [d for d in missing if not all(rows[d][f] for f in DETAILS)][:200]:
        try:
            item = get(f"https://api.crossref.org/works/{quote(doi)}", mailto()).json()["message"]
        except requests.RequestException:
            continue  # e.g. arXiv's own DOIs are not in Crossref
        fill(rows[doi], crossref_record(item, ""), "Crossref (by DOI)")


def load(path, unlooked=None):
    """The list earlier runs saved: the CSV, and the bare DOIs of the text file next to it — a DOI in
    either one is already in the list, so it is never added twice nor dropped when the list is saved
    again (a DOI only in the text file, e.g. added by hand, gets a row of its own). One row per DOI,
    whatever its case. A detail marked "not listed" or "not looked up yet" is emptied, to be looked
    up again this run; the DOIs marked "not looked up yet" go into `unlooked`."""
    rows = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as file:
            for line in csv.DictReader(file):
                row = {column: line.get(column) or "" for column in COLUMNS}
                row["doi"] = clean_doi(row["doi"]) or row["doi"].strip().lower()
                if not row["doi"]:
                    continue
                for column in SETS:
                    row[column] = set(filter(None, row[column].split("; ")))
                for field in DETAILS:
                    if row[field] == NOT_LOOKED_UP and unlooked is not None:
                        unlooked.add(row["doi"])
                    if row[field] in (NOT_LISTED, NOT_LOOKED_UP):
                        row[field] = ""  # try again this run
                if row["doi"] in rows:  # the same DOI twice (another case): one row with what both say
                    kept = rows[row["doi"]]
                    for column in SETS:
                        kept[column] |= row[column]
                    for field in DETAILS:
                        kept[field] = kept[field] or row[field]
                else:
                    rows[row["doi"]] = row
    text = path.with_suffix(".txt")
    if text.exists():
        for line in text.read_text(encoding="utf-8-sig").splitlines():
            doi = clean_doi(line)
            if doi and doi not in rows:
                rows[doi] = new_row(doi)
                rows[doi]["found_by"].add(f"{text.name} (not in {path.name})")
    return rows


def save(rows, path, unlooked=()):
    """Write the list: the CSV, and the bare DOIs next to it. A detail no source gave reads "not
    looked up yet" for a DOI in `unlooked` (its look-up has not run), else "not listed"."""
    path.parent.mkdir(parents=True, exist_ok=True)  # the folder may not exist yet (a fresh working folder)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        for row in rows.values():
            out = dict(row)
            for column in SETS:
                out[column] = "; ".join(sorted(row[column]))
            for field in DETAILS:
                out[field] = row[field] or (NOT_LOOKED_UP if row["doi"] in unlooked else NOT_LISTED)
            out["details_from"] = out["details_from"] or "only the DOI was found"
            out["link"] = "https://doi.org/" + row["doi"]
            writer.writerow(out)
    temporary.replace(path)  # never leaves a half-written CSV
    save_doi_list(rows, path.with_suffix(".txt"))


def save_doi_list(rows, path):
    """Write the bare DOIs, one per line (e.g. 10.1088/1361-6463/aad926), next to the CSV; kept in
    step with the CSV."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        for row in rows.values():
            if row["doi"]:
                file.write(row["doi"] + "\n")
    temporary.replace(path)  # never leaves a half-written list


# ---------------- searches already done ----------------

def searched_path(out):
    """Where the searches already run are remembered: next to the list (dois.csv -> dois.searched.json)."""
    return out.with_suffix(".searched.json")


def load_searched(path):
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_searched(searched, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(searched, file, indent=1, sort_keys=True)
    temporary.replace(path)


def search_key(source, keyword, years):
    return f"{source}|{simple(keyword)}|{list(years) if years else 'all years'}"


def already_searched(searched, key, depth):
    """The day `key` was searched in full, at least `depth` results deep, within SEARCH_KEPT_DAYS;
    None when it has to be searched."""
    entry = searched.get(key) if searched is not None else None
    if not entry or entry.get("depth", 0) < depth:
        return None
    try:
        at = datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return None
    if (datetime.now(timezone.utc) - at).total_seconds() > SEARCH_KEPT_DAYS * 86400:
        return None
    return at.date().isoformat()


# ---------------- keywords ----------------

def spread(items):
    """The items in an order that jumps across the list. Word lists are written grouped (synonyms
    side by side: "solid electrolyte", "solid-state electrolyte", ...), and neighbours find the same
    papers; a stride with no common factor with the length visits every item once, far apart."""
    n = len(items)
    step = max(1, round(n * 0.382))
    while math.gcd(step, n) != 1:
        step += 1
    return [items[(k * step) % n] for k in range(n)]


def list_of(job, out):
    """Where the DOIs go: --out when given, else the job's own list (search.doi_list, read from the home
    folder), else the shared list. A job's DOIs never land in another job's list."""
    if out is not None:
        return out
    if job.get("doi_list"):
        listed = Path(job["doi_list"])
        return listed if listed.is_absolute() else PROJECT_HOME / listed
    return OUTPUT


def main_topic(queries, topics):
    """The job's main topic, to keep its extra keywords on it: its first topic word, when at least half of
    its queries are about it ("solid electrolyte" in the electrolyte job). None when the job spans several
    subjects (a job on garnets and NASICONs: "garnet" added to every NASICON keyword would lose them)."""
    if not topics or not queries:
        return None
    first = simple(topics[0])
    share = sum(1 for query in queries if first in simple(query)) / len(queries)
    return topics[0] if share >= 0.5 else None


def extra_keywords(base, topics, properties, anchor=None):
    """Keywords beyond the base ones, for when those no longer find new DOIs: each topic with each
    property ("argyrodite ionic conductivity"), in an order where both change from one keyword to the
    next and jump across the word lists — so any number of them covers many kinds of material and
    many properties — without the base keywords, repeats, or pairs where one word holds the other.

    `anchor` (the job's main topic, e.g. "solid electrolyte") is added to a keyword whose topic does
    not share a word with it: "graph neural network shear modulus" alone finds papers of any field,
    "graph neural network shear modulus solid electrolyte" those of the topic."""
    seen = {simple(k) for k in base}
    anchor_words = set(simple(anchor).split()) if anchor else set()
    topics = spread(list(dict.fromkeys(t for t in topics if simple(t))))
    properties = spread(list(dict.fromkeys(p for p in properties if simple(p))))
    pairs = sorted(((i, j) for i in range(len(topics)) for j in range(len(properties))),
                   key=lambda pair: (pair[0] + pair[1], pair[0]))
    keywords = []
    for i, j in pairs:
        topic, prop = simple(topics[i]), simple(properties[j])
        if prop in topic or topic in prop:
            continue
        keyword = f"{topics[i]} {properties[j]}"
        if anchor_words and not anchor_words & set(topic.split()):
            keyword += f" {anchor}"
        if simple(keyword) not in seen:
            seen.add(simple(keyword))
            keywords.append(keyword)
    return keywords


def collect(rows, keywords, sources, limit, years, count=None, extra=(), after_keyword=None, used=None,
            searched=None, refresh=False):
    """Ask every source every keyword and add what they find to `rows`; return how many new DOIs
    were added.

    With `count`, it stops once that many new DOIs are in, and shares them out over the keywords:
    each keyword may add its share of what is still missing (a keyword that adds less leaves more
    for the next), so the new DOIs come from all the keywords. If the base keywords run dry first, it
    goes on with the `extra` ones. Without `count`, it uses every base keyword, then every extra one,
    until none is left or the search is stopped. `after_keyword(phase, number, total)` is called
    after each keyword (the caller saves there); `used` counts the base and extra keywords used.
    `searched` (optional) remembers which source answered which keyword in full: one already answered
    is skipped (unless `refresh`), and each one answered in full now is added to it."""
    used = used if used is not None else {}
    added = 0
    for phase, words, depth in (("base", list(keywords), limit),
                                ("extra", list(extra), min(limit, EXTRA_PER_SOURCE))):
        if not words or (count is not None and added >= count):
            continue
        if phase == "extra":
            print(f"\nThe {len(keywords)} keywords gave {added} new DOIs"
                  + (f" of the {count} asked for" if count is not None else "")
                  + f"; going on with {len(words)} more keywords, made of topic and property words.")
        for number, keyword in enumerate(words, 1):
            if count is not None and added >= count:
                break
            room = None
            if count is not None:
                share = math.ceil((count - added) / (len(words) - number + 1))
                room = min(count - added, max(share, EXTRA_MIN_SHARE if phase == "extra" else 1))
            so_far = f"{added} of {count}" if count is not None else str(added)
            print(f"\n=== [{'' if phase == 'base' else 'extra '}{number}/{len(words)}] {keyword}"
                  f"   (new DOIs so far: {so_far})")
            for name, search in list(sources):
                asked = depth
                key = search_key(name, keyword, years)
                when = None if refresh else already_searched(searched, key, asked)
                if when:
                    print(f"  {name}: already fetched on {when} — skipped")
                    used["skipped"] = used.get("skipped", 0) + 1
                    continue
                complete = True
                used["asked"] = used.get("asked", 0) + 1
                used.setdefault("keywords", set()).add(keyword)
                try:
                    found = search(keyword, asked, years)
                except Exception as exc:  # one failing source must not stop the others
                    if refused_now(exc):
                        used.setdefault("refused", []).append((name, search, keyword, asked))
                        print(f"  {name}: refused ({exc.__class__.__name__}: {exc}) — the watcher asks again later")
                    else:
                        print(f"  {name}: failed ({exc.__class__.__name__}: {exc})")
                    continue
                used["answered"] = used.get("answered", 0) + 1
                used["given"] = used.get("given", 0) + len(found)
                given = {rec["doi"] for rec in found if rec["doi"]}
                fresh = {doi for doi in given if doi not in rows}
                new = add_all(rows, found, name, keyword, room)
                added += new
                known = len(given) - len(fresh)
                print(f"  {name}: {len(found)} DOIs ({new} new"
                      + (f", {known} already in the list — skipped" if known else "") + ")")
                if searched is not None and complete and new == len(fresh):  # every DOI it gave is in
                    searched[key] = {"depth": asked, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                if room is not None:
                    room -= new
                    if room <= 0:
                        break  # this keyword's share is in: the next keyword gets the rest
            used[phase] = used.get(phase, 0) + 1
            if after_keyword is not None:
                after_keyword(phase, number, len(words))
    return added


def refused_now(exc):
    """Whether a source's failure is a "not now" worth asking again later: too many requests, a busy
    server, a connection that broke or timed out."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        return code in (408, 425, 429) or code >= 500
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


def recheck(rows, used, searched, years, count=None, added=0, after_round=None):
    """The watcher's rounds: the keyword searches a source refused are asked again after a pause of
    2, 5, 10 then 15 minutes (Ctrl-C or Stop ends the wait; what is still refused is asked by the next
    run, since it is not remembered as done). Returns how many new DOIs they added."""
    from WebScraping.averageScrap.watcher import ROUNDS_MINUTES
    new_total = 0
    for number, minutes in enumerate(ROUNDS_MINUTES, 1):
        waiting = used.get("refused") or []
        if not waiting or (count is not None and added + new_total >= count):
            break
        print(f"\nWatcher: {len(waiting)} keyword search(es) refused by a source that limits or did not answer "
              f"requests — asked again in {minutes} min (round {number} of {len(ROUNDS_MINUTES)}). "
              "Ctrl-C / Stop leaves them for the next run.")
        runcontrol.sleep(minutes * 60)
        used["refused"] = []
        for name, search, keyword, asked in waiting:
            used["asked"] = used.get("asked", 0) + 1
            try:
                found = search(keyword, asked, years)
            except Exception as exc:
                if refused_now(exc):
                    used["refused"].append((name, search, keyword, asked))
                print(f"  {name} · {keyword}: refused again ({exc.__class__.__name__})")
                continue
            used["answered"] = used.get("answered", 0) + 1
            used["later"] = used.get("later", 0) + 1
            used["given"] = used.get("given", 0) + len(found)
            room = None if count is None else max(0, count - added - new_total)
            fresh = {rec["doi"] for rec in found if rec["doi"] and rec["doi"] not in rows}
            new = add_all(rows, found, name, keyword, room)
            new_total += new
            print(f"  {name} · {keyword}: {len(found)} DOIs ({new} new) — answered on a later try")
            if searched is not None and new == len(fresh):
                searched[search_key(name, keyword, years)] = {
                    "depth": asked, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if after_round is not None:
            after_round()
    return new_total


def watch_report(used, before, total):
    """The watcher's report of a run of Fetch DOIs: keywords and searches checked, DOIs."""
    still = len(used.get("refused") or [])
    return (f"\nWatcher report — keywords checked: {len(used.get('keywords') or ()):,}; searches (keyword × source): "
            f"{used.get('asked', 0):,} asked, {used.get('answered', 0):,} answered, "
            f"{used.get('later', 0):,} of them on a later try, {still:,} still refused (asked again next run), "
            f"{used.get('skipped', 0):,} already done; DOIs: {used.get('given', 0):,} given by the sources, "
            f"{total - before:,} new, {total:,} in the list.")


def positive_count(text):
    """--count: a whole number from 1 up."""
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{number}: the number of DOIs must be 1 or more")
    return number


# ---------------- main ----------------

def main(argv=None):
    """The command (mme-dois). `argv`: its arguments (default: the command line) — the Web scraping
    window calls it with its own."""
    parser = argparse.ArgumentParser(prog=command_name("mme-dois", "WebScraping.Fetch_DOIs.get_dois"),
                                     description="Collect DOIs for keywords into a CSV file (and the bare "
                                                 "DOIs into a text file next to it). Each run adds to the list.")
    parser.add_argument("--version", action="version", version=version_text("mme-dois"))
    parser.add_argument("keywords", nargs="*",
                        help='e.g. "solid electrolyte" "LLZO garnet" (default: the queries of the job file)')
    parser.add_argument("--count", "-n", type=positive_count, metavar="N",
                        help="how many NEW DOIs to add to the list (1 or more), then stop. Without it there is "
                             "no limit: the search goes on until you stop it (Ctrl-C); what was found is kept")
    parser.add_argument("--job", type=Path, default=JOB_FILE,
                        help="job file whose queries, years, sources and max_per_query are used "
                             "(default: configs/sse.yaml)")
    parser.add_argument("--max", type=int,
                        help=f"results asked from each source per keyword "
                             f"(default: the job's max_per_query, else {PER_SOURCE})")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"CSV file (default: the job's doi_list, else WebScraping/Fetch_DOIs/{OUTPUT.name})")
    parser.add_argument("--refresh", action="store_true",
                        help=f"ask the sources again the keywords they already answered (by default a keyword a "
                             f"source answered in the last {SEARCH_KEPT_DAYS} days is skipped)")
    parser.add_argument("--no-expand", action="store_true",
                        help="use only the keywords given: do not go on with keywords made of topic and "
                             "property words when they run dry")
    args = parser.parse_args(argv)
    args.job = found_here(args.job)  # before the move into the home folder
    enter_project_home("dois")

    # A job the package ships, not made yet (a fresh folder): made from the shipped one, with the others.
    from WebScraping.averageScrap.about import starter_job
    if not args.job.exists() and (args.job != JOB_FILE or not args.keywords):
        starter_job(str(args.job))
    if not args.job.exists() and args.job != JOB_FILE:
        sys.exit(f"There is no job file {args.job}")
    job = load_job(args.job)
    args.out = list_of(job, args.out)
    set_contact(os.environ.get("MME_EMAIL") or job.get("email", ""))

    keywords = args.keywords or job.get("queries")
    if not keywords:
        try:
            keywords = [k.strip() for k in input("Keywords, separated by commas: ").split(",") if k.strip()]
        except EOFError:  # no terminal to ask in (run from the window)
            keywords = []
    if not keywords:
        sys.exit("No keywords given.")
    years = job.get("years")
    limit = args.max or job.get("max") or PER_SOURCE
    properties = job.get("property_words") or FALLBACK_PROPERTIES
    if args.no_expand:
        extra = []
    elif args.keywords:  # keywords of your own: each of them with a property word
        extra = extra_keywords(keywords, keywords, properties)
    else:  # the job's queries: its topic words with its property words, kept on the job's main topic
        topics = job.get("topic_words") or FALLBACK_TOPICS
        extra = extra_keywords(keywords, topics, properties, anchor=main_topic(keywords, topics))

    wanted = job.get("sources")
    sources = [(name, search) for name, key, search in SOURCES if not wanted or key in wanted]
    if not sources:  # the job searches none of these four: ask them all
        sources = [(name, search) for name, _, search in SOURCES]

    origin = "the command line" if args.keywords else args.job
    more = (f" (+ {len(extra)} more made of topic and property words, "
            + ("used if these run dry)" if args.count else "used after them)") if extra else "")
    print(f"{len(keywords)} keywords from {origin}{more}; "
          f"{f'years {years[0]}-{years[1]}' if years else 'all years'}; "
          f"up to {limit} results per source; sources: {', '.join(name for name, _ in sources)}")
    print(f"Goal: {args.count} new DOIs, added to the list." if args.count else
          "Goal: no limit — the search goes on until you stop it (Ctrl-C, or Stop in the window); "
          "every DOI found is kept.")

    unlooked = set()  # DOIs whose missing details have not been looked up yet
    rows = load(args.out, unlooked)
    before = len(rows)
    print(f"The list holds {before} DOIs ({args.out.name} and {args.out.with_suffix('.txt').name}); a DOI already in it is "
          "skipped, only new ones are added.")
    known = set(rows)
    retry = {doi for doi, row in rows.items() if missing_details(row)}  # details to look up this run

    def checkpoint(phase=None, number=0, total=0, lookup=False):
        """Takes in the DOIs added since the last call, looks up the details the sources left out
        (after the base keywords, every LOOKUP_EVERY extra keywords, and at the end), and saves."""
        fresh = rows.keys() - known
        known.update(fresh)
        unlooked.update(fresh)
        retry.update(doi for doi in fresh if missing_details(rows[doi]))
        lookup = lookup or (phase == "base" and number == total) or (phase == "extra" and number % LOOKUP_EVERY == 0)
        if lookup and retry:
            print(f"\nLooking up the missing titles, years, authors and venues of {len(retry)} DOIs ...")
            fill_details(rows, only=retry)
            retry.clear()
            unlooked.clear()
        save(rows, args.out, unlooked)
        save_searched(searched, searched_file)

    searched_file = searched_path(args.out)
    searched = load_searched(searched_file)
    used = {}
    stopped = False
    # Run on its own (mme-dois), Ctrl-C is caught here; run as a step of a window or of mme-web, the
    # step's own Stop (or Ctrl-C) is used, and its handler is left as it was.
    own_signals = not isinstance(runcontrol.current(), runcontrol.RunControl)
    before_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)} if own_signals else {}
    _STOP.clear()
    if own_signals:
        _on_signals(_on_stop)
    try:
        added = collect(rows, keywords, sources, limit, years, args.count, extra, checkpoint, used, searched, args.refresh)
        recheck(rows, used, searched, years, args.count, added, after_round=checkpoint)
        checkpoint(lookup=True)  # the details of the last DOIs, and the final save
    except (StopRequested, runcontrol.StepStopped):  # Ctrl-C, or Stop in the window
        stopped = True
        if own_signals:
            _on_signals(signal.SIG_IGN)  # a second press must not cut the save short
        print("\nStopped — saving what was found ...")
        checkpoint()
    finally:
        for sig, handler in before_signals.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, TypeError):
                pass

    added, total = len(rows) - before, len(rows)
    extras = used.get("extra", 0)
    keywords_used = (f"{used.get('base', 0)} of the {len(keywords)} keywords"
                     + (f" and {extras} extra keyword{'s' if extras > 1 else ''}" if extras else ""))
    if stopped:
        print(f"\nStopped after {keywords_used}: {added} new DOIs kept; {total} in the list."
              + (" The details not looked up yet are looked up by the next run." if unlooked else ""))
    elif args.count and added < args.count:
        print(f"\nOnly {added} new DOIs could be found (you asked for {args.count}): all {keywords_used} were used"
              + (" — run without --no-expand to try more keywords." if args.no_expand else "."))
    else:
        print(f"\n{added} new DOIs added" + (f" (you asked for {args.count})" if args.count else "")
              + f", from {keywords_used}; {total} in the list.")
    if used.get("skipped"):
        print(f"{used['skipped']} keyword searches were already fetched and skipped (--refresh asks them again).")
    print(watch_report(used, before, total))
    print(f"Saved: {args.out} (full records) and {args.out.with_suffix('.txt')} (bare DOIs, one per line). "
          "In the Web scraping window they become candidates; “3 · Download” fetches their legal open-access copies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
