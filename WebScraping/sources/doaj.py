# WebScraping/sources/doaj.py
"""DOAJ, the Directory of Open Access Journals: every article it lists can be read by anyone,
with its abstract. Free, no key."""

from typing import Any, Dict, Iterator, Optional, Tuple
from urllib.parse import quote

from WebScraping.ids import candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://doaj.org/api/search/articles"
_MAX_RESULTS = 1000  # its search hands out the first thousand results of a query


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    bib = record.get("bibjson") or {}
    doi = next((normalize_doi(i.get("id") or "") for i in bib.get("identifier") or []
                if (i.get("type") or "").lower() == "doi"), "")
    title = plain(bib.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    links = [link for link in bib.get("link") or [] if link.get("type") == "fulltext" and link.get("url")]
    pdfs = [link["url"] for link in links if "pdf" in (link.get("content_type") or "").lower()]
    pages = [link["url"] for link in links if link["url"] not in pdfs]
    journal = bib.get("journal") or {}
    abstract = abstract_or_nothing(bib.get("abstract"))
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="doaj" if abstract else "",
        year=year_of(bib.get("year")), journal=journal.get("title") or "", publisher=journal.get("publisher") or "",
        authors=[a.get("name", "") for a in (bib.get("author") or [])[:8]], work_type="article",
        oa_status="gold", oa_urls=pdfs, landing_url=pages[0] if pages else "", found_by=[found_by])


class DOAJ(Source):
    name, label = "doaj", "DOAJ"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        text = query + (f" AND bibjson.year:[{years[0]} TO {years[1]}]" if years else "")
        page, seen, size = 1, 0, min(100, max(1, limit))
        while seen < limit and (page - 1) * size < _MAX_RESULTS:
            data = self.client.get_json(f"{API}/{quote(text, safe='')}", params={"page": page, "pageSize": size})
            records = data.get("results") or []
            for record in records:
                candidate = candidate_from_record(record, f"doaj: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(records) < size:
                return
            page += 1
