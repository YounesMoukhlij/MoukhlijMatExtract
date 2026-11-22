# WebScraping/sources/plos.py
"""PLOS: every article of its journals (PLOS ONE and the others) is open access under CC BY, with its
abstract and a PDF anyone may download. Free, no key; PLOS asks for at most ten searches a minute."""

import re
from typing import Any, Dict, Iterator, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, year_of

API = "https://api.plos.org/search"
PDF = "https://journals.plos.org/plosone/article/file?id={doi}&type=printable"  # any PLOS journal's DOI is served
PAGE = "https://journals.plos.org/plosone/article?id={doi}"
_ROWS = 100
_FIELDS = "id,title_display,abstract,publication_date,journal,author_display,article_type"
_TERM = re.compile(r'"([^"]+)"|(\S+)')
_SOLR_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def build_query(query: str) -> str:
    """Every word (or quoted phrase) of the query in the title or in the abstract:
    'argyrodite "ionic conductivity"' -> title:(argyrodite AND "ionic conductivity") OR abstract:(...)."""
    terms = [f'"{_SOLR_SPECIAL.sub(r"", phrase)}"' if phrase else _SOLR_SPECIAL.sub(r"\\\1", word)
             for phrase, word in _TERM.findall(query)]
    joined = " AND ".join(t for t in terms if t.strip('"'))
    return f"title:({joined}) OR abstract:({joined})"


def candidate_from_doc(doc: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(doc.get("id") or "")
    title = plain(doc.get("title_display"))
    key = candidate_key(doi, "", title)
    if not key or not doi:
        return None
    abstract = abstract_or_nothing(" ".join(doc.get("abstract") or []))
    kind = (doc.get("article_type") or "").lower()
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="plos" if abstract else "",
        year=year_of(doc.get("publication_date")), journal=doc.get("journal") or "", publisher="PLOS",
        authors=list(doc.get("author_display") or [])[:8], work_type="review" if "review" in kind else "article",
        oa_status="gold", oa_urls=[PDF.format(doi=doi)], landing_url=PAGE.format(doi=doi), license="cc-by",
        found_by=[found_by])


class PLOS(Source):
    name, label = "plos", "PLOS"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        filters = ["doc_type:full"]
        if years:
            filters.append(f"publication_date:[{years[0]}-01-01T00:00:00Z TO {years[1]}-12-31T23:59:59Z]")
        start = 0
        while start < limit:
            rows = min(_ROWS, limit - start)
            data = self.client.get_json(API, params={"q": build_query(query), "fq": " AND ".join(filters),
                                                     "fl": _FIELDS, "rows": rows, "start": start, "wt": "json"})
            docs = (data.get("response") or {}).get("docs") or []
            for doc in docs:
                candidate = candidate_from_doc(doc, f"plos: {query}")
                if candidate and in_years(candidate.year, years):
                    yield candidate
            if len(docs) < rows:
                return
            start += len(docs)

    def applies(self, candidate: Candidate) -> bool:
        return candidate.doi.startswith("10.1371/")

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(API, params={"q": f'id:"{candidate.doi}"', "fl": "id,abstract", "wt": "json"})
        return next((abstract_or_nothing(" ".join(d.get("abstract") or []))
                     for d in (data.get("response") or {}).get("docs") or [] if normalize_doi(d.get("id") or "") == candidate.doi), "")
