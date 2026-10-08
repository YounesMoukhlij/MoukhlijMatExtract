# models.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExtractedField:
    """A single extracted datum with full provenance.

    Kept as the one universal "value" type used across materials, properties,
    metadata, equations, etc. `unit`/`value_numeric`/`category`/`property_name`
    are optional enrichments (default "NONE"/None) so every existing positional
    call site (7 required args) keeps working unchanged.
    """
    raw_value: str
    normalized_value: str
    confidence: float
    source_page: str
    source_section: str
    source_sentence: str
    source_type: str  # Text, Figure, Table, Metadata — where in the paper the value sits
    unit: str = "NONE"
    value_numeric: Optional[float] = None
    category: str = "NONE"
    property_name: str = "NONE"
    # Only set for the ion-transport properties (config.TRANSPORT_PROPERTIES): "bulk",
    # "grain_boundary", "surface", "total" or "unspecified" (see transport.classify_transport).
    # "NONE" for every other property.
    transport_component: str = "NONE"
    # Verbatim text tying the value to that component; "NONE" when unspecified.
    transport_component_evidence: str = "NONE"
    # Only for "total" values the text says are dominated by one component ("NONE" otherwise).
    dominant_component: str = "NONE"
    # "Figure 3" / "Table 2" the value sits in (its caption or one of its cells); "NONE" for body text.
    source_label: str = "NONE"
    # "caption", or the row and column of a table cell; "NONE" for body text.
    source_detail: str = "NONE"
    # Figures/tables the source sentence itself points to ("Figure 4b | Table 1").
    cited_refs: str = "NONE"
    # The material the value was obtained for and how it was tied to it (the same label as
    # Relation.extraction_method); "NONE" when no material could be established.
    material_id: str = "NONE"
    material_formula: str = "NONE"
    material_link: str = "NONE"
    # Measurement context (see context.py), only set for numeric material properties: the crystal
    # structure the value is quoted for ("cubic | garnet | Ia-3d"), the temperature ("300 K",
    # "room temperature") and pressure ("0.005 GPa", "ambient pressure") it holds at, and whether
    # it is "experimental" or from "simulation" ("unspecified" when the text doesn't establish it;
    # "NONE" for every other property) with the verbatim cue that decided it.
    structure: str = "NONE"
    temperature: str = "NONE"
    pressure: str = "NONE"
    data_origin: str = "NONE"
    data_origin_evidence: str = "NONE"
    # Where each of those answers comes from — "structure", "temperature", "pressure", "origin",
    # "component" -> "stated" (the value's own sentence), "context" (the sentences before it),
    # "caption of Figure 3", "table", "paper" (stated once for the whole study), "known" (a
    # structure family that follows from the composition), "assumed" (a convention, with its
    # reason) or "not stated". Empty for the properties that have no measurement context.
    basis: Dict[str, str] = field(default_factory=dict)
    # The paper's own wording for the quantity ("migration barrier", "Ea"); only kept for the
    # activation energy, which papers name in a dozen ways.
    reported_as: str = "NONE"
    # "this work" for a result of the paper itself, "cited" for one it quotes from another source.
    attribution: str = "NONE"

    @classmethod
    def empty(cls) -> "ExtractedField":
        return cls("NONE", "NONE", 0.0, "NONE", "NONE", "NONE", "NONE")

    def is_empty(self) -> bool:
        return self.raw_value == "NONE"

    def to_flat_dict(self, prefix: str) -> Dict[str, Any]:
        """Flattens this field into prefixed columns for the legacy flat summary export."""
        optional = {
            "Type": self.transport_component, "Source": self.source_label, "Material": self.material_formula,
            "Temperature": self.temperature, "Pressure": self.pressure, "Origin": self.data_origin,
        }
        return {
            f"{prefix}_Raw": self.raw_value,
            f"{prefix}_Value": self.normalized_value,
            f"{prefix}_Unit": self.unit,
            f"{prefix}_Confidence": round(self.confidence, 3) if self.confidence else 0.0,
            f"{prefix}_Page": self.source_page,
            f"{prefix}_Section": self.source_section,
            f"{prefix}_SourceType": self.source_type,
            **{f"{prefix}_{name}": value for name, value in optional.items() if value != "NONE"},
        }


@dataclass
class Relation:
    """Links one material to one property value, with the method used to establish the link."""
    material_id: str
    material_formula: str
    category: str
    property_name: str
    property_value: ExtractedField
    confidence: float
    source_sentence: str
    source_page: str
    # apposition ("0.31 eV (LLZO)") | named_with_quantity ("the conductivity of LLZO is ...") |
    # dependency_parse | proximity | list_alignment | table_row, or — when the value's own
    # sentence/row names no material — previous_sentence | paragraph_topic | table_caption
    extraction_method: str


@dataclass
class Material:
    """A material/composition found in a paper, with its own attached properties (schema section 16)."""
    material_id: str
    raw_formula: str
    normalized_formula: str
    # Atoms per formula unit; for the general formula of a series ("Li3-xY1-xZrxCl6") an amount
    # can be an expression in x.
    elements: Dict[str, Any]
    is_known_alias: bool
    confidence: float
    source_page: str
    source_section: str
    source_sentence: str
    source_type: str
    properties: List[ExtractedField] = field(default_factory=list)
    # Every structure the paper states for this formula ("cubic | garnet | Ia-3d"); when it states
    # none, the structure family that follows from the composition; "NONE" if neither. And which
    # of the two it is: "stated", "known for this composition" or "not stated".
    structure: str = "NONE"
    structure_basis: str = "NONE"
    # Shannon ionic radius (Å) of each constituent ion, e.g. {"Li+": 0.76, "O2-": 1.4} (chemistry.ionic_radii).
    ionic_radii: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "Material":
        return cls("NONE", "NONE", "NONE", {}, False, 0.0, "NONE", "NONE", "NONE", "NONE")


@dataclass
class TableRecord:
    table_number: str
    caption: str
    page: str
    section: str
    headers: List[str] = field(default_factory=list)
    rows: List[Dict[str, str]] = field(default_factory=list)
    material_column: str = "NONE"
    raw_text: str = "NONE"


@dataclass
class FigureRecord:
    figure_number: str
    caption: str
    page: str
    section: str
    referenced_materials: List[str] = field(default_factory=list)
    referenced_properties: List[str] = field(default_factory=list)
    referenced_tables: List[str] = field(default_factory=list)
    referenced_equations: List[str] = field(default_factory=list)
    mentioned_methods: List[str] = field(default_factory=list)


@dataclass
class EquationRecord:
    equation_text: str
    equation_type: str
    page: str
    section: str
    variables: List[str] = field(default_factory=list)
    context_sentence: str = "NONE"


@dataclass
class WorkflowStep:
    order: int
    stage: str
    evidence_sentence: str
    page: str
    section: str


@dataclass
class PaperData:
    filename: str
    metadata: Dict[str, ExtractedField]

    # Per-material extraction (schema section 16): each material carries its own properties.
    materials: List[Material] = field(default_factory=list)

    # Paper-level (not tied to one material) categorized candidate lists — DFT/AIMD/ML/synthesis
    # settings usually describe the whole computational/experimental study, not a single material.
    electrochemical: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    thermodynamic: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    mechanical: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    structural: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    electronic: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    thermal: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    spectroscopy: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    dft: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    aimd: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    ml: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    synthesis: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    characterization: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    battery_perf: Dict[str, List[ExtractedField]] = field(default_factory=dict)
    interfaces: Dict[str, List[ExtractedField]] = field(default_factory=dict)

    relations: List[Relation] = field(default_factory=list)
    workflow: List[WorkflowStep] = field(default_factory=list)
    figures: List[FigureRecord] = field(default_factory=list)
    tables: List[TableRecord] = field(default_factory=list)
    equations: List[EquationRecord] = field(default_factory=list)
    references: List[str] = field(default_factory=list)

    # "local" for a PDF you supplied, "web" for one the web project fetched; and, for a web paper,
    # what the fetch recorded: source, URL, license, retrieval date, checksum (see web/sidecar.py).
    origin: str = "local"
    provenance: Dict[str, str] = field(default_factory=dict)
