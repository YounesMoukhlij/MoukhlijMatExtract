# WebScraping/sources/wos.py
"""Web of Science, through its Starter API: titles, DOIs and journals of the Web of Science Core
Collection (no abstracts: `search.abstract_sources` finds them). Key: WOS_API_KEY — the free trial
plan (https://developer.clarivate.com/apis/wos-starter, "Subscribe") allows 50 requests a day;
your library's subscription, many more."""

import re
from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, in_years, plain, year_of

API = "https://api.clarivate.com/apis/wos-starter/v1/documents"
_PAGE = 50
_TERM = re.compile(r'"([^"]+)"|(\S+)')


def build_query(query: str, years: Optional[Tuple[int, int]]) -> str:
    """Every word (or "phrase") of the query in the topic (title, abstract, keywords), within the years."""
    terms = " AND ".join(f'"{phrase}"' if phrase else word for phrase, word in _TERM.findall(query))
    return f"TS=({terms})" + (f" AND PY=({years[0]}-{years[1]})" if years else "")


def candidate_from_hit(hit: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    ids = hit.get("identifiers") or {}
    doi = normalize_doi(ids.get("doi") or "")
    title = plain(hit.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    source = hit.get("source") or {}
    kinds = [kind.lower() for kind in hit.get("types") or []]
    return Candidate(
        key=key, doi=doi, title=title, year=year_of(source.get("publishYear")), journal=source.get("sourceTitle") or "",
        authors=[a.get("displayName", "") for a in ((hit.get("names") or {}).get("authors") or [])[:8]],
        work_type="review" if "review" in kinds else "article", found_by=[found_by])


class WebOfScience(Source):
    name, label = "wos", "Web of Science"
    key_name = "WOS_API_KEY"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        page, seen = 1, 0
        while seen < limit:
            size = min(_PAGE, limit - seen)
            data = self.client.get_json(API, params={"db": "WOS", "q": build_query(query, years), "limit": size,
                                                     "page": page}, headers={"X-ApiKey": self.key})
            hits = data.get("hits") or []
            for hit in hits:
                candidate = candidate_from_hit(hit, f"wos: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(hits) < size:
                return
            page += 1
