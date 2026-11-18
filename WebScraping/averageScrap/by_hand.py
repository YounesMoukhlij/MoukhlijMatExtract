# WebScraping/by_hand.py
"""The papers downloaded by hand. Every paper the download could not get is listed in
to_download_by_hand.csv (fetch.HAND_LIST) with its link, why it was missed and what can be done (`missed_rows`):
a site that refuses programs (HTTP 403) still lets a person read the paper in a browser. A PDF saved from a browser into the by_hand folder (BY_HAND_FOLDER, in the papers folder),
under any name, is taken in by the next download:

  - its DOI is read from its first pages or its metadata (or from its name, 10.3390_batteries9020137.pdf);
  - it is taken in only if that DOI is one of the list's, and its first pages carry the paper's title;
  - it is then moved into the papers folder under the paper's name, with the sidecar every downloaded
    paper has: where it came from (the article's link, saved by hand in a browser), when, its checksum.

A PDF that matches nothing stays in the by_hand folder, and the log says why."""

import csv
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from WebScraping.averageScrap.fetch import _NOT_NOW, NOT_ENTITLED_MARK, SITE_BLOCKED_MARK, check_pdf, save_copy
from WebScraping.averageScrap.ids import file_stem, normalize_doi
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, FAILED, Candidate, Ledger
from WebScraping.averageScrap.resolve import FetchOption

BY_HAND_FOLDER = "by_hand"
# What the sidecar of a PDF taken in from the by_hand folder says of its source (with the article's link).
BY_HAND_SERVICE = "by hand (the article's page, in a browser)"
_DOI = re.compile(r'10\.\d{4,9}/[^\s"<>]+', re.IGNORECASE)
_DOI_NAME = re.compile(r"^(10\.\d{4,9})_(\S+)$")

# Why a paper was not downloaded, and what can be done about it — in the order of the list, the ones a person
# can get at once first.
BLOCKED = "Site refuses programs"
SUBSCRIPTION = "Subscription needed"
NO_COPY = "No open copy found"
NOT_FOUND = "Not found at the sources"
BUSY = "Site busy or not answering"
REASONS = {
    BLOCKED: "Open the link in your browser and save the PDF into the by_hand folder.",
    SUBSCRIPTION: "Run “3 · Download” on the university's network (campus or VPN), or get it by hand.",
    NO_COPY: "Get it by hand: the publisher's page, your library, or the authors.",
    NOT_FOUND: "Tried again by the next download; or get it by hand.",
    BUSY: "Nothing to do: the next download tries it again by itself.",
}
_OPEN_FIRST = {"gold": 0, "diamond": 0, "hybrid": 1, "bronze": 2, "green": 3}
HAND_COLUMNS = ("doi", "title", "year", "journal", "open_access", "reason", "what_to_do", "link", "detail")


def reason_of(c: Candidate) -> str:
    """Why this paper (failed or closed) has no PDF yet: one of REASONS."""
    error = c.error or ""
    # The 403s of a site (not of a publisher's API, which refuses for the subscription): programs are refused.
    site_refusals = error.count("HTTP 403") - error.count(f"HTTP 403 ({NOT_ENTITLED_MARK}")
    if site_refusals or SITE_BLOCKED_MARK in error:
        return BLOCKED
    if NOT_ENTITLED_MARK in error:  # a publisher's API refused, or sent the first page only
        return SUBSCRIPTION
    if c.status == FAILED and (error.startswith("waiting") or _NOT_NOW.search(error)):
        return BUSY
    if c.status == CLOSED:
        return NO_COPY
    return NOT_FOUND


def missed_rows(folder: str, ledger: Ledger, keys: Optional[set] = None) -> List[Dict[str, str]]:
    """The papers the downloads could not get (failed or closed), as the rows of the hand list: those `keys`
    only when given. A paper whose PDF is in the folder already is left out."""
    rows = []
    for c in ledger.all(FAILED, CLOSED):
        if keys is not None and c.key not in keys:
            continue
        if os.path.isfile(os.path.join(folder, f"{file_stem(c.key)}.pdf")):
            continue
        reason = reason_of(c)
        rows.append({"doi": c.doi, "title": c.title, "year": str(c.year or ""), "journal": c.journal,
                     "open_access": c.oa_status or "unknown", "reason": reason, "what_to_do": REASONS[reason],
                     "link": f"https://doi.org/{c.doi}" if c.doi else (c.landing_url or (c.oa_urls[0] if c.oa_urls else "")),
                     "detail": (c.error or "")[:300], "key": c.key})
    order = list(REASONS)
    rows.sort(key=lambda r: (order.index(r["reason"]), _OPEN_FIRST.get(r["open_access"], 4), r["doi"]))
    return rows


def write_hand_list(path: str, rows: List[Dict[str, str]]) -> None:
    """Writes the hand list (removed when there is nothing on it)."""
    if not rows:
        if os.path.exists(path):
            os.remove(path)
        return
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HAND_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def inbox(folder: str) -> str:
    """The by_hand folder of a papers folder (made when missing)."""
    path = os.path.join(folder, BY_HAND_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def waiting(folder: str) -> int:
    """How many PDFs wait in the by_hand folder of a papers folder (the next download takes them in)."""
    try:
        return sum(1 for name in os.listdir(os.path.join(folder, BY_HAND_FOLDER)) if name.lower().endswith(".pdf"))
    except OSError:
        return 0


def read_hand_list(path: str) -> Dict[str, Dict[str, str]]:
    """The rows of to_download_by_hand.csv, by DOI (lower case). Empty when there is no list."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return {normalize_doi(row.get("doi", "")): row for row in csv.DictReader(f) if normalize_doi(row.get("doi", ""))}
    except OSError:
        return {}


def dois_in(data: bytes, filename: str = "") -> List[str]:
    """The DOIs a PDF names, the likeliest first: its file name, its metadata, then its first two pages
    (a paper's own DOI is printed on its first page; the references come later)."""
    found: List[str] = []

    def add(text: str) -> None:
        for match in _DOI.finditer(text or ""):
            doi = normalize_doi(match.group())
            if doi and doi not in found:
                found.append(doi)

    name = _DOI_NAME.match(os.path.splitext(os.path.basename(filename))[0])
    if name:
        add(f"{name.group(1)}/{name.group(2)}")
    try:
        import pymupdf
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return found
    try:
        add(" ".join(str(v) for v in (document.metadata or {}).values() if v))
        for index in range(min(2, document.page_count)):
            add(document[index].get_text("text"))
    except Exception:
        pass
    finally:
        document.close()
    return found


def take_in(folder: str, ledger: Ledger, hand_list: str) -> int:
    """Takes in the PDFs of the by_hand folder that are papers of the hand list (see the module's text).
    Returns how many were taken in."""
    box = inbox(folder)
    files = sorted(f for f in os.listdir(box) if f.lower().endswith(".pdf"))
    if not files:
        return 0
    wanted = read_hand_list(hand_list)
    by_doi: Dict[str, Candidate] = {c.doi.lower(): c for c in ledger.all() if c.doi}
    taken = 0
    for name in files:
        path = os.path.join(box, name)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as error:
            logging.warning(f"By hand: {name} cannot be read ({error}) — left in {box}.")
            continue
        # Every DOI of the list the PDF names, the likeliest first. A first page can also cite another paper of the
        # list: the PDF is the paper whose title its first pages carry, not the first DOI found.
        listed = [(d, by_doi[d]) for d in dois_in(data, name) if d in wanted and d in by_doi]
        if not listed:
            logging.warning(f"By hand: {name} names no DOI of {os.path.basename(hand_list)} — left in {box}. "
                            "(Is it the right article? Its DOI must be printed on its first page, or be its file "
                            "name: 10.3390_batteries9020137.pdf.)")
            continue
        match = next(((d, c, check) for d, c in listed if c.status != DOWNLOADED
                      for check in [check_pdf(data, c.title)] if check.ok), None)
        if match is None:
            doi, candidate = listed[0]
            why = ("which is downloaded already" if candidate.status == DOWNLOADED
                   else f"not taken in: {check_pdf(data, candidate.title).reason}")
            logging.warning(f"By hand: {name} names {doi}, {why} — left in {box}.")
            continue
        doi, candidate, check = match
        link = wanted[doi].get("link") or f"https://doi.org/{doi}"
        outcome = save_copy(folder, candidate, FetchOption(BY_HAND_SERVICE, link, license=candidate.license), data, check)
        ledger.update(candidate.key, status=DOWNLOADED, file=outcome.file, sha256=outcome.sha256,
                      source_used=BY_HAND_SERVICE, source_url=link, license=outcome.license, error="",
                      retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        os.remove(path)  # moved: the same bytes are in the papers folder now, with their record
        taken += 1
        logging.info(f"By hand: {name} taken in as {doi} → {outcome.file} (its source is recorded: {link}).")
    return taken

