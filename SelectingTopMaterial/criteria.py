# SelectingTopMaterial/criteria.py
"""The rule of the selection: the classes an activation energy falls into, read from criteria.toml.

    Ea < 0.25 eV    Superionic
    Ea < 0.30 eV    Performant
    Ea < 0.40 eV    Acceptable
    otherwise       Rejected

Every limit is exclusive, so a value that sits exactly on one belongs to the class after it:
0.25 eV is Performant, 0.40 eV is Rejected."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CRITERIA = Path(__file__).with_name("criteria.toml")

# How one activation energy is chosen for a material that has several, and what each choice means.
POLICIES = {
    "consensus": "confidence-weighted median of the material's values",
    "optimistic": "lowest value reported for the material",
    "conservative": "highest value reported for the material",
}

# Activation energies are printed with two or three decimals; anything past the sixth is the
# arithmetic of floating-point numbers, not physics, and must not move a value across a limit.
_PRECISION = 6


class CriteriaError(ValueError):
    """The criteria file cannot be used; the message says what to change in it."""


def format_energy(value: float) -> str:
    """An energy as the limits are written: at least two decimals, no trailing noise (0.25, 0.305)."""
    text = f"{value:.4f}".rstrip("0")
    whole, _, decimals = text.partition(".")
    return f"{whole}.{decimals.ljust(2, '0')}"


@dataclass(frozen=True, slots=True)
class EnergyClass:
    """One class of the selection: its name and the interval of activation energies it holds,
    `lower` included and `below` excluded."""
    name: str
    lower: float
    below: float
    accepted: bool

    @property
    def rule(self) -> str:
        """The interval in words: "Ea < 0.25 eV", "0.25 ≤ Ea < 0.30 eV", "Ea ≥ 0.40 eV"."""
        if math.isinf(self.below):
            return f"Ea ≥ {format_energy(self.lower)} eV"
        if self.lower <= 0:
            return f"Ea < {format_energy(self.below)} eV"
        return f"{format_energy(self.lower)} ≤ Ea < {format_energy(self.below)} eV"


@dataclass(frozen=True, slots=True)
class Criteria:
    """The classes, best first and the rejected one last, with what the checks are held to."""
    classes: tuple[EnergyClass, ...]
    policy: str = "consensus"
    borderline_margin: float = 0.01
    low_confidence: float = 0.5
    source: str = "criteria.toml"

    @property
    def limits(self) -> tuple[float, ...]:
        """The energies at which one class ends and the next begins."""
        return tuple(c.below for c in self.classes if not math.isinf(c.below))

    @property
    def rejected(self) -> EnergyClass:
        return self.classes[-1]

    def classify(self, energy_eV: float) -> EnergyClass:
        """The class of one activation energy."""
        energy = round(energy_eV, _PRECISION)
        return next(c for c in self.classes if energy < c.below)

    def position(self, name: str) -> int:
        """Where a class stands, 0 being the best."""
        return next(i for i, c in enumerate(self.classes) if c.name == name)

    def nearest_limit(self, energy_eV: float) -> float | None:
        """The limit an energy is within the borderline margin of, if any."""
        energy = round(energy_eV, _PRECISION)
        near = [limit for limit in self.limits if abs(energy - limit) <= self.borderline_margin + 10 ** -_PRECISION]
        return min(near, key=lambda limit: abs(energy - limit)) if near else None

    @classmethod
    def load(cls, path: str | Path | None = None) -> Criteria:
        """The criteria of a TOML file; those shipped with the program when no file is named."""
        path = Path(path) if path else DEFAULT_CRITERIA
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except FileNotFoundError:
            raise CriteriaError(f"criteria file not found: {path}") from None
        except tomllib.TOMLDecodeError as error:
            raise CriteriaError(f"{path} is not valid TOML ({error}). "
                                f"Decimals are written with a point: 0.25, not 0,25.") from None
        return cls.from_mapping(data, source=path.name)

    @classmethod
    def from_mapping(cls, data: dict, source: str = "criteria") -> Criteria:
        """The criteria of an already parsed file; everything a wrong file can hold is refused
        here, with the reason, so that a ranking is never built on a rule nobody meant."""
        entries = data.get("class")
        if not isinstance(entries, list) or not entries:
            raise CriteriaError(f"{source}: at least one [[class]] with a name and a `below` limit is needed")

        classes: list[EnergyClass] = []
        lower = 0.0
        for entry in entries:
            name = str(entry.get("name", "")).strip() if isinstance(entry, dict) else ""
            below = entry.get("below") if isinstance(entry, dict) else None
            if not name:
                raise CriteriaError(f"{source}: every [[class]] needs a name")
            if isinstance(below, bool) or not isinstance(below, (int, float)) or not math.isfinite(below):
                raise CriteriaError(f"{source}: class {name!r} needs a number for `below` (its upper limit in eV)")
            if below <= lower:
                raise CriteriaError(f"{source}: the limit of class {name!r} ({below} eV) must be above "
                                    f"{format_energy(lower)} eV — classes are listed best first, limits rising")
            classes.append(EnergyClass(name=name, lower=lower, below=float(below), accepted=True))
            lower = float(below)

        rejected = str((data.get("rejected") or {}).get("name", "Rejected")).strip() or "Rejected"
        classes.append(EnergyClass(name=rejected, lower=lower, below=math.inf, accepted=False))
        names = [c.name.casefold() for c in classes]
        if len(set(names)) != len(names):
            raise CriteriaError(f"{source}: two classes share a name")

        policy = str((data.get("material") or {}).get("policy", "consensus")).strip().lower()
        if policy not in POLICIES:
            raise CriteriaError(f"{source}: unknown policy {policy!r} — choose one of {', '.join(POLICIES)}")

        checks = data.get("checks") or {}
        margin, low_confidence = checks.get("borderline_margin", 0.01), checks.get("low_confidence", 0.5)
        for label, value in (("borderline_margin", margin), ("low_confidence", low_confidence)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise CriteriaError(f"{source}: [checks] {label} must be a number, zero or above")
        return cls(classes=tuple(classes), policy=policy, borderline_margin=float(margin),
                   low_confidence=float(low_confidence), source=source)
