# SelectingTopMaterial/console.py
"""What the terminal says of a ranking: what was read, the rule, how many materials each class
holds, and the materials that pass, best first.

Colour is an extra here, never the message: every class is written by name beside its mark, so the
same text reads right in a file, in a terminal without colours, or with NO_COLOR set."""

from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import loader
from .about import NAME, VERSION
from .criteria import POLICIES, EnergyClass
from .models import NOT_REPORTED, RankedMaterial, Selection

_MARKS = ("◆", "●", "○", "◇", "▪")  # the accepted classes, best first; past the fifth, the last again
_REJECTED_MARK = "×"
_COLOURS = ("32", "36", "33", "35", "34")  # green, cyan, yellow, magenta, blue: the terminal's own
_SHORT_ORIGIN = {"experimental": "exp", "simulation": "sim"}
_NAME_WIDTH = 30
_REJECTED_SHOWN = 8


def use_colour(stream: TextIO, wanted: bool | None = None) -> bool:
    """Whether to colour what goes to a stream: when asked, otherwise in a terminal that has
    not said no (NO_COLOR, TERM=dumb)."""
    if wanted is not None:
        return wanted
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def render(selection: Selection, *, top: int | None = None, colour: bool = False, width: int | None = None,
           written: Sequence[Path] = (), out_dir: str = "") -> str:
    """The whole of what the terminal shows, as text."""
    paint = _Painter(colour, selection)
    lines = [paint.bold(f"{NAME} {VERSION}") + " — materials ranked by activation energy", ""]

    labelled = [("Read", f"{report.path:<{max(len(r.path) for r in selection.databases)}}   {loader.describe(report)}")
                for report in selection.databases]
    labelled.append(("Ea used", f"{selection.policy} — {POLICIES[selection.policy]}"))
    if selection.by_phase:
        labelled.append(("Materials", "one per phase of a composition"))
    labelled.append(("Values", f"{selection.filters.describe()} ({selection.values_used} of {selection.values_read}) · "
                               f"{_count(selection.papers_used, 'paper')} · {_count(len(selection.materials), 'material')}"))
    previous = ""
    for label, text in labelled:
        heading = label if label != previous else ""  # "Read" once, above the folders it covers
        lines.append(f"  {paint.dim(f'{heading:<10}')} {text}")
        previous = label
    lines.append("")

    classes = selection.criteria.classes
    name_width, rule_width = max(len(c.name) for c in classes), max(len(c.rule) for c in classes)
    for energy_class in classes:
        lines.append(f"  {paint.mark(energy_class)} {energy_class.name:<{name_width}}   "
                     f"{energy_class.rule:<{rule_width}}   {_count(selection.count(energy_class), 'material')}")
    lines.append("")

    shown = selection.top[:top]
    if shown:
        title = f"Top materials ({len(selection.top)})" if len(shown) == len(selection.top) \
            else f"Top materials (the first {len(shown)} of {len(selection.top)})"
        lines += ["  " + paint.bold(title), ""]
        lines += _table(shown, paint, name_width, width)
    elif selection.materials:
        lines.append("  No material passes: every one of them is in the rejected class.")
    else:
        lines.append("  No activation energy to rank" + (
            f" — none of the {selection.values_read} values read passes the filters ({selection.filters.describe()})."
            if selection.values_read else "."))

    if selection.rejected:
        names = [f"{m.material} {m.energy_eV:.3f}" for m in selection.rejected[:_REJECTED_SHOWN]]
        more = len(selection.rejected) - len(names)
        lines += ["", f"  {paint.mark(selection.criteria.rejected)} {selection.criteria.rejected.name} "
                      f"({len(selection.rejected)}): " + paint.dim(" · ".join(names) + (f" … and {more} more" if more > 0 else ""))]
    for note in selection.notes:
        lines += ["", f"  {paint.dim('Note')} {note}"]
    if written:
        lines += ["", f"  {paint.dim('Written to')} {out_dir}", "    " + "  ".join(path.name for path in written)]
    return "\n".join(lines) + "\n"


def _table(materials: Sequence[RankedMaterial], paint: _Painter, class_width: int, width: int | None) -> list[str]:
    headers = ("#", "Material", "Class", "Ea (eV)", "Range (eV)", "Values", "Papers", "Origin", "Checks")
    rows = []
    for m in materials:
        spread = f"{m.energy_min_eV:.3f} – {m.energy_max_eV:.3f}" if len(m.values) > 1 else "single value"
        rows.append((str(m.rank), _clip(m.material, _NAME_WIDTH), m.energy_class.name, f"{m.energy_eV:.3f}", spread,
                     str(len(m.values)), str(len(m.papers)), _origin(m), " | ".join(m.checks) or "ok"))
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    widths[2] = max(widths[2], class_width) + 2  # the mark and a space before the class name
    right = {0, 3, 5, 6}  # numbers line up on their last digit
    # The checks come last and take what is left of the line; in a narrow terminal they are cut short.
    taken = 2 + sum(widths[:-1]) + 2 * (len(widths) - 1)
    room = max(width - taken, 12) if width else None

    def line(cells: Sequence[str], mark: str = "") -> str:
        parts = []
        for i, cell in enumerate(cells[:-1]):
            if i == 2 and mark:
                parts.append(f"{mark} {cell:<{widths[i] - 2}}")
            else:
                parts.append(f"{cell:>{widths[i]}}" if i in right else f"{cell:<{widths[i]}}")
        return "  " + "  ".join(parts) + "  " + (_clip(cells[-1], room) if room else cells[-1])

    return [paint.dim(line(headers))] + [line(row, mark=paint.mark(m.energy_class)) for m, row in zip(materials, rows)]


def _origin(material: RankedMaterial) -> str:
    """Where the values of a material come from, short: "simulation", "exp 1 · sim 2"."""
    counts = Counter(v.data_origin for v in material.values if v.data_origin != NOT_REPORTED)
    if not counts:
        return NOT_REPORTED
    if len(counts) == 1:
        return next(iter(counts))
    return " · ".join(f"{_SHORT_ORIGIN.get(origin, origin)} {count}" for origin, count in sorted(counts.items()))


def _clip(text: str, room: int) -> str:
    return text if len(text) <= room else text[:max(room - 1, 1)] + "…"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def terminal_width(stream: TextIO = sys.stdout) -> int | None:
    """How wide a line may be: the terminal's width, and no limit for a file or a pipe."""
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return None
    return shutil.get_terminal_size((120, 24)).columns


class _Painter:
    """Colours text when colours are on; gives it back unchanged when they are off."""

    def __init__(self, enabled: bool, selection: Selection):
        self.enabled = enabled
        accepted = [c for c in selection.criteria.classes if c.accepted]
        self._marks = {c.name: (_MARKS[min(i, len(_MARKS) - 1)], _COLOURS[min(i, len(_COLOURS) - 1)])
                       for i, c in enumerate(accepted)}

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def dim(self, text: str) -> str:
        return self._wrap(text, "2")

    def mark(self, energy_class: EnergyClass) -> str:
        """The sign of a class: a shape of its own, in its colour."""
        if not energy_class.accepted:
            return self._wrap(_REJECTED_MARK, "2")
        mark, code = self._marks[energy_class.name]
        return self._wrap(mark, f"1;{code}")
