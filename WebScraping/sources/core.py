# WebScraping/sources/core.py
"""CORE: the full texts of the world's open repositories (university archives, preprint servers,
open journals). Its search reads the full text, not only the title and abstract, so it finds a
paper whose abstract does not name the property. Free key: CORE_API_KEY
(https://core.ac.uk/services/api, "Register now")."""

import re
from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://api.core.ac.uk/v3/search/works"
_TERM = re.compile(r'"([^"]+)"|(\S+)')
_MAX_OFFSET = 10000


def build_query(query: str) -> str:
    """CORE joins the words of a query with OR; a query here means all of its words (a phrase in
    quotes stays a phrase): "argyrodite ionic conductivity" -> argyrodite AND ionic AND conductivity."""
    return " AND ".join(f'"{phrase}"' if phrase else word for phrase, word in _TERM.findall(query))


def candidate_from_work(work: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(work.get("doi") or "")
    preprint_id = arxiv_id(str(work.get("arxivId") or ""))
    title = plain(work.get("title"))
    key = candidate_key(doi, preprint_id, title)
    if not key:
        return None
    download = work.get("downloadUrl") or ""
    journals = [j.get("title") for j in work.get("journals") or [] if j.get("title")]
    kind = (work.get("documentType") or "").lower()
    abstract = abstract_or_nothing(work.get("abstract"))
    return Candidate(
        key=key, doi=doi, arxiv_id=preprint_id, title=title, abstract=abstract, abstract_from="core" if abstract else "",
        year=int(work.get("yearPublished") or 0) or year_of(work.get("publishedDate")),
        journal=journals[0] if journals else "", publisher=work.get("publisher") or "",
        authors=[a.get("name", "") for a in (work.get("authors") or [])[:8]],
        work_type="thesis" if "thesis" in kind else "article", oa_status="green" if download else "",
        oa_urls=[download] if download else [], found_by=[found_by])


class Core(Source):
    name, label = "core", "CORE"
    key_name = "CORE_API_KEY"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        # CORE's year syntax is not dependable, so the years are checked here; at most `limit` results
        # are read, whatever their year.
        offset, text = 0, build_query(query)
        while offset < min(limit, _MAX_OFFSET):
            size = min(100, limit - offset)
            data = self.client.get_json(API, params={"q": text, "limit": size, "offset": offset}, headers=self._headers())
            works = data.get("results") or []
            for work in works:
                candidate = candidate_from_work(work, f"core: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
            if len(works) < size:
                return
            offset += len(works)

    def records(self, doi: str, limit: int = 3) -> Iterator[Dict[str, Any]]:
        """CORE's records of one DOI (one per repository that holds the paper, merged or not)."""
        data = self.client.get_json(API, params={"q": f'doi:"{doi}"', "limit": limit}, headers=self._headers())
        for work in data.get("results") or []:
            if normalize_doi(work.get("doi") or "") == doi:
                yield work

    def abstract(self, candidate: Candidate) -> str:
        return max((abstract_or_nothing(work.get("abstract")) for work in self.records(candidate.doi)), key=len, default="")
