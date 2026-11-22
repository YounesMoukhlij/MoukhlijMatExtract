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
                     component_key)

_PRECISION = 6
BOOTSTRAP, SEED, TOP_N = 1000, 20261116, 10  # the rank intervals: resamplings, their seed, the top they count


def _resampled(group: Sequence[Measurement], policy: str, rng, rounds: int):
    """The energy that stands for a material in each of `rounds` resamplings of its values (with replacement): the
    same rule as `representative`, row by row — numpy arrays, so that a thousand rounds of hundreds of materials take
    a moment."""
    import numpy as np
    values = np.array([v.energy_eV for v in group], dtype=float)
    weights = np.array([v.confidence for v in group], dtype=float)
    n = len(values)
    picks = rng.integers(0, n, size=(rounds, n))
    v = values[picks]
    if policy == "optimistic":
        return np.round(v.min(axis=1), _PRECISION)
    if policy == "conservative":
        return np.round(v.max(axis=1), _PRECISION)
    w = weights[picks]
    none = (w > 0).sum(axis=1) == 0                # no weight at all: every value counts the same
    w = np.where(none[:, None], 1.0, w)
    v = np.where(w > 0, v, np.inf)                 # a value of no weight does not count: sorted last, never reached
    order = np.lexsort((w, v), axis=-1)            # by value, then weight: the order `weighted_median` sorts in
    v, w = np.take_along_axis(v, order, axis=1), np.take_along_axis(w, order, axis=1)
    cumulative = np.cumsum(w, axis=1)
    half = cumulative[:, -1:] / 2
    rows = np.arange(rounds)
    exact = np.abs(cumulative - half) <= 1e-12
    first_exact = np.where(exact.any(axis=1), exact.argmax(axis=1), n)
    first_above = (cumulative > half).argmax(axis=1)
    at = np.minimum(first_exact, n - 1)
    following = np.minimum(first_exact + 1, n - 1)
    # Half the weight reached exactly (checked before "above half", as weighted_median does): the middle of two.
    between = (first_exact <= first_above) & (first_exact + 1 < n) & np.isfinite(v[rows, following])
    energy = np.where(between, (v[rows, at] + v[rows, following]) / 2, v[rows, first_above])
    return np.round(energy, _PRECISION)


def rank_intervals(groups: Sequence[Sequence[Measurement]], policy: str, rounds: int = BOOTSTRAP, seed: int = SEED,
                   top: int = TOP_N) -> list[tuple[int, int, float]]:
    """How sure each rank is. The values of every material are resampled `rounds` times, the materials ranked again
    each time; for each, its 95 % rank interval and the share of rounds that put it in the first `top`. `groups` are
    in their rank order, which settles ties as the ranking does. A material that rests on one value has no spread
    of its own: its interval says only how the others move (its evidence tier says it rests on one value)."""
    import numpy as np
    if not groups or rounds <= 0:
        return []
    rng = np.random.default_rng(seed)
    energies = np.column_stack([_resampled(group, policy, rng, rounds) for group in groups])
    order = np.argsort(energies, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(rounds)[:, None], order] = np.arange(1, len(groups) + 1)
    low = np.percentile(ranks, 2.5, axis=0, method="lower")
    high = np.percentile(ranks, 97.5, axis=0, method="higher")
    share = (ranks <= top).mean(axis=0)
    return [(int(a), int(b), round(float(p), 3)) for a, b, p in zip(low, high, share)]


def evidence_tier(group: Sequence[Measurement]) -> str:
    """A: 3 values or more from 2 papers or more; B: 2 values or more; C: a single value."""
    papers = len({v.paper_key for v in group})
    return "A" if len(group) >= 3 and papers >= 2 else "B" if len(group) >= 2 else "C"


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
           databases: Sequence[DatabaseReport] = (), notes: Sequence[str] = (), bootstrap: int = BOOTSTRAP,
           seed: int = SEED, top_n: int = TOP_N) -> Selection:
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

    intervals = rank_intervals([group for *_, group in unranked], policy, bootstrap, seed, top_n)
    materials = []
    for rank, (energy, confidence, name, group) in enumerate(unranked, start=1):
        counts = Counter(criteria.classify(v.energy_eV).name for v in group)
        votes = tuple(sorted(counts.items(), key=lambda vote: criteria.position(vote[0])))
        low, high, share = intervals[rank - 1] if intervals else (0, 0, 0.0)
        materials.append(RankedMaterial(
            rank=rank, material=name, energy_class=criteria.classify(energy), energy_eV=energy,
            values=tuple(group), votes=votes, checks=_checks(energy, votes, confidence, criteria, group),
            confidence=confidence,
            evidence=min(group, key=lambda v: (abs(v.energy_eV - energy), -v.confidence, v.energy_eV)),
            rank_low=low, rank_high=high, p_top=share, evidence_tier=evidence_tier(group)))

    return Selection(criteria=criteria, policy=policy, by_phase=by_phase, filters=filters,
                     materials=tuple(materials), databases=tuple(databases), values_read=len(values),
                     generated_at=datetime.now().astimezone().isoformat(timespec="seconds"), notes=tuple(notes),
                     bootstrap=bootstrap if intervals else 0, top_n=top_n, seed=seed)


def components_in(values: Iterable[Measurement]) -> list[str]:
    """The components to rank: bulk, grain boundary and total always (one may hold no value), then
    any other the values describe (surface, …), and the values whose component is not stated."""
    found = {component_key(v.transport_component) for v in values}
    others = sorted(c for c in found if c and c not in COMPONENTS and c != component_key(NOT_REPORTED))
    return [*COMPONENTS, *others, *([component_key(NOT_REPORTED)] if component_key(NOT_REPORTED) in found else [])]


def select_each(values: Iterable[Measurement], criteria: Criteria, *, policy: str | None = None,
                by_phase: bool = False, filters: Filters | None = None, databases: Sequence[DatabaseReport] = (),
                notes: Sequence[str] = (), bootstrap: int = BOOTSTRAP) -> dict[str, Selection]:
    """One ranking per transport component — bulk, grain boundary, total — each with its own ranks
    and classes: a material's bulk Ea is compared with bulk Ea only. A component named in the
    filters gives that ranking alone."""
    filters = filters or Filters()
    values = list(values)
    wanted = [component_key(filters.component)] if filters.component else components_in(values)
    return {component: select(values, criteria, policy=policy, by_phase=by_phase,
                              filters=replace(filters, component=component), databases=databases, notes=notes,
                              bootstrap=bootstrap)
            for component in wanted}


def select_from_each(databases: Sequence[Path], criteria: Criteria, *, root: Path | None = None,
                     policy: str | None = None, by_phase: bool = False, filters: Filters | None = None,
                     bootstrap: int = BOOTSTRAP, verifications: Path | None = None) -> dict[str, Selection]:
    """One ranking per transport component of what the results folders hold."""
    values, reports = loader.load(databases, root=root, verifications=verifications)
    note = loader.unassigned_note(reports)
    return select_each(values, criteria, policy=policy, by_phase=by_phase, filters=filters,
                       databases=reports, notes=(note,) if note else (), bootstrap=bootstrap)


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
            criteria: Criteria, group: Sequence[Measurement] = ()) -> tuple[str, ...]:
    checks = []
    disagree = sum(1 for v in group if v.arrhenius == "inconsistent")
    if disagree:
        checks.append(f"Arrhenius fit disagrees ({disagree} value{'s' if disagree != 1 else ''})")
    limit = criteria.nearest_limit(energy)
    if limit is not None:
        checks.append(f"borderline ({format_energy(limit)} eV limit)")
    if len(votes) > 1:
        checks.append(f"values disagree ({votes[0][0]} to {votes[-1][0]})")
    if confidence < criteria.low_confidence:
        checks.append("low confidence")
    return tuple(checks)
