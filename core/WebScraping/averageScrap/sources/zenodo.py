# WebScraping/sources/zenodo.py
"""Zenodo, CERN's open repository: papers, preprints, theses and reports deposited by their authors —
often the free copy of a journal article (the record then carries the journal's DOI and the PDF).
Free, no key (60 requests a minute; 25 results a page)."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license, year_of

API = "https://zenodo.org/api/records"
_PAGE = 25  # Zenodo's largest page without a key
# The kinds of publication that are a paper; posters, presentations, peer reviews and the like are not.
_PAPERS = {"article": "article", "preprint": "preprint", "thesis": "thesis", "conferencepaper": "article",
           "report": "report", "workingpaper": "preprint", "technicalnote": "report", "book": "book",
           "section": "book-chapter"}


def pdf_links(record: Dict[str, Any]) -> List[str]:
    """The PDF files of a record, as links that download them."""
    links = []
    for file in record.get("files") or []:
        name = (file.get("key") or "").lower()
        link = (file.get("links") or {}).get("self") or ""
        if name.endswith(".pdf") and link:
            links.append(link)
    return links


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    meta = record.get("metadata") or {}
    kind = ((meta.get("resource_type") or {}).get("subtype") or (meta.get("resource_type") or {}).get("type") or "")
    if kind not in _PAPERS:
        return None
    doi = normalize_doi(record.get("doi") or meta.get("doi") or "")
    preprint = arxiv_id(doi)
    title = plain(meta.get("title"))
    key = candidate_key("" if preprint else doi, preprint, title)
    if not key:
        return None
    pdfs = pdf_links(record) if meta.get("access_right") == "open" else []
    abstract = abstract_or_nothing(meta.get("description"))
    journal = (meta.get("journal") or {}).get("title") or ""
    return Candidate(
        key=key, doi="" if preprint else doi, arxiv_id=preprint, title=title, abstract=abstract,
        abstract_from="zenodo" if abstract else "", year=year_of(meta.get("publication_date")), journal=journal,
        publisher="Zenodo", authors=[c.get("name", "") for c in (meta.get("creators") or [])[:8]],
        work_type=_PAPERS[kind], is_preprint=_PAPERS[kind] == "preprint",
        oa_status="green" if pdfs else "", oa_urls=pdfs, landing_url=(record.get("links") or {}).get("self_html") or "",
        license=spell_license((meta.get("license") or {}).get("id") or ""), found_by=[found_by])


class Zenodo(Source):
    name, label = "zenodo", "Zenodo"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        text = query + (f" AND publication_date:[{years[0]}-01-01 TO {years[1]}-12-31]" if years else "")
        page, seen = 1, 0
        while seen < limit:
            data = self.client.get_json(API, params={"q": text, "type": "publication", "size": _PAGE, "page": page,
                                                     "sort": "bestmatch"})
            records = (data.get("hits") or {}).get("hits") or []
            for record in records:
                candidate = candidate_from_record(record, f"zenodo: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(records) < _PAGE:
                return
            page += 1

    def by_doi(self, doi: str) -> List[Dict[str, Any]]:
        """The records that carry this DOI (the free copy of a journal article, deposited by its authors)."""
        data = self.client.get_json(API, params={"q": f'doi:"{doi}"', "size": 5})
        return [r for r in (data.get("hits") or {}).get("hits") or []
                if normalize_doi(r.get("doi") or (r.get("metadata") or {}).get("doi") or "") == doi]

    def abstract(self, candidate: Candidate) -> str:
        return max((abstract_or_nothing((r.get("metadata") or {}).get("description")) for r in self.by_doi(candidate.doi)),
                   key=len, default="")
