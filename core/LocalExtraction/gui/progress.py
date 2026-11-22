# LocalExtraction/gui/progress.py
"""How far a long step is, the same in every window: an estimate when it starts (“about 26 min · done around 15:12”),
the line of the step in dark yellow while it runs, and “⏱ Progress details”: a window that follows the whole step —
its phases, what it is doing now, when each thing was searched or fetched, the time spent and the time left, the pace.

    tracker = Tracker("web", "Web scraping · 2 · Search", [("keywords", "Searching the keywords", "searches"), …])
    tracker.start({"keywords": 2128})           # the estimate, from the pace of the earlier runs
    tracker.update("keywords", 148, 2128, "OpenAlex: “LLZO garnet”", {"new papers": 312})
    status.set(tracker.line())                  # the line of the window
    tracker.finish("done")                      # the pace of this run kept for the next estimate

The pace of each phase (seconds per item) is kept in ~/.moukhlijmatextract/timings.json, as a running mean of the
runs finished: the estimate is the time on this computer, with this network. Before a phase has run once, a first
guess (FIRST_GUESS) is used, and said to be one."""

from __future__ import annotations

import csv
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

from .progress_text import duration

TIMINGS = Path.home() / ".moukhlijmatextract" / "timings.json"
# Seconds per item before a phase has ever run here (a whole run for the phases counted in runs: "run").
FIRST_GUESS: Dict[str, float] = {
    "dois": 6.0, "keywords": 2.5, "records": 0.03, "abstracts": 0.4, "snowball": 3.0, "screen": 0.003,
    "download": 8.0, "extract": 9.0, "local-extract": 9.0, "classify": 0.03, "rank": 4.0, "rank-write": 3.0,
    "mp": 1.0,
}
GOLD = {"light": "#8a6100", "dark": "#e0b23a"}  # dark yellow: readable on the light and the dark windows
SAVED = {"light": "#1a7f37", "dark": "#3fb950"}  # the note that stopping keeps what was done: a calm green
_MEAN_WEIGHT = 0.35  # how much the last run counts in the running mean


def gold(widget) -> str:
    """The dark yellow of the progress line, for the appearance the window is in."""
    from . import theme
    return GOLD["dark" if theme.is_dark(widget) else "light"]


# ------------------------------------------------------------------------------------------------ the paces kept
class Timings:
    """Seconds per item of each phase, from the runs finished (a running mean), kept on disk."""

    def __init__(self, path: Path = TIMINGS):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self.data: Dict[str, Dict[str, float]] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def seconds(self, phase: str) -> Tuple[float, bool]:
        """(seconds per item, measured here before?)."""
        known = self.data.get(phase)
        if known and known.get("seconds_per_item", 0) > 0:
            return float(known["seconds_per_item"]), True
        return FIRST_GUESS.get(phase, 1.0), False

    def record(self, phase: str, seconds: float, items: int) -> None:
        if items <= 0 or seconds <= 0:
            return
        pace = seconds / items
        with self._lock:
            known = self.data.get(phase, {})
            old = known.get("seconds_per_item")
            known["seconds_per_item"] = pace if not old else (1 - _MEAN_WEIGHT) * old + _MEAN_WEIGHT * pace
            known["runs"] = int(known.get("runs", 0)) + 1
            known["last"] = datetime.now().isoformat(timespec="seconds")
            self.data[phase] = known
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            except OSError:
                pass  # a read-only home: the next estimate is a first guess again, nothing worse


# ------------------------------------------------------------------------------------------------ one step followed
@dataclass
class Phase:
    key: str
    title: str
    unit: str = ""
    total: int = 0
    done: int = 0
    started: Optional[float] = None
    ended: Optional[float] = None
    first_done: int = 0  # items done when the phase started (a phase gone back to)

    def state(self) -> str:
        return "done" if self.ended is not None else "now" if self.started is not None else "next"


@dataclass
class Event:
    at: float
    phase: str
    text: str


@dataclass
class Tracker:
    """One long step of a window: its phases, how far each is, what it did when. Updated by the window (on its
    thread); read by the line of the window and by the details window."""
    key: str
    title: str
    phases_spec: Sequence[Tuple[str, str, str]]
    timings: Optional[Timings] = None
    controls: Dict[str, Callable] = field(default_factory=dict)  # "pause", "stop", "paused" (→ bool)
    # What stopping now keeps (“every DOI found so far is saved”): said while the step runs. Empty for a step that
    # cannot be stopped half-way (it writes everything at once).
    saved_on_stop: str = ""

    def __post_init__(self):
        self.timings = self.timings or Timings()
        self.phases: Dict[str, Phase] = {k: Phase(k, t, u) for k, t, u in self.phases_spec}
        self.current: Optional[str] = None
        self.detail = ""
        self.counters: Dict[str, object] = {}
        self.events: Deque[Event] = deque(maxlen=2000)
        self.events_said = 0  # every event ever said (the deque keeps the last 2,000): what a reader has not seen yet
        self.samples: Deque[Tuple[float, int]] = deque(maxlen=4000)  # (time, items done in all): the pace chart
        self.started: Optional[float] = None
        self.ended: Optional[float] = None
        self.outcome = ""
        self.estimate: Optional[float] = None
        self.estimate_measured = False
        self.listeners: List[Callable[[], None]] = []
        # Items of a phase an earlier run finished (searches already answered): counted as done, never timed.
        self.before: Dict[str, int] = {}
        self._last_mark: Optional[float] = None  # the last moment something was said: where a new phase's clock starts

    # ---------------------------------------------------------------- what the window says
    def start(self, totals: Optional[Dict[str, int]] = None, before: Optional[Dict[str, int]] = None) -> None:
        """`before`: items of a phase an earlier run finished (they are skipped): its progress starts there, and neither
        the estimate nor the pace counts them."""
        self.started, self.ended, self.outcome = time.time(), None, ""
        self.before = {key: max(int(count), 0) for key, count in (before or {}).items() if key in self.phases}
        self._last_mark = self.started
        for key, total in (totals or {}).items():
            if key in self.phases:
                self.phases[key].total = max(int(total), 0)
        for key, count in self.before.items():
            self.phases[key].done = count
        self.estimate, self.estimate_measured = self._estimate_all()
        if self.estimate is not None:
            self.event("", f"Started — estimated {duration(self.estimate)} "
                           f"({'from your earlier runs' if self.estimate_measured else 'a first guess'}), "
                           f"done around {clock(self.started + self.estimate)}")
        else:
            self.event("", "Started")
        self._tell()

    def update(self, phase: str, done: int, total: int, detail: str = "",
               counters: Optional[Dict[str, object]] = None) -> None:
        if phase not in self.phases:
            return
        now = time.time()
        if self.started is None:
            self.start()
        if phase != self.current:
            # The first report of a phase comes once its first item is done: its clock starts when the phase before
            # it ended (or the step began), so that every item of it is timed.
            begun = self._last_mark or now
            if self.current is not None and self.phases[self.current].ended is None:
                self.phases[self.current].ended = begun
            p = self.phases[phase]
            again = p.started is not None  # a phase gone back to: counted from where it is now
            p.started, p.ended, p.first_done = begun, None, (max(done - 1, 0) if again else self.before.get(phase, 0))
            for earlier in self.phases_spec:  # the phases before it are over, even those it skipped
                if earlier[0] == phase:
                    break
                q = self.phases[earlier[0]]
                if q.started is not None and q.ended is None:
                    q.ended = now
            self.current = phase
            self.event(phase, f"{p.title} started")
        p = self.phases[phase]
        p.done, p.total = max(int(done), 0), max(int(total), 0)
        if counters:
            self.counters.update(counters)
        if detail and detail != self.detail:
            self.event(phase, f"{detail}  ({p.done:,} of {p.total:,} {p.unit})".replace(" of 0 ", " "))
        self.detail = detail
        self.samples.append((now, sum(q.done for q in self.phases.values())))
        self._last_mark = now
        self._tell()

    def event(self, phase: str, text: str) -> None:
        self.events.append(Event(time.time(), phase, text))
        self.events_said += 1

    def finish(self, outcome: str = "done") -> None:
        """The step ended: "done", "stopped" or "failed". The pace of each phase that went to its end is kept."""
        if self.started is None or self.ended is not None:
            return
        now = time.time()
        self.ended, self.outcome = now, outcome
        for p in self.phases.values():
            if p.started is not None and p.ended is None:
                p.ended = now
            if p.started is not None and outcome == "done":
                items = p.done - p.first_done if p.total else 1  # a phase not counted: one run
                self.timings.record(self._timing_key(p.key), p.ended - p.started, items)
        word = {"done": "Finished", "stopped": "Stopped", "failed": "Failed"}.get(outcome, outcome)
        self.event("", f"{word} after {duration(now - self.started)}")
        self._tell()

    # ---------------------------------------------------------------- read-outs
    def _timing_key(self, phase: str) -> str:
        return f"local-{phase}" if self.key == "local" and phase == "extract" else phase

    def _estimate_all(self) -> Tuple[Optional[float], bool]:
        total, measured, any_known = 0.0, True, False
        for p in self.phases.values():
            pace, known = self.timings.seconds(self._timing_key(p.key))
            if p.total:
                total += pace * max(p.total - self.before.get(p.key, 0), 0)
                any_known = True
            elif p.unit == "":  # a phase counted in runs
                total += pace
                any_known = True
            else:
                continue
            measured &= known
        return (total, measured) if any_known else (None, False)

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return (self.ended or time.time()) - self.started

    def phase_left(self, p: Phase, now: Optional[float] = None) -> Optional[float]:
        """Seconds left of a phase: from its own pace once it has one, else from the pace of the earlier runs."""
        now = time.time() if now is None else now
        if p.ended is not None:
            return 0.0
        pace, _ = self.timings.seconds(self._timing_key(p.key))
        if not p.total:
            if p.unit:
                return None  # counted, but how many is not known yet
            spent = now - p.started if p.started else 0.0
            return max(pace - spent, 0.0)
        worked = p.done - p.first_done
        if p.started is not None and worked >= 2 and now - p.started >= 4:
            pace = (now - p.started) / worked
        return max(p.total - p.done, 0) * pace

    def left(self) -> Optional[float]:
        """Seconds left of the whole step (the phases still to come at the pace of the earlier runs)."""
        if self.ended is not None:
            return 0.0
        total, any_known = 0.0, False
        for p in self.phases.values():
            if p.ended is not None:
                continue
            if p.started is None and p.unit and not p.total:
                continue  # a phase to come whose size is not known (it depends on what is found)
            part = self.phase_left(p)
            if part is not None:
                total += part
                any_known = True
        return total if any_known else None

    def fraction(self) -> float:
        """How far the whole step is, 0 to 1 (by time: each phase weighs what it takes)."""
        if self.ended is not None:
            return 1.0
        left = self.left()
        if left is None:
            return 0.0
        spent = self.elapsed()
        return spent / (spent + left) if spent + left > 0 else 0.0

    def pace_parts(self) -> Tuple[str, str]:
        """(“3.1 s”, “per search”) or, when fast, (“1,795”, “searches / min”); ("–", "") before a pace is set."""
        p = self.phases.get(self.current or "")
        if p is None or p.started is None:
            return "–", ""
        worked = p.done - p.first_done
        spent = (p.ended or time.time()) - p.started
        if worked < 1 or spent <= 0 or not p.unit:
            return "–", ""
        seconds = spent / worked
        if seconds >= 1:
            return f"{seconds:.1f} s", f"per {singular(p.unit)}"
        return f"{60 / seconds:,.0f}", f"{p.unit} / min"

    def pace_text(self) -> str:
        value, per = self.pace_parts()
        return value if not per else f"{value} {per}"

    def time_text(self) -> str:
        """“ · about 6 min left · done around 15:12” (the estimate of the earlier runs before a pace is set)."""
        left = self.left()
        if left is None or self.ended is not None:
            return ""
        return f" · about {duration(left)} left · done around {clock(time.time() + left)}"

    def start_text(self, what: str) -> str:
        """The line as a step starts: what it does, and its estimate."""
        if self.estimate is None:
            return f"{what} …"
        return (f"{what} · estimated {duration(self.estimate)} "
                f"({'from your earlier runs' if self.estimate_measured else 'a first guess'}) · "
                f"done around {clock((self.started or time.time()) + self.estimate)} …")

    def line(self) -> str:
        """The line of the window for the phase under way."""
        p = self.phases.get(self.current or "")
        if p is None:
            return self.title
        text = f"{p.title} — {p.done:,} of {p.total:,} {p.unit}".rstrip() if p.total else f"{p.title} …"
        if self.detail:
            text += f" · {self.detail}"
        for name, value in self.counters.items():
            text += f" · {name}: {value:,}" if isinstance(value, int) else f" · {name}: {value}"
        return text + self.time_text()

    def _tell(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                self.listeners.remove(listener)

    def stop_text(self) -> str:
        """“If you stop now, every DOI found so far is saved.” ("" when stopping keeps nothing to say)."""
        return f"✓ If you stop now, {self.saved_on_stop}." if self.saved_on_stop else ""

    def rows(self) -> List[Dict[str, str]]:
        """The timeline, for the CSV file."""
        return [{"time": datetime.fromtimestamp(e.at).strftime("%Y-%m-%d %H:%M:%S"),
                 "phase": self.phases[e.phase].title if e.phase in self.phases else "",
                 "what": e.text} for e in self.events]


def singular(unit: str) -> str:
    """“search” for “searches”, “paper kept” for “papers kept”, “PDF” for “PDFs” (the first word only)."""
    first, _, rest = unit.partition(" ")
    if first.endswith(("ches", "shes", "sses", "xes")):
        first = first[:-2]
    elif first.endswith("s") and not first.endswith("ss"):
        first = first[:-1]
    return f"{first} {rest}".strip()


def clock(timestamp: float) -> str:
    """15:12 today; “Tue 09:40” another day."""
    moment = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    return moment.strftime("%H:%M") if moment.date() == today else moment.strftime("%a %H:%M")


# ------------------------------------------------------------------------------------------------ the window's line
def style_running(label, running: bool, rest: str = "") -> None:
    """The line of a window in dark yellow while its step runs; back to its colour at the end."""
    try:
        label.configure(foreground=gold(label) if running else rest or "")
    except Exception:
        pass


def stop_note(parent):
    """The line under a window's progress that says what stopping now keeps (not packed: `show_stop_note` does)."""
    from . import theme
    from .widgets import WrapLabel
    return WrapLabel(parent, text="", foreground=SAVED["dark" if theme.is_dark(parent) else "light"])


def show_stop_note(note, tracker: Optional["Tracker"], running: bool, **pack) -> None:
    """Shows the note of `tracker` while its step runs (packed with `pack`), hides it at the end."""
    try:
        text = tracker.stop_text() if (tracker is not None and running) else ""
        if text:
            note.configure(text=text)
            if not note.winfo_manager():
                note.pack(**pack)
        elif note.winfo_manager():
            note.pack_forget()
    except Exception:
        pass


def details_button(parent, tracker_of: Callable[[], Optional[Tracker]], origin: str):
    """“⏱ Progress details”: opens the details window of the window's step (the last one, after it ended)."""
    from tkinter import messagebox, ttk

    def open_it() -> None:
        tracker = tracker_of()
        if tracker is None:
            messagebox.showinfo("MoukhlijMatExtract", "No step has run in this window yet: start one, and its progress "
                                                      "can be followed here.", parent=parent.winfo_toplevel())
            return
        open_details(parent.winfo_toplevel(), tracker, origin)
    return ttk.Button(parent, text="⏱ Progress details", command=open_it)


# ------------------------------------------------------------------------------------------------ the details window
def open_details(parent, tracker: Tracker, origin: str):
    """The window that follows a step (one per window it belongs to: asked again, it comes back, on the step of now)."""
    from .single import bring_back, existing, register
    key = f"progress:{origin}"
    open_one = existing(key)
    if open_one is not None:
        open_one.follow(tracker)
        return bring_back(open_one, f"The progress of {origin}", say=False)
    return register(key, _DetailsWindow(parent, tracker, origin))


def _details_class():
    import tkinter as tk
    from tkinter import filedialog, ttk

    from . import design, layout, theme
    from .widgets import WrapLabel

    class DetailsWindow(tk.Toplevel):
        def __init__(self, parent, tracker: Tracker, origin: str):
            super().__init__(parent)
            self.origin = origin
            self.title(f"MoukhlijMatExtract · Progress — {origin}")
            layout.place(self, (980, 760), (760, 560), parent=parent)
            theme.apply(self)
            self.colours, self.dark = theme.palette(self), theme.is_dark(self)
            design.header(self, "Progress details", origin, compact=True, flow=False)
            # The buttons first, at the bottom: a short window shrinks the timeline, never cuts them off.
            buttons = ttk.Frame(self, padding=(16, 6, 16, 8))
            buttons.pack(side="bottom", fill="x")
            self.pause_button = ttk.Button(buttons, text="Pause", command=self._pause)
            self.pause_button.pack(side="left")
            self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop)
            self.stop_button.pack(side="left", padx=(6, 0))
            ttk.Button(buttons, text="Save the timeline (CSV)…", command=self._save).pack(side="left", padx=(12, 0))
            design.back_button(buttons, self).pack(side="right")
            body = ttk.Frame(self, padding=(16, 10, 16, 6))
            body.pack(fill="both", expand=True)

            self.step_title = ttk.Label(body, text="", font=("TkDefaultFont", 14, "bold"))
            self.step_title.pack(anchor="w")
            self.estimate = WrapLabel(body, text="", style="Muted.TLabel", wraplength=700)
            self.estimate.pack(anchor="w", fill="x", pady=(0, 8))

            tiles = ttk.Frame(body)
            tiles.pack(fill="x")
            self.tiles: Dict[str, ttk.Label] = {}
            self.captions: Dict[str, ttk.Label] = {}
            for column, name in enumerate(("Started", "Elapsed", "Time left", "Expected end", "Pace", "State")):
                tile = ttk.Frame(tiles, padding=(10, 6), relief="solid", borderwidth=1)
                tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
                tiles.columnconfigure(column, weight=1, uniform="tile")
                self.captions[name] = ttk.Label(tile, text=name, style="Muted.TLabel")
                self.captions[name].pack(anchor="w")
                value = ttk.Label(tile, text="–", font=("TkDefaultFont", 14, "bold"))
                value.pack(anchor="w")
                self.tiles[name] = value

            line = ttk.Frame(body)
            line.pack(fill="x", pady=(10, 2))
            self.overall = ttk.Progressbar(line, mode="determinate", maximum=1000)
            self.overall.pack(side="left", fill="x", expand=True)
            self.percent = ttk.Label(line, text="", width=6, anchor="e")
            self.percent.pack(side="left", padx=(8, 0))

            # Now: what it does at this moment, the counters, and the pace chart beside them.
            now_box = ttk.LabelFrame(body, text=" Now ", padding=8)
            now_box.pack(fill="x", pady=(8, 4))
            self.chart = tk.Canvas(now_box, width=260, height=70, highlightthickness=0, background=self.colours["card"])
            self.chart.pack(side="right", padx=(12, 0))
            words = ttk.Frame(now_box)
            words.pack(side="left", fill="both", expand=True)
            self.now = tk.Label(words, text="", justify="left", anchor="w", wraplength=420,
                                font=("TkDefaultFont", 11, "bold"), foreground=gold(self),
                                background=ttk.Style().lookup("TFrame", "background") or self.colours["card"])
            self.now.pack(anchor="w", fill="x")
            words.bind("<Configure>", lambda event: self.now.configure(wraplength=max(event.width - 8, 160)))
            self.counters = WrapLabel(words, text="", wraplength=420)
            self.counters.pack(anchor="w", fill="x", pady=(6, 0))
            self.saved = WrapLabel(words, text="", wraplength=420, foreground=SAVED["dark" if self.dark else "light"])
            self.saved.pack(anchor="w", fill="x", pady=(6, 0))  # what stopping now keeps
            ttk.Label(words, text="The chart: items done per minute, minute by minute", style="Muted.TLabel").pack(
                anchor="w", pady=(6, 0))

            self.phase_box = ttk.LabelFrame(body, text=" The phases of the step ", padding=8)
            self.phase_box.pack(fill="x", pady=(4, 4))

            ttk.Label(body, text="Timeline — what was searched or fetched, and when (the newest first)",
                      style="Section.TLabel").pack(anchor="w", pady=(8, 2))
            table = ttk.Frame(body)
            table.pack(fill="both", expand=True)
            self.timeline = ttk.Treeview(table, columns=("time", "phase", "what"), show="headings", height=8)
            for column, width, stretch in (("time", 80, False), ("phase", 200, False), ("what", 520, True)):
                self.timeline.heading(column, text=column.capitalize())
                self.timeline.column(column, width=width, stretch=stretch, anchor="w")
            bar = ttk.Scrollbar(table, orient="vertical", command=self.timeline.yview)
            self.timeline.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y")
            self.timeline.pack(side="left", fill="both", expand=True)
            design.website_line(self)
            self.bind("<Escape>", lambda event: design.go_back(self))
            self._after = None  # the next refresh: cancelled when the window closes
            self.bind("<Destroy>", self._closed, add="+")

            self.tracker: Optional[Tracker] = None
            self._phase_rows: Dict[str, Tuple] = {}
            self._shown_events = 0
            self.follow(tracker)
            self._tick()

        # ------------------------------------------------------------ following a step
        def follow(self, tracker: Tracker) -> None:
            """Follows `tracker` (the step of now, or the last one)."""
            if tracker is self.tracker:
                return
            self.tracker = tracker
            for child in self.phase_box.winfo_children():
                child.destroy()
            self._phase_rows = {}
            for row, (key, title, unit) in enumerate(tracker.phases_spec):
                mark = ttk.Label(self.phase_box, text="○", width=2)
                mark.grid(row=row, column=0, sticky="w")
                name = ttk.Label(self.phase_box, text=title)
                name.grid(row=row, column=1, sticky="w", padx=(2, 8))
                bar = ttk.Progressbar(self.phase_box, mode="determinate", maximum=1000, length=120)
                bar.grid(row=row, column=2, sticky="ew", padx=(0, 8))
                count = ttk.Label(self.phase_box, text="", style="Muted.TLabel")
                count.grid(row=row, column=3, sticky="w")
                self._phase_rows[key] = (mark, name, bar, count)
            self.phase_box.columnconfigure(2, weight=1)
            self.timeline.delete(*self.timeline.get_children())
            self._shown_events = 0
            self.step_title.configure(text=tracker.title)
            if tracker.estimate is not None:
                self.estimate.configure(
                    text=f"Estimated when it started: {duration(tracker.estimate)} "
                         f"({'from your earlier runs on this computer' if tracker.estimate_measured else 'a first guess: the next runs are estimated from this one'})")
            else:
                self.estimate.configure(text="")
            has = bool(tracker.controls)
            for button in (self.pause_button, self.stop_button):
                button.configure(state="normal" if has else "disabled")

        def _tick(self) -> None:
            self._after = None
            try:
                if not self.winfo_exists():
                    return
                self.refresh()
                self._after = self.after(500, self._tick)
            except tk.TclError:
                return

        def _closed(self, event) -> None:
            if event.widget is self and self._after is not None:
                try:
                    self.after_cancel(self._after)
                except tk.TclError:
                    pass
                self._after = None

        def refresh(self) -> None:
            t = self.tracker
            if t is None:
                return
            running = t.ended is None and t.started is not None
            left = t.left()
            paused = bool(t.controls.get("paused", lambda: False)()) if running else False
            values = {
                "Started": clock(t.started) if t.started else "–",
                "Elapsed": duration(t.elapsed()) if t.started else "–",
                "Time left": ("–" if left is None else duration(left)) if running else "0 s",
                "Expected end": (clock(time.time() + left) if left is not None else "–") if running
                                else (clock(t.ended) if t.ended else "–"),
                "Pace": t.pace_parts()[0],
                "State": "Paused" if paused else "Running" if running else
                         {"done": "Done", "stopped": "Stopped", "failed": "Failed"}.get(t.outcome, "–"),
            }
            for name, value in values.items():
                self.tiles[name].configure(text=value)
            per = t.pace_parts()[1]
            self.captions["Pace"].configure(text=f"Pace ({per})" if per else "Pace")
            fraction = t.fraction()
            self.overall.configure(value=int(fraction * 1000))
            self.percent.configure(text=f"{100 * fraction:.0f} %")
            for key, (mark, name, bar, count) in self._phase_rows.items():
                p = t.phases[key]
                state = p.state()
                mark.configure(text={"done": "✓", "now": "▶", "next": "○"}[state])
                name.configure(font=("TkDefaultFont", 11, "bold") if state == "now" else ("TkDefaultFont", 11))
                bar.configure(value=int(1000 * p.done / p.total) if p.total else (1000 if state == "done" else 0))
                spent = ((p.ended or time.time()) - p.started) if p.started else 0
                words = f"{p.done:,} of {p.total:,} {p.unit}".strip() if p.total else ("done" if state == "done" else "")
                if p.started:
                    words += f" · {duration(spent)}"
                    if state == "now":
                        part = t.phase_left(p)
                        if part is not None:
                            words += f" · {duration(part)} left"
                count.configure(text=words)
            self.now.configure(text=(t.line() if running else
                                     f"{values['State']} — {t.title}, in {duration(t.elapsed())}"))
            self.counters.configure(text="   ".join(
                f"{name}: {value:,}" if isinstance(value, int) else f"{name}: {value}"
                for name, value in t.counters.items()))
            self.saved.configure(text=t.stop_text() if running else "")
            self.pause_button.configure(text="Resume" if paused else "Pause",
                                        state="normal" if running and t.controls else "disabled")
            self.stop_button.configure(state="normal" if running and t.controls else "disabled")
            # The events said since the last look (the deque keeps the last 2,000, so its length stops growing: a
            # long search went on, its timeline did not).
            unseen = min(t.events_said - self._shown_events, len(t.events))
            events = list(t.events)[len(t.events) - unseen:] if unseen > 0 else []
            for event in events:
                phase = t.phases[event.phase].title if event.phase in t.phases else ""
                self.timeline.insert("", 0, values=(datetime.fromtimestamp(event.at).strftime("%H:%M:%S"), phase,
                                                    event.text))
            self._shown_events = t.events_said
            rows = self.timeline.get_children()
            if len(rows) > 2000:  # the newest stay (inserted at the top); the oldest go
                self.timeline.delete(*rows[2000:])
            self._draw_chart(t)

        def _draw_chart(self, t: Tracker) -> None:
            """Items per minute, minute by minute (thin line, quiet axis)."""
            canvas = self.chart
            canvas.delete("all")
            width, height = max(canvas.winfo_width(), 200), int(canvas.cget("height"))
            samples = list(t.samples)
            if len(samples) < 2:
                canvas.create_text(8, height / 2, text="The pace is drawn once a few items are done.", anchor="w",
                                   fill=self.colours["muted"], font=("TkDefaultFont", 10))
                return
            start = samples[0][0]
            minutes: Dict[int, int] = {}
            previous = samples[0][1]
            for at, total in samples[1:]:
                minute = int((at - start) // 60)
                minutes[minute] = minutes.get(minute, 0) + max(total - previous, 0)
                previous = total
            last = max(minutes)
            values = [minutes.get(m, 0) for m in range(last + 1)][-60:]
            top = max(values) or 1
            step = (width - 16) / max(len(values) - 1, 1)
            canvas.create_line(8, height - 6, width - 8, height - 6, fill=self.colours["line"])
            points = []
            for index, value in enumerate(values):
                points += [8 + index * step, height - 8 - (height - 20) * value / top]
            if len(points) >= 4:
                canvas.create_line(*points, fill=self.colours["accent"], width=2, smooth=True)
            canvas.create_text(width - 8, 6, text=f"peak {top:,} per minute", anchor="ne",
                               fill=self.colours["muted"], font=("TkDefaultFont", 9))

        # ------------------------------------------------------------ buttons
        def _pause(self) -> None:
            control = (self.tracker.controls if self.tracker else {}).get("pause")
            if control:
                control()

        def _stop(self) -> None:
            control = (self.tracker.controls if self.tracker else {}).get("stop")
            if control:
                control()

        def _save(self) -> None:
            if self.tracker is None:
                return
            path = filedialog.asksaveasfilename(parent=self, title="Save the timeline", defaultextension=".csv",
                                                initialfile="progress_timeline.csv",
                                                filetypes=[("CSV", "*.csv")])
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["time", "phase", "what"])
                writer.writeheader()
                writer.writerows(self.tracker.rows())

    return DetailsWindow


def _DetailsWindow(parent, tracker: Tracker, origin: str):
    return _details_class()(parent, tracker, origin)
