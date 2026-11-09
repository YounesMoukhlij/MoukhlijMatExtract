# WebScraping/sources/dimensions.py
"""Dimensions (Digital Science): about 140 million publications, with abstracts and open-access
status. Its API is free for non-commercial scientometric research, on application: DIMENSIONS_API_KEY
(https://www.dimensions.ai/scientometric-research/ → apply; the key is then in your account's
"API key" page)."""

import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain

AUTH = "https://app.dimensions.ai/api/auth"
DSL = "https://app.dimensions.ai/api/dsl/v2"
_PAGE = 100
_MAX_SKIP = 1000
_FIELDS = "doi+title+abstract+year+journal+publisher+authors+open_access+linkout+type"
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}


def dsl_string(text: str) -> str:
    """Text as a quoted string of the Dimensions query language."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_query(query: str, years: Optional[Tuple[int, int]], skip: int, limit: int) -> str:
    where = f" where year in [{years[0]}:{years[1]}]" if years else ""
    return (f"search publications in title_abstract_only for {dsl_string(query)}{where} "
            f"return publications[{_FIELDS}] limit {limit} skip {skip}")


def candidate_from_publication(publication: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(publication.get("doi") or "")
    title = plain(publication.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    access = [str(a).lower() for a in publication.get("open_access") or []]
    colour = next((a for a in access if a in _OPEN), "")
    authors: List[str] = [f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip()
                          for a in publication.get("authors") or []]
    kind = (publication.get("type") or "").lower()
    abstract = abstract_or_nothing(publication.get("abstract"))
    publisher = publication.get("publisher") or ""
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="dimensions" if abstract else "",
        year=int(publication.get("year") or 0), journal=(publication.get("journal") or {}).get("title") or "",
        publisher=publisher.get("name", "") if isinstance(publisher, dict) else str(publisher),
        authors=[a for a in authors if a][:8], work_type="preprint" if kind == "preprint" else "article",
        is_preprint=kind == "preprint", oa_status=colour,
        landing_url=publication.get("linkout") or "", found_by=[found_by])


class Dimensions(Source):
    name, label = "dimensions", "Dimensions"
    key_name = "DIMENSIONS_API_KEY"

    def __init__(self, client, contact: str = ""):
        super().__init__(client, contact)
        self._token = ""
        self._lock = threading.Lock()

    def _headers(self) -> Dict[str, str]:
        with self._lock:
            if not self._token:  # the key is traded for a token that is good for a couple of hours
                self._token = self.client.post_json(AUTH, {"key": self.key}).get("token") or ""
        return {"Authorization": f"JWT {self._token}"}

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        skip = 0
        while skip < min(limit, _MAX_SKIP):
            size = min(_PAGE, limit - skip)
            data = self.client.post_json(DSL, data=build_query(query, years, skip, size), headers=self._headers())
            publications = data.get("publications") or []
            for publication in publications:
                candidate = candidate_from_publication(publication, f"dimensions: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
            if len(publications) < size:
                return
            skip += len(publications)
