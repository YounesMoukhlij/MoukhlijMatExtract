# WebScraping/sources/thesesfr.py
"""theses.fr: every doctoral thesis defended in France, with its abstract (in English as well as
French, as a rule) and, when its author made it public, its full text — kept by HAL, which theses.fr
points to. Free, no key."""

from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://theses.fr/api/v1/theses"
DOCUMENT = "https://theses.fr/api/v1/document/{nnt}"  # leads to the thesis's page in HAL, which declares its PDF
_PAGE = 50
_MAX_START = 1000


def candidate_from_thesis(summary: Dict[str, Any], details: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    nnt = summary.get("nnt") or details.get("nnt") or ""
    titles = details.get("titres") or {}
    title = plain(titles.get("en") or summary.get("titreEN") or titles.get("fr") or summary.get("titrePrincipal"))
    doi = normalize_doi(details.get("doi") or summary.get("doi") or "")
    key = candidate_key(doi, "", title)
    if not key or not nnt:
        return None
    abstracts = details.get("resumes") or {}
    abstract = abstract_or_nothing(abstracts.get("en") or abstracts.get("fr"))
    opened = (details.get("accessible") or "").lower() == "oui"
    authors = [f"{a.get('prenom') or ''} {a.get('nom') or ''}".strip() for a in summary.get("auteurs") or []]
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="theses.fr" if abstract else "",
        year=year_of(summary.get("dateSoutenance") or details.get("dateSoutenance")),
        journal=summary.get("etabSoutenanceN") or "", publisher="theses.fr", authors=[a for a in authors if a],
        work_type="thesis", oa_status="green" if opened else "", copy_pages=[DOCUMENT.format(nnt=nnt)] if opened else [],
        landing_url=f"https://theses.fr/{nnt}", found_by=[found_by])


class ThesesFr(Source):
    name, label = "thesesfr", "theses.fr"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, seen = 0, 0
        while seen < limit and start < _MAX_START:
            data = self.client.get_json(f"{API}/recherche/", params={"q": query, "debut": start, "nombre": _PAGE})
            theses = data.get("theses") or []
            for summary in theses:
                # Only a defended thesis has a text; its abstract and whether it is public are in its record.
                if summary.get("status") != "soutenue" or not summary.get("nnt"):
                    continue
                if not in_years(year_of(summary.get("dateSoutenance")), years):
                    continue
                details = self.client.get_json(f"{API}/these/{summary['nnt']}")
                candidate = candidate_from_thesis(summary, details, f"thesesfr: {query}")
                if candidate:
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(theses) < _PAGE:
                return
            start += len(theses)
