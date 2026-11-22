# WebScraping/sources/jstage.py
"""J-STAGE: Japan's journal platform (the Journal of the Ceramic Society of Japan, Electrochemistry,
Materials Transactions, ...). Free, no key. Its records carry no abstract (Crossref usually has it:
see `search.abstract_sources`), and its robots.txt keeps programs away from its PDFs, so a copy
of a J-STAGE paper comes from another source or by hand."""

import xml.etree.ElementTree as ET
from typing import Iterator, List, Optional, Tuple

from WebScraping.averageScrap.http import HttpError
from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, in_years, plain, year_of

API = "https://api.jstage.jst.go.jp/searchapi/do"
_ATOM, _PRISM = "{http://www.w3.org/2005/Atom}", "{http://prismstandard.org/namespaces/basic/2.0/}"
_PAGE = 100
_NOTHING_FOUND = "ERR_001"


def _english(entry: ET.Element, tag: str) -> str:
    node = entry.find(f"{_ATOM}{tag}/{_ATOM}en")
    return plain(node.text) if node is not None and node.text else ""


def parse_feed(xml_text: str, found_by: str) -> List[Candidate]:
    root = ET.fromstring(xml_text)
    # "0": fine; "WARN_002": more results than it lists (the list is still there); "ERR_001": none;
    # any other ERR_: the query was refused.
    status = root.findtext(f"{_ATOM}result/{_ATOM}status") or "0"
    if status == _NOTHING_FOUND:
        return []
    if status.startswith("ERR"):
        raise HttpError(API, 400, root.findtext(f"{_ATOM}result/{_ATOM}message") or f"status {status}")
    candidates = []
    for entry in root.findall(f"{_ATOM}entry"):
        doi = normalize_doi(entry.findtext(f"{_PRISM}doi") or "")
        title = _english(entry, "article_title") or plain(entry.findtext(f"{_ATOM}title"))
        key = candidate_key(doi, "", title)
        if not key:
            continue
        names = entry.findall(f"{_ATOM}author/{_ATOM}en/{_ATOM}name")
        candidates.append(Candidate(
            key=key, doi=doi, title=title, year=year_of(entry.findtext(f"{_ATOM}pubyear")),
            journal=_english(entry, "material_title"), publisher="J-STAGE",
            authors=[plain(n.text) for n in names if n.text][:8], work_type="article",
            landing_url=_english(entry, "article_link"), found_by=[found_by]))
    return candidates


class JStage(Source):
    name, label = "jstage", "J-STAGE"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        start, seen = 1, 0
        while seen < limit:
            size = min(_PAGE, limit - seen)
            params = {"service": 3, "text": query, "count": size, "start": start,
                      **({"pubyearfrom": years[0], "pubyearto": years[1]} if years else {})}
            response = self.client.get(API, params=params)
            if response.status_code != 200:
                raise HttpError(API, response.status_code, response.text[:200].replace("\n", " "))
            page = parse_feed(response.text, f"jstage: {query}")
            for candidate in page:
                if in_years(candidate.year, years):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(page) < size:
                return
            start += size
