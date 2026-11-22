# WebScraping/sources/ntrs.py
"""NASA's Technical Reports Server (NTRS): the reports, conference papers and journal articles of
NASA and its centres and contractors, most with a PDF released for public use (a work of the US
government). Free, no key."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

SITE = "https://ntrs.nasa.gov"
API = f"{SITE}/api/citations/search"
_PAGE = 100
_KINDS = {"REPRINT": "article", "CONFERENCE_PAPER": "article", "TECHNICAL_REPORT": "report", "THESIS_DISSERTATION": "thesis",
          "CONTRACTOR_REPORT": "report", "TECHNICAL_MEMORANDUM": "report", "TECHNICAL_PUBLICATION": "report",
          "PREPRINT": "preprint", "ACCEPTED_MANUSCRIPT": "article", "JOURNAL_ARTICLE": "article"}


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = next((normalize_doi(i.get("number") or "") for i in record.get("sourceIdentifiers") or []
                if (i.get("type") or "").upper() == "DOI"), "")
    title = plain(record.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    released = record.get("downloadsAvailable") and \
        ((record.get("copyright") or {}).get("determinationType") or "PUBLIC_USE_PERMITTED") == "PUBLIC_USE_PERMITTED"
    pdfs = [SITE + d["links"]["pdf"] for d in record.get("downloads") or []
            if released and (d.get("links") or {}).get("pdf") and d.get("mimetype") == "application/pdf"]
    publication = (record.get("publications") or [{}])[0] or {}
    abstract = abstract_or_nothing(record.get("abstract"))
    kind = _KINDS.get((record.get("stiType") or "").upper(), "report")
    authors = [((a.get("meta") or {}).get("author") or {}).get("name", "") for a in record.get("authorAffiliations") or []]
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="ntrs" if abstract else "",
        year=year_of(publication.get("publicationDate")) or year_of(record.get("created")),
        journal=publication.get("publicationName") or "", publisher="NASA", authors=[a for a in authors if a][:8],
        work_type=kind, is_preprint=kind == "preprint", oa_status="green" if pdfs else "", oa_urls=pdfs,
        landing_url=f"{SITE}/citations/{record.get('id')}" if record.get("id") else "",
        license="public use (NASA)" if pdfs else "", found_by=[found_by])


class NTRS(Source):
    name, label = "ntrs", "NASA NTRS"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, seen = 0, 0
        while seen < limit:
            data = self.client.get_json(API, params={"q": query, "page.size": _PAGE, "page.from": start})
            records = data.get("results") or []
            for record in records:
                candidate = candidate_from_record(record, f"ntrs: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(records) < _PAGE:
                return
            start += len(records)
