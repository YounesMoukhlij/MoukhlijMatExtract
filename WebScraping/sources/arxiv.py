# WebScraping/sources/arxiv.py
"""arXiv: the preprints. Its API is free and open (one request every three seconds); every paper on
arXiv can be read, so nothing found here is ever "closed"."""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Iterator, List, Optional, Tuple

from WebScraping.http import HttpError, PoliteClient
from WebScraping.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.ledger import Candidate

API = "https://export.arxiv.org/api/query"
_ATOM, _ARXIV = "{http://www.w3.org/2005/Atom}", "{http://arxiv.org/schemas/atom}"
_TERM = re.compile(r'"([^"]+)"|(\S+)')


def build_query(query: str, categories: List[str], years: Optional[Tuple[int, int]]) -> str:
    """"argyrodite ionic conductivity" -> all:argyrodite AND all:ionic AND all:conductivity, limited
    to the given categories and years. A phrase in quotes stays a phrase."""
    terms = [f'all:"{phrase}"' if phrase else f"all:{word}" for phrase, word in _TERM.findall(query)]
    parts = [" AND ".join(terms)]
    if categories:
        parts.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
    if years:
        parts.append(f"submittedDate:[{years[0]}01010000 TO {years[1]}12312359]")
    return " AND ".join(parts)


def _text(entry: ET.Element, tag: str) -> str:
    node = entry.find(tag)
    return " ".join((node.text or "").split()) if node is not None else ""


def parse_feed(xml_text: str, found_by: str) -> List[Candidate]:
    candidates = []
    for entry in ET.fromstring(xml_text).findall(f"{_ATOM}entry"):
        identifier = arxiv_id(_text(entry, f"{_ATOM}id"))
        if not identifier:  # the error entry arXiv returns for a bad query has no abs link
            continue
        doi = normalize_doi(_text(entry, f"{_ARXIV}doi"))
        title = _text(entry, f"{_ATOM}title")
        candidates.append(Candidate(
            key=candidate_key(doi, identifier, title), doi=doi, arxiv_id=identifier, title=title,
            abstract=_text(entry, f"{_ATOM}summary"), abstract_from="arxiv", year=int(_text(entry, f"{_ATOM}published")[:4] or 0),
            journal=_text(entry, f"{_ARXIV}journal_ref") or "arXiv",
            authors=[" ".join((a.findtext(f"{_ATOM}name") or "").split()) for a in entry.findall(f"{_ATOM}author")][:8],
            work_type="preprint", is_preprint=not doi,  # a journal DOI means the paper is published; arXiv holds a copy
            oa_status="green", oa_urls=[f"https://arxiv.org/pdf/{identifier}"],
            landing_url=f"https://arxiv.org/abs/{identifier}", license="arxiv", found_by=[found_by]))
    return candidates


class ArXiv:
    name, label = "arxiv", "arXiv"

    def __init__(self, client: PoliteClient, categories: Optional[List[str]] = None):
        self.client = client
        self.categories = categories or []

    def _fetch(self, params: dict) -> str:
        response = self.client.get(API, params=params)
        if response.status_code != 200:
            raise HttpError(API, response.status_code, response.text[:200].replace("\n", " "))
        return response.text

    def available(self) -> bool:
        return True

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        """The preprints matching a query. (Everything on arXiv is a preprint, or the arXiv copy of a
        paper: `include_preprints` does not apply.)"""
        search_query = build_query(query, self.categories, years)
        start = 0
        while start < limit:
            page = parse_feed(self._fetch({"search_query": search_query, "start": start, "sortBy": "relevance",
                                           "max_results": min(100, limit - start)}), f"arxiv: {query}")
            yield from page
            if len(page) < min(100, limit - start):
                return
            start += len(page)

    def lookup(self, identifier: str) -> Optional[Candidate]:
        try:
            found = parse_feed(self._fetch({"id_list": identifier}), f"arxiv: {identifier}")
        except (HttpError, ET.ParseError) as error:
            logging.debug(f"arXiv has no record for {identifier}: {error}")
            return None
        return found[0] if found else None
