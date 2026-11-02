# WebScraping/job.py
"""The job file of the web project: what to search for, which papers to keep, where to put them
and which data to extract. Plain YAML. A key the loader does not know is an error rather than
being ignored — a misspelled `min_score` would otherwise quietly keep its default."""

import difflib
import json
import os
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import yaml

from LocalExtraction.config import PROPERTY_ALIASES, SchemaConfig

# The keys and the contact address live next to this file: WebScraping/averageScrap/.env (git-ignored).
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
DEFAULT_FOLDER = os.path.join("WebScraping", "papers")
# What the .env file may hold, in the order the settings window shows it: (variable, what it is, secret?).
ENV_SETTINGS = (
    ("MME_EMAIL", "Contact email (sent to OpenAlex, Crossref and Unpaywall, nowhere else)", False),
    ("ELSEVIER_API_KEY", "Elsevier API key (Elsevier's full texts, and Scopus)", True),
    ("ELSEVIER_INSTTOKEN", "Elsevier institutional token (only if Elsevier gave you one)", True),
    ("WILEY_TDM_TOKEN", "Wiley text-and-data-mining token", True),
    ("OPENALEX_API_KEY", "OpenAlex API key (optional)", True),
    ("SEMANTIC_SCHOLAR_API_KEY", "Semantic Scholar API key (optional: steadier)", True),
    ("CORE_API_KEY", "CORE API key (repository full texts: search and copies)", True),
    ("SPRINGER_NATURE_API_KEY", "Springer Nature API key (search, abstracts of Springer and Nature papers)", True),
    ("ADS_API_TOKEN", "NASA ADS token (physics literature, arXiv versions of journal papers)", True),
    ("IEEE_API_KEY", "IEEE Xplore API key", True),
    ("WOS_API_KEY", "Web of Science Starter API key", True),
)
# Where each key is had — all of them free.
KEY_SIGNUP = {
    "ELSEVIER_API_KEY": "https://dev.elsevier.com/ → I want an API key (create it on your university's network)",
    "WILEY_TDM_TOKEN": "https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining",
    "SEMANTIC_SCHOLAR_API_KEY": "https://www.semanticscholar.org/product/api#api-key-form",
    "CORE_API_KEY": "https://core.ac.uk/services/api → Register now",
    "SPRINGER_NATURE_API_KEY": "https://dev.springernature.com/ → Sign up (the Basic plan)",
    "ADS_API_TOKEN": "https://ui.adsabs.harvard.edu/ → create an account, then Settings → API Token",
    "IEEE_API_KEY": "https://developer.ieee.org/ → Register",
    "WOS_API_KEY": "https://developer.clarivate.com/apis/wos-starter → Subscribe (Free Trial: 50 requests a day)",
}


class KeyGroup(NamedTuple):
    """The settings one organization issues, as the window shows them: one card each."""
    organization: str
    opens: str                          # what its key gives access to
    used_by: str                        # which web method uses it
    fields: Tuple[Tuple[str, str], ...]  # (variable of the .env file, its label)
    signup: str = ""                    # where a key is had: a link, then what to do there


_METHOD_1, _BOTH = "Search open sources (method 1)", "both methods (Search open sources and moukhlij4scraping)"
# Every variable of ENV_SETTINGS is in exactly one group (WebScraping/tests/test_keys.py checks it).
KEY_GROUPS = (
    KeyGroup("Your contact e-mail", "Sent to OpenAlex, Crossref and Unpaywall only, as the polite way to ask: "
             "Unpaywall needs one; OpenAlex and Crossref answer faster with one.", _BOTH, (("MME_EMAIL", "E-mail"),)),
    KeyGroup("Elsevier", "Full texts of Elsevier journals (ScienceDirect), and the Scopus search.", _METHOD_1,
             (("ELSEVIER_API_KEY", "API key"), ("ELSEVIER_INSTTOKEN", "Institutional token (only if Elsevier gave you one)")),
             KEY_SIGNUP["ELSEVIER_API_KEY"]),
    KeyGroup("Wiley", "Full texts of Wiley journals, for text and data mining.", _METHOD_1,
             (("WILEY_TDM_TOKEN", "Text-and-data-mining token"),), KEY_SIGNUP["WILEY_TDM_TOKEN"]),
    KeyGroup("OpenAlex", "The main search index. Without a key it gives the first 100 results of each search, on "
             "a daily budget shared with your network; a free key gives every result and a budget of its own.", _BOTH,
             (("OPENALEX_API_KEY", "API key (optional)"),), "https://openalex.org/settings/api"),
    KeyGroup("Semantic Scholar", "Searches and abstracts. It works without a key; one makes it steadier.", _BOTH,
             (("SEMANTIC_SCHOLAR_API_KEY", "API key (optional)"),), KEY_SIGNUP["SEMANTIC_SCHOLAR_API_KEY"]),
    KeyGroup("CORE", "Full texts of the world's repositories: their search, and copies of the papers.", _METHOD_1,
             (("CORE_API_KEY", "API key"),), KEY_SIGNUP["CORE_API_KEY"]),
    KeyGroup("Springer Nature", "Search and abstracts of Springer, Nature and BMC papers.", _METHOD_1,
             (("SPRINGER_NATURE_API_KEY", "API key"),), KEY_SIGNUP["SPRINGER_NATURE_API_KEY"]),
    KeyGroup("NASA ADS", "Physics literature, and the arXiv version of journal papers.", _METHOD_1,
             (("ADS_API_TOKEN", "API token"),), KEY_SIGNUP["ADS_API_TOKEN"]),
    KeyGroup("IEEE Xplore", "Search of IEEE journals and conferences.", _METHOD_1,
             (("IEEE_API_KEY", "API key"),), KEY_SIGNUP["IEEE_API_KEY"]),
    KeyGroup("Web of Science (Clarivate)", "The Web of Science Starter search (free trial: 50 requests a day).",
             _METHOD_1, (("WOS_API_KEY", "Starter API key"),), KEY_SIGNUP["WOS_API_KEY"]),
)
# Where candidates are searched for (WebScraping/sources/ says what each one is). Those that need a
# key are skipped, with a line saying so, until the key is in WebScraping/averageScrap/.env.
SOURCES = ("openalex", "arxiv", "crossref", "semanticscholar", "europepmc", "openaire", "doaj", "jstage", "core",
           "springernature", "scopus", "ads", "ieee", "wos")
# Who is asked, in this order, for the abstract of a paper its search record came without (screening
# reads the title and the abstract). Springer Nature only knows its own papers, IEEE its own, and
# Scopus gives abstracts only on the network of the institution its key belongs to.
ABSTRACT_SOURCES = ("openaire", "crossref", "europepmc", "semanticscholar", "springernature", "scopus", "core",
                    "ads", "ieee")
# Where a legal copy is looked for, in this order (WebScraping/resolve.py says what each one is). "elsevier"
# and "wiley" only apply to those publishers' papers and only with ELSEVIER_API_KEY / WILEY_TDM_TOKEN;
# "unpaywall" wants a contact email; "core" and "ads" their keys; every other source needs nothing but a
# network connection.
RESOLVERS = ("elsevier", "wiley", "aps", "openalex", "unpaywall", "arxiv", "pmc", "osti", "hal",
             "semanticscholar", "ads", "openaire", "core", "crossref")
# How the window names them.
LABELS = {
    "openalex": "OpenAlex", "arxiv": "arXiv", "crossref": "Crossref", "semanticscholar": "Semantic Scholar",
    "europepmc": "Europe PMC", "openaire": "OpenAIRE", "doaj": "DOAJ", "jstage": "J-STAGE", "core": "CORE",
    "springernature": "Springer Nature", "scopus": "Scopus", "ads": "NASA ADS", "ieee": "IEEE Xplore",
    "wos": "Web of Science", "elsevier": "Elsevier", "wiley": "Wiley", "aps": "APS", "unpaywall": "Unpaywall",
    "pmc": "PubMed Central", "osti": "OSTI", "hal": "HAL",
}
# The setting of the .env file a source or a copy source cannot work without (all the others need none).
NEEDS = {
    "scopus": "ELSEVIER_API_KEY", "core": "CORE_API_KEY", "springernature": "SPRINGER_NATURE_API_KEY",
    "ads": "ADS_API_TOKEN", "ieee": "IEEE_API_KEY", "wos": "WOS_API_KEY", "elsevier": "ELSEVIER_API_KEY",
    "wiley": "WILEY_TDM_TOKEN", "unpaywall": "MME_EMAIL",
}
# The numbers of a job a person may set, and their bounds (the window and the loader both hold them).
LIMITS = {
    "max_per_query": (1, 1000),   # results asked of each source for each query
    "min_score": (0, 20),         # the screening score a paper needs
    "workers": (1, 8),            # downloads at once: more is impolite to the servers
    "max_pdf_mb": (1, 500),       # the largest PDF accepted
    "years": (1900, 2100),
}
# The folder of the downloaded PDFs is not a setting a person changes: both web methods, the ledger
# and "Delete outputs" all look for the papers there.


@dataclass
class SearchConfig:
    queries: List[str] = field(default_factory=list)
    ids_file: str = ""  # optional text file: one DOI, DOI link or arXiv id per line
    years: Optional[Tuple[int, int]] = None
    sources: List[str] = field(default_factory=lambda: list(SOURCES))
    max_per_query: int = 200  # candidates asked of each source for each query
    include_preprints: bool = True
    arxiv_categories: List[str] = field(
        default_factory=lambda: ["cond-mat.mtrl-sci", "physics.chem-ph", "physics.comp-ph"])
    abstract_sources: List[str] = field(default_factory=lambda: list(ABSTRACT_SOURCES))  # [] = ask nobody


@dataclass
class ScreenConfig:
    topic_words: List[str] = field(default_factory=list)     # the field: at least one must appear
    property_words: List[str] = field(default_factory=list)  # the data: at least one must appear
    exclude_words: List[str] = field(default_factory=list)   # each one found costs points
    min_score: float = 2.0
    review: bool = True  # stop after screening so the list can be checked before anything is fetched
    # Also propose a paper no open copy is known for yet: the fetch stage then asks the repositories
    # for one, and lists the paper as closed (to get by hand) when none has it.
    propose_closed: bool = False


@dataclass
class FetchConfig:
    folder: str = DEFAULT_FOLDER
    sources: List[str] = field(default_factory=lambda: list(RESOLVERS))
    workers: int = 3
    max_pdf_mb: int = 60


@dataclass
class ExtractConfig:
    properties: List[str] = field(default_factory=list)  # the wished data; empty = every property
    require_material: bool = False  # drop a value that cannot be tied to a material


@dataclass
class Job:
    name: str = "web"
    contact_email: str = ""
    search: SearchConfig = field(default_factory=SearchConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)

    def email(self) -> str:
        """The address sent to OpenAlex, Crossref and Unpaywall as the polite-pool identifier: the job's,
        else the MME_EMAIL environment variable. Never anything else."""
        return self.contact_email or os.environ.get("MME_EMAIL", "")


# Names the settings had before the project was called MoukhlijMatExtract: a .env that still uses them works.
_FORMER_NAMES = {"AUTOMATEXTRACT_EMAIL": "MME_EMAIL"}


def load_env(path: str = ENV_PATH) -> int:
    """Puts the KEY=VALUE lines of a .env file into the environment; what is already set wins and an
    empty value is ignored. It is where the secrets live (the keys of ENV_SETTINGS) and the contact
    address (MME_EMAIL); the file is git-ignored.
    Returns how many variables it set."""
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip("\"'")
            name = _FORMER_NAMES.get(name, name)
            if name and value and name not in os.environ:
                os.environ[name] = value
                count += 1
    return count


def read_env(path: str = ENV_PATH) -> Dict[str, str]:
    """The KEY=VALUE lines of a .env file as they stand, whatever the environment holds."""
    values: Dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                name, found, value = line.strip().partition("=")
                if found and name.strip() and not name.lstrip().startswith("#"):
                    values[name.strip()] = value.strip().strip("\"'")
    return values


def save_env(values: Dict[str, str], path: str = ENV_PATH) -> None:
    """Writes settings into a .env file and into the environment of this run: a line that names the
    variable is replaced, a new variable is added at the end, every other line (and comment) is
    kept; an empty value unsets the variable. The file is created readable by its owner only."""
    for name, value in values.items():
        if "\n" in value or "\r" in value or "=" in name or not name.strip():
            raise ValueError(f"{name}: a setting is one line of text")
    lines = ["# Keys and contact address of MoukhlijMatExtract. This file is git-ignored: keep it to yourself."]
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    left = {name: value.strip() for name, value in values.items()}
    for index, line in enumerate(lines):
        name = line.partition("=")[0].strip()
        if "=" in line and name in left:
            lines[index] = f"{name}={left.pop(name)}"
    lines += [f"{name}={value}" for name, value in left.items()]
    part = path + ".part"
    with open(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(part, path)
    for name, value in values.items():
        if value.strip():
            os.environ[name] = value.strip()
        else:
            os.environ.pop(name, None)


HEADER = "# Job file of MoukhlijMatExtract's web project (see the README for every setting)."
# The lists of words a person groups under "# headings" (kept when the job is saved again).
WORD_LISTS = ("search.queries", "screen.topic_words", "screen.property_words", "screen.exclude_words")


def _scalar(key: str, value: Any, indent: str) -> List[str]:
    """`key: value` as YAML lines, a list on one line (wrapped) as the shipped job writes it."""
    text = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True, default_flow_style=True, width=110)
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    lines = text.splitlines()
    return [indent + lines[0]] + [indent + "  " + line.strip() for line in lines[1:]]


def dump_job(job: Job, headings: Optional[Dict[str, List[str]]] = None,
             notes: Optional[Dict[str, List[str]]] = None) -> str:
    """The job as the text of a job file: what `load_job` reads back as the same job.

    The comments a person wrote are kept when given: `notes` are the comment lines above a setting
    ("screen.exclude_words" → its lines), `headings` the "# …" lines among the words of a list
    (`read_comments` reads both from a file). A heading is kept only between words it was among."""
    headings, notes = headings or {}, notes or {}
    out = [HEADER, ""]

    def note(name: str, indent: str) -> None:
        out.extend(indent + line for line in notes.get(name, []))

    for key in ("name", "contact_email"):
        note(key, "")
        out.extend(_scalar(key, getattr(job, key), ""))
    for section in ("search", "screen", "fetch", "extract"):
        out.append("")
        note(section, "")
        out.append(f"{section}:")
        for f in fields(getattr(job, section)):
            name, value = f"{section}.{f.name}", getattr(getattr(job, section), f.name)
            if name == "search.years":
                if not value:
                    continue
                value = list(value)
            note(name, "  ")
            if name in WORD_LISTS and value:
                out.append(f"  {f.name}:")
                for entry in _with_headings(value, headings.get(name, [])):
                    out.append(f"    {entry}" if entry.startswith("#") else
                               "    - " + json.dumps(entry, ensure_ascii=False))
            else:
                out.extend(_scalar(f.name, value, "  "))
    return "\n".join(out) + "\n"


def _with_headings(words: List[str], layout: List[str]) -> List[str]:
    """The words, with the headings of `layout` (an earlier list: words and "# …" lines) put back
    before the first word that followed them there. Headings whose words are all gone are dropped."""
    if not layout:
        return list(words)
    before: Dict[str, List[str]] = {}
    waiting: List[str] = []
    for entry in layout:
        if entry.startswith("#"):
            waiting.append(entry)
        else:
            if waiting and entry not in before:
                before[entry] = waiting
            waiting = []
    out: List[str] = []
    for word in words:
        out.extend(before.pop(word, []))
        out.append(word)
    return out


def read_comments(path: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """The comments of a job file: (headings, notes) as `dump_job` takes them back. Only comments on
    lines of their own are read (one after a value is not kept)."""
    headings: Dict[str, List[str]] = {}
    notes: Dict[str, List[str]] = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return headings, notes
    section, current, pending = "", "", []
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if not stripped:
            continue
        if stripped.startswith("#"):
            if stripped == HEADER:
                continue
            if current in WORD_LISTS and indent >= 4:
                headings[current].append(stripped)
            else:
                pending.append(stripped)
            continue
        if stripped.startswith("- ") and current in WORD_LISTS:
            try:
                word = yaml.safe_load(stripped[2:])
            except yaml.YAMLError:
                continue
            if isinstance(word, str) and word.strip():
                headings[current].append(word.strip())
            continue
        key = stripped.partition(":")[0].strip()
        if indent == 0:
            section = key if key in ("search", "screen", "fetch", "extract") else ""
            current = key
        elif section and indent == 2:
            current = f"{section}.{key}"
        else:
            continue
        if pending:
            notes[current] = pending
            pending = []
        if current in WORD_LISTS:
            headings[current] = []
    # A list of words a heading stands in only counts if its words are the words of the job.
    return {name: layout for name, layout in headings.items() if any(e.startswith("#") for e in layout)}, notes


def _build(cls, data: Any, where: str):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(f"{where}: expected a mapping of settings, got {type(data).__name__}")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        hints = [f"{key!r} (did you mean {difflib.get_close_matches(key, known, 1)[0]!r}?)"
                 if difflib.get_close_matches(key, known, 1) else repr(key) for key in unknown]
        raise ValueError(f"{where}: unknown setting {', '.join(hints)}; known: {', '.join(sorted(known))}")
    return cls(**data)


def _words(value: Any, where: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: expected a list of text items")
    return [v.strip() for v in value if v.strip()]


def load_job(path: str) -> Job:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: a job file is a mapping of settings")

    sections = {name: raw.pop(name, None) for name in ("search", "screen", "fetch", "extract")}
    job = _build(Job, {k: v for k, v in raw.items()}, path)
    job.search = _build(SearchConfig, sections["search"], f"{path}: search")
    job.screen = _build(ScreenConfig, sections["screen"], f"{path}: screen")
    job.fetch = _build(FetchConfig, sections["fetch"], f"{path}: fetch")
    job.extract = _build(ExtractConfig, sections["extract"], f"{path}: extract")

    s = job.search
    s.queries = _words(s.queries, "search.queries")
    s.sources = _words(s.sources, "search.sources")
    s.arxiv_categories = _words(s.arxiv_categories, "search.arxiv_categories")
    s.abstract_sources = _words(s.abstract_sources, "search.abstract_sources")
    bad = [name for name in s.sources if name not in SOURCES]
    if bad:
        raise ValueError(f"search.sources: unknown {bad}; known: {list(SOURCES)}")
    bad = [name for name in s.abstract_sources if name not in ABSTRACT_SOURCES]
    if bad:
        raise ValueError(f"search.abstract_sources: unknown {bad}; known: {list(ABSTRACT_SOURCES)}")
    if s.years is not None:
        if not (isinstance(s.years, (list, tuple)) and len(s.years) == 2 and all(isinstance(y, int) for y in s.years)
                and s.years[0] <= s.years[1]):
            raise ValueError("search.years: expected [first_year, last_year], e.g. [2015, 2026]")
        if not all(LIMITS["years"][0] <= y <= LIMITS["years"][1] for y in s.years):
            raise ValueError(f"search.years: years from {LIMITS['years'][0]} to {LIMITS['years'][1]}")
        s.years = (s.years[0], s.years[1])
    if not s.queries and not s.ids_file:
        raise ValueError("search: give at least one query or an ids_file")

    c = job.screen
    c.topic_words, c.property_words, c.exclude_words = (
        _words(c.topic_words, "screen.topic_words"), _words(c.property_words, "screen.property_words"),
        _words(c.exclude_words, "screen.exclude_words"))

    f = job.fetch
    f.sources = _words(f.sources, "fetch.sources")
    bad = [name for name in f.sources if name not in RESOLVERS]
    if bad:
        raise ValueError(f"fetch.sources: unknown {bad}; known: {list(RESOLVERS)}")
    for where, value, limit in (("search.max_per_query", s.max_per_query, "max_per_query"),
                                ("screen.min_score", c.min_score, "min_score"),
                                ("fetch.workers", f.workers, "workers"), ("fetch.max_pdf_mb", f.max_pdf_mb, "max_pdf_mb")):
        low, high = LIMITS[limit]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"{where}: must be a number from {low} to {high}")

    e = job.extract
    # A job file written for an earlier version may still ask for a property under its old name.
    e.properties = list(dict.fromkeys(PROPERTY_ALIASES.get(p, p) for p in _words(e.properties, "extract.properties")))
    known = {prop for props in SchemaConfig.SCHEMA.values() for prop in props}
    bad = [p for p in e.properties if p not in known]
    if bad:
        hints = [f"{p!r} (did you mean {difflib.get_close_matches(p, known, 1)[0]!r}?)"
                 if difflib.get_close_matches(p, known, 1) else repr(p) for p in bad]
        raise ValueError(f"extract.properties: unknown {', '.join(hints)}")
    return job
