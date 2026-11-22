# LocalExtraction/scope.py
"""Whether a transport value is one of the kind of material a database is about: a solid electrolyte, a cathode
or an anode (the `domain` of an extraction, `DOMAINS`).

Papers on solid electrolytes give, next to their electrolytes' values, values of the other things in a cell: the
lithium fluoride or carbonate of an interphase, an electrode, an alloy anode, a molecule of a liquid, or a composite
of the ceramic with a polymer. They are real values, but not of a candidate electrolyte, and a screening that ranks
them puts LiF and LiCoO2 among the "superionic" conductors. `material_scope` says why a value is not one of a
candidate, in words; "" when it may be one. species.plausibility turns the reason into a "check: …" flag, so the
value stays in the database and the ranking leaves it out unless asked.

A cathode or an anode database keeps what an electrolyte one flags as an electrode, and flags instead what is no
material of its kind: an interphase salt, a molecule, a solid electrolyte (and, for cathodes, an alloy or a lithiated
carbon, which are anodes). Composites are the rule for electrodes (carbon, binder), so only an electrolyte database
flags them.

Only what the composition, or the value's own clause, leaves no doubt about is flagged.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Optional, Union

from .chemistry import ChemistryEngine

Composition = Dict[str, Union[float, str]]

ELECTROLYTE, CATHODE, ANODE = "electrolyte", "cathode", "anode"
DOMAINS = (ELECTROLYTE, CATHODE, ANODE)
# The families of the well-known solid electrolytes (chemistry.structure_family): no electrode material of either
# kind. (NASICON is left out for anodes: LiTi2(PO4)3 is one.)
_ELECTROLYTE_FAMILIES = {CATHODE: ("garnet", "argyrodite", "LGPS-type", "NASICON", "LISICON", "thio-LISICON",
                                   "anti-perovskite"),
                         ANODE: ("garnet", "argyrodite", "LGPS-type", "LISICON", "thio-LISICON", "anti-perovskite")}

# The elements that form the anions of a salt; a composition of none of them is a metal or an alloy.
_ANION_FORMERS = frozenset("H B C N O F P S Se Te Cl Br I".split())
# Transition metals that change their oxidation state in an electrode. (Ti, Nb, Ta, Zr, Y, La, Sc, In are framework
# cations of electrolytes; Cu and Ag of the Cu+ and Ag+ conductors.)
_REDOX_METALS = frozenset("Co Ni Mn Fe V Cr".split())
# A material with this share of its cations a redox metal is an electrode (LiCoO2: 1/2, Li3V2(PO4)3: 2/8, NaFeO2: 1/2),
# not an electrolyte doped with one (Li6.25Fe0.25La3Zr2O12: 0.02).
_REDOX_SHARE = 0.2
_ELECTRODE_FAMILIES = ("layered", "spinel", "olivine")

# Compounds that form an interphase (SEI, CEI) or are simple salts, never candidate solid electrolytes; by formula.
_INTERPHASE = frozenset({
    "LiF", "LiCl", "Li2O", "Li2O2", "Li2CO3", "LiOH", "Li2S", "Li2Se", "LiNO3",
    "NaF", "NaCl", "Na2O", "Na2CO3", "NaOH", "Na2S", "KF", "KCl",
    "CaF2", "CaO", "CaCO3", "MgF2", "MgO", "ZnF2", "ZnO",
})
_MOLECULES = frozenset({"H2O", "CO2", "H2", "O2", "N2", "CH4", "CH4N2O", "NH3"})

# A composite in the value's own clause: "the LTPO composite samples", "0.27 eV for the 50–50 sample", "in PEO".
_COMPOSITE = re.compile(
    r'(?i)\bcomposites?\b|\bCSEs?\b|\bCPEs?\b|\bhybrid\b|\bgel(?:s|led)?\b|\bpolymers?\b|\bMOFs?\b|\bfillers?\b'
    r'|\b(?:PEO|PVDF(?:-HFP)?|PAN|PEG|PEGDA|PMMA|PVA|PPC|PTFE|PVP|PAA|PDA)\b|\bwt\s?%|\b\d+\s?[–-]\s?\d+\s+samples?\b')
# ... and a formula glued to another phase: "CaI2@TB-MOF", "LAGP/PEO", "PEO-LLZO".
_GLUED_AFTER = re.compile(r'^\s?[@/]\s?[A-Za-z]')
_GLUED_BEFORE = re.compile(r'[A-Za-z][@/]\s?$|(?:PEO|PVDF|PAN|PEG|PMMA)\s?[-–]\s?$')
# ... and the strongest of these words anywhere in a sentence that gives one value only, or pairs its values off
# ("respectively"): "the membrane containing 26 wt% LATP exhibits the lowest activation energy (0.138 eV)".
_COMPOSITE_STRONG = re.compile(r'(?i)\bcomposites?\b|\bCSEs?\b|\bCPEs?\b|\bhybrid\b|\bwt\s?%|\bmembranes?\s+(?:containing|with)\b'
                               r'|\bmixed\s+electrolytes?\b|\bpowder\s+mixtures?\b')
_ENERGY_VALUE = re.compile(r'\d(?:\.\d+)?\s?(?:eV|meV|kJ\s?(?:/\s?mol|mol))')
_RESPECTIVELY = re.compile(r'(?i)\brespectively\b')
# "the Al-doped LLZO", "Al─N co-doped", "Ga-stabilized": the dopants a sentence names for a sample.
_DOPED = re.compile(r'(?<![A-Za-z])((?:[A-Z][a-z]?)(?:\s?[─–/,-]\s?[A-Z][a-z]?)*)\s?[-‐─–]?\s?(?:co-?)?(?:doped|substituted|stabili[sz]ed)\b')
_SYMBOLS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
    "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi".split())
# Where a sentence moves on to another value: its clause is the value's own.
_CLAUSE_BREAK = re.compile(r'(?i)[;,]|\s(?:and|whereas|while|but|than|unlike|versus|vs\.?)\s')


def _composition(formula: str, composition: Union[str, Composition, None]) -> Optional[Composition]:
    if isinstance(composition, dict):
        return composition
    if isinstance(composition, str) and composition.strip().startswith("{"):
        try:
            return json.loads(composition)
        except ValueError:
            pass
    found = ChemistryEngine.find_materials(formula) if formula and formula != "NONE" else []
    return found[0]["elements"] if len(found) == 1 else None


def _clause(sentence: str, at: Optional[int]) -> str:
    if at is None or not 0 <= at <= len(sentence):
        return sentence
    start = max((m.end() for m in _CLAUSE_BREAK.finditer(sentence) if m.end() <= at), default=0)
    end = min((m.start() for m in _CLAUSE_BREAK.finditer(sentence) if m.start() > at), default=len(sentence))
    return sentence[start:end]


def _own_text(sentence: str, at: Optional[int]) -> str:
    """The value's own clause; the whole sentence when it pairs its values off ("..., respectively")."""
    return sentence if _RESPECTIVELY.search(sentence) else _clause(sentence, at)


def _composite(formula: str, sentence: str, at: Optional[int]) -> bool:
    if _COMPOSITE.search(_own_text(sentence, at)):
        return True
    if _COMPOSITE_STRONG.search(sentence) and (len(_ENERGY_VALUE.findall(sentence)) <= 1 or _RESPECTIVELY.search(sentence)):
        return True
    for m in re.finditer(re.escape(formula), sentence) if formula and len(formula) > 2 else ():
        if _GLUED_AFTER.match(sentence[m.end():]) or _GLUED_BEFORE.search(sentence[:m.start()]):
            return True
    return False


def _missing_dopant(amounts: Composition, sentence: str, at: Optional[int]) -> str:
    """The dopant a value's clause names that its formula lacks ("Al" of "the Al-doped LLZO" stored as Li7La3Zr2O12)."""
    for m in _DOPED.finditer(_own_text(sentence, at)):
        named = [e for e in re.findall(r'[A-Z][a-z]?', m.group(1)) if e in _SYMBOLS]
        missing = [e for e in named if e not in amounts]
        if named and missing:
            return "-".join(named)
    return ""


def material_scope(formula: str, composition: Union[str, Composition, None] = None, sentence: str = "",
                   at: Optional[int] = None, domain: str = ELECTROLYTE) -> str:
    """Why a transport value of `formula` (with its `composition`, as the tables write it) is not one of a material of
    the `domain` ("electrolyte", "cathode", "anode") — "" when it may be. `sentence` is the value's sentence and `at`
    where its number stands."""
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r}: one of {', '.join(DOMAINS)}")
    if domain != ELECTROLYTE:
        return _electrode_scope(str(formula or ""), composition, sentence, at, domain)
    formula = str(formula or "")
    amounts = _composition(formula, composition)
    if amounts:
        numeric = {e: a for e, a in amounts.items() if isinstance(a, (int, float))}
        canonical = formula.replace(" ", "")
        if canonical in _MOLECULES:
            return "a molecule, not a solid ion conductor"
        if canonical in _INTERPHASE:
            return "a simple salt or an interphase compound (LiF, Li2CO3 ...), not a candidate electrolyte"
        elements = set(amounts)
        if not elements & _ANION_FORMERS:
            return "a metal or an alloy (an electrode), not an electrolyte" if len(elements) > 1 else "a metal, not an electrolyte"
        cations = {e: a for e, a in numeric.items() if e not in _ANION_FORMERS}
        total = sum(cations.values())
        if total and sum(a for e, a in cations.items() if e in _REDOX_METALS) / total >= _REDOX_SHARE:
            return "an electrode material (a transition-metal compound), not an electrolyte"
        if ChemistryEngine.structure_family(amounts) in _ELECTRODE_FAMILIES:
            return "an electrode material (a layered, spinel or olivine compound), not an electrolyte"
        if elements <= {"Li", "Na", "K", "C"} and "C" in elements:
            return "a lithiated carbon (an electrode, LiC6), not an electrolyte"
        dopant = _missing_dopant(amounts, sentence, at) if sentence and "-doped " not in formula else ""
        if dopant:
            # "an Al-doped", "a Ga-doped": the article goes by how the symbol is read out
            article = "an" if dopant[0] in "AEFHILMNORSX" else "a"
            return f"{article} {dopant}-doped sample stored under a formula without {dopant}"
    if sentence and _composite(formula, sentence, at):
        return "a composite (with a polymer, a gel or a framework), not the material alone"
    return ""


def _redox_share(amounts: Composition) -> float:
    cations = {e: a for e, a in amounts.items() if isinstance(a, (int, float)) and e not in _ANION_FORMERS}
    total = sum(cations.values())
    return sum(a for e, a in cations.items() if e in _REDOX_METALS) / total if total else 0.0


def _electrode_scope(formula: str, composition: Union[str, Composition, None], sentence: str, at: Optional[int],
                     domain: str) -> str:
    """material_scope for a cathode or an anode database."""
    amounts = _composition(formula, composition)
    if not amounts:
        return ""
    what = ("an " if domain[0] in "aeiou" else "a ") + f"{domain} material"
    canonical = formula.replace(" ", "")
    if canonical in _MOLECULES:
        return f"a molecule, not {what}"
    if canonical in _INTERPHASE:
        return f"a simple salt or an interphase compound (LiF, Li2CO3 ...), not {what}"
    elements = set(amounts)
    if domain == CATHODE:
        if not elements & _ANION_FORMERS:
            return "a metal or an alloy (an anode), not a cathode material"
        if elements <= {"Li", "Na", "K", "C"} and "C" in elements:
            return "a lithiated carbon (an anode), not a cathode material"
    if _redox_share(amounts) < _REDOX_SHARE and ChemistryEngine.structure_family(amounts) in _ELECTROLYTE_FAMILIES[domain]:
        return f"a solid electrolyte, not {what}"
    dopant = _missing_dopant(amounts, sentence, at) if sentence and "-doped " not in formula else ""
    if dopant:
        article = "an" if dopant[0] in "AEFHILMNORSX" else "a"
        return f"{article} {dopant}-doped sample stored under a formula without {dopant}"
    return ""
