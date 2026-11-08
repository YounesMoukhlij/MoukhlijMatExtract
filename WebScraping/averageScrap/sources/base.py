# WebScraping/sources/base.py
"""BASE, the Bielefeld Academic Search Engine: over 400 million documents from more than 11,000
repositories and open journals worldwide, with whether each one is open access. Free for research,
but its interface answers only the computers it has registered: ask BASE to register your network's
IP address (https://www.base-search.net/about/en/contact.php — say it is for non-commercial
research), then write yes after BASE_ACCESS= in the .env file."""

import logging
from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.http import HttpError
from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
REGISTER = "https://www.base-search.net/about/en/contact.php"
_PAGE = 100
_MAX_OFFSET = 1000


def listed(value: Any) -> List[str]:
    """BASE gives a field as one value or a list of them."""
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def candidate_from_doc(doc: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = next((normalize_doi(d) for d in listed(doc.get("dcdoi")) if normalize_doi(d)), "")
    preprint = next((arxiv_id(i) for i in listed(doc.get("dcidentifier")) if "arxiv.org" in i and arxiv_id(i)), "")
    title = plain(next(iter(listed(doc.get("dctitle"))), ""))
    key = candidate_key(doi, preprint, title)
    if not key:
        return None
    link = next(iter(listed(doc.get("dclink"))), "")
    opened = str(doc.get("dcoa") or "") == "1"
    abstract = abstract_or_nothing(" ".join(listed(doc.get("dcdescription"))))
    kinds = " ".join(listed(doc.get("dctype"))).lower()
    kind = "thesis" if "thesis" in kinds or "doctoral" in kinds else "preprint" if "preprint" in kinds else "article"
    return Candidate(
        key=key, doi=doi, arxiv_id=preprint, title=title, abstract=abstract, abstract_from="base" if abstract else "",
        year=int(doc.get("dcyear") or 0) or year_of(" ".join(listed(doc.get("dcdate")))),
        journal=next(iter(listed(doc.get("dcsource"))), ""), publisher=next(iter(listed(doc.get("dcpublisher"))), ""),
        authors=listed(doc.get("dccreator"))[:8], work_type=kind, is_preprint=kind == "preprint",
        oa_status="green" if opened and link else "", copy_pages=[link] if opened and link else [],
        landing_url=link, found_by=[found_by])


class BASE(Source):
    name, label = "base", "BASE"
    key_name = "BASE_ACCESS"  # "yes" once BASE has registered this network's IP address

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        text = query + (f" year:[{years[0]} TO {years[1]}]" if years else "")
        offset = 0
        while offset < min(limit, _MAX_OFFSET):
            hits = min(_PAGE, limit - offset)
            data = self.client.get_json(API, params={"func": "PerformSearch", "query": text, "format": "json",
                                                     "hits": hits, "offset": offset})
            if data.get("error"):  # "Access denied for IP address …": this network is not registered
                logging.warning(f"BASE: {data['error']} Ask BASE to register it (free for research): {REGISTER}")
                raise HttpError(API, 403, str(data["error"]))
            docs = (data.get("response") or {}).get("docs") or []
            for doc in docs:
                candidate = candidate_from_doc(doc, f"base: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
            if len(docs) < hits:
                return
            offset += len(docs)
