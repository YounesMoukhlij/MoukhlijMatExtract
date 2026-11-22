# WebScraping/sources/springernature.py
"""Springer Nature's metadata API: the Springer, Nature and BioMed Central journals with their
abstracts (OpenAlex lacks many of them). Free key: SPRINGER_NATURE_API_KEY
(https://dev.springernature.com/, the Basic plan). That plan cannot filter by year, so the years
are checked here."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://api.springernature.com/meta/v2/json"
PREFIXES = ("10.1007/", "10.1023/", "10.1038/", "10.1057/", "10.1134/", "10.1140/", "10.1186/")
_PAGE = 25


def _abstract(record: Dict[str, Any]) -> str:
    """The abstract is a string, or {"h1": "Abstract", "p": ...} with p a string or a list of paragraphs."""
    value = record.get("abstract")
    if isinstance(value, dict):
        value = value.get("p")
    if isinstance(value, list):
        value = " ".join(str(part) for part in value)
    return abstract_or_nothing(value)


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(record.get("doi") or record.get("identifier") or "")
    title = plain(record.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    is_open = str(record.get("openaccess") or "").lower() == "true"
    links = record.get("url") or []
    pdfs = [u["value"] for u in links if u.get("format") == "pdf" and u.get("value")]
    pages = [u["value"] for u in links if u.get("format") == "html" and u.get("value")]
    abstract = _abstract(record)
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="springernature" if abstract else "",
        year=year_of(record.get("publicationDate") or record.get("onlineDate")),
        journal=record.get("publicationName") or "", publisher=record.get("publisher") or "Springer Nature",
        authors=[c.get("creator", "") for c in (record.get("creators") or [])[:8]],
        work_type="chapter" if (record.get("contentType") or "").lower() == "chapter" else "article",
        oa_status="gold" if is_open else "", oa_urls=pdfs if is_open else [],
        landing_url=pages[0] if pages else "", found_by=[found_by])


class SpringerNature(Source):
    name, label = "springernature", "Springer Nature"
    key_name = "SPRINGER_NATURE_API_KEY"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, read = 1, 0
        while read < limit:
            size = min(_PAGE, limit - read)
            data = self.client.get_json(API, params={"q": query, "s": start, "p": size, "api_key": self.key})
            records = data.get("records") or []
            for record in records:
                candidate = candidate_from_record(record, f"springernature: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
            read += len(records)
            if len(records) < size:
                return
            start += len(records)

    def applies(self, candidate: Candidate) -> bool:
        publisher = candidate.publisher.lower()
        return bool(candidate.doi) and (candidate.doi.startswith(PREFIXES) or "springer" in publisher
                                        or "nature" in publisher or "biomed central" in publisher)

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(API, params={"q": f"doi:{candidate.doi}", "api_key": self.key})
        return next((_abstract(r) for r in data.get("records") or [] if normalize_doi(r.get("doi") or "") == candidate.doi), "")
