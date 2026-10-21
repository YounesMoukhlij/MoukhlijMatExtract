# WebScraping/sources/openaire.py
"""OpenAIRE: the European research graph, harvested from university and national repositories,
Zenodo, journals and Crossref. It finds what the other indexes miss — theses, the accepted
manuscripts of closed papers — and it often holds the abstract a journal record lacks (Elsevier's,
from the authors' deposit). Free, no key."""

from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

from WebScraping.ids import candidate_key, normalize_doi
from WebScraping.ledger import Candidate
from WebScraping.sources.common import NOT_A_COPY, Source, abstract_or_nothing, in_years, plain, spell_license, year_of

API = "https://api.openaire.eu/graph/v1/researchProducts"
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}


def _doi(product: Dict[str, Any]) -> str:
    for pid in [*(product.get("pids") or []),
                *(pid for instance in product.get("instances") or [] for pid in instance.get("pids") or [])]:
        if (pid.get("scheme") or "").lower() == "doi":
            doi = normalize_doi(pid.get("value") or "")
            if doi:
                return doi
    return ""


def best_description(product: Dict[str, Any]) -> str:
    """The abstract among its descriptions: the longest one (a record merged from several deposits
    may also carry a short note or the abstract in a second language)."""
    texts = [abstract_or_nothing(text) for text in product.get("descriptions") or []]
    return max(texts, key=len, default="")


def candidate_from_product(product: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi, title = _doi(product), plain(product.get("mainTitle"))
    key = candidate_key(doi, "", title)
    if not key:
        return None
    instances = product.get("instances") or []
    kind = (instances[0].get("type") or "").lower() if instances else ""
    work_type = "preprint" if "preprint" in kind else "thesis" if "thesis" in kind else \
        "review" if "review" in kind else "article"
    # The copies in repositories: a file first; a page (handle, repository record) as the place to look.
    files: List[str] = []
    pages: List[str] = []
    for instance in instances:
        if ((instance.get("accessRight") or {}).get("label") or "").upper() != "OPEN":
            continue
        for url in instance.get("urls") or []:
            if urlsplit(url).netloc.lower() not in NOT_A_COPY and url not in files + pages:
                (files if url.lower().split("?")[0].endswith(".pdf") else pages).append(url)
    best = ((product.get("bestAccessRight") or {}).get("label") or "").upper()
    color = (product.get("openAccessColor") or "").lower()
    abstract = best_description(product)
    license = next((spell_license(i.get("license") or "") for i in instances if i.get("license")), "")
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="openaire" if abstract else "",
        year=year_of(product.get("publicationDate")), journal=((product.get("container") or {}).get("name") or ""),
        publisher=product.get("publisher") or "",
        authors=[a.get("fullName", "") for a in (product.get("authors") or [])[:8]],
        work_type=work_type, is_preprint=work_type == "preprint",
        oa_status=color if color in _OPEN else "green" if best == "OPEN" and (files or pages) else "",
        oa_urls=files, landing_url=pages[0] if pages else "", license=license, found_by=[found_by])


class OpenAIRE(Source):
    name, label = "openaire", "OpenAIRE"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        params: Dict[str, Any] = {"search": query, "type": "publication"}
        if years:
            params.update(fromPublicationDate=f"{years[0]}-01-01", toPublicationDate=f"{years[1]}-12-31")
        cursor, seen = "*", 0
        while cursor and seen < limit:
            data = self.client.get_json(API, params={**params, "pageSize": min(100, limit - seen), "cursor": cursor})
            products = data.get("results") or []
            for product in products:
                candidate = candidate_from_product(product, f"openaire: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if not products:
                return
            cursor = (data.get("header") or {}).get("nextCursor")

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(API, params={"pid": candidate.doi})
        return max((best_description(product) for product in data.get("results") or []), key=len, default="")
