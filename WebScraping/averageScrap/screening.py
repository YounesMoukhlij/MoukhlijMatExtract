# WebScraping/screening.py
"""Which candidates are worth fetching. A transparent score from the title and abstract (so a person
can see why a paper was proposed), plus the flags a reader wants before approving: a preprint, a
review, a retraction, a duplicate of another candidate, no open copy known."""

import logging
import re
from collections import defaultdict
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from WebScraping.averageScrap.elsevier import Elsevier
from WebScraping.averageScrap.ids import normalize_title
from WebScraping.averageScrap.wiley import Wiley
from WebScraping.averageScrap.job import ScreenConfig
from WebScraping.averageScrap.ledger import DOI_LIST, APPROVED, DOWNLOADED, EXTRACTED, NEW, NO, REJECTED, SCREENED, YES, Candidate, Ledger

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


# A formula word ("Li7La3Zr2O12", "La3Zr2O12", "LiZr2(PO4)3"): no space, a digit and a capital letter.
_FORMULA = re.compile(r"^(?=\S*\d)(?=\S*[A-Z])\S+$")
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋−", "0123456789+--")
_HAS_SUBSCRIPT = re.compile("[₀-₉₊₋−]")
_TAGS = re.compile(r"</?su[bp]>", re.IGNORECASE)
# A space inside a formula: before a digit, a bracket or the capital of the next element ("Li 7 La 3 Zr 2 O 12",
# "LiZr 2 (PO 4 ) 3"). A space before a word in lower case stays, so a formula is never glued to the next word.
_SPACE = re.compile(r"\s+(?=[0-9()\[\]A-Z])")


def _compact(text: str) -> str:
    """A text as a formula is looked for in it: subscript digits made plain, <sub> tags and the spaces inside formulas
    removed. Titles often come with the formula spread out ("Li 7 La 3 Zr 2 O 12", "LiZr 2 (PO 4 ) 3") or
    sub-scripted."""
    text = text or ""
    if _HAS_SUBSCRIPT.search(text):
        text = text.translate(_SUBSCRIPTS)
    if "<" in text:
        text = _TAGS.sub("", text)
    return _SPACE.sub("", text)


class _Word(NamedTuple):
    """A word of the job as it is looked for. A formula is looked for in the compact text, case kept (CO is not Co),
    anywhere — also inside a longer formula, so that the part of a family's formula finds its doped members
    (La3Zr2O12 in Li6.4Ga0.2La3Zr2O12). Another word: in the running text, as _pattern says; `needle` (its first
    part, in lower case) must be in the text before the pattern is tried, which makes a long list quick."""
    word: str
    pattern: "re.Pattern | None"
    needle: str
    formula: bool


def _word(word: str) -> _Word:
    if _FORMULA.match(word.strip()):
        # Anywhere in a longer formula (La3Zr2O12 in Li6.4Ga0.2La3Zr2O12), but not inside another element: an element
        # symbol goes on in lower case, so Li3N is not the start of Li3NbO4.
        needle = _SPACE.sub("", _compact(word))
        return _Word(word, re.compile(re.escape(needle) + r"(?![a-z])"), needle, True)
    first = re.split(r"[\s-]+", word.strip())[0].lower()
    return _Word(word, _pattern(word), first[:-1] if first.endswith("y") else first, False)


class _Text:
    """A title or an abstract, in the forms the words are looked for in (made once, when first needed)."""

    def __init__(self, text: str):
        self.text = text or ""
        self._lower: Optional[str] = None
        self._compact: Optional[str] = None

    def has(self, word: _Word) -> bool:
        if word.formula:
            if self._compact is None:
                self._compact = _compact(self.text)
            return word.needle in self._compact and bool(word.pattern.search(self._compact))
        if self._lower is None:
            self._lower = self.text.lower().replace("i\u0307", "i")  # "İonic" lower-cased is i + a dot
        return word.needle in self._lower and bool(word.pattern.search(self.text))


def _hits(candidate: Candidate, words: Sequence[_Word]) -> Tuple[int, List[str]]:
    """Points and the words found: a word in the title counts more than one only in the abstract."""
    points, found = 0, []
    title, abstract = _Text(candidate.title), _Text(candidate.abstract)
    for word in words:
        if title.has(word):
            points += _TITLE_POINTS
            found.append(f"{word.word} (title)")
        elif abstract.has(word):
            points += _ABSTRACT_POINTS
            found.append(f"{word.word} (abstract)")
    return points, found


def access_of(candidate: Candidate, elsevier_ok: bool, wiley_ok: bool = False) -> str:
    """How a copy is expected to be had: from an open source, through its publisher's API, or — as
    far as the search knows — not at all (a repository may still hold one: see `propose_closed`)."""
    if candidate.oa_urls or candidate.copy_pages or candidate.arxiv_id or candidate.oa_status in _OPEN:
        return "open"
    if elsevier_ok and Elsevier.applies(candidate):
        return "elsevier"
    if wiley_ok and Wiley.applies(candidate):
        return "wiley"
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
        flags.append("no-open-copy-known")
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


def _words(cfg: ScreenConfig) -> Tuple[List[_Word], List[_Word], List[_Word]]:
    """The topic, property and excluded words of a job, ready to be looked for (made once per screening)."""
    return ([_word(w) for w in cfg.topic_words], [_word(w) for w in cfg.property_words],
            [_word(w) for w in cfg.exclude_words])


def _judge(candidate: Candidate, cfg: ScreenConfig, words, elsevier_ok: bool, wiley_ok: bool) -> Dict[str, object]:
    """The score of a paper, why, its flags, how a copy is expected, and the decision proposed for it."""
    topic, prop, exclude = words
    topic_points, topic_found = _hits(candidate, topic)
    prop_points, prop_found = _hits(candidate, prop)
    _, exclude_found = _hits(candidate, exclude)
    score = topic_points + prop_points + _EXCLUDE_POINTS * len(exclude_found)
    access = access_of(candidate, elsevier_ok, wiley_ok)
    flags = _flags(candidate, access)
    passes = (score >= cfg.min_score and (bool(topic_found) or not topic)
              and (bool(prop_found) or not prop) and not candidate.is_retracted
              and (access != "closed" or cfg.propose_closed))
    why = "; ".join(part for part in (
        f"topic: {', '.join(topic_found)}" if topic_found else "",
        f"property: {', '.join(prop_found)}" if prop_found else "",
        f"excluded: {', '.join(exclude_found)}" if exclude_found else "") if part)
    return {"score": float(score), "why": why or "no topic or property word found", "flags": flags, "access": access,
            "decision": YES if passes else NO}


def screen(ledger: Ledger, cfg: ScreenConfig, elsevier_ok: bool = False, approve: bool = False,
           wiley_ok: bool = False) -> Dict[str, int]:
    """Scores every candidate not yet scored and proposes a decision for it. With `approve` the
    proposals are final (no review): a yes is approved for fetching, a no is rejected."""
    words = _words(cfg)
    scored = 0
    for candidate in ledger.all(NEW):
        if candidate.found_by == [DOI_LIST] and not candidate.openalex_id and "openalex" not in candidate.abstract_asked:
            continue  # a DOI and a title only: scored once its OpenAlex record was looked up (next search)
        ledger.update(candidate.key, status=SCREENED, **_judge(candidate, cfg, words, elsevier_ok, wiley_ok))
        scored += 1
    duplicates = _mark_duplicates(ledger) if scored else 0  # nothing new: no new duplicate either
    if duplicates:
        logging.info(f"Screening: {duplicates} duplicate(s) of another candidate declined.")

    if approve:
        for candidate in ledger.all(SCREENED):
            ledger.update(candidate.key, status=APPROVED if candidate.decision == YES else REJECTED)
    return ledger.counts()


def rescreen(ledger: Ledger, cfg: ScreenConfig, elsevier_ok: bool = False, wiley_ok: bool = False) -> Dict[str, int]:
    """Decides again, with the settings of now, the papers screened before and not downloaded yet (screened, approved
    or rejected): the settings changed since — “also keep papers no free copy is known for” ticked, a word added or
    excluded, another minimum score. A paper whose decision changes is a new proposal (screened), made final by the
    next download like any other. A paper downloaded, failed or closed is left as it is, and so is a duplicate
    declined for another candidate. A yes or no set by hand is decided again too. Returns how many papers were
    scored ("rescored"), newly proposed ("proposed") and no longer proposed ("dropped")."""
    words = _words(cfg)
    counts = {"rescored": 0, "proposed": 0, "dropped": 0}
    for candidate in ledger.all(SCREENED, APPROVED, REJECTED):
        if any(flag.startswith("duplicate-of") for flag in candidate.flags):
            continue
        judged = _judge(candidate, cfg, words, elsevier_ok, wiley_ok)
        counts["rescored"] += 1
        if judged["decision"] != candidate.decision:
            counts["proposed" if judged["decision"] == YES else "dropped"] += 1
            ledger.update(candidate.key, status=SCREENED, decided_by="", **judged)  # the rules' decision again
        elif (judged["score"], judged["why"], judged["flags"], judged["access"]) != \
                (candidate.score, candidate.why, candidate.flags, candidate.access):
            ledger.update(candidate.key, **judged)
    return counts
