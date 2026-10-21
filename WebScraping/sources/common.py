# WebScraping/sources/common.py
"""What the sources share: the base every source builds on (its key, if it needs one), abstracts
and titles cleaned of the markup the services send, the job's years, licences in one spelling."""

import html
import os
import re
from typing import Iterator, Optional, Tuple

from WebScraping.http import PoliteClient
from WebScraping.ledger import Candidate

# What a search record lists beside the copies of a paper: its DOI link, indexes, and sites that are
# either no repository (ResearchGate, Academia) or turn scripts away (the PubMed Central web pages).
NOT_A_COPY = {"doi.org", "dx.doi.org", "pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
              "europepmc.org", "doaj.org", "www.researchgate.net", "www.academia.edu"}
# Shorter than this, an "abstract" is a placeholder ("No abstract available"), not something to screen.
MIN_ABSTRACT = 80

# Markup inside a word or a formula ("Li<sub>6</sub>PS<sub>5</sub>Cl") goes without a trace; any
# other tag (a paragraph, a section title) leaves a space. A tag starts with a letter: "x < 0.5" is text.
_INLINE = re.compile(r'</?(?:[a-z]+:)?(?:sub|sup|inf|i|b|em|strong|italic|bold|span|sc|u|a)\b[^<>]*>', re.IGNORECASE)
_TAG = re.compile(r'</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>')
_HEADING = re.compile(r'^(?:abstract|summary|graphical abstract)\s*[:.]?\s+', re.IGNORECASE)
_CC = re.compile(r'creativecommons\.org/(?:licenses/([a-z-]+)|publicdomain/(zero))', re.IGNORECASE)


def plain(text: object) -> str:
    """Text as a reader sees it: entities decoded, markup removed, one space between words, without
    the "Abstract" heading some services put in front. "" for nothing."""
    if not text:
        return ""
    text = html.unescape(str(text))
    text = _TAG.sub(" ", _INLINE.sub("", text))
    return _HEADING.sub("", " ".join(text.split())).strip()


def abstract_or_nothing(text: object) -> str:
    """An abstract worth screening, or "" for a placeholder."""
    text = plain(text)
    return text if len(text) >= MIN_ABSTRACT else ""


def cc_license(url: str) -> str:
    """A Creative Commons licence link as the other sources spell it:
    ".../licenses/by-nc/4.0/" -> "cc-by-nc", ".../publicdomain/zero/1.0/" -> "cc0"; "" for anything else."""
    match = _CC.search(url or "")
    if not match:
        return ""
    return "cc0" if match.group(2) else f"cc-{match.group(1).lower()}"


def spell_license(text: str) -> str:
    """A Creative Commons licence as the other sources spell it: "CCBYNCND", "CC BY", "cc by-nc-nd"
    and a creativecommons.org link are "cc-by-nc-nd", "cc-by", ... Anything else is kept as the
    service wrote it."""
    text = (text or "").strip()
    linked = cc_license(text)
    if linked:
        return linked
    code = re.sub(r'[\s-]+', '', text.lower())
    return "-".join(re.findall(r'cc|by|nc|nd|sa', code)) if re.fullmatch(r'cc(?:by|nc|nd|sa)+', code) else text


def in_years(year: int, years: Optional[Tuple[int, int]]) -> bool:
    """Whether a paper's year is within the job's; a year the service did not give is kept."""
    return not years or not year or years[0] <= year <= years[1]


def year_of(text: object) -> int:
    """The year in "2024", "2024-05-01" or 2024; 0 when there is none."""
    match = re.search(r'(?<!\d)(1[89]\d\d|20\d\d)(?!\d)', str(text or ""))
    return int(match.group(1)) if match else 0


class Source:
    """A place to search. `search` turns a query into candidates; `abstract` (for a source that can
    also be asked about one paper) gives the abstract of a paper the search found without one.
    A source that needs a key and has none is not used: `available()` says so."""

    name = ""
    key_name = ""          # the WebScraping/.env variable holding its key ("" = it needs none)
    key_required = True    # False: the key only lifts the limits
    label = ""             # its name in messages

    def __init__(self, client: PoliteClient, contact: str = ""):
        self.client, self.contact = client, contact
        self.key = os.environ.get(self.key_name, "").strip() if self.key_name else ""

    def available(self) -> bool:
        return bool(self.key) or not (self.key_name and self.key_required)

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        raise NotImplementedError

    def applies(self, candidate: Candidate) -> bool:
        """Whether `abstract` can be asked about this paper (most services know a paper by its DOI)."""
        return bool(candidate.doi)

    def abstract(self, candidate: Candidate) -> str:
        """The paper's abstract, or "" when the service has none; an error status raises."""
        return ""
