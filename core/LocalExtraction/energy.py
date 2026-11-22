# LocalExtraction/energy.py
"""What kind of energy an "activation energy" is.

Papers give one name to quantities that are not the same, and a screening may only compare like with like:

    arrhenius          the activation energy of long-range transport: the slope of ln(σ) or ln(σT) against 1/T
                       (impedance), or of ln(D) against 1/T (molecular dynamics, PFG-NMR, tracer diffusion)
    migration_barrier  the energy barrier of one hop or one path, from a static calculation (NEB, a computed
                       "migration barrier" with no dynamics). It leaves out the defect formation energy and the
                       correlation of hops, so it is lower than the Arrhenius E_a of the same material
    bvse               the percolation barrier of a bond-valence site-energy map
    local_hop          the energy of local ion motion seen by NMR relaxation or quasi-elastic scattering,
                       often much lower than that of long-range transport
    vtf                the pseudo-activation energy B of a Vogel–Tammann–Fulcher fit (polymers, glasses)
    rotation, charge_transfer, electron_transfer, reaction
                       not of ion migration at all (see extractor._ROTATION and _NOT_MIGRATION): an anion's
                       rotation, ion transfer across an interface, electron transfer, a nucleation, a sintering ...
    unspecified        the paper does not say enough to tell

`energy_kind` returns the kind and why, in the words of a value's basis: "stated (NEB)" when the value's wording
names it, "paper (…)" when it is the one method of the paper's own work, "assumed (…)" for a convention.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

ARRHENIUS, BARRIER, BVSE, LOCAL_HOP, VTF = "arrhenius", "migration_barrier", "bvse", "local_hop", "vtf"
ROTATION, CHARGE_TRANSFER, ELECTRON_TRANSFER, UNSPECIFIED = "rotation", "charge_transfer", "electron_transfer", "unspecified"
REACTION = "reaction"
KINDS = (ARRHENIUS, BARRIER, BVSE, LOCAL_HOP, VTF, ROTATION, CHARGE_TRANSFER, ELECTRON_TRANSFER, REACTION, UNSPECIFIED)
# The kinds that are an energy of ion migration, so that a screening may rank them (each on its own).
MIGRATION_KINDS = (ARRHENIUS, BARRIER, BVSE, LOCAL_HOP, VTF)

# What the extraction appends to `reported_as` for an energy that is not of ion migration.
_MARKED = {"(of a rotation)": ROTATION, "(of an interfacial charge transfer)": CHARGE_TRANSFER,
           "(of an electron transfer)": ELECTRON_TRANSFER, "(of a reaction)": REACTION}

# Read in a value's own sentence, in this order: the first that matches decides.
_STATED = (
    (VTF, re.compile(r'(?i)\bV(?:TF|FT)\b|\bVogel\b|\bpseudo[\s-]?activation\b')),
    (BVSE, re.compile(r'(?i)\bBV(?:SE|EL|S)\b|\bbond[\s-]valence\b|\bsoftBV\b')),
    (BARRIER, re.compile(r'(?i)\b(?:CI-)?NEB\b|\bnudged[\s-]elastic[\s-]band\b|\bclimbing[\s-]image\b'
                         r'|\bstatic\s+(?:DFT\s+)?calculations?\b')),
    (LOCAL_HOP, re.compile(r'(?i)\bspin[\s-]lattice\b|\brelaxation\s+(?:rates?|times?|NMR)\b|\b(?:SLR|NSR)\b|\bT1(?:ρ|rho)?\b'
                           r'|\b(?:motional|line)[\s-]narrowing\b|\bquasi[\s-]?elastic\b|\bQENS\b'
                           r'|\blocal(?:i[sz]ed)?\s+(?:\([\w\s-]{1,15}\)\s+)?(?:ion(?:ic)?\s+)?(?:dynamics|motions?|hops?|hopping|jumps?)\b'
                           r'|\bshort[\s-]range\b|\bintra[\s-]?cage\b|\belementary\s+(?:jump|hop)')),
    (ARRHENIUS, re.compile(r'(?i)\bArrhenius\b|\blong[\s-]range\b|\bmacroscopic\b|\binter[\s-]?cage\b|\bimpedance\b|\bEIS\b|\bNyquist\b|\bslopes?\b|\bfit(?:ted|ting)?\b'
                           r'|\btemperature[\s-]dependen\w+|\bmolecular[\s-]dynamics\b|\b(?:AI|FP|ML)?MD\b|\bPFG\b'
                           r'|\bmean[\s-]squared?[\s-]displacements?\b|\bMSD\b|\btracer\b|\bdiffusivit\w+')),
)
# The names a static, one-hop quantity goes by.
_BARRIER_NAME = re.compile(r'(?i)\bbarriers?\b|\bmigration\s+energ|\bhopping\s+energ|^E\s?m$|^e m$')
# Techniques (study.py) as they decide the kind.
_BY_TECHNIQUE = {"static": BARRIER, "dynamic": ARRHENIUS, "impedance": ARRHENIUS}


# Where a sentence turns to another value: "..., whereas localized ion dynamics show 0.22 eV", "; the NEB
# barrier is ...", "... lower than the Arrhenius value of ...".
_TURN = re.compile(r'(?i);|,?\s+(?:whereas|while|but|than|unlike|in\s+contrast\s+(?:to|with)|compared\s+(?:to|with)'
                   r'|as\s+opposed\s+to|(?:in\s+(?:\w+\s+)?)?agree\w*\s+with|consistent\s+with|similar\s+to|close\s+to)\b')


def _quote(match: "re.Match") -> str:
    return match.group(0).strip()


def _clause(text: str, at: Optional[int]) -> str:
    """The stretch of a sentence between the turns (see _TURN) that holds position `at`."""
    if at is None or not 0 <= at <= len(text):
        return text
    start = max((m.end() for m in _TURN.finditer(text) if m.end() <= at), default=0)
    end = min((m.start() for m in _TURN.finditer(text) if m.start() > at), default=len(text))
    return text[start:end]


def _stated(text: str) -> Optional[Tuple[str, "re.Match"]]:
    for kind, pattern in _STATED:
        found = pattern.search(text)
        if found:
            return kind, found
    return None


def energy_kind(reported_as: str, sentence: str, origin: str, technique: Optional[str] = None,
                paper_technique: Optional[str] = None, at: Optional[int] = None) -> Tuple[str, str]:
    """(kind, why) of an activation energy. `reported_as` is the paper's word for it (with the extraction's
    mark for a rotation or a charge transfer), `origin` "experimental" or "simulation", `technique` the method
    its own wording (or the sentences just before it) names and `paper_technique` the one method of the paper's
    own work, both as study.technique gives them ("static", "dynamic", "local probe", "impedance"). `at` is where
    the value's number stands in `sentence`: its own clause is read first, the rest of the sentence only when
    it names one kind of energy throughout."""
    name = str(reported_as or "")
    for mark, kind in _MARKED.items():
        if name.endswith(mark):
            return kind, f"stated (“{name}”)"
    text = str(sentence or "")
    own = _stated(_clause(text, at))
    if own:
        return own[0], f"stated ({_quote(own[1])})"
    # The rest of the sentence speaks for the value only when it does not turn to another value ("..., whereas
    # localized ion dynamics show 0.22 eV" says nothing of the value before it) and names one kind throughout.
    kinds = {kind for kind, pattern in _STATED if pattern.search(text)}
    if len(kinds) == 1 and not _TURN.search(text):
        whole = _stated(text)
        return whole[0], f"stated ({_quote(whole[1])})"
    word = name.split(" (")[0].strip()
    for method, why in ((technique, "named just before the value"), (paper_technique, "the method of this paper's own work")):
        if method == "local probe":
            return LOCAL_HOP, f"assumed (NMR or scattering: {why})"
        if method in _BY_TECHNIQUE:
            kind = _BY_TECHNIQUE[method]
            if kind == ARRHENIUS and origin == "simulation" and _BARRIER_NAME.search(word) and method == "dynamic":
                # "the barrier of the [Li1-Li1] trajectory": one path read off a molecular-dynamics run
                return BARRIER, f"assumed (called “{word}” in a molecular-dynamics study: a barrier of one path)"
            return kind, f"assumed ({method} work: {why})"
    if origin == "experimental":
        return ARRHENIUS, "assumed (a measured activation energy is the slope of an Arrhenius plot)"
    if origin == "simulation" and _BARRIER_NAME.search(word):
        return BARRIER, f"assumed (called “{word}”, computed, no dynamics named: a barrier of one hop)"
    return UNSPECIFIED, "not stated (a computed activation energy whose method is not named)"
