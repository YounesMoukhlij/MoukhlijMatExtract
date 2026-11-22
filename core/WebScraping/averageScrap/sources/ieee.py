# WebScraping/sources/ieee.py
"""IEEE Xplore: the IEEE's journals and conferences (batteries, sensors, devices), with abstracts.
Free key: IEEE_API_KEY (register at https://developer.ieee.org/). 200 requests a day."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
_PAGE = 200
_SKIP = {"standards", "books", "courses"}  # not research articles


def candidate_from_article(article: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    if (article.get("content_type") or "").lower() in _SKIP:
        return None
    doi = normalize_doi(article.get("doi") or "")
    title = plain(article.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    is_open = article.get("access_type") == "OPEN_ACCESS"
    abstract = abstract_or_nothing(article.get("abstract"))
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="ieee" if abstract else "",
        year=year_of(article.get("publication_year")), journal=article.get("publication_title") or "",
        publisher=article.get("publisher") or "IEEE",
        authors=[a.get("full_name", "") for a in ((article.get("authors") or {}).get("authors") or [])[:8]],
        work_type="article", oa_status="gold" if is_open else "",
        landing_url=article.get("html_url") or "", found_by=[found_by])


class IEEE(Source):
    name, label = "ieee", "IEEE Xplore"
    key_name = "IEEE_API_KEY"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, seen = 1, 0
        while seen < limit:
            size = min(_PAGE, limit - seen)
            params = {"querytext": query, "max_records": size, "start_record": start, "apikey": self.key,
                      **({"start_year": years[0], "end_year": years[1]} if years else {})}
            data = self.client.get_json(API, params=params)
            articles = data.get("articles") or []
            for article in articles:
                candidate = candidate_from_article(article, f"ieee: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(articles) < size:
                return
            start += len(articles)

    def applies(self, candidate: Candidate) -> bool:
        return candidate.doi.startswith("10.1109/")

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(API, params={"doi": candidate.doi, "apikey": self.key})
        return next((abstract_or_nothing(a.get("abstract")) for a in data.get("articles") or []
                     if normalize_doi(a.get("doi") or "") == candidate.doi), "")
