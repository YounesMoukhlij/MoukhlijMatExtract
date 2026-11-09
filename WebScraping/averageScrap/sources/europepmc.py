# WebScraping/sources/europepmc.py
"""Europe PMC: PubMed, PubMed Central and the preprint servers (ChemRxiv, Research Square,
bioRxiv, ...), with their abstracts. Free, no key. Its strength is chemistry close to the life
sciences; for physics it finds little, which costs one request a query."""

from typing import Any, Dict, Iterator, Optional, Tuple
from urllib.parse import urlsplit

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import NOT_A_COPY, Source, abstract_or_nothing, in_years, plain, spell_license, year_of

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def candidate_from_result(result: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(result.get("doi") or "")
    title = plain(result.get("title")).rstrip(".")
    key = candidate_key(doi, "", title)
    if not key:
        return None
    preprint = result.get("source") == "PPR"
    kinds = [kind.lower() for kind in ((result.get("pubTypeList") or {}).get("pubType") or [])]
    # The open PDFs it lists, but not its own pages (they turn scripts away; the `pmc` source reads that copy).
    oa_urls = [link["url"] for link in ((result.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
               if link.get("documentStyle") == "pdf" and link.get("availabilityCode") in ("OA", "F") and link.get("url")
               and urlsplit(link["url"]).netloc.lower() not in NOT_A_COPY]
    in_pmc = result.get("isOpenAccess") == "Y" and bool(result.get("pmcid"))
    abstract = abstract_or_nothing(result.get("abstractText"))
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="europepmc" if abstract else "",
        year=year_of(result.get("pubYear")),
        journal=(((result.get("journalInfo") or {}).get("journal") or {}).get("title") or ""),
        authors=[name.strip() for name in (result.get("authorString") or "").rstrip(".").split(",") if name.strip()][:8],
        work_type="preprint" if preprint else "review" if "review" in kinds else "article", is_preprint=preprint,
        oa_status="green" if in_pmc else "", oa_urls=oa_urls, license=spell_license(result.get("license") or ""),
        found_by=[found_by])


class EuropePMC(Source):
    name, label = "europepmc", "Europe PMC"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        text = f"({query})" + (f" AND PUB_YEAR:[{years[0]} TO {years[1]}]" if years else "") \
            + ("" if include_preprints else " NOT SRC:PPR")
        cursor, seen = "*", 0
        while cursor and seen < limit:
            data = self.client.get_json(API, params={"query": text, "format": "json", "resultType": "core",
                                                     "pageSize": min(100, limit - seen), "cursorMark": cursor})
            results = (data.get("resultList") or {}).get("result") or []
            for result in results:
                candidate = candidate_from_result(result, f"europepmc: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            following = data.get("nextCursorMark")
            if not results or following == cursor:
                return
            cursor = following

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(API, params={"query": f'DOI:"{candidate.doi}"', "format": "json",
                                                 "resultType": "core", "pageSize": 1})
        for result in (data.get("resultList") or {}).get("result") or []:
            if normalize_doi(result.get("doi") or "") == candidate.doi:
                return abstract_or_nothing(result.get("abstractText"))
        return ""
