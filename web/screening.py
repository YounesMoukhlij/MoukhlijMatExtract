# web/screening.py
"""Which candidates are worth fetching. A transparent score from the title and abstract (so a person
can see why a paper was proposed), plus the flags a reader wants before approving: a preprint, a
review, a retraction, a duplicate of another candidate, no legal copy to be had."""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from web.elsevier import Elsevier
from web.ids import normalize_title
from web.job import ScreenConfig
from web.ledger import APPROVED, DOWNLOADED, EXTRACTED, NEW, NO, REJECTED, SCREENED, YES, Candidate, Ledger

_TITLE_POINTS, _ABSTRACT_POINTS, _EXCLUDE_POINTS = 2, 1, -3
_OPEN = {"gold", "green", "hybrid", "bronze", "diamond"}
_MIN_TITLE_LENGTH = 20  # shorter normalized titles are too generic to call two papers one


def _pattern(word: str) -> re.Pattern:
    """A word or phrase as running text writes it: any spacing or a hyphen between its words, and
    an optional plural ("conductivity" also finds "conductivities")."""
    *head, last = re.split(r'[\s-]+', word.strip())
    tail = re.escape(last[:-1]) + r'(?:y|ies)' if last.lower().endswith("y") else re.escape(last) + r's?'
    return re.compile(r'(?<![A-Za-z0-9])' + r'[\s-]+'.join([*map(re.escape, head), tail]) + r'(?![A-Za-z0-9])',
                      re.IGNORECASE)


def _hits(candidate: Candidate, words: List[Tuple[str, re.Pattern]]) -> Tuple[int, List[str]]:
    """Points and the words found: a word in the title counts more than one only in the abstract."""
    points, found = 0, []
    for word, pattern in words:
        if pattern.search(candidate.title):
            points += _TITLE_POINTS
            found.append(f"{word} (title)")
        elif pattern.search(candidate.abstract):
            points += _ABSTRACT_POINTS
            found.append(f"{word} (abstract)")
    return points, found


def access_of(candidate: Candidate, elsevier_ok: bool) -> str:
    """How a copy is expected to be had: from an open source, through Elsevier's API, or not at all."""
    if candidate.oa_urls or candidate.arxiv_id or candidate.oa_status in _OPEN:
        return "open"
    if elsevier_ok and Elsevier.applies(candidate):
        return "elsevier"
    return "closed"


def _flags(candidate: Candidate, access: str) -> List[str]:
    flags = []
    if candidate.is_preprint:
        flags.append("preprint")
    if candidate.work_type == "review":
        flags.append("review")
    if candidate.is_retracted:
        flags.append("RETRACTED")
    if not candidate.abstract:
        flags.append("no-abstract")
    if access == "closed":
        flags.append("no-legal-copy")
    return flags


def _mark_duplicates(ledger: Ledger) -> int:
    """The same paper often arrives twice — a preprint and its journal version. The version that can
    be fetched and is published wins; the other waiting candidates are declined and say which one won."""
    groups: Dict[str, List[Candidate]] = defaultdict(list)
    for candidate in ledger.all():
        title = normalize_title(candidate.title)
        if len(title) >= _MIN_TITLE_LENGTH:
            groups[title].append(candidate)
    marked = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda c: (c.status not in (DOWNLOADED, EXTRACTED), c.is_preprint, c.access == "closed",
                                  -c.score, -c.year))
        winner = group[0]
        for loser in group[1:]:
            if loser.status == SCREENED and not any(f.startswith("duplicate-of") for f in loser.flags):
                ledger.update(loser.key, decision=NO, flags=[*loser.flags, f"duplicate-of:{winner.key}"])
                marked += 1
    return marked


def screen(ledger: Ledger, cfg: ScreenConfig, elsevier_ok: bool = False, approve: bool = False) -> Dict[str, int]:
    """Scores every candidate not yet scored and proposes a decision for it. With `approve` the
    proposals are final (no review): a yes is approved for fetching, a no is rejected."""
    topic = [(w, _pattern(w)) for w in cfg.topic_words]
    prop = [(w, _pattern(w)) for w in cfg.property_words]
    exclude = [(w, _pattern(w)) for w in cfg.exclude_words]

    for candidate in ledger.all(NEW):
        topic_points, topic_found = _hits(candidate, topic)
        prop_points, prop_found = _hits(candidate, prop)
        _, exclude_found = _hits(candidate, exclude)
        score = topic_points + prop_points + _EXCLUDE_POINTS * len(exclude_found)
        access = access_of(candidate, elsevier_ok)
        flags = _flags(candidate, access)
        passes = (score >= cfg.min_score and (bool(topic_found) or not topic)
                  and (bool(prop_found) or not prop) and not candidate.is_retracted and access != "closed")
        why = "; ".join(part for part in (
            f"topic: {', '.join(topic_found)}" if topic_found else "",
            f"property: {', '.join(prop_found)}" if prop_found else "",
            f"excluded: {', '.join(exclude_found)}" if exclude_found else "") if part)
        ledger.update(candidate.key, score=float(score), why=why or "no topic or property word found",
                      flags=flags, access=access, decision=YES if passes else NO, status=SCREENED)
    duplicates = _mark_duplicates(ledger)
    if duplicates:
        logging.info(f"Screening: {duplicates} duplicate(s) of another candidate declined.")

    if approve:
        for candidate in ledger.all(SCREENED):
            ledger.update(candidate.key, status=APPROVED if candidate.decision == YES else REJECTED)
    return ledger.counts()
