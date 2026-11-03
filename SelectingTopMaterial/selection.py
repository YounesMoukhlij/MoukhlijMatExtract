# SelectingTopMaterial/selection.py
"""From the activation energies of the database to a ranking of materials.

    values ──filters──▶ one group per material ──policy──▶ one Ea per material ──criteria──▶ class
                                                                      │
                                                    lowest Ea first ──▶ rank

A material is its composition: every spelling of it, in every paper, is one group (two phases of
it are two groups when asked for with by_phase). The energy that stands for a group is chosen by
the policy; its class, and the class of each value behind it, by the criteria. What makes a class
less sure — values on both sides of a limit, an energy sitting on one — is written beside it as a
check, never used to move the material."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import loader
from .criteria import POLICIES, Criteria, format_energy
from .models import (COMPONENTS, NOT_REPORTED, DatabaseReport, Filters, Measurement, RankedMaterial, Selection,
                     component_key, component_word)

_PRECISION = 6


def weighted_median(pairs: Iterable[tuple[float, float]]) -> float:
    """The median of (value, weight) pairs: the value at which half of the weight is reached,
    and the middle of the two values around it when half is reached exactly between them (so
    that two equally trusted values give their mean, as an ordinary median does). Values of no
    weight do not count, unless none has any: then all count the same."""
    ordered = sorted(pairs)
    if not ordered:
        raise ValueError("a median needs at least one value")
    weighted = [(value, weight) for value, weight in ordered if weight > 0]
    if not weighted:
        weighted = [(value, 1.0) for value, _ in ordered]
    half = sum(weight for _, weight in weighted) / 2
    running = 0.0
    for index, (value, weight) in enumerate(weighted):
        running += weight
        if abs(running - half) <= 1e-12 and index + 1 < len(weighted):
            return (value + weighted[index + 1][0]) / 2
        if running > half:
            return value
    return weighted[-1][0]


def representative(values: Sequence[Measurement], policy: str) -> float:
    """The activation energy that stands for a material which has these values."""
    if policy == "optimistic":
        energy = min(v.energy_eV for v in values)
    elif policy == "conservative":
        energy = max(v.energy_eV for v in values)
    elif policy == "consensus":
        energy = weighted_median((v.energy_eV, v.confidence) for v in values)
    else:
        raise ValueError(f"unknown policy {policy!r} — choose one of {', '.join(POLICIES)}")
    return round(energy, _PRECISION)


def select(values: Iterable[Measurement], criteria: Criteria, *, policy: str | None = None,
           by_phase: bool = False, filters: Filters | None = None,
           databases: Sequence[DatabaseReport] = (), notes: Sequence[str] = ()) -> Selection:
    """The ranking of the materials these values describe: lowest activation energy first, each
    with its class. The same values always give the same ranking, whatever order they come in."""
    policy = policy or criteria.policy
    filters = filters or Filters()
    values = list(values)

    groups: dict[tuple[str, str], list[Measurement]] = {}
    for value in values:
        if filters.keeps(value):
            groups.setdefault((value.material_key, value.polymorph if by_phase else ""), []).append(value)

    unranked = []
    for (_, phase), group in groups.items():
        group.sort(key=lambda v: (v.energy_eV, -v.confidence, v.paper_id, v.page, v.sentence))
        energy = representative(group, policy)
        confidence = round(sum(v.confidence for v in group) / len(group), 3)
        unranked.append((energy, confidence, _name(group, phase), group))
    # Equal energies: the better supported material first, then the name, so that the order is settled.
    unranked.sort(key=lambda item: (item[0], -item[1], -len(item[3]), item[2].casefold(), item[2]))

    materials = []
    for rank, (energy, confidence, name, group) in enumerate(unranked, start=1):
        counts = Counter(criteria.classify(v.energy_eV).name for v in group)
        votes = tuple(sorted(counts.items(), key=lambda vote: criteria.position(vote[0])))
        materials.append(RankedMaterial(
            rank=rank, material=name, energy_class=criteria.classify(energy), energy_eV=energy,
            values=tuple(group), votes=votes, checks=_checks(energy, votes, confidence, criteria),
            confidence=confidence,
            evidence=min(group, key=lambda v: (abs(v.energy_eV - energy), -v.confidence, v.energy_eV))))

    return Selection(criteria=criteria, policy=policy, by_phase=by_phase, filters=filters,
                     materials=tuple(materials), databases=tuple(databases), values_read=len(values),
                     generated_at=datetime.now().astimezone().isoformat(timespec="seconds"), notes=tuple(notes))


def components_in(values: Iterable[Measurement]) -> list[str]:
    """The components to rank: bulk, grain boundary and total always (one may hold no value), then
    any other the values describe (surface, …), and the values whose component is not stated."""
    found = {component_key(v.transport_component) for v in values}
    others = sorted(c for c in found if c and c not in COMPONENTS and c != component_key(NOT_REPORTED))
    return [*COMPONENTS, *others, *([component_key(NOT_REPORTED)] if component_key(NOT_REPORTED) in found else [])]


def select_each(values: Iterable[Measurement], criteria: Criteria, *, policy: str | None = None,
                by_phase: bool = False, filters: Filters | None = None, databases: Sequence[DatabaseReport] = (),
                notes: Sequence[str] = ()) -> dict[str, Selection]:
    """One ranking per transport component — bulk, grain boundary, total — each with its own ranks
    and classes: a material's bulk Ea is compared with bulk Ea only. A component named in the
    filters gives that ranking alone."""
    filters = filters or Filters()
    values = list(values)
    wanted = [component_key(filters.component)] if filters.component else components_in(values)
    return {component: select(values, criteria, policy=policy, by_phase=by_phase,
                              filters=replace(filters, component=component), databases=databases, notes=notes)
            for component in wanted}


def select_from_each(databases: Sequence[Path], criteria: Criteria, *, root: Path | None = None,
                     policy: str | None = None, by_phase: bool = False,
                     filters: Filters | None = None) -> dict[str, Selection]:
    """One ranking per transport component of what the results folders hold."""
    values, reports = loader.load(databases, root=root)
    note = loader.unassigned_note(reports)
    return select_each(values, criteria, policy=policy, by_phase=by_phase, filters=filters,
                       databases=reports, notes=(note,) if note else ())


def select_from(databases: Sequence[Path], criteria: Criteria, *, root: Path | None = None,
                policy: str | None = None, by_phase: bool = False, filters: Filters | None = None) -> Selection:
    """The ranking of what the results folders hold."""
    values, reports = loader.load(databases, root=root)
    note = loader.unassigned_note(reports)
    return select(values, criteria, policy=policy, by_phase=by_phase, filters=filters,
                  databases=reports, notes=(note,) if note else ())


def _name(group: Sequence[Measurement], phase: str) -> str:
    """The name a material goes by: its most frequent spelling, the shortest one among equals."""
    spellings = Counter(v.material for v in group)
    name = min(spellings, key=lambda spelling: (-spellings[spelling], len(spelling), spelling))
    return f"{name} ({phase})" if phase else name


def _checks(energy: float, votes: Sequence[tuple[str, int]], confidence: float,
            criteria: Criteria) -> tuple[str, ...]:
    checks = []
    limit = criteria.nearest_limit(energy)
    if limit is not None:
        checks.append(f"borderline ({format_energy(limit)} eV limit)")
    if len(votes) > 1:
        checks.append(f"values disagree ({votes[0][0]} to {votes[-1][0]})")
    if confidence < criteria.low_confidence:
        checks.append("low confidence")
    return tuple(checks)
