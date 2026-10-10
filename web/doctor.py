# web/doctor.py
"""`python main.py web --check`: what this setup can and cannot do, before a long run finds out the
hard way. Every line says what it tried and what came back."""

import os
from typing import List, Optional, Tuple

import pandas as pd
import requests

from web.elsevier import Elsevier
from web.http import PoliteClient
from web.job import Job
from web.resolve import APS, HAL, OPENAIRE, OSTI, PMC_CLOUD, SEMANTIC_SCHOLAR
from web.sources.openalex import BASE as OPENALEX
from web.wiley import Wiley

_UNPAYWALL_TEST_DOI = "10.1038/nature12373"  # an open-access paper Unpaywall certainly knows
_TEST_DOI = "10.1038/s41467-021-21488-7"     # an open-access paper every repository service can be asked about
_WILEY_TEST_DOI = "10.1002/advs.202000196"   # an open-access Wiley article: any valid token fetches it
# One small request per source of `fetch.sources` that needs no key: can it be reached from here?
_PROBES = {
    "pmc": ("PubMed Central (open-access set)", f"{PMC_CLOUD}/", {"list-type": "2", "prefix": "PMC7902639.", "max-keys": "1"}),
    "osti": ("OSTI (US Department of Energy)", OSTI, {"doi": _TEST_DOI}),
    "hal": ("HAL (France)", HAL, {"q": f'doiId_s:"{_TEST_DOI}"', "rows": 1, "wt": "json"}),
    "semanticscholar": ("Semantic Scholar", f"{SEMANTIC_SCHOLAR}/DOI:{_TEST_DOI}", {"fields": "externalIds"}),
    "openaire": ("OpenAIRE", OPENAIRE, {"pid": _TEST_DOI}),
    "aps": ("APS (open-access articles)", f"{APS}/10.1103/PhysRevResearch.6.043210", None),
}


def _probe_doi(papers_csv: str) -> str:
    """An Elsevier DOI from the papers already in the database: a paper the subscription is known to cover."""
    try:
        dois = pd.read_csv(papers_csv, usecols=["doi"], dtype=str)["doi"].dropna()
    except Exception:
        return ""
    return next((d for d in dois if d.lower().startswith("10.1016/")), "")


def report(job: Job, client: PoliteClient, probe_doi: str = "", papers_csv: str = os.path.join("output", "papers.csv"),
           elsevier: Optional[Elsevier] = None, wiley: Optional[Wiley] = None) -> List[Tuple[bool, str]]:
    """What was tried and what came back, one (worked?, sentence) per line."""
    lines: List[Tuple[bool, str]] = []

    email = job.email()
    lines.append((bool(email), "contact email: set" if email else
                  "contact email: NOT set. Unpaywall needs one and OpenAlex answers faster with one: "
                  "set contact_email in the job file or AUTOMATEXTRACT_EMAIL"))

    for label, url, params in (("OpenAlex", f"{OPENALEX}/works", {"per-page": 1}),
                               ("arXiv API", "https://export.arxiv.org/api/query", {"search_query": "all:electrolyte", "max_results": 1})):
        try:
            status = client.get(url, params=params).status_code
            lines.append((status == 200, f"{label}: {'reachable' if status == 200 else f'HTTP {status}'}"))
        except requests.RequestException as error:
            lines.append((False, f"{label}: no answer ({type(error).__name__})"))

    if email:
        try:
            status = client.get(f"https://api.unpaywall.org/v2/{_UNPAYWALL_TEST_DOI}", params={"email": email}).status_code
            lines.append((status == 200, f"Unpaywall: {'works with your email' if status == 200 else f'HTTP {status}'}"))
        except requests.RequestException as error:
            lines.append((False, f"Unpaywall: no answer ({type(error).__name__})"))
    else:
        lines.append((False, "Unpaywall: skipped (no contact email)"))

    elsevier = elsevier or Elsevier.from_env()
    if elsevier is None:
        lines.append((False, "Elsevier: ELSEVIER_API_KEY is not set, so Elsevier papers can only come from open copies. "
                             "Get a free key at https://dev.elsevier.com/ (while on your university's network), then put "
                             "ELSEVIER_API_KEY=... in a .env file next to main.py"))
    else:
        doi = probe_doi or _probe_doi(papers_csv)
        if not doi:
            lines.append((False, "Elsevier: key found, but there is no Elsevier DOI to test it with: pass --probe-doi 10.1016/..."))
        else:
            lines.append((True, f"Elsevier: key found (+ institutional token)" if elsevier.insttoken else "Elsevier: key found"))
            lines.extend((ok, f"Elsevier, {text}") for ok, text in elsevier.check(client, doi))

    if "wiley" in job.fetch.sources:
        wiley = wiley or Wiley.from_env()
        if wiley is None:
            lines.append((False, "Wiley: WILEY_TDM_TOKEN is not set, so Wiley papers can only come from other copies. "
                                 "A token is free: sign in at https://onlinelibrary.wiley.com/library-info/resources/"
                                 "text-and-datamining, then put WILEY_TDM_TOKEN=... in the .env file"))
        else:
            ok, text = wiley.check(client, _WILEY_TEST_DOI)
            lines.append((ok, f"Wiley: {text}"))

    for name in job.fetch.sources:
        if name not in _PROBES:
            continue
        label, url, params = _PROBES[name]
        try:
            # A check says what it finds now: a service in trouble is reported, not waited for.
            response = client.get(url, params=params, stream=True, no_retry={429, 500, 502, 503, 504},
                                  headers={"Accept": "application/pdf"} if name == "aps" else None)
            status = response.status_code
            response.close()
            lines.append((status == 200, f"{label}: {'reachable' if status == 200 else f'HTTP {status}'}"))
        except requests.RequestException as error:
            lines.append((False, f"{label}: no answer ({type(error).__name__})"))

    folder = job.fetch.folder
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        open(probe, "w").close()
        os.remove(probe)
        lines.append((True, f"download folder {folder}: writable"))
    except OSError as error:
        lines.append((False, f"download folder {folder}: {error}"))

    return lines


def check(job: Job, client: PoliteClient, probe_doi: str = "", papers_csv: str = os.path.join("output", "papers.csv"),
          elsevier: Optional[Elsevier] = None, wiley: Optional[Wiley] = None) -> int:
    """Prints the report; the exit code says whether the essentials (the search, the folder) are there."""
    lines = report(job, client, probe_doi, papers_csv, elsevier, wiley)
    for ok, text in lines:
        print(f"  [{'ok' if ok else '!!'}] {text}")
    essential = [ok for ok, text in lines if text.startswith(("OpenAlex", "download folder"))]
    return 0 if all(essential) else 1
