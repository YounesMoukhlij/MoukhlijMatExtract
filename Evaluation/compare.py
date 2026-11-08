# Evaluation/compare.py
"""When are two values, or two materials, the same — and the matching of a paper's extracted values
to its reference values (the most pairs possible, each value used once)."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .about import LINEAR_TOLERANCE, LOG_TOLERANCE, PROPERTIES

# ---- numbers and units -----------------------------------------------------------------------------

# Factor from the unit written to the unit of the database (eV, S/cm, cm2/s), after _unit_key.
_UNITS = {
    "activation_energy": {"": 1.0, "ev": 1.0, "mev": 1e-3, "kj/mol": 1 / 96.485, "kcal/mol": 1 / 23.0605,
                          "j/mol": 1 / 96485.0},
    "conductivity": {"": 1.0, "s/cm": 1.0, "ms/cm": 1e-3, "us/cm": 1e-6, "ns/cm": 1e-9, "s/m": 1e-2,
                     "ms/m": 1e-5, "us/m": 1e-8},
    "diffusion_coefficient": {"": 1.0, "cm2/s": 1.0, "m2/s": 1e4, "mm2/s": 1e-2, "um2/s": 1e-8},
}


def _unit_key(unit: str) -> str:
    text = (unit or "").strip().lower()
    for old, new in (("μ", "u"), ("µ", "u"), ("−", "-"), ("–", "-"), ("²", "2"), ("⁻¹", "-1"), ("·", " "),
                     ("^", ""), ("⋅", " ")):
        text = text.replace(old, new)
    text = re.sub(r"\s*\*\s*", " ", text)
    # "S cm-1" -> "s/cm", "cm2 s-1" -> "cm2/s"; also glued, as some tools write them: "mScm-1", "kJmol-1"
    for base, after in (("cm", ""), ("mol", ""), ("m", "(?<!c)"), ("s", "")):
        text = re.sub(rf"\s*{after}{base}\s*-1\b", f"/{base}", text)
    text = text.replace(" ", "").replace("//", "/")
    return text


def unit_factor(prop: str, unit: str) -> Optional[float]:
    """The factor from `unit` to the database unit of `prop`; None when the unit is not known."""
    table = _UNITS["conductivity" if prop.endswith("conductivity") else prop]
    return table.get(_unit_key(unit))


_NUMBER = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))\s*(?:(?:[x×*·]|×)\s*10\s*\^?\s*\(?([+-]?\d+)\)?)?$")
_POWER = re.compile(r"^10\s*\^?\s*\(?([+-]?\d+)\)?$")


def parse_number(text) -> Optional[float]:
    """1.16e-3, 1.16 × 10^-3, 1.16x10-3, 10^-4, 0,31 → a float; None when it is not a number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return None if isinstance(text, float) and math.isnan(text) else float(text)
    s = str(text).strip().replace("−", "-").replace("–", "-").replace("⁻", "-").replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"[+-]?\d+,\d+", s):
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        pass
    found = _NUMBER.match(s)
    if found:
        return float(found.group(1)) * (10.0 ** int(found.group(2)) if found.group(2) else 1.0)
    found = _POWER.match(s)
    if found:
        return 10.0 ** int(found.group(1))
    return None


def to_database_unit(prop: str, value, unit: str = "") -> Tuple[Optional[float], str]:
    """(the value in the unit of the database, "") or (None, why not)."""
    number = parse_number(value)
    if number is None:
        return None, f"“{value}” is not a number"
    factor = unit_factor(prop, unit)
    if factor is None:
        return None, f"the unit “{unit}” is not known for {prop.replace('_', ' ')}"
    return number * factor, ""


def same_value(prop: str, a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    if PROPERTIES[prop][2]:  # compared on a log scale
        if a <= 0 or b <= 0:
            return a == b
        return abs(math.log10(a) - math.log10(b)) <= LOG_TOLERANCE + 1e-12
    relative, absolute = LINEAR_TOLERANCE
    return abs(a - b) <= max(relative * abs(b), absolute) + 1e-12


# ---- materials --------------------------------------------------------------------------------------

def _plain(formula: str) -> str:
    return re.sub(r"[\s\-_·•]", "", str(formula or "")).lower()


@lru_cache(maxsize=20000)
def _composition(formula: str):
    """The fractional composition of a formula ({"Li": 0.25, ...}), or None when it is not a formula."""
    text = re.sub(r"\s+", "", str(formula or ""))
    if not text or not re.search(r"[A-Z]", text):
        return None
    try:
        from pymatgen.core import Composition
        composition = Composition(text)
        if composition.num_atoms <= 0:
            return None
        return {str(el): amt / composition.num_atoms for el, amt in composition.items()}
    except Exception:  # not a formula: a name such as LLZO or "garnet"
        return None


def same_material(a: str, b: str) -> bool:
    """The same composition (Li6PS5Cl = Li12P2S10Cl2), or, for names, the same text."""
    if _plain(a) and _plain(a) == _plain(b):
        return True
    ca, cb = _composition(a), _composition(b)
    if ca is None or cb is None or set(ca) != set(cb):
        return False
    return all(abs(ca[el] - cb[el]) <= 0.005 + 0.01 * cb[el] for el in cb)


# ---- matching ---------------------------------------------------------------------------------------

def max_matching(left: Sequence, right: Sequence, fits: Callable[[object, object], bool],
                 prefer: Optional[Callable[[object, object], float]] = None) -> List[Tuple[int, int]]:
    """The largest set of (i, j) pairs with fits(left[i], right[j]), each item used once (augmenting
    paths; a paper has tens of values, so this is instant). Among pairings as large, the partners with
    the highest prefer(left, right) are tried first — so two values of one material (bulk and total)
    pair with the reference values they agree with, not crosswise."""
    options = [[j for j, r in enumerate(right) if fits(item, r)] for item in left]
    if prefer is not None:
        options = [sorted(js, key=lambda j, i=i: -prefer(left[i], right[j])) for i, js in enumerate(options)]
    owner: Dict[int, int] = {}

    def place(i: int, seen: set) -> bool:
        for j in options[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or place(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in sorted(range(len(left)), key=lambda k: len(options[k])):  # the most constrained first
        place(i, set())
    return sorted((i, j) for j, i in owner.items())
