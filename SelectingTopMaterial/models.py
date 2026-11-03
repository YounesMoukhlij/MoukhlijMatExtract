# SelectingTopMaterial/models.py
"""What flows through the selection: a value as a paper reports it, a material with the class its
values earn it, and the whole ranking with what it was built from."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .criteria import Criteria, EnergyClass

# What a cell says when the database does not answer it. The database's own word for that is
# NONE; the tables written here spell it out instead.
NOT_REPORTED = "not reported"

# The transport components an activation energy can describe, each ranked on its own: a bulk Ea and
# a total (bulk + grain boundary) Ea are not the same quantity, and are never compared.
COMPONENTS = ("bulk", "grain_boundary", "total")
_COMPONENT_WORDS = {"bulk": "bulk", "grain_boundary": "grain boundary", "total": "total",
                    "not_reported": "component not stated"}


def component_key(text: str) -> str:
    """One spelling of a component: "Grain boundary", "grain-boundary" → "grain_boundary"."""
    return re.sub(r"[\s\-]+", "_", (text or "").strip().casefold())


def component_word(key: str) -> str:
    """A component in words: "grain_boundary" → "grain boundary"."""
    key = component_key(key)
    return _COMPONENT_WORDS.get(key, key.replace("_", " "))


@dataclass(frozen=True, slots=True)
class Measurement:
    """One activation energy of one material, with where it was read and what it holds for."""
    material: str                 # the formula as the database spells it
    material_key: str             # the same for every spelling of one composition
    elements: tuple[str, ...]
    energy_eV: float
    reported_as: str              # the paper's own word: "migration barrier", "Ea", ...
    structure: str
    polymorph: str                # "cubic", "β-phase", ... — empty when the structure names none
    temperature: str
    pressure: str
    data_origin: str              # experimental / simulation
    transport_component: str      # bulk / total / grain boundary / ...
    attribution: str              # this work / cited
    confidence: float
    paper_id: str
    paper_key: str                # the DOI when the database has it: one paper under two file names
    paper_title: str
    doi: str
    year: str
    database: str                 # the results folder the value was read from
    extracted_from: str           # Text / Figure / Table
    page: str
    source: str
    section: str
    sentence: str


@dataclass(frozen=True, slots=True)
class Filters:
    """Which values take part in the ranking. Left as it is, all of them do."""
    min_confidence: float = 0.0
    origin: str = ""              # "experimental" or "simulation"
    attribution: str = ""         # "this work" or "cited"
    component: str = ""           # "bulk", "total", ...
    elements: tuple[str, ...] = ()

    def keeps(self, value: Measurement) -> bool:
        return (value.confidence >= self.min_confidence
                and (not self.origin or value.data_origin.casefold() == self.origin.casefold())
                and (not self.attribution or value.attribution.casefold() == self.attribution.casefold())
                and (not self.component or component_key(value.transport_component) == component_key(self.component))
                and all(element in value.elements for element in self.elements))

    def describe(self) -> str:
        """The filters in words: "experimental values · confidence ≥ 0.5"; "all values" when none is set."""
        parts = []
        if self.origin:
            parts.append(f"{self.origin} values")
        if self.attribution:
            parts.append(f"{self.attribution} only")
        if self.component:
            parts.append(f"{component_word(self.component)} transport")
        if self.elements:
            parts.append(f"materials with {' + '.join(self.elements)}")
        if self.min_confidence > 0:
            parts.append(f"confidence ≥ {self.min_confidence:g}")
        return " · ".join(parts) or "all values"


@dataclass(frozen=True, slots=True)
class RankedMaterial:
    """A material in the ranking: the activation energy that stands for it, the class that
    energy earns, and every value behind it."""
    rank: int
    material: str
    energy_class: EnergyClass
    energy_eV: float
    values: tuple[Measurement, ...]          # lowest energy first
    votes: tuple[tuple[str, int], ...]       # (class, how many of the values fall in it), best class first
    checks: tuple[str, ...]                  # what to look at before trusting the class; empty when nothing
    confidence: float                        # mean extraction confidence of the values
    evidence: Measurement                    # the reported value closest to energy_eV

    @property
    def accepted(self) -> bool:
        return self.energy_class.accepted

    @property
    def energy_min_eV(self) -> float:
        return self.values[0].energy_eV

    @property
    def energy_max_eV(self) -> float:
        return self.values[-1].energy_eV

    @property
    def papers(self) -> tuple[str, ...]:
        """The papers the values come from, each once, in the order of the values."""
        return tuple(dict.fromkeys(v.paper_key for v in self.values))


@dataclass(frozen=True, slots=True)
class DatabaseReport:
    """What one results folder gave: how much was read, and what was left aside and why."""
    name: str
    path: str
    values: int = 0                          # values that take part
    papers: int = 0
    rows: int = 0                            # rows of activation_energy.csv
    already_read: int = 0                    # rows of papers an earlier folder already gave
    repeated: int = 0                        # the same value given twice by one paper
    unreadable: int = 0                      # rows without a material or a usable number
    unassigned: int = 0                      # activation energies the extraction tied to no material
    problem: str = ""                        # why nothing could be read, when nothing could


@dataclass(frozen=True, slots=True)
class Selection:
    """The ranking: every material that has an activation energy, best first, the rejected ones
    last — with the rule and the data it was made from."""
    criteria: Criteria
    policy: str
    by_phase: bool
    filters: Filters
    materials: tuple[RankedMaterial, ...]
    databases: tuple[DatabaseReport, ...]
    values_read: int                         # before the filters
    generated_at: str
    notes: tuple[str, ...] = field(default=())

    @property
    def top(self) -> tuple[RankedMaterial, ...]:
        """The materials that pass: every class but the rejected one."""
        return tuple(m for m in self.materials if m.accepted)

    @property
    def rejected(self) -> tuple[RankedMaterial, ...]:
        return tuple(m for m in self.materials if not m.accepted)

    @property
    def values_used(self) -> int:
        return sum(len(m.values) for m in self.materials)

    @property
    def papers_used(self) -> int:
        return len({v.paper_key for m in self.materials for v in m.values})

    @property
    def component(self) -> str:
        """The transport component this ranking is of ("bulk", "grain_boundary", "total"); "" for all."""
        return component_key(self.filters.component)

    def count(self, energy_class: EnergyClass) -> int:
        return sum(1 for m in self.materials if m.energy_class == energy_class)
