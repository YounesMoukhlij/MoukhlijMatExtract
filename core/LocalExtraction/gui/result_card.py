# LocalExtraction/gui/result_card.py
"""What a step has done, shown the moment it ends — the same card in every window of the project.

    ✓  Extraction finished                                   finished 14:32 · took 3 min 12 s   ✕
       23 new articles read into LocalExtraction/local_output
    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
    │   23   │ │   61   │ │   46   │ │  260   │      big numbers, a coloured bar on top of each
    │articles│ │  Ea    │ │   σ    │ │materials│
    └────────┘ └────────┘ └────────┘ └────────┘
    • Lowest activation energy: Li6PS5Cl — 0.19 eV (Article title)
    [ Open the workbook ]  [ Show the activation energies ]  [ Open the folder ]

A window makes one card (`ResultCard`), placed where it should appear; `show(Outcome)` fills it and
makes it appear, `hide()` takes it away (a new run hides it). The tiles wrap when the window narrows."""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .widgets import WrapLabel

DONE, WARNING, FAILED, NOTHING = "done", "warning", "failed", "nothing"
_LOOK: Dict[str, Tuple[str, str]] = {  # status → (sign, colour)
    DONE: ("✓", "#2e9e5b"), WARNING: ("⚠", "#d08c00"), FAILED: ("✕", "#d0453f"), NOTHING: ("○", "#8c8c8c"),
}
ACCENT = "#4a90d9"
GOOD, BAD, GREY = "#2e9e5b", "#d0453f", "#8c8c8c"
_TILE_WIDTH = 190


@dataclass
class Stat:
    value: str
    label: str
    accent: str = ACCENT
    hint: str = ""  # a small line under the label: "+5 new", "of 40,825"


@dataclass
class Outcome:
    title: str
    status: str = DONE
    detail: str = ""
    stats: List[Stat] = field(default_factory=list)
    highlights: List[str] = field(default_factory=list)
    actions: List[Tuple[str, Callable[[], None]]] = field(default_factory=list)
    started: Optional[float] = None  # time.time() when the step began: the card says how long it took


def number(n: int) -> str:
    return f"{n:,}"


def took(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes:02d} min"
    days, hours = divmod(hours, 24)  # many hours said in days
    return f"{days} day{'s' if days > 1 else ''}" + (f" {hours} h" if hours else "")


class ResultCard(ttk.Frame):
    """The card; hidden until `show`. `pack_options` say where it goes when shown."""

    def __init__(self, parent: tk.Misc, **pack_options):
        super().__init__(parent, padding=(12, 8), relief="solid", borderwidth=1)
        self._pack = {"fill": "x", "pady": (4, 8), **pack_options}
        self.outcome: Optional[Outcome] = None
        self._tiles: List[ttk.Frame] = []
        self._tile_area: Optional[ttk.Frame] = None

    # ------------------------------------------------------------------
    def show(self, outcome: Outcome, bell: bool = True) -> None:
        self.outcome = outcome
        for child in self.winfo_children():
            child.destroy()
        sign, colour = _LOOK.get(outcome.status, _LOOK[DONE])

        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Label(head, text=sign, foreground=colour, font=("TkDefaultFont", 18, "bold")).pack(side="left", padx=(0, 10))
        titles = ttk.Frame(head)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text=outcome.title, font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        if outcome.detail:
            WrapLabel(titles, text=outcome.detail, foreground=GREY, justify="left").pack(fill="x", anchor="w")
        ttk.Button(head, text="✕", width=2, command=self.hide).pack(side="right", anchor="n")
        when = datetime.now().strftime("finished %H:%M")
        if outcome.started is not None:
            when += f" · took {took(time.time() - outcome.started)}"
        ttk.Label(head, text=when, foreground=GREY).pack(side="right", anchor="n", padx=8)

        if outcome.stats:
            self._tile_area = ttk.Frame(self)
            self._tile_area.pack(fill="x", pady=(8, 0))
            self._tiles = [self._tile(self._tile_area, stat) for stat in outcome.stats]
            self._tile_area.bind("<Configure>", lambda e: self._arrange(e.width))
            self._arrange(self.winfo_width() or 900)

        if outcome.highlights:
            lines = ttk.Frame(self)
            lines.pack(fill="x", pady=(4, 0))
            for line in outcome.highlights[:4]:
                WrapLabel(lines, text=f"•  {line}", justify="left").pack(fill="x", anchor="w", pady=1)

        if outcome.actions:
            buttons = ttk.Frame(self)
            buttons.pack(fill="x", pady=(8, 0))
            for index, (label, action) in enumerate(outcome.actions):
                ttk.Button(buttons, text=label, command=action).pack(side="left", padx=(0 if index == 0 else 6, 0))

        if not self.winfo_ismapped():
            self.pack(**self._pack)
        if bell:
            try:
                self.bell()
            except tk.TclError:
                pass

    def hide(self) -> None:
        if self.winfo_ismapped() or self.winfo_manager():
            self.pack_forget()

    # ------------------------------------------------------------------
    @staticmethod
    def _tile(parent: ttk.Frame, stat: Stat) -> ttk.Frame:
        tile = ttk.Frame(parent, padding=(10, 0, 10, 6), relief="groove", borderwidth=1)
        tk.Frame(tile, height=3, background=stat.accent or ACCENT).pack(fill="x", pady=(0, 4))
        line = ttk.Frame(tile)
        line.pack(fill="x")
        ttk.Label(line, text=stat.value, font=("TkDefaultFont", 18, "bold")).pack(side="left")
        ttk.Label(line, text=stat.label).pack(side="left", padx=(6, 0), anchor="s", pady=(0, 2))
        if stat.hint:
            ttk.Label(tile, text=stat.hint, foreground=GREY, font=("TkDefaultFont", 10)).pack(anchor="w")
        return tile

    def _arrange(self, width: int) -> None:
        """As many tiles on a line as the width holds; the rest go below."""
        if not self._tiles:
            return
        columns = max(1, min(len(self._tiles), max(width, _TILE_WIDTH) // _TILE_WIDTH))
        for index, tile in enumerate(self._tiles):
            tile.grid(row=index // columns, column=index % columns, sticky="nsew", padx=(0, 6), pady=(0, 6))
        for column in range(len(self._tiles)):
            self._tile_area.columnconfigure(column, weight=1 if column < columns else 0, uniform="tile" if column < columns else "")


def stats_line(stats: Sequence[Stat]) -> str:
    """The tiles as one line of text, for the log: "23 articles read · 61 activation energies"."""
    return " · ".join(f"{s.value} {s.label}" for s in stats)
