# WebScraping/sources/lens.py
"""The Lens (lens.org): over 250 million scholarly works merged from Crossref, PubMed, OpenAlex and
others, with their open-access status and links. Its API comes with an institutional subscription
(ask your library), or a trial for non-commercial evaluation: LENS_API_TOKEN (sign in at lens.org →
https://www.lens.org/lens/user/subscriptions, "API & Data" → request access; once approved, create the
token on your profile). Request and answer as https://docs.api.lens.org/ describes them."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license

API = "https://api.lens.org/scholarly/search"
_PAGE = 100
_MAX_RESULTS = 1000  # a search pages ("from") through its first thousand results
_INCLUDE = ["lens_id", "title", "abstract", "year_published", "external_ids", "authors", "source",
            "open_access", "publication_type"]
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}


def external_id(record: Dict[str, Any], kind: str) -> str:
    return next((str(i.get("value") or "") for i in record.get("external_ids") or [] if i.get("type") == kind), "")


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(external_id(record, "doi"))
    preprint = arxiv_id(external_id(record, "arxiv"))
    title = plain(record.get("title"))
    key = candidate_key(doi, preprint, title)
    if not key:
        return None
    access = record.get("open_access") or {}
    colour = (access.get("colour") or "").lower()
    source = record.get("source") or {}
    authors: List[str] = [f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip()
                          for a in record.get("authors") or []]
    kind = (record.get("publication_type") or "").lower()
    abstract = abstract_or_nothing(record.get("abstract"))
    pdfs = list(dict.fromkeys(url for location in access.get("locations") or [] for url in location.get("pdf_urls") or []))
    return Candidate(
        key=key, doi=doi, arxiv_id=preprint, title=title, abstract=abstract, abstract_from="lens" if abstract else "",
        year=int(record.get("year_published") or 0), journal=source.get("title") or "", publisher=source.get("publisher") or "",
        authors=[a for a in authors if a][:8], work_type="review" if "review" in kind else "preprint" if "preprint" in kind else "article",
        is_preprint="preprint" in kind, oa_status=colour if colour in _OPEN else "", oa_urls=pdfs[:3],
        license=spell_license(access.get("license") or ""),
        landing_url=f"https://www.lens.org/{record['lens_id']}" if record.get("lens_id") else "", found_by=[found_by])


def build_body(query: str, years: Optional[Tuple[int, int]], start: int, size: int) -> Dict[str, Any]:
    """The search, as Lens's query language writes it: every word of the query in the title or abstract."""
    must: List[Dict[str, Any]] = [{"query_string": {"query": query, "fields": ["title", "abstract"],
                                                    "default_operator": "and"}}]
    if years:
        must.append({"range": {"year_published": {"gte": years[0], "lte": years[1]}}})
    return {"query": {"bool": {"must": must}}, "size": size, "from": start, "include": _INCLUDE}


class Lens(Source):
    name, label = "lens", "The Lens"
    key_name = "LENS_API_TOKEN"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start = 0
        while start < min(limit, _MAX_RESULTS):
            size = min(_PAGE, limit - start)
            data = self.client.post_json(API, build_body(query, years, start, size),
                                         headers={"Authorization": f"Bearer {self.key}"})
            records = data.get("data") or []
            for record in records:
                candidate = candidate_from_record(record, f"lens: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
            if len(records) < size:
                return
            start += len(records)
