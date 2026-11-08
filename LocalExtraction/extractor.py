# LocalExtraction/extractor.py

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import spacy

from . import quantities
from .chemistry import INERT, Abbreviations, ChemistryEngine
from .config import (EA_PROPERTIES, MATERIAL_CATEGORIES, NUM, NUM_MAGNITUDE, QUANTITY_PROPERTIES,
                    TRANSPORT_PROPERTIES, SchemaConfig)
from .context import (AMBIENT_PRESSURE, EXPERIMENTAL, NEARBY, ROOM_TEMPERATURE, SIMULATION, STATED, UNSPECIFIED,
                     Descriptor, comparison_clauses, describe, find_structures, is_compared_with,
                     is_room_temperature, not_a_result, origin_of, pairs_off, preceding_values, pressure_point,
                     structure_near, structures_of, table_context, temperature_point, temperature_range,
                     value_context, without_type_labels)
from .models import (EquationRecord, ExtractedField, FigureRecord, Material, Relation, TableRecord, WorkflowStep,
                     as_written)
from .normalizer import DataNormalizer
from .species import mobile_species, paper_ion
from .study import DYNAMIC, LOCAL_PROBE, STATIC, Study, is_quoted, names_interface, technique
from .transport import classify_transport, classify_transport_contexts, components_in_order

# SciSpaCy is preferred for scientific literature; falls back to the general English model.
# Loaded once at import time and shared read-only across ThreadPoolExecutor workers — spaCy's
# documented pattern (inference calls don't mutate the shared pipeline). Only the sentence
# boundaries and the dependency tree are used, so the entity recogniser and the lemmatiser — half
# of the running time — are left out; neither changes a sentence or a parse.
_UNUSED_COMPONENTS = ["ner", "lemmatizer"]
try:
    nlp = spacy.load("en_core_sci_sm", exclude=_UNUSED_COMPONENTS)
except OSError:
    try:
        nlp = spacy.load("en_core_web_sm", exclude=_UNUSED_COMPONENTS)
    except OSError:
        nlp = spacy.blank("en")
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
# The model used, recorded with every paper it reads (papers.csv, extracted_with): another model splits
# sentences and parses them differently, so the same PDF can give other values.
if nlp.meta.get("name", "").startswith("core_"):
    NLP_MODEL = f"en_{nlp.meta['name']} {nlp.meta.get('version', '')}".strip()
else:
    NLP_MODEL = "no language model (blank English, sentence splitter only)"


def warn_if_no_language_model() -> None:
    """Said when an extraction starts — not when the code is loaded (`--version`, `--help`)."""
    if NLP_MODEL.startswith("no language model"):
        logging.warning("No spaCy language model is installed: sentences are split by punctuation only and "
                        "fewer values are tied to their material. Install one with: python -m spacy download "
                        "en_core_web_sm")

_HAS_PARSER = "parser" in nlp.pipe_names or "senter" in nlp.pipe_names

_EQUATION_TYPE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pattern), etype) for pattern, etype in SchemaConfig.EQUATION_PATTERNS.items()
]
_WORKFLOW_STAGE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pattern), stage) for pattern, stage in SchemaConfig.WORKFLOW_STAGES
]
_EA_HEADER_REGEX = re.compile(r'(?i)^\s*E\s*_?\s*(?:a|act|m)\b')
_SIGMA_HEADER_REGEX = re.compile(r'σ(?!\s?_?\s?e)')
_VAR_TOKEN_REGEX = re.compile(r'\b([a-zA-Zσαβγμδρω∂][a-zA-Z0-9]{0,2})\b')
_VAR_STOPWORDS = {"the", "of", "in", "is", "at", "to", "for", "and", "or", "eq", "we"}
# The forms of an equation found by its "=" (ExtractorEngine._equation_form).
_LINEAR_FIT = re.compile(r'^\s*y\s*=\s*[-+−]?\s*\d')
_EQUATION_SIDES = re.compile(r'\s*(?:→|⟶|->|⇌|=)\s*')
_SUBSTITUTION = re.compile(r'\b[A-Z]\s*=\s*[A-Z][a-z]?\s*(?:,|\bor\b|\band\b)')
_BARE_VALUE = re.compile(r'\s*[-+−]?\s*[\d.,]+\s*(?:[×x]\s*10\S*)?\s*[A-Za-zÅ%°/·\-\s0-9²³⁻¹]*[.,;)]?\s*')
_OPERATOR = re.compile(r'exp|\bln\b|\blog|√|∑|∫|/|\^|[⁻¹²³]|\bd[A-Za-z]\s*/\s*d|[×·*]')
_ARRHENIUS_FORM = re.compile(r'exp.*(?:E_?a|E\s?a\b|k_?B|RT|kT)')

_CELL_UNIT = r'\s*([A-Za-zΩ°μ%][A-Za-zΩ°μ%/\.\d⁻¹²³⁰⁴⁵⁶⁷⁸⁹\^-]*)?'
_CELL_NUM_UNIT = re.compile(rf'[~≈∼]?\s*{NUM}{_CELL_UNIT}')
_CELL_MAGNITUDE_UNIT = re.compile(rf'[~≈∼]?\s*{NUM_MAGNITUDE}{_CELL_UNIT}')
_HEADER_UNIT = re.compile(r'\(([^)]+)\)')
_EQ_REF_REGEX = re.compile(r'(?i)\bEq(?:uation)?s?\.?\s*(\d+)')
_TABLE_REF_REGEX = re.compile(r'(?i)\bTables?\.?\s*(\d+)')
# A figure/table a sentence points to: "Fig. 4b", "Figure S5", "Table II".
_CITED_REF_REGEX = re.compile(r'(?i)\b(Fig(?:ure)?|Table)s?\.?\s*(S?\d+[a-z]?|[IVX]+\b)')

# A value in a sentence that names no material is tied to a material named in the sentences just
# before it (of the same paragraph):
#  - when it refers back to it ("LLZO was sintered at 1200 °C. Its conductivity reached 0.5
#    mS/cm."): the single material of the nearest of the previous _BACKREF_SENTENCES that names any;
#  - for an activation energy, even without such a reference ("... diffusion in LiFePO4 ... It can
#    be seen that the energy barriers are about 0.51 eV"): the material the previous
#    _TOPIC_SENTENCES name most often, if one clearly leads.
# Without either the sentence may be about anything — a literature value for another compound, a
# class of materials — so nothing is assumed.
_BACKREF_SENTENCES = 2
_TOPIC_SENTENCES = 3
_REFERS_BACK = re.compile(
    r'(?i)\b(?:its|their)\b'
    r'|\b(?:it|they)\s+(?:also\s+)?(?:exhibit|show|ha[sv]|possess|deliver|achiev|display|reach|present)\w*'
    r'|\b(?:this|these|the\s+(?:same|latter|former|resulting|obtained|as[\s-]prepared|title))\s+(?:\w+[\s-]+)?'
    r'(?:material|compound|phase|electrolyte|sample|composition|structure|polymorph|pellet|ceramic|glass)s?\b'
    r'|\bthe\s+(?:latter|former)\b')

# A value and the material it is given for, side by side: "0.31 eV (LLZO)", "0.3 eV for cubic
# LLZO", "0.55 eV found in LiPON" — and "LLZO (0.31 eV)", "LLZO: 0.31 eV", "Li6PS5Cl (σ = 3 mS/cm,
# Ea = 0.3 eV)", "... than that of LATP is 0.7 mS/cm".
_APPOSED_AFTER = re.compile(
    r'(?i)^\s*(?:(?:at|under)\s+[^,;()]{1,30}?)?\)?\s*'  # "... (10−7 S/cm at ambient temperature) in Li14ZnGe4O16"
    r'(?:\(\s*|,?\s*(?:(?:found|obtained|reported|measured|observed|calculated|computed|predicted|'
    r'determined|achieved)\s+)?(?:for|in|of)\s+(?:the\s+|that\s+of\s+)?(?:[\w.+-]+[\s-]+){0,2}?)$')
_APPOSED_BEFORE = re.compile(
    r'^\s*(?:\(\s*(?:[^()]{0,40}?,\s*)?|[:=]\s*)(?:(?:E\s?_?\s?a|σ\w*|D\w*)\s*[=:≈~]\s*)?(?:[~≈∼]\s*|ca\.\s*|about\s+)?$')
_THAT_OF = re.compile(r'(?i)\bthat\s+(?:of|for|in)\s+(?:the\s+)?(?:[\w.+-]+[\s-]+){0,2}$')
_COPULA = re.compile(r'(?i)^\s+(?:(?:is|was|are|were|being|reaches|reached)\s+)?(?:[~≈∼]\s*|about\s+|only\s+)?$')
# A material named as what was added to another — "1 wt% MgF2 additive", "the addition of Li3BO3",
# "coated with LiNbO3", "Al2O3 filler" — is not what the value was measured on.
_ADDED_AFTER = re.compile(r'(?i)^[\s-]*(?:additives?|addition|added|dopants?|doping|doped|coatings?|coated|modified|'
                          r'containing|fillers?|precursors?|sintering\s+aids?|flux|contents?|amounts?|concentrations?|'
                          r'incorporation|(?:nano)?particles|cathodes?|anodes?|electrodes?)(?![a-z])')
_ADDED_BEFORE = re.compile(
    r'(?i)(?:\b(?:addition|incorporation|introduction|amounts?|contents?|doping|coating|layers?)\s+of'
    r'|\b(?:coated|doped|mixed|modified|treated|composited|blended)\s+with|\b(?:wt|mol|at|vol)\.?\s?%'
    # "the electrolyte containing polyacrylonitrile-LiClO4 and 15 wt% LLTO"
    r'|\b(?:containing|comprising|consisting\s+of|composed\s+of))'
    r'\s+(?:\d+(?:\.\d+)?\s*(?:wt|mol|at|vol)\.?\s?%\s+)?(?:of\s+)?(?:[A-Za-z()]{3,}[-–/])?$'
    # The salt of a polymer electrolyte: "PEO-LiClO4", "poly(ethylene oxide)/LiTFSI".
    r'|(?:\b(?:PEO|PAN|PVDF|PVDF-HFP|PMMA|PVA|PPC|PEG|PEGDA|PVC|PVP|PTFE|PPO)|(?i:\bpoly(?!cryst|morph|anion|hedr|type)[\w()\s-]{3,40}?))\s?[-–/:]\s?$')
# What a neighbouring sentence must speak of for its temperature range to be that of a fit.
_OF_TRANSPORT = re.compile(
    r'(?i:\b(?:conductivit\w+|impedance|arrhenius|diffusi\w+|simulat\w+|molecular[\s-]dynamics|'
    r'temperature[\s-]dependen\w+|temperature\s+range|nyquist|activation)\b)|\b(?:EIS|MD|AIMD|NMR|MSD)\b')
# ... and for the one temperature it states to be that of a measurement.
_OF_MEASUREMENT = re.compile(r'(?i:\b(?:measur\w+|impedance|recorded|determined|conductivit\w+|simulat\w+)\b)|\b(?:EIS|MD|AIMD)\b')
# A citation the sentence splitter cut off from the sentence it closes: "[5].", "(Kamaya et al., 2011)."
_CITATION_ALONE = re.compile(r'^\s*(?:\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\]'
                             r'|\(\s?[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?,?\s+(?:19|20)\d{2}[a-z]?\s?\))\s*[.,;:]?\s*$')
# A piece of text that starts like this goes on with the sentence before it.
_GOES_ON = re.compile(r'\s*[a-z]{2,}[\s,]')
_BASIS_QUOTE = 110  # characters of a statement kept in a value's basis
# A sentence end hidden by a citation number run into it: "... conductors.9 The ...", "... by
# doping with Cl.[22] Inorganic glasses ...", "... as high as 10 mS cm−1.86 The screened phase ...".
_MISSED_BREAK = re.compile(r'(?<=[A-Za-z)\]%])\.(?:\d{1,3}|\[\d{1,3})(?:\s?[,–-]\s?\d{1,3})*\]?\s+(?=[A-Z][a-z])'
                           r'|(?<=[−-]\d)\.\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\s+(?=[A-Z][a-z]+\s)'
                           # ... or by a unit that reads like an abbreviation: "... of 0.37 eV. Bond-valence ..."
                           r'|(?:(?<=eV)|(?<=°C)|(?<=\dK)|(?<=\sK)|(?<=cm−1)|(?<=cm-1)|(?<=/cm)|(?<=Pa)|(?<=%))\.\s+(?=[A-Z][a-z])')
# An activation energy of something other than an ion's hop: the rotation of an anion group.
_ROTATION = re.compile(r'(?i)\b(?:re)?orientation(?:al|s)?\b|\brotation(?:al|s)?\b|\brotat(?:e|es|ing)\b')
# A material this seldom named in a paper is one it compares with, not one it studies: at most
# this many mentions, or this share of the mentions of the paper's most named material.
_PASSING_MENTIONS = 2
_PASSING_MENTION_SHARE = 0.05
# ... and the material a paragraph is about, for a value whose sentence names none, has to be one
# of the paper's main ones: a precursor named in the sentence before is not the topic.
_TOPIC_MENTION_SHARE = 0.2
# A value that names its own subject, though not one that can be resolved to a formula — a sample
# label ("0.04 eV in NLZC", "NLZC0.2-HT (0.31 eV)") or a variant ("the undoped sample") — is not a
# value of the paragraph's topic.
_SAMPLE_LABEL = r'(?=[A-Za-z0-9.+-]*[A-Z0-9][A-Za-z0-9.+-]*[A-Z0-9])[A-Z][A-Za-z0-9.+-]{2,}'
_OWN_LABEL_AFTER = re.compile(rf'^\s*(?:\(\s*|,?\s*(?:for|in|of)\s+(?:the\s+)?)({_SAMPLE_LABEL})')
_OWN_LABEL_BEFORE = re.compile(rf'({_SAMPLE_LABEL})\s*\(\s*[~≈∼]?\s*$')
_ANY_LABEL = re.compile(rf'\b(?:of|for|in)\s+(?:the\s+)?({_SAMPLE_LABEL})')
# ... or named with the quantity: "the activation energy of PL is higher (0.26 eV)".
_OWN_LABEL_NAMED = re.compile(r'\b(?:of|for|in)\s+(?:the\s+)?([A-Z][A-Z0-9][A-Za-z0-9.+-]*)(?![A-Za-z0-9+])')
_CONTRAST = re.compile(r'(?i)(?:[,;]\s*(?:\[[^\]]{1,12}\]\s*)?(?:but|whereas|while|although|however)|\bwhereas)\b')
# All that stands between two numbers of one list.
_LIST_JOIN = re.compile(r'(?i)\s*(?:[,;&–—-]|,?\s*(?:and|or)|to|vs\.?|versus)?\s*')
# What a comparison is made with when it names no material: another kind of thing altogether.
_ANOTHER_CLASS = re.compile(r'(?i)\b(?:that|those)\s+(?:of|for|in)\b|\b(?:typical|conventional|common|other|most|known|'
                            r'state-of-the-art|traditional)\b')
# What stands between two materials named together: "A and B", "A, B and C", "A (LGPS) and B".
_COORDINATED = re.compile(r'(?i)\s*(?:\([^()]{0,30}\)\s*)?(?:,\s*(?:and\s+|or\s+)?|and\s+|or\s+|&\s*)(?:the\s+)?')
_NOT_A_LABEL = {"DFT", "AIMD", "FPMD", "MD", "MLMD", "NEB", "CI-NEB", "BVSE", "BVEL", "MLIP", "EIS", "NMR", "XRD",
                "RT", "SSE", "SSES", "SE", "SES", "GB", "GBS", "II", "III", "IV", "VI", "FIG", "FIGS", "TABLE", "PBE",
                "PBESOL", "GGA", "GGA+U", "LDA", "HSE", "HSE06", "SCAN", "R2SCAN", "VASP", "MSD", "NVT", "NPT", "SI", "ESI",
                "ASSB", "ASSLB", "SSB", "LIB", "SIB", "SEI", "CEI", "CE", "OCV", "DC", "AC", "PFG", "SLR", "QENS"}
_VARIANT = re.compile(
    r'(?i)\b(?:un-?doped|pristine|bare|parent|(?:\w+-)?(?:co-?)?doped|(?:\w+-)?substituted'
    r'|(?:different|various|all|these|those|other|both)\s+(?:[\w-]+\s+){0,4}'
    r'(?:samples|compositions|compounds|materials|glasses|electrolytes|systems|phases|structures|candidates|conductors|'
    r'SEs|SSEs)'
    r'|composites?|(?:composite|hybrid)\s+(?:[\w-]+\s+){0,2}(?:samples?|glass(?:es)?|electrolytes?|membranes?|films?))\b')
# A paper that measures calls what it measured an activation energy; what it calls a barrier it
# usually computed on the side (bond-valence or NEB estimates in an experimental paper).
_BARRIER_WORD = re.compile(r'(?i)barrier|migration\s+energ')
# ... and, where no method is named at all, the names a computed value usually goes by: a
# migration, diffusion or energy barrier, a migration energy. (An "activation barrier" is as often
# a measured activation energy.)
_COMPUTED_NAME = re.compile(r'(?i)^(?!activation\b).*(?:barrier|(?:migration|hopping|jump)\s+(?:energ|enthalp))|^E_?m(?:ig)?$')
# The temperatures molecular-dynamics studies of ion conductors are usually run at.
_USUAL_MD_RANGE = "600-1200 K"
# A value read off the temperature dependence of something: not a static barrier.
_FITTED = re.compile(r'(?i)\barrhenius\b|\bfit(?:ted|ting|s)?\b|\bslope\b|temperature[\s-]dependen')
# What papers of this field compute rather than measure, when nothing says which (DFT quantities).
_USUALLY_COMPUTED = {"Formation_Energy", "Energy_Above_Hull", "Reaction_Energy", "Surface_Energy",
                     "Vacancy_Formation_Energy", "Binding_Energy", "Adsorption_Energy", "Bader_Charge", "Band_Gap"}
# Properties whose value is itself a temperature: they hold at that temperature.
_TEMPERATURE_VALUED = {"Melting_Point", "Glass_Transition_Temperature", "Debye_Temperature", "Activation_Temperature"}
# The properties the transport component (bulk / grain boundary / surface / total) is answered for.
COMPONENT_PROPERTIES = QUANTITY_PROPERTIES


class _Found(NamedTuple):
    """A value found in a sentence, before it is tied to a material."""
    cat: str
    prop: str
    field: ExtractedField
    span: Tuple[int, int]    # the number and its unit
    anchor: Tuple[int, int]  # from the wording that names the quantity to the end of the value
    group: int = 0           # the values of one list share a group, ...
    position: int = 0        # ... in which this is the position-th ...
    size: int = 1            # ... of this many,
    list_start: int = 0      # the first of which starts here
    about_class: bool = False  # "in antiperovskites": a class of materials, not one named earlier


@dataclass
class _Note:
    """What is learnt about a value on the way and needed again once the whole paper is read."""
    descriptors: List[Descriptor] = dataclass_field(default_factory=list)  # the structure stated with the value itself
    quoted: bool = False             # a result of another source, not of this paper
    technique: Optional[str] = None  # study.STATIC / DYNAMIC / LOCAL_PROBE / IMPEDANCE, when the wording says
    interface: bool = False          # the wording speaks of a grain boundary, a surface or an interface
    rotation: bool = False           # the activation energy of a rotation, not of ion transport


# Table columns that state a condition of their row ("T (K)", "Pressure (MPa)") or its structure
# ("Space group", "Phase") rather than a property value.
_TEMPERATURE_HEADER = re.compile(
    r'(?i)^\s*(?:T|temp(?:\.|erature)?)\b(?!.*(?:sinter|anneal|calcin|synth|melt|transition|glass|debye))')
_PRESSURE_HEADER = re.compile(r'(?i)^\s*(?:P|pressure)\b')
_STRUCTURE_HEADER = re.compile(r'(?i)space\s*group|crystal\s*system|structure|phase|symmetry|polymorph')
_REFERENCE_HEADER = re.compile(r'(?i)^\s*(?:refs?\.?|references?|sources?|citations?)\s*$')
_TEMPERATURE_UNIT = re.compile(r'(?:°|◦|º|˚)\s?C|\bK\b')
_PRESSURE_UNIT = re.compile(r'GPa|MPa|kPa|kbar|mbar|bar|atm|Pa')

# Table header keyword -> schema (category, property). Checked longest-keyword-first so
# "ionic conductivity" matches before the bare "conductivity" fallback.
_HEADER_PROPERTY_KEYWORDS: List[Tuple[str, str, str]] = sorted([
    ("ionic conductivity", "ELECTROCHEMICAL", "Ionic_Conductivity"),
    ("electronic conductivity", "ELECTROCHEMICAL", "Electronic_Conductivity"),
    ("conductivity", "ELECTROCHEMICAL", "Ionic_Conductivity"),
    ("activation energy", "ELECTROCHEMICAL", "Activation_Energy"),
    ("activation enthalpy", "ELECTROCHEMICAL", "Activation_Energy"),
    ("barrier", "ELECTROCHEMICAL", "Activation_Energy"),
    ("migration energy", "ELECTROCHEMICAL", "Activation_Energy"),
    ("diffusion coefficient", "ELECTROCHEMICAL", "Diffusion_Coefficient"),
    ("diffusivity", "ELECTROCHEMICAL", "Diffusion_Coefficient"),
    ("capacity retention", "ELECTROCHEMICAL", "Capacity_Retention"),
    ("specific capacity", "ELECTROCHEMICAL", "Specific_Capacity"),
    ("capacity", "ELECTROCHEMICAL", "Capacity"),
    ("coulombic efficiency", "ELECTROCHEMICAL", "Coulombic_Efficiency"),
    ("voltage", "ELECTROCHEMICAL", "Voltage"),
    ("energy density", "ELECTROCHEMICAL", "Energy_Density"),
    ("power density", "ELECTROCHEMICAL", "Power_Density"),
    ("current density", "ELECTROCHEMICAL", "Current_Density"),
    ("band gap", "ELECTRONIC", "Band_Gap"),
    ("formation energy", "THERMODYNAMIC", "Formation_Energy"),
    ("bulk modulus", "MECHANICAL", "Bulk_Modulus"),
    ("young's modulus", "MECHANICAL", "Young_Modulus"),
    ("cell volume", "STRUCTURAL", "Cell_Volume"),
    ("density", "STRUCTURAL", "Density"),
    ("space group", "STRUCTURAL", "Space_Group"),
    ("crystal system", "STRUCTURAL", "Crystal_System"),
    ("grain size", "STRUCTURAL", "Grain_Size"),
    ("particle size", "STRUCTURAL", "Particle_Size"),
    ("porosity", "STRUCTURAL", "Porosity"),
    ("melting point", "THERMAL", "Melting_Point"),
    ("thermal conductivity", "THERMAL", "Thermal_Conductivity"),
    ("cutoff energy", "DFT", "Cutoff_Energy"),
    ("temperature", "AIMD", "Temperature"),
], key=lambda x: len(x[0]), reverse=True)


class ExtractorEngine:

    # ------------------------------------------------------------------
    # Materials (delegated to chemistry.py — schema section 2)
    # ------------------------------------------------------------------
    @staticmethod
    def extract_materials(text: str) -> List[Dict[str, Any]]:
        return ChemistryEngine.find_materials(text)

    # ------------------------------------------------------------------
    # Dependency-parse relation linking (schema section 7)
    # ------------------------------------------------------------------
    @staticmethod
    def _dep_distance(tok_a, tok_b) -> int:
        if tok_a is None or tok_b is None:
            return 10_000
        chain_a = [tok_a] + list(tok_a.ancestors)
        chain_b = [tok_b] + list(tok_b.ancestors)
        pos_b = {t.i: d for d, t in enumerate(chain_b)}
        for d_a, t in enumerate(chain_a):
            if t.i in pos_b:
                return d_a + pos_b[t.i]
        return 10_000

    @staticmethod
    def _token_at(doc, start: int, end: int):
        span = doc.char_span(start, end, alignment_mode="expand")
        if span is not None and len(span) > 0:
            return span.root
        candidates = [t for t in doc if t.idx <= start]
        return candidates[-1] if candidates else (doc[0] if len(doc) else None)

    @classmethod
    def _link_property_to_material(cls, doc, materials: List[Dict], prop_start: int, prop_end: int) -> Tuple[Dict, str]:
        """Returns (best_material, extraction_method). Only ever links to ONE material —
        the syntactically (or, as a fallback, positionally) closest one in the sentence."""
        if len(materials) == 1:
            return materials[0], "proximity"

        if _HAS_PARSER and doc is not None:
            prop_tok = cls._token_at(doc, prop_start, prop_end)
            best, best_dist = None, None
            for mat in materials:
                mat_tok = cls._token_at(doc, mat["start"], mat["end"])
                dist = cls._dep_distance(prop_tok, mat_tok)
                if best_dist is None or dist < best_dist:
                    best, best_dist = mat, dist
            if best is not None and best_dist is not None and best_dist < 10_000:
                return best, "dependency_parse"

        # Fallback: nearest material by character distance to the property value.
        best = min(materials, key=lambda m: min(abs(m["start"] - prop_end), abs(prop_start - m["end"])))
        return best, "proximity"

    # ------------------------------------------------------------------
    # Sentence-level scoring (lightweight — ranking.py does the heavier multi-factor pass)
    # ------------------------------------------------------------------
    @staticmethod
    def _score_context(sentence: str, section: str, b_type: str) -> float:
        if section == "References":
            return 0.0
        score = 0.5
        sent_lower = sentence.lower()
        if b_type == "Table":
            score += 0.35
        elif b_type == "Caption":
            score += 0.25
        if section in ("Results", "Abstract", "Conclusion"):
            score += 0.2
        elif section == "Boilerplate":
            score -= 0.3
        elif section == "Supplementary":
            score -= 0.1
        if any(c in sent_lower for c in SchemaConfig.POSITIVE_CUES):
            score += 0.15
        if any(c in sent_lower for c in SchemaConfig.NEGATIVE_CUES):
            score -= 0.35
        return max(0.01, min(score, 0.99))

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @classmethod
    def extract_all(cls, blocks: List[Dict[str, Any]], title: str = "", references: int = 0) -> Dict[str, Any]:
        """Everything the paper's blocks hold. `title` and the number of `references` (both
        optional) help tell a review from a research paper."""
        results: Dict[str, Any] = {
            cat: {prop: [] for prop in SchemaConfig.SCHEMA[cat]} for cat in SchemaConfig.SCHEMA
        }
        results["relations"] = []
        results["equations"] = []
        results["figures"] = []
        results["tables"] = []
        # formula -> how often each structure descriptor was stated with it, anywhere in the paper.
        results["structure_votes"] = defaultdict(Counter)
        # The paper's own names for its formulas ("Na3Zr2Si2PO12 (NZSP)").
        results["abbreviations"] = Abbreviations.from_texts(
            b["text"] for b in blocks if b["type"] in ("Text", "Caption"))
        # What the paper states once for all its values, and what is noted about each value on the way.
        results["study"] = Study(blocks, title, references)
        results["notes"] = {}
        results["mentions"] = Counter()  # formula -> how often the paper names it
        results["series"] = {}           # the formula of a member of a series -> the series as the paper writes it

        materials_by_formula: Dict[str, Material] = {}
        material_counter = [0]
        seen_equation_types = set()

        def get_or_create_material(cand: Dict[str, Any], score: float, page: str, section: str,
                                    sentence: str, b_type: str) -> Material:
            key = cand["formula"]
            existing = materials_by_formula.get(key)
            if existing:
                existing.confidence = max(existing.confidence, score)
                return existing
            material_counter[0] += 1
            mat = Material(
                material_id=f"MAT_{material_counter[0]}",
                raw_formula=cand["raw"], normalized_formula=cand["formula"],
                elements=cand["elements"], is_known_alias=cand["is_known_alias"],
                confidence=score, source_page=page, source_section=section,
                source_sentence=sentence, source_type=b_type,
                ionic_radii=ChemistryEngine.ionic_radii(cand.get("representative", cand["elements"])),
            )
            materials_by_formula[key] = mat
            return mat

        for block in blocks:
            try:
                cls._process_block(block, results, get_or_create_material, seen_equation_types)
            except Exception as e:
                # One malformed block (bad OCR text, unusual table shape, ...) must not lose the
                # rest of the paper's extraction — schema section 20: robust against malformed input.
                logging.warning(f"Skipping block on page {block.get('page', '?')} after error: {e}")

        results["materials"] = list(materials_by_formula.values())
        # A member of a series the paper studies is one of its materials, however seldom the paper
        # singles it out: it is named as often as the series is.
        for formula, series in results["series"].items():
            results["mentions"][formula] = max(results["mentions"][formula], results["mentions"][series])
        cls._drop_passing_topics(results)
        cls._settle_structures(results["materials"], results.pop("structure_votes"), results["notes"])
        cls._complete_context(results)
        for scratch in ("abbreviations", "study", "notes", "mentions", "series"):
            del results[scratch]
        results["workflow"] = cls._build_workflow(blocks)
        return results

    @staticmethod
    def _has_context(cat: str, prop: str) -> bool:
        """Only a numeric value obtained for a material has a measurement context — not a
        paper-level setting (DFT/AIMD/ML/synthesis) or a bare mention ("cubic", "DOS")."""
        return cat in MATERIAL_CATEGORIES and SchemaConfig.SCHEMA[cat][prop][1] != "string"

    @staticmethod
    def _source(block: Dict[str, Any]) -> Tuple[str, str, str]:
        """(source_type, source_label, source_detail): where in the paper a block's values sit."""
        if block["type"] == "Caption":
            kind = block.get("ref_kind", "Figure")
            return kind, f"{kind} {block.get('ref_number', '')}".strip(), "caption"
        return "Text", "NONE", "NONE"

    @staticmethod
    def _cited_refs(text: str, own_label: str = "NONE") -> str:
        """Figures/tables the text points to ("Figure 4b | Table 1"), other than the one it sits in."""
        refs = (f"{'Table' if m.group(1).lower() == 'table' else 'Figure'} {m.group(2)}"
                for m in _CITED_REF_REGEX.finditer(text))
        return " | ".join(dict.fromkeys(ref for ref in refs if ref != own_label)) or "NONE"

    @classmethod
    def _process_block(cls, block: Dict[str, Any], results: Dict[str, Any], get_or_create_material,
                        seen_equation_types: set) -> None:
        if len(block.get("text", "")) < 3:
            return

        if block["type"] == "EquationCandidate":
            cls._record_equation(results, block["text"], block["text"], str(block["page"]),
                                  block["section"], seen_equation_types, force=True)
            return

        if block["type"] == "Table":
            cls._process_table_block(block, results, get_or_create_material)
            return

        if block["type"] == "Caption" and block.get("ref_kind") == "Figure":
            results["figures"].append(cls._build_figure(block, results["abbreviations"]))

        if block["type"] in ("Text", "Caption"):
            parts = [part for s in nlp(block["text"]).sents for part in _MISSED_BREAK.split(s.text)]
        else:
            parts = [block["text"]]
        sentences: List[str] = []
        for part in parts:
            # The splitter cuts "... of 12 mS/cm [5]." before the citation: it belongs to that sentence.
            # ... and after a formula that opens one: "Na2(CB9H10)(CB11H12)" | "with a conductivity of ...".
            if sentences and (_CITATION_ALONE.match(part)
                              or (_GOES_ON.match(part) and cls._is_a_bare_name(sentences[-1], results["abbreviations"]))):
                sentences[-1] = f"{sentences[-1]} {part.strip()}"
            else:
                sentences.append(part)
        source = cls._source(block)
        # The sentences processed so far, each with the materials it names (nearest last).
        processed: List[Tuple[str, List[Dict[str, Any]]]] = []

        for idx, sent in enumerate(sentences):
            if len(sent.strip()) < 4:
                continue
            score = cls._score_context(sent, block["section"], block["type"])
            if score == 0.0:
                continue
            named = cls._process_sentence(sent, score, str(block["page"]), block["section"], source,
                                           results, get_or_create_material, seen_equation_types,
                                           neighbors=(sentences[idx - 1] if idx > 0 else "",
                                                      sentences[idx + 1] if idx + 1 < len(sentences) else ""),
                                           recent=processed[::-1][:_TOPIC_SENTENCES])
            processed.append((sent, named))

    # ------------------------------------------------------------------
    # Workflow (schema section 11): ordered first-occurrence scan for pipeline-stage keywords,
    # preserving the paper's own order rather than forcing a fixed template.
    # ------------------------------------------------------------------
    @classmethod
    def _build_workflow(cls, blocks: List[Dict[str, Any]]) -> List[WorkflowStep]:
        steps: List[WorkflowStep] = []
        seen_stages = set()
        for block in blocks:
            if block["type"] not in ("Text", "Caption", "EquationCandidate") or block["section"] == "References":
                continue
            text = block["text"]
            for pattern, stage in _WORKFLOW_STAGE_PATTERNS:
                if stage in seen_stages:
                    continue
                if pattern.search(text):
                    seen_stages.add(stage)
                    steps.append(WorkflowStep(
                        order=len(steps) + 1, stage=stage, evidence_sentence=text[:200],
                        page=str(block["page"]), section=block["section"],
                    ))
        return steps

    # ------------------------------------------------------------------
    # The context of a value, from its own sentence outwards. Each answer records the level it
    # was found at (ExtractedField.basis); a level is only asked when the ones before it are silent.
    #   1. the value's own sentence                        ("stated")       _in_sentence
    #   2. the sentences just before it                    ("context")      value_context, _widen
    #   3. the caption of the figure/table it points to    ("caption of …") _widen
    #   4. what the paper states once for all its values   ("paper")        _complete_context
    #   5. what holds by convention, with the reason       ("assumed")      _complete_context
    # ------------------------------------------------------------------
    @staticmethod
    def _is_a_bare_name(text: str, abbreviations: Optional[Abbreviations]) -> bool:
        """Whether a piece of text is a material's name and next to nothing else: no sentence."""
        text = text.strip()
        if not text or len(text) > 60 or text[-1] in ".!?:;":
            return False
        mentions = ChemistryEngine.find_materials(text, abbreviations)
        return bool(mentions) and len(text) - sum(m["end"] - m["start"] for m in mentions) <= 12

    @staticmethod
    def _quote(text: str) -> str:
        text = re.sub(r'\s+', ' ', text.replace("|", "/")).strip()  # "|" separates the parts of a basis
        return text if len(text) <= _BASIS_QUOTE else text[:_BASIS_QUOTE].rsplit(" ", 1)[0] + " ..."

    @classmethod
    def _in_sentence(cls, field: ExtractedField, sent: str, spans: Sequence[Tuple[int, int]], kind: str,
                     neighbors: Tuple[str, str]) -> None:
        """Level 1 and the nearest part of level 2. `spans` are the stretches of the sentence to
        read the value's wording from: its own, then (for one of a list of values) the list's."""
        prop = field.property_name
        if prop in TRANSPORT_PROPERTIES:
            for start, end in spans:
                result = classify_transport(sent, start, end, neighbors, kind)
                if result.component != UNSPECIFIED:
                    break
            field.transport_component = result.component
            field.transport_component_evidence, field.dominant_component = result.evidence, result.dominant
            if result.component != UNSPECIFIED:
                dominated = f", dominated by the {result.dominant.replace('_', ' ')}" if result.dominant != "NONE" else ""
                field.basis["component"] = f"{STATED} ({cls._quote(result.evidence)}{dominated})"
        for start, end in spans:
            ctx = value_context(sent, start, end, kind, neighbors[0], any_rival=prop in EA_PROPERTIES)
            if field.temperature == "NONE" and ctx.temperature != "NONE":
                field.temperature, field.basis["temperature"] = ctx.temperature, STATED
            if field.pressure == "NONE" and ctx.pressure != "NONE":
                field.pressure, field.basis["pressure"] = ctx.pressure, STATED
            if field.data_origin in ("NONE", UNSPECIFIED):
                field.data_origin, field.data_origin_evidence = ctx.origin, ctx.origin_evidence
                if ctx.origin != UNSPECIFIED:
                    field.basis["origin"] = f"{ctx.origin_level} ({ctx.origin_evidence})"
        # An activation energy is the slope over a temperature range, so the one range its
        # sentence states is its own even when it stands far from the number.
        if prop in EA_PROPERTIES and field.temperature == "NONE":
            fitted = temperature_range(sent)
            if fitted != "NONE":
                field.temperature, field.basis["temperature"] = fitted, STATED

    @classmethod
    def _widen(cls, field: ExtractedField, note: _Note, sent: str,
               recent: Sequence[Tuple[str, List[Dict[str, Any]]]], study: Study) -> None:
        """Levels 2 and 3: what the sentences before the value and the caption it points to say.
        They speak of the paper's own work, so a value it quotes from another source keeps to what
        its own sentence says."""
        prop = field.property_name
        if note.quoted or study.review:
            note.technique, note.interface = technique(sent), names_interface(sent)
            if field.basis.get("origin", "").startswith(NEARBY):
                field.data_origin, field.data_origin_evidence = UNSPECIFIED, "NONE"
                del field.basis["origin"]
            return
        earlier = [text for text, _ in recent]
        captions = [(ref, study.caption(ref)) for ref in field.cited_refs.split(" | ")] if field.cited_refs != "NONE" else []
        captions = [(ref, caption) for ref, caption in captions if caption]

        note.technique = next((kind for kind in (technique(text) for text in (sent, *earlier, *(c for _, c in captions)))
                               if kind), None)
        note.interface = names_interface(sent) or any(names_interface(text) for text in earlier[:1])

        if field.data_origin == UNSPECIFIED:
            for level, text in (*((NEARBY, text) for text in earlier), *((f"caption of {ref}", c) for ref, c in captions)):
                origin, cue = origin_of(text)
                if origin != UNSPECIFIED:
                    field.data_origin, field.data_origin_evidence = origin, cue
                    field.basis["origin"] = f"{level} ({cue})"
                    break
        if prop not in QUANTITY_PROPERTIES:
            return

        if field.temperature == "NONE":
            if prop in EA_PROPERTIES:
                near = ((NEARBY, text) for text in earlier if _OF_TRANSPORT.search(text))
                read = temperature_range
            else:
                # A statement of the conditions ("The impedance was measured at 25 °C."), not the
                # temperature of the neighbouring sentence's own value.
                near = ((NEARBY, text) for text in earlier[:1]
                        if _OF_MEASUREMENT.search(text) and not quantities.find(text))
                read = temperature_point
            for level, text in (*near, *((f"caption of {ref}", c) for ref, c in captions)):
                label = read(text)
                if label != "NONE":
                    field.temperature, field.basis["temperature"] = label, level
                    break
        if field.pressure == "NONE":
            for ref, caption in captions:
                label = pressure_point(caption)
                if label != "NONE":
                    field.pressure, field.basis["pressure"] = label, f"caption of {ref}"
                    break
        if prop in TRANSPORT_PROPERTIES and field.transport_component == UNSPECIFIED:
            for ref, caption in captions:
                result = classify_transport_contexts((caption,))
                if result.component != UNSPECIFIED:
                    field.transport_component, field.transport_component_evidence = result.component, result.evidence
                    field.basis["component"] = f"caption of {ref} ({cls._quote(result.evidence)})"
                    break

    @classmethod
    def _complete_context(cls, results: Dict[str, Any]) -> None:
        """Levels 4 and 5, once the whole paper is read, for every value that has a context."""
        study: Study = results["study"]
        notes: Dict[int, _Note] = results["notes"]
        fields = [f for cat in MATERIAL_CATEGORIES for prop, found in results[cat].items()
                  if cls._has_context(cat, prop) for f in found]
        usual = cls._usual_temperature(fields)
        materials = {m.material_id: m.normalized_formula for m in results["materials"]}
        mentions: Counter = results["mentions"]
        often = max(mentions.values(), default=0)

        for f in fields:
            note, basis, prop = notes.get(id(f)) or _Note(), f.basis, f.property_name
            # In a review every value is somebody else's.
            quoted = note.quoted or study.review
            f.attribution = "cited" if quoted else "this work"
            # What the paper says of its own work holds for the materials it studies, not for one
            # it names once or twice to compare with.
            named = mentions[materials.get(f.material_id, "")]
            studied = not quoted and (f.material_id == "NONE" or named > max(_PASSING_MENTIONS, _PASSING_MENTION_SHARE * often))
            basis.setdefault("structure", STATED if f.structure != "NONE" else "not stated")

            if f.data_origin in ("NONE", UNSPECIFIED):
                f.data_origin = UNSPECIFIED
                origin, why = study.origin() if studied else (UNSPECIFIED, "")
                if origin == EXPERIMENTAL and _BARRIER_WORD.search(f.reported_as):
                    origin = UNSPECIFIED
                if origin != UNSPECIFIED:
                    f.data_origin, f.data_origin_evidence, basis["origin"] = origin, why, f"paper ({why})"
            if f.data_origin == UNSPECIFIED and quoted and prop in ("Ionic_Conductivity", "Electronic_Conductivity"):
                # Papers quote each other's measurements; a computed conductivity is called one.
                f.data_origin = EXPERIMENTAL
                basis["origin"] = "assumed (a quoted conductivity is a measured one unless it is called computed)"
            basis.setdefault("origin", "not stated (a value quoted from another source)" if quoted else "not stated")
            origin = f.data_origin
            own = origin in (SIMULATION, EXPERIMENTAL) and studied
            method = note.technique or (study.technique(origin) if own else None)
            if prop not in QUANTITY_PROPERTIES:
                continue

            if f.temperature == "NONE":
                if prop in EA_PROPERTIES:
                    span = study.temperature_range(origin, method) if own and method != STATIC else None
                    if span:
                        f.temperature, basis["temperature"] = span.label, f'paper ("{cls._quote(span.quote)}")'
                    elif origin == SIMULATION and method == STATIC:
                        f.temperature, basis["temperature"] = "0 K", "assumed (a static calculation: no thermal motion)"
                elif prop in usual:
                    f.temperature, basis["temperature"] = usual[prop]
            basis.setdefault("temperature", "not stated")

            if f.pressure == "NONE":
                stated = study.pressure(origin) if own else None
                if stated:
                    f.pressure, basis["pressure"] = stated.label, f'paper ("{cls._quote(stated.quote)}")'
                elif not study.pressure_varies:
                    f.pressure, basis["pressure"] = AMBIENT_PRESSURE, "assumed (no pressure is stated)"
            basis.setdefault("pressure", "not stated")

            if prop in TRANSPORT_PROPERTIES:
                if f.transport_component == UNSPECIFIED and not note.interface and not note.rotation:
                    if origin == SIMULATION and study.assumes_bulk():
                        f.transport_component, basis["component"] = "bulk", "assumed (simulated in a bulk cell)"
                    elif origin == EXPERIMENTAL and method == LOCAL_PROBE:
                        f.transport_component = "bulk"
                        basis["component"] = "assumed (NMR and scattering probe the ion motion inside the grains)"
                    elif origin == EXPERIMENTAL and prop != "Diffusion_Coefficient":
                        f.transport_component = "total"
                        basis["component"] = "assumed (measured on a pellet: bulk and grain boundaries together)"
                basis.setdefault("component", "not stated")
        for f in fields:
            note = notes.get(id(f)) or _Note()
            cls._leave_nothing_open(f, note, study, note.quoted or study.review)
        # The species that moves: read off each value's sentence, else from its material and the paper's main ion.
        quantities = [f for f in fields if f.property_name in QUANTITY_PROPERTIES]
        main_ion, main_count = paper_ion(f.source_sentence for f in quantities)
        for f in quantities:
            formula = materials.get(f.material_id, "") or (f.material_formula if f.material_formula != "NONE" else "")
            f.mobile_ion, f.basis["ion"] = mobile_species(f.property_name, f.source_sentence, formula, main_ion,
                                                          main_count)

    @classmethod
    def _leave_nothing_open(cls, f: ExtractedField, note: _Note, study: Study, quoted: bool) -> None:
        """The last level, for every value of a material: whatever the paper and the conventions
        above left open is answered with the likeliest value, so that every row of the value tables
        can be filtered and compared on every column. Each such answer says "assumed" and why in the
        value's basis — it is a default, not a statement of the paper."""
        basis, prop = f.basis, f.property_name
        is_ea = prop in EA_PROPERTIES
        name = f.reported_as if f.reported_as != "NONE" else prop.replace("_", " ").lower()
        computed_name = is_ea and bool(_COMPUTED_NAME.search(name.split(" (")[0]))
        own_paper = not quoted and not study.review
        noun = prop.replace("_", " ").lower()
        what = ("an " if noun[0] in "aeiou" else "a ") + noun

        if f.data_origin in ("NONE", UNSPECIFIED):
            if own_paper and study.kind == SIMULATION:
                f.data_origin, why = SIMULATION, "a value of a computational paper, given without its method"
            elif own_paper and study.kind == EXPERIMENTAL and not computed_name:
                f.data_origin, why = EXPERIMENTAL, "a value of an experimental paper, given without its method"
            elif computed_name:
                f.data_origin, why = SIMULATION, f"called “{name}”, no method named: such a value is usually computed"
            elif prop in _USUALLY_COMPUTED:
                f.data_origin, why = SIMULATION, f"{what}, no method named: such a value is usually computed (DFT)"
            elif is_ea:
                f.data_origin, why = EXPERIMENTAL, f"called “{name}”, no method named: such a value is usually measured"
            else:
                f.data_origin, why = EXPERIMENTAL, f"{what}, no method named: such a value is usually measured"
            basis["origin"] = f"assumed ({why})"
        origin = f.data_origin
        # The method: what the value's own wording names, else the one kind this paper uses.
        said = note.technique
        usual = study.technique(origin) if own_paper else None
        method = said or usual

        if prop in COMPONENT_PROPERTIES and f.transport_component in ("NONE", UNSPECIFIED):
            if note.rotation:
                f.transport_component, why = "bulk", "a rotation inside the crystal, not a path through the sample"
            elif origin == SIMULATION:
                f.transport_component, why = "bulk", "a computed value: of the bulk unless a boundary or a surface is named"
            elif method == LOCAL_PROBE:
                f.transport_component, why = "bulk", "NMR and scattering probe the ion motion inside the grains"
            elif prop == "Diffusion_Coefficient":
                f.transport_component, why = "bulk", "a measured diffusion coefficient comes from NMR or tracer studies of the grains"
            elif prop == "Electronic_Conductivity":
                f.transport_component, why = "total", "measured by DC polarization on a pellet: bulk and grain boundaries together"
            else:
                f.transport_component, why = "total", "a measured value: bulk and grain boundaries together unless one is named"
            basis["component"] = f"assumed ({why})"

        if f.pressure == "NONE":
            f.pressure, basis["pressure"] = AMBIENT_PRESSURE, "assumed (no pressure is stated with this value)"

        if f.temperature == "NONE":
            if is_ea:
                cls._ea_temperature(f, study, origin, method, said, usual, computed_name, own_paper)
            elif prop in _TEMPERATURE_VALUED:
                f.temperature = f.normalized_value
                basis["temperature"] = "assumed (the value is itself a temperature: it holds at that temperature)"
            elif prop in QUANTITY_PROPERTIES:
                given = study.any_temperature_range(origin, method) if own_paper and prop != "Ionic_Conductivity" else None
                if origin == EXPERIMENTAL:
                    f.temperature = ROOM_TEMPERATURE
                    basis["temperature"] = f"assumed ({what} quoted without a temperature is a room-temperature value)"
                elif prop == "Ionic_Conductivity" or prop == "Electronic_Conductivity":
                    f.temperature = ROOM_TEMPERATURE
                    basis["temperature"] = (f"assumed ({what} computed without a temperature is given at, or "
                                            "extrapolated to, room temperature)")
                elif given:
                    f.temperature = given.label
                    basis["temperature"] = f'assumed (the range this paper gives for its own work: "{cls._quote(given.quote)}")'
                else:
                    f.temperature = _USUAL_MD_RANGE
                    basis["temperature"] = "assumed (the usual range of molecular-dynamics runs: none is given for this value)"
            elif origin == SIMULATION:
                f.temperature = "0 K"
                basis["temperature"] = f"assumed ({what} computed without a temperature: a static calculation)"
            else:
                f.temperature = ROOM_TEMPERATURE
                basis["temperature"] = f"assumed ({what} measured without a temperature: at room temperature)"

    @classmethod
    def _ea_temperature(cls, f: ExtractedField, study: Study, origin: str, method: Optional[str], said: Optional[str],
                        usual: Optional[str], computed_name: bool, own_paper: bool) -> None:
        basis = f.basis
        given = study.any_temperature_range(origin, method) if own_paper else None
        # A value called a barrier is a static one unless its own sentence speaks of dynamics or
        # of a fit — even next to a sentence about trajectories, even in a paper that also runs
        # molecular dynamics.
        own_words = technique(f.source_sentence)
        static = origin == SIMULATION and own_words != DYNAMIC and not _FITTED.search(f.source_sentence) and (
            own_words == STATIC or computed_name or said == STATIC or (said is None and usual == STATIC))
        if static:
            f.temperature = "0 K"
            basis["temperature"] = "assumed (a computed barrier: a static calculation unless the paper says otherwise)"
        elif given:
            f.temperature = given.label
            basis["temperature"] = f'assumed (the range this paper gives for its own work: "{cls._quote(given.quote)}")'
        elif origin == SIMULATION:
            f.temperature = _USUAL_MD_RANGE
            basis["temperature"] = "assumed (the usual range of molecular-dynamics runs: none is given for this value)"
        else:
            f.temperature = ROOM_TEMPERATURE
            basis["temperature"] = ("assumed (a measured activation energy is fitted around room temperature: "
                                    "no range is given for this value)")

    @staticmethod
    def _usual_temperature(fields: Sequence[ExtractedField]) -> Dict[str, Tuple[str, str]]:
        """property -> (temperature, basis) for the conductivities and diffusion coefficients a
        paper quotes without a temperature, when those it does give one are at room temperature.
        An assumption about the value, though one the paper's own habit supports."""
        usual: Dict[str, Tuple[str, str]] = {}
        for prop in ("Ionic_Conductivity", "Electronic_Conductivity", "Diffusion_Coefficient"):
            stated = [f.temperature for f in fields if f.property_name == prop and f.temperature != "NONE"]
            at_room = sum(1 for label in stated if is_room_temperature(label))
            if len(stated) >= 3 and at_room >= 0.7 * len(stated):
                usual[prop] = (ROOM_TEMPERATURE, f"assumed ({at_room} of the {len(stated)} values of this property that the "
                                                 f"paper gives a temperature for are at room temperature)")
        return usual

    @staticmethod
    def _drop_passing_topics(results: Dict[str, Any]) -> None:
        """Undoes the links made to "the material the paragraph is about" where that material turns
        out to be one the paper names in passing (see _TOPIC_MENTION_SHARE)."""
        mentions: Counter = results["mentions"]
        needed = max(_PASSING_MENTIONS + 1, _TOPIC_MENTION_SHARE * max(mentions.values(), default=0))
        kept = []
        for relation in results["relations"]:
            if relation.extraction_method != "paragraph_topic" or mentions[relation.material_formula] >= needed:
                kept.append(relation)
                continue
            value = relation.property_value
            for material in results["materials"]:
                if material.material_id == relation.material_id:
                    material.properties = [p for p in material.properties if p is not value]
            value.material_id = value.material_formula = value.material_link = "NONE"
        results["relations"] = kept

    @classmethod
    def _settle_structures(cls, materials: List[Material], votes: Dict[str, Counter], notes: Dict[int, _Note]) -> None:
        """Gives each material every structure the paper states for it, most often stated first,
        and each of its values the structure it holds for: what its own sentence states; then what
        the paper states for the material — only where it describes it one way, never when it
        discusses e.g. both cubic and tetragonal LLZO on an equal footing; then the structure
        family that follows from the composition, when nothing names one."""
        for material in materials:
            stated = votes[material.normalized_formula]
            family = ChemistryEngine.structure_family(material.elements)
            material.structure = describe(descriptor for descriptor, _ in stated.most_common())
            material.structure_basis = STATED if stated else "not stated"
            if not stated and family:
                material.structure, material.structure_basis = family, "known for this composition"
            if material.structure == "NONE":
                # Nothing names a structure. What kind of compound it is can always be said.
                material.structure = ChemistryEngine.compound_class(material.elements, material.normalized_formula)
                material.structure_basis = "known for this composition (the kind of compound: no crystal structure is stated)"

            by_kind: Dict[str, Counter] = defaultdict(Counter)
            for (kind, label), count in stated.items():
                by_kind[kind][label] += count
            # One label per kind where the paper is of one mind: the only one, or three times in four.
            agreed = {kind: labels.most_common(1)[0][0] for kind, labels in by_kind.items()
                      if labels.most_common(1)[0][1] >= 0.75 * sum(labels.values())}

            for value in material.properties:
                if not cls._has_context(value.category, value.property_name):
                    continue
                own = list(notes[id(value)].descriptors) if id(value) in notes else []
                kinds = {kind for kind, _ in own}
                # A value quoted for one form of the material ("γ-Li3PS4") is not given the form the
                # paper mostly speaks of; only the family, which all its forms share.
                one_form = bool(kinds - {"family"})
                elsewhere = [(kind, label) for kind, label in agreed.items()
                             if kind not in kinds and (kind == "family" or not one_form)]
                known = [("family", family)] if family and "family" not in kinds | set(agreed) else []
                value.structure = describe(own + elsewhere + known)
                sources = [name for name, used in ((STATED, own), ("paper", elsewhere),
                                                   ("known for this composition", known)) if used]
                value.basis["structure"] = " + ".join(sources) or "not stated"
                if value.structure == "NONE":
                    # Nothing names a structure. What kind of compound it is can always be said.
                    value.structure = ChemistryEngine.compound_class(material.elements, material.normalized_formula)
                    value.basis["structure"] = "known for this composition (the kind of compound: no crystal structure is stated)"

    @staticmethod
    def _link(results: Dict[str, Any], field: ExtractedField, material: Material, method: str,
              confidence: float) -> None:
        """Records that `field` was obtained for `material`, on both of them and as a Relation."""
        field.material_id, field.material_formula = material.material_id, material.normalized_formula
        field.material_link = method
        material.properties.append(field)
        results["relations"].append(Relation(
            material_id=material.material_id, material_formula=material.normalized_formula,
            category=field.category, property_name=field.property_name, property_value=field,
            confidence=confidence, source_sentence=field.source_sentence, source_page=field.source_page,
            extraction_method=method,
        ))

    # ------------------------------------------------------------------
    # One sentence
    # ------------------------------------------------------------------
    @classmethod
    def _process_sentence(cls, sent: str, score: float, page: str, section: str, source: Tuple[str, str, str],
                           results: Dict[str, Any], get_or_create_material, seen_equation_types: set,
                           neighbors: Tuple[str, str] = ("", ""),
                           recent: Sequence[Tuple[str, List[Dict[str, Any]]]] = ()) -> List[Dict[str, Any]]:
        """Extracts the sentence's values and ties each to the material it is given for. `recent`
        holds the previous sentences of the paragraph with the materials each names, nearest first.
        Returns the materials this sentence names."""
        materials = without_type_labels(sent, ChemistryEngine.find_materials(sent, results["abbreviations"]))
        source_type, source_label, source_detail = source
        cited_refs = cls._cited_refs(sent, source_label)
        study: Study = results["study"]
        results["mentions"].update(m["formula"] for m in materials)
        for mention in materials:
            if "representative" in mention or mention.get("open_series"):  # a series named as a whole
                results.setdefault("named_series", {})[mention["formula"]] = mention
            if mention.get("series"):  # "x = 0.25" of a series named as a whole elsewhere
                results["mentions"][mention["series"]] += 1
                results["series"][mention["formula"]] = mention["series"]

        # Structure words go to the material mention they stand next to ("cubic LLZO", "β-Li3PS4").
        stated = structures_of(sent, [(m["start"], m["end"]) for m in materials])
        for cand, descriptors in zip(materials, stated):
            results["structure_votes"][cand["formula"]].update(descriptors)

        refers_back = bool(_REFERS_BACK.search(sent))
        found: List[_Found] = []

        def value(cat: str, prop: str, raw: Any, normalized: str, numeric: bool) -> ExtractedField:
            unit = normalized.split(" ", 1)[1] if numeric and " " in normalized else "NONE"
            return ExtractedField(
                raw_value=as_written(raw), normalized_value=normalized, confidence=score,
                source_page=page, source_section=section, source_sentence=sent, source_type=source_type,
                unit=unit, category=cat, property_name=prop,
                source_label=source_label, source_detail=source_detail, cited_refs=cited_refs,
            )

        def place(item: _Found, spans: Sequence[Tuple[int, int]], kind: str) -> None:
            """Reads the context of a numeric value off its sentence and records the value."""
            nonlocal refers_back
            note = results["notes"][id(item.field)] = _Note(quoted=is_quoted(sent, section, item.span))
            if item.prop in EA_PROPERTIES and _ROTATION.search(sent, item.anchor[0], item.anchor[1]):
                note.rotation = True
                item.field.reported_as = f"{item.field.reported_as} (of a rotation)"
            cls._in_sentence(item.field, sent, spans, kind, neighbors)
            if item.prop in TRANSPORT_PROPERTIES and item.size > 1:
                # "The total and bulk conductivities are 0.4 and 2.5 mS/cm": one component each, in that order.
                components, wording = components_in_order(sent, item.anchor[0], item.list_start)
                if len(components) == item.size:
                    item.field.transport_component = components[item.position]
                    item.field.transport_component_evidence, item.field.dominant_component = wording, "NONE"
                    item.field.basis["component"] = f"{STATED} ({cls._quote(wording)})"
            about_class = False
            if not materials:
                nearby = structure_near(sent, item.anchor[0], item.anchor[1], kind)
                item.field.structure, note.descriptors = describe(nearby), list(nearby)
                # "... in the γ-phase had a barrier of 0.16 eV": a phase of something named earlier.
                refers_back = refers_back or any(k == "polymorph" for k, _ in nearby)
                about_class = any(k == "family" for k, _ in nearby)
            cls._widen(item.field, note, sent, recent, study)
            results[item.cat][item.prop].append(item.field)
            found.append(item._replace(about_class=about_class))

        # 1. The properties named by a keyword followed by their value.
        group = 1000
        for cat, props in SchemaConfig.COMPILED_SCHEMA.items():
            for prop, (pattern, norm_type) in props.items():
                if prop in QUANTITY_PROPERTIES:
                    continue
                numeric = cls._has_context(cat, prop)
                for match in pattern.finditer(sent):
                    raw = match.groups() if match.groups() else match.group()
                    normalized = DataNormalizer.normalize(raw, norm_type)
                    if normalized == "NONE":
                        continue
                    grp = match.lastindex or 0
                    end = match.end(grp) if grp else match.end()
                    anchor = (match.start(), end)
                    if not numeric:
                        item = _Found(cat, prop, value(cat, prop, raw, normalized, False), anchor, anchor)
                        results[cat][prop].append(item.field)
                        found.append(item)
                        continue
                    # "0.6, 1.2 and 1.5 GPa": the pattern finds the last number, the ones before it share its unit.
                    group += 1
                    list_start, earlier_numbers = preceding_values(sent, match.start(1))
                    numbers = [*((n, (list_start, list_start)) for n in earlier_numbers), (raw[0], (match.start(1), end))]
                    for position, (number, span) in enumerate(numbers):
                        normalized = DataNormalizer.normalize((number, *raw[1:]), norm_type)
                        if normalized != "NONE":
                            place(_Found(cat, prop, value(cat, prop, (number, *raw[1:]), normalized, True), span, anchor,
                                         group, position, len(numbers), list_start), [anchor], norm_type)

        # 2. The transport quantities, read value-first (quantities.py).
        accepted, dismissed = [], []
        for q in quantities.find(sent, neighbors[0]):
            normalized = DataNormalizer.normalize(q.raw, q.kind)
            if normalized == "NONE" or (q.prop in EA_PROPERTIES and not float(normalized.split(" ", 1)[0]) > 0):
                continue
            reason = not_a_result(sent, q.anchor[0], q.list_start, q.span, energy=q.kind == "energy")
            if reason:
                logging.debug(f"Skipping {q.prop} {normalized!r} ({reason}): {sent[:120]!r}")
                dismissed.append(q)
                continue
            accepted.append((q, normalized))
        for q, normalized in accepted:
            members = [other for other, _ in accepted if other.group == q.group]
            cat = "ELECTROCHEMICAL"
            field = value(cat, q.prop, q.raw, normalized, True)
            if q.prop in EA_PROPERTIES:
                field.reported_as = q.term or "NONE"
            # A later value of a list reads its own wording first (from the number to its unit), then the list's.
            place(_Found(cat, q.prop, field, q.span, q.anchor, q.group, members.index(q), len(members), members[0].span[0]),
                  [(q.span[0], q.anchor[1]), q.anchor] if members.index(q) > 0 else [q.anchor], q.kind)

        cls._scan_equation_mentions(sent, page, section, seen_equation_types, results)

        if not found:
            return materials

        doc = []  # the sentence's parse, made only if a link needs it

        def parse():
            if not doc:
                doc.append(nlp(sent) if _HAS_PARSER else None)
            return doc[0]

        # A value standing right next to a material is that material's, whatever else the sentence
        # names. Not in a list whose numbers share one unit ("0.6, 1.2 and 1.5 eV for A, B and C"),
        # where the material after the last number is the first of another list, nor where the
        # sentence itself pairs its lists off ("..., respectively").
        paired = pairs_off(sent)
        sharing = {item.group for item in found if item.span[1] != item.anchor[1]}
        apposed: Dict[int, int] = {}
        for i, item in enumerate(found):
            if cls._has_context(item.cat, item.prop) and item.group not in sharing:
                j = cls._apposed(sent, materials, item.span, after=not (paired and item.size > 1))
                if j is not None:
                    apposed[i] = j

        # A material that a bound or an assumed value is given for ("... not higher than 10−3 S/cm for
        # the LLTO ceramic") is that value's, though the value itself is no result.
        spoken_for = {(q.prop, j) for q in dismissed for j in [cls._apposed(sent, materials, q.span)] if j is not None}
        compared = comparison_clauses(sent)
        # ... "than that for LGPS or Li6.25PS5.25Cl0.75": and what is named together with it.
        # It is that mention which is compared with, not the compound wherever it is named: "β-LZC
        # shows a lower barrier (0.68 eV) than α-LZC (0.97 eV)" compares two forms of one compound.
        compared_with: set = set()
        for j, m in enumerate(materials):
            between = sent[materials[j - 1]["end"]:m["start"]] if j else ""
            # ... nor is the name it is given there another material: "close to Li10GeP2S12 (LGPS, 0.16 eV)".
            if is_compared_with(sent, m["start"]) or (
                    (j - 1) in compared_with and (_COORDINATED.fullmatch(between) or re.fullmatch(r'\s*\(\s*', between))):
                compared_with.add(j)
        added = {j for j, m in enumerate(materials)
                 if _ADDED_AFTER.match(sent[m["end"]:]) or _ADDED_BEFORE.search(sent[:m["start"]])}

        # "A and B, with σ = 82 mS/cm (Ea = 0.17 eV) and σ = 177 mS/cm (Ea = 0.11 eV)": materials named
        # together, then as many values of a property, each in its own clause — in the same order.
        in_order: Dict[int, int] = {}
        listed = [j for j, m in enumerate(materials) if m["formula"] not in INERT and j not in added]
        together = len({materials[j]["formula"] for j in listed}) == len(listed) >= 2 and all(
            _COORDINATED.fullmatch(sent[materials[a]["end"]:materials[b]["start"]]) for a, b in zip(listed, listed[1:]))
        for prop in {item.prop for item in found} if together else ():
            singles = [i for i, item in enumerate(found) if item.prop == prop and cls._has_context(item.cat, prop)]
            if len(singles) == len(listed) and all(found[i].size == 1 and i not in apposed for i in singles) \
                    and materials[listed[-1]]["end"] <= found[singles[0]].span[0]:
                in_order.update(zip(singles, listed))
        # "A with a conductivity of 70 mS/cm and B with one of 7 mS/cm": each value of a property
        # follows a material of its own — the one material named since the value before it.
        in_turn: Dict[int, int] = {}
        subjects = [j for j, m in enumerate(materials) if m["formula"] not in INERT and j not in added]
        for prop in {item.prop for item in found}:
            turns = sorted((i for i, item in enumerate(found) if item.prop == prop and cls._has_context(item.cat, prop)),
                           key=lambda i: found[i].span)
            pairs, start = {}, 0
            for i in turns:
                named = {materials[j]["formula"]: j for j in subjects if start <= materials[j]["start"] < found[i].span[0]
                         and not any(apposed.get(k) == j for k in turns if k != i)}
                if len(named) != 1:
                    break
                pairs[i], start = next(iter(named.values())), found[i].span[1]
            else:
                if len(turns) >= 2:
                    in_turn.update(pairs)
        for i, item in enumerate(found):
            numeric = cls._has_context(item.cat, item.prop)
            # A filler or a precursor is named next to a conductivity without it being its own; and
            # what a comparison names ("Similar to the β-Li3PS4 results, the activation energy
            # (0.67 eV) ...") is the other party, unless the value stands in the comparison too.
            in_comparison = next((c for c in compared if c[0] <= item.span[0] < c[1]), None)
            # A material bracketed with another value of the same property — "(Ea = 0.55 eV for
            # LiPON)" — is that value's alone.
            elsewhere = {apposed[k] for k, other in enumerate(found)
                         if k in apposed and k != i and other.prop == item.prop
                         and cls._bracketed_together(sent, other.span, materials[apposed[k]])}
            usable = [j for j, m in enumerate(materials)
                      if not (item.prop in QUANTITY_PROPERTIES and (m["formula"] in INERT or j in added))
                      and not (numeric and (j in elsewhere or (item.prop, j) in spoken_for
                                            or (not in_comparison and j in compared_with)))]
            if numeric:
                # "A shows 0.3 eV, whereas B shows 0.5 eV": each clause has its own subject. A value
                # keeps to the materials its clause names before it; else to those on its side of the
                # "but" / "whereas" — unless the clause refers back ("..., but their conductivities ...").
                turns = [m for m in _CONTRAST.finditer(sent)]
                after = next((m.start() for m in turns if m.start() >= item.span[1]), len(sent))
                before = max((m.end() for m in turns if m.end() <= item.span[0]), default=0)
                named_first = [j for j in usable if before <= materials[j]["start"] < item.span[0]]
                if turns and named_first:
                    usable = named_first
                elif not _REFERS_BACK.search(sent[before:item.span[0]]):
                    usable = [j for j in usable if before <= materials[j]["start"] < after] or usable
                # "A shows 3 mS/cm, whereas the Br-substituted sample shows 5 mS/cm": a value given after
                # another one of its property, for a variant named in between, is not a value of the
                # materials named before that other one.
                start = item.span[0]
                for other in sorted((o for o in found if o.prop == item.prop and o.span[1] <= start),
                                    key=lambda o: o.span, reverse=True):
                    between = sent[other.span[1]:start]
                    if _LIST_JOIN.fullmatch(between):  # the number before it in "1.5 × 10−3 and 8 × 10−5 mS/cm"
                        start = other.span[0]
                        continue
                    if _VARIANT.search(between):
                        usable = [j for j in usable if materials[j]["start"] >= other.span[1]]
                    break
            # A value inside a comparison is a value of what the comparison names.
            inside = [j for j in usable if in_comparison and in_comparison[0] <= materials[j]["start"] < in_comparison[1]]
            usable = inside if numeric and inside else usable
            chosen: Optional[Tuple[Dict[str, Any], str]] = None
            # "PLL (0.13 eV)": it names its own subject, one that is not a formula — nothing else is its
            # material. Nor is anything the material of a value quoted for a class the comparison
            # leaves unnamed ("... exceeds that of typical superionic conductors (0.1–0.3 eV)").
            labelled = numeric and i not in apposed and (
                cls._own_label(sent, materials, item)
                or bool(in_comparison and not inside and _ANOTHER_CLASS.search(sent, in_comparison[0], in_comparison[1])))
            if i in apposed:
                chosen = (materials[apposed[i]], "apposition")
            elif i in in_order:
                chosen = (materials[in_order[i]], "list_alignment")
            elif i in in_turn and in_turn[i] in usable and not labelled:
                chosen = (materials[in_turn[i]], "proximity")
            elif usable and not labelled:
                # The materials the other values of its list took for themselves are not candidates.
                siblings = [k for k, other in enumerate(found) if other.group == item.group and item.group]
                taken = {apposed[k] for k in siblings if k in apposed}
                free = [materials[j] for j in usable if j not in taken]
                waiting = [k for k in siblings if k not in apposed] or [i]
                chosen = cls._choose_material(parse, sent, free, item, len(waiting), waiting.index(i)) if free else None
                if not free:
                    usable = []
            if chosen is not None:
                cand, method = chosen
                member = cls._member(sent, cand, item, found) if numeric else None
                if member:
                    results["series"][member["formula"]] = member["series"]
                material = get_or_create_material(member or cand, score, page, section, sent, source_type)
                cls._link(results, item.field, material, method, min(0.99, score + 0.1))
                if numeric:
                    results["notes"][id(item.field)].descriptors = list(stated[materials.index(cand)])
            elif numeric and not usable and not labelled and not in_comparison \
                    and not cls._names_its_own(cls._without(sent, compared), materials, item, results["abbreviations"]):
                # "Both show barriers of 0.13 eV and 0.15 eV, respectively": one value each for the
                # materials the sentence before names, when it names as many (and different ones).
                named = next(((text, ms) for text, ms in recent if ms), ("", []))
                if item.size > 1 and paired and len({m["formula"] for m in named[1]}) == len(named[1]) == item.size:
                    earlier = (named[1][item.position], named[0], "previous_sentence")
                else:
                    # "For x = 0.25, the conductivity reaches ...": the member of the series just named.
                    earlier = cls._member_of_earlier_series(sent, recent, results.get("named_series", {}))
                    # A caption describes several panels, so the sentence before one says nothing about
                    # the material of the next: only running text may take its paragraph's topic.
                    topical = item.prop in EA_PROPERTIES and source_type == "Text" and not item.about_class
                    earlier = earlier or cls._earlier_material(recent, refers_back, topical)
                if earlier is not None:
                    cand, earlier_sentence, method = earlier
                    if cand.get("series"):
                        results["series"][cand["formula"]] = cand["series"]
                    material = get_or_create_material(cand, score, page, section, earlier_sentence, source_type)
                    cls._link(results, item.field, material, method, max(0.01, score - 0.1))

        for cand in materials:
            get_or_create_material(cand, score, page, section, sent, source_type)
        return materials

    @staticmethod
    def _member(sent: str, mention: Dict[str, Any], item: _Found, found: Sequence[_Found]) -> Optional[Dict[str, Any]]:
        """The member of a series a value is given for, where the sentence gives one value of the
        property for each value of the composition variable, in the same order: "3.9 mS/cm for
        x = 0.25 and 7.5 mS/cm for x = 0.6 in Li6+xP1-xGexS5I"."""
        if "representative" not in mention:
            return None
        stated = ChemistryEngine.stated_values(sent)
        variables = {name for name, _ in stated}
        values = [other for other in found if other.prop == item.prop and other.cat == item.cat]
        if len(variables) != 1 or len(stated) != len(values) or len(stated) < 2:
            return None
        position = next(k for k, other in enumerate(values) if other.field is item.field)
        return ChemistryEngine.member(mention, {stated[position][0]: stated[position][1]})

    @staticmethod
    def _without(sent: str, spans: Sequence[Tuple[int, int]]) -> str:
        """The sentence with these stretches blanked out, every other character where it was."""
        text = list(sent)
        for start, end in spans:
            text[start:end] = " " * (end - start)
        return "".join(text)

    @staticmethod
    def _names_its_own(sent: str, materials: List[Dict[str, Any]], item: _Found,
                       abbreviations: Optional[Abbreviations] = None) -> bool:
        """Whether a value that no material of its sentence can take still says what it is a value
        of: a filler or an electrode the sentence names, a family ("Li3MX6"), a sample label, "the
        undoped sample"."""
        if item.prop in QUANTITY_PROPERTIES and any(m["formula"] in INERT for m in materials):
            return True
        if ChemistryEngine.names_a_variant(sent, abbreviations):
            return True
        # "the conductivity of PPS-QSSE ...": a sample the sentence names by a label that is no formula.
        for label in _ANY_LABEL.finditer(sent):
            if label.group(1).upper().rstrip("S") not in {name.rstrip("S") for name in _NOT_A_LABEL} \
                    and not any(m["start"] <= label.start(1) < m["end"] for m in materials):
                return True
        return bool(_VARIANT.search(sent))

    @staticmethod
    def _bracketed_together(sent: str, value: Tuple[int, int], mention: Dict[str, Any]) -> bool:
        """Whether a value and a material stand inside the same pair of brackets."""
        left, right = min(value[0], mention["start"]), max(value[1], mention["end"])
        opened = sent.rfind("(", 0, left)
        return opened > sent.rfind(")", 0, left) and ")" not in sent[left:right] and "(" not in sent[left:right] \
            and sent.find(")", right) != -1

    @staticmethod
    def _own_label(sent: str, materials: List[Dict[str, Any]], item: _Found) -> bool:
        """Whether a value is attached to a sample label that is no material of the sentence:
        "PLL (0.13 eV)", "0.04 eV in NLZC", "the activation energy of PL is 0.26 eV"."""
        after = _OWN_LABEL_AFTER.match(sent[item.span[1]:])
        before = _OWN_LABEL_BEFORE.search(sent[:item.span[0]])
        named = _OWN_LABEL_NAMED.search(sent[item.anchor[0]:item.list_start]) if item.anchor[0] < item.list_start else None
        for label, offset in ((after, item.span[1]), (before, 0), (named, item.anchor[0])):
            if label and label.group(1).upper().rstrip("S") not in {name.rstrip("S") for name in _NOT_A_LABEL}:
                start = label.start(1) + offset
                if not any(m["start"] <= start < m["end"] for m in materials):
                    return True
        return False

    @staticmethod
    def _apposed(sent: str, materials: List[Dict[str, Any]], span: Tuple[int, int], after: bool = True) -> Optional[int]:
        """The index of the mention a value stands right next to (see _APPOSED_AFTER), if any.
        `after` is unset where "0.4 eV for A" opens a list of materials rather than naming the
        value's own ("... 0.3 and 0.4 eV for A and B, respectively")."""
        start, end = span
        for j, mention in enumerate(materials):
            if after and mention["start"] >= end and _APPOSED_AFTER.match(sent[end:mention["start"]]):
                return j
        for j, mention in enumerate(materials):
            if mention["end"] <= start:
                between = sent[mention["end"]:start]
                if _APPOSED_BEFORE.match(between) or (_COPULA.match(between) and _THAT_OF.search(sent[:mention["start"]])):
                    return j
        return None

    @classmethod
    def _choose_material(cls, parse: Callable[[], Any], sent: str, materials: List[Dict[str, Any]], item: _Found,
                         waiting: int = 1, turn: int = 0) -> Optional[Tuple[Dict[str, Any], str]]:
        """The mention a value is for, as (mention, link method) — or None when the sentence names
        several materials and cannot say which one this value belongs to. `materials` are the
        mentions still free; `waiting` values of its list have no material yet and this is the
        turn-th of them."""
        if len({m["formula"] for m in materials}) == 1:
            return materials[0], "proximity"
        # "the activation energy of LLZO is 0.30 eV, lower than that of LATP": named with the quantity.
        named = [m for m in materials if item.anchor[0] <= m["start"] and m["end"] <= item.list_start]
        if item.anchor[0] < item.list_start and len({m["formula"] for m in named}) == 1:
            return named[0], "named_with_quantity"
        if item.size > 1:  # one of "0.6, 1.2 and 1.5 eV"
            # "A, B and C ... 0.6, 1.2 and 1.5 eV, respectively": the lists are paired off.
            if len(materials) == waiting and pairs_off(sent):
                return materials[turn], "list_alignment"
            return None
        return cls._link_property_to_material(parse(), materials, *item.span)

    @staticmethod
    def _member_of_earlier_series(sent: str, recent: Sequence[Tuple[str, List[Dict[str, Any]]]],
                                  named_series: Optional[Dict[str, Dict[str, Any]]] = None
                                  ) -> Optional[Tuple[Dict[str, Any], str, str]]:
        """A sentence that names no material but fixes one composition variable ("For x = 0.25, ...") is
        about that member of the series the nearest of the previous _BACKREF_SENTENCES names — when it
        names one series only, and the variable is one of its own. Else, when the paper so far has named
        one series only with that variable (`named_series`), about that series' member ("The x = 50
        samples ..." pages after "(100−x)(0.75Li2S·0.25P2S5)·xLiBH4"): a value of x means a series."""
        stated = ChemistryEngine.stated_values(sent)
        if len({name for name, _ in stated}) != 1 or len({value for _, value in stated}) != 1:
            return None
        variable, value = stated[0]

        def has_variable(mention: Dict[str, Any]) -> bool:
            return variable in re.sub(r"[A-Z][a-z]?", "", mention.get("written", mention["raw"]))

        for text, mentions in list(recent)[:_BACKREF_SENTENCES]:
            series = {m["formula"]: m for m in mentions if "representative" in m or m.get("open_series")}
            if not mentions:
                continue
            if len(series) != 1:
                break
            mention = next(iter(series.values()))
            if not has_variable(mention):
                break
            member = ChemistryEngine.member(mention, {variable: value})
            return (member, text, "previous_sentence") if member else None
        # Only a series this value of x gives a composition: x = 50 is no member of Li7−xPS6−x(BH4)x.
        members = [(member, m) for m in (named_series or {}).values() if has_variable(m)
                   for member in [ChemistryEngine.member(m, {variable: value})] if member]
        if len(members) == 1:
            member, mention = members[0]
            return member, mention.get("raw", ""), "paper_series"
        return None

    @staticmethod
    def _earlier_material(recent: Sequence[Tuple[str, List[Dict[str, Any]]]], refers_back: bool,
                          topical: bool) -> Optional[Tuple[Dict[str, Any], str, str]]:
        """The material a sentence that names none is about, from the sentences just before it:
        (mention, the sentence naming it, link method) — see _BACKREF_SENTENCES / _TOPIC_SENTENCES."""
        recent = [(text, [m for m in mentions if m["formula"] not in INERT]) for text, mentions in recent]
        if refers_back:
            named = next(((s, ms) for s, ms in recent[:_BACKREF_SENTENCES] if ms), None)
            if named and len({m["formula"] for m in named[1]}) == 1:
                return named[1][0], named[0], "previous_sentence"
        if topical:
            window = recent[:_TOPIC_SENTENCES]
            leaders = Counter(m["formula"] for _, ms in window for m in ms).most_common(2)
            # The only material those sentences name, or one they name at least twice as often as any other.
            if leaders and (len(leaders) == 1 or leaders[0][1] >= max(2, 2 * leaders[1][1])):
                return next((m, s, "paragraph_topic") for s, ms in window for m in ms
                            if m["formula"] == leaders[0][0])
        return None

    # ------------------------------------------------------------------
    # Tables (schema section 8): structured row/column relations, deterministic — no NLP needed.
    # ------------------------------------------------------------------
    @classmethod
    def _process_table_block(cls, block: Dict[str, Any], results: Dict[str, Any], get_or_create_material) -> None:
        page, section = str(block["page"]), block["section"]
        results["tables"].append(TableRecord(
            table_number=block.get("table_number", "NONE"), caption=block.get("caption", "NONE"),
            page=page, section=section, headers=block.get("headers", []), rows=block.get("rows", []),
            material_column=block.get("material_column", "NONE"), raw_text=block.get("text", "NONE"),
        ))

        abbreviations = results["abbreviations"]
        caption = block.get("caption", "NONE")
        rows = block.get("rows", [])
        material_column = cls._material_column(block, abbreviations)
        headers = [h for h in block.get("headers", []) if h != material_column]
        header_props = {h: cls._match_header_property(h) for h in headers}
        # Only a table whose own caption was found has a number of its own ("Table 2"); the
        # parser's per-page index is not one.
        source_label = f"Table {block.get('table_number')}" if caption != "NONE" else "Table"
        cited_refs = cls._cited_refs(caption, source_label)
        # A table with no material column is about the material its caption names, if it names one.
        caption_materials = ChemistryEngine.find_materials(caption, abbreviations) if material_column == "NONE" else []
        caption_material = caption_materials[0] if len({m["formula"] for m in caption_materials}) == 1 else None
        # A table with a column of references collects other people's values.
        quoted = any(_REFERENCE_HEADER.search(h) for h in block.get("headers", [])) or is_quoted(caption)

        # A table of a series, one row per value of its variable: the column headed "x" ("x (Ga)",
        # "x Ga") under a caption naming "Li4-xZn1-xGax(PO4)2" gives each row's member.
        variable_column = cls._variable_column(block, caption_material)

        for row in rows:
            row_text = " ".join(str(v) for h, v in row.items() if not header_props.get(h))
            row_label = next((str(v) for v in row.values() if v), "")
            conditions, row_structure = cls._row_conditions(row), cls._row_structure(row)
            row_material = None
            if variable_column:
                header, variable = variable_column
                number = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", str(row.get(header, "")))
                member = ChemistryEngine.member(caption_material, {variable: float(number.group(1))}) if number else None
                if member:
                    results["series"][member["formula"]] = member["series"]
                    row_material = get_or_create_material(member, 0.85, page, section, caption, "Table")
            if material_column != "NONE":
                cell_materials = ChemistryEngine.find_materials(row.get(material_column, ""), abbreviations)
                if cell_materials:
                    row_material = get_or_create_material(cell_materials[0], 0.85, page, section, caption, "Table")
                    results["structure_votes"][row_material.normalized_formula].update(row_structure)
            for header, cell_value in row.items():
                if header == material_column or not cell_value:
                    continue
                prop_info = header_props.get(header)
                if not prop_info:
                    continue
                cat, prop = prop_info
                field = cls._extract_cell_value(cell_value, header, cat, prop, page, section, block)
                if field is None:
                    continue
                field.source_label, field.cited_refs = source_label, cited_refs
                field.source_detail = f"row: {row_label[:60]} | column: {header}"
                if prop in EA_PROPERTIES:
                    field.reported_as = re.sub(r'\s*\([^)]*\)\s*$', '', header).strip().lower() or "NONE"
                if prop in TRANSPORT_PROPERTIES:
                    # Column header ("Ea,bulk (eV)"), row label ("Grain boundary") or caption.
                    result = classify_transport_contexts((header, row_text, caption))
                    field.transport_component = result.component
                    field.transport_component_evidence, field.dominant_component = result.evidence, result.dominant
                    if result.component != UNSPECIFIED:
                        field.basis["component"] = f"table ({cls._quote(result.evidence)})"
                if cls._has_context(cat, prop):
                    # The row's own condition columns first, then the header, row label and caption.
                    ctx = table_context((*conditions, header, row_text, caption), SchemaConfig.SCHEMA[cat][prop][1])
                    field.temperature, field.pressure = ctx.temperature, ctx.pressure
                    field.data_origin, field.data_origin_evidence = ctx.origin, ctx.origin_evidence
                    for name, stated in (("temperature", ctx.temperature != "NONE"), ("pressure", ctx.pressure != "NONE"),
                                         ("origin", ctx.origin != UNSPECIFIED)):
                        if stated:
                            field.basis[name] = "table"
                    field.structure = describe(row_structure)
                    results["notes"][id(field)] = _Note(descriptors=list(row_structure), quoted=quoted,
                                                        technique=technique(f"{header} {caption}"),
                                                        interface=names_interface(f"{header} {row_text}"))
                results[cat][prop].append(field)
                if row_material is not None:
                    cls._link(results, field, row_material, "table_row", 0.95)
                elif caption_material is not None:
                    material = get_or_create_material(caption_material, 0.85, page, section, caption, "Table")
                    cls._link(results, field, material, "table_caption", 0.75)

    @staticmethod
    def _variable_column(block: Dict[str, Any], series: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
        """(header, variable) of the column that gives each row the value of the caption's series
        variable — a header that is the variable ("x", "x (Ga)", "x Ga", "x in Li7-xLa3Zr2-xTaxO12") of a
        series the caption names; None otherwise."""
        if not series or "representative" not in series:
            return None
        written = re.sub(r"[A-Z][a-z]?", "", series.get("written", series["raw"]))
        for header in block.get("headers", []):
            m = re.match(r"^\s*([xyzδ])(?:\s*(?:\(|\b[A-Z][a-z]?\b|in\b|=|value)|\s*$)", str(header))
            if m and m.group(1) in written:
                return header, m.group(1)
        return None

    @staticmethod
    def _material_column(block: Dict[str, Any], abbreviations: Optional[Abbreviations]) -> str:
        """The column that names each row's material: the one the parser recognised by its header
        ("Material", "Sample"), else the first column in which most cells are a material."""
        column = block.get("material_column", "NONE")
        rows = block.get("rows", [])
        if column != "NONE" or len(rows) < 2:
            return column
        for header in block.get("headers", []):
            cells = [str(row.get(header, "")) for row in rows if row.get(header)]
            named = sum(1 for cell in cells if len(cell) <= 60 and ChemistryEngine.find_materials(cell, abbreviations))
            if len(cells) >= 2 and named >= 0.6 * len(cells):
                return header
        return "NONE"

    @staticmethod
    def _row_conditions(row: Dict[str, str]) -> List[str]:
        """A row's own conditions, read off its temperature/pressure columns and phrased the way
        context.table_context reads them in prose: "T (K)" = "300" -> "at 300 K"."""
        phrases = []
        for header, cell in row.items():
            if not cell:
                continue
            if _TEMPERATURE_HEADER.search(header):
                unit = _TEMPERATURE_UNIT.search(header)
                phrases.append(f"at {cell} {unit.group() if unit else ''}")
            elif _PRESSURE_HEADER.search(header):
                unit = _PRESSURE_UNIT.search(header)
                phrases.append(f"pressure of {cell} {unit.group() if unit else ''}")
        return phrases

    @staticmethod
    def _row_structure(row: Dict[str, str]) -> List[Descriptor]:
        """Structure descriptors in a row's "Space group" / "Crystal system" / "Phase" columns."""
        found: List[Descriptor] = []
        for header, cell in row.items():
            if cell and _STRUCTURE_HEADER.search(header):
                # Under a "Space group" header a bare symbol is one (see context._SPACE_GROUP).
                text = f"space group {cell}" if re.search(r'(?i)space\s*group|symmetry', header) else cell
                found.extend((kind, label) for _, _, kind, label in find_structures(text))
        return found

    @staticmethod
    def _match_header_property(header: str) -> Optional[Tuple[str, str]]:
        if _EA_HEADER_REGEX.match(header):
            return "ELECTROCHEMICAL", "Activation_Energy"
        # PDF tables often lose the spaces of a header ("Migrationenergybarrier(eV)").
        squeezed = re.sub(r'[\s_]+', '', header.lower())
        for keyword, cat, prop in _HEADER_PROPERTY_KEYWORDS:
            if keyword.replace(" ", "") in squeezed:
                return cat, prop
        if _SIGMA_HEADER_REGEX.search(header):
            return "ELECTROCHEMICAL", "Ionic_Conductivity"
        return None

    @staticmethod
    def _extract_cell_value(cell_value: str, header: str, cat: str, prop: str, page: str, section: str,
                             block: Dict[str, Any]) -> Optional[ExtractedField]:
        _, norm_type = SchemaConfig.SCHEMA[cat][prop]
        pattern = _CELL_MAGNITUDE_UNIT if norm_type in ("conductivity", "diffusion") else _CELL_NUM_UNIT
        m = pattern.match(cell_value.strip())
        if not m:
            return None
        value_str, unit_str = m.group(1), (m.group(2) or "").strip()
        if not unit_str:
            # Last bracketed group: "Ea (GB) (eV)" has a qualifier before the unit.
            header_units = _HEADER_UNIT.findall(header)
            unit_str = header_units[-1].strip() if header_units else ""
        normalized = DataNormalizer.normalize((value_str, unit_str), norm_type)
        if normalized == "NONE" or (prop in EA_PROPERTIES and not float(normalized.split(" ", 1)[0]) > 0):
            return None
        unit = normalized.split(" ", 1)[1] if " " in normalized else "NONE"
        return ExtractedField(
            raw_value=cell_value, normalized_value=normalized, confidence=0.9,
            source_page=page, source_section=section, source_sentence=block.get("caption", "NONE"),
            source_type="Table", unit=unit, category=cat, property_name=prop,
        )

    # ------------------------------------------------------------------
    # Figures (schema section 9)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_figure(block: Dict[str, Any], abbreviations: Optional[Abbreviations] = None) -> FigureRecord:
        caption = block["text"]
        materials = [m["formula"] for m in ChemistryEngine.find_materials(caption, abbreviations)]
        properties = []
        for cat, props in SchemaConfig.COMPILED_SCHEMA.items():
            for prop, (pattern, _) in props.items():
                if pattern.search(caption):
                    properties.append(prop)
        techniques = SchemaConfig.COMPILED_SCHEMA["CHARACTERIZATION"]["Technique"][0].findall(caption)
        return FigureRecord(
            figure_number=block.get("ref_number", "NONE"), caption=caption,
            page=str(block["page"]), section=block["section"],
            referenced_materials=list(dict.fromkeys(materials)),
            referenced_properties=list(dict.fromkeys(properties)),
            referenced_tables=list(dict.fromkeys(_TABLE_REF_REGEX.findall(caption))),
            referenced_equations=list(dict.fromkeys(_EQ_REF_REGEX.findall(caption))),
            mentioned_methods=list(dict.fromkeys(techniques)),
        )

    # ------------------------------------------------------------------
    # Equations (schema section 10)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_variables(text: str) -> List[str]:
        out = []
        for tok in _VAR_TOKEN_REGEX.findall(text):
            if len(tok) <= 3 and tok.lower() not in _VAR_STOPWORDS and tok not in out:
                out.append(tok)
        return out[:8]

    @classmethod
    def _classify_equation(cls, text: str) -> str:
        for pattern, etype in _EQUATION_TYPE_PATTERNS:
            if pattern.search(text):
                return etype
        return "Unclassified"

    @staticmethod
    def _equation_form(text: str) -> Optional[str]:
        """What an equation found by its "=" is, from its form; None for what only looks like one —
        a value ("x = 0", "Ea = 0.3 eV"), a substitution ("X = Cl or Br"), a sentence."""
        text = text.strip()
        if len(re.findall(r"[A-Za-z]{3,}", text)) >= 7:
            return None  # a sentence with an "=" in it
        if _LINEAR_FIT.match(text):
            return "Linear fit"
        sides = _EQUATION_SIDES.split(text, maxsplit=1)
        if len(sides) == 2 and "+" in text and all(ChemistryEngine.find_materials(side) for side in sides):
            return "Chemical reaction"
        if _SUBSTITUTION.search(text):
            return None
        left, _, right = text.partition("=")
        if not right.strip() or (len(left.strip()) <= 15 and _BARE_VALUE.fullmatch(right)):
            return None
        if _OPERATOR.search(right):
            return "Arrhenius" if _ARRHENIUS_FORM.search(right) else "Expression"
        return None

    @classmethod
    def _record_equation(cls, results: Dict[str, Any], equation_text: str, context: str, page: str,
                          section: str, seen: set, force: bool = False) -> None:
        etype = cls._classify_equation(equation_text)
        if etype == "Unclassified":
            form = cls._equation_form(equation_text) if force else None
            if form is None:
                return
            etype = form
        key = etype if etype != "Unclassified" else f"unclassified:{page}:{equation_text[:30]}"
        if key in seen:
            return
        seen.add(key)
        results["equations"].append(EquationRecord(
            equation_text=equation_text, equation_type=etype, page=page, section=section,
            variables=cls._extract_variables(equation_text), context_sentence=context,
        ))

    @classmethod
    def _scan_equation_mentions(cls, sent: str, page: str, section: str, seen: set, results: Dict[str, Any]) -> None:
        for pattern, etype in _EQUATION_TYPE_PATTERNS:
            if etype in seen:
                continue
            if pattern.search(sent):
                cls._record_equation(results, sent, sent, page, section, seen)
