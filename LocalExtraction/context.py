# LocalExtraction/context.py
"""Measurement context of an extracted value.

For the value at text[start:end] this reports the temperature and pressure it was obtained at and
whether it comes from experiment or simulation, and for each material mention the crystal
structure stated with it. Same rule as transport.py: every answer comes only from the wording tied
to that specific value — a condition sitting closer to another value of the same kind belongs to
that value — and conflicting evidence yields "unspecified"/"NONE", never a guess. What the
sentence leaves out is then looked for further away, level by level (`widen`, study.py), and each
answer records the level it came from. It also tells whether a number is a result for a material
at all (`not_a_result`) and whether two lists are paired off item by item (`pairs_off`).
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pymatgen.core import Element

from .normalizer import DataNormalizer
from .transport import VALUE_PATTERNS, own_segment

EXPERIMENTAL, SIMULATION, UNSPECIFIED = "experimental", "simulation", "unspecified"
ROOM_TEMPERATURE, AMBIENT_PRESSURE = "room temperature", "ambient pressure"

Span = Tuple[int, int]
Cue = Tuple[int, int, str]              # (start, end, label)
Condition = Tuple[int, int, str, bool]  # (start, end, label, trails) — see _TRAILS
Descriptor = Tuple[str, str]            # (kind, label), e.g. ("system", "cubic")

# How far (in characters) a condition / structure word may sit from what it describes.
_REACH = 60
_STRUCTURE_REACH = 45
# Two opposite origin cues closer together than this (relative to the value) are a tie.
_ORIGIN_MARGIN = 20

_NUMBER = r'\d+(?:\.\d+)?'
# A condition introduced like this trails the value it qualifies ("1.2 mS/cm at 300 K",
# "0.3 eV (25–100 °C)", "under 5 MPa"); otherwise it leads it ("room-temperature conductivity of
# 1.2 mS/cm", "σRT", "RT ionic conductivity").
_TRAILS = re.compile(r'(?i)(?:\b(?:at|under|near|around|over|between|from|of|within)|[@(=,])\s?'
                     r'(?:(?:about|approximately)\s|~\s?)?$')

# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------
_DEG_C = r'(?:°|◦|º|˚)\s?C'
_T_UNIT = rf'(?:K|{_DEG_C})'
# "300 K", "25 °C", and spans read as one range: "300–600 K", "from 25 to −20 °C",
# "500, 700 and 900 K". Not "10−6 K−1" (a per-kelvin unit) or "DES370K" (a name).
_T_MENTION = re.compile(
    rf'(?<![A-Za-z0-9.])'
    rf'(?:(?P<lo>[-−–]?{_NUMBER})\s?(?:{_T_UNIT})?\s?'
    rf'(?:[-–—−]|to|and|(?:,\s?{_NUMBER}\s?(?:{_T_UNIT})?\s?)+,?\s?and)\s?)?'
    rf'(?P<hi>(?<!\d)[-−–]?{_NUMBER})\s?(?P<unit>{_T_UNIT})(?![\w/^]|\s?[-−]\s?1)')
_ROOM_T = re.compile(r'(?i:\b(?:room|ambient|normal)[\s-]+temperatures?\b|\bambient\s+conditions\b)'
                     r'|(?<![/\w])RT\b|σ\s?_?\s?RT\b')
# "from room temperature to 100 °C", "RT–120 °C": a range that starts at room temperature.
_FROM_ROOM_T = re.compile(rf'(?:(?i:\b(?:room|ambient)[\s-]+temperature)|(?<![/\w])RT)\s?(?:[-–—−]|(?i:up\s+)?to)\s?'
                          rf'(?P<hi>{_NUMBER})\s?(?P<unit>{_T_UNIT})(?![\w/^])')
# A temperature introduced like this is a processing step, a property of its own or a bound
# ("sintered at 1200 °C", "melting point of 450 °C", "stable up to 600 K"), not the temperature
# the value was obtained at.
_T_NOT_A_CONDITION = re.compile(
    r'(?i)(?:\b(?:sinter\w*|calcin\w*|anneal\w*|heat(?:ed|ing|[\s-]treat\w*)|synthesi\w+|dr(?:ied|ying)|'
    r'quench\w*|melt\w*|decompos\w*|fir(?:ed|ing)|hot[\s-]press\w*|ball[\s-]mill\w*|debye|curie)'
    r'[^.;,]{0,25}|\btransitions?\b[^.;,]{0,60}|\b(?:above|below|up\s+to|exceed\w*|than|beyond|until)\s+(?:\w+\s+)?|[<>≤≥]\s?)$')

# A temperature that is part of the name of another quantity: "room-temperature ionic conductivity".
_T_OF_ANOTHER_QUANTITY = re.compile(r'(?i)[\s-]*(?:(?:ionic|ion|Li\+?|Na\+?|lithium|sodium|total|bulk|electronic|electrical)[\s-]+)'
                                    r'{0,2}(?:conductivit|diffusi|σ)')
# ... and so is one that names a sample by how it was made: "the 350 °C-annealed sample", "290C-Li6PS5I".
_T_OF_A_SAMPLE = re.compile(r'[\s-]*(?:annealed|sintered|calcined|heat[\s-]treated|treated|dried|synthesi[sz]ed|quenched)\b'
                            r'|-[A-Z]')

# ---------------------------------------------------------------------------
# Pressure. A bare "10 GPa" is far more often a modulus than a condition, so a pressure only
# counts when the wording introduces it as one ("under 300 MPa", "a stack pressure of 5 MPa",
# "at 300 K and 1 bar").
# ---------------------------------------------------------------------------
_P_UNIT = r'(?:GPa|MPa|kPa|Pa|kbar|mbar|bar|atm|[Tt]orr|psi)'
_P_MENTION = re.compile(
    rf'(?:(?i:\bpressures?(?:\s+(?:of|at)\b|\s*[=:])|\b(?:at|under)\b)\s*(?i:(?:about|around|approximately)\s+)?~?\s?'
    rf'|(?:\bK|{_DEG_C})\s+and\s+)'
    rf'(?P<num>{_NUMBER})\s?(?P<unit>{_P_UNIT})(?![\w/])')
_AMBIENT_P = re.compile(r'(?i)\b(?:ambient|atmospheric|standard)\s+pressure\b|\bambient\s+conditions\b')
# Pellet fabrication ("cold-pressed at 300 MPa") and mechanical properties, not a measurement condition.
_P_NOT_A_CONDITION = re.compile(
    r'(?i)\b(?:(?:\w+-)?press(?:ed|ing)|pelleti[sz]\w*|compact\w*|densif\w*|consolidat\w*|modul\w+|strength|'
    r'hardness|stress)[^.;,]{0,25}$')

# ---------------------------------------------------------------------------
# Experiment vs. simulation
# ---------------------------------------------------------------------------
_SIMULATION = re.compile(
    r'(?i:\b(?:density[\s-]functional|first[\s-]principles?|ab[\s-]initio|molecular[\s-]dynamics|'
    r'nudged[\s-]elastic[\s-]band|simulat\w+|theoretical(?:ly)?|comput(?:ed|ations?|ational(?:ly)?)|calculations?|'
    # "calculated from the Arrhenius plot" is how experimental papers report E_a: not a cue.
    r'calculated(?!\s+(?:from|using|by|via|with|according)\b)|predict\w*|force[\s-]fields?|'
    r'monte[\s-]carlo|bond[\s-]valence|machine[\s-]learn\w+|supercells?|mean[\s-]squared?[\s-]displacements?|'
    r'energy\s+(?:landscapes?|profiles?))\b)'
    r'|\b(?:DFT|AIMD|MD|NEB|MLIPs?|MLFFs?|kMC|BVSE|MSD)\b')
_EXPERIMENT = re.compile(
    r'(?i:\b(?:experiment(?:al(?:ly)?|s)?|measur(?:ed|ements?|ing)|impedance|nyquist|synthesi[sz]ed|as[\s-]prepared|'
    r'sintered|pellets?|blocking[\s-]electrodes?|galvanostatic|voltammetry|tracer[\s-]diffusion|'
    r'nuclear[\s-]magnetic[\s-]resonance|neutron[\s-]scattering)\b)'
    r'|\b(?:EIS|NMR|PFG|SIMS|XRD|GITT)\b')
# Words for a specimen: "the bare sample has an activation energy of 0.31 eV" was measured — but
# they only describe what a value is for, so they count when nothing in the sentence names a
# method ("BVSE analysis of the 350 °C-annealed sample" is a calculation). "sample" is a specimen
# in a laboratory, except the samples a model is trained on.
_SPECIMEN = re.compile(
    r'(?i)\b(?:annealed|ball[\s-]milled|(?:hot|cold)[\s-]pressed|'
    r'(?<!training\s)(?<!test\s)(?<!data\s)(?<!validation\s)samples?(?!\s+(?:the|space|size|from|of\s+(?:the\s+)?(?:data|configurations))\b))\b')
# Column-header shorthand ("σ exp.", "Ea (calc.)"); only safe in table headers — in prose "exp" is
# the exponential.
_TABLE_ORIGIN = (
    (EXPERIMENTAL, re.compile(r'(?i)\b(?:expt?l?|meas)\b\.?')),
    (SIMULATION, re.compile(r'(?i)\b(?:calcd?|sim|theor?|pred)\b\.?')),
)
# A comparison clause describes a different value ("... agrees with experiment", "... higher than
# the DFT value of 0.33 eV"): its cues speak for a value inside the clause, not for one outside it.
_COMPARED = re.compile(
    r'(?i)\b(?:agree\w*\s+(?:\w+\s+)?with|consistent\s+with|compar(?:ed|able|ing|ison)\s+(?:to|with)|'
    r'in\s+contrast\s+(?:to|with)|similar\s+to|close\s+to|match(?:es|ed|ing)?|versus|vs\.?|than|'
    r'exceed(?:s|ed|ing)?|surpass\w*|outperform\w*|relative\s+to|on\s+par\s+with)\s+'
    # To the end of the clause: the point of "0.37 eV" or "et al.10" does not end it, nor does the
    # comma before its examples ("... comparable to the best conductors, such as Li10GeP2S12.[57]")
    # or before what is said of it ("... than the barrier of LGPS, which ranges from 0.22 to 0.25 eV").
    # A citation in brackets is one thing, commas and all ("[31, 80]"); the next "than" opens a
    # comparison of its own.
    r'(?:(?!\bthan\b)(?:\[[^\]]{0,24}\]|[^.;,]|\.(?=\d)|,\s*(?=(?:such\s+as|including|like|namely)\b|e\.g\.'
    r'|which\s+(?:ranges?|lies?|var(?:y|ies))\b|which\s+(?:is|are|was|were)\s+(?:measured|reported|found|determined|'
    r'calculated|computed|estimated|predicted|about|around|approximately|only|as\s+(?:high|low)|in\s+the\s+range|[~≈∼]?\s?\d))))*'
    r'(?:\.?\s?\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\])?')

# ---------------------------------------------------------------------------
# Crystal structure
# ---------------------------------------------------------------------------
# "face-centered cubic" / "hexagonal close-packed" name a sublattice packing, not the crystal system.
_SYSTEM = re.compile(
    r'(?i)(?<!centered[\s-])(?<!centred[\s-])\b(cubic|tetragonal|orthorhombic|hexagonal|trigonal|rhombohedral|'
    r'monoclinic|triclinic)\b(?![\s-]+clos)')
# NASICON / LISICON / LGPS also name a compound (chemistry.ALIASES), so they only count as a
# structure when used as one ("NASICON-type", "LGPS-like").
_FAMILY = re.compile(
    r'(?i)\b((?:thio[\s-]?LISICON|LISICON|NASICON|LGPS)(?=[\s-]?(?:type|like|structur|phase|framework|family))|'
    r'(?:garnet|argyrodite|anti[\s-]?perovskite|perovskite|spinel|olivine|rock[\s-]?salt|anti[\s-]?fluorite|'
    r'fluorite|wurtzite|zinc[\s-]?blende|tavorite)s?|layered)\b')
_FAMILY_ALIAS = re.compile(r'(?i)(?:thio[\s-]?)?LISICON|NASICON|LGPS')
_FAMILY_LABELS = {
    "nasicon": "NASICON", "lisicon": "LISICON", "thiolisicon": "thio-LISICON", "lgps": "LGPS",
    "antiperovskite": "anti-perovskite", "rocksalt": "rock-salt", "antifluorite": "anti-fluorite",
    "zincblende": "zinc-blende",
}
# Prototype named by its formula or stacking label: "UCl3-type", "Li3YCl6-type", "P2-type".
_PROTOTYPE = re.compile(r'\b(?:[A-Z][A-Za-z0-9]*\d[A-Za-z0-9]*|[A-Z]{3,})-type\b')
_STATE = re.compile(
    r'(?i)\b(amorphous|glass[\s-]ceramics?|glassy|glass(?:es)?(?![\s-]+(?:transition|fib|substrate|vial|tube|'
    r'slide|plate))|crystalline)\b')
_GREEK = "αβγδεζꞵ"
_POLYMORPH = re.compile(rf'([{_GREEK}])\s?[-‐‑–−]?\s?(?:phase|form|polymorph|modification)\b')
_POLYMORPH_PREFIX = re.compile(rf'([{_GREEK}])\s?[-‐‑–−]\s?$')  # glued to a formula: "β-Li3PS4"
# Hermann–Mauguin symbols collide with element symbols, orbitals and scores ("Fe2", "Fe-3d", "F1",
# "R2"), so one is only read where the text marks it ("space group C2/c", "Pnma (No. 62)") or its
# shape is unmistakable ("Fm-3m", "P63/mmc", "Pnma").
_SG_CHARS = r'[-−\d/mabcdne\u0304\u0305]'
_SG_LETTERS_ONLY = (r'P(?:nma|bca|bcn|nnm|bam|ccn|mmn|mma|nna|bcm|mna|cca|mmm)|C(?:mcm|mce|mca|mmm)|'
                    r'I(?:mma|bam|mmm)|F(?:ddd|mmm)')
_SPACE_GROUP = re.compile(
    rf'(?i:space[\s-]groups?(?:\s+symmetry)?(?:\s+of)?[\s:(]*)(?P<named>[PIFRABC]{_SG_CHARS}{{1,9}})(?![A-Za-z0-9+])'
    rf'|(?<![A-Za-z0-9])(?P<numbered>(?i:{_SG_LETTERS_ONLY})|[PIFRABCpifrabc](?=[^\s(]*\d){_SG_CHARS}{{1,9}})'
    rf'\s?\(\s?(?i:no\.?|#)\s?\d{{1,3}}\s?\)'
    rf'|(?<![A-Za-z0-9])(?P<bare>[PIFRABC][mabcdne]?[-−][1-6][1-6]?[mabcdne][1-6mabcdne]{{0,2}}'
    rf'|[PIFRABC][1-6][1-5]?/[mabcdne]{{1,3}}|{_SG_LETTERS_ONLY})(?![A-Za-z0-9+])')
_ORBITAL = re.compile(r'^([A-Z][a-z]?)-\dd$')  # "Fe-3d", "Pd-4d"
_KIND_ORDER = ("polymorph", "state", "system", "family", "space_group")
# What may stand between a material and a structure word for the word to describe it — anything
# else (the comma of an enumeration "garnet, LGPS, ...", another phrase "LiCoO2 paired with garnet
# electrolytes") means it is about something else.
# Before it: "cubic LLZO", "garnet-type Li7La3Zr2O12", "the cubic phase of LLZO", "garnet (e.g., LLZO)".
_GLUE_BEFORE = re.compile(
    r'(?i)^[\s-]*(?:(?:type|phase|structured?|like|framework|polymorph|form)[\s-]*)?(?:of\s+)?(?:the\s+)?'
    r'(?:\(\s*)?(?:(?:e\.g\.|i\.e\.|such\s+as|for\s+example|namely),?\s*)?$')
# After it: "LLZO garnet", "LLZO (cubic", "Li2S with space group Fm-3m", "X crystallizes in the ...".
_GLUE_AFTER = re.compile(
    r'(?i)^\)?\s*\(?\s*(?:(?:with|in|has|have|having|adopts?|exhibits?|shows?|possess\w*|'
    r'crystalli[sz]\w+\s+in(?:to)?|of|is|as)\s+)?(?:both\s+|an?\s+|the\s+)?(?:space\s+group\s+(?:of\s+)?)?$')
# ... and between two structure words for both to describe the same material: side by side when
# they differ in kind ("cubic garnet", "cubic, Ia-3d", "garnet framework of cubic"), explicitly
# coordinated when they are alternatives of one kind ("cubic and tetragonal").
_GLUE_SAME_MATERIAL = re.compile(
    r'(?i)^[\s-]*(?:(?:type|phase|structured?|like|framework|polymorph|form|structure)[\s-]*)?[\s,]*'
    r'(?:(?:with|of)\s+)?(?:an?\s+|the\s+)?(?:space\s+group\s+(?:of\s+)?)?\(?$')
_GLUE_ALTERNATIVE = re.compile(r'(?i)^[\s-]*(?:phase\s+)?(?:and|or|/)\s*$')


# Where an answer was read: in the value's own sentence, or in the wording just before it.
STATED, NEARBY = "stated", "context"


@dataclass
class ValueContext:
    temperature: str = "NONE"
    pressure: str = "NONE"
    origin: str = UNSPECIFIED
    origin_evidence: str = "NONE"
    origin_level: str = STATED


# ---------------------------------------------------------------------------
# Shared: which value does a mention belong to
# ---------------------------------------------------------------------------
def _gap(a: Span, b: Span) -> int:
    """Characters between two spans; 0 when they overlap."""
    return 0 if a[1] > b[0] and a[0] < b[1] else min(abs(a[1] - b[0]), abs(a[0] - b[1]))


def _rivals(text: str, value: Span, kind: Optional[str]) -> List[Span]:
    """The other values in the text a mention could belong to instead: those of the same unit
    family as the value, or of every family when `kind` is None."""
    patterns = VALUE_PATTERNS.values() if kind is None else [p for k, p in VALUE_PATTERNS.items() if k == kind]
    return [m.span() for p in patterns for m in p.finditer(text) if _gap(m.span(), value) > 0]


def _tied(mentions: Sequence[tuple], value: Span, rivals: Sequence[Span], reach: int) -> List[tuple]:
    """The mentions tied to the value — within `reach` characters of it and not closer to a rival
    value — nearest first. Each mention is a tuple starting with its (start, end)."""
    kept = []
    for mention in mentions:
        distance = _gap(mention[:2], value)
        if distance <= reach and not any(_gap(mention[:2], rival) < distance for rival in rivals):
            kept.append((distance, mention))
    return [mention for _, mention in sorted(kept, key=lambda pair: pair[0])]


def _condition(conditions: Sequence[Condition], value: Span, rivals: Sequence[Span],
               others: Sequence[Span]) -> str:
    """Label of the nearest condition tied to the value ("NONE" if there is none). `others` are
    all the other transport values of the sentence: a trailing condition ("... at 300 K") belongs
    to what precedes it and a leading one ("room-temperature ...") to what follows, so the value
    only takes one from the wrong side when nothing else stands on the right side."""
    def faces(condition: Condition) -> bool:
        start, end, _, trails = condition
        if _gap((start, end), value) == 0:
            return True
        if value[1] <= start:  # the value comes first
            return trails or not any(other[0] >= end for other in others)
        return not trails or not any(other[1] <= start for other in others)

    tied = _tied([c for c in conditions if faces(c)], value, rivals, _REACH)
    return tied[0][2] if tied else "NONE"


def _merge_restated(conditions: List[Condition], keyword: str) -> List[Condition]:
    """ "room temperature (298 K)" / "25 °C (RT)" state one condition twice: keep it once, with
    the number."""
    merged: List[Condition] = []
    for condition in sorted(conditions):
        previous = merged[-1] if merged else None
        if previous and condition[0] - previous[1] <= 3 and keyword in (previous[2], condition[2]):
            label = condition[2] if previous[2] == keyword else previous[2]
            merged[-1] = (previous[0], max(previous[1], condition[1]), label, previous[3])
        else:
            merged.append(condition)
    return merged


# ---------------------------------------------------------------------------
# Temperature / pressure
# ---------------------------------------------------------------------------
def _kelvin(number: str, unit: str) -> Optional[float]:
    if unit == "K":
        number = number.lstrip("-−–")  # no negative kelvin: the dash belonged to a range
    normalized = DataNormalizer.normalize((number, unit), "temperature")
    return None if normalized == "NONE" else float(normalized.split(" ", 1)[0])


def _temperatures(text: str) -> List[Condition]:
    found: List[Condition] = []
    spans: List[Span] = []
    for m in _FROM_ROOM_T.finditer(text):
        high = _kelvin(m.group("hi"), "K" if m.group("unit") == "K" else "°C")
        if high is not None and high > 298 and not _T_NOT_A_CONDITION.search(text[:m.start()]):
            found.append((m.start(), m.end(), f"298-{high:g} K", bool(_TRAILS.search(text[:m.start()]))))
            spans.append(m.span())
    for m in _T_MENTION.finditer(text):
        if any(_gap(m.span(), span) == 0 for span in spans) or _T_OF_A_SAMPLE.match(text, m.end()):
            continue
        if _T_NOT_A_CONDITION.search(text[:m.start()]):
            continue
        unit = "K" if m.group("unit") == "K" else "°C"
        points = [_kelvin(n, unit) for n in (m.group("lo"), m.group("hi")) if n]
        if None in points:
            continue
        low, high = min(points), max(points)
        label = f"{low:g} K" if low == high else f"{low:g}-{high:g} K"
        found.append((m.start(), m.end(), label, bool(_TRAILS.search(text[:m.start()]))))
    found.extend((m.start(), m.end(), ROOM_TEMPERATURE, bool(_TRAILS.search(text[:m.start()])))
                 for m in _ROOM_T.finditer(text) if all(_gap(m.span(), span) > 0 for span in spans))
    return _merge_restated(found, ROOM_TEMPERATURE)


def _pressures(text: str) -> List[Condition]:
    found: List[Condition] = []
    for m in _P_MENTION.finditer(text):
        if _P_NOT_A_CONDITION.search(text[:m.start()]):
            continue
        unit = m.group("unit")
        normalized = DataNormalizer.normalize((m.group("num"), unit.lower() if unit == "Torr" else unit), "pressure")
        if normalized != "NONE":
            found.append((m.start(), m.end(), normalized, True))  # the pattern itself starts at "at"/"under"/...
    found.extend((m.start(), m.end(), AMBIENT_PRESSURE, bool(_TRAILS.search(text[:m.start()])))
                 for m in _AMBIENT_P.finditer(text))
    return _merge_restated(found, AMBIENT_PRESSURE)


# ---------------------------------------------------------------------------
# Experiment vs. simulation
# ---------------------------------------------------------------------------
def _origin_cues(text: str, value: Optional[Span]) -> List[Cue]:
    """The origin cues that can speak for the value (see _COMPARED)."""
    clauses = [m.span() for m in _COMPARED.finditer(text)]
    own = next((c for c in clauses if value is not None and c[0] <= value[0] < c[1]), None)

    def speaks(start: int) -> bool:
        if own:
            return own[0] <= start < own[1]
        return not any(c[0] <= start < c[1] for c in clauses)

    cues = [(m.start(), m.end(), origin)
            for origin, pattern in ((SIMULATION, _SIMULATION), (EXPERIMENTAL, _EXPERIMENT))
            for m in pattern.finditer(text) if speaks(m.start())]
    return cues or [(m.start(), m.end(), EXPERIMENTAL) for m in _SPECIMEN.finditer(text) if speaks(m.start())]


def _origin(text: str, value: Optional[Span] = None, rivals: Sequence[Span] = ()) -> Tuple[str, str]:
    """(origin, verbatim cue). With no `value` the text is judged as a whole (a neighbouring
    sentence, a table header) and must speak of one kind of work only."""
    cues = _origin_cues(text, value)
    origins = {cue[2] for cue in cues}
    if len(origins) == 1:  # the whole sentence is about one kind of work
        best = min(cues, key=lambda cue: _gap(cue[:2], value) if value else cue[0])
        return best[2], text[best[0]:best[1]]
    if origins and value is not None:
        # Both in one sentence ("DFT gives 0.30 eV while impedance gives 0.35 eV"): each value
        # takes the cue nearest to it, unless the opposite cue is about as near.
        tied = _tied(cues, value, rivals, len(text))
        if tied and all(cue[2] == tied[0][2] or _gap(cue[:2], value) - _gap(tied[0][:2], value) >= _ORIGIN_MARGIN
                        for cue in tied):
            return tied[0][2], text[tied[0][0]:tied[0][1]]
    return UNSPECIFIED, "NONE"


def value_context(text: str, start: int, end: int, kind: str, previous: str = "",
                  any_rival: bool = False) -> ValueContext:
    """Context of the value at text[start:end]; `kind` is its normalizer category and `previous`
    the sentence before it.

    Set `any_rival` for activation energies: an E_a is a slope over a temperature range, not a
    value at one temperature, so it only takes a temperature that no other transport value in the
    sentence sits closer to ("σRT of 1.2 mS/cm and Ea of 0.25 eV" leaves the E_a without one)."""
    text, start, end, split = own_segment(text, start, end)
    value = (start, end)
    same_kind, others = _rivals(text, value, kind), _rivals(text, value, None)
    rivals = others if any_rival else same_kind

    ctx = ValueContext()
    if kind != "temperature":  # a melting point is not measured "at" itself
        temperatures = _temperatures(text)
        if kind == "energy":
            # "... a barrier of 0.47 eV and a room-temperature ionic conductivity of ...": that
            # temperature is the conductivity's, whether or not its value could be read.
            temperatures = [t for t in temperatures
                            if not _T_OF_ANOTHER_QUANTITY.match(text, t[1]) and not text[t[0]:t[1]].startswith("σ")]
        ctx.temperature = _condition(temperatures, value, rivals, others)
    if kind != "pressure":
        ctx.pressure = _condition(_pressures(text), value, rivals, others)

    ctx.origin, ctx.origin_evidence = _origin(text, value, same_kind)
    # Nothing in the sentence itself: the method is often named just before it ("AIMD simulations
    # were run at 600-1200 K. The activation energy is 0.25 eV."). Only what precedes counts — the
    # sentence after a measured result routinely moves on to the calculations explaining it.
    for preceding in (split[0] if split else "", previous):
        if ctx.origin == UNSPECIFIED and preceding:
            ctx.origin, ctx.origin_evidence = _origin(preceding)
            ctx.origin_level = NEARBY
    return ctx


def table_context(contexts: Iterable[Optional[str]], kind: str) -> ValueContext:
    """Table cells: for each of temperature, pressure and origin, the first context (a condition
    column of the row, the column header, the row label, the caption) that states it wins."""
    ctx = ValueContext()
    for text in contexts:
        if not text:
            continue
        if ctx.temperature == "NONE" and kind != "temperature":
            ctx.temperature = next((c[2] for c in _temperatures(text)), "NONE")
        if ctx.pressure == "NONE" and kind != "pressure":
            ctx.pressure = next((c[2] for c in _pressures(text)), "NONE")
        if ctx.origin == UNSPECIFIED:
            ctx.origin, ctx.origin_evidence = _origin(text)
            if ctx.origin == UNSPECIFIED:
                shorthand = [(origin, m.group()) for origin, pattern in _TABLE_ORIGIN for m in pattern.finditer(text)]
                if len({origin for origin, _ in shorthand}) == 1:
                    ctx.origin, ctx.origin_evidence = shorthand[0]
    return ctx


# ---------------------------------------------------------------------------
# What a text other than the value's own sentence states: a neighbouring sentence, the caption of
# the figure it points to, a statement of the methods. Such a text is not about one value, so it
# only counts when it says one thing.
# ---------------------------------------------------------------------------
def comparison_clauses(text: str) -> List[Span]:
    """The stretches of a text that compare with something else ("... higher than that of LATP",
    "in agreement with the experimental value of 0.37 eV [4]"): what stands in one speaks of the
    other thing, not of the sentence's own subject."""
    return [m.span() for m in _COMPARED.finditer(text)]


# What a comparison is made with stands right after the word that makes it: "than that of LATP",
# "similar to the β-Li3PS4 results", "compared with Li6PS5Cl".
_COMPARED_WITH = re.compile(
    r'(?i)\b(?:agree\w*\s+(?:\w+\s+)?with|consistent\s+with|compar(?:ed|able|ing|ison)\s+(?:to|with)|'
    r'in\s+contrast\s+(?:to|with)|similar\s+to|close\s+to|match(?:es|ed|ing)?|versus|vs\.?|than|unlike|'
    r'exceed(?:s|ed|ing)?|surpass\w*|outperform\w*|relative\s+to|on\s+par\s+with)\s+'
    r'(?:(?:that|those|the\s+ones?|the\s+(?:[\w-]+\s+){0,2}?(?:values?|case|conductivit(?:y|ies)|barriers?|energ(?:y|ies)))'
    r'\s+(?:of|for|in)\s+)?'
    # "... comparable to the known superionic conductors such as Li10GeP2S12"
    r'(?:(?:[\w-]+\s+){0,6}(?:such\s+as|like|including|namely|e\.g\.,?)\s+'
    # ... or at the end of the words that describe it: "surpassing that of the Hf4+-substituted
    # Li2.6Yb0.6Hf0.4Cl6", "comparable to the previously reported ball-milled KB11H14".
    r'|(?:(?!(?:is|are|was|were|has|have|had|and|or|but|which|that|while|whereas|in|on|at|by|with|from|to|as|for|of)\b)'
    r'(?:[\w+−-]|\.(?=\d))+[\s-]+){0,4})$')


def is_compared_with(text: str, start: int) -> bool:
    """Whether what starts at `start` is the thing a comparison is made with."""
    return bool(_COMPARED_WITH.search(text[:start]))


def origin_of(text: str) -> Tuple[str, str]:
    """(origin, verbatim cue) of a text that speaks of one kind of work only; else unspecified."""
    return _origin(text)


def is_room_temperature(label: str) -> bool:
    """Whether a temperature label is room temperature in words or in numbers (18-30 °C)."""
    if label == ROOM_TEMPERATURE:
        return True
    return label != "NONE" and "-" not in label and 291 <= float(label.split(" ", 1)[0]) <= 303


def temperature_range(text: str) -> str:
    """The temperature range a text states ("298-373 K": what an Arrhenius fit or a set of MD runs
    spans); "NONE" unless it states exactly one."""
    ranges = {label for _, _, label, _ in _temperatures(text) if "-" in label}
    return ranges.pop() if len(ranges) == 1 else "NONE"


def temperature_point(text: str) -> str:
    """The one temperature a text states ("473 K", "room temperature"); "NONE" if it states none,
    a range, or several different ones. "room temperature" and "25 °C" are the same statement."""
    labels = [label for _, _, label, _ in _temperatures(text)]
    if not labels or any("-" in label for label in labels):
        return "NONE"
    if all(is_room_temperature(label) for label in labels):
        return next((label for label in labels if label != ROOM_TEMPERATURE), ROOM_TEMPERATURE)
    return labels[0] if len(set(labels)) == 1 else "NONE"


def pressure_point(text: str) -> str:
    """The one pressure a text states as a condition; "NONE" if it states none or several."""
    labels = {label for _, _, label, _ in _pressures(text)}
    return labels.pop() if len(labels) == 1 else "NONE"


# ---------------------------------------------------------------------------
# Crystal structure
# ---------------------------------------------------------------------------
def _space_group(symbol: str, bare: bool) -> Optional[str]:
    # "Fm3m" written with an overline on the 3 is "Fm-3m"
    symbol = re.sub(r'(\d)[\u0304\u0305]', r'-\1', symbol.replace("−", "-")).rstrip("-/")
    symbol = re.sub(r'-{2,}', '-', symbol)  # "R-3̄c": a minus and an overline for the same thing
    symbol = symbol[0].upper() + symbol[1:]
    orbital = _ORBITAL.match(symbol) if bare else None
    if orbital and Element.is_valid_symbol(orbital.group(1)):
        return None
    return symbol


def _is_label(text: str, start: int) -> bool:
    """A structure-family word capitalised in mid-sentence is a label lifted from a figure ("LLTO
    Antiperovskite Li7P3S11 Argyrodite ..."), not a description of what happens to stand next to
    it. Acronyms (NASICON, LGPS) are always capitalised, so they don't count."""
    return (text[start].isupper() and not text[start:start + 2].isupper()
            and text[:start].rstrip()[-1:].isalnum())


def find_structures(text: str) -> List[Tuple[int, int, str, str]]:
    """Every structure descriptor in the text, as (start, end, kind, label)."""
    hits: List[Tuple[int, int, str, str]] = []

    def add(span: Span, kind: str, label: Optional[str]) -> None:
        if label and all(_gap(span, hit[:2]) > 0 for hit in hits):
            hits.append((*span, kind, label))

    for m in _SPACE_GROUP.finditer(text):
        add(m.span(m.lastgroup), "space_group", _space_group(m.group(m.lastgroup), m.lastgroup == "bare"))
    for m in _SYSTEM.finditer(text):
        add(m.span(1), "system", m.group(1).lower())
    for m in _FAMILY.finditer(text):
        if not _is_label(text, m.start(1)):
            key = re.sub(r'[\s-]', '', m.group(1).lower())
            key = key if key in _FAMILY_LABELS else key.rstrip("s")
            add(m.span(1), "family", _FAMILY_LABELS.get(key, key))
    for m in _PROTOTYPE.finditer(text):
        add(m.span(), "family", m.group())
    for m in _STATE.finditer(text):
        if not _is_label(text, m.start(1)):
            word = m.group(1).lower()
            label = "glass-ceramic" if "ceramic" in word else "glass" if word.startswith("glass") else word
            add(m.span(1), "state", label)
    for m in _POLYMORPH.finditer(text):
        add(m.span(), "polymorph", f"{m.group(1).replace('ꞵ', 'β')}-phase")
    return hits


def describe(descriptors: Iterable[Descriptor]) -> str:
    """'cubic | garnet | Ia-3d' from (kind, label) pairs, in a fixed kind order; 'NONE' if empty."""
    descriptors = list(descriptors)
    labels = dict.fromkeys(label for kind in _KIND_ORDER for k, label in descriptors if k == kind)
    return " | ".join(labels) or "NONE"


def structures_of(text: str, mentions: Sequence[Span]) -> List[List[Descriptor]]:
    """For each material mention (a span of `text`), the structure descriptors stated with it.

    A descriptor belongs to a mention only when it stands right next to it (see _GLUE_BEFORE /
    _GLUE_AFTER), or next to another descriptor that does — never by mere proximity."""
    hits = find_structures(text)
    owned: List[List[Tuple[int, str, str]]] = [[] for _ in mentions]  # (position, kind, label)

    def between(a: Span, b: Span) -> str:
        return text[min(a[1], b[1]):max(a[0], b[0])]

    # A "mention" that is itself a structure name ("NASICON-type ...", "Li3YCl6-type Li3ErCl6")
    # is not a material here: the name describes the material next to it.
    real = [i for i, m in enumerate(mentions) if all(_gap(m, hit[:2]) > 0 for hit in hits)]
    # ... and one that is a family name used as a compound (chemistry.ALIASES) is never of
    # another family: "perovskite, NASICON and garnet electrolytes" lists three.
    named_family = {i for i in real if _FAMILY_ALIAS.fullmatch(text[mentions[i][0]:mentions[i][1]])}
    attached: List[Tuple[Span, str, int]] = []  # (span, kind, mention index)
    pending = []
    for start, end, kind, label in hits:
        span = (start, end)
        # Adjectives precede what they describe ("LaCl3, monoclinic Na3ErCl6"): at equal distance
        # the following mention wins.
        glued = sorted(
            (_gap(mentions[i], span), mentions[i][0] < start, i) for i in real
            if not (kind == "family" and i in named_family)
            and (_GLUE_BEFORE if end <= mentions[i][0] else _GLUE_AFTER).match(between(span, mentions[i])))
        if glued and glued[0][0] <= _STRUCTURE_REACH:
            owned[glued[0][2]].append((start, kind, label))
            attached.append((span, kind, glued[0][2]))
        else:
            pending.append((span, kind, label))
    progress = True
    while progress:
        progress = False
        for span, kind, label in list(pending):
            for other, other_kind, i in attached:
                glue = _GLUE_ALTERNATIVE if kind == other_kind else _GLUE_SAME_MATERIAL
                if not (kind == "family" and i in named_family) and glue.match(between(span, other)):
                    owned[i].append((span[0], kind, label))
                    attached.append((span, kind, i))
                    pending.remove((span, kind, label))
                    progress = True
                    break

    for i, (start, _) in enumerate(mentions):
        prefix = _POLYMORPH_PREFIX.search(text[max(0, start - 3):start])
        if prefix:
            owned[i].append((start, "polymorph", f"{prefix.group(1).replace('ꞵ', 'β')}-phase"))
    return [[(kind, label) for _, kind, label in sorted(found)] for found in owned]


def structure_near(text: str, start: int, end: int, kind: str) -> List[Descriptor]:
    """Descriptors tied to a value whose sentence names no material ("... in the γ-phase had a
    diffusion barrier of 0.16 eV"): in the value's own clause, and not closer to another value."""
    text, start, end, _ = own_segment(text, start, end)
    value = (start, end)
    hits = [(s, e, (k, label)) for s, e, k, label in find_structures(text)
            if not re.search(r'[,;:]', text[min(e, end):max(s, start)])]
    return [descriptor for _, _, descriptor in _tied(hits, value, _rivals(text, value, kind), _STRUCTURE_REACH)]


def without_type_labels(text: str, mentions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The material mentions that really are mentions of a material. A name used as a structure
    type — "five LGPS-like structures", "NASICON-type Li1.3Al0.3Ti1.7(PO4)3", "Li3YCl6-type
    Li3ErCl6" — describes the material next to it and says nothing about the one it names."""
    labels = [hit[:2] for hit in find_structures(text) if hit[2] == "family"]
    return [m for m in mentions if all(_gap((m["start"], m["end"]), label) > 0 for label in labels)]


# ---------------------------------------------------------------------------
# Is the number a result?
# ---------------------------------------------------------------------------
# What a number with the right unit can be besides a result for a material: a design criterion
# ("an activation energy of <0.3 eV"), an assumed input ("the extrapolation assumes a barrier of
# 0.35 eV"), the error of a model ("RMSE of 0.15 eV"), the thermal energy ("kBT = 78 meV"), a
# change or a difference ("lowered by 0.1 eV", "0.2 eV higher than"), a reference line drawn in a
# plot ("the vertical dashed line shows the activation energy at 0.356 eV") or the tick labels of
# a plot that PDF extraction ran together ("EA 106 104 102 10 3 10 2 FV0.5 eV").
_BOUND = (r'[<>≤≥]|\b(?:below|above|under|over|exceed(?:s|ing)?|less\s+than|more\s+than|lower\s+than|'
          r'higher\s+than|greater\s+than|smaller\s+than|larger\s+than|at\s+least|at\s+most|within')
_APPROXIMATELY = r'\s*(?:[~≈∼]|about|approximately|around|nearly|roughly|only)?\s*$'
# "up to 12 mS/cm" is how a best conductivity is reported; "up to 0.5 eV" is a bound.
_BOUND_BEFORE = {
    True: re.compile(rf'(?i)(?:{_BOUND}|up\s+to)){_APPROXIMATELY}'),
    False: re.compile(rf'(?i)(?:{_BOUND})){_APPROXIMATELY}'),
}
_CHANGE_BEFORE = re.compile(rf'(?i)\b(?:by|(?:differences?|changes?|increases?|decreases?|reductions?|drops?|shifts?)\s+of){_APPROXIMATELY}')
# "the difference between the lowest and the highest migration barriers of MgMn2O4 is 662 meV"
_DIFFERENCE_BEFORE = re.compile(r'(?i)\bdifferences?\s+(?:between|in|of)\b[^.;]{0,90}$')
_DIFFERENCE_AFTER = re.compile(
    r'(?i)^\s*(?:lower|higher|smaller|larger|less|more|greater|below|above|changes?|differences?|reductions?|'
    r'increases?|decreases?|drops?|shifts?|variations?)\b')
_THERMAL_BEFORE = re.compile(r'\bk\s*_?\s*(?:B\s*_?\s*)?T\s*[=≈~:]?\s*$')
_ERROR_WORD = re.compile(
    r'(?i)\b(?:RMSE|MAE|MSE|RMSD|MAPE|errors?|deviations?|uncertaint(?:y|ies)|accuracy|residuals?)\b')
_INPUT_WORD = re.compile(
    r'(?i)\b(?:assum(?:e|es|ed|ing|ption)|typical(?:ly)?|hypothetical(?:ly)?|desired|targets?|'
    r'criteri(?:on|a)|thresholds?|(?:upper|lower)[\s-]+(?:limit|bound)s?|cut-?offs?)\b')
_REFERENCE_LINE = re.compile(r'(?i)\b(?:dashed|dotted|dash-dotted|horizontal|vertical)\s+(?:\w+\s+)?lines?\b')
_NUMERIC_TOKEN = re.compile(r'^[-−]?\d+(?:\.\d+)?[,;]?$')
_INPUT_REACH = 30  # characters before the keyword in which "assumes ..." / "typical ..." still apply


def not_a_result(text: str, keyword_start: int, list_start: int, value: Optional[Span] = None,
                 energy: bool = True) -> Optional[str]:
    """Why a number is not a result for a material, or None if it may be one.

    `keyword_start` is where the wording that names the quantity begins and `list_start` where the
    first number it introduces does (the start of the list, for "0.6, 1.2 and 1.5 eV"); `value` is
    the number itself when it is not that first one. `energy` tells an energy from a conductivity
    or a diffusion coefficient."""
    start, end = value or (list_start, list_start)
    before = text[:start]
    if _BOUND_BEFORE[energy].search(before):
        return "threshold"
    if _CHANGE_BEFORE.search(before) or (value is not None and _DIFFERENCE_AFTER.search(text[end:])) \
            or (start == list_start and _DIFFERENCE_BEFORE.search(text[:keyword_start])):
        return "a change or a difference"
    if energy and _THERMAL_BEFORE.search(before):
        return "thermal energy"
    between = text[keyword_start:list_start]
    nearby = text[max(0, keyword_start - _INPUT_REACH):list_start]
    if _ERROR_WORD.search(nearby):
        return "error of a model"
    if _INPUT_WORD.search(nearby):
        return "assumed or typical value"
    if _REFERENCE_LINE.search(nearby):
        return "reference line of a plot"
    tokens = between.split()
    numeric = sum(1 for token in tokens if _NUMERIC_TOKEN.match(token))
    if numeric >= 3 and numeric * 2 > len(tokens):
        return "plot labels"
    return None


# ---------------------------------------------------------------------------
# Lists of values: "0.6, 1.2 and 1.5 GPa", ranges "150–160 mAh/g", "A, B and C ... respectively".
# (The transport quantities have their own, richer reading of lists: quantities.py.)
# ---------------------------------------------------------------------------
_LIST_ITEM = r'\d+(?:\.\d+)?'
# A dash joins the two ends of a range ("0.23–0.39 eV"); both ends are values of the property.
_LIST_SEPARATOR = r'(?:\s*,\s*(?:and\s+|or\s+)?|\s*;\s*|\s+(?:and|or)\s+|\s*&\s*|\s*[–—-]\s*)'
# Numbers (without their own unit) right before the one a pattern matched. Not the tail of a
# formula ("Li0.5FePO4 and") or of a power of ten ("10−4 and").
_VALUE_LIST = re.compile(rf'(?<![\w.^×−–-])(?:{_LIST_ITEM}{_LIST_SEPARATOR})+$')
_RESPECTIVELY = re.compile(r'(?i)\b(?:respectively|in\s+(?:that|this|the\s+same)\s+order|correspondingly|accordingly)\b')


def preceding_values(text: str, value_start: int) -> Tuple[int, List[str]]:
    """The numbers that share the unit of the value starting at `value_start` ("0.6" and "1.2" for
    the "1.5" of "0.6, 1.2 and 1.5 GPa"), and where the list starts (`value_start` if it is alone)."""
    found = _VALUE_LIST.search(text[:value_start])
    if not found:
        return value_start, []
    return found.start(), re.findall(_LIST_ITEM, found.group())


def pairs_off(text: str) -> bool:
    """Whether the text pairs two lists item by item ("..., respectively")."""
    return bool(_RESPECTIVELY.search(text))
