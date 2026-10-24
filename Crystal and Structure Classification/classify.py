# Crystal and Structure Classification/classify.py
"""Which crystal-structure type and which chemical family a material belongs to.

    crystal structure   the known crystal family it belongs to: NASICON, LISICON, thio-LISICON, garnet,
                        argyrodite, perovskite, anti-perovskite, spinel, olivine, layered, rock-salt,
                        anti-fluorite, ... — or amorphous / glass-ceramic; a material of none of them
                        is "no known crystal family" (a type named after a compound — LGPS-type,
                        Li3YCl6-type — is not a family)
    structure family    the family of compounds it belongs to, named after its anions: oxide,
                        sulfide, halide, oxyhalide, nitride, hydride, ...

The structure type is taken, in this order, from what settles it best:

    1. the composition, when it leaves no doubt (Li7La3Zr2O12 is a garnet, Li6PS5Cl an argyrodite):
       the rule of the extraction itself, LocalExtraction.chemistry.ChemistryEngine.structure_family
    2. the same rule on a composition series taken at its nominal value (Li6+xP1-xGexS5I at x = 0.25)
    3. what the papers state about the material ("NASICON-type", "the garnet LLZO"), the type
       stated by the most papers winning — if at least a third of its papers state it
    4. a state instead of a structure ("glass", "amorphous", "glass-ceramic") — if most of its
       papers state it: a glassy sample in one paper does not make the material a glass
    5. the family its composition type belongs to: a lithium-rich orthooxide A3-4MX4 is LISICON,
       its sulfide thio-LISICON
    6. a family or a state stated by fewer of its papers than above (the basis says how few)
    7. the family of the materials of the same composition type and family (an analogue)
    8. otherwise: no known crystal family — its composition type ("A3MX6 halide") is in a column
       of its own, and a type named after a compound its composition or its papers give
       (LGPS-type, Li3YCl6-type) is said in its basis

`crystal_structure_basis` says which of these steps decided — a family the papers state is told
apart from one inferred.

The chemical family always follows from the composition (ChemistryEngine.compound_class), so
every material with a known composition has one. Each answer says where it came from (`*_basis`)."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from LocalExtraction.chemistry import ChemistryEngine, _nominal

from .about import UNCLASSIFIED

# The transport components an activation energy is told apart by (the extraction's
# `transport_component`): the barrier inside the grains, across their boundaries, or of the whole sample.
COMPONENTS = ("bulk", "grain_boundary", "total")
COMPONENT_WORDS = {"bulk": "bulk", "grain_boundary": "grain-boundary", "total": "total", "surface": "surface"}

# ---------------------------------------------------------------------------
# The labels of the structure column
# ---------------------------------------------------------------------------
# The structure column of the databases holds several kinds of label, "cubic | garnet | Ia-3d":
# the crystal system, the structure type, the space group, a polymorph, the state.
CRYSTAL_SYSTEMS = ("cubic", "tetragonal", "orthorhombic", "hexagonal", "trigonal", "rhombohedral", "monoclinic",
                   "triclinic")
_STATES = {"amorphous": "amorphous", "glass": "amorphous", "glassy": "amorphous", "glasses": "amorphous",
           "glass-ceramic": "glass-ceramic", "glass-ceramics": "glass-ceramic"}
# Every spelling of a structure type, folded (lower case, no space or hyphen) → its one name.
_TYPES = {
    "garnet": "garnet", "nasicon": "NASICON", "lisicon": "LISICON", "thiolisicon": "thio-LISICON",
    "argyrodite": "argyrodite", "perovskite": "perovskite", "antiperovskite": "anti-perovskite",
    "spinel": "spinel", "olivine": "olivine", "layered": "layered", "rocksalt": "rock-salt",
    "antifluorite": "anti-fluorite", "fluorite": "fluorite", "wurtzite": "wurtzite", "zincblende": "zinc-blende",
    "tavorite": "tavorite",
}
# The classes of the crystal axis: the known crystal families, and the two states of no crystal structure.
KNOWN_FAMILIES = (*dict.fromkeys(_TYPES.values()), "amorphous", "glass-ceramic")
# What a material of none of them is.
NO_FAMILY = "no known crystal family"
# A structure type named after a compound — not a family: "LGPS" (Li10GeP2S12), "Li3YCl6-type", "UCl3-type".
_PROTOTYPE_NAMES = {"lgps": "LGPS-type", "lgpstype": "LGPS-type"}
# The stacking of a layered oxide ("P2-type", "O3-type") is a layered structure.
_STACKING = re.compile(r"^[OPT][1-3]-type$")
# What the extraction writes in place of a structure when only the kind of compound is known.
_COMPOUND_CLASSES = {"oxide", "phosphate", "silicate", "borate", "sulfate", "carbonate", "oxynitride", "sulfide",
                     "thiophosphate", "selenide", "selenophosphate", "telluride", "tellurophosphate", "fluoride",
                     "chloride", "bromide", "iodide", "mixed halide", "oxyhalide", "nitride", "hydride",
                     "borohydride", "closo-borate", "alloy", "element"}
_MISSING = {"", "none", "nan", "null", "n/a", "unspecified", "unknown", "open"}

# ---------------------------------------------------------------------------
# Composition types and prototypes
# ---------------------------------------------------------------------------
_MOBILE = {"Li", "Na", "K", "Rb", "Cs", "Ag", "Cu"}       # A: the mobile cations
_ANIONS = {"O", "S", "Se", "Te", "F", "Cl", "Br", "I", "N"}  # X
_TETRAHEDRAL = {"P", "Si", "Ge", "V", "As", "Sn", "Sb"}    # the centres of the XO4 / XS4 groups
# The centres of the polyanions of a framework — PO4, SiO4, PS4, GeS4, BO3, CO3, SO4, WO4, ...
_POLYANION_CENTRES = _TETRAHEDRAL | {"B", "C", "S", "Mo", "W"}


def has_open_shares(amounts: dict[str, float | str]) -> bool:
    """Whether the composition is a mixture whose shares the paper leaves open ("xLi2S-(100-x)SiS2"):
    its elements are known, their amounts are not."""
    return any(isinstance(amount, str) and amount.strip().casefold() == "open" for amount in amounts.values())


def _amounts(amounts: dict[str, float | str]) -> dict[str, float]:
    return {symbol: (amount if isinstance(amount, float) else _nominal(amount)) for symbol, amount in amounts.items()}


def _integral(counts: tuple[float, float, float]) -> tuple[int, int, int]:
    """Whole numbers for A, M and X: the smallest multiple that makes them whole (Li1.5Al0.5Ge1.5(PO4)3
    → A3M4X24 ...), else each rounded — a dopant-level share dropped — so that a doped variant is of
    the type of its parent (Li2.6Y0.8Zr0.2Cl6 is an A3MX6 halide like Li3YCl6)."""
    for k in (1, 2, 3, 4):
        scaled = [count * k for count in counts]
        if all(abs(v - round(v)) <= 0.12 and round(v) >= 1 for v in scaled if v > 0):
            return tuple(round(v) if v > 0 else 0 for v in scaled)  # type: ignore[return-value]
    return tuple(max(1, round(v)) if v > 0.3 else 0 for v in counts)  # type: ignore[return-value]


def composition_type(amounts: dict[str, float | str]) -> tuple[str, float, float, float] | None:
    """The formula a material shares with its kind — "A3MX6" for Li3YCl6, Na3YI6 and Li3InCl6 —
    with its A (mobile cation), M (other cation) and X (anion) contents per formula unit. None for
    a mixture whose shares are open: its formula is not known."""
    if has_open_shares(amounts):
        return None
    numbers = _amounts(amounts)
    anions = _ANIONS if numbers.keys() & _ANIONS else {"P", "As", "Sb"}  # a phosphide: Li3P, Li8SiP4
    a = sum(v for k, v in numbers.items() if k in _MOBILE)
    x = sum(v for k, v in numbers.items() if k in anions)
    m = sum(v for k, v in numbers.items() if k not in _MOBILE | anions and k != "H")
    if not x or not (a or m):
        return None
    unit = m if m else a
    a, m, x = a / unit, m / unit, x / unit
    whole = _integral((a, m, x))

    def part(symbol: str, count: int) -> str:
        return "" if count <= 0 else symbol + ("" if count == 1 else str(count))
    return part("A", whole[0]) + part("M", whole[1]) + part("X", whole[2]), round(a, 2), round(m, 2), round(x, 2)


def prototype(amounts: dict[str, float | str]) -> str | None:
    """The known family a material's composition type belongs to, where that settles it: a
    lithium-rich orthooxide A3-4MX4 (γ-Li3PO4, Li4SiO4) is LISICON, its sulfide (Li3PS4, Li4GeS4)
    thio-LISICON. None elsewhere. (A sodium thiophosphate such as Na3PS4 is neither: a type of its own.)"""
    kind = composition_type(amounts)
    if not kind:
        return None
    _, a, m, x = kind
    present = set(amounts)
    anions = present & _ANIONS
    numbers = _amounts(amounts)
    lithium, sodium = numbers.get("Li", 0.0), numbers.get("Na", 0.0)
    centres = present & _TETRAHEDRAL
    others = {e for e in present - _MOBILE - _ANIONS - _TETRAHEDRAL if numbers.get(e, 0.0) >= 0.2}  # a dopant aside
    if lithium > sodium and centres and not others and 2.5 <= a <= 4.5 and abs(x - 4) <= 0.1 and m <= 1.05:
        if anions == {"O"}:
            return "LISICON"          # γ-Li3PO4, Li4SiO4, Li4GeO4 and their solid solutions
        if anions == {"S"}:
            return "thio-LISICON"     # Li3PS4, Li4GeS4, Li4SnS4
    return None


@dataclass(frozen=True)
class Labels:
    """The labels of one structure cell, by kind."""
    types: tuple[str, ...] = ()
    systems: tuple[str, ...] = ()
    polymorphs: tuple[str, ...] = ()
    space_groups: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    prototypes: tuple[str, ...] = ()   # types named after a compound: not a family


def structure_labels(cell: str) -> Labels:
    """'cubic | garnet | Ia-3d' → the type garnet, the system cubic, the space group Ia-3d."""
    found: dict[str, list[str]] = {"types": [], "systems": [], "polymorphs": [], "space_groups": [], "states": [],
                                   "prototypes": []}
    for label in (part.strip() for part in str(cell or "").split("|")):
        lowered = label.casefold()
        if lowered in _MISSING or lowered in _COMPOUND_CLASSES or lowered == "crystalline":
            continue
        folded = re.sub(r"[\s\-]", "", lowered)
        if lowered in CRYSTAL_SYSTEMS:
            found["systems"].append(lowered)
        elif lowered in _STATES:
            found["states"].append(_STATES[lowered])
        elif label.endswith("-phase"):
            found["polymorphs"].append(label)
        elif folded in _TYPES:
            found["types"].append(_TYPES[folded])
        elif _STACKING.match(label):
            found["types"].append("layered")
        elif folded in _PROTOTYPE_NAMES:
            found["prototypes"].append(_PROTOTYPE_NAMES[folded])
        elif label.endswith("-type"):  # a type named after a compound: "UCl3-type", "Li3YCl6-type"
            found["prototypes"].append(label)
        else:
            found["space_groups"].append(label)
    return Labels(**{kind: tuple(dict.fromkeys(labels)) for kind, labels in found.items()})


# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------
def composition(cell: str) -> dict[str, float | str]:
    """The composition of the `elements` / `composition` column: {"Li": 7.0, "La": 3.0, ...};
    an open subscript of a series stays text ("1-x")."""
    try:
        amounts = json.loads(cell) if cell and str(cell).strip().startswith("{") else {}
    except ValueError:
        return {}
    if not isinstance(amounts, dict):
        return {}
    return {symbol: (float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else str(amount))
            for symbol, amount in amounts.items()}


def material_key(amounts: dict[str, float | str], formula: str) -> str:
    """What makes two rows one material: the composition when there is one (Li1.3Al0.3Ti1.7(PO4)3
    and Li1.3Ti1.7Al0.3(PO4)3 are one), otherwise the formula as it is spelled."""
    if amounts:
        return " ".join(f"{symbol}{round(amount, 4):g}" if isinstance(amount, float) else f"{symbol}[{''.join(amount.split())}]"
                        for symbol, amount in sorted(amounts.items()))
    return "formula:" + "".join(str(formula).split())


def type_from_composition(amounts: dict[str, float | str]) -> tuple[str | None, str]:
    """The structure type the composition alone settles, and how it was settled — nothing for a
    mixture whose shares are open."""
    if not amounts or has_open_shares(amounts):
        return None, ""
    if all(isinstance(amount, float) for amount in amounts.values()):
        found = ChemistryEngine.structure_family(amounts)
        return (found, "known for this composition") if found else (None, "")
    nominal = {symbol: _nominal(amount) for symbol, amount in amounts.items()}
    found = ChemistryEngine.structure_family(nominal)
    return (found, "known for this composition series (taken at x = 0.25)") if found else (None, "")


# ---------------------------------------------------------------------------
# Chemical families
# ---------------------------------------------------------------------------
# What part of its papers must state a type (or a state) for it to classify a material.
TYPE_SHARE, STATE_SHARE = 1 / 3, 1 / 2

# The kind of compound the extraction names (after its anions) → the family it belongs to.
FAMILIES = {
    "oxide": ("oxide", "phosphate", "silicate", "borate", "sulfate", "carbonate", "oxynitride"),
    "sulfide": ("sulfide", "thiophosphate"),
    "selenide": ("selenide", "selenophosphate"),
    "telluride": ("telluride", "tellurophosphate"),
    "halide": ("fluoride", "chloride", "bromide", "iodide", "mixed halide"),
    "oxyhalide": ("oxyhalide",),
    "nitride": ("nitride",),
    "phosphide": ("phosphide", "arsenide"),
    "hydride": ("hydride", "borohydride", "closo-borate"),
    "element_or_alloy": ("element", "alloy"),
}
_FAMILY_OF = {kind: family for family, kinds in FAMILIES.items() for kind in kinds}
_ELECTROPOSITIVE = {"Li", "Na", "K", "Rb", "Cs", "Mg", "Ca", "Sr", "Ba"}


def chemical_family(amounts: dict[str, float | str], formula: str) -> tuple[str, str]:
    """The family and the kind of compound: ("sulfide", "thiophosphate") for Li6PS5Cl."""
    if not amounts and not re.search(r"[A-Z]", str(formula)):
        return UNCLASSIFIED, ""
    kind = ChemistryEngine.compound_class(amounts, str(formula))
    if kind in ("alloy", "element"):
        # No O, S, halogen or N: a pnictogen with an electropositive metal is its anion (Li3P, Li8SiP4).
        present = set(amounts) or set(re.findall(r"[A-Z][a-z]?", str(formula)))
        if present & _ELECTROPOSITIVE:
            kind = "phosphide" if "P" in present else "arsenide" if "As" in present else kind
    return _FAMILY_OF.get(kind, UNCLASSIFIED), kind


# ---------------------------------------------------------------------------
# One material, from all its rows
# ---------------------------------------------------------------------------
_STATE_CLASSES = {"amorphous", "glass-ceramic"}
# What classified a material well enough for it to stand as an analogue of another: its composition,
# what most of its papers state, or a prototype — not a type few papers state, nor a state.
_ESTABLISHED = ("known for this composition", "stated by ", "inferred: the family of its composition type")


def roles(amounts: dict[str, float | str]) -> tuple[frozenset, frozenset, frozenset]:
    """The mobile cations, the main framework cations (a dopant aside) and the anions of a
    composition."""
    numbers = _amounts(amounts)
    anions = _ANIONS if numbers.keys() & _ANIONS else {"P", "As", "Sb"}
    framework = {e: v for e, v in numbers.items() if e not in _MOBILE | anions and e != "H"}
    largest = max(framework.values(), default=0.0)
    main = {e for e, v in framework.items() if v >= 0.2 * largest}
    return (frozenset(e for e in numbers if e in _MOBILE), frozenset(main), frozenset(e for e in numbers if e in anions))


def analogous(a: "Material", b: "Material") -> bool:
    """Whether two materials are analogues — a doped or substituted variant of the other: the same
    composition type and family, the same stoichiometry (A, M and X per formula unit within 15%),
    the same anions and mobile cations, the same polyanion centres (P, Si, Ge, ...) and a main
    framework cation in common. Na2.88Sb0.88W0.12S4 is one of Na3SbS4, Li3Er0.6In0.4Cl6 of
    Li3ErCl6; ZrO2 is none of a zirconium phosphate, LiBiO2 none of a garnet, LixMn2O4 none of a
    perovskite titanate — and Li3ScCl6 none of Li3YCl6, as the Li3MX6 halides change structure with
    the size of M (only the symmetry their papers state tells them apart: step 5)."""
    kind_a, kind_b = composition_type(a.amounts), composition_type(b.amounts)
    if not kind_a or not kind_b or a.kind() != b.kind():
        return False
    if any(abs(u - v) > 0.15 * max(u, v, 0.1) for u, v in zip(kind_a[1:], kind_b[1:])):
        return False
    (mobile_a, main_a, anions_a), (mobile_b, main_b, anions_b) = roles(a.amounts), roles(b.amounts)
    centres_a, centres_b = (main_a & _POLYANION_CENTRES) - anions_a, (main_b & _POLYANION_CENTRES) - anions_b
    return mobile_a == mobile_b and anions_a == anions_b and centres_a == centres_b and bool(main_a & main_b)


def classify_the_rest(materials: list["Material"]) -> None:
    """Steps 7 and 8, for the materials nothing about themselves classifies: the family of their
    analogues — when those agree on one — else no known crystal family."""
    established = [m for m in materials if m.structure_type not in (UNCLASSIFIED, *_STATE_CLASSES)
                   and m.structure_type_basis.startswith(_ESTABLISHED)
                   and not m.structure_type_basis.startswith("stated by only")]
    for m in materials:
        if m.structure_type != UNCLASSIFIED:
            continue
        kind = m.kind()
        # nor from its analogues, for a material of a type named after a compound (see Material.classify)
        alike = [] if m.prototypes else [other for other in established if analogous(m, other)]
        votes = Counter(other.structure_type for other in alike)
        if votes:
            label, count = votes.most_common(1)[0]
            if count >= 2 * sum(votes.values()) / 3:
                names = ", ".join(sorted(other.name for other in alike if other.structure_type == label)[:3])
                m.structure_type = label
                m.structure_type_basis = (f"inferred: the type of its analogues, {kind}s of the same ions "
                                          f"({count} of {sum(votes.values())}: {names})")
                continue
        what = (f"its composition type is {kind}" if composition_type(m.amounts) else
                f"a {m.family} mixture whose shares are open" if has_open_shares(m.amounts) else
                "an element" if len(m.amounts) == 1 else "an intermetallic")
        named = m.prototypes.most_common()
        m.structure_type = NO_FAMILY
        m.structure_type_basis = (f"none of the known crystal families is stated by its papers, known for its "
                                  f"composition or shared by its analogues; {what}"
                                  + (f"; a type named after a compound is given for it: "
                                     f"{', '.join(label for label, _ in named)}" if named else ""))


@dataclass
class Material:
    key: str
    amounts: dict[str, float | str]
    spellings: Counter = field(default_factory=Counter)
    occurrences: list[tuple[str, str]] = field(default_factory=list)   # (database, paper_id)
    stated_types: dict[str, set] = field(default_factory=dict)        # type → the papers that state it
    systems: Counter = field(default_factory=Counter)
    polymorphs: Counter = field(default_factory=Counter)
    space_groups: Counter = field(default_factory=Counter)
    states: dict[str, set] = field(default_factory=dict)
    prototypes: Counter = field(default_factory=Counter)  # types named after a compound: stated or known
    structure_type: str = UNCLASSIFIED
    structure_type_basis: str = ""
    family: str = UNCLASSIFIED
    compound_class: str = ""

    @property
    def name(self) -> str:
        """Its most frequent spelling, the shortest one among equals."""
        return min(self.spellings, key=lambda spelling: (-self.spellings[spelling], len(spelling), spelling))

    @property
    def papers(self) -> list[str]:
        return list(dict.fromkeys(paper for _, paper in self.occurrences))

    @property
    def databases(self) -> list[str]:
        return list(dict.fromkeys(database for database, _ in self.occurrences))

    def add(self, database: str, paper: str, formula: str, structure: str) -> None:
        self.spellings[formula] += 1
        self.occurrences.append((database, paper))
        labels = structure_labels(structure)
        for label in labels.types:
            self.stated_types.setdefault(label, set()).add((database, paper))
        for label in labels.states:
            self.states.setdefault(label, set()).add((database, paper))
        self.prototypes.update(labels.prototypes)
        self.systems.update(labels.systems)
        self.polymorphs.update(labels.polymorphs)
        self.space_groups.update(labels.space_groups)

    def votes(self) -> str:
        """What the papers state, most stated first: "NASICON 3 papers · garnet 1 paper"."""
        ranked = sorted(self.stated_types.items(), key=lambda item: (-len(item[1]), item[0]))
        return " · ".join(f"{label} {len(papers)} paper{'s' if len(papers) != 1 else ''}" for label, papers in ranked)

    def classify(self) -> None:
        """Steps 1 to 6: what the material itself settles. Steps 7 and 8 need the other materials:
        see `classify_the_rest`."""
        self.family, self.compound_class = chemical_family(self.amounts, self.name)
        if self.family == "halide":
            # "Layered" in a paper on a Li3MX6 halide describes the anion stacking its monoclinic and
            # trigonal phases share — not the family of the layered oxides.
            self.stated_types.pop("layered", None)
        found, basis = type_from_composition(self.amounts)
        if found and found not in KNOWN_FAMILIES:  # LGPS-type: a type named after a compound, not a family
            self.prototypes[found] += 1
            found = None
        if found:
            stated = set(self.stated_types) - {found}
            note = f"; the papers also state {', '.join(sorted(stated))}" if stated else ""
            self.structure_type, self.structure_type_basis = found, basis + note
            return
        self.structure_type, self.structure_type_basis = self._stated()
        if self.structure_type != UNCLASSIFIED:
            return
        # A material of a type named after a compound (LGPS-type, Li3YCl6-type) has a structure of its own:
        # no family is inferred for it from its formula — Li10GeP2S12 has the formula of a thio-LISICON, not
        # its structure. Only papers stating a family classify it.
        found = None if self.prototypes else prototype(self.amounts)
        if found:
            self.structure_type = found
            self.structure_type_basis = f"inferred: the family of its composition type ({self.kind()})"
            return
        if self.stated_types or self.states:
            label, papers = max([*self.stated_types.items(), *self.states.items()], key=lambda item: (len(item[1]), item[0]))
            self.structure_type = label
            self.structure_type_basis = f"stated by only {len(papers)} of the {len(self.papers)} paper(s) of this material"

    def kind(self) -> str:
        """Its composition type, "A3MX6 halide"."""
        found = composition_type(self.amounts)
        return f"{found[0]} {self.family}" if found else self.family

    def _stated(self) -> tuple[str, str]:
        """The class what the papers state gives, when enough of them state it; why not, otherwise."""
        total = len(self.papers)
        too_few = []
        if self.stated_types:
            ranked = sorted(self.stated_types.items(), key=lambda item: (-len(item[1]), item[0]))
            label, papers = ranked[0]
            if len(papers) >= TYPE_SHARE * total:
                basis = f"stated by {len(papers)} of the {total} paper(s) of this material"
                if len(ranked) > 1:
                    basis += f" (also stated: {', '.join(other for other, _ in ranked[1:])})"
                return label, basis
            too_few.append(f"{label} by {len(papers)} of {total}")
        if self.states:
            label, papers = max(self.states.items(), key=lambda item: (len(item[1]), item[0] == "amorphous"))
            if len(papers) > STATE_SHARE * total:
                return label, f"stated by {len(papers)} of the {total} paper(s): no crystal structure"
            too_few.append(f"{label} by {len(papers)} of {total}")
        if too_few:
            return UNCLASSIFIED, f"too few of its papers state a structure ({'; '.join(too_few)})"
        return UNCLASSIFIED, "not stated by its papers and not known for this composition"

    def row(self, energies: list[float], conductivities: list[float],
            by_component: dict[str, list[float]] | None = None) -> dict[str, object]:
        """Its line in materials.csv of a classification folder. `by_component`: its activation
        energies by the transport component they describe (bulk, grain_boundary, total)."""
        def joined(counter: Counter) -> str:
            return " | ".join(label for label, _ in counter.most_common()) or "none stated by its papers"

        energies, conductivities = sorted(energies), sorted(conductivities)
        components: dict[str, object] = {}
        for component in COMPONENTS:
            values = sorted((by_component or {}).get(component, []))
            components[f"n_Ea_{component}"] = len(values)
            components[f"Ea_{component}_min_eV"] = values[0] if values else f"no {COMPONENT_WORDS[component]} value reported"
        return {
            "material": self.name,
            "spellings": " | ".join(s for s, _ in self.spellings.most_common()),
            "composition": json.dumps(self.amounts, ensure_ascii=False) if self.amounts else "its formula names no element",
            "crystal_structure": self.structure_type,
            "crystal_structure_basis": self.structure_type_basis,
            "structure_types_stated": self.votes() or "none stated by its papers",
            "composition_type": self.kind(),
            "structure_family": self.family,
            "compound_class": self.compound_class or self.family,
            "crystal_systems": joined(self.systems),
            "polymorphs": joined(self.polymorphs),
            "space_groups": joined(self.space_groups),
            "n_papers": len(self.papers),
            "papers": " | ".join(self.papers),
            "databases": " | ".join(self.databases),
            "n_activation_energies": len(energies),
            "Ea_min_eV": energies[0] if energies else "no activation energy reported",
            "Ea_median_eV": _median(energies) if energies else "no activation energy reported",
            "Ea_max_eV": energies[-1] if energies else "no activation energy reported",
            **components,
            "n_ionic_conductivities": len(conductivities),
            "sigma_max_S_cm": conductivities[-1] if conductivities else "no ionic conductivity reported",
            "material_key": self.key,
        }


def _median(values: list[float]) -> float:
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else round((values[middle - 1] + values[middle]) / 2, 6)


def number(text: object) -> float | None:
    """The number at the start of a cell: "0.31 eV" → 0.31, "1e-3 S/cm" → 0.001."""
    match = re.match(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", str(text))
    if not match:
        return None
    value = float(match.group(1))
    return value if math.isfinite(value) else None
