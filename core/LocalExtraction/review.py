# LocalExtraction/review.py
"""Which extracted values a person should look at: the `needs_check` column of every quantity table.

A value is flagged — never left out — when something about it is doubtful, with the reasons:

  out of range         its plausibility says "check: …" (a number outside what ion conductors show, or the
                       transport of electrons or of a species that is no conducting ion)
  unusual formula      its material does not balance in charge under the usual oxidation states (a formula cut
                       short, "PSe", "Li6PS5"; a fragment of a name, "LiSO3"; also a few real compounds whose
                       metal takes a less usual state, Na3V2(PO4)3)
  material from another sentence
                       its own sentence names no material; the one before or the paragraph's topic was taken
  doped sample         its sentence speaks of a doped or substituted sample ("the Ta-doped LLZO") and its
                       material is the parent compound: the dopant is not in the formula
  table text           its sentence is mostly numbers: a table read as running text, where the cells of
                       neighbouring columns run together
  low confidence       the extraction's own score is under 0.4

"no" for every other value. The flags point at the values most worth checking; they are not a verdict:
a flagged value is often right, and an unflagged one can be wrong (the accuracy is measured by mme-eval)."""

from __future__ import annotations

import re
from typing import List

_LOW_CONFIDENCE = 0.4
_FROM_ELSEWHERE = {"previous_sentence", "paragraph_topic"}
# A number standing on its own: not the subscript of a formula ("Li6PS5Cl") nor part of a word.
_STANDALONE_NUMBER = re.compile(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?(?![A-Za-z\d])")
_WORD = re.compile(r"[A-Za-z]{4,}")
_DOPED = re.compile(r"(?i)\b(?:doped|co-?doped|substituted|stabili[sz]ed)\b|\bdoping\b")
# The parent compounds most often doped, as the extraction writes their formulas.
_PARENTS = {"Li7La3Zr2O12", "Li1.3Ti1.7Al0.3(PO4)3", "Li1.5Al0.5Ge1.5(PO4)3", "Li0.33La0.56TiO3", "Li0.33La0.55TiO3",
            "Li0.5La0.5TiO3", "Li6PS5Cl", "Li6PS5Br", "Li3PS4", "Li7P3S11", "Li10GeP2S12", "Na3Zr2Si2PO12",
            "Na3PS4", "Na3SbS4", "Li3InCl6", "Li3YCl6", "Li3YBr6", "Li2ZrCl6", "LiZr2(PO4)3", "Li3ClO", "Li3OCl"}


def _unusual(formula: str) -> bool:
    from .chemistry import ChemistryEngine, _BALANCED, _net_charge
    if not formula or formula == "NONE" or re.search(r"[xyzδ]", formula):
        return False  # no material, or the general formula of a series
    found = ChemistryEngine.find_materials(formula)
    if not found or not isinstance(found[0].get("elements"), dict):
        return False
    elements = found[0]["elements"]
    if any(not isinstance(amount, float) for amount in elements.values()) or len(elements) < 2:
        return False
    # Under the usual oxidation states only: it catches formulas cut short ("PSe", "Li6PS5", "LiSO3"), and
    # flags too some real ones with a less usual state (Na3V2(PO4)3, NMC): a pointer, not a verdict.
    return _net_charge(elements, True) > _BALANCED


def reasons(plausibility: str, confidence, material_link: str, sentence: str, formula: str) -> List[str]:
    """Why a value should be checked (empty: no reason)."""
    found = []
    if str(plausibility).startswith("check"):
        found.append("out of range")
    if _unusual(str(formula)):
        found.append("unusual formula")
    if str(formula) in _PARENTS and _DOPED.search(str(sentence or "")):
        found.append("doped sample")
    if str(material_link) in _FROM_ELSEWHERE:
        found.append("material from another sentence")
    text = str(sentence or "")
    numbers = len(_STANDALONE_NUMBER.findall(text))
    if numbers >= 8 and len(_WORD.findall(text)) < numbers:
        found.append("table text")
    try:
        if float(confidence) < _LOW_CONFIDENCE:
            found.append("low confidence")
    except (TypeError, ValueError):
        pass
    return found


def needs_check(plausibility: str, confidence, material_link: str, sentence: str, formula: str) -> str:
    """The `needs_check` cell: "no", or "yes: <reasons>"."""
    why = reasons(plausibility, confidence, material_link, sentence, formula)
    return "yes: " + "; ".join(why) if why else "no"
