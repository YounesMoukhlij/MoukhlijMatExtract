# web/job.py
"""The job file of the web project: what to search for, which papers to keep, where to put them
and which data to extract. Plain YAML. A key the loader does not know is an error rather than
being ignored — a misspelled `min_score` would otherwise quietly keep its default."""

import difflib
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

import yaml

from config import PROPERTY_ALIASES, SchemaConfig

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
DEFAULT_FOLDER = os.path.join("papers", "web")
# What the .env file may hold, in the order the settings window shows it: (variable, what it is, secret?).
ENV_SETTINGS = (
    ("AUTOMATEXTRACT_EMAIL", "Contact email (sent to OpenAlex and Unpaywall, nowhere else)", False),
    ("ELSEVIER_API_KEY", "Elsevier API key", True),
    ("ELSEVIER_INSTTOKEN", "Elsevier institutional token (only if Elsevier gave you one)", True),
    ("WILEY_TDM_TOKEN", "Wiley text-and-data-mining token", True),
    ("OPENALEX_API_KEY", "OpenAlex API key (optional)", True),
    ("SEMANTIC_SCHOLAR_API_KEY", "Semantic Scholar API key (optional)", True),
)
SOURCES = ("openalex", "arxiv")
# Where a legal copy is looked for, in this order (web/resolve.py says what each one is). "elsevier"
# and "wiley" only apply to those publishers' papers and only with ELSEVIER_API_KEY / WILEY_TDM_TOKEN;
# "unpaywall" wants a contact email; every other source needs nothing but a network connection.
RESOLVERS = ("elsevier", "wiley", "aps", "openalex", "unpaywall", "arxiv", "pmc", "osti", "hal",
             "semanticscholar", "openaire")


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
        """The address sent to OpenAlex/Unpaywall as the polite-pool identifier: the job's, else the
        AUTOMATEXTRACT_EMAIL environment variable. Never anything else."""
        return self.contact_email or os.environ.get("AUTOMATEXTRACT_EMAIL", "")


def load_env(path: str = ENV_PATH) -> int:
    """Puts the KEY=VALUE lines of a .env file into the environment; what is already set wins and an
    empty value is ignored. It is where the secrets live (ELSEVIER_API_KEY, ELSEVIER_INSTTOKEN,
    WILEY_TDM_TOKEN, OPENALEX_API_KEY, SEMANTIC_SCHOLAR_API_KEY) and the contact address
    (AUTOMATEXTRACT_EMAIL); the file is git-ignored.
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
    lines = ["# Keys and contact address of AutoMatExtract. This file is git-ignored: keep it to yourself."]
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


def dump_job(job: Job) -> str:
    """The job as the text of a job file: what `load_job` reads back as the same job. (A job file
    written by hand may carry comments; they are not part of the job and are not kept.)"""
    data: Dict[str, Any] = {"name": job.name, "contact_email": job.contact_email}
    for section in ("search", "screen", "fetch", "extract"):
        data[section] = asdict(getattr(job, section))
    if job.search.years:
        data["search"]["years"] = list(job.search.years)
    else:
        del data["search"]["years"]
    return ("# Job file of AutoMatExtract's web project (see the README for every setting).\n"
            + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110))


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
    bad = [name for name in s.sources if name not in SOURCES]
    if bad:
        raise ValueError(f"search.sources: unknown {bad}; known: {list(SOURCES)}")
    if s.years is not None:
        if not (isinstance(s.years, (list, tuple)) and len(s.years) == 2 and all(isinstance(y, int) for y in s.years)
                and s.years[0] <= s.years[1]):
            raise ValueError("search.years: expected [first_year, last_year], e.g. [2015, 2026]")
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
    if f.workers < 1:
        raise ValueError("fetch.workers: must be at least 1")

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
