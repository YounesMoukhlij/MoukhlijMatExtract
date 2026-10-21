# WebScraping/sources/scopus.py
"""Scopus, Elsevier's index of every publisher's journals, with the same free key as Elsevier's
full texts (ELSEVIER_API_KEY). From anywhere the key searches Scopus (titles, DOIs, journals);
abstracts are given only to the institution the key belongs to: from its network, or with
ELSEVIER_INSTTOKEN. It is how the abstracts of Elsevier's papers (which OpenAlex does not carry)
are had."""

import os
import re
from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.ids import candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

SEARCH = "https://api.elsevier.com/content/search/scopus"
ABSTRACT = "https://api.elsevier.com/content/abstract/doi"
_PAGE = 25            # the most one page of the standard view holds
_MAX_OFFSET = 5000    # the most the search hands out for one query
_TERM = re.compile(r'"([^"]+)"|(\S+)')
_COPYRIGHT = re.compile(r'\s*(?:©|\(c\)|Copyright)\s*\d{4}.*$', re.IGNORECASE)


def build_query(query: str) -> str:
    """Every word (or "phrase") in the title, abstract or keywords: TITLE-ABS-KEY(a AND "b c")."""
    terms = [f'"{phrase}"' if phrase else word for phrase, word in _TERM.findall(query)]
    return f"TITLE-ABS-KEY({' AND '.join(terms)})"


def candidate_from_entry(entry: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    if entry.get("error"):  # how Scopus says "no result"
        return None
    doi = normalize_doi(entry.get("prism:doi") or "")
    title = plain(entry.get("dc:title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    return Candidate(
        key=key, doi=doi, title=title, year=year_of(entry.get("prism:coverDate")),
        journal=entry.get("prism:publicationName") or "",
        authors=[entry["dc:creator"]] if entry.get("dc:creator") else [],
        work_type="review" if (entry.get("subtypeDescription") or "").lower() == "review" else "article",
        found_by=[found_by])


class Scopus(Source):
    name, label = "scopus", "Scopus"
    key_name = "ELSEVIER_API_KEY"

    def _headers(self) -> Dict[str, str]:
        token = os.environ.get("ELSEVIER_INSTTOKEN", "").strip()
        return {"X-ELS-APIKey": self.key, "Accept": "application/json", **({"X-ELS-Insttoken": token} if token else {})}

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, seen = 0, 0
        while seen < limit and start < _MAX_OFFSET:
            size = min(_PAGE, limit - seen)
            params = {"query": build_query(query), "start": start, "count": size,
                      **({"date": f"{years[0]}-{years[1]}"} if years else {})}
            data = self.client.get_json(SEARCH, params=params, headers=self._headers())
            entries = (data.get("search-results") or {}).get("entry") or []
            page = [c for c in (candidate_from_entry(e, f"scopus: {query}") for e in entries) if c]
            for candidate in page:
                if in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(entries) < size or not page:
                return
            start += len(entries)

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(f"{ABSTRACT}/{candidate.doi}", params={"view": "META_ABS"}, headers=self._headers())
        core = (data.get("abstracts-retrieval-response") or {}).get("coredata") or {}
        return abstract_or_nothing(_COPYRIGHT.sub("", plain(core.get("dc:description"))))
