# study.py
"""What a paper states once, for all of its values.

A value's own sentence usually leaves its context out. A paper says in its methods that the
impedance was measured from 25 to 100 °C, or that every result comes from AIMD runs at 600-1200 K,
and then quotes activation energies without repeating any of it; whether a number was measured or
computed is often clear only from the kind of paper it is. `Study` reads those paper-wide facts
once. extractor.py turns to it for a value whose sentence, paragraph and figure caption are silent,
and records that the answer came from the paper as a whole (the value's `basis`).
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from context import (AMBIENT_PRESSURE, EXPERIMENTAL, ROOM_TEMPERATURE, SIMULATION, UNSPECIFIED, comparison_clauses,
                     pressure_point, temperature_range)

BOTH = "both"

_SENTENCE_BREAK = re.compile(r'(?<=[A-Za-z0-9)\]%])\.\s+(?=[A-Z])')

# The vocabulary of doing a calculation and of doing an experiment. Counted over the whole paper
# they tell what kind of study it is; a paper of one kind mentions the other in passing at most.
_SIMULATION_WORK = re.compile(
    r'(?i:\b(?:density[\s-]functional|first[\s-]principles?|ab[\s-]initio|molecular[\s-]dynamics|'
    r'nudged[\s-]elastic[\s-]band|force[\s-]fields?|interatomic[\s-]potentials?|supercells?|pseudopotentials?|'
    r'exchange[\s-]correlation|plane[\s-]wave|k[\s-]points?|thermostat|bond[\s-]valence|monte[\s-]carlo)\b)'
    r'|\b(?:DFT|AIMD|VASP|NEB|MLIPs?|MLFFs?|kMC|BVSE|LAMMPS|NVT|NPT|PBE)\b')
_EXPERIMENTAL_WORK = re.compile(
    r'(?i:\b(?:synthesi[sz]ed|sintered|sintering|calcined|calcination|annealed|ball[\s-]mill\w*|pellets?|'
    r'precursors?|stoichiometric\s+amounts?|as[\s-]prepared|glove\s?box|impedance|potentiostat|diffractometer|'
    r'blocking\s+electrodes?|purchased|sigma[\s-]aldrich|alfa\s+aesar|furnace|crucible|quartz\s+tubes?|'
    r'cold[\s-]pressed|hot[\s-]pressed|sputter\w*|spin[\s-]coat\w*|coin\s+cells?)\b)'
    r'|\b(?:EIS|XRD|SEM|TEM|XPS|NMR|TGA|DSC)\b')
# A paper of one kind may use this fraction of the other kind's vocabulary; and it takes this many
# words to call a paper anything.
_PASSING_SHARE = 0.12
_ENOUGH_WORDS = 5

_REVIEW_TITLE = re.compile(
    r'(?i)\b(?:reviews?|perspectives?|progress|advances|overview|roadmap|outlook|survey|prospects|'
    r'recent\s+developments?|state[\s-]of[\s-]the[\s-]art)\b')
_THIS_REVIEW = re.compile(r'(?i)\b(?:this|the\s+present|in\s+this)\s+(?:mini[\s-]?)?(?:review|perspective|overview|survey)\b')

# A study of interfaces computes grain boundaries and surfaces too: its values are not bulk by default.
_INTERFACE = re.compile(r'(?i)\bgrain[\s-]boundar(?:y|ies)\b|\bGBs?\b|\bsurfaces?\b|\binterfac\w+|\bslabs?\b'
                        r'|\bheterostructures?\b|\bthin[\s-]films?\b')
_GRAIN_BOUNDARY = re.compile(r'(?i)\bgrain[\s-]boundar(?:y|ies)\b|\bGBs?\b')
_MANY_GRAIN_BOUNDARIES = 10
# This many references and more is the bibliography of a review.
_MANY_REFERENCES = 150
# A method named this often is one the paper uses, not one it mentions.
_A_FEW_MENTIONS = 3

# How a value was obtained, as far as it decides what the value means.
STATIC, DYNAMIC, LOCAL_PROBE, IMPEDANCE = "static", "dynamic", "local probe", "impedance"
_TECHNIQUES = (
    (STATIC, re.compile(r'(?i:\bnudged[\s-]elastic[\s-]band\b|\bbond[\s-]valence\b|\bclimbing[\s-]image\b)'
                        r'|\b(?:NEB|CI-NEB|BVSE|BVEL)\b')),
    (DYNAMIC, re.compile(r'(?i:\bmolecular[\s-]dynamics\b|\bmean[\s-]squared?[\s-]displacements?\b|\btrajector\w+)'
                         r'|\b(?:AIMD|FPMD|MD|MSD|MLMD|kMC)\b')),
    (LOCAL_PROBE, re.compile(r'(?i:\bnuclear\s+magnetic\b|\bspin[\s-]lattice\b|\bquasi[\s-]?elastic\b|\bmuon\b)'
                             r'|\b(?:NMR|PFG|QENS|μSR)\b')),
    (IMPEDANCE, re.compile(r'(?i:\bimpedance\b|\bnyquist\b|\bblocking\s+electrodes?\b)|\bEIS\b')),
)

# The conditions of the paper's own work, as its methods state them.
_SIMULATION_RUN = re.compile(r'(?i:\b(?:molecular[\s-]dynamics|simulat(?:ions?|ed)|thermostat)\b)'
                             r'|\b(?:AIMD|FPMD|MD|MLMD|NVT|NPT|NpT|kMC)\b')
_COMPUTED = re.compile(r'(?i:\b(?:calculat\w+|comput\w+|predict\w+|theoretical\w*|first[\s-]principles)\b)|\bDFT\b')
# ... not the steps of a melt-quench or annealing protocol, and what the runs were for.
_PROTOCOL = re.compile(r'(?i)\b(?:melt\w*|quench\w*|cool(?:ed|ing)|heat(?:ed|ing)|anneal\w*|equilibrat\w+)\b')
_TRANSPORT = re.compile(r'(?i:\b(?:diffusi\w+|conductivit(?:y|ies)|arrhenius|activation|mean[\s-]squared?[\s-]displacements?|'
                        r'ion(?:ic)?\s+transport|migration)\b)|\bMSD\b')
# A statement about measuring ion transport: it names the technique, or says the conductivity was
# measured. An Arrhenius plot alone does not say so — molecular dynamics gives one too.
_TRANSPORT_MEASUREMENT = re.compile(
    r'(?i:\b(?:impedance|nyquist|resistance\s+measurements?)\b)|\b(?:EIS|NMR|PFG)\b'
    r'|(?i:\bconductivit(?:y|ies)\b.{0,80}?\b(?:measur\w+|determin\w+|characteri[sz]\w+|record\w+|collect\w+|studied)\b'
    r'|\b(?:measur\w+|determin\w+|characteri[sz]\w+|record\w+|collect\w+|studied)\b.{0,80}?\bconductivit(?:y|ies)\b)')
_ARRHENIUS = re.compile(r'(?i)\barrhenius\b')
_EXTRAPOLATED = re.compile(r'(?i)\bextrapolat\w+|\bfrom\s+high(?:er)?\s+temperatures?\b')
_IMPEDANCE_MEASUREMENT = re.compile(r'(?i:\b(?:impedance|nyquist)\b)|\bEIS\b')
_OTHER_MEASUREMENT = re.compile(
    r'(?i:\b(?:sinter\w*|calcin\w*|anneal\w*|synthesi\w+|heat[\s-]treat\w*|dr(?:ied|ying)|melt\w*|quench\w*|'
    r'mill\w*|diffract\w+|thermogravimetr\w+|calorimetr\w+|decompos\w+|cycl(?:ed|ing)|transitions?)\b)|\b(?:XRD|TGA|DSC|XPS)\b')
# Runs made to fit or test a potential, and collections of other people's data, are not the paper's results.
_NOT_A_RESULT_RUN = re.compile(
    r'(?i)\b(?:train\w*|datasets?|databases?|configurations?|phase\s+space|validat\w+|benchmark\w*|'
    r'fine[\s-]tun\w+|active[\s-]learning)\b|\bPES\b')
_RUN_VERB = re.compile(r'(?i)\b(?:performed|carried\s+out|conducted|run|ran|simulated)\b')
# A set of temperatures is the span of a fit when it is at least this wide; and molecular dynamics
# for ion transport is not run colder or hotter than this.
_SPAN = 20.0
_SIMULATED_BETWEEN = (100.0, 3000.0)
# The pressure a measurement was made under: said of the measurement itself, never of how the
# pellet was made ("cold-pressed at 370 MPa", "sintered under 100 MPa", "94% dense under 300 MPa").
_PRESSURE_OF_MEASUREMENT = re.compile(
    r'(?i:\b(?:impedance|conductivity)\s+(?:\w+\s+)?(?:measurements?|experiments?|data|spectra)\b'
    r'|\b(?:measurements?|experiments?|data|spectra)\s+(?:were|was)\s+(?:all\s+)?(?:performed|carried|conducted|made|'
    r'recorded|collected|taken)\b|\b(?:during|throughout)\s+(?:the\s+)?(?:\w+\s+)?measurements?\b)|\bEIS\b')
_FABRICATION = re.compile(
    r'(?i)\b(?:(?:\w+-)?press(?:ed|ing)|pelleti[sz]\w*|compact\w*|compress\w*|densif\w*|dense|consolidat\w*|'
    r'sinter\w*|treat(?:ed|ments?)|uniaxial\w*|isostatic\w*|cycl(?:ed|ing)|assembl\w+|deposit\w+)\b')
_DURING_MEASUREMENT = re.compile(r'(?i)\b(?:during|throughout)\s+(?:the\s+)?(?:\w+\s+)?(?:measurements?|EIS|impedance)\b')
_BAROSTAT = re.compile(r'(?i:\bbarostat\b)|\b(?:NPT|NpT)\b')
_NUMERIC_PRESSURE = re.compile(r'\d+(?:\.\d+)?\s?(?:GPa|MPa|kbar)\b')
# With this many different pressures in a paper, pressure is one of its variables: nothing is assumed.
_PRESSURE_IS_A_VARIABLE = 4

# A sentence about somebody else's result: "Kamaya et al. reported ...", "... of 12 mS/cm [5]",
# "(Wang et al., 2024)", "their study proposed ...", a superscript citation run into a word, a
# unit or a bracket ("conductors.9", "coworkers1", "0.40 eV40.", "(σRT = 1 mS/cm, Ea = 0.3 eV)3,").
_QUOTED = re.compile(
    r'(?i:\bet\s+al\b|\bref(?:s|erences?)?\.?\s*\[?\d|\bliterature\b|\belsewhere\b|\bpublished\s+(?:values?|data|results?)'
    r'|\b(?:previous(?:ly)?|earlier|prior)\s+(?:\w+\s+)?(?:works?|stud(?:y|ies)|reports?|reported|experiments?|calculations?)'
    r'|\b(?:their|the\s+authors\W?|these\s+authors\W?)\s+(?:\w+\s+)?(?:study|work|results?|calculations?|reports?|measurements?)'
    r'|\bthey\s+(?:also\s+)?(?:reported|found|showed|proposed|demonstrated|observed|obtained|calculated|measured)'
    r'|\breported\b(?!\s+(?:in\s+)?(?:here|this|table|fig)))'
    r'|\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\]|\(\s?[A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s+(?:19|20)\d{2}[a-z]?\s?\)'
    r'|[a-z]{4,}\.?\d{1,3}(?:[,–-]\s?\d{1,3})*(?=[\s,.;)]|$)'
    r'|\beV\d{1,3}(?=[\s,.;)]|$)|\([^()]*\s[^()]*\)\d{1,3}(?:\s?[,–-]\s?\d{1,3})*(?=[\s,.;]|$)'
    r'|(?i:\b(?:has|have)\s+(?:also\s+)?been\s+(?:studied|reported|investigated|explored|shown|demonstrated|proposed)\b)')
_OWN_WORK = re.compile(r'(?i)\b(?:in\s+this\s+(?:work|study|paper|letter|article|contribution)|here(?:in)?,?\s+we|'
                       r'we\s+(?:report|find|found|obtain\w*|measure\w*|calculate\w*|comput\w+|predict\w*|observe\w*|'
                       r'synthesi[sz]ed|prepared|show|demonstrate\w*)|our\s+(?:\w+\s+)?(?:results?|calculations?|'
                       r'measurements?|simulations?|samples?|work|study))\b')

# Panels of a figure caption: "(a) Nyquist plots ... (b) Arrhenius plots ...", "a Nyquist plots.
# b Arrhenius plots." — or, the other way round, "Nyquist plots (a) and Arrhenius plots (b)".
_PANEL_MARK = re.compile(r'(?<![A-Za-z0-9])\(?([a-h])\)(?=[\s,.;:])|(?<=[.|:]\s)([a-h])(?=\s+[A-Z(])')
_CITED = re.compile(r'(?i)^(figure|table)\s+(s?\d+|[ivx]+)([a-z]?)$')


@dataclass
class Stated:
    """A condition and the statement of the paper it was read from."""
    label: str
    quote: str


def technique(text: str) -> Optional[str]:
    """The kind of method a text names, when it names one kind only."""
    kinds = [kind for kind, pattern in _TECHNIQUES if pattern.search(text)]
    return kinds[0] if len(kinds) == 1 else None


def names_interface(text: str) -> bool:
    """Whether a text speaks of a grain boundary, a surface or an interface."""
    return bool(_INTERFACE.search(text))


def is_quoted(sentence: str, section: str = "", value: Optional[Tuple[int, int]] = None) -> bool:
    """Whether the value at `value` in a sentence (or the sentence as a whole) reports somebody
    else's result rather than the paper's own: its part of the sentence cites a source, or it
    stands in the introduction without saying "we" or "in this work". A value inside a comparison
    ("... in good agreement with the 0.37 eV of ref. [4]") is judged by the comparison alone, and
    one outside it by the rest of the sentence."""
    clauses = comparison_clauses(sentence)
    inside = next((c for c in clauses if value is not None and c[0] <= value[0] < c[1]), None)
    if inside is not None:
        own = sentence[inside[0]:inside[1]]
    else:
        own = list(sentence)
        for start, end in clauses:
            own[start:end] = " " * (end - start)
        own = "".join(own)
    if _OWN_WORK.search(own):
        return False
    return bool(_QUOTED.search(own)) or (inside is None and section == "Introduction")


def _bounds(label: str) -> Tuple[float, float]:
    """(lowest, highest) kelvin of a temperature label."""
    if label == ROOM_TEMPERATURE:
        return 298.0, 298.0
    numbers = [float(n) for n in label.split(" ", 1)[0].split("-")]
    return min(numbers), max(numbers)


def _quote(sentence: str, limit: int = 200) -> str:
    sentence = re.sub(r'\s+', ' ', sentence).strip()
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + " ..."


class Study:
    """The paper-wide facts of one paper; see the module docstring."""

    def __init__(self, blocks: Sequence[Dict[str, Any]], title: str = "", references: int = 0):
        texts = [b["text"] for b in blocks if b.get("type") in ("Text", "Caption") and b.get("section") != "References"]
        whole = " ".join(texts)
        self.simulation_words = len(_SIMULATION_WORK.findall(whole))
        self.experimental_words = len(_EXPERIMENTAL_WORK.findall(whole))
        self.kind = self._kind(self.simulation_words, self.experimental_words)
        # A review quotes other people's values: nothing about the paper itself says how each was obtained.
        self.review = (bool(_REVIEW_TITLE.search(title or "")) or len(_THIS_REVIEW.findall(whole)) >= 2
                       or references >= _MANY_REFERENCES)
        self.about_grain_boundaries = len(_GRAIN_BOUNDARY.findall(whole)) >= _MANY_GRAIN_BOUNDARIES
        self._techniques = Counter(kind for kind, pattern in _TECHNIQUES for _ in pattern.finditer(whole))
        self.pressure_varies = len({re.sub(r'\s', '', p) for p in _NUMERIC_PRESSURE.findall(whole)}) >= _PRESSURE_IS_A_VARIABLE

        self.captions: Dict[str, str] = {}
        for b in blocks:
            if b.get("type") == "Caption" and b.get("ref_number"):
                self.captions.setdefault(f"{b.get('ref_kind', 'Figure')} {str(b['ref_number']).upper()}", b["text"])

        own = [s for text in texts for s in _SENTENCE_BREAK.split(text) if 20 < len(s) < 600 and not _QUOTED.search(s)]
        # In a paper that also simulates, an Arrhenius plot may be either: it only counts in an experimental one.
        arrhenius = self.kind == EXPERIMENTAL
        self._temperature = {SIMULATION: self._simulated_range(own),
                             EXPERIMENTAL: self._measured_range(own, probe=False, arrhenius=arrhenius),
                             LOCAL_PROBE: self._measured_range(own, probe=True, arrhenius=False)}
        self._pressure = {SIMULATION: self._one_pressure(own, simulation=True),
                          EXPERIMENTAL: self._one_pressure(own, simulation=False)}

    # ------------------------------------------------------------------
    # The kind of study
    # ------------------------------------------------------------------
    @staticmethod
    def _kind(simulation: int, experimental: int) -> str:
        if simulation >= _ENOUGH_WORDS and experimental <= _PASSING_SHARE * simulation:
            return SIMULATION
        if experimental >= _ENOUGH_WORDS and simulation <= _PASSING_SHARE * experimental:
            return EXPERIMENTAL
        return BOTH if min(simulation, experimental) >= _ENOUGH_WORDS else UNSPECIFIED

    def origin(self) -> Tuple[str, str]:
        """(origin, why) of a value the paper reports as its own result, if the paper is of one kind."""
        if self.review or self.kind not in (SIMULATION, EXPERIMENTAL):
            return UNSPECIFIED, ""
        if self.kind == SIMULATION:
            return SIMULATION, (f"a computational study ({self.simulation_words} mentions of simulation methods, "
                                f"{self.experimental_words} of experimental ones)")
        return EXPERIMENTAL, (f"an experimental study ({self.experimental_words} mentions of experimental methods, "
                              f"{self.simulation_words} of simulation ones)")

    def assumes_bulk(self) -> bool:
        """Whether a simulated value of this paper is a bulk value unless it says otherwise."""
        return not self.about_grain_boundaries

    def technique(self, origin: str) -> Optional[str]:
        """The kind of method behind the paper's values of this origin, when it uses one kind only:
        static calculations or molecular dynamics, impedance or a local probe."""
        kinds = (STATIC, DYNAMIC) if origin == SIMULATION else (IMPEDANCE, LOCAL_PROBE)
        used = [kind for kind in kinds if self._techniques[kind]]
        return used[0] if len(used) == 1 and self._techniques[used[0]] >= _A_FEW_MENTIONS else None

    # ------------------------------------------------------------------
    # Conditions stated in the methods
    # ------------------------------------------------------------------
    @staticmethod
    def _simulated_range(sentences: Sequence[str]) -> Optional[Stated]:
        """The temperatures of the paper's molecular-dynamics runs: of the statements about runs
        made for ion transport first, the one naming the widest set."""
        best: Optional[Tuple[Tuple[bool, bool, float], Stated]] = None
        for sentence in sentences:
            if (not _SIMULATION_RUN.search(sentence) or _PROTOCOL.search(sentence)
                    or _IMPEDANCE_MEASUREMENT.search(sentence) or _NOT_A_RESULT_RUN.search(sentence)):
                continue
            label = temperature_range(sentence)
            if label == "NONE":
                continue
            low, high = _bounds(label)
            if high - low < _SPAN or low < _SIMULATED_BETWEEN[0] or high > _SIMULATED_BETWEEN[1]:
                continue
            rank = (bool(_TRANSPORT.search(sentence)), bool(_RUN_VERB.search(sentence)), high - low)
            if best is None or rank > best[0]:
                best = (rank, Stated(label, _quote(sentence)))
        return best[1] if best else None

    @staticmethod
    def _measured_range(sentences: Sequence[str], probe: bool, arrhenius: bool) -> Optional[Stated]:
        """The temperature range of the paper's transport measurements — by impedance, or (`probe`)
        by NMR and the like, which need not span the same range: a statement about the technique
        first, else about the conductivity; the widest of them."""
        best: Optional[Tuple[Tuple[bool, float], Stated]] = None
        for sentence in sentences:
            impedance = bool(_IMPEDANCE_MEASUREMENT.search(sentence))
            if (technique(sentence) == LOCAL_PROBE) != probe:
                continue
            if (not (_TRANSPORT_MEASUREMENT.search(sentence) or (arrhenius and _ARRHENIUS.search(sentence)))
                    or _SIMULATION_RUN.search(sentence) or _COMPUTED.search(sentence) or _EXTRAPOLATED.search(sentence)
                    or _NOT_A_RESULT_RUN.search(sentence) or (_OTHER_MEASUREMENT.search(sentence) and not impedance)):
                continue
            label = temperature_range(sentence)
            if label == "NONE":
                continue
            low, high = _bounds(label)
            if high - low < _SPAN:
                continue
            rank = (impedance, high - low)
            if best is None or rank > best[0]:
                best = (rank, Stated(label, _quote(sentence)))
        return best[1] if best else None

    @staticmethod
    def _one_pressure(sentences: Sequence[str], simulation: bool) -> Optional[Stated]:
        """The pressure of the paper's measurements (or of its constant-pressure simulations), if
        it states exactly one."""
        found: Dict[str, str] = {}
        for sentence in sentences:
            if simulation:
                if not _BAROSTAT.search(sentence):
                    continue
            elif not _PRESSURE_OF_MEASUREMENT.search(sentence) or (
                    _FABRICATION.search(sentence) and not _DURING_MEASUREMENT.search(sentence)):
                continue
            label = pressure_point(sentence)
            if label != "NONE" and not (label == AMBIENT_PRESSURE and "pressure" not in sentence.lower()):
                found.setdefault(label, _quote(sentence))
        return Stated(*next(iter(found.items()))) if len(found) == 1 else None

    def temperature_range(self, origin: str, method: Optional[str] = None) -> Optional[Stated]:
        """The temperature range the paper's own values of this origin were obtained over; `method`
        (see `technique`) tells an NMR value from an impedance one."""
        if not self._did(origin):
            return None
        return self._temperature.get(LOCAL_PROBE if origin == EXPERIMENTAL and method == LOCAL_PROBE else origin)

    def any_temperature_range(self, origin: str, method: Optional[str] = None) -> Optional[Stated]:
        """The range the paper gives for work of this kind, whatever kind of paper it is and whichever
        material the value is for: the last thing to go by before a mere convention."""
        return self._temperature.get(LOCAL_PROBE if origin == EXPERIMENTAL and method == LOCAL_PROBE else origin)

    def pressure(self, origin: str) -> Optional[Stated]:
        """The pressure the paper's own values of this origin were obtained under."""
        return self._pressure.get(origin) if self._did(origin) and not self.pressure_varies else None

    def _did(self, origin: str) -> bool:
        """Whether the paper itself did work of this kind (a review did none)."""
        return not self.review and self.kind in (origin, BOTH)

    # ------------------------------------------------------------------
    # Figure and table captions
    # ------------------------------------------------------------------
    def caption(self, reference: str) -> str:
        """The caption a reference points to ("Figure 4b", "Table 1"), narrowed to its panel where
        the caption can be split by panel; "" if the caption was not found."""
        cited = _CITED.match(reference.strip())
        if not cited:
            return ""
        kind = "Table" if cited.group(1).lower() == "table" else "Figure"
        caption = self.captions.get(f"{kind} {cited.group(2).upper()}", "")
        return self._panel(caption, cited.group(3).lower()) if caption and cited.group(3) else caption

    @staticmethod
    def _panel(caption: str, letter: str) -> str:
        marks = [(m.start(), m.end(), m.group(1) or m.group(2)) for m in _PANEL_MARK.finditer(caption)]
        letters = [mark[2] for mark in marks]
        if letter not in letters or len(set(letters)) != len(letters):
            return caption
        # Does a mark open its panel's description, or close it?
        opens = [bool(re.search(r'(?:^|[.;,:|]|\band)\s*$', caption[:start])) for start, _, _ in marks]
        i = letters.index(letter)
        if all(opens):
            lead = caption[:marks[0][0]]
            return lead + caption[marks[i][1]:marks[i + 1][0] if i + 1 < len(marks) else len(caption)]
        if not any(opens[1:]):
            return caption[marks[i - 1][1] if i else 0:marks[i][0]]
        return caption
