# LocalExtraction/transport.py
"""Transport-component classifier for ion-transport observations.

Decides whether an E_a, conductivity or diffusivity value describes "bulk", "grain_boundary",
"surface" or "total" transport, else "unspecified", from the wording tied to that specific value.
High precision beats recall: a bare "polycrystalline", "pellet", "Arrhenius", "AIMD", "[001]", ...
never decides a label, and conflicting evidence yields "unspecified". Returns the verbatim text
that justifies the label.
"""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

BULK, GB, SURFACE, TOTAL, UNSPECIFIED = "bulk", "grain_boundary", "surface", "total", "unspecified"

# Any transport quantity a qualifier can attach to (conductivity, diffusion, E_a, resistance, ...).
_Q = (r'(?:(?:ionic|ion|electrical|electronic|li|na|lithium|sodium)[\s-]+)?'
      r'(?:transport|conduction|conductivit(?:y|ies)|conductances?|diffusion|diffusivit(?:y|ies)|'
      r'diffusion\s+coefficients?|migration|hopping|resistances?|resistivit(?:y|ies)|relaxation|'
      r'activation\s+(?:energy|energies|barriers?)|barriers?|semicircles?|arcs?|contributions?|responses?|process(?:es)?)')
# The symbol is matched case-sensitively and as a word of its own (every pattern below is
# otherwise case-insensitive): "ea" is also how "area" ends, and "area of the grains" is not E_a.
_EA = r'(?:(?-i:\bE\s?_?\s?(?:a|ac|act|A))\b|activation\s+energ(?:y|ies))'
_GAP_W = r'(?:(?!(?:with|of|was|were|is|are|and|for|at|in|as|the|by|from)\b)[\w\-]+\s+){0,2}'  # up to two filler words ("bulk lithium ion diffusion")

_GB_WORD = r'(?:grain[\s-]*boundar(?:y|ies)|\bGBs?\b|inter-?granular)'

_RAW: List[Tuple[str, str]] = [
    # ---- total: combined / overall / effective, checked before single components ----
    (TOTAL, rf'(?i)\bcombined\s+(?:the\s+)?(?:bulk|grain[\s-]*interior)\s*(?:and|\+|/|&)\s*(?:the\s+)?{_GB_WORD}'),
    (TOTAL, rf'(?i)\b(?:bulk|grain[\s-]*interior)\s*(?:and|\+|/|&)\s*{_GB_WORD}\s+(?:contributions?|resistances?|conductivit(?:y|ies))\s+(?:combined|together)'),
    (TOTAL, rf'(?i)\b(?:including|contain\w*|sum\s+of)\s+(?:both\s+)?(?:the\s+)?(?:bulk|grain[\s-]*interior)\s*(?:and|\+|/|&)\s*{_GB_WORD}'),
    (TOTAL, rf'(?i)\b(?:through|across|within)\s+(?:both\s+)?(?:the\s+)?grains?\s+and\s+{_GB_WORD}'),
    (TOTAL, r'\bR\s*_\s*(?:tot(?:al)?|t)\b|\bR(?:tot|total)\b'),
    (TOTAL, r'\bR\s*_?\s*(?:b|bulk)\s*\+\s*R\s*_?\s*(?:gb|g\.?b\.?)\b'),
    (TOTAL, r'(?i)\b(?:total|overall|effective|macroscopic|apparent|sample)\s+(?:ionic\s+|ion\s+)?(?:conductivity|conductance|transport|diffusion(?:\s+coefficient)?|diffusivity|resistance|resistivity)\b'),
    (TOTAL, rf'(?i)\btotal\s+{_EA}'),
    (TOTAL, r'(?i)\b(?:total|overall)\s+(?:ionic\s+)?conductivit(?:y|ies)\b'),
    (TOTAL, r'(?i)\bE\s*_?\s*a\s*[,_(\[]?\s*(?:tot|total)\b'),
    # A conductivity's subscript, as table headers write it: "σ tot", "σ_total" (not "σT": that is σ × T).
    (TOTAL, r'(?i)σ\s*_?\s*[,(\[]?\s*(?:tot|total)\b'),
    (TOTAL, r'(?i)\b(?:through-plane|conductivity\s+of\s+the\s+(?:entire|whole)\s+(?:pellet|sample))'),
    (TOTAL, r'(?i)\b(?:D_?eff|effective\s+diffusion\s+coefficient)\b'),
    # ---- grain boundary ----
    (GB, rf'(?i){_GB_WORD}\s*{_GAP_W}(?:{_Q}|{_EA})'),
    (GB, rf'(?i)(?:{_Q}|{_EA})\s+(?:of|at|across|in|for|through|along)\s+(?:the\s+)?{_GB_WORD}'),
    (GB, r'(?i)\bE\s*_?\s*(?:a|ac)\s*[,_(\[]?\s*(?:gb|g\.b\.)\b'),
    (GB, r'(?i)σ\s*_?\s*[,(\[]?\s*(?:gb|g\.b\.)\b'),
    (GB, r'\bR\s*_?\s*(?:gb|g\.b\.)\b'),
    (GB, rf'(?i)\b(?:across|between)\s+(?:the\s+)?(?:grains|{_GB_WORD})'),
    (GB, rf'(?i){_GB_WORD}\s+(?:space[\s-]charge|potential|blocking)\s+(?:layer|barrier)'),
    (GB, rf'(?i)\b(?:grain[\s-]*to[\s-]*grain)\s+{_Q}'),
    (GB, r'(?i)\b(?:intergranular|inter-granular)\b'),
    (GB, rf'(?i)\b(?:for|of|at)\s+(?:the\s+)?{_GB_WORD}'),
    # ---- surface ----
    (SURFACE, r'(?i)\bsurface[\s-]+(?:mediated\s+|controlled\s+)?(?:diffusion|transport|conduction|conductivity|migration|hopping|activation|barrier|E\s*_?\s*a|ionic|ion)\b'),
    (SURFACE, r'(?i)\bE\s*_?\s*(?:a|ac)\s*[,_(\[]?\s*(?:surf(?:ace)?|s)\b'),
    (SURFACE, r'(?i)\b(?:terrace|step[\s-]edge|step|interlayer\s+surface)\s+(?:diffusion|migration|hopping)'),
    (SURFACE, r'(?i)\b(?:on|along|across)\s+the\s+(?:\(\s*\d{3,4}\s*\)\s+|exposed\s+|crystal\s+)?surfaces?\b'),
    (SURFACE, r'(?i)\bon\s+the\s+\(\s*\d{3,4}\s*\)\s+(?:surface|facet)'),
    (SURFACE, r'(?i)\b(?:exposed\s+facets?|surface\s+termination)\b'),
    # ---- bulk ----
    (BULK, rf'(?i)\b(?:bulk(?!\s+(?:ceramic|powder|material|modulus|density|sample|synthes\w+))|intrinsic|lattice|crystal[\s-]lattice|grain[\s-]*interior|intra-?\s?granular|intra-?\s?grain)\s*{_GAP_W}(?:{_Q}|{_EA})'),
    (BULK, rf'(?i)(?:{_Q}|{_EA})\s+(?:of|in|through|within|inside)\s+(?:the\s+)?(?:bulk(?!\s+(?:modulus|density|ceramic|powder|material))|lattice|crystal\s+lattice|grain\s+interiors?|grains)\b'),
    (BULK, r'(?i)\b(?:through|within|in|inside)\s+the\s+(?:bulk\b(?!\s+(?:modulus|density|ceramic|powder))|(?:crystal\s+)?lattice\b|grain\s+interiors?\b|grains\b)'),
    (BULK, r'(?i)\bfor\s+(?:the\s+)?(?:bulk\b(?!\s+(?:modulus|density|ceramic|powder|material))|grain\s+interiors?\b)'),
    (BULK, r'(?i)\bE\s*_?\s*(?:a|ac)\s*[,_(\[]?\s*(?:b|bulk|gi|int)\b'),
    # "σ g": the grain (interior) of an impedance fit, as against "σ gb", its boundaries.
    (BULK, r'(?i)σ\s*_?\s*[,(\[]?\s*(?:b|bulk|g|gi|grain|int)\b'),
    (BULK, r'\bR\s*_\s*(?:b|bulk|gi)\b|\bR(?:bulk|gi)\b'),
    (BULK, r'(?i)\bhigh[\s-]frequency\s+(?:semicircle|arc)[^.;]{0,60}?\b(?:grain[\s-]interior|bulk)\b'),
    (BULK, r'(?i)\bsingle[\s-]crystal\s+(?:ionic\s+)?(?:conductivity|diffusion|ion\s+transport)\b'),
    (BULK, r'(?i)\bdiffusion\s+in\s+a\s+single[\s-]crystal\b'),
]
_PATTERNS: List[Tuple[str, re.Pattern]] = [(label, re.compile(p)) for label, p in _RAW]

# Several components named for one quantity — "the total and bulk conductivities are 0.4 and 2.5
# mS/cm", "the bulk and grain-boundary responses": each word is for one of the values that follow,
# so the phrase types none of them on its own.
_COMPONENT_WORDS: List[Tuple[str, str]] = [
    (TOTAL, r'total|overall'),
    (GB, _GB_WORD),
    (BULK, r'bulk|grain[\s-]*interior|intra-?\s?granular|intra-?\s?grain|lattice'),
]
_COMPONENT = '(?:' + '|'.join(words for _, words in _COMPONENT_WORDS) + ')'
_SEVERAL = re.compile(
    rf'(?i)(?<![\w-])({_COMPONENT}(?:\s*(?:,|/|&|\+|,?\s*and|,?\s*or)\s*(?:the\s+)?{_COMPONENT})+)\s+{_GAP_W}(?:{_Q}|{_EA})')

# "dominated by grain boundaries" says which part controls a total value; it does not type it.
_DOMINANCE = re.compile(
    rf'(?i)\b(?:dominat\w*|limit\w*|control\w*|govern\w*|determin\w*)\s+by\s+(?:the\s+)?'
    rf'(?P<dom>{_GB_WORD}|bulk|grain\s+interior|surface)')
_DOM_LABEL = {"bulk": BULK, "grain interior": BULK, "surface": SURFACE}

# Units that can carry each kind of transport value, keyed by normalizer category; used to find
# the sibling values in a sentence ("0.30 eV ... 0.45 eV", "1.2 mS cm−1 ... 0.3 mS cm−1").
_UNITS: Dict[str, str] = {
    "energy": r'(?:meV|eV|kJ\s*/?\s*mol|kcal\s*/?\s*mol)',
    "conductivity": r'(?:[mμµu]?S\s*[/·⋅]?\s*cm(?:\s?[-−–]\s?1)?)',
    "diffusion": r'(?:c?m\s*\^?2\s*[/·⋅]?\s*s(?:\s?[-−–]\s?1)?)',
}
VALUE_PATTERNS: Dict[str, re.Pattern] = {
    kind: re.compile(rf'(?i)\d+(?:\.\d+)?\s*(?:±\s*\d+(?:\.\d+)?\s*)?{units}') for kind, units in _UNITS.items()
}


# Sentence end: period after a word/closing bracket/number, then a capital (not "Fig. 4", "e.g. x").
_SENT_BREAK = re.compile(r'(?<=[A-Za-z0-9)\]%])\.\s+(?=[A-Z])')


@dataclass
class TransportResult:
    component: str = UNSPECIFIED
    evidence: str = "NONE"
    dominant: str = "NONE"


def _mask_spans(text: str, spans: Iterable[Tuple[int, int]]) -> str:
    out = list(text)
    for s, e in spans:
        for i in range(s, e):
            out[i] = " " if out[i] != "\n" else out[i]
    return "".join(out)


def own_segment(text: str, start: int, end: int,
                neighbors: Iterable[str] = ()) -> Tuple[str, int, int, Tuple[str, ...]]:
    """Narrows `text` to the sentence segment holding text[start:end].

    The upstream sentence splitter is not reliable on scientific text ("0.42 eV. Bulk ..."), so
    re-split here: only the segment holding the value is its own context, the rest are neighbours.
    Returns (segment, start, end, neighbors) with the offsets rebased onto the segment."""
    seg_start, seg_end, before, after = 0, len(text), "", ""
    for m in _SENT_BREAK.finditer(text):
        if m.end() <= start:
            before, seg_start = text[seg_start:m.start() + 1], m.end()
        elif m.start() >= end:
            after, seg_end = text[m.end():], m.start() + 1
            break
    if seg_start or seg_end != len(text):
        neighbors = (before, after, *neighbors)
    return text[seg_start:seg_end], start - seg_start, end - seg_start, tuple(neighbors)


def components_in_order(text: str, named_at: int, values_at: int) -> Tuple[List[str], str]:
    """The components a quantity is named for when it is named for several at once, in the order
    they are named, with the wording: "The total and bulk conductivities are ..." -> (["total",
    "bulk"], "total and bulk conductivities"). `named_at` is where the quantity is named and
    `values_at` where its values start; ([], "") when it is named for one component or none."""
    for m in _SEVERAL.finditer(text):
        if m.start() <= named_at <= m.end() <= values_at:
            words = re.finditer(rf'(?i){_COMPONENT}', m.group(1))
            return [next(label for label, pattern in _COMPONENT_WORDS if re.fullmatch(rf'(?i)(?:{pattern})', w.group()))
                    for w in words], m.group()
    return [], ""


def classify_transport(text: str, start: int = 0, end: int = 0,
                       neighbors: Iterable[str] = (), kind: str = "energy") -> TransportResult:
    """Types the transport value at text[start:end] from the wording tied to it.

    `kind` is the value's normalizer category ("energy" for E_a, "conductivity", "diffusion"): its
    siblings are the other values of that kind. Every qualifier is assigned to its nearest sibling
    in the sentence, so "bulk E_a = 0.30 eV and grain-boundary E_a = 0.45 eV" gives each value only
    its own qualifier. Qualifiers of two different components that are about equally close to the
    value are treated as ambiguous."""
    value = VALUE_PATTERNS.get(kind, VALUE_PATTERNS["energy"])
    text, start, end, neighbors = own_segment(text, start, end, neighbors)
    result = _classify_span(text, start, end, value=value)
    if result.component != UNSPECIFIED:
        return result
    # Nothing in the sentence itself: the component is often named in the adjacent sentence
    # ("Bulk transport was probed by EIS. The activation energy was 0.29 eV."). A neighbour only
    # counts if it holds no value of this kind of its own (its qualifier would belong to that
    # value) and names exactly one component.
    for nb in neighbors:
        if nb and not value.search(nb):
            nb_result = _classify_span(nb, 0, 0, whole=True, value=value)
            if nb_result.component != UNSPECIFIED:
                return nb_result
    return result


def _classify_span(text: str, start: int, end: int, whole: bool = False,
                   value: re.Pattern = VALUE_PATTERNS["energy"]) -> TransportResult:
    if not text:
        return TransportResult()
    end = max(end, start)
    others = [(m.start(), m.end()) for m in value.finditer(text)
              if not (m.start() < end and m.end() > start)]

    dominant_labels: List[str] = []
    dom_spans: List[Tuple[int, int]] = []
    for m in _DOMINANCE.finditer(text):
        dom = re.sub(r'[\s-]+', ' ', m.group("dom").lower())
        dominant_labels.append(GB if re.search(r'grain|gb|inter', dom) else _DOM_LABEL.get(dom, UNSPECIFIED))
        dom_spans.append(m.span())
    work = _mask_spans(text, dom_spans)
    # What "including both bulk and grain-boundary contributions" says is read as a whole (total);
    # the words of such a phrase one by one say nothing.
    single = _mask_spans(work, [m.span(1) for m in _SEVERAL.finditer(work)])

    def distance(s: int, e: int, a: int, b: int) -> int:
        return 0 if e > a and s < b else min(abs(e - a), abs(s - b))

    # (label, distance, start, end); a qualifier closer to a sibling value belongs to that one.
    hits: List[Tuple[str, int, int, int]] = []
    taken: List[Tuple[int, int]] = []  # spans already claimed by a stronger (earlier) pattern
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(work if label == TOTAL else single):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            d = 0 if whole else distance(s, e, start, end)
            if any(distance(s, e, os_, oe) < d for os_, oe in others):
                continue
            taken.append((s, e))
            hits.append((label, d, s, e))
    if not hits:
        return TransportResult()

    labels = {h[0] for h in hits}
    order = {GB: 0, SURFACE: 1, BULK: 2, TOTAL: 3}
    if TOTAL in labels and len(labels) > 1:
        # Combined/overall wording next to a component word ("total conductivity includes the
        # grain-boundary contribution") is still the total response.
        chosen = TOTAL
    elif len(labels) > 1:
        ranked = sorted(hits, key=lambda h: (h[1], order[h[0]]))
        nearest = ranked[0]
        rival = next((h for h in ranked if h[0] != nearest[0]), None)
        if rival is not None and rival[1] - nearest[1] < 30:
            return TransportResult()  # conflicting evidence: do not guess
        chosen = nearest[0]
    else:
        chosen = next(iter(labels))

    best = min((h for h in hits if h[0] == chosen), key=lambda h: h[1])
    q_start, q_end = min(best[2], start), max(best[3], end)
    evidence = text[q_start:q_end].strip()
    dominant = "NONE"
    if chosen == TOTAL and dominant_labels and UNSPECIFIED not in dominant_labels:
        dominant = dominant_labels[0]
    return TransportResult(chosen, evidence, dominant)


def classify_transport_contexts(contexts: Iterable[Optional[str]]) -> TransportResult:
    """Table cells: the first context (header, row label, caption) that establishes a component
    wins. The context's text itself is the evidence."""
    for ctx in contexts:
        if not ctx:
            continue
        result = classify_transport(ctx, 0, 0)
        if result.component != UNSPECIFIED:
            return result
    return TransportResult()
