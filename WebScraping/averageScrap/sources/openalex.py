# WebScraping/sources/openalex.py
"""OpenAlex: the main discovery source. It indexes journals, arXiv and ChemRxiv alike, says for each
work whether (and where) a legal open-access copy exists, and flags retracted papers."""

import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

from WebScraping.averageScrap.http import HttpError, PoliteClient
from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate

BASE = "https://api.openalex.org"
_SELECT = ("id,doi,title,publication_year,type,abstract_inverted_index,is_retracted,cited_by_count,"
           "open_access,best_oa_location,primary_location,locations,authorships")
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}
_BATCH = 50  # DOIs asked about in one request


def abstract_from_index(index: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex ships abstracts as {word: [positions]} (a copyright workaround); this puts them back in order."""
    if not index:
        return ""
    words = {position: word for word, positions in index.items() for position in positions}
    return " ".join(words[i] for i in sorted(words))


def _host(url: str) -> str:
    return urlsplit(url or "").netloc.lower()


def candidate_from_work(work: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    best = work.get("best_oa_location") or {}
    locations = work.get("locations") or []

    # An arXiv copy anywhere among the locations (or an arXiv DOI) lets the paper be fetched from arXiv.
    arxiv = arxiv_id(work.get("doi") or "")
    for loc in locations:
        for url in (loc.get("landing_page_url") or "", loc.get("pdf_url") or ""):
            if not arxiv and "arxiv.org" in _host(url):
                arxiv = arxiv_id(url)

    # Direct links to legal copies: the best location first, then every other open one.
    oa_urls: List[str] = []
    for loc in [best, *locations]:
        if loc and loc.get("is_oa", True) and loc.get("pdf_url") and loc["pdf_url"] not in oa_urls:
            oa_urls.append(loc["pdf_url"])

    title = (work.get("title") or work.get("display_name") or "").strip()
    doi = normalize_doi(work.get("doi") or "")
    key = candidate_key(doi, arxiv, title)
    if not key:
        return None
    oa = work.get("open_access") or {}
    work_type = work.get("type") or ""
    abstract = abstract_from_index(work.get("abstract_inverted_index"))
    return Candidate(
        key=key, doi=doi, arxiv_id=arxiv, openalex_id=(work.get("id") or "").rsplit("/", 1)[-1],
        title=title, abstract=abstract, abstract_from="openalex" if abstract else "",
        year=int(work.get("publication_year") or 0), journal=source.get("display_name") or "",
        publisher=source.get("host_organization_name") or "",
        authors=[a.get("author", {}).get("display_name", "") for a in (work.get("authorships") or [])[:8]],
        work_type=work_type, is_preprint=work_type == "preprint",
        is_retracted=bool(work.get("is_retracted")),
        oa_status=oa.get("oa_status") or ("closed" if not oa.get("is_oa") else ""),
        oa_urls=oa_urls, landing_url=best.get("landing_page_url") or primary.get("landing_page_url") or "",
        license=best.get("license") or "", cited_by=int(work.get("cited_by_count") or 0),
        found_by=[found_by] if found_by else [],
    )


class OpenAlex:
    name, label = "openalex", "OpenAlex"

    def __init__(self, client: PoliteClient, contact: str = "", api_key: str = ""):
        self.client = client
        # Neither is required; a contact address puts us in OpenAlex's polite pool, a key lifts its limits.
        key = api_key or os.environ.get("OPENALEX_API_KEY", "")
        self.auth: Dict[str, str] = {**({"api_key": key} if key else {}), **({"mailto": contact} if contact else {})}
        self._said_first_page_only = False

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True, within: str = "") -> Iterator[Candidate]:
        """`within`: only the works one source holds (an OpenAlex source id, e.g. arXiv's)."""
        types = "article|review" + ("|preprint" if include_preprints else "")
        filters = [f"type:{types}", "language:en"] + ([f"locations.source.id:{within}"] if within else [])
        if years:
            filters += [f"from_publication_date:{years[0]}-01-01", f"to_publication_date:{years[1]}-12-31"]
        cursor, seen = "*", 0
        while cursor and seen < limit:
            data = self.client.get_json(f"{BASE}/works", params={
                "search": query, "filter": ",".join(filters), "per-page": min(100, limit - seen),
                "cursor": cursor, "select": _SELECT, **self.auth})
            for work in data.get("results", []):
                candidate = candidate_from_work(work, f"openalex: {query}")
                if candidate:
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not data.get("results"):
                return
            if "api_key" not in self.auth:  # OpenAlex refuses (HTTP 401) a page past the first without a key
                if cursor and not self._said_first_page_only:
                    logging.info("OpenAlex: without OPENALEX_API_KEY only the first page of each search is given "
                                 f"({seen} results); a free key gives the rest: https://openalex.org/settings/api")
                    self._said_first_page_only = True
                return

    def available(self) -> bool:
        return True

    def lookup_many(self, dois: List[str]) -> Iterator[Candidate]:
        """The records of many papers, found by their DOIs, fifty to a request. They say nothing about
        how the papers were found (`found_by` is empty): this completes what another source found
        — whether and where an open copy exists, a retraction — it is not a search."""
        dois = [doi for doi in dict.fromkeys(dois) if doi and "," not in doi and "|" not in doi]
        for start in range(0, len(dois), _BATCH):
            batch = dois[start:start + _BATCH]
            data = self.client.get_json(f"{BASE}/works", params={
                "filter": "doi:" + "|".join(batch), "per-page": len(batch), "select": _SELECT, **self.auth})
            for work in data.get("results", []):
                candidate = candidate_from_work(work, "")
                if candidate:
                    yield candidate

    def lookup(self, doi: str) -> Optional[Candidate]:
        """The record of one paper, found by its DOI."""
        try:
            work = self.client.get_json(f"{BASE}/works/https://doi.org/{doi}",
                                        params={"select": _SELECT, **self.auth})
        except HttpError as error:
            logging.debug(f"OpenAlex has no record for {doi}: {error}")
            return None
        return candidate_from_work(work, f"openalex: {doi}")
