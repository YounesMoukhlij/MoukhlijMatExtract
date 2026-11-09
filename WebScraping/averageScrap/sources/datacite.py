# WebScraping/sources/datacite.py
"""DataCite: the DOI registry of repositories, universities and research centres (the DOIs Crossref
does not hold). Its "text" records are the papers, theses and reports those institutions keep —
often the free copy of a journal article (the record then names the journal's DOI). Free, no key."""

from typing import Any, Dict, Iterator, List, Optional, Tuple

from WebScraping.averageScrap.ids import arxiv_id, candidate_key, normalize_doi
from WebScraping.averageScrap.ledger import Candidate
from WebScraping.averageScrap.sources.common import Source, abstract_or_nothing, in_years, plain, spell_license

API = "https://api.datacite.org/dois"
_PAGE = 25         # a larger page can take DataCite longer than the client waits
_MAX_PAGE = 40     # DataCite pages by number up to 1,000 results
# A record that is another form of a journal article: the repository copy of that DOI.
SAME_WORK = {"IsVariantFormOf", "IsIdenticalTo", "IsVersionOf", "IsPreprintOf", "IsManuscriptOf"}
_OPEN_WORDS = ("openaccess", "creativecommons", "open access")


def is_open(attributes: Dict[str, Any]) -> bool:
    """Whether the record says anyone may read it (an open-access right, a Creative Commons licence)."""
    for right in attributes.get("rightsList") or []:
        text = f"{right.get('rights') or ''} {right.get('rightsUri') or ''} {right.get('rightsIdentifier') or ''}".lower()
        if any(word in text.replace(" ", "") or word in text for word in _OPEN_WORDS):
            return True
    return False


def license_of(attributes: Dict[str, Any]) -> str:
    for right in attributes.get("rightsList") or []:
        spelled = spell_license(right.get("rightsUri") or right.get("rightsIdentifier") or "")
        if spelled.startswith("cc"):
            return spelled
    return ""


def kind_of(attributes: Dict[str, Any]) -> str:
    types = attributes.get("types") or {}
    text = f"{types.get('resourceTypeGeneral') or ''} {types.get('resourceType') or ''}".lower()
    for word, kind in (("preprint", "preprint"), ("working paper", "preprint"), ("thesis", "thesis"),
                       ("dissertation", "thesis"), ("report", "report"), ("technical note", "report"),
                       ("book chapter", "book-chapter"), ("book", "book")):
        if word in text:
            return kind
    return "article"


def same_work(attributes: Dict[str, Any]) -> List[str]:
    """The DOIs this record is another form of (the journal version of a repository copy)."""
    return [normalize_doi(r.get("relatedIdentifier") or "") for r in attributes.get("relatedIdentifiers") or []
            if r.get("relationType") in SAME_WORK and (r.get("relatedIdentifierType") or "").upper() == "DOI"]


def candidate_from_record(record: Dict[str, Any], found_by: str) -> Optional[Candidate]:
    attributes = record.get("attributes") or {}
    doi = normalize_doi(attributes.get("doi") or record.get("id") or "")
    preprint = arxiv_id(doi)  # arXiv registers its DOIs here: the arXiv source has those papers already
    title = plain(next((t.get("title") for t in attributes.get("titles") or [] if t.get("title")), ""))
    key = candidate_key("" if preprint else doi, preprint, title)
    if not key:
        return None
    abstract = abstract_or_nothing(next((d.get("description") for d in attributes.get("descriptions") or []
                                         if d.get("descriptionType") == "Abstract"), ""))
    publisher = attributes.get("publisher") or ""
    publisher = publisher.get("name", "") if isinstance(publisher, dict) else str(publisher)
    container = attributes.get("container") or {}
    kind = kind_of(attributes)
    url = attributes.get("url") or ""
    opened = is_open(attributes)
    return Candidate(
        key=key, doi="" if preprint else doi, arxiv_id=preprint, title=title, abstract=abstract,
        abstract_from="datacite" if abstract else "", year=int(attributes.get("publicationYear") or 0),
        journal=container.get("title") or "", publisher=publisher,
        authors=[c.get("name", "") for c in (attributes.get("creators") or [])[:8]], work_type=kind,
        is_preprint=kind == "preprint", oa_status="green" if opened and url else "",
        oa_urls=[attributes["contentUrl"][0]] if opened and attributes.get("contentUrl") else [],
        copy_pages=[url] if opened and url else [], landing_url=url, license=license_of(attributes), found_by=[found_by])


class DataCite(Source):
    name, label = "datacite", "DataCite"

    def search(self, query: str, years: Optional[Tuple[int, int]] = None, limit: int = 200,
               include_preprints: bool = True) -> Iterator[Candidate]:
        params: Dict[str, Any] = {"query": query, "resource-type-id": "text", "page[size]": _PAGE}
        if years:
            params["published"] = f"{years[0]},{years[1]}"
        number, seen = 1, 0
        while seen < limit and number <= _MAX_PAGE:
            data = self.client.get_json(API, params={**params, "page[number]": number})
            records = data.get("data") or []
            for record in records:
                candidate = candidate_from_record(record, f"datacite: {query}")
                if candidate and in_years(candidate.year, years) and (include_preprints or not candidate.is_preprint):
                    yield candidate
                    seen += 1
                    if seen >= limit:
                        return
            if len(records) < _PAGE:
                return
            number += 1

    def copies_of(self, doi: str) -> List[Dict[str, Any]]:
        """The repository records that say they are another form of this DOI (a journal article)."""
        data = self.client.get_json(API, params={"query": f'relatedIdentifiers.relatedIdentifier:"{doi}"',
                                                 "page[size]": 10})
        return [r for r in data.get("data") or [] if doi in same_work(r.get("attributes") or {})
                and ((r.get("attributes") or {}).get("types") or {}).get("resourceTypeGeneral") != "Dataset"]

    def abstract(self, candidate: Candidate) -> str:
        data = self.client.get_json(f"{API}/{candidate.doi}")
        attributes = (data.get("data") or {}).get("attributes") or {}
        return abstract_or_nothing(next((d.get("description") for d in attributes.get("descriptions") or []
                                         if d.get("descriptionType") == "Abstract"), ""))
