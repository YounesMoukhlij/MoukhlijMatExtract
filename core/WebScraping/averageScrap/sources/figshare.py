# WebScraping/sources/figshare.py
"""Figshare: the repository many universities keep their theses and papers in (Deakin, Purdue,
Newcastle, Loughborough, …), and the former home of TechRxiv. Free, no key. Its search also lists
the supporting information of journal articles (ACS, Taylor & Francis) — those files are not the
paper and are left out."""

import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license, year_of

API = "https://api.figshare.com/v2"
_PAGE = 100
_MAX_PAGES = 10
# The kinds of item that are a paper (Figshare's defined_type), and what they are here.
_PAPERS = {6: "article", 8: "thesis", 12: "preprint", 14: "article", 18: "report"}
# The DOI of a journal article's supporting information: the article's own DOI + ".s001".
_SUPPLEMENT = re.compile(r'\.s\d{3}$')


def is_paper(item: Dict[str, Any]) -> bool:
    return item.get("defined_type") in _PAPERS and not _SUPPLEMENT.search(item.get("doi") or "")


def candidate_from_article(article: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    doi = normalize_doi(article.get("doi") or "")
    title = plain(article.get("title"))
    key = candidate_key(doi, "", title)
    if not key or not is_paper(article):
        return None
    pdfs: List[str] = [f["download_url"] for f in article.get("files") or []
                       if (f.get("name") or "").lower().endswith(".pdf") and f.get("download_url")
                       and not f.get("is_link_only")]
    kind = _PAPERS[article["defined_type"]]
    abstract = abstract_or_nothing(article.get("description"))
    license = article.get("license") or {}
    return Candidate(
        key=key, doi=doi, title=title, abstract=abstract, abstract_from="figshare" if abstract else "",
        year=year_of(article.get("published_date")), publisher="Figshare",
        authors=[a.get("full_name", "") for a in (article.get("authors") or [])[:8]], work_type=kind,
        is_preprint=kind == "preprint", oa_status="green" if pdfs else "", oa_urls=pdfs,
        landing_url=article.get("url_public_html") or "", license=spell_license(license.get("url") or license.get("name") or ""),
        found_by=[found_by])


class Figshare(Source):
    name, label = "figshare", "Figshare"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        body: Dict[str, Any] = {"search_for": query, "page_size": _PAGE}
        if years:
            body["published_since"] = f"{years[0]}-01-01"
        seen = 0
        for page in range(1, _MAX_PAGES + 1):
            items = self.client.post_json(f"{API}/articles/search", {**body, "page": page}) or []
            for item in items:
                if not is_paper(item):
                    continue
                # The search gives no description and no files: the record of the item does.
                article = self.client.get_json(f"{API}/articles/{item['id']}")
                candidate = candidate_from_article(article, f"figshare: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(items) < _PAGE:
                return
