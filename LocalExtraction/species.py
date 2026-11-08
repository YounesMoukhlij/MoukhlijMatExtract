# LocalExtraction/species.py
"""Which species moves — and is the value plausible.

An activation energy, a conductivity or a diffusion coefficient belongs to one moving species: Li+ in a
lithium conductor — but a paper on LLZO also gives the activation energy of Co cross-diffusion from the
cathode, and a paper on Li6PS5Cl the barrier of electron transfer at an interface. Those are not the ion
transport of the electrolyte, and a ranking that takes them in is wrong. `mobile_species` reads the
species off the value's sentence ("Co diffusion", "electron transfer", "Na+ migration"), else answers
from the material's composition and the paper's main ion — saying "assumed" and why.

`plausibility` flags the values outside the range known for ion conductors (0.05–1.5 eV, 1e-12–0.1 S/cm,
…) or carried by another species: "check: …", else "in range"."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Optional, Tuple

STATED = "stated"

# The conducting ions of solid electrolytes, the most common first: (symbol, name, ion as written).
CARRIERS: List[Tuple[str, str, str]] = [
    ("Li", "lithium", "Li+"), ("Na", "sodium", "Na+"), ("K", "potassium", "K+"), ("Ag", "silver", "Ag+"),
    ("Cu", "copper", "Cu+"), ("Mg", "magnesium", "Mg2+"), ("Zn", "zinc", "Zn2+"), ("Ca", "calcium", "Ca2+"),
    ("Al", "alumin(?:i)?um", "Al3+"),
]
ANIONS = [("H+", r"\bprotons?\b|\bproton(?:ic)?\b|\bH\s?\+(?![\w+])|\bhydrogen(?:[- ]ion)?\s+(?:diffus|migrat|conduct|transport)"),
          ("O2-", r"\boxide[- ]ions?\b|\bO\s?2\s?[−-](?![\w])|\boxygen(?:[- ]ion)?\s+(?:diffus|migrat|conduct|transport|vacanc)"),
          ("F-", r"\bfluoride[- ]ions?\b|\bF\s?[−-](?=[\s),.;])")]
ELECTRON = "electron"
ION_SPECIES = {ion for _, _, ion in CARRIERS} | {ion for ion, _ in ANIONS}

_MOVES = r"(?:diffus\w*|interdiffus\w*|cross[- ]diffus\w*|migrat\w*|conduct\w*|transport\w*|hopping|hops?|mobility|motion)"
# Other elements a sentence may say move — from a cathode, a dopant, a sintering aid — named or symbol.
_FOREIGN = {"Co": "cobalt", "Ni": "nickel", "Mn": "manganese", "Fe": "iron", "Ti": "titanium", "Zr": "zirconium",
            "La": "lanthanum", "Ta": "tantalum", "Ga": "gallium", "Cr": "chromium", "Nb": "niobium", "Ge": "germanium",
            "Sn": "tin", "Y": "yttrium", "In": "indium", "Si": "silicon", "P": "phosphorus", "S": "sulfur",
            "Se": "selenium", "Cl": "chlorine", "Br": "bromine", "I": "iodine", "B": "boron", "Sc": "scandium"}

# A symbol right after a number is a unit ("300 K conductivity"), not an ion.
_NOT_AFTER_NUMBER = r"(?<!\d)(?<!\d\s)"
_PATTERNS: List[Tuple[str, "re.Pattern"]] = []
for _symbol, _name, _ion in CARRIERS:
    charge = _ion[len(_symbol):-1]  # "" for Li+, "2" for Mg2+
    _PATTERNS.append((_ion, re.compile(
        rf"{_NOT_AFTER_NUMBER}\b{_symbol}\s?{charge}\+(?![\w+])"           # Li+, Mg2+
        rf"|{_NOT_AFTER_NUMBER}\b{_symbol}\s?{charge}\+?[- ]?ions?\b"       # Li-ion, Li+ ions
        rf"|\b(?i:{_name})[- ]ions?\b"                                       # lithium ion
        rf"|{_NOT_AFTER_NUMBER}\b(?:{_symbol}|(?i:{_name}))(?:[- ]ion)?\s+{_MOVES}")))  # Li diffusion
for _ion, _pattern in ANIONS:
    _PATTERNS.append((_ion, re.compile(_pattern, re.IGNORECASE)))
# Symbols as written (case matters: "CO" is no cobalt), names in any case. "In" and "I" are left out as
# symbols: "In conductivity measurements, …" is no indium.
_FOREIGN_SYMBOLS = sorted((s for s in _FOREIGN if s not in ("In", "I")), key=len, reverse=True)
_FOREIGN_MOVES = re.compile(rf"{_NOT_AFTER_NUMBER}\b(?:({'|'.join(_FOREIGN_SYMBOLS)})|(?i:({'|'.join(_FOREIGN.values())})))"
                            rf"(?:[- ](?:ion|atom|cation)s?)?\s+{_MOVES}")
_BY_NAME = {name: symbol for symbol, name in _FOREIGN.items()}
_ELECTRON = re.compile(r"\belectrons?\b(?![- ](?:microscop|diffraction|beam|energy[- ]loss|backscatter|probe|"
                       r"paramagnetic|spin|density|localization|configuration|structure|withdraw|donat|count))"
                       r"|\belectronic\s+(?:conduct|transport|leak)|\bpolarons?\b|\bholes?\s+(?:conduct|transport|"
                       r"carrier|mobility|polaron)", re.IGNORECASE)


def stated_species(sentence: str) -> List[Tuple[str, str]]:
    """Every species the sentence says moves, as (species, the words), in this order: an element said to
    move that is no conducting ion ("Co diffusion"), the conducting ions, the electron."""
    text = sentence or ""
    found: List[Tuple[str, str]] = []
    for match in _FOREIGN_MOVES.finditer(text):
        symbol = match.group(1) or _BY_NAME[match.group(2).lower()]
        found.append((symbol, match.group(0)))
    for ion, pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            found.append((ion, match.group(0)))
    match = _ELECTRON.search(text)
    if match:
        found.append((ELECTRON, match.group(0)))
    return found


def carriers_of(formula: str) -> List[str]:
    """The conducting ions of a formula, the most common first: "Li6PS5Cl" -> ["Li+"]."""
    symbols = set(re.findall(r"[A-Z][a-z]?", formula or ""))
    return [ion for symbol, _, ion in CARRIERS if symbol in symbols]


def paper_ion(sentences: Iterable[str]) -> Tuple[Optional[str], int]:
    """The conducting ion a paper's values name most, and how many name it."""
    counts = Counter(ion for s in sentences for ion, _ in stated_species(s) if ion in ION_SPECIES)
    if not counts:
        return None, 0
    ion, n = counts.most_common(1)[0]
    return ion, n


def _quote(words: str) -> str:
    words = " ".join(words.split())
    return words if len(words) <= 60 else words[:57] + "…"


def mobile_species(prop: str, sentence: str, formula: str, main_ion: Optional[str] = None,
                   main_count: int = 0) -> Tuple[str, str]:
    """(the species, its basis) for a value of `prop` read from `sentence`, for the material `formula`.
    `main_ion`: the ion the paper's values name most (paper_ion)."""
    if prop == "Electronic_Conductivity":
        return ELECTRON, "the property (an electronic conductivity is carried by electrons and holes)"
    stated = stated_species(sentence)
    ions = carriers_of(formula)
    if stated:
        foreign = [s for s in stated if s[0] not in ION_SPECIES and s[0] != ELECTRON]
        if foreign:
            # "Co diffusion" in a sentence about Li+: the value is Co's only if no conducting ion is said to move too.
            moving_ions = [s for s in stated if s[0] in ION_SPECIES]
            if not moving_ions:
                species, words = foreign[0]
                return species, f'{STATED} ("{_quote(words)}")'
        named = [s for s in stated if s[0] in ION_SPECIES]
        if named:
            own = [s for s in named if s[0] in ions] or named
            species, words = own[0]
            return species, f'{STATED} ("{_quote(words)}")'
        species, words = stated[0]
        return species, f'{STATED} ("{_quote(words)}")'
    if len(ions) == 1:
        return ions[0], f"assumed (the only conducting-ion element of {formula})"
    if ions:
        if main_ion in ions:
            return main_ion, f"assumed (of the conducting ions of {formula}, the one this paper is about)"
        return ions[0], f"assumed (the first conducting ion of {formula}: {', '.join(ions)})"
    if main_ion:
        return main_ion, (f"assumed (the ion this paper is about: {main_count} of its values name it; "
                          f"{formula or 'the material'} names none)")
    return "Li+", "assumed (no conducting ion is named or in the formula; Li+ is the usual one of solid electrolytes)"


# The range known for each quantity, in the unit of the database. Outside it, a value is more often a
# misreading (another property, a lost exponent, another species) than a record.
RANGES = {
    "Activation_Energy": (0.05, 1.5, "eV"),
    "Ionic_Conductivity": (1e-12, 0.1, "S/cm"),
    "Electronic_Conductivity": (1e-14, 1e4, "S/cm"),
    "Diffusion_Coefficient": (1e-16, 1e-3, "cm²/s"),
}


def _number(value) -> Optional[float]:
    try:
        number = float(str(value).split(" ", 1)[0])
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _short(x: float) -> str:
    return f"{x:g}"


def plausibility(prop: str, value, species: str) -> str:
    """"in range", or "check: <why>" for a value outside the known range of its quantity or carried by a
    species that is no conducting ion."""
    reasons = []
    number = _number(value)
    low, high, unit = RANGES.get(prop, (None, None, ""))
    if number is not None and low is not None and not (low <= number <= high):
        reasons.append(f"{_short(number)} {unit} is outside the {_short(low)}–{_short(high)} {unit} known for ion "
                       f"conductors")
    if prop != "Electronic_Conductivity" and species not in ION_SPECIES:
        what = "electrons" if species == ELECTRON else species
        reasons.append(f"it is the transport of {what}, not of a conducting ion")
    return "check: " + "; ".join(reasons) if reasons else "in range"
