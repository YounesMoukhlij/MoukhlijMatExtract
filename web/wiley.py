# web/wiley.py
"""Wiley Online Library through its text-and-data-mining API: the sanctioned way to fetch, by
machine, the Wiley articles one may read — the open-access ones, and those of a subscription when
the request comes from the subscribing institution's network. It needs a token (free: sign in at
https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining and accept the
agreement), set as WILEY_TDM_TOKEN.

Without a token this source offers nothing. An article the token does not cover is answered with a
refusal, and that is the end of it. Wiley allows 60 requests in 10 minutes."""

import os
from typing import Dict, Optional, Tuple
from urllib.parse import quote

from web.http import PoliteClient
from web.ledger import Candidate

BASE = "https://api.wiley.com/onlinelibrary/tdm/v1/articles"
PREFIXES = ("10.1002/", "10.1111/")


class Wiley:
    def __init__(self, token: str):
        self.token = token

    @classmethod
    def from_env(cls) -> Optional["Wiley"]:
        token = os.environ.get("WILEY_TDM_TOKEN", "").strip()
        return cls(token) if token else None

    @staticmethod
    def applies(candidate: Candidate) -> bool:
        """Wiley DOIs start 10.1002/ or 10.1111/; the publisher's name catches the rest."""
        return candidate.doi.startswith(PREFIXES) or "wiley" in candidate.publisher.lower()

    @staticmethod
    def url(doi: str) -> str:
        return f"{BASE}/{quote(doi, safe='')}"  # the DOI is one path segment: its "/" has to be escaped

    def headers(self) -> Dict[str, str]:
        return {"Wiley-TDM-Client-Token": self.token}

    def check(self, client: PoliteClient, doi: str) -> Tuple[bool, str]:
        """Whether the token fetches one article, in plain words."""
        try:
            response = client.get(self.url(doi), headers=self.headers(), stream=True, no_retry={429})
        except Exception as error:  # a check must report, not crash
            return False, f"no answer ({type(error).__name__})"
        try:
            status = response.status_code
            if status == 200:
                ok = next(response.iter_content(8), b"").startswith(b"%PDF")
                return ok, "the token works" if ok else "answered 200 but not with a PDF"
            meaning = {400: "the token is missing or malformed", 403: "the token was refused, or this article is not "
                       "covered from where you run", 404: "Wiley does not know this DOI",
                       429: "no more requests allowed for now"}.get(status, "")
            return False, f"HTTP {status}" + (f" ({meaning})" if meaning else "")
        finally:
            response.close()
