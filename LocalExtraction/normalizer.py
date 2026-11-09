# LocalExtraction/normalizer.py

import re
import threading
import unicodedata
from collections import Counter
from typing import List, Optional, Sequence, Tuple, Union

import pint

# ---------------------------------------------------------------------------
# Shared scientific-text normalization (schema sections 13 & 14). Used by
# parser.py, ocr.py, chemistry.py and this module so unicode minus signs,
# Greek letters, and compatibility glyphs are handled in exactly one place.
# ---------------------------------------------------------------------------
_UNICODE_MINUS = '−'  # −
_EN_DASH = '–'        # –
_EM_DASH = '—'        # —
_SOFT_HYPHEN = chr(0xAD)  # invisible; PDFs leave it where a line was hyphenated


# Some PDF fonts map their minus glyph to no real character, so the text carries a control
# character where a superscript minus was printed: "mS cm\x021" is mS cm−1 and "10\x014 S/cm" is
# 10−4 S/cm. Which control character differs from font to font; where it stands does not — right
# after a unit symbol and before its exponent, or between a bare "10" and its exponent.
_LOST_MINUS = re.compile(r'(?:(?<=[A-Za-zΩ])[\x00-\x08\x0b\x0c\x0e-\x1f](?=[1-3](?!\d))'
                         r'|(?<=(?<![\d.])10)[\x00-\x08\x0b\x0c\x0e-\x1f](?=\d))')
# The same fonts give their multiplication sign as a control character too: "1.15 \x03 10\x024 S cm\x021" is
# 1.15 × 10−4 S/cm. One standing alone between a number and a power of ten is that sign.
_CONTROL_TIMES = re.compile(r'(?<=\d)\s?[\x00-\x08\x0b\x0c\x0e-\x1f]\s?(?=10\s?[-−–]\s?\d)')


# NFKC turns the macron of an overlined digit ("Fm¯3m", "P¯3m1") into a space and a combining
# overline, which no space-group reader recognises: it is the minus of "Fm-3m".
_OVERLINE = re.compile(r'(?<=[A-Za-z0-9])\s?[\u0304\u0305]\s?(?=\d)')
# The invisible hyphen a PDF leaves where it broke a word: a real one at a line break (the word
# is put back together by repair_hyphenation), nothing at all inside a line.
_SOFT_HYPHEN_AT_BREAK = re.compile(chr(0xAD) + r'(?=\s)')


# Some fonts print their multiplication sign as a "9": "1.6 9 10–3 S cm-1" is 1.6 × 10−3 S/cm.
_LOST_TIMES = re.compile(r'(?<=\d)\s9\s(?=10\s?[-−–]\s?\d)')
# ... and others lose it altogether, leaving only a space: "7.0  10−9 S cm−1" is 7.0 × 10−9 S/cm, not 10−9.
# Only before the unit of a conductivity, a resistivity or a diffusion coefficient, and only after a number
# that stands on its own (not the subscript of a formula: "Li7La3Zr2O12 10−4" is no product).
_VANISHED_TIMES = re.compile(r'(?<![\w.,/^×·−–-])(\d+(?:\.\d+)?)\s{1,3}(?=10\s?[-−–]\s?\d{1,2}(?!\d)\s?'
                             r'(?:[mμµ]?S\b|Ω|ohm|cm\s?2|cm²|m\s?2\b|m²))')


# Subscripts that a PDF's text layer gives as separate words: "Na 3 PSe 4", "Li 6.4 La 3 Zr 1.4 Ta 0.6 O 12",
# "Li 6 PS 5 Cl", "Li 1.3 Al 0.3 Ti 1.7 (PO 4 ) 3". Read as they stand, "PSe" would be taken for the
# material. A run of at least two element groups each followed by its subscript (a bracketed group
# too, and, last, a group without one) is put back together.
_GROUP = r'(?:[A-Z][a-z]?){1,4}'
_SUBSCRIPT = r'\d{1,2}(?:\.\d{1,3})?'
_UNIT = rf'(?:{_GROUP} {_SUBSCRIPT}|\( ?{_GROUP} ?{_SUBSCRIPT}?(?: {_GROUP} {_SUBSCRIPT})* ?\) ?{_SUBSCRIPT})'
_SPACED_FORMULA = re.compile(rf'(?<![\w.,/−–-])(?<![A-Za-z0-9]\()({_UNIT}(?: ?{_UNIT})+)(?: ({_GROUP}))?(?![\w.−–/-]*\w)')
# One group and its subscript ("LiNbO 3", "BaTiO 3"): only a group of two or more symbols with a two-letter one
# among them, so "S 2", "K 2" or an acronym ("SI 2", "BCC 2") stay as they are.
_SPACED_SINGLE = re.compile(rf'(?<![\w.,/−–-])(?<![A-Za-z0-9]\()((?:[A-Z][a-z]?){{2,4}}) ({_SUBSCRIPT})(?![\w.−–/-]*\w)')
# A number followed by a unit is a quantity, not a subscript: "LiPON 2 µm", "SnO 2 wt%".
_UNIT_AFTER = re.compile(r'\s?(?:[nµμu]?m|mm|cm|nm|wt|vol|mol|at\.?|h|min|K|°|%|mAh|mV|V|GPa|MPa)(?![A-Za-z])')
_SYMBOL_SET = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
    "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu".split())
# A trailing group that is also an English word is the next word, not the end of the formula.
_WORDS_LIKE_SYMBOLS = frozenset({"In", "As", "At", "No", "I", "He", "Be", "Am", "Ce", "Co", "Ho", "Pa", "Ti"})


def _is_element_group(group: str) -> bool:
    """"PSe" = P + Se, "GeP" = Ge + P; "Ab" is no element."""
    parts = re.findall(r'[A-Z][a-z]?', group)
    return "".join(parts) == group and all(part in _SYMBOL_SET for part in parts)


# The inside of a formula's bracket the run cannot be joined in whole: "Li(Ni 0.8 Co 0.1 Mn 0.1 )O 2".
_IN_FORMULA_BRACKET = re.compile(rf'[A-Za-z0-9]\(\s?(?:{_GROUP} {_SUBSCRIPT} ?)*$')


def _in_formula_bracket(match: "re.Match") -> bool:
    return bool(_IN_FORMULA_BRACKET.search(match.string, max(0, match.start() - 80), match.start()))


def _join_formula(match: "re.Match") -> str:
    run, tail = match.group(1), match.group(2)
    if not all(_is_element_group(g) for g in re.findall(r'[A-Za-z]+', run)) or _in_formula_bracket(match):
        return match.group(0)
    if not tail and _UNIT_AFTER.match(match.string, match.end()):
        return match.group(0)
    joined = run.replace(" ", "")
    if tail:
        if _is_element_group(tail) and tail not in _WORDS_LIKE_SYMBOLS:
            return joined + tail
        return joined + " " + tail
    return joined


def _join_single(match: "re.Match") -> str:
    group = match.group(1)
    if (_is_element_group(group) and any(c.islower() for c in group)
            and not _UNIT_AFTER.match(match.string, match.end()) and not _in_formula_bracket(match)):
        return group + match.group(2)
    return match.group(0)


def join_spaced_formulas(text: str) -> str:
    """"The Na 3 PSe 4 phase" -> "The Na3PSe4 phase", "a LiNbO 3 coating" -> "a LiNbO3 coating"
    (see _SPACED_FORMULA, _SPACED_SINGLE)."""
    if not text or " " not in text:
        return text
    return _SPACED_SINGLE.sub(_join_single, _SPACED_FORMULA.sub(_join_formula, text))


# Some publishers' symbol fonts (Wiley-VCH, 1990s–2010s) come out of the PDF as other letters: the
# times sign as "Õ", the minus as "¢", Ω as "W". "2.9Õ10¢9 W¢1cm¢1" is 2.9 × 10−9 Ω−1 cm−1. Only these
# places are mended: between a number and its power of ten, and in an exponent of a unit.
_SYMBOL_TIMES = re.compile(r'(?<=\d)\s?Õ\s?(?=10[¢−-]?\d)')
_SYMBOL_MINUS = re.compile(r'(?:(?<=\b10)|(?<=[A-Za-zΩ]))¢(?=[1-9](?!\d))')
_SYMBOL_OHM = re.compile(r'\bW(?=−1\s?(?:cm|m)\b)')
# A conductivity in inverse ohms is one in siemens: "Ω−1 cm−1", "(Ω cm)−1", "ohm-1 cm-1", "mho/cm" → "S cm−1".
_INVERSE_OHM = re.compile(
    r'(?:(?:Ω|ohm)\s?[−-]\s?1\s?(?:·\s?)?(c?m)\s?[−-]\s?1'
    r'|\(\s?(?:Ω|ohm)\s?(?:·\s?)?(c?m)\s?\)\s?[−-]\s?1'
    r'|\bmhos?\s?(?:/\s?(c?m)\b|(c?m)\s?[−-]\s?1))')


def _siemens(match: "re.Match") -> str:
    length = next(g for g in match.groups() if g)
    return f"S {length}−1"


def mend_units(text: str) -> str:
    """The symbol-font letters of a value put back (_SYMBOL_TIMES …), and inverse ohms written as siemens."""
    if "Õ" in text or "¢" in text:
        text = _SYMBOL_OHM.sub("Ω", _SYMBOL_MINUS.sub("−", _SYMBOL_TIMES.sub(" × ", text)))
    if "Ω" in text or "ohm" in text or "mho" in text:
        text = _INVERSE_OHM.sub(_siemens, text)
    return text


def normalize_scientific_text(text: str) -> str:
    """NFKC-normalizes text while preserving Greek letters, sub/superscripts, and symbols, and
    restores a minus sign the PDF's font lost (see _LOST_MINUS) or hid (_OVERLINE), a
    multiplication sign it misprinted (_LOST_TIMES, _CONTROL_TIMES) or lost (_VANISHED_TIMES) and the formulas whose subscripts it set apart
    (_SPACED_FORMULA)."""
    if not text:
        return text
    text = _LOST_MINUS.sub(_UNICODE_MINUS, unicodedata.normalize("NFKC", text))
    text = _CONTROL_TIMES.sub(" × ", text)
    text = _OVERLINE.sub("-", _SOFT_HYPHEN_AT_BREAK.sub("-", text)).replace(_SOFT_HYPHEN, "")
    text = _VANISHED_TIMES.sub(r"\1 × ", _LOST_TIMES.sub(" × ", text))
    return join_spaced_formulas(mend_units(text))


# A word a line break split in two, as the parser's joined lines show it: "activa- tion",
# "temperature- dependent", "Li- ion". (In running text nothing else looks like this except a
# suspended hyphen, "Li- and Na-ion", which _SUSPENDED recognises.)
_BROKEN_WORD = re.compile(r'(?<![\w-])([A-Za-z]{2,})-\s+([a-z]{2,})(?![\w])')
_SUSPENDED = {"and", "or", "to", "nor", "versus", "vs", "as", "but", "than", "through", "into", "from", "in",
              "of", "with", "by", "for", "on", "at", "is", "are", "was", "were", "the"}
_PLAIN_WORD = re.compile(r'[A-Za-z]{2,}')


def repair_hyphenation(texts: Sequence[str]) -> List[str]:
    """Puts back together the words that line breaks split: "activa- tion barrier" would otherwise
    hide an activation barrier from every pattern. Whether the hyphen was the printer's or the
    author's is read off the rest of the document: "activation" is a word it uses, so the pieces
    are joined; "temperaturedependent" is not but "temperature" is, so the hyphen stays
    ("temperature-dependent"). Pass all the texts of one document together."""
    vocabulary = Counter(word.lower() for text in texts for word in _PLAIN_WORD.findall(_BROKEN_WORD.sub(" ", text)))

    def join(match: "re.Match") -> str:
        head, tail = match.group(1), match.group(2)
        if tail in _SUSPENDED:
            return match.group(0)
        if vocabulary[(head + tail).lower()]:
            return head + tail
        # A first half that is a word of its own ("temperature- dependent", not "activa- tion").
        if vocabulary[head.lower()] and (vocabulary[tail] or len(head) >= 4):
            return f"{head}-{tail}"
        return head + tail

    return [_BROKEN_WORD.sub(join, text) for text in texts]


def _fold_number(raw: str) -> str:
    """The captured number text with every dash as an ASCII hyphen and no spaces."""
    s = str(raw).strip().replace(_UNICODE_MINUS, '-').replace(_EN_DASH, '-').replace(_EM_DASH, '-')
    return s.replace(' ', '')


# A power of ten printed without a coefficient: "10-4" (the superscript is lost in PDF text),
# "10^-4", "10^4". A plain "104" never gets here — it parses as a number first.
_BARE_POWER = re.compile(r'^10\^?(-?\d+)$')
# "5.10-9": a point where the multiplication sign was.
_POINT_FOR_TIMES = re.compile(r'^(\d+(?:\.\d+)?)\.10\^?(-\d{1,2})$')
# ... which, without a caret and with two digits, is written exactly like a range ("10-20").
_RANGE_LIKE = re.compile(r'^10-(\d{2})$')


def _parse_scientific_number(raw: str) -> Optional[float]:
    """Parses '1.2', '1.2e-3', '1.2x10^-3', '1.2×10−3' (incl. unicode minus) and a bare power
    of ten ('10−4', '10^-4') into a float."""
    if raw is None:
        return None
    s = _fold_number(raw)
    m = re.match(r'^([+-]?\d*\.?\d+)(?:[eE]([+-]?\d+)|[xX×\*·⋅]10\^?([+-]?\d+))?$', s)
    if not m:
        power, pointed = _BARE_POWER.match(s), _POINT_FOR_TIMES.match(s)
        try:
            if pointed:
                return float(pointed.group(1)) * 10.0 ** int(pointed.group(2))
            return 10.0 ** int(power.group(1)) if power else None
        except OverflowError:
            return None
    try:
        coeff = float(m.group(1))
    except ValueError:
        return None
    exponent = m.group(2) or m.group(3)
    if exponent:
        coeff *= 10.0 ** int(exponent)
    return coeff


def _readings(raw: str) -> List[float]:
    """The values a captured number can stand for, most likely first. Only a bare "10−NN" has two:
    a power of ten ("10−12 cm2/s") or the upper end of a range ("10–20 mS/cm"). The caller keeps
    the first one that is physically valid, so the power wins whenever it is possible at all."""
    num = _parse_scientific_number(raw)
    if num is None:
        return []
    range_like = _RANGE_LIKE.match(_fold_number(raw))
    return [num, float(range_like.group(1))] if range_like else [num]


# ---------------------------------------------------------------------------
# Unit engine (schema section 14). Built once, on first use (it takes ~0.4 s: not when a window
# opens), and shared read-only across threads.
# ---------------------------------------------------------------------------
_REGISTRY = None
_REGISTRY_LOCK = threading.Lock()


def _units() -> "pint.UnitRegistry":
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            registry = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
            # pint's default registry already ships 'rydberg'/'Ry', 'hartree', 'Ah' and 'Wh' — only the
            # common short alias 'Ha' for hartree is missing, so that's the only addition needed.
            registry.define('@alias hartree = Ha')
            _REGISTRY = registry
    return _REGISTRY

# Exact captured-unit-text -> pint-parseable unit string. Kept as an explicit lookup (rather
# than generic regex munging) since every possible unit token is enumerated in config.py's
# SCHEMA patterns and controlled by this same codebase.
UNIT_ALIASES = {
    'S/cm': 'S/cm', 'mS/cm': 'mS/cm', 'μS/cm': 'microsiemens/cm', 'uS/cm': 'microsiemens/cm',
    'S/m': 'S/m', 'mS/m': 'mS/m', 'μS/m': 'microsiemens/m', 'uS/m': 'microsiemens/m', 'µS/m': 'microsiemens/m',
    'cm2/s': 'cm**2/s', 'cm^2/s': 'cm**2/s', 'cm2/?s': 'cm**2/s', 'm2/s': 'm**2/s', 'm^2/s': 'm**2/s',
    'eV': 'eV', 'meV': 'meV', 'eV/atom': 'eV', 'meV/atom': 'meV', 'eV/f.u.': 'eV',
    'Ry': 'Ry', 'Ha': 'Ha', 'kJ/mol': 'kJ/mol', 'kcal/mol': 'kcal/mol',
    'V': 'V', 'mV': 'mV',
    'mAh/g': 'mAh/g', 'Ah/kg': 'Ah/kg', 'mAh/cm2': 'mAh/cm**2',
    'Wh/kg': 'Wh/kg', 'Wh/L': 'Wh/L', 'kWh/kg': 'kWh/kg',
    'W/kg': 'W/kg', 'kW/kg': 'kW/kg',
    'mA/cm2': 'mA/cm**2', 'A/cm2': 'A/cm**2', 'mA/g': 'mA/g', 'A/g': 'A/g',
    'GPa': 'GPa', 'MPa': 'MPa', 'bar': 'bar', 'atm': 'atm',
    'Å': 'angstrom', 'Angstrom': 'angstrom', 'nm': 'nm', 'pm': 'pm',
    'Å3': 'angstrom**3', 'Å^3': 'angstrom**3', 'nm3': 'nm**3',
    'g/cm3': 'g/cm**3', 'kg/m3': 'kg/m**3', 'g/cc': 'g/cm**3',
    'K': 'kelvin', '°C': 'degC', 'C': 'degC',
    'ps': 'ps', 'ns': 'ns', 'fs': 'fs',
    'h': 'hour', 'hours': 'hour', 'min': 'minute', 'minutes': 'minute',
    'cm-1': 'cm**-1', 'cm^-1': 'cm**-1',
    '°': 'degree', 'deg': 'degree', 'degrees': 'degree',
    'W/mK': 'W/m/K', 'W/m/K': 'W/m/K', 'W/(m·K)': 'W/m/K',
    'ohm cm2': 'ohm*cm**2', 'Ω cm2': 'ohm*cm**2', 'Ω⋅cm2': 'ohm*cm**2', 'ohm*cm2': 'ohm*cm**2',
    'J/m2': 'J/m**2', 'eV/Å2': 'eV/angstrom**2', 'eV/A2': 'eV/angstrom**2',
    '%': 'percent', 'percent': 'percent',
}


def _canonical_unit(unit: str) -> str:
    """Folds the ways a unit is printed onto the spelling UNIT_ALIASES is keyed by.

    NFKC-normalization turns superscript minus signs (cm⁻¹) into the unicode minus U+2212, and
    PDF text also uses an en dash there — every UNIT_ALIASES key uses a plain hyphen ("cm-1").
    A "per" unit comes as "mS/cm", "mS / cm", "mS cm−1", "mS·cm–1", "mS cm^-1" or — where the PDF
    dropped the minus sign — "mS cm1": all of them are "mS/cm"."""
    unit = normalize_scientific_text(unit).replace(_SOFT_HYPHEN, '').strip()
    for dash in (_UNICODE_MINUS, _EN_DASH, _EM_DASH):
        unit = unit.replace(dash, '-')
    unit = re.sub(r'\s*/\s*|\s+per\s+', '/', unit)
    # Two unit symbols with a separator between them, so a lone "cm-1" (a wavenumber) is kept.
    unit = re.sub(r'^(\S+?)(?:\s*[·⋅.]\s*|\s+)([A-Za-z]+)\s*\^?\s*-?\s*1$', r'\1/\2', unit)
    return re.sub(r'/sec$', '/s', unit)


# Canonical per-category output unit (a valid pint unit expression).
CANONICAL_UNITS = {
    'energy': 'eV', 'energy_large': 'eV', 'conductivity': 'S/cm', 'diffusion': 'cm**2/s', 'voltage': 'V',
    'capacity': 'mAh/g', 'energy_density': 'Wh/kg', 'power_density': 'W/kg',
    'current_density': 'mA/cm**2', 'area_resistance': 'ohm*cm**2', 'pressure': 'GPa',
    'length': 'angstrom', 'volume': 'angstrom**3', 'density': 'g/cm**3',
    'temperature': 'kelvin', 'time': 'ps', 'wavenumber': 'cm**-1', 'angle': 'degree',
    'thermal_conductivity': 'W/m/K', 'surface_energy': 'J/m**2',
}

# (min, max) physical-validation bounds, expressed in the category's canonical unit.
BOUNDS = {
    # 'energy' covers physically small quantities (activation energy, band gap, formation
    # energy, ...); 'energy_large' covers DFT numerical-parameter energies (plane-wave cutoffs,
    # SCF thresholds), which routinely run into the hundreds of eV — a genuinely different scale
    # that would otherwise get wrongly rejected by the tight 'energy' bound.
    'energy': (-10.0, 10.0), 'energy_large': (0.0, 5000.0),
    # Down to the poorest conductors a paper compares with ("10−13 S cm−1" for Li2S, "10−31 S cm−1"
    # for the electronic conductivity of LiF).
    'conductivity': (1e-35, 100.0), 'diffusion': (1e-30, 1e-3),
    'voltage': (0.0, 10.0), 'capacity': (0.0, 5000.0), 'energy_density': (0.0, 2000.0),
    'power_density': (0.0, 100000.0), 'current_density': (0.0, 10000.0),
    'area_resistance': (0.0, 1e7), 'pressure': (-50.0, 1000.0), 'length': (0.0, 1e7),
    'volume': (0.0, 1e7), 'density': (0.0, 30.0), 'temperature': (0.0, 4000.0),
    'time': (0.0, 1e9), 'wavenumber': (0.0, 5000.0), 'angle': (0.0, 180.0),
    'thermal_conductivity': (0.0, 3000.0), 'surface_energy': (0.0, 20.0),
    'percent': (0.0, 150.0), 'count': (0.0, 1e9), 'dimensionless': (-1e6, 1e6),
}


class DataNormalizer:
    """Generic pint-backed unit normalization + physical validation.

    `normalize(raw_match, norm_type)` keeps the exact call signature already used across the
    codebase (extractor passes `match.groups()` or `match.group()`); `norm_type` now names a
    physical category resolved dynamically through pint rather than a hand-written per-type
    branch, so adding a new unit is a one-line addition to UNIT_ALIASES, not a new code path.
    """

    @classmethod
    def normalize(cls, raw_match: Union[Tuple, str], norm_type: str) -> str:
        if not raw_match:
            return "NONE"

        if norm_type == 'string':
            value = raw_match[0] if isinstance(raw_match, tuple) else raw_match
            value = normalize_scientific_text(str(value)).strip()
            return value if value else "NONE"

        if not isinstance(raw_match, tuple) or len(raw_match) < 1:
            return "NONE"

        value_str = raw_match[0]
        unit_str = raw_match[1] if len(raw_match) > 1 and raw_match[1] else ""
        readings = _readings(value_str)
        if len(readings) == 2 and norm_type in ('conductivity', 'diffusion'):
            # "10–20 mS/cm" is a range: nobody writes a power of ten that small in millisiemens.
            # "10−13 S/cm" is a power of ten: no solid conducts 13 S/cm.
            readings = readings[::-1] if re.match(r'\s*[mμµu]S', unit_str) else readings[:1]
        for num in readings:
            normalized = cls._convert(num, unit_str, norm_type)
            if normalized != "NONE":
                return normalized
        return "NONE"

    @staticmethod
    def _convert(num: float, unit_str: str, norm_type: str) -> str:
        """One numeric reading of a value -> "<value> <canonical unit>", or "NONE" if it is not
        a physically valid quantity of that category."""
        if norm_type in ('count', 'dimensionless'):
            lo, hi = BOUNDS[norm_type]
            if not (lo <= num <= hi):
                return "NONE"
            return f"{num:g}"

        if norm_type == 'percent':
            lo, hi = BOUNDS['percent']
            if not (lo <= num <= hi):
                return "NONE"
            return f"{num:.2f} %"

        if norm_type not in CANONICAL_UNITS:
            return "NONE"

        unit_str = _canonical_unit(unit_str)
        pint_unit = UNIT_ALIASES.get(unit_str, unit_str)
        if not pint_unit:
            return "NONE"

        target = CANONICAL_UNITS[norm_type]
        try:
            qty = _units().Quantity(num, pint_unit)
        except Exception:
            return "NONE"

        try:
            try:
                converted = qty.to(target)
            except pint.errors.DimensionalityError:
                # A molar energy ("31.2 kJ/mol") is the same quantity per mole of particles: one
                # activation energy column needs it in eV like every other.
                converted = (qty / _units().avogadro_constant).to(target)
            out_val, out_unit = converted.magnitude, target
            lo, hi = BOUNDS[norm_type]
            if not (lo <= out_val <= hi):
                return "NONE"
        except pint.errors.DimensionalityError:
            # Same category but incompatible dimension (e.g. areal vs. gravimetric capacity) —
            # keep the pint-validated original unit instead of silently dropping the value.
            if not (num == num and abs(num) < float('inf')):  # NaN/inf guard
                return "NONE"
            out_val, out_unit = qty.magnitude, pint_unit
        except Exception:
            return "NONE"

        return f"{out_val:.4g} {out_unit}"

    @staticmethod
    def parse_number(raw: str) -> Optional[float]:
        """Public helper for other modules (e.g. chemistry.py) needing plain numeric parsing."""
        return _parse_scientific_number(raw)
