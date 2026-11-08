# WebScraping/sources/osf.py
"""OSF Preprints, through SHARE (the Center for Open Science's index): the preprint servers OSF hosts —
ECSarXiv (the Electrochemical Society's), ChemRxiv's older papers, engrXiv, EarthArXiv, and others —
each with its PDF. Free, no key."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license, year_of

API = "https://share.osf.io/trove/index-card-search"
_PAGE = 50
OSF = "https://osf.io/"


def values(record: Dict[str, Any], field: str) -> List[str]:
    """The plain values of a field of a SHARE record ([{"@value": ...}, ...])."""
    return [v["@value"] for v in record.get(field) or [] if isinstance(v, dict) and v.get("@value")]


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    page = record.get("@id") or ""
    if not page.startswith(OSF):  # a preprint OSF itself hosts: its file is had from OSF
        return None
    identifiers = values(record, "identifier") + [s.get("@id", "") for s in record.get("sameAs") or []]
    doi = next((normalize_doi(i) for i in identifiers if "doi.org/" in i), "")
    title = plain(next(iter(values(record, "title")), ""))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    abstract = abstract_or_nothing(next(iter(values(record, "description")), ""))
    server = next((n for p in record.get("publisher") or [] for n in values(p, "name")), "OSF Preprints")
    rights = next((r.get("@id") or "" for r in record.get("rights") or []), "")
    authors = [n for c in record.get("creator") or [] for n in values(c, "name")]
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="osf" if abstract else "",
        year=year_of(next(iter(values(record, "dateCreated")), "")), journal=server, publisher=server,
        authors=authors[:8], work_type="preprint", is_preprint=True, oa_status="green",
        oa_urls=[page.rstrip("/") + "/download"], landing_url=page, license=spell_license(rights), found_by=[found_by])


class OSFPreprints(Source):
    name, label = "osf", "OSF Preprints"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        if not include_preprints:
            return
        url: Optional[str] = API
        params: Optional[Dict[str, Any]] = {"cardSearchText": query, "cardSearchFilter[resourceType]": "Preprint",
                                            "page[size]": _PAGE, "acceptMediatype": "application/json"}
        seen = 0
        while url and seen < limit:
            data = self.client.get_json(url, params=params)
            records = data.get("data") or []
            for record in records:
                candidate = candidate_from_record(record, f"osf: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            url, params = ((data.get("links") or {}).get("next"), None) if records else (None, None)
