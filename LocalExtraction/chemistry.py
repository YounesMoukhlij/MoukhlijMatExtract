# LocalExtraction/chemistry.py
"""Chemistry-aware material detection (schema section 2).

Generic across any battery chemistry (Li/Na/K/Mg/Ca/Zn/Al/H, solid-state or liquid
electrolytes, cathodes/anodes/coatings/separators/...). Combines:
  1. A formula tokenizer built on the real element symbols. It understands decimal, fractional
     ("Li2Sc2/3Cl4") and variable ("Li3−xY1−xZrxCl6") subscripts, parenthesized groups, and
     mixtures with or without coefficients ("Li2S-P2S5", "0.8Li2O–ZrCl4", "Li3InCl6·2H2O").
  2. Chemical checks on every candidate: real elements only, not an acronym that happens to spell
     element symbols, not a polyatomic unit of a structure ("PO4", "LiS4"), no citation number run
     into the formula ("Li6PS5Cl8").
  3. A curated alias table for common battery-material shorthand that isn't a literal
     chemical formula (LFP, LCO, NMC811, LLZO, LATP, graphite, ...).

Also derives each material's ionic radii from its composition (`ChemistryEngine.ionic_radii`),
knows the structure family of the well-known electrolyte and electrode compositions
(`ChemistryEngine.structure_family`) and resolves the names a paper defines for its own formulas
(`Abbreviations`).
"""

import itertools
import math
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from pymatgen.core import Element

from .normalizer import normalize_scientific_text

Amount = Union[float, str]  # a number, or — for a composition series — an expression in x ("1-x")

# The elements a battery material is made of. No noble gas (no formula has one, and "He" and "Ne"
# are words), no isotope letter (pymatgen reads "D" and "T" as hydrogen, which made formulas out
# of "LiTFSI" and "PVDF"), nothing radioactive ("UiO-66" is a framework, not a uranium compound).
_NOT_IN_MATERIALS = {"D", "T", "He", "Ne", "Ar", "Kr", "Xe", "Rn", "Tc", "Pm", "Po", "At", "Fr", "Ra", "Ac", "Pa",
                     "Th", "U"}
_SYMBOLS = sorted({el.symbol for el in Element if el.Z <= 92} - _NOT_IN_MATERIALS, key=len, reverse=True)
_ELEMENT = '(?:' + '|'.join(_SYMBOLS) + ')'
_NUMBER = r'\d+(?:\.\d+)?'
_SIGN = r'[−–+-]'  # U+2212, en dash, plus, hyphen
# A subscript is a number, a fraction ("2/3"), or — in the general formula of a series — an
# expression in a composition variable: "x", "2x", "1−x", "3+x", "2−2x", "1−x−y". After a digit a
# dash can only open such an expression when the variable follows it ("Li7-xLa3Zr2O12"); before an
# element it joins two formulas ("Li2S-P2S5").
_VARIABLES = "xyzδ"
_VAR_TERM = rf'(?:{_NUMBER})?[{_VARIABLES}](?![a-z])'
_FRACTION = r'\d+/[2-9](?!\d)'
_VARIABLE = (rf'(?:(?:{_FRACTION}|{_NUMBER})\s?{_SIGN}\s?{_VAR_TERM}(?:\s?{_SIGN}\s?{_VAR_TERM})?'
             rf'|{_VAR_TERM}(?:\s?{_SIGN}\s?{_VAR_TERM})?)')
_SUBSCRIPT = rf'(?:{_VARIABLE}|{_FRACTION}|{_NUMBER})?'
_ATOM = rf'{_ELEMENT}{_SUBSCRIPT}'
# "(II)" after a formula numbers a polymorph ("Li2HfSiO5(II)"): it is not two iodine atoms.
_UNIT = rf'(?:\((?![IVX]+\))(?:{_ATOM})+\){_SUBSCRIPT}|{_ATOM})'
_RUN = rf'(?:{_UNIT}){{2,}}'
# The share of one part of a mixture: "0.8", or in the general formula of a series "x" and "(100-x)".
_COEFFICIENT = rf'(?:{_NUMBER}|\(\s?{_NUMBER}\s?{_SIGN}\s?[{_VARIABLES}]\s?\)|[{_VARIABLES}](?![a-z]))'
_PART = rf'(?:{_COEFFICIENT})?{_RUN}'
_JOINER = r'[-–−·]'

# A material formula token: at least two element/group units, alone or as a mixture of up to four
# parts, each with an optional coefficient. It must end where the formula ends: a token that would
# stop in the middle of a word ("PV" of "PVDF") is no formula at all.
# ... nor one that the rest of a general formula follows ("Li6−yPS5" of "Li6−yPS5−yX1+y").
TOKEN_REGEX = re.compile(rf'(?<![A-Za-z0-9.]){_PART}(?:{_JOINER}{_PART}){{0,3}}'
                         rf'(?![A-Za-z0-9])(?!\s?[−–+]\s?[{_VARIABLES}])')
_PART_REGEX = re.compile(rf'({_JOINER})?({_COEFFICIENT})?({_RUN})')
_OPENS_WITH_SHARE = re.compile(rf'\(\s?{_NUMBER}\s?{_SIGN}\s?[{_VARIABLES}]\s?\)|[{_VARIABLES}](?=[A-Z(])')
_SHARE_BEFORE_PART = re.compile(rf'(?<=\d)[-–−](?=[{_VARIABLES}][A-Z(])')
# "(Li2S)70(P2S5)30": the same mixture written with its shares as subscripts.
_SHARES_AS_SUBSCRIPTS = re.compile(rf'(?:\((?:{_ATOM})+\){_NUMBER}){{2,4}}')
_SHARE_REGEX = re.compile(rf'\(((?:{_ATOM})+)\)({_NUMBER})')
_UNIT_REGEX = re.compile(rf'\(((?:{_ATOM})+)\)({_SUBSCRIPT})|({_ELEMENT})({_SUBSCRIPT})')
_ATOM_REGEX = re.compile(rf'({_ELEMENT})({_SUBSCRIPT})')
_TERM_REGEX = re.compile(rf'([+-]?)({_NUMBER})?([{_VARIABLES}])?')
# The values a sentence gives a composition variable: "x = 0.5", "x = 0.25 and 0.6", "x = 0.25 and
# x = 0.6" — not the 7.5 of "x = 0.25 and 7.5 mS/cm", and none at all for a range ("x = 0–1").
_SHARE = rf'{_NUMBER}(?!\d|\.\d|\s*(?:[×x*]\s?10|[mμµ]?S\b|[mk]?eV\b|kJ|K\b|°|%|[GMk]?Pa\b|[cmμn]m\b|wt\b|mol\b))'
_VALUES_OF = re.compile(
    rf'(?<![A-Za-z])([{_VARIABLES}])\s?(?:=|≈)\s?'
    rf'({_SHARE}(?:(?:\s?,\s?(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)(?:\1\s?(?:=|≈)\s?)?{_SHARE})*)'
    rf'(\s?[–−-]\s?\d|\s+to\s+\d)?')

# Common shorthand that is not itself a parseable chemical formula string. An abbreviation stands
# for the composition it is usually written for; a paper's own definition takes precedence.
ALIASES: Dict[str, str] = {
    "lfp": "LiFePO4", "lithium iron phosphate": "LiFePO4",
    "lco": "LiCoO2", "lithium cobalt oxide": "LiCoO2",
    "lmo": "LiMn2O4", "lithium manganese oxide": "LiMn2O4",
    "lnmo": "LiNi0.5Mn1.5O4",
    "nca": "LiNi0.8Co0.15Al0.05O2",
    "llzo": "Li7La3Zr2O12", "llz": "Li7La3Zr2O12", "llzto": "Li6.4La3Zr1.4Ta0.6O12",
    "llto": "Li0.33La0.56TiO3",
    "latp": "Li1.3Al0.3Ti1.7(PO4)3", "lagp": "Li1.5Al0.5Ge1.5(PO4)3",
    "lgps": "Li10GeP2S12",
    "lpscl": "Li6PS5Cl", "lpsbr": "Li6PS5Br", "lpsi": "Li6PS5I",
    "lipon": "Li2.9PO3.3N0.46",
    "lto": "Li4Ti5O12",
    "lisicon": "Li14ZnGe4O16",
    "nasicon": "Na3Zr2Si2PO12", "nzsp": "Na3Zr2Si2PO12",
    "nvp": "Na3V2(PO4)3",
    "na3ps4": "Na3PS4",
    "graphite": "C", "hard carbon": "C", "soft carbon": "C",
    "silicon": "Si", "lithium metal": "Li", "sodium metal": "Na",
}
_ALIAS_REGEX = re.compile(
    r'\b(' + '|'.join(sorted((re.escape(k) for k in ALIASES), key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)
_NMC_REGEX = re.compile(r'(?i)\bNMC\s?-?(\d)(\d)(\d)\b')
_SAMPLE_PREFIX = re.compile(r'(?:[A-Za-z0-9][-–]|@)$')
# A formula written for a whole family: a capital that is no element stands for several
# ("M = Y, Er", "X = Cl, Br"). It needs a subscript to be a formula at all ("LLZO" is a name).
_PLACEHOLDER_FORMULA = re.compile(r'(?<![A-Za-z0-9])(?=[A-Za-z0-9.]*\d)(?=[A-Za-z0-9.]*[AEGJLMQRXZ](?![a-z]))'
                                  r'(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}(?![A-Za-z0-9])')
# ... and so is a name with a composition hung on it ("LPS-0.05SnO2", "LLZO-Ta"), unlike "LLZO-based".
# ... and one thing on or in another ("LLZTO@PEO").
_SAMPLE_SUFFIX = re.compile(r'[-–](?=[0-9A-Z])|@(?=\w)')
# A formula that a name is hung on ("1LiF–LZZTO"): the name is the sample, the formula what was added to it.
_LABEL_AFTER_FORMULA = re.compile(r'[-–][A-Z]{2,}[A-Za-z0-9]*(?![a-z]*[-–]?(?:type|like|based))')
# Tags that say how a sample was made or which polymorph it is — the compound stays the same:
# "BM-LYC" (ball-milled), "SS-LYC" (solid-state), "c-LLZO" (cubic), "β-Li3PS4".
_SAME_COMPOUND_TAG = r'(?:BM|SS|HT|LT|HP|SPS|WM|DM|MQ|MM|am|gc|[cthmorg]|[αβγδ])'
_POLYMORPH_PREFIX = re.compile(rf'(?:^|[^A-Za-z0-9-]){_SAME_COMPOUND_TAG}[-–]$')

# Valid-looking element-symbol strings that are actually acronyms/units/methods, not materials.
ACRONYM_BLACKLIST = {
    "DFT", "XRD", "SEM", "TEM", "EDS", "EDX", "XPS", "FTIR", "EIS", "GITT", "CV", "PBE", "PBE0",
    "GGA", "LDA", "SCAN", "HSE", "NVT", "NPT", "NVE", "SOC", "PAW", "NEB", "VASP", "MSD", "RMSE",
    "MAE", "ROC", "AUC", "SHAP", "LIME", "CIF", "ICSD", "DOS", "PDOS", "COHP", "ESI", "ESW",
    "BET", "TGA", "DSC", "SAXS", "NMR", "SVM", "GNN", "PLD", "CVD", "SI", "IR", "UV", "AI", "ML",
    "NO", "IN", "AS", "IS", "AT", "OF", "OR", "ON", "BY", "TO", "PO", "SE", "BE", "PC", "CO",
}
# Letter-only, all-caps tokens ("FV", "KNN", "TDOS") are acronyms far more often than formulas;
# real all-caps binaries are whitelisted.
_ALLCAPS_FORMULAS = {"BN", "CO", "HF", "HI", "KI", "KF", "NO"}
# A letter-only token of this many different elements ("UIOSLi", "LiPON") is a name, not a formula.
_NAME_NOT_FORMULA = 4

_ALKALI = {"Li", "Na", "K", "Rb", "Cs"}
_ALKALINE_EARTH = {"Mg", "Ca", "Sr", "Ba"}
_HALOGENS = {"F", "Cl", "Br", "I"}
_CHALCOGENS = {"O", "S", "Se", "Te"}
# The charge an element takes as the anion of a compound.
_ANION_CHARGE = {"O": -2, "S": -2, "Se": -2, "Te": -2, "F": -1, "Cl": -1, "Br": -1, "I": -1, "N": -3, "H": -1}
# Compounds whose anions are bonded to one another, so that no single charge per element balances them.
_CATENATED = {"Li2O2", "Na2O2", "K2O2", "H2O2", "BaO2", "LiO2", "NaO2", "KO2", "LiN3", "NaN3", "KN3"}
# Ions and groups that the charge test below does not see (their centre is hydrogen or carbon).
_GROUPS = {"NH4", "H4N", "NH2", "H2N", "OH", "HO", "CH3", "H3C", "CH2", "H2C", "CN", "NC", "NH", "HN"}
# What follows the name of a building block of a structure rather than of a material ("PS4
# tetrahedra", "the Li6S unit", "PS43− anions"), and what precedes a reference electrode.
_BUILDING_BLOCK = re.compile(
    r'\s?(?:\d*[+−–-])?\s*(?:units?|tetrahedr\w+|octahedr\w+|polyhedr\w+|polyanions?|anions?|cations?|groups?|'
    r'clusters?|moiet\w+|ligands?|motifs?|dimers?)\b')
_REFERENCE_ELECTRODE = re.compile(r'(?i)\b(?:vs\.?|versus)\s*$')
# Polyanions a formula is conventionally written with ("Na3V2(PO4)3", not "Na3V2P3O12"):
# (central atom, anion) -> (spelling, anions per central atom).
_POLYANIONS = {
    ("P", "O"): ("PO4", 4), ("S", "O"): ("SO4", 4), ("Si", "O"): ("SiO4", 4), ("Ge", "O"): ("GeO4", 4),
    ("B", "O"): ("BO3", 3), ("C", "O"): ("CO3", 3), ("N", "O"): ("NO3", 3), ("Cl", "O"): ("ClO4", 4),
    ("Mo", "O"): ("MoO4", 4), ("W", "O"): ("WO4", 4), ("V", "O"): ("VO4", 4), ("As", "O"): ("AsO4", 4),
    ("B", "H"): ("BH4", 4), ("Al", "H"): ("AlH4", 4), ("B", "F"): ("BF4", 4), ("P", "F"): ("PF6", 6),
    ("P", "S"): ("PS4", 4), ("H", "O"): ("OH", 1),
}
# Fillers, precursors, gases and electrodes: what a paper names next to a conductivity without it being theirs.
INERT = {"SiO2", "Al2O3", "TiO2", "B2O3", "P2S5", "P2O5", "MgO", "ZnO", "H2O", "CO2", "C", "Li", "Na", "Si"}
_BALANCED = 0.05  # net charge per formula below which a composition counts as charge-balanced


def _evaluate(expression: str, values: Dict[str, float]) -> Optional[Amount]:
    """A subscript as a number: "" -> 1, "2/3" -> 0.667, "1−x" with x = 0.5 -> 0.5. An expression
    whose variable has no value is returned as text ("1-x"); None if it cannot be read."""
    text = re.sub(r'\s', '', expression).replace("−", "-").replace("–", "-")
    if not text:
        return 1.0
    text = re.sub(r'(\d+)/(\d)', lambda m: f"{int(m.group(1)) / int(m.group(2)):.4f}".rstrip("0"), text)
    if not any(v in text for v in _VARIABLES):
        return float(text)
    if any(v in text and v not in values for v in _VARIABLES):
        return text
    total, position = 0.0, 0
    while position < len(text):
        term = _TERM_REGEX.match(text, position)
        if not term or term.end() == position:
            return None
        amount = float(term.group(2)) if term.group(2) else 1.0
        if term.group(3):
            amount *= values[term.group(3)]
        total += -amount if term.group(1) == "-" else amount
        position = term.end()
    return round(total, 6)


def _times(amount: Amount, factor: Amount) -> Amount:
    if isinstance(amount, float) and isinstance(factor, float):
        return round(amount * factor, 6)
    return str(amount) if factor == 1.0 else str(factor) if amount == 1.0 else f"({amount})*({factor})"


def _amounts(body: str, values: Dict[str, float]) -> Optional[Dict[str, Amount]]:
    """Element -> amount of one formula ("Li1.3Al0.3Ti1.7(PO4)3"), in the order it is written."""
    amounts: Dict[str, Amount] = {}

    def add(symbol: str, amount: Optional[Amount]) -> bool:
        if amount is None:
            return False
        known = amounts.get(symbol)
        if known is None:
            amounts[symbol] = amount
        elif isinstance(known, float) and isinstance(amount, float):
            amounts[symbol] = round(known + amount, 6)
        else:
            amounts[symbol] = f"{known}+{amount}"
        return True

    for unit in _UNIT_REGEX.finditer(body):
        if unit.group(3):
            if not add(unit.group(3), _evaluate(unit.group(4), values)):
                return None
            continue
        factor = _evaluate(unit.group(2), values)
        if factor is None:
            return None
        for atom in _ATOM_REGEX.finditer(unit.group(1)):
            amount = _evaluate(atom.group(2), values)
            if amount is None or not add(atom.group(1), _times(amount, factor)):
                return None
    return amounts


def _net_charge(amounts: Dict[str, float], usual_states_only: bool = False) -> float:
    """|net charge| of a composition under the best assignment of one oxidation state per element —
    with `usual_states_only`, of each element's common states (a garbled formula balances with
    Ca+ and Si+, a real one does not need them)."""
    states = _oxidation_states(tuple(amounts.items()), usual_states_only)
    return abs(sum(amount * states.get(symbol, 0) for symbol, amount in amounts.items())) if states else 0.0


def _is_building_block(amounts: Dict[str, float]) -> bool:
    """Whether a two-element "formula" is an ion or a coordination polyhedron rather than a
    compound: one or two central atoms that even at their highest usual oxidation state cannot
    balance the anions around them — PO4, SiO4, PS4, BH4, PF6, ZrO6, LiS4, P2S7."""
    if len(amounts) != 2:
        return False
    (a, n_a), (b, n_b) = amounts.items()
    if Element(a).X > Element(b).X:
        a, n_a, b, n_b = b, n_b, a, n_a  # b is the more electronegative: the anion
    if b not in _ANION_CHARGE:
        return False
    positive = [s for s in Element(a).oxidation_states if s > 0]
    # ... or, the other way round, more cations than the anion can balance at their lowest
    # oxidation state: the "Li6S" unit of a structure, the "SbS" left of a garbled "Na3SbS4".
    if positive and min(positive) * n_a > -_ANION_CHARGE[b] * n_b:
        return True
    alone = n_a == 1 and n_b >= 3
    paired = n_a == 2 and n_b >= 6 and a not in _ALKALI | _ALKALINE_EARTH
    if not (alone or paired):
        return False
    highest = max((s for s in Element(a).common_oxidation_states if s > 0), default=0)
    return highest * n_a < -_ANION_CHARGE[b] * n_b


def _nominal(amount: Amount) -> float:
    """A number to compare amounts by: the amount itself, or — for the open subscript of a series
    ("6+x", "1-x") — its value a quarter of the way into the series."""
    if isinstance(amount, float):
        return amount
    try:
        value = _evaluate(amount, dict.fromkeys(_VARIABLES, 0.25))
    except (ValueError, ZeroDivisionError):
        return 1.0  # a share that is no expression at all ("open": a mixture whose shares are not given)
    return value if isinstance(value, float) else 1.0


def _written(amount: Amount) -> str:
    if isinstance(amount, str):  # the open subscript of a series: "1-x"
        return amount
    return "" if amount == 1 else f"{amount:.4g}"


def _canonical(amounts: Dict[str, Amount]) -> str:
    """One spelling per composition, whatever order the paper wrote it in: the elements from the
    least to the most electronegative, with the stoichiometry as written (Li4P2S6 stays Li4P2S6)
    and a closing polyanion spelled the way chemists do — "Na3V2(PO4)3", "LiOH", "LiBH4"."""
    ordered = sorted(amounts, key=lambda symbol: (Element(symbol).X, symbol))
    tail = ""
    if len(ordered) >= 3 and all(isinstance(amounts[symbol], float) for symbol in ordered[-2:]):
        centre, anion = ordered[-2:]
        spelling = _POLYANIONS.get((centre, anion))
        if spelling:
            name, per_centre = spelling
            count = amounts[centre]
            if count == int(count) and amounts[anion] == per_centre * count:
                tail = name if count == 1 else f"({name}){int(count)}"
                ordered = ordered[:-2]
    return "".join(f"{symbol}{_written(amounts[symbol])}" for symbol in ordered) + tail


# Oxidation-state search space cap: beyond this many combinations only each element's common
# states are tried (keeps a many-element formula from stalling a worker thread).
_MAX_OXIDATION_COMBOS = 50_000
_COORDINATIONS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIV")


@lru_cache(maxsize=8192)
def _oxidation_states(amounts: Tuple[Tuple[str, float], ...], usual_states_only: bool = False) -> Dict[str, int]:
    """One oxidation state per element, charge-balanced where the formula allows it.

    A small exhaustive search rather than pymatgen's `oxi_state_guesses`, which needs integer
    amounts (so it rejects every doped composition, e.g. Li6.4La3Zr1.4Ta0.6O12) and can take
    minutes on large cells. Each element gets a single state: its common ones are tried first,
    rarer ones (Ni3+, V3+) only if they are what balances the charge exactly. A more
    electronegative element is never left positive beside a less electronegative anion (rules
    out "Cl+ with S2-"). When nothing balances exactly (mixed valence such as LiMn2O4, a
    sub-stoichiometric cell, or a formula the paper itself wrote unbalanced) the closest
    common-state assignment is returned — the ion labels show what was assumed.
    """
    if len(amounts) < 2:
        return {}  # an element on its own (Li metal, graphite) has no ions
    elements = [Element(symbol) for symbol, _ in amounts]
    common_states = [tuple(s for s in el.common_oxidation_states if s) for el in elements]
    # Ordered pairs (i, j) with i the more electronegative element. An element with no Pauling
    # electronegativity (a noble gas in a mis-read formula) compares False as NaN, so it never
    # vetoes a combination. Read from the data table: `Element.X` warns on every such element.
    electronegativity = [el.data.get("X") or float("nan") for el in elements]
    ordered = [(i, j) for i, j in itertools.permutations(range(len(elements)), 2)
               if electronegativity[i] > electronegativity[j]]

    def search(choices: List[Tuple[int, ...]]) -> Optional[Tuple[float, Tuple[int, ...]]]:
        if not 0 < math.prod(len(states) for states in choices) <= _MAX_OXIDATION_COMBOS:
            return None
        best = None
        for combo in itertools.product(*choices):
            if any(combo[i] > 0 > combo[j] for i, j in ordered):
                continue
            charge = abs(sum(amount * state for (_, amount), state in zip(amounts, combo)))
            uncommon = sum(state not in common for state, common in zip(combo, common_states))
            key = (round(charge, 6), uncommon, sum(abs(state) for state in combo))
            if best is None or key < best[0]:
                best = (key, combo)
        return (best[0][0], best[1]) if best else None

    found = search(common_states)
    if not usual_states_only and (found is None or found[0] > 1e-6):
        every = search([tuple(s for s in el.oxidation_states if s) for el in elements])
        if every is not None and (found is None or every[0] <= 1e-6):
            found = every
    return dict(zip((el.symbol for el in elements), found[1])) if found else {}


def _shannon_radius(element: Element, state: int) -> Optional[float]:
    """Shannon effective ionic radius (Å) in six-fold coordination, the usual single-number
    convention; the nearest tabulated coordination when VI is not listed, high spin when both
    spin states are."""
    by_coordination = element.data.get("Shannon radii", {}).get(str(state))
    if not by_coordination:
        return None
    known = [cn for cn in by_coordination if cn in _COORDINATIONS]
    if not known:
        return None
    cn = min(known, key=lambda c: abs(_COORDINATIONS.index(c) - _COORDINATIONS.index("VI")))
    by_spin = by_coordination[cn]
    radius = (by_spin.get("") or by_spin.get("High Spin") or next(iter(by_spin.values())))["ionic_radius"]
    return radius if radius > 0 else None  # Shannon lists a negative radius for the bare proton


def common_radii(symbols: Iterable[str]) -> Dict[str, float]:
    """Shannon radii of each element in its most common oxidation state — for a formula whose
    oxidation states cannot be balanced (a radical, a mixture whose shares are open)."""
    radii: Dict[str, float] = {}
    for symbol in symbols:
        try:
            element = Element(symbol)
        except ValueError:
            continue
        for state in element.common_oxidation_states or ():
            radius = _shannon_radius(element, state)
            if radius is not None:
                charge = f"{abs(state) if abs(state) > 1 else ''}{'+' if state > 0 else '-'}"
                radii[f"{symbol}{charge}"] = radius
                break
    return radii


@lru_cache(maxsize=4096)
def _ionic_radii(amounts: Tuple[Tuple[str, float], ...]) -> Tuple[Tuple[str, float], ...]:
    radii = []
    for symbol, state in _oxidation_states(amounts).items():
        radius = _shannon_radius(Element(symbol), state)
        if radius is not None:
            charge = f"{abs(state) if abs(state) > 1 else ''}{'+' if state > 0 else '-'}"
            radii.append((f"{symbol}{charge}", radius))
    return tuple(radii)


# "Na3Zr2Si2PO12 (NZSP)", "Na3.5Zr1.0Ti0.5Lu0.5Si2PO12 (ME1-NZSP)": a paper's own name for a
# formula, defined once in brackets right after it and used from then on.
_LABEL = r'[A-Z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*'
_DEFINITION = re.compile(rf'\s*\(\s*({_LABEL})\s*\)')
_TAGGED_LABEL = re.compile(rf'{_SAME_COMPOUND_TAG}[-–]([A-Z][A-Za-z0-9]{{2,}})|([A-Z][A-Za-z0-9]{{2,}})[-–]{_SAME_COMPOUND_TAG}')


class Abbreviations:
    """The names one paper defines for its formulas, and where they are mentioned afterwards.

    "NZSP" is not a formula and not in the curated alias table, so without this a sentence like
    "ME1-NZSP exhibits an activation energy of 0.29 eV" names no material at all. A label defined
    as two different formulas in the same paper is ambiguous and is not resolved."""

    def __init__(self, definitions: Dict[str, Dict[str, Any]]):
        self.definitions = definitions
        # Longest label first, so "ME1-NZSP" wins over the "NZSP" inside it. A citation number may
        # be run into a label ("LASI-80Si32").
        self._pattern = re.compile(
            r'(?:' + '|'.join(re.escape(label) for label in sorted(definitions, key=len, reverse=True))
            + r')(?=\d{1,3}(?!\w)|(?!\w))') if definitions else None

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> "Abbreviations":
        defined: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for text in texts:
            for label, material in ChemistryEngine.find_definitions(text):
                defined.setdefault(label, {})[material["formula"]] = material
        # "NaLaCl4 (NLC-HT)" also tells what "NLC" is, when the paper does not define it otherwise.
        for label in list(defined):
            stem = _TAGGED_LABEL.fullmatch(label)
            if stem and len(defined[label]) == 1:
                defined.setdefault(stem.group(1) or stem.group(2), dict(defined[label]))
        return cls({label: next(iter(by_formula.values()))
                    for label, by_formula in defined.items() if len(by_formula) == 1})

    def mentions(self, text: str) -> List[Dict[str, Any]]:
        if self._pattern is None:
            return []
        found = []
        for m in self._pattern.finditer(text):
            before = text[:m.start()]
            # A label glued to something else ("XYZ-NZSP", "LPS-0.05SnO2") is a different sample —
            # unless what is glued on only says how it was made ("BM-LYC").
            if (re.search(r'[\w-]$', before) and not _POLYMORPH_PREFIX.search(before)) or _SAMPLE_SUFFIX.match(text, m.end()):
                continue
            found.append({**self.definitions[m.group()], "raw": m.group(), "is_known_alias": True,
                          "start": m.start(), "end": m.end()})
        return found


class ChemistryEngine:
    """Generic, chemistry-agnostic material finder used by extractor.py."""

    @staticmethod
    def ionic_radii(elements: Dict[str, Amount]) -> Dict[str, float]:
        """Shannon ionic radius (Å) of each ion in a composition, keyed by the ion it was looked
        up for: {"Li": 7, "La": 3, "Zr": 2, "O": 12} -> {"Li+": 0.76, "La3+": 1.032, "Zr4+": 0.72,
        "O2-": 1.4}. Elements with no tabulated radius at their oxidation state are left out."""
        amounts = {symbol: amount for symbol, amount in elements.items() if isinstance(amount, float) and amount > 0}
        try:
            return dict(_ionic_radii(tuple(amounts.items())))
        except (ValueError, KeyError):
            return {}  # an element pymatgen has no data for must not lose the material itself

    @staticmethod
    def structure_family(elements: Dict[str, Amount]) -> Optional[str]:
        """The structure family the well-known electrolyte and electrode compositions crystallise
        in, read off the composition alone: Li7La3Zr2O12 and its doped variants are garnets,
        Li6PS5X argyrodites, A(1+x)M2(PO4)3 NASICONs ... None for everything else — a family is
        only named where the composition leaves no doubt about it (not for Li3PS4, whose
        polymorphs differ, or for the halides Li3MX6)."""
        if not elements or any(isinstance(amount, str) for amount in elements.values()):
            return None
        present = set(elements)

        def count(*symbols: str) -> float:
            return sum(elements.get(s, 0.0) for s in symbols)

        def per(anions: float, formula_unit: float) -> float:
            return formula_unit / anions if anions else 0.0

        oxygen, lithium = count("O"), count("Li")
        alkali = count("Li", "Na", "K")
        if oxygen and count("S", "Se", *_HALOGENS) <= 0.1 * oxygen:  # an oxide, a little F or Cl on its anion site at most
            f = per(oxygen, 12)
            if "La" in present and lithium and 2.4 <= f * count("La", "Ca", "Sr", "Ba", "Y", "Nd", "Pr", "Sm", "Gd") <= 3.1 \
                    and 1.5 <= f * count("Zr", "Ta", "Nb", "Hf", "Sn", "Te", "W", "Sb", "Bi", "Mo", "Ce", "Ti") <= 2.2 \
                    and 3.0 <= f * lithium <= 7.6:
                return "garnet"
            if present & {"P", "Si"} and 2.9 <= f * count("P", "Si", "S", "As") <= 3.1 \
                    and 1.8 <= f * count("Ti", "Zr", "Ge", "Hf", "Sn", "Al", "Sc", "V", "Fe", "Cr", "In", "Y", "Lu",
                                         "Ga", "Nb", "Ta", "Mn", "Yb", "Er") <= 2.2 \
                    and 0.4 <= f * count("Li", "Na", "K", "Mg", "Ca", "Zn", "Ag") <= 4.3:
                return "NASICON"
            f = per(oxygen, 3)
            if {"Li", "La", "Ti"} <= present and 0.9 <= f * count("Ti", "Nb", "Ta", "Zr", "Al") <= 1.1 \
                    and 0.7 <= f * count("Li", "La", "Sr", "Na", "K", "Ba", "Nd") <= 1.05:
                return "perovskite"
            f = per(oxygen, 4)
            if "P" in present and present <= {"Li", "Fe", "Mn", "Co", "Ni", "Mg", "P", "O"} and 0.95 <= f * count("P") <= 1.05 \
                    and 0.9 <= f * count("Fe", "Mn", "Co", "Ni", "Mg") <= 1.1 and f * lithium <= 1.1:
                return "olivine"
            metals = count("Mn", "Ni", "Ti", "Co", "Al", "Cr", "Fe", "Mg")
            if present <= {"Li", "Mn", "Ni", "Ti", "Co", "Al", "Cr", "Fe", "Mg", "O"} and present & {"Mn", "Ti"} \
                    and 2.9 <= f * (metals + lithium) <= 3.1 and f * lithium <= 1.4 and 1.6 <= f * metals <= 2.1:
                return "spinel"
            f = per(oxygen, 2)
            metals = count("Co", "Ni", "Mn", "Al", "Fe", "Ti", "Mg", "Cr")
            # LiMO2, lithium-rich Li(1+x)M(1-x)O2 and sodium-deficient NaxMO2.
            if present <= {"Li", "Na", "Co", "Ni", "Mn", "Al", "Fe", "Ti", "Mg", "Cr", "O"} and 0.3 <= f * alkali <= 1.25 \
                    and (1.95 <= f * (alkali + metals) <= 2.05 if f * alkali > 1.02 else 0.95 <= f * metals <= 1.05) \
                    and (present & {"Co", "Ni"} or ("Na" in present and metals)):
                return "layered"
            f = per(oxygen, 16)
            if present == {"Li", "Zn", "Ge", "O"} and 12 <= f * lithium <= 15 and 3.5 <= f * count("Ge") <= 4.5:
                return "LISICON"
            if present == {"Li", "P", "O", "N"}:
                return "amorphous"  # LiPON
        chalcogenide = count("S", "Se", "Te")
        centres = count("P", "Si", "Ge", "Sn", "Sb", "As", "B", "Al")
        if lithium and chalcogenide and centres and present <= {"Li", "P", "Si", "Ge", "Sn", "Sb", "As", "B", "Al", "S", "Se",
                                                              "Te", "O", "Cl", "Br", "I", "F"}:
            f = 1 / centres
            if 5.8 <= f * (chalcogenide + count("O", "Cl", "Br", "I", "F")) <= 6.2 and 5.0 <= f * lithium <= 7.6:
                return "argyrodite"
            f = per(chalcogenide + count("O", "Cl", "Br", "I"), 12)
            tetrels = count("Ge", "Si", "Sn")
            if tetrels and "P" in present and 9.0 <= f * lithium <= 11.5 and 2.8 <= f * centres <= 3.3 \
                    and 0.30 <= tetrels / centres <= 0.70:
                return "LGPS-type"
        halide = count(*_HALOGENS)
        if oxygen and halide and present <= _ALKALI | _HALOGENS | {"O", "H", "Mg", "Ca", "Ba", "Al"} \
                and count("Mg", "Ca", "Ba", "Al") <= 0.2 * oxygen:
            f = 1 / oxygen
            if 0.9 <= f * halide <= 1.1 and 2.9 <= f * (alkali + count("H")) <= 3.1 and f * alkali >= 2.0:
                return "anti-perovskite"
        if len(present) == 2:
            (a, n_a), (b, n_b) = elements.items()
            if a not in _ALKALI:
                a, n_a, b, n_b = b, n_b, a, n_a
            if a in {"Li", "Na", "K", "Rb"}:
                if b in _HALOGENS | {"H"} and n_a == n_b:
                    return "rock-salt"
                if b in _CHALCOGENS and n_a == 2 * n_b:
                    return "anti-fluorite"
        return None

    @staticmethod
    def compound_class(elements: Dict[str, Amount], formula: str = "") -> str:
        """What kind of compound a composition is, named after its anions: "thiophosphate",
        "chloride", "oxide", "phosphate", "borohydride" ... It is what can always be said of a
        material — also where neither the paper nor the composition gives its crystal structure —
        and it says nothing about that structure. `formula` is read for the elements of a mixture
        whose shares are left open."""
        amounts = {symbol: (amount if isinstance(amount, float) else _nominal(amount)) for symbol, amount in elements.items()}
        if not amounts:
            amounts = {symbol: 1.0 for symbol, _ in _ATOM_REGEX.findall(formula)}
        amounts = {symbol: amount for symbol, amount in amounts.items() if amount > 0}

        def total(*symbols: str) -> float:
            return sum(amounts.get(symbol, 0.0) for symbol in symbols)

        oxygen, chalcogen, halogen, nitrogen = total("O"), total("S", "Se", "Te"), total(*_HALOGENS), total("N")
        if "B" in amounts and "H" in amounts and not oxygen:
            return "borohydride" if total("H") >= 3 * total("B") else "closo-borate"
        leading = max(oxygen, chalcogen, halogen, nitrogen)
        if leading == 0:
            return "hydride" if "H" in amounts else ("alloy" if len(amounts) > 1 else "element")
        if leading == chalcogen and chalcogen > oxygen:
            kind = max(("S", "Se", "Te"), key=lambda symbol: amounts.get(symbol, 0.0))
            if "P" in amounts:
                return {"S": "thiophosphate", "Se": "selenophosphate", "Te": "tellurophosphate"}[kind]
            return {"S": "sulfide", "Se": "selenide", "Te": "telluride"}[kind]
        if leading == halogen and halogen > oxygen:
            if oxygen:
                return "oxyhalide"
            kinds = [symbol for symbol in ("F", "Cl", "Br", "I") if symbol in amounts]
            return {"F": "fluoride", "Cl": "chloride", "Br": "bromide", "I": "iodide"}[kinds[0]] if len(kinds) == 1 \
                else "mixed halide"
        if leading == nitrogen and nitrogen > oxygen:
            return "nitride"
        # An oxide, named after the centre of its polyanion when it has one.
        for centre, name in (("P", "phosphate"), ("Si", "silicate"), ("B", "borate"), ("S", "sulfate"), ("C", "carbonate")):
            if centre in amounts:
                return "oxynitride" if centre == "P" and nitrogen else name
        return "oxyhalide" if halogen else "oxynitride" if nitrogen else "oxide"

    @staticmethod
    def names_a_variant(text: str, abbreviations: Optional["Abbreviations"] = None) -> bool:
        """Whether a text names a material this module cannot resolve to one composition: a family
        written with a placeholder ("Li3MX6", "Li6PS5X", "NaMO2") or a sample label built on a known
        name ("bmLLZO30", "LPS-0.05SnO2")."""
        if _PLACEHOLDER_FORMULA.search(text):
            return True
        names = {key.upper() for key in ALIASES if key.isalpha() and len(key) >= 3} | set(abbreviations.definitions if abbreviations else ())
        if not names:
            return False
        whole = re.compile(r'(?<![A-Z])(?:' + '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r')(?![A-Za-z])')
        for m in whole.finditer(text):
            before = text[:m.start()]
            glued = re.search(r'[a-z0-9]$', before) or (_SAMPLE_PREFIX.search(before) and not _POLYMORPH_PREFIX.search(before))
            if glued or re.match(r'\d|[-–][0-9A-Z]', text[m.end():]):
                return True
        return False

    @staticmethod
    def find_definitions(text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """(label, material) for every "<formula> (<LABEL>)" in the text."""
        text = normalize_scientific_text(text)
        found: List[Tuple[str, Dict[str, Any]]] = []
        for material in ChemistryEngine.find_materials(text):
            defined = _DEFINITION.match(text, material["end"])
            if not defined:
                continue
            label = defined.group(1)
            # A label is an acronym: several capitals, not a known method, and not itself a formula ("PO4").
            if (len(label) < 3 or sum(c.isupper() for c in label) < 2 or label.upper() in ACRONYM_BLACKLIST
                    or TOKEN_REGEX.fullmatch(label)):
                continue
            found.append((label, material))
        return found

    @staticmethod
    def stated_values(text: str) -> List[Tuple[str, float]]:
        """(variable, value) for every value the text gives a composition variable, in text order:
        "for x = 0.25 and 0.6" -> [("x", 0.25), ("x", 0.6)]."""
        found: List[Tuple[str, float]] = []
        for m in _VALUES_OF.finditer(normalize_scientific_text(text)):
            if not m.group(3):
                found += [(m.group(1), float(n.group())) for n in re.finditer(_SHARE, m.group(2) + " ")]
        return found

    @staticmethod
    def member(mention: Dict[str, Any], values: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """The compound a mention of a series ("Li6+xP1-xGexS5I") stands for at these values of its
        variables; None when they do not fix its composition."""
        if "representative" not in mention:
            return None
        resolved = ChemistryEngine._resolve_token(mention["raw"], values)
        if not resolved or "representative" in resolved or not resolved["elements"]:
            return None
        del resolved["matched"]
        return {**resolved, "series": mention["formula"], "start": mention["start"], "end": mention["end"]}

    @staticmethod
    def find_materials(text: str, abbreviations: Optional[Abbreviations] = None) -> List[Dict[str, Any]]:
        """Every material mentioned in the text, in text order. With the paper's `abbreviations`,
        its own names for formulas ("NZSP") are mentions too, and take precedence over the curated
        aliases."""
        text = normalize_scientific_text(text)
        results: List[Dict[str, Any]] = []
        claimed_spans: List[tuple] = []
        # "x = 0.5" fixes the composition of a series for the whole sentence — unless it gives x several values.
        values: Dict[str, float] = {}
        stated = ChemistryEngine.stated_values(text)
        for variable in _VARIABLES:
            given = {value for name, value in stated if name == variable}
            if len(given) == 1:
                values[variable] = given.pop()

        # 1. Formula tokens (mixtures and hydrates are part of TOKEN_REGEX itself).
        for m in TOKEN_REGEX.finditer(text):
            if m.group()[0] in _VARIABLES and text[:m.start()].rstrip()[-1:] in ("−", "–", "+", "-"):
                continue  # the tail of a general formula that could not be read as a whole
            if m.group()[0].isdigit() and _SAMPLE_PREFIX.search(text[:m.start()]):
                continue  # the rest of a sample label: "LPS-0.05SnO2"
            if _LABEL_AFTER_FORMULA.match(text, m.end()):
                continue  # the head of one: "1LiF–LZZTO"
            material = ChemistryEngine._resolve_token(m.group(), values)
            if not material:
                continue
            if values and "representative" not in material:
                written = ChemistryEngine._resolve_token(m.group()) or {}
                if "representative" in written:
                    material["series"] = written["formula"]  # the series this compound is a member of
            claimed_spans.append((m.start(), m.end()))
            end = m.start() + len(material.pop("matched"))
            if _BUILDING_BLOCK.match(text, end) or _REFERENCE_ELECTRODE.search(text[:m.start()]):
                continue
            material["start"], material["end"] = m.start(), end
            results.append(material)

        # 2. Curated aliases (LFP, NMC811, graphite, ...). Glued to a prefix it is the label of a
        # sample ("Ta-LLZO", "ME1-NZSP"): another composition, unless the prefix only names the
        # polymorph ("c-LLZO", "β-LLZO").
        for m in _ALIAS_REGEX.finditer(text):
            if any(s <= m.start() < e for s, e in claimed_spans):
                continue
            if _SAMPLE_PREFIX.search(text[:m.start()]) and not _POLYMORPH_PREFIX.search(text[:m.start()]):
                continue
            if _SAMPLE_SUFFIX.match(text, m.end()):
                continue
            canonical = ALIASES[m.group(1).lower()]
            amounts = _amounts(canonical, {}) or {}
            results.append({
                "raw": m.group(1),
                "formula": _canonical(amounts) if len(amounts) > 1 else canonical,
                "elements": amounts,
                "is_known_alias": True,
                "start": m.start(),
                "end": m.end(),
            })

        # 3. Generic NMCxyz stoichiometry (NMC811 -> LiNi0.8Mn0.1Co0.1O2, etc.).
        for m in _NMC_REGEX.finditer(text):
            if any(s <= m.start() < e for s, e in claimed_spans):
                continue
            ni, mn, co = (int(d) / 10 for d in m.groups())
            amounts = {"Li": 1.0, "Ni": ni, "Mn": mn, "Co": co, "O": 2.0}
            amounts = {symbol: amount for symbol, amount in amounts.items() if amount}
            results.append({
                "raw": m.group(0),
                "formula": _canonical(amounts),
                "elements": amounts,
                "is_known_alias": True,
                "start": m.start(),
                "end": m.end(),
            })

        # 4. The paper's own names for formulas.
        named = abbreviations.mentions(text) if abbreviations else []
        if named:
            results = [r for r in results
                       if not any(n["start"] < r["end"] and r["start"] < n["end"] for n in named)] + named

        return sorted(results, key=lambda r: r["start"])

    @staticmethod
    def _resolve_token(raw: str, values: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
        """The material a formula token names, or None if it names none. `values` are the values
        its sentence gives the composition variables ("x = 0.5"). "matched" is the part of the
        token that is the formula (a citation number run into it is cut off)."""
        if not TOKEN_REGEX.fullmatch(raw) or raw.upper() in ACRONYM_BLACKLIST:
            return None
        values = values or {}
        if _SHARES_AS_SUBSCRIPTS.fullmatch(raw) and abs(sum(float(n) for _, n in _SHARE_REGEX.findall(raw)) - 100) < 0.5:
            return ChemistryEngine._resolve_token("-".join(f"{share}{body}" for body, share in _SHARE_REGEX.findall(raw)),
                                                  values) and {**ChemistryEngine._resolve_token(
                                                      "-".join(f"{share}{body}" for body, share in _SHARE_REGEX.findall(raw)),
                                                      values), "raw": raw, "matched": raw}
        parts = []
        # After a digit, "-x" before an element is a variable subscript ("Li7-xLa3Zr2O12") — unless
        # the formula opens with a share, which makes it a mixture: "(1-x)Li3PS4-xLiI".
        split = _SHARE_BEFORE_PART.sub("·", raw) if _OPENS_WITH_SHARE.match(raw) else raw
        for m in _PART_REGEX.finditer(split):
            coefficient = _evaluate(m.group(2).strip("()"), values) if m.group(2) else 1.0
            if not isinstance(coefficient, float):
                # A mixture whose shares are left open ("xLi2S-(100-x)P2S5"): a series, kept as written.
                written = re.sub(r'\s', '', raw).replace("−", "-").replace("–", "-")
                return {"raw": raw, "matched": raw, "formula": written, "elements": {}, "is_known_alias": False}
            parts.append((m.group(1) or "", coefficient, m.group(3)))
        resolved: List[Tuple[str, float, str, Dict[str, Amount]]] = []
        matched = raw
        for joiner, coefficient, body in parts:
            amounts = _amounts(body, values)
            if not amounts:
                return None
            if any(isinstance(amount, str) for amount in amounts.values()):
                # The general formula of a series whose x the sentence does not fix. It names the
                # series, not one compound: kept as written, never cut down to a formula it is not.
                if len(parts) > 1 or not any(c.isdigit() for c in body):
                    return None
                inside = _amounts(body, dict.fromkeys(_VARIABLES, 0.25)) or {}
                return {"raw": raw, "matched": raw, "formula": _canonical(amounts), "elements": amounts, "is_known_alias": False,
                        # One composition inside the series: what its ions are does not depend on x.
                        "representative": {el: a for el, a in inside.items() if isinstance(a, float) and a > 0}}
            amounts = {symbol: amount for symbol, amount in amounts.items() if amount}
            if len(amounts) < 2 and len(parts) == 1 or any(amount < 0 for amount in amounts.values()):
                return None
            if len(parts) == 1:
                repaired = ChemistryEngine._without_citation(body, amounts)
                if repaired:
                    body, amounts = repaired
                    matched = raw[:raw.index(parts[0][2]) + len(body)]
            if not ChemistryEngine._is_compound(body, amounts):
                return None
            resolved.append((joiner, coefficient, body, amounts))

        if len(resolved) == 1:
            _, _, body, amounts = resolved[0]
            return {"raw": matched, "matched": matched, "formula": _canonical(amounts), "elements": amounts,
                    "is_known_alias": False}
        # "70Li2S-30P2S5" gives the parts in percent, "0.8Li2O-ZrCl4" in moles.
        percent = abs(sum(coefficient for _, coefficient, _, _ in resolved) - 100) < 0.5
        elements: Dict[str, float] = {}
        for _, coefficient, _, amounts in resolved:
            for symbol, amount in amounts.items():
                share = coefficient / 100 if percent else coefficient
                elements[symbol] = round(elements.get(symbol, 0.0) + share * amount, 6)
        formula = "".join(("" if not joiner else "·" if _canonical(amounts) == "H2O" else "-")
                          + _written(coefficient) + _canonical(amounts) for joiner, coefficient, _, amounts in resolved)
        return {"raw": raw, "matched": raw, "formula": formula, "elements": elements, "is_known_alias": False}

    @staticmethod
    def _is_compound(body: str, amounts: Dict[str, float]) -> bool:
        """Whether a formula with real elements is a compound and not an acronym or an ion."""
        if body.upper() in ACRONYM_BLACKLIST:
            return False
        if body.isalpha():
            if body.isupper() and body not in _ALLCAPS_FORMULAS:
                return False
            if re.fullmatch(r'[A-Z]{2,}s', body) or len(amounts) >= _NAME_NOT_FORMULA:
                return False  # "SICs" (superionic conductors), "UIOSLi"
            if len(amounts) >= 3 and _net_charge(amounts, usual_states_only=True) > _BALANCED:
                return False  # what is left of a formula whose subscripts a table lost: "CaSiS", "NaLaZr"
        if len(amounts) < 2:
            return True  # one part of a mixture: "LiCl" needs two, the "C" of a composite does not
        canonical = _canonical(amounts)
        if canonical in _CATENATED:
            return True
        if set(amounts) in ({"B", "H"}, {"B", "H", "C"}):
            return False  # a closo-borate or carborane anion, its charge often run into it: "B12H122−"
        return canonical not in _GROUPS and body not in _GROUPS and not _is_building_block(amounts)

    @staticmethod
    def _without_citation(body: str, amounts: Dict[str, float]) -> Optional[Tuple[str, Dict[str, float]]]:
        """PDF text has no superscripts, so a citation number runs into the formula before it:
        "Li6PS5Cl8", "LiCoO223", "Li3PS4.11". When a formula of three or more elements is not
        charge-balanced but is once trailing digits are cut off, they were a citation. (Two-element
        formulas are left alone: Li2S8 and FeS2 are real and balance under no simple rule.)"""
        tail = re.search(r'(\d+)(?:\.(\d+))?$', body)
        if not tail or len(amounts) < 3 or body[:tail.start()].endswith(")") or _net_charge(amounts) <= _BALANCED:
            return None
        whole, decimals = tail.group(1), tail.group(2)
        kept = [whole] if decimals else [whole[:-n] for n in range(1, min(3, len(whole)) + 1)]
        for digits in kept:
            shorter = body[:tail.start()] + digits
            candidate = _amounts(shorter, {})
            if candidate and all(isinstance(a, float) for a in candidate.values()) and _net_charge(candidate) <= _BALANCED:
                return shorter, candidate
        return None
