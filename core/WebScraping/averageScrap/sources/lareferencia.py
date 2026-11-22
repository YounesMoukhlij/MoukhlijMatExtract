# WebScraping/sources/lareferencia.py
"""LA Referencia: the open-access repositories of Latin America and Spain (national networks of
Argentina, Brazil, Chile, Colombia, Mexico, Peru, Spain, …) — articles and theses, many in Spanish or
Portuguese, each kept by its own university repository. Free, no key."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://buscador.lareferencia.info/api/v1/search"
_PAGE = 100
_MAX_PAGES = 10
_FIELDS = ["id", "title", "urls", "authors", "publicationDates", "formats", "summary", "rawData"]
_KINDS = {"article": "article", "doctoralthesis": "thesis", "masterthesis": "thesis", "bachelorthesis": "thesis",
          "report": "report", "conferenceobject": "article", "preprint": "preprint", "workingpaper": "preprint"}


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    raw = record.get("rawData") or {}
    doi = next((normalize_doi(str(v)) for k, v in raw.items() if "doi" in k.lower() and v), "")
    if not doi:
        doi = next((normalize_doi(u.get("url") or "") for u in record.get("urls") or [] if "doi.org/" in (u.get("url") or "")), "")
    title = plain(record.get("title"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    kinds = [f.replace(" ", "").lower() for f in record.get("formats") or []]
    kind = next((_KINDS[k] for k in kinds if k in _KINDS), "article")
    pages = [u.get("url") for u in record.get("urls") or [] if u.get("url") and "doi.org/" not in u.get("url")]
    opened = "openAccess" in (raw.get("eu_rights_str_mv") or [])
    authors = list(((record.get("authors") or {}).get("primary") or {}).keys()) + \
        list(((record.get("authors") or {}).get("secondary") or {}).keys())
    abstract = abstract_or_nothing(" ".join(record.get("summary") or []))
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="lareferencia" if abstract else "",
        year=year_of(" ".join(record.get("publicationDates") or [])), publisher=raw.get("network_name_str") or "",
        authors=authors[:8], work_type=kind, is_preprint=kind == "preprint",
        oa_status="green" if opened and pages else "", copy_pages=pages[:3] if opened else [],
        landing_url=pages[0] if pages else "", found_by=[found_by])


class LAReferencia(Source):
    name, label = "lareferencia", "LA Referencia"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        params: Dict[str, Any] = {"lookfor": query, "type": "AllFields", "limit": _PAGE, "field[]": _FIELDS}
        if years:
            params["filter[]"] = f'publishDate:"[{years[0]} TO {years[1]}]"'
        seen = 0
        for page in range(1, _MAX_PAGES + 1):
            data = self.client.get_json(API, params={**params, "page": page})
            records = data.get("records") or []
            for record in records:
                candidate = candidate_from_record(record, f"lareferencia: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(records) < _PAGE:
                return
