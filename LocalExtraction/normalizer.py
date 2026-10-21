# LocalExtraction/normalizer.py

import re
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


# NFKC turns the macron of an overlined digit ("Fm¯3m", "P¯3m1") into a space and a combining
# overline, which no space-group reader recognises: it is the minus of "Fm-3m".
_OVERLINE = re.compile(r'(?<=[A-Za-z0-9])\s?[\u0304\u0305]\s?(?=\d)')
# The invisible hyphen a PDF leaves where it broke a word: a real one at a line break (the word
# is put back together by repair_hyphenation), nothing at all inside a line.
_SOFT_HYPHEN_AT_BREAK = re.compile(chr(0xAD) + r'(?=\s)')


# Some fonts print their multiplication sign as a "9": "1.6 9 10–3 S cm-1" is 1.6 × 10−3 S/cm.
_LOST_TIMES = re.compile(r'(?<=\d)\s9\s(?=10\s?[-−–]\s?\d)')


def normalize_scientific_text(text: str) -> str:
    """NFKC-normalizes text while preserving Greek letters, sub/superscripts, and symbols, and
    restores a minus sign the PDF's font lost (see _LOST_MINUS) or hid (_OVERLINE) and a
    multiplication sign it misprinted (_LOST_TIMES)."""
    if not text:
        return text
    text = _LOST_MINUS.sub(_UNICODE_MINUS, unicodedata.normalize("NFKC", text))
    text = _OVERLINE.sub("-", _SOFT_HYPHEN_AT_BREAK.sub("-", text)).replace(_SOFT_HYPHEN, "")
    return _LOST_TIMES.sub(" × ", text)


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
# Unit engine (schema section 14). Built once at import time and shared
# read-only across threads.
# ---------------------------------------------------------------------------
_ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
# pint's default registry already ships 'rydberg'/'Ry', 'hartree', 'Ah' and 'Wh' — only the
# common short alias 'Ha' for hartree is missing, so that's the only addition needed.
_ureg.define('@alias hartree = Ha')
Q_ = _ureg.Quantity

# Exact captured-unit-text -> pint-parseable unit string. Kept as an explicit lookup (rather
# than generic regex munging) since every possible unit token is enumerated in config.py's
# SCHEMA patterns and controlled by this same codebase.
UNIT_ALIASES = {
    'S/cm': 'S/cm', 'mS/cm': 'mS/cm', 'μS/cm': 'microsiemens/cm', 'uS/cm': 'microsiemens/cm',
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
            qty = Q_(num, pint_unit)
        except Exception:
            return "NONE"

        try:
            try:
                converted = qty.to(target)
            except pint.errors.DimensionalityError:
                # A molar energy ("31.2 kJ/mol") is the same quantity per mole of particles: one
                # activation energy column needs it in eV like every other.
                converted = (qty / _ureg.avogadro_constant).to(target)
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
