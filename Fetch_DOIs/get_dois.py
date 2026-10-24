"""Collect DOIs for keywords and store them in a CSV file.

The keywords are the search queries of the project's job file,
configs/sse.yaml (the one WebScraping searches with), unless others are given
on the command line. The job's years, max_per_query, sources and
contact_email are used too.

Sources: OpenAlex, Crossref, Semantic Scholar, arXiv and Google Scholar.
Google Scholar results carry no DOI, so it is read from the result's link or
found on Crossref by the paper's title. Every run adds to the CSV, one row per
DOI, and the CSV is saved after each keyword.

    python get_dois.py                                  # every query of configs/sse.yaml
    python get_dois.py "solid electrolyte" "LLZO garnet"
    python get_dois.py --job configs/my_job.yaml --max 50 --no-scholar

Keys are read from WebScraping/.env when it exists (MME_EMAIL,
OPENALEX_API_KEY, SEMANTIC_SCHOLAR_API_KEY); none is required.
"""

import argparse
import csv
import difflib
import logging
import math
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTPUT = HERE / "dois.csv"
JOB_FILE = ROOT / "configs" / "sse.yaml"
ENV_FILE = ROOT / "WebScraping" / ".env"

PER_SOURCE = 100       # results asked from each source per keyword, if the job does not say
SCHOLAR_MAX = 20       # Google Scholar is slow and blocks scripts quickly
SCHOLAR_TIMEOUT = 180  # seconds before giving up on Google Scholar

COLUMNS = ["doi", "title", "year", "authors", "venue", "keywords",
           "found_by", "doi_basis", "details_from", "link"]
DETAILS = ["title", "year", "authors", "venue"]
SETS = ["keywords", "found_by", "doi_basis", "details_from"]  # "; "-joined in the CSV
NOT_LISTED = "not listed by OpenAlex or Crossref"

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
    """What get_dois.py uses of a job file: its queries, years, max_per_query, sources, contact_email."""
    if not path.exists():
        return {}
    job = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    search = job.get("search") or {}
    return {
        "queries": [str(q).strip() for q in search.get("queries") or [] if str(q).strip()],
        "years": tuple(search["years"]) if search.get("years") else None,
        "max": search.get("max_per_query"),
        "sources": search.get("sources"),
        "email": job.get("contact_email") or "",
    }


load_env(ENV_FILE)
EMAIL = ""

SESSION = requests.Session()
# Wait and retry on rate limits (429) and server errors, following Retry-After.
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=["GET"])))


def set_contact(email):
    """The e-mail the APIs are told about (it gets you their faster, polite lanes)."""
    global EMAIL
    EMAIL = email
    SESSION.headers["User-Agent"] = f"get_dois.py (mailto:{email})" if email else "get_dois.py"


def get(url, params=None, headers=None):
    response = SESSION.get(url, params=params, headers=headers, timeout=30)
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
    found, cursor = [], "*"
    while cursor and len(found) < limit:
        data = get("https://api.openalex.org/works", {**params, "cursor": cursor}).json()
        found += [openalex_record(work, "given by OpenAlex") for work in data["results"]]
        cursor = data["meta"].get("next_cursor") if data["results"] else None
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
        time.sleep(1)  # one request a second
    return found


def from_arxiv(keyword, limit, years):
    query = " AND ".join(f"all:{word}" for word in re.findall(r"[\w-]+", keyword))
    if years:
        query += f" AND submittedDate:[{years[0]}01010000 TO {years[1]}12312359]"
    found = []
    for start in range(0, limit, 100):
        if start:
            time.sleep(3)  # arXiv asks for 3 s between requests
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


class CaptchaWatch(logging.Handler):
    """Notes when scholarly logs that Google answered with a captcha."""

    def __init__(self):
        super().__init__()
        self.seen = threading.Event()

    def emit(self, record):
        if "captcha" in record.getMessage().lower():
            self.seen.set()


class ScholarBlocked(Exception):
    """Google Scholar stopped answering; .records holds what it gave before."""

    def __init__(self, reason, records):
        super().__init__(reason)
        self.records = records


def crossref_by_title(title):
    """The Crossref item whose title matches this one (score >= 0.9) and the score, or None."""
    items = get("https://api.crossref.org/works", {
        "query.bibliographic": title, "rows": 3, "select": CROSSREF_FIELDS,
        **mailto()}).json()["message"]["items"]
    for item in items:
        score = difflib.SequenceMatcher(None, simple(title), simple(first(item.get("title")))).ratio()
        if score >= 0.9:
            return item, score
    return None


def from_google_scholar(keyword, limit, years):
    try:
        from scholarly import scholarly
    except ImportError as exc:
        raise ScholarBlocked(f"scholarly cannot be imported ({exc})", [])

    results, errors = [], []
    year_range = {"year_low": years[0], "year_high": years[1]} if years else {}

    def run():
        try:
            for result in scholarly.search_pubs(keyword, **year_range):
                results.append(result)
                if len(results) >= limit:
                    break
        except Exception as exc:  # scholarly raises many kinds of errors when blocked
            errors.append(exc)

    # When Google answers with a captcha, scholarly only logs it and keeps
    # retrying for minutes; watch its log so we can stop at once instead.
    captcha = CaptchaWatch()
    log = logging.getLogger("scholarly")
    log.addHandler(captcha)
    log.setLevel(logging.INFO)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    end = time.time() + SCHOLAR_TIMEOUT
    while worker.is_alive() and time.time() < end and not captcha.seen.is_set():
        worker.join(0.5)
    log.removeHandler(captcha)

    found = []
    for result in list(results):
        bib = result.get("bib", {})
        title, year = bib.get("title", ""), bib.get("pub_year", "")
        # Scholar shortens authors and venues, so only title and year are kept;
        # fill_details() then looks the rest up by DOI.
        doi = clean_doi(" ".join(filter(None, (result.get("pub_url"), result.get("eprint_url")))))
        if doi:
            found.append(record(doi, title, year, basis="in the Google Scholar result's link"))
            continue
        try:
            match = crossref_by_title(title)
        except requests.RequestException:
            match = None
        if match:
            item, score = match
            found.append(crossref_record(item, f"Crossref title match {score:.2f} (Google Scholar result)"))

    if captcha.seen.is_set():
        raise ScholarBlocked("Google asked for a captcha (it blocks scripts for a while)", found)
    if worker.is_alive():
        raise ScholarBlocked(f"no answer after {SCHOLAR_TIMEOUT} s", found)
    if errors:
        raise ScholarBlocked(f"blocked ({errors[0].__class__.__name__})", found)
    return found


# (name shown, name in the job's search.sources, function)
SOURCES = [
    ("OpenAlex", "openalex", from_openalex),
    ("Crossref", "crossref", from_crossref),
    ("Semantic Scholar", "semanticscholar", from_semantic_scholar),
    ("arXiv", "arxiv", from_arxiv),
    ("Google Scholar", None, from_google_scholar),  # not a WebScraping source: always asked
]


# ---------------- table ----------------

def new_row(doi):
    return {"doi": doi, **{f: "" for f in DETAILS}, **{s: set() for s in SETS}}


def fill(row, rec, label):
    """Fill the row's empty title/year/authors/venue from rec."""
    filled = False
    for field in DETAILS:
        if not row[field] and rec[field]:
            row[field] = rec[field]
            filled = True
    if filled:
        row["details_from"].add(label)


def add_all(rows, records, source, keyword):
    """Add records to rows; return how many DOIs are new."""
    new = 0
    for rec in records:
        doi = rec["doi"]
        if not doi:
            continue
        if doi not in rows:
            rows[doi] = new_row(doi)
            new += 1
        row = rows[doi]
        row["keywords"].add(keyword)
        row["found_by"].add(source)
        row["doi_basis"].add(rec["basis"])
        fill(row, rec, source)
    return new


def fill_details(rows):
    """Look up by DOI the titles, years, authors and venues no source gave."""
    missing = [doi for doi, row in rows.items() if not all(row[f] for f in DETAILS)]
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


def load(path):
    rows = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as file:
            for line in csv.DictReader(file):
                row = {column: line.get(column) or "" for column in COLUMNS}
                for column in SETS:
                    row[column] = set(filter(None, row[column].split("; ")))
                for field in DETAILS:
                    if row[field] == NOT_LISTED:
                        row[field] = ""  # try again this run
                rows[row["doi"]] = row
    return rows


def save(rows, path):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        for row in rows.values():
            out = dict(row)
            for column in SETS:
                out[column] = "; ".join(sorted(row[column]))
            for field in DETAILS:
                out[field] = row[field] or NOT_LISTED
            out["details_from"] = out["details_from"] or "only the DOI was found"
            out["link"] = "https://doi.org/" + row["doi"]
            writer.writerow(out)
    temporary.replace(path)  # never leaves a half-written CSV


# ---------------- main ----------------

def main():
    parser = argparse.ArgumentParser(description="Collect DOIs for keywords into a CSV file.")
    parser.add_argument("keywords", nargs="*",
                        help='e.g. "solid electrolyte" "LLZO garnet" (default: the queries of the job file)')
    parser.add_argument("--job", type=Path, default=JOB_FILE,
                        help="job file whose queries, years, sources and max_per_query are used "
                             "(default: configs/sse.yaml)")
    parser.add_argument("--max", type=int,
                        help=f"results asked from each source per keyword "
                             f"(default: the job's max_per_query, else {PER_SOURCE})")
    parser.add_argument("--out", type=Path, default=OUTPUT, help=f"CSV file (default: Fetch_DOIs/{OUTPUT.name})")
    parser.add_argument("--no-scholar", action="store_true", help="skip Google Scholar")
    args = parser.parse_args()

    if not args.job.exists() and args.job != JOB_FILE:
        sys.exit(f"There is no job file {args.job}")
    job = load_job(args.job)
    set_contact(os.environ.get("MME_EMAIL") or job.get("email", ""))

    keywords = args.keywords or job.get("queries") or [
        k.strip() for k in input("Keywords, separated by commas: ").split(",") if k.strip()
    ]
    if not keywords:
        sys.exit("No keywords given.")
    years = job.get("years")
    limit = args.max or job.get("max") or PER_SOURCE

    wanted = job.get("sources")
    sources = [(name, search) for name, key, search in SOURCES
               if (key is None and not args.no_scholar) or (key and (not wanted or key in wanted))]

    origin = "the command line" if args.keywords else args.job
    print(f"{len(keywords)} keywords from {origin}; "
          f"{f'years {years[0]}-{years[1]}' if years else 'all years'}; "
          f"up to {limit} results per source; sources: {', '.join(name for name, _ in sources)}")

    rows = load(args.out)
    before = len(rows)
    for number, keyword in enumerate(keywords, 1):
        print(f"\n=== [{number}/{len(keywords)}] {keyword}")
        for name, search in list(sources):
            asked = min(limit, SCHOLAR_MAX) if name == "Google Scholar" else limit
            try:
                found = search(keyword, asked, years)
            except ScholarBlocked as exc:
                found = exc.records
                sources.remove((name, search))
                print(f"  {name}: {exc}; not asked again in this run")
            except Exception as exc:  # one failing source must not stop the others
                print(f"  {name}: failed ({exc.__class__.__name__}: {exc})")
                continue
            new = add_all(rows, found, name, keyword)
            print(f"  {name}: {len(found)} DOIs ({new} new)")
        save(rows, args.out)

    print("\nLooking up missing titles, years, authors and venues by DOI...")
    fill_details(rows)
    save(rows, args.out)
    print(f"\n{len(rows) - before} new DOIs, {len(rows)} in total, saved in {args.out}")


if __name__ == "__main__":
    main()
