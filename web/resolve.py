# web/resolve.py
"""Where a legal copy of a paper may be had. A resolver does not download anything: it lists the
places to try, best first, and the downloader tries them in order until one gives a real PDF.
The order comes from the job (`fetch.sources`); a source that does not apply to a paper — Elsevier's
API for a Nature paper, Unpaywall without a contact email — simply offers nothing."""

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from web.elsevier import Elsevier
from web.http import HttpError, PoliteClient
from web.ledger import Candidate

UNPAYWALL = "https://api.unpaywall.org/v2"


@dataclass
class FetchOption:
    service: str                 # which source offered it: elsevier | openalex | unpaywall | arxiv
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    license: str = ""
    api: bool = False            # a call to an API under its own terms: robots.txt is not consulted
    landing: bool = False        # a web page that may point to the PDF (citation_pdf_url), not the PDF itself


class Resolver:
    def __init__(self, client: PoliteClient, sources: List[str], contact: str = "",
                 elsevier: Optional[Elsevier] = None):
        self.client, self.sources, self.contact, self.elsevier = client, sources, contact, elsevier
        self._warned_unpaywall = False

    def options(self, candidate: Candidate) -> Iterator[FetchOption]:
        seen = set()
        for service in self.sources:
            for option in getattr(self, f"_{service}")(candidate):
                if option.url not in seen:
                    seen.add(option.url)
                    yield option

    # ------------------------------------------------------------------
    # One method per source
    # ------------------------------------------------------------------
    def _elsevier(self, c: Candidate) -> Iterator[FetchOption]:
        if self.elsevier and c.doi and Elsevier.applies(c):
            yield FetchOption("elsevier", Elsevier.url(c.doi), self.elsevier.headers("application/pdf"),
                              license="Elsevier subscription (text-and-data-mining terms)", api=True)

    def _openalex(self, c: Candidate) -> Iterator[FetchOption]:
        for url in c.oa_urls:
            yield FetchOption("openalex", url, license=c.license)
        if c.landing_url and c.access == "open":
            yield FetchOption("openalex", c.landing_url, license=c.license, landing=True)

    def _unpaywall(self, c: Candidate) -> Iterator[FetchOption]:
        if not c.doi:
            return
        if not self.contact:
            if not self._warned_unpaywall:
                logging.warning("Unpaywall is skipped: it requires a contact email "
                                "(contact_email in the job file, or AUTOMATEXTRACT_EMAIL).")
                self._warned_unpaywall = True
            return
        try:
            data = self.client.get_json(f"{UNPAYWALL}/{c.doi}", params={"email": self.contact})
        except HttpError as error:
            logging.debug(f"Unpaywall has nothing for {c.doi}: {error}")
            return
        for location in [data.get("best_oa_location"), *(data.get("oa_locations") or [])]:
            if not location:
                continue
            if location.get("url_for_pdf"):
                yield FetchOption("unpaywall", location["url_for_pdf"], license=location.get("license") or "")
            elif location.get("url_for_landing_page"):
                yield FetchOption("unpaywall", location["url_for_landing_page"], landing=True,
                                  license=location.get("license") or "")

    def _arxiv(self, c: Candidate) -> Iterator[FetchOption]:
        if c.arxiv_id:
            yield FetchOption("arxiv", f"https://arxiv.org/pdf/{c.arxiv_id}", license="arxiv")
