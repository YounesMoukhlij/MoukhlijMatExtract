# WebScraping/sources/crossref.py
"""Crossref: the registry every DOI is minted in. Its records carry the abstract whenever the
publisher deposited one (most do — not Elsevier), the licence, and the links a publisher offers for
text mining. Free, no key; a contact address puts the requests in its "polite" pool."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.ids import candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, cc_license, in_years, plain

API = "https://api.crossref.org/works"
_SELECT = "DOI,title,abstract,issued,container-title,publisher,author,type,license,link"


def _license(item: Dict[str, Any]) -> str:
    """The Creative Commons licence of the published version, if it has one."""
    for entry in item.get("license") or []:
        if entry.get("content-version") in ("vor", "unspecified", None):
            spelled = cc_license(entry.get("URL") or "")
            if spelled:
                return spelled
    return ""


def candidate_from_item(item: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(item.get("DOI") or "")
    title = plain((item.get("title") or [""])[0])
    key = candidate_key(doi, "", title)
    if not key:
        return None
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    preprint = item.get("type") == "posted-content"
    license = _license(item)
    # A PDF link under an open licence is an open copy; any other link is for subscribers.
    oa_urls = [link["URL"] for link in item.get("link") or []
               if license and link.get("URL") and link.get("content-type") == "application/pdf"]
    abstract = abstract_or_nothing(item.get("abstract"))
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="crossref" if abstract else "",
        year=int(parts[0] or 0) if parts else 0, journal=plain((item.get("container-title") or [""])[0]),
        publisher=item.get("publisher") or "",
        authors=[" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
                 for a in (item.get("author") or [])[:8]],
        work_type="preprint" if preprint else "article", is_preprint=preprint, oa_urls=oa_urls, license=license,
        found_by=[found_by])


class Crossref(Source):
    name, label = "crossref", "Crossref"

    def _polite(self) -> Dict[str, str]:
        return {"mailto": self.contact} if self.contact else {}

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        filters = ["type:journal-article"] + (["type:posted-content"] if include_preprints else [])  # one type or the other
        if years:
            filters += [f"from-pub-date:{years[0]}", f"until-pub-date:{years[1]}"]
        cursor, seen = "*", 0
        while cursor and seen < limit:
            data = self.client.get_json(API, params={
                "query.bibliographic": query, "filter": ",".join(filters), "rows": min(100, limit - seen),
                "cursor": cursor, "select": _SELECT, **self._polite()})
            message = data.get("message") or {}
            items: List[Dict[str, Any]] = message.get("items") or []
            for item in items:
                candidate = candidate_from_item(item, f"crossref: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if not items:
                return
            cursor = message.get("next-cursor")

    def record(self, doi: str) -> Dict[str, Any]:
        """The whole record of one DOI."""
        return self.client.get_json(f"{API}/{doi}", params=self._polite() or None).get("message") or {}

    def abstract(self, candidate: Candidate) -> str:
        return abstract_or_nothing(self.record(candidate.doi).get("abstract"))
