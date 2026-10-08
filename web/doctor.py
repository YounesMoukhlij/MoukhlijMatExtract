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
from web.sources.openalex import BASE as OPENALEX

_UNPAYWALL_TEST_DOI = "10.1038/nature12373"  # an open-access paper Unpaywall certainly knows


def _probe_doi(papers_csv: str) -> str:
    """An Elsevier DOI from the papers already in the database: a paper the subscription is known to cover."""
    try:
        dois = pd.read_csv(papers_csv, usecols=["doi"], dtype=str)["doi"].dropna()
    except Exception:
        return ""
    return next((d for d in dois if d.lower().startswith("10.1016/")), "")


def check(job: Job, client: PoliteClient, probe_doi: str = "", papers_csv: str = os.path.join("output", "papers.csv"),
          elsevier: Optional[Elsevier] = None) -> int:
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

    folder = job.fetch.folder
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        open(probe, "w").close()
        os.remove(probe)
        lines.append((True, f"download folder {folder}: writable"))
    except OSError as error:
        lines.append((False, f"download folder {folder}: {error}"))

    for ok, text in lines:
        print(f"  [{'ok' if ok else '!!'}] {text}")
    essential = [ok for ok, text in lines if text.startswith(("OpenAlex", "download folder"))]
    return 0 if all(essential) else 1
