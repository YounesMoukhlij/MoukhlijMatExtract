# web/ids.py
"""Identifiers of a paper — DOI, arXiv id, title — and the single key the ledger files it under."""

import hashlib
import re
import unicodedata

_DOI_REGEX = re.compile(r'10\.\d{4,9}/[^\s"<>]+', re.IGNORECASE)
_ARXIV_NEW = re.compile(r'(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)')
_ARXIV_OLD = re.compile(r'(?<![\w/.-])([a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?!\d)')

# arXiv gives every preprint a DOI of its own: "10.48550/arXiv.2411.06804".
ARXIV_DOI_PREFIX = "10.48550/arxiv."


def normalize_doi(text: str) -> str:
    """The bare, lower-case DOI inside a DOI, a doi.org link or "doi:..." text; "" if there is none."""
    match = _DOI_REGEX.search(text or "")
    if not match:
        return ""
    doi = match.group().rstrip('.,;:\'"')
    # A closing bracket is only punctuation when nothing opened it: 10.1016/S0022-2860(96)01234-5.
    while doi and doi[-1] in ")]}" and doi.count(")") + doi.count("]") + doi.count("}") > \
            doi.count("(") + doi.count("[") + doi.count("{"):
        doi = doi[:-1].rstrip('.,;:\'"')
    return doi.lower()


def arxiv_id(text: str) -> str:
    """The arXiv identifier (no version) in an arXiv link, "arXiv:..." text, an arXiv DOI or a bare
    id; "" if there is none. A DOI that is not an arXiv one is never searched for an id."""
    text = (text or "").strip()
    doi = normalize_doi(text)
    if doi:
        return doi[len(ARXIV_DOI_PREFIX):] if doi.startswith(ARXIV_DOI_PREFIX) else ""
    match = _ARXIV_NEW.search(text) or _ARXIV_OLD.search(text)
    return match.group(1) if match else ""


# The American Physical Society's interface for programs only knows a DOI in the journal's own
# spelling ("10.1103/PhysRevB.99.094106"), which the lower-case form used everywhere else loses.
_APS_JOURNALS = ("PhysRevAccelBeams", "PhysRevApplied", "PhysRevFluids", "PhysRevMaterials", "PhysRevPhysEducRes",
                 "PhysRevResearch", "PhysRevLett", "PhysRevSTAB", "PhysRevSTPER", "PhysRevA", "PhysRevB", "PhysRevC",
                 "PhysRevD", "PhysRevE", "PhysRevX", "PhysRev", "PRXEnergy", "PRXQuantum", "PRXLife", "RevModPhys")


def aps_doi(doi: str) -> str:
    """An APS DOI as the journal spells it: "10.1103/physrevb.99.094106" -> "10.1103/PhysRevB.99.094106".
    A DOI of the newer kind ("10.1103/lx5w-x6wl") has no journal in it and is returned as it is."""
    prefix, _, rest = doi.partition("/")
    journal, dot, tail = rest.partition(".")
    spelling = next((name for name in _APS_JOURNALS if name.lower() == journal.lower()), "")
    return f"{prefix}/{spelling}{dot}{tail}" if spelling else doi


def normalize_title(title: str) -> str:
    """Lower case, no accents or punctuation, single spaces — what two copies of a title share."""
    folded = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r'[^a-z0-9]+', ' ', folded.lower()).split())


def candidate_key(doi: str = "", arxiv: str = "", title: str = "") -> str:
    """The stable identity of a paper, whichever identifiers its source knew: its DOI, else its
    arXiv id (an arXiv DOI counts as one, so OpenAlex and arXiv agree on a preprint), else a hash
    of its title. "" when there is nothing to go on."""
    doi = normalize_doi(doi)
    if doi.startswith(ARXIV_DOI_PREFIX):
        arxiv, doi = arxiv or doi[len(ARXIV_DOI_PREFIX):], ""
    if doi:
        return doi
    if arxiv:
        return f"arxiv:{arxiv}"
    normalized = normalize_title(title)
    return f"title:{hashlib.sha1(normalized.encode()).hexdigest()[:12]}" if normalized else ""


def file_stem(key: str) -> str:
    """A file-system-safe name for a key: "10.1016/j.ssi.2020.115234" -> "10.1016_j.ssi.2020.115234".
    The DOI-based name is what keeps a paper's id (the file name is its paper_id) stable across runs."""
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', key).strip('._')
    if len(stem) > 140:
        stem = f"{stem[:120]}_{hashlib.sha1(key.encode()).hexdigest()[:8]}"
    return stem or "paper"
