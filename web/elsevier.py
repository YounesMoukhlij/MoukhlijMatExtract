# web/elsevier.py
"""Elsevier (ScienceDirect) through its own API: the sanctioned way to read, by machine, the full
texts a subscription includes. It needs

  - an API key (free at https://dev.elsevier.com/, set as ELSEVIER_API_KEY), and
  - the entitlement of the institution the key is tied to: the request has to come from that
    institution's network (campus or VPN), or carry the institutional token Elsevier issues on
    request (ELSEVIER_INSTTOKEN).

Without that the API answers 401/403 and this module says so (`check`); it never tries anything
else. Use is limited by Elsevier's text-and-data-mining terms and a weekly quota."""

import os
from typing import Dict, List, Optional, Tuple

from web.http import PoliteClient
from web.ledger import Candidate

BASE = "https://api.elsevier.com/content"
PREFIXES = ("10.1016/",)


class Elsevier:
    def __init__(self, api_key: str, insttoken: str = ""):
        self.api_key, self.insttoken = api_key, insttoken

    @classmethod
    def from_env(cls) -> Optional["Elsevier"]:
        key = os.environ.get("ELSEVIER_API_KEY", "").strip()
        return cls(key, os.environ.get("ELSEVIER_INSTTOKEN", "").strip()) if key else None

    @staticmethod
    def applies(candidate: Candidate) -> bool:
        """Elsevier DOIs start 10.1016/; the publisher's name catches the rest."""
        return candidate.doi.startswith(PREFIXES) or "elsevier" in candidate.publisher.lower()

    @staticmethod
    def url(doi: str) -> str:
        return f"{BASE}/article/doi/{doi}"

    def headers(self, accept: str) -> Dict[str, str]:
        headers = {"X-ELS-APIKey": self.api_key, "Accept": accept}
        if self.insttoken:
            headers["X-ELS-Insttoken"] = self.insttoken
        return headers

    def check(self, client: PoliteClient, doi: str) -> List[Tuple[bool, str]]:
        """What this key can actually do for one DOI, in plain words — the first thing to run when
        Elsevier papers do not arrive. Three requests: the key, the full text as XML, the PDF."""
        report: List[Tuple[bool, str]] = []
        probes = (("the key is accepted", "application/json", {"view": "META_ABS"}),
                  ("full text as XML", "text/xml", {}),
                  ("full text as PDF", "application/pdf", {}))
        for label, accept, params in probes:
            try:
                response = client.get(self.url(doi), params=params or None, headers=self.headers(accept),
                                      stream=True, no_retry={429})
            except Exception as error:  # a check must report, not crash
                report.append((False, f"{label}: no answer ({type(error).__name__})"))
                continue
            try:
                status = response.status_code
                note = response.headers.get("X-ELS-Status", "")
                if status == 200 and accept == "application/pdf":
                    ok = next(response.iter_content(8), b"").startswith(b"%PDF")
                    report.append((ok, f"{label}: {'yes' if ok else 'answered 200 but not with a PDF'}"))
                elif status == 200:
                    report.append((True, f"{label}: yes"))
                else:
                    meaning = {401: "the key is not valid", 403: "not entitled — run from the institution's network "
                               "or ask Elsevier for an institutional token", 404: "Elsevier does not know this DOI",
                               429: "weekly quota used up"}.get(status, "")
                    report.append((False, f"{label}: HTTP {status}" + (f" ({meaning})" if meaning else "")
                                   + (f" [{note}]" if note else "")))
            finally:
                response.close()
        return report
