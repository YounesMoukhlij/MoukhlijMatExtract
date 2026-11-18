# LocalExtraction/arrhenius.py
"""The Arrhenius cross-check: a paper's own conductivities, at two temperatures or more, give an activation energy
of their own — does it agree with the one the paper reports?

    sigma(T) = (A / T) exp(-Ea / kB T)      → ln(sigma T) is a straight line in 1/T, of slope -Ea/kB
    sigma(T) =  A      exp(-Ea / kB T)      → ln(sigma) against 1/T (the other convention papers use)

For each activation energy of a database, the conductivities of the same paper, the same material and (when both
state it) the same transport component are gathered; when they cover two temperatures or more, at least
MIN_SPAN_K apart, both lines are fitted. The value is "consistent" when either fit is within TOLERANCE of it,
"inconsistent" when neither is, "not checkable" otherwise. "Room temperature" counts as 298.15 K, and only next to a
measured temperature (the check says it was assumed).

An inconsistent value is a value to look at, not a wrong one: the conductivities may be of another sample, a
narrow range, or a curved plot. Nothing is changed or left out because of it.

    python -m LocalExtraction.arrhenius WebScraping/web_output      # the summary, and the values that disagree"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

K_B = 8.617333262e-5  # eV/K
ROOM = 298.15
MIN_SPAN_K = 20.0
TOLERANCE_EV, TOLERANCE_SHARE = 0.05, 0.20
CONSISTENT, INCONSISTENT, NOT_CHECKABLE = "consistent", "inconsistent", "not checkable"
_KELVIN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*K\s*$")


@dataclass(frozen=True)
class Check:
    status: str                 # consistent / inconsistent / not checkable
    reported_eV: float
    fit_eV: Optional[float] = None       # the fit closest to the reported value
    fit_sigma_T_eV: Optional[float] = None
    fit_sigma_eV: Optional[float] = None
    points: int = 0
    t_min: float = 0.0
    t_max: float = 0.0
    room_assumed: bool = False
    paper: str = ""
    material: str = ""
    reason: str = ""            # why it is not checkable

    def against(self, reported: float) -> "Check":
        """The same fits judged against another value (a person corrected the number)."""
        if self.status == NOT_CHECKABLE or self.fit_sigma_T_eV is None or self.fit_sigma_eV is None:
            return self
        from dataclasses import replace
        closest = min((self.fit_sigma_T_eV, self.fit_sigma_eV), key=lambda e: abs(e - reported))
        tolerance = max(TOLERANCE_EV, TOLERANCE_SHARE * reported)
        return replace(self, status=CONSISTENT if abs(closest - reported) <= tolerance else INCONSISTENT,
                       reported_eV=reported, fit_eV=closest)

    @property
    def text(self) -> str:
        if self.status == NOT_CHECKABLE:
            return f"not checkable ({self.reason or 'no conductivities of it at several temperatures in the paper'})"
        assumed = ", room temperature taken as 298 K" if self.room_assumed else ""
        return (f"{self.status}: the paper's conductivities give {self.fit_eV:.2f} eV "
                f"({self.points} temperatures, {self.t_min:.0f}–{self.t_max:.0f} K{assumed}); reported "
                f"{self.reported_eV:.3g} eV")


def kelvin(text: str) -> Tuple[Optional[float], bool]:
    """A temperature of the database ("298.1 K", "room temperature") in K, and whether it was assumed."""
    text = (text or "").strip()
    match = _KELVIN.match(text)
    if match:
        return float(match.group(1)), False
    if text.lower() == "room temperature":
        return ROOM, True
    return None, False


def _slope_eV(points: Sequence[Tuple[float, float]]) -> float:
    """-kB × the least-squares slope of y against x = 1/T."""
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return -K_B * sxy / sxx


def fit(points: Sequence[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """The activation energies (from ln σT, from ln σ) of conductivities given as (T in K, σ in S/cm); None when they
    do not span two temperatures MIN_SPAN_K apart."""
    by_t: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
    for t, sigma in points:
        if t > 0 and sigma > 0:
            by_t[round(t, 1)].append((t, sigma))
    if len(by_t) < 2 or max(by_t) - min(by_t) < MIN_SPAN_K:
        return None
    # A value repeated (abstract, text) counts once: one point per temperature.
    one = [(median(t for t, _ in pairs), median(s for _, s in pairs)) for _, pairs in sorted(by_t.items())]
    sigma_t = _slope_eV([(1 / t, math.log(s * t)) for t, s in one])
    sigma = _slope_eV([(1 / t, math.log(s)) for t, s in one])
    return sigma_t, sigma


def judge(reported: float, points: Sequence[Tuple[float, float]], room_assumed: bool = False) -> Check:
    found = fit(points)
    if found is None:
        return Check(NOT_CHECKABLE, reported, reason=f"no conductivities of it {MIN_SPAN_K:g} K apart or more")
    sigma_t, sigma = found
    if max(sigma_t, sigma) <= 0:
        return Check(NOT_CHECKABLE, reported, reason="its conductivities do not rise with temperature: likely of "
                                                     "different samples")
    closest = min((sigma_t, sigma), key=lambda e: abs(e - reported))
    tolerance = max(TOLERANCE_EV, TOLERANCE_SHARE * reported)
    temperatures = [t for t, _ in points]
    return Check(CONSISTENT if abs(closest - reported) <= tolerance else INCONSISTENT, reported, closest, sigma_t,
                 sigma, len({round(t, 1) for t in temperatures}), min(temperatures), max(temperatures), room_assumed)


def _component(text: str) -> str:
    text = (text or "").lower()
    return "grain boundary" if "grain" in text else "bulk" if "bulk" in text else "total" if "total" in text else ""


def cross_check(folder: Path) -> Dict[str, Check]:
    """The check of every activation energy of a database folder, by value id (LocalExtraction.verification)."""
    import pandas as pd
    from .verification import value_id
    folder = Path(folder)
    try:
        energies = pd.read_csv(folder / "activation_energy.csv", dtype=str, keep_default_na=False)
        sigmas = pd.read_csv(folder / "ionic_conductivity.csv", dtype=str, keep_default_na=False)
    except (OSError, ValueError):
        return {}
    groups: Dict[Tuple[str, str, str], List[Tuple[float, float, bool]]] = defaultdict(list)
    for row in sigmas.to_dict("records"):
        t, assumed = kelvin(row.get("temperature", ""))
        try:
            sigma = float(row.get("ionic_conductivity_S_cm", ""))
        except ValueError:
            continue
        if t is not None and sigma > 0:
            groups[(row.get("paper_id", ""), row.get("material_formula", ""), _component(row.get("transport_component")))
                   ].append((t, sigma, assumed))
    checks: Dict[str, Check] = {}
    for row in energies.to_dict("records"):
        try:
            reported = float(row.get("activation_energy_eV", ""))
        except ValueError:
            continue
        paper, material, component = row.get("paper_id", ""), row.get("material_formula", ""), \
            _component(row.get("transport_component"))
        candidates = [key for key in groups if key[0] == paper and key[1] == material]
        same = [key for key in candidates if key[2] == component] if component else []
        chosen = same or (candidates if len(candidates) == 1 else [])
        points: List[Tuple[float, float, bool]] = [p for key in chosen for p in groups[key]]
        measured = {round(t, 1) for t, _, assumed in points if not assumed}
        every = {round(t, 1) for t, _, _ in points}
        if "cited" in (row.get("attribution") or "").lower():
            check = Check(NOT_CHECKABLE, reported, reason="a value the paper cites, not its own measurement")
        elif len(measured) < 2 and len(every) < 3:  # two points, one of them an assumed room temperature: too thin
            check = Check(NOT_CHECKABLE, reported, reason="too few measured temperatures in the paper")
        else:
            check = judge(reported, [(t, s) for t, s, _ in points], room_assumed=any(a for _, _, a in points))
        from dataclasses import replace
        checks[value_id(paper, row.get("page", ""), row.get("sentence", ""), reported, material)] = replace(
            check, paper=paper, material=material)
    return checks


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m LocalExtraction.arrhenius",
                                     description="Checks each activation energy of a database against the paper's own "
                                                 "conductivities at several temperatures.")
    parser.add_argument("folder", help="a results folder (it holds activation_energy.csv and ionic_conductivity.csv)")
    args = parser.parse_args(argv)
    checks = cross_check(Path(args.folder))
    counts = {status: sum(c.status == status for c in checks.values()) for status in (CONSISTENT, INCONSISTENT,
                                                                                      NOT_CHECKABLE)}
    print(f"{len(checks)} activation energies: {counts[CONSISTENT]} consistent, {counts[INCONSISTENT]} inconsistent, "
          f"{counts[NOT_CHECKABLE]} not checkable.")
    for check in checks.values():
        if check.status == INCONSISTENT:
            print(f"  - {check.material} ({check.paper}): {check.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
