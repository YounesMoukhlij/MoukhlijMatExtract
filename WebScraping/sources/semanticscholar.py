# WebScraping/sources/semanticscholar.py
"""Semantic Scholar: a search engine of its own over journals and preprints, which matches a
journal paper to its arXiv version. Free; without a key every user shares one request a second,
so a key (SEMANTIC_SCHOLAR_API_KEY) makes it much steadier."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license

PAPER = "https://api.semanticscholar.org/graph/v1/paper"
_FIELDS = "title,abstract,externalIds,year,venue,journal,publicationTypes,openAccessPdf,authors"
_MAX_OFFSET = 1000  # the search hands out its first thousand results, no more
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}


def candidate_from_paper(paper: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    ids = paper.get("externalIds") or {}
    doi, preprint_id = normalize_doi(ids.get("DOI") or ""), arxiv_id(str(ids.get("ArXiv") or ""))
    title = plain(paper.get("title"))
    key = candidate_key(doi, preprint_id, title)
    if not key:
        return None
    copy = paper.get("openAccessPdf") or {}
    status = (copy.get("status") or "").lower()
    types = paper.get("publicationTypes") or []
    abstract = abstract_or_nothing(paper.get("abstract"))
    return Candidate(
        key=key, doi=doi, arxiv_id=preprint_id, title=title, abstract=abstract,
        abstract_from="semanticscholar" if abstract else "", year=int(paper.get("year") or 0),
        journal=(paper.get("journal") or {}).get("name") or paper.get("venue") or "",
        authors=[a.get("name", "") for a in (paper.get("authors") or [])[:8]],
        work_type="review" if "Review" in types else "preprint" if not doi and preprint_id else "article",
        is_preprint=not doi and bool(preprint_id), oa_status=status if status in _OPEN else "",
        oa_urls=[copy["url"]] if copy.get("url") else [], license=spell_license(copy.get("license") or ""),
        found_by=[found_by])


class SemanticScholar(Source):
    name, label = "semanticscholar", "Semantic Scholar"
    key_name, key_required = "SEMANTIC_SCHOLAR_API_KEY", False

    def _headers(self) -> Optional[Dict[str, str]]:
        return {"x-api-key": self.key} if self.key else None

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        offset, seen = 0, 0
        while seen < limit and offset < _MAX_OFFSET:
            size = min(100, limit - seen, _MAX_OFFSET - offset)
            params = {"query": query, "fields": _FIELDS, "limit": size, "offset": offset,
                      **({"year": f"{years[0]}-{years[1]}"} if years else {})}
            data = self.client.get_json(f"{PAPER}/search", params=params, headers=self._headers())
            papers = data.get("data") or []
            for paper in papers:
                candidate = candidate_from_paper(paper, f"semanticscholar: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(papers) < size or data.get("next") is None:
                return
            offset += len(papers)

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(f"{PAPER}/DOI:{candidate.doi}", params={"fields": "abstract"},
                                    headers=self._headers())
        return abstract_or_nothing(data.get("abstract"))
