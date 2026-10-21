# LocalExtraction/quantities.py
"""Which numbers of a sentence are transport quantities, and which of them belong together.

The activation energy, the ionic and electronic conductivity and the diffusion coefficient are read
value-first: every number carrying one of their units is a candidate, and the wording around it
decides what it is. A keyword-then-number pattern finds "an activation energy of 0.30 eV" but not
what follows it in most papers — "... and 0.45 eV for the tetragonal phase", "LLZO (0.31 eV), LATP
(0.35 eV)", "a conductivity of 1.2 mS/cm for A and 0.4 mS/cm for B".

 - "S/cm" can only be a conductivity and "cm2/s" a diffusion coefficient, so those need no keyword
   at all; a conductivity is ionic unless the wording says electronic.
 - "eV" can be anything. An energy is an activation energy when the quantity named last before it
   is one (config.EA_TERM: activation energy, migration barrier, Ea, ...) and not another energy
   (a band gap, a formation energy, the error of a model), or when it is named right after it
   ("a 0.25 eV barrier").

Values that follow one another in a list ("0.6, 1.2 and 1.5 eV", "0.30 eV for A and 0.45 eV for
B") form a group: they share the quantity's name and whatever condition is stated for the list as
a whole, and a "respectively" pairs them off with the materials named in the same order.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import (COMPILED_EA_TERM, CONDUCTIVITY_TERM, DIFFUSION_TERM, ELECTRONIC_TERM, QUANTITY_VALUES)

Span = Tuple[int, int]

ACTIVATION_ENERGY, IONIC, ELECTRONIC, DIFFUSION = ("Activation_Energy", "Ionic_Conductivity",
                                                   "Electronic_Conductivity", "Diffusion_Coefficient")
_VALUES: Dict[str, re.Pattern] = {kind: re.compile(pattern) for kind, pattern in QUANTITY_VALUES.items()}

# How far (in characters) the name of a quantity may stand before its first value ("the activation
# energy for ionic transport, derived from the Nyquist plots measured between 25 and 60 °C, is found
# to be 0.22 eV"), and how far apart two values of one list may be.
_TERM_REACH = 160
_LIST_REACH = 100
# ... and how far a name counts as the wording of a conductivity or diffusion value, which need none.
_NAME_REACH = 90

# Energies that are not activation energies. One of these named between an activation-energy term
# and a value means the value is that other energy.
_OTHER_ENERGY = re.compile(
    r'(?i)\b(?:formation|binding|adsorption|absorption|reaction|surface|interfac\w+|cohesive|decomposition|'
    r'defect|vacancy|total|free|strain|elastic|site|exchange|segregation|solution|dissolution|insertion|'
    r'substitution|doping|dopant|ordering|configurational|thermal|cut-?off|excitation|ioni[sz]ation|'
    r'dissociation|bond|lattice|coulomb|electrostatic|interaction|photon|beam|fermi|zero[\s-]point)\s+energ(?:y|ies)'
    r'|\benerg(?:y|ies)\s+(?:above|differences?|gain|penalty|cost|change|window|resolution|range|scale|cut-?off)'
    r'|\bband[\s-]?gaps?\b|\benergy\s+gaps?\b|\bhull\b|\bhubbard\b'
    r'|(?-i:\bU\s?(?:=|value|parameter|correction)|\bE\s?_?\s?(?:g|hull|f|form|coh|F|gap)\b|\bk\s?_?\s?B\s?_?\s?T\b)'
    r'|\b(?:RMSE|MAE|MSE|RMSD|MAPE|errors?|accuracy|uncertaint\w+|deviations?|residuals?|convergence|converged|'
    r'tolerance)\b')
_ELECTRONIC = re.compile(rf'(?i){ELECTRONIC_TERM}')
_CONDUCTIVITY = re.compile(rf'(?i){CONDUCTIVITY_TERM}')
_DIFFUSION = re.compile(rf'(?i){DIFFUSION_TERM}')
_ELECTRONIC_WORD = re.compile(r'(?i)\belectron(?:ic)?\b(?![\s-]+(?:micro|diffract|beam|dens))')

_RESPECTIVELY = re.compile(r'(?i)\brespectively\b')
_COORDINATED = re.compile(r'(?i)\s*,?\s*(?:and|or)\s+(?:the\s+|its\s+)?(?:[\w-]+\s+){0,2}')
# A sentence ends here even when the sentence splitter upstream did not see it.
_SENTENCE_BREAK = re.compile(r'(?<=[A-Za-z0-9)\]%])\.\s+(?=[A-Z])')
# What stands between two values of one list: "0.30 eV for A and 0.45 eV for B", "0.04 eV in NLC
# vs. 0.26 eV in NLZC", "from 0.97 eV for the undoped material to 0.62 eV".
_LIST_LINK = re.compile(r'(?i)[,;(]|\b(?:and|or|vs|versus|to|while|whereas|but|than)\b|[–—-]\s*$')
# A value named before its quantity: "a 0.25 eV barrier", "its 0.3 eV Li+ migration barrier".
_ADJECTIVE = (r'(?:Li\+?|Na\+?|K\+?|Mg2?\+?|lithium|sodium|ion|ionic|low|high|small|large|bulk|average|effective|'
              r'overall|calculated|computed|measured|experimental|apparent|total|lowest|highest)')
_NAMED_AFTER = re.compile(rf'(?i)^\s+(?:{_ADJECTIVE}[\s-]+){{0,2}}$')

# Numbers (without a unit of their own) right before a value, which share its unit: the "0.6" and
# "1.2" of "0.6, 1.2 and 1.5 eV", both ends of "0.23–0.39 eV" and of "from 0.22 to 0.25 eV", the
# "1.2 × 10−9" of "1.2 × 10−9 and 3.4 × 10−3 S/cm". Not the tail of a formula ("Li0.5FePO4 and")
# or of a power of ten ("10−4 and").
_DECIMAL_ITEM = r'\d+(?:\.\d+)?'
_POWER_ITEM = (r'(?:10\^[-−–]?\d+|10[-−–]\d{1,2}(?!\d)'
               r'|\d+(?:\.\d+)?(?:\s*(?:[eE][-−+]?\d+|[xX×\*·⋅]\s*10\^?\s?[-−–]?\s?\d+))?)')
_LIST_ITEM = {"energy": _DECIMAL_ITEM, "conductivity": _POWER_ITEM, "diffusion": _POWER_ITEM}
_LIST_SEPARATOR = r'(?:\s*,\s*(?:and\s+|or\s+)?|\s*;\s*|\s+(?:and|or|to|vs\.?|versus)\s+|\s*&\s*|\s*[–—-]\s*)'
# A citation may follow each number: "10−9[45] and 10−13 S cm−1[46]".
_CITATION = r'(?:\s?\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\])'
# Between two conductivities a minus sign is a range dash too ("0.3−0.5 mS/cm", "10−9−10−8 S/cm"):
# there is no negative one, while "0.23−0.39 eV" may be 0.23 and −0.39.
_SEPARATOR = {"energy": _LIST_SEPARATOR, "conductivity": rf'(?:{_LIST_SEPARATOR}|\s*−\s*)',
              "diffusion": rf'(?:{_LIST_SEPARATOR}|\s*−\s*)'}
_SHARED_UNIT = {kind: re.compile(rf'(?<![\w.^×−–-])(?:{item}{_CITATION}?{_SEPARATOR[kind]})+$')
                for kind, item in _LIST_ITEM.items()}
# The value of a composition variable is no member of such a list: "for x = 0.25 and 7.5 mS/cm for x = 0.6".
_OF_A_VARIABLE = re.compile(r'(?<![A-Za-z])[xyzδn]\s?[=≈]\s?$')
# "3.1 ± 0.3 × 10−6 cm2/s": the power of ten belongs to the value, not to its uncertainty.
# ... and in "3.8 × 10−10 ± 1.1 × 10−10 S/cm" each has its own.
_BEFORE_UNCERTAINTY = re.compile(r'(\d+(?:\.\d+)?)(\s*[xX×\*·⋅]\s*10\^?\s?[-−–]?\s?\d+)?\s*(?:±|\+/-|\+-)\s*$')
_POWER_OF_TEN = re.compile(r'\s*[xX×\*·⋅]\s*10\^?\s?[-−–]?\s?\d+$')
# A number that only a dash stands before is what is left of an exponent ("... 1.06×10 [line break] –4 S/cm").
_DANGLING = re.compile(r'[-−–—]\s?$')
# ... and one that follows another number is no member of a list ("Article 778057 5 and 2.9 × 10−6 S/cm").
_AFTER_A_NUMBER = re.compile(r'\d\s+$')


@dataclass
class Quantity:
    """One value of a transport quantity found in a sentence."""
    prop: str               # schema property
    kind: str               # normalizer category: "energy", "conductivity" or "diffusion"
    raw: Tuple[str, str]    # (number, unit) as printed
    span: Span              # the number (with its unit, unless it borrows the unit of a later one)
    anchor: Span            # from the name of the quantity, if it has one, to the end of the value
    term: str = ""          # the paper's wording for the quantity ("migration barrier"); "" if unnamed
    group: int = 0          # values of one list share a group ...
    position: int = 0       # ... in which this is the position-th ...
    size: int = 1           # ... of this many
    list_start: int = 0     # where the group's first number starts


def _terms(text: str, kind: str) -> List[Tuple[int, int, Optional[str]]]:
    """(start, end, property) of every name of a quantity of this kind, in text order; property is
    None for a quantity with the same unit that is not extracted (a band gap, an error)."""
    if kind == "energy":
        found = [(m.start(), m.end(), ACTIVATION_ENERGY) for m in COMPILED_EA_TERM.finditer(text)]
        found += [(m.start(), m.end(), None) for m in _OTHER_ENERGY.finditer(text)
                  if not any(s < m.end() and m.start() < e for s, e, _ in found)]
    elif kind == "conductivity":
        found = [(m.start(), m.end(), ELECTRONIC) for m in _ELECTRONIC.finditer(text)]
        found += [(m.start(), m.end(), IONIC) for m in _CONDUCTIVITY.finditer(text)
                  if not any(s < m.end() and m.start() < e for s, e, _ in found)]
    else:
        found = [(m.start(), m.end(), DIFFUSION) for m in _DIFFUSION.finditer(text)]
    return sorted(found)


def _same_sentence(text: str, start: int, end: int) -> bool:
    return not _SENTENCE_BREAK.search(text, start, end)


def _clean_term(term: str) -> str:
    """ "Activation  Energies" -> "activation energies"; a symbol keeps its case ("Ea", "DLi")."""
    term = re.sub(r'\s+', ' ', term.replace("-", " ")).strip()
    return term.lower() if re.match(r'[A-Za-z]{4}', term) else re.sub(r'\s|_', '', term)


def _which_conductivity(text: str, anchor: int, start: int, count: int, unnamed_electronic: bool) -> List[str]:
    """Ionic or electronic, for each of `count` conductivity values that end at `start` and are
    named from `anchor` on. "The electronic and ionic conductivities are 1e-9 and 1e-3 S/cm": two
    words for two values, in that order."""
    window = text[max(anchor - 45, 0):start]
    electronic = [m.start() for m in _ELECTRONIC_WORD.finditer(window)]
    ionic = [m.start() for m in re.finditer(r'(?i)\b(?:ionic|ion|total|bulk|Li\+?|Na\+?|lithium|sodium)\b', window)]
    if not electronic:
        return [ELECTRONIC if unnamed_electronic else IONIC] * count
    if not ionic:
        return [ELECTRONIC] * count
    if count == 2:
        return [ELECTRONIC, IONIC] if electronic[0] < ionic[0] else [IONIC, ELECTRONIC]
    return [ELECTRONIC if electronic[-1] > ionic[-1] else IONIC] * count


def find(text: str, previous: str = "") -> List[Quantity]:
    """Every transport value in the sentence `text`, in text order; `previous` is the sentence
    before it (it can say that an unnamed conductivity is the electronic one)."""
    found: List[Quantity] = []
    group = 0
    for kind, pattern in _VALUES.items():
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        terms = _terms(text, kind)
        unnamed_electronic = kind == "conductivity" and not terms and bool(_ELECTRONIC.search(previous)) \
            and not _CONDUCTIVITY.search(previous)
        last: Optional[Quantity] = None  # the value before this one, of the same kind
        for match in matches:
            start, end = match.start(1), match.end(match.lastindex)
            number, unit = match.group(1), match.group(match.lastindex)
            mantissa, power = _BEFORE_UNCERTAINTY.search(text[:start]), _POWER_OF_TEN.search(number)
            if mantissa:
                if not (power or mantissa.group(2)):
                    continue  # the uncertainty of a value that was not read
                number, start = mantissa.group(1) + (mantissa.group(2) or power.group()), mantissa.start()
            # The numbers before it that borrow its unit.
            shared = _SHARED_UNIT[kind].search(text[:start])
            listed = re.sub(_CITATION, lambda m: " " * len(m.group()), shared.group()) if shared else ""
            numbers = [(m.group(), shared.start() + m.start(), shared.start() + m.end())
                       for m in re.finditer(_LIST_ITEM[kind], listed)]
            while numbers and (any(_OF_A_VARIABLE.search(text[:s]) for _, s, _ in numbers)
                               or _AFTER_A_NUMBER.search(text[:numbers[0][1]])):
                numbers.pop(0)
            if kind != "energy":
                if not numbers and re.fullmatch(r'\d+(?:\.\d+)?', number) and _DANGLING.search(text[:start]):
                    continue
                # "1–2 × 10−4 S/cm", "1.2, 3.4 and 5.6 × 10−4 S/cm": one power of ten for the whole list.
                shared_power = _POWER_OF_TEN.search(number)
                if shared_power:
                    numbers = [(n if re.search(r'10|[eE]', n) else n + shared_power.group(), s, e) for n, s, e in numbers]
            first = numbers[0][1] if numbers else start

            before = [t for t in terms if t[1] <= first and _same_sentence(text, t[1], first)]
            term = before[-1] if before else None
            after = next((t for t in terms if t[0] >= end), None)
            named_after = after is not None and bool(_NAMED_AFTER.match(text[end:after[0]] + " "))
            # One list with the value before it: list wording between the two, and no quantity named there.
            chained = (last is not None and not named_after and first - last.span[1] <= _LIST_REACH
                       and _same_sentence(text, last.span[1], first)
                       and bool(_LIST_LINK.search(text[last.span[1]:first]))
                       and not any(last.span[1] <= t[0] < first for t in terms))
            props: List[Optional[str]] = [None] * (len(numbers) + 1)
            name, anchor = "", first
            if kind == "energy":
                # "the formation energy and the migration energy are 2.4 and 2.6 eV, respectively":
                # two quantities for two numbers, in that order.
                both = before[-2:] if len(numbers) == 1 and len(before) >= 2 and _RESPECTIVELY.search(text, end) else []
                if named_after:  # "a 0.25 eV barrier"; "a 5 eV band gap" is not one
                    props, name = [after[2]] * len(props), text[after[0]:after[1]]
                elif chained:
                    props, name, anchor = [last.prop] * len(props), last.term, last.anchor[0]
                elif both and _COORDINATED.fullmatch(text[both[0][1]:both[1][0]]) and first - both[1][1] <= _TERM_REACH:
                    props = [both[0][2], both[1][2]]
                    named = next((t for t in both if t[2]), None)
                    if named:
                        name, anchor = text[named[0]:named[1]], named[0]
                elif term is not None and term[2] and first - term[1] <= _TERM_REACH:
                    props, name, anchor = [term[2]] * len(props), text[term[0]:term[1]], term[0]
            elif kind == "diffusion":
                props = [DIFFUSION] * len(props)
                if chained:
                    name, anchor = last.term, last.anchor[0]
                elif term is not None and first - term[1] <= _NAME_REACH:
                    name, anchor = text[term[0]:term[1]], term[0]
            elif chained:
                props, name, anchor = [last.prop] * len(props), last.term, last.anchor[0]
            elif named_after:  # "with 5 × 10−6 S/cm electronic conductivity"
                props, name = [after[2]] * len(props), text[after[0]:after[1]]
            else:
                if term is not None and first - term[1] <= _NAME_REACH \
                        and not any(term[1] <= q.span[0] < first for q in found if q.kind == kind):
                    name, anchor = text[term[0]:term[1]], term[0]
                if name and term[2] == ELECTRONIC:
                    props = [ELECTRONIC] * len(props)
                else:
                    props = _which_conductivity(text, anchor, first, len(props), unnamed_electronic)
            if not any(props):
                last = None
                continue
            if not chained:
                group += 1
            name = _clean_term(name)
            for (earlier, s, e), prop in zip(numbers, props):
                if prop:
                    found.append(Quantity(prop, kind, (earlier, unit), (s, e), (min(anchor, s), end), name, group))
            if props[-1]:
                last = Quantity(props[-1], kind, (number, unit), (start, end), (min(anchor, start), end), name, group)
                found.append(last)

    found.sort(key=lambda q: q.span)
    for g in {q.group for q in found}:
        members = [q for q in found if q.group == g]
        for position, q in enumerate(members):
            q.position, q.size, q.list_start = position, len(members), members[0].span[0]
    return found
