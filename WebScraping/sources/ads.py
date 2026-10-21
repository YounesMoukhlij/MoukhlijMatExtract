# WebScraping/sources/ads.py
"""NASA ADS, the Astrophysics Data System: the physics literature (condensed matter, materials,
chemical physics) with abstracts, and for each journal paper its arXiv version. Free token:
ADS_API_TOKEN (create an account at https://ui.adsabs.harvard.edu/, then Settings -> API Token).
5000 requests a day."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.ids import ARXIV_DOI_PREFIX, arxiv_id, candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://api.adsabs.harvard.edu/v1/search/query"
_FIELDS = "bibcode,doi,title,abstract,year,pub,author,identifier,doctype,esources"
_PAGE = 200


def journal_doi(doc: Dict[str, Any]) -> str:
    """Its DOI, not the one arXiv gives the preprint."""
    return next((d for d in (normalize_doi(x) for x in doc.get("doi") or []) if d and not d.startswith(ARXIV_DOI_PREFIX)), "")


def preprint_of(doc: Dict[str, Any]) -> str:
    """The arXiv id among its identifiers ("arXiv:2101.01234", "10.48550/arXiv.2101.01234")."""
    return next((i for i in (arxiv_id(x) for x in doc.get("identifier") or [] if "arxiv" in x.lower()) if i), "")


def candidate_from_doc(doc: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi, preprint_id = journal_doi(doc), preprint_of(doc)
    titles: List[str] = doc.get("title") or []
    title = plain(titles[0] if titles else "")
    key = candidate_key(doi, preprint_id, title)
    if not key:
        return None
    is_preprint = doc.get("doctype") == "eprint" and not doi
    abstract = abstract_or_nothing(doc.get("abstract"))
    return Candidate(
        key=key, doi=doi, arxiv_id=preprint_id, title=title, abstract=abstract, abstract_from="ads" if abstract else "",
        year=year_of(doc.get("year")), journal=doc.get("pub") or "", authors=(doc.get("author") or [])[:8],
        work_type="preprint" if is_preprint else "article", is_preprint=is_preprint,
        oa_status="green" if preprint_id else "", found_by=[found_by])


class ADS(Source):
    name, label = "ads", "NASA ADS"
    key_name = "ADS_API_TOKEN"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        q = f"abs:({query})" + (f" year:{years[0]}-{years[1]}" if years else "") \
            + ("" if include_preprints else " doctype:article")
        start, seen = 0, 0
        while seen < limit:
            size = min(_PAGE, limit - seen)
            data = self.client.get_json(API, params={"q": q, "fl": _FIELDS, "rows": size, "start": start,
                                                     "sort": "score desc"}, headers=self._headers())
            docs = (data.get("response") or {}).get("docs") or []
            for doc in docs:
                candidate = candidate_from_doc(doc, f"ads: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(docs) < size:
                return
            start += len(docs)

    def record(self, doi: str, fields: str = _FIELDS) -> Optional[Dict[str, Any]]:
        """ADS's record of one DOI, or None."""
        data = self.client.get_json(API, params={"q": f'doi:"{doi}"', "fl": fields, "rows": 1}, headers=self._headers())
        docs = (data.get("response") or {}).get("docs") or []
        return docs[0] if docs else None

    def abstract(self, candidate: Candidate) -> str:
        doc = self.record(candidate.doi, "abstract")
        return abstract_or_nothing((doc or {}).get("abstract"))
