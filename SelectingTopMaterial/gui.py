# SelectingTopMaterial/gui.py
"""The window of the selection: the options of the command line as fields, the ranked materials in
a table, and the files it writes one click away.

    python -m SelectingTopMaterial gui

It reads the results folders and writes into its own results/ (which "Delete outputs…" empties)."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from LocalExtraction.gui.delete_outputs import delete_outputs_button
from LocalExtraction.gui.result_card import NOTHING, Outcome, ResultCard, Stat, number

from . import loader
from LocalExtraction.about import command_name, enter_project_home

from .about import DEFAULT_RESULTS, NAME, PROJECT_ROOT
from .cli import (ENERGY_KINDS, FORMATS, ranking_run, ranking_settings, ranking_stamp, record_ranking, source_folder,
                  write_rankings)
from .console import origin_summary
from .exporters import rank_interval
from .criteria import DOMAIN_CRITERIA, POLICIES, Criteria, CriteriaError, format_energy
from .models import COMPONENTS, Filters, RankedMaterial, Selection, component_word
from .palette import REJECTED, class_colours
from .selection import select_from_each

_ANY = "any"
# (column, heading, width, anchor)
_COLUMNS = (("rank", "#", 44, "e"), ("material", "material", 230, "w"), ("class", "class", 104, "w"),
            ("ea", "Ea (eV)", 70, "e"), ("range", "range (eV)", 110, "w"), ("values", "values", 58, "e"),
            ("papers", "papers", 58, "e"), ("interval", "rank 95 %", 80, "w"), ("evidence", "evidence", 70, "w"),
            ("origin", "origin", 130, "w"), ("checks", "checks", 300, "w"))


def open_path(path: Path) -> None:
    """Shows a file or a folder with the program the system uses for it."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _shown(path: Path) -> str:
    """A folder as the window names it: from the project root, when it is under it."""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def elements(text: str) -> tuple[str, ...]:
    """The element symbols of a field — "Li, na" → ("Li", "Na"). Raises ValueError on one that is not."""
    symbols = [part.strip().capitalize() for part in re.split(r"[\s,;+]+", text) if part.strip()]
    for symbol in symbols:
        if symbol not in loader._ELEMENTS:
            raise ValueError(f"Elements: {symbol!r} is not the symbol of an element (Li, Na, ...)")
    return tuple(dict.fromkeys(symbols))


class App:
    def __init__(self, root: tk.Tk, sources: Sequence[Path] | None = None, out_dir: Path = DEFAULT_RESULTS,
                 criteria_path: str | None = None):
        self.root = root
        from LocalExtraction.gui import theme
        theme.apply(root)  # buttons that light up under the mouse
        root.title(f"MoukhlijMatExtract (MME) · {NAME} · Ranking the materials")
        from LocalExtraction.gui import layout
        # Fitted to the screen it opens on and centred; at least the settings, the Materials Project line and a table
        # of a few rows (as far as the screen allows: the settings then scroll).
        layout.place(root, (1260, 820), (1000, 720))
        self.criteria_path = criteria_path
        self.selections: dict[str, Selection] = {}   # one ranking per transport component
        self.written: list[Path] = []
        self.written_by: dict[str, list[Path]] = {}
        self.tabs: dict[str, dict] = {}                # component → its tab: frame, table, materials shown
        self._top: int | None = None
        self._ranking = False  # a ranking runs on its thread
        known = [PROJECT_ROOT / name for name in loader.KNOWN_DATABASES]
        # The databases of the other web jobs (WebScraping/web_output_<job>) are offered, not ticked: each is a
        # corpus of its own, ranked with the others only when asked.
        self._other_jobs = [] if sources else loader.job_databases(PROJECT_ROOT)
        self._build(list(sources) if sources else known + self._other_jobs, out_dir, ticked_missing=bool(sources))
        self.rank(write=False)  # what the folders hold, at once; the files are written on “Rank”

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build(self, folders: list[Path], out_dir: Path, ticked_missing: bool) -> None:
        from LocalExtraction.gui import design
        from LocalExtraction.gui.about_window import open_about
        design.header(self.root, "Ranking the materials", "by activation energy, one ranking per transport component",
                      compact=True)
        design.footer(self.root, about=lambda: open_about(self.root)).pack(side="bottom", fill="x")

        # The settings and the card of the last ranking above, the ranked materials below, with a divider between:
        # the tables keep their room in a short window (_fit_split), and the divider can be dragged.
        split = ttk.PanedWindow(self.root, orient="vertical")
        split.pack(fill="both", expand=True)
        from LocalExtraction.gui.widgets import Scrolled
        holder = Scrolled(split)  # the settings scroll when the divider (or a small screen) leaves them short
        top = holder.inner
        split.add(holder, weight=0)
        self._split, self._upper = split, top
        settings = ttk.Frame(top, padding=(12, 4, 12, 4))
        settings.pack(fill="x")
        self._settings = settings
        # The two columns side by side, with a line to drag between them: widen the one you are reading.
        columns = ttk.PanedWindow(settings, orient="horizontal")
        columns.pack(fill="x")

        # Where the values come from
        sources = ttk.LabelFrame(columns, text=" Results folders — the most trusted first ", padding=8)
        columns.add(sources, weight=1)
        self._sources_frame = sources
        self.sources: list[tuple[Path, tk.BooleanVar, tk.StringVar]] = []
        for folder in folders:
            self._add_source(folder, ticked=ticked_missing or ((folder / loader.TABLE).is_file()
                                                               and folder not in self._other_jobs))
        ttk.Button(sources, text="Add a folder…", command=self._pick_source).grid(
            row=999, column=0, sticky="w", pady=(6, 0))

        # Which values take part, and how one stands for a material
        options = ttk.LabelFrame(columns, text=" Which values, and which one stands for a material ", padding=8)
        columns.add(options, weight=1)
        self.policy_var = tk.StringVar()
        self.origin_var = tk.StringVar(value=_ANY)
        self.attribution_var = tk.StringVar(value=_ANY)
        self.component_var = tk.StringVar()
        self.elements_var = tk.StringVar()
        self.confidence_var = tk.StringVar(value="0")
        self.by_phase_var = tk.BooleanVar(value=False)
        self.top_var = tk.StringVar()
        self.rejected_var = tk.BooleanVar(value=True)
        # As mme-rank --domain, --kind and --include-flagged, with the same defaults.
        self.domain_var = tk.StringVar(value="electrolyte")
        self.kind_var = tk.StringVar(value=_ANY)
        self.flagged_var = tk.BooleanVar(value=False)
        self.verified_var = tk.BooleanVar(value=False)

        ttk.Label(options, text="Ea of a material").grid(row=0, column=0, sticky="w")
        policy = ttk.Combobox(options, values=tuple(POLICIES), textvariable=self.policy_var, state="readonly", width=13)
        policy.grid(row=0, column=1, sticky="w", padx=4)
        self.policy_meaning = tk.StringVar()
        ttk.Label(options, textvariable=self.policy_meaning, foreground="#8c8c8c").grid(
            row=0, column=2, columnspan=3, sticky="w")
        policy.bind("<<ComboboxSelected>>", lambda event: self._policy_changed())

        ttk.Label(options, text="Origin").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(options, values=(_ANY, "experimental", "simulation"), textvariable=self.origin_var,
                     state="readonly", width=13).grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="Result of").grid(row=1, column=2, sticky="e", pady=(6, 0))
        ttk.Combobox(options, values=(_ANY, "this work", "cited"), textvariable=self.attribution_var,
                     state="readonly", width=11).grid(row=1, column=3, sticky="w", padx=4, pady=(6, 0))

        ttk.Label(options, text="Component").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(options, textvariable=self.component_var, width=15).grid(row=2, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="Elements").grid(row=2, column=2, sticky="e", pady=(6, 0))
        ttk.Entry(options, textvariable=self.elements_var, width=13).grid(row=2, column=3, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="(bulk, total, … · Li Na)", foreground="#8c8c8c").grid(
            row=2, column=4, sticky="w", pady=(6, 0))

        ttk.Label(options, text="Confidence ≥").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(options, from_=0, to=1, increment=0.05, textvariable=self.confidence_var, width=6).grid(
            row=3, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="Show the first").grid(row=3, column=2, sticky="e", pady=(6, 0))
        ttk.Entry(options, textvariable=self.top_var, width=6).grid(row=3, column=3, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="(empty: all that pass)", foreground="#8c8c8c").grid(
            row=3, column=4, sticky="w", pady=(6, 0))

        ttk.Checkbutton(options, text="Rank the phases of a composition apart (cubic / tetragonal, β / γ)",
                        variable=self.by_phase_var).grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text="Show the rejected materials too", variable=self.rejected_var,
                        command=self._fill_tables).grid(row=5, column=0, columnspan=5, sticky="w", pady=(2, 0))

        ttk.Label(options, text="Kind of Ea").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(options, values=(_ANY, *ENERGY_KINDS), textvariable=self.kind_var, state="readonly",
                     width=17).grid(row=6, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="Classes of").grid(row=6, column=2, sticky="e", pady=(6, 0))
        ttk.Combobox(options, values=tuple(DOMAIN_CRITERIA), textvariable=self.domain_var, state="readonly",
                     width=11).grid(row=6, column=3, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(options, text="(arrhenius: the measured Ea only)", foreground="#8c8c8c").grid(
            row=6, column=4, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text="Include the values the extraction flagged (out of range, not an electrolyte, …)",
                        variable=self.flagged_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Checkbutton(options, text="Verified values only (the Verify tab)", variable=self.verified_var).grid(
            row=7, column=3, columnspan=2, sticky="w", pady=(2, 0))

        # Where the ranking is written, and the buttons
        actions = ttk.Frame(top, padding=(12, 6, 12, 4))
        actions.pack(fill="x")
        self._actions = actions
        # The files of the ranking on a line of their own: on one line with the rest, a narrow window cut them.
        files = ttk.Frame(top, padding=(12, 0, 12, 4))
        files.pack(fill="x")
        self._files_row = files
        self._materials_project_row(top)
        self.rank_button = ttk.Button(actions, text="Rank", command=self.rank)
        self.rank_button.pack(side="left")
        self.write_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="and write the files into", variable=self.write_var).pack(side="left", padx=(10, 4))
        self.out_var = tk.StringVar(value=str(out_dir))
        ttk.Entry(actions, textvariable=self.out_var, width=8).pack(side="left", fill="x", expand=True)  # it widens with the window
        ttk.Button(actions, text="Browse…", command=self._pick_out).pack(side="left", padx=4)
        self.open_report_button = ttk.Button(files, text="Open the report", command=lambda: self._open(".html"))
        self.open_report_button.pack(side="left")
        self.open_workbook_button = ttk.Button(files, text="Open the workbook", command=lambda: self._open(".xlsx"))
        self.open_workbook_button.pack(side="left", padx=4)
        delete_outputs_button(files, "rank", after=self._outputs_deleted).pack(side="right", padx=(4, 0))
        from LocalExtraction.gui.csv_browser import results_buttons
        self.open_folder_button, self.browse_button = results_buttons(files, "3 · Ranking",
                                                                      lambda: self.out_var.get())

        self.summary = tk.StringVar(value="")
        self.summary_label = ttk.Label(top, textvariable=self.summary, wraplength=1200, justify="left",
                                       padding=(12, 4))
        self.summary_label.pack(fill="x")

        self.book = ttk.Notebook(split, padding=(8, 0, 8, 8))
        split.add(self.book, weight=1)
        self.card = ResultCard(top, padx=8)  # what the last ranking found
        for event in ("<Map>", "<Unmap>"):  # the card shown or closed: the divider follows
            self.card.bind(event, lambda e: self.root.after_idle(self._fit_split), add="+")
        split.bind("<Configure>", lambda e: self._fit_split(), add="+")
        self.about = tk.Text(self.book, wrap="word", relief="flat", padx=10, pady=8, state="disabled")
        self.book.add(self.about, text="Rule and data")
        for component in COMPONENTS:  # bulk, grain boundary, total: each ranked on its own
            self._ranking_tab(component)
        self.book.select(0)
        self.book.bind("<<NotebookTabChanged>>", lambda event: self._buttons())

    def _materials_project_row(self, parent: ttk.Frame) -> None:
        """The person's own Materials Project key (typed hidden, saved with the other keys in
        ~/MoukhlijMatExtract/.env) and whether a ranking also writes each material's entry
        (materials_project.py)."""
        from WebScraping.averageScrap.job import load_env
        load_env()  # a key saved before (here or in the Web scraping window's "API keys…")
        row = ttk.Frame(parent, padding=(12, 0, 12, 4))
        row.pack(fill="x")
        self._mp_row = row
        ttk.Label(row, text="Materials Project key").pack(side="left")
        self.mp_key_var = tk.StringVar(value=os.environ.get("MP_API_KEY", ""))
        self.mp_key_entry = ttk.Entry(row, textvariable=self.mp_key_var, show="•", width=26)
        self.mp_key_entry.pack(side="left", padx=(6, 4))
        self.mp_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Show", variable=self.mp_show_var, command=self._show_mp_key).pack(side="left")
        ttk.Button(row, text="Save the key", command=self.save_mp_key).pack(side="left", padx=(6, 0))
        self.mp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="and write each material's entry", variable=self.mp_var).pack(side="left",
                                                                                                padx=(12, 0))
        self.mp_status = tk.StringVar()
        status = ttk.Label(row, textvariable=self.mp_status, foreground="#8c8c8c", cursor="hand2")
        status.pack(side="left", padx=(10, 0))
        status.bind("<Button-1>", lambda event: None if self.mp_key_var.get().strip() else webbrowser.open(
            "https://next-gen.materialsproject.org/api"))  # no key yet: where a free one is had
        self._mp_said()

    def _mp_said(self, saved: bool = False) -> None:
        """Whether a key is there — never the key itself."""
        if self.mp_key_var.get().strip():
            self.mp_status.set("✓ key saved" if saved else "✓ key set")
        else:
            self.mp_status.set("no key yet — get one (free) ↗")

    def _show_mp_key(self) -> None:
        self.mp_key_entry.configure(show="" if self.mp_show_var.get() else "•")

    def save_mp_key(self) -> None:
        """Saves the key typed (an empty field removes it) where the other keys are, and uses it at once."""
        from WebScraping.averageScrap import job as web_job
        key = self.mp_key_var.get().strip()
        try:
            web_job.save_env({"MP_API_KEY": key})  # ~/MoukhlijMatExtract/.env, made if missing
        except OSError as error:
            messagebox.showerror(NAME, f"The key could not be saved:\n{error}", parent=self.root)
            return
        self.mp_key_var.set(key)
        self._mp_said(saved=True)

    def _fit_split(self) -> None:
        """The divider below the settings and the card, but never so low that the tables keep less than half of the
        window (they are what a ranking is for), nor above the settings and their buttons (Rank)."""
        try:
            self._upper.update_idletasks()
            total = self._split.winfo_height()
            if total > 1:
                settings = (self._settings.winfo_reqheight() + self._actions.winfo_reqheight()
                            + self._files_row.winfo_reqheight() + self._mp_row.winfo_reqheight())
                wanted = max(settings, min(self._upper.winfo_reqheight(), int(total * 0.5)))
                if abs(self._split.sashpos(0) - wanted) > 1:  # moved only when its place changed
                    self._split.sashpos(0, wanted)
        except tk.TclError:  # the window is closing
            pass

    def _ranking_tab(self, component: str) -> dict:
        """The tab of one component's ranking: its own table, before the "Rule and data" tab."""
        frame = ttk.Frame(self.book, padding=(0, 6, 0, 0))
        caption = tk.StringVar()
        ttk.Label(frame, textvariable=caption, foreground="#8c8c8c").pack(anchor="w", pady=(0, 4))
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        table = ttk.Treeview(box, columns=[c for c, _, _, _ in _COLUMNS], show="headings", selectmode="browse")
        for column, heading, width, anchor in _COLUMNS:
            table.heading(column, text=heading)
            table.column(column, width=width, anchor=anchor, stretch=column == "checks")
        bar = ttk.Scrollbar(box, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=bar.set)
        table.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        table.bind("<Double-1>", self._opened)
        table.bind("<Return>", self._opened)
        from LocalExtraction.gui.design import stripes
        stripes(table)
        self.book.insert(self.about, frame, text=component_word(component).capitalize())
        self.tabs[component] = {"frame": frame, "table": table, "caption": caption, "shown": []}
        return self.tabs[component]

    # The component of the tab in front, and its ranking.
    @property
    def component(self) -> str:
        current = self.book.select()
        return next((c for c, tab in self.tabs.items() if str(tab["frame"]) == current),
                    next(iter(self.tabs)))

    @property
    def selection(self) -> Selection | None:
        return self.selections.get(self.component) or next((s for s in self.selections.values() if s.materials), None)

    @property
    def table(self) -> ttk.Treeview:
        return self.tabs[self.component]["table"]

    @property
    def _shown_materials(self) -> list[RankedMaterial]:
        return self.tabs[self.component]["shown"]

    def _add_source(self, folder: Path, ticked: bool) -> None:
        row = len(self.sources)
        ticked_var, status = tk.BooleanVar(value=ticked), tk.StringVar()
        ttk.Checkbutton(self._sources_frame, text=_shown(folder), variable=ticked_var).grid(row=row, column=0, sticky="w")
        ttk.Label(self._sources_frame, textvariable=status, foreground="#8c8c8c").grid(row=row, column=1, sticky="w", padx=8)
        if not (folder / loader.TABLE).is_file():
            status.set("no activation_energy.csv in it yet")
        elif folder in getattr(self, "_other_jobs", ()):
            status.set("another job's database: tick it to rank it")
        self.sources.append((folder, ticked_var, status))

    def _pick_source(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, title="A results folder (it holds activation_energy.csv)",
                                         initialdir=str(PROJECT_ROOT), mustexist=True)
        if chosen:
            self._add_source(Path(chosen), ticked=True)

    def _pick_out(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, title="Where to write the ranking",
                                         initialdir=self.out_var.get() or str(PROJECT_ROOT))
        if chosen:
            self.out_var.set(chosen)

    def _policy_changed(self) -> None:
        self.policy_meaning.set(POLICIES.get(self.policy_var.get(), ""))

    # ------------------------------------------------------------------
    # Reading the fields
    # ------------------------------------------------------------------
    def filters(self) -> Filters:
        """The filters the fields describe. Raises ValueError with what is wrong in them."""
        try:
            confidence = float(self.confidence_var.get().replace(",", ".") or 0)
        except ValueError:
            confidence = -1.0
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence: a number between 0 and 1")
        origin, attribution = self.origin_var.get(), self.attribution_var.get()
        kind = self.kind_var.get()
        return Filters(min_confidence=confidence, origin="" if origin == _ANY else origin,
                       attribution="" if attribution == _ANY else attribution,
                       component=self.component_var.get().strip(), elements=elements(self.elements_var.get()),
                       kind="" if kind == _ANY else kind, include_flagged=self.flagged_var.get(),
                       verified_only=self.verified_var.get())

    def criteria(self) -> Criteria:
        """The classes of the domain chosen (as mme-rank --domain), or of the criteria file the window was given.
        Raises CriteriaError."""
        return Criteria.load(self.criteria_path or DOMAIN_CRITERIA[self.domain_var.get()])

    def top(self) -> int | None:
        text = self.top_var.get().strip()
        if not text:
            return None
        if not text.isdigit() or int(text) < 1:
            raise ValueError("Show the first: a number of materials (1 or more), or empty for all")
        return int(text)

    # ------------------------------------------------------------------
    # The ranking
    # ------------------------------------------------------------------
    def rank(self, write: bool | None = None) -> None:
        """Ranks what the ticked folders hold; writes the files when asked (by default: as the box says)."""
        try:
            criteria = self.criteria()
        except CriteriaError as error:
            messagebox.showerror(NAME, str(error), parent=self.root)
            return
        if not self.policy_var.get():
            self.policy_var.set(criteria.policy)
            self._policy_changed()
        try:
            filters, top = self.filters(), self.top()
        except ValueError as error:
            messagebox.showerror(NAME, str(error), parent=self.root)
            return
        ticked = [(folder, status) for folder, var, status in self.sources if var.get()]
        self.card.hide()
        if not self.summary_label.winfo_manager():
            self.summary_label.pack(fill="x")
        if not ticked:
            self.summary.set("Tick at least one results folder above. (None yet? Run the extraction first: "
                             "python -m LocalExtraction or python -m WebScraping.)")
            return
        out_dir = Path(self.out_var.get()).expanduser()
        write = self.write_var.get() if write is None else write
        if write and (out_dir / loader.TABLE).exists():
            messagebox.showerror(NAME, f"{out_dir} is a database of MoukhlijMatExtract: the ranking is not written "
                                       "into a folder it reads. Choose another folder.", parent=self.root)
            return

        if self._ranking:
            return  # a ranking is under way: its result comes in a moment
        from LocalExtraction.gui.home_guard import ensure_home
        if not ensure_home(self.root, "The ranking"):  # the main folder deleted meanwhile: made again, or nothing done
            return
        self._ranking = True
        self.root.configure(cursor="watch")
        self.rank_button.configure(state="disabled")
        folders, policy, by_phase = [folder for folder, _ in ticked], self.policy_var.get(), self.by_phase_var.get()
        # The Materials Project entries too, when ticked: with the key typed (saved or not).
        mp_key = self.mp_key_var.get().strip() if self.mp_var.get() and write else ""
        if self.mp_var.get() and write and not mp_key:
            messagebox.showinfo(NAME, "Type your Materials Project key first (free at "
                                      "next-gen.materialsproject.org/api): the ranking is made without the entries.",
                                parent=self.root)
        done: list = []

        def work() -> None:
            """On another thread: reading the databases and writing the files take seconds for a large
            database, and the window must answer meanwhile. No Tk call here."""
            try:
                # Recorded as the command records it (its fingerprint and its run): see cli.record_ranking.
                settings = ranking_settings(folders, criteria, policy, by_phase, filters, top, FORMATS)
                run = ranking_run(out_dir, settings, filters)
                selections = select_from_each(folders, criteria, root=PROJECT_ROOT, policy=policy,
                                              by_phase=by_phase, filters=filters)
                written_by, problem, entries = {}, "", None
                if write and any(s.materials for s in selections.values()):
                    try:
                        written_by = write_rankings(selections, out_dir, FORMATS, top)
                        record_ranking(out_dir, ranking_stamp(folders, settings), run, selections, written_by)
                    except OSError as error:
                        problem = f"The files could not be written:\n{error}"
                    if mp_key and not problem:  # beside the ranking, not part of it
                        from . import materials_project
                        entries = materials_project.link(selections, out_dir, key=mp_key)
                done.append((selections, written_by, problem, entries))
            except Exception as error:  # said in the window, never lost on the thread
                logging.getLogger(__name__).exception("The ranking failed")
                done.append((None, {}, f"The ranking failed: {type(error).__name__}: {error}", None))

        def finish() -> None:
            if not done:
                self.root.after(50, finish)
                return
            self._ranking = False
            self.root.configure(cursor="")
            self.rank_button.configure(state="normal")
            selections, written_by, problem, entries = done[0]
            if problem:
                messagebox.showerror(NAME, problem, parent=self.root)
            self._mp_entries = entries
            if selections is not None:
                self._ranked(ticked, selections, written_by, top, out_dir)

        threading.Thread(target=work, name="ranking", daemon=True).start()
        self.root.after(50, finish)

    def wait_ranked(self, timeout: float = 60.0) -> bool:
        """Turns the window's loop until the ranking under way is shown (for the tests)."""
        end = time.monotonic() + timeout
        while self._ranking and time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)
        return not self._ranking

    def _ranked(self, ticked, selections: dict[str, Selection], written_by: dict[str, list[Path]],
                top: int | None, out_dir: Path) -> None:
        """Shows a ranking made on the ranking thread."""
        first = next(iter(selections.values()))
        for (_, status), report in zip(ticked, first.databases):
            status.set(loader.describe(report))
        for component in selections:
            if component not in self.tabs:  # surface, or a component the paper does not state
                self._ranking_tab(component)
        self.selections, self.written_by, self._top = selections, written_by, top
        self.written = [p for paths in written_by.values() for p in paths]
        self._out_dir = out_dir
        self._fill_tables()
        self._fill_about()
        # The tab in front: the one it was on if it has a ranking, else the first that has one.
        if not self.selections.get(self.component, first).materials:
            best = next((c for c, s in selections.items() if s.materials), None)
            if best:
                self.book.select(self.tabs[best]["frame"])
        self._buttons()
        self.show_outcome()

    def show_outcome(self) -> None:
        """The card of the ranking: each component's ranking in a tile — how many materials, how many
        superionic — and the best materials of each, with their articles."""
        if not self.selections:
            return
        stats, highlights = [], []
        for component, selection in self.selections.items():
            word = component_word(component)
            superionic = next((selection.count(c) for c in selection.criteria.classes if c.accepted), 0)
            best = selection.materials[0] if selection.materials else None
            first_class = selection.criteria.classes[0].name
            stats.append(Stat(number(len(selection.materials)), f"{word} materials",
                              class_colours(1)[0] if selection.materials else REJECTED,
                              f"{superionic} {first_class} · best {best.material} {format_energy(best.energy_eV)} eV"
                              if best else "no value of this component"))
            for m in selection.top[:2]:
                highlights.append(f"{word.capitalize()} #{m.rank}: {m.material} — {format_energy(m.energy_eV)} eV "
                                  f"({m.energy_class.name}), from {len(m.papers)} paper{'s' if len(m.papers) != 1 else ''}: "
                                  f"{m.evidence.paper_title}")
            first = selection.materials[:selection.top_n]
            if selection.bootstrap and first:
                stable = sum(1 for m in first if m.p_top >= 0.9)
                single = sum(1 for m in first if m.evidence_tier == "C")
                highlights.insert(0, f"{word.capitalize()}: {stable} of the first {len(first)} stay in the top "
                                     f"{selection.top_n} in 90 % of the resamplings or more; {single} rest on a single "
                                     "value")
        actions = [(f"Show {component_word(c)}", lambda c=c: self.book.select(self.tabs[c]["frame"]))
                   for c, s in self.selections.items() if s.materials]
        if self.written:
            actions += [("Open the report", lambda: self._open(".html")), ("Browse the files", self._browse),
                        ("Open the folder", self._open_folder)]
        if getattr(self, "_mp_entries", None):
            actions.append(("Open the Materials Project entries", lambda: open_path(self._mp_entries)))
        ranked = any(s.materials for s in self.selections.values())
        self.summary_label.pack_forget()  # its text is the card's detail
        self.card.show(Outcome("Ranking done — one ranking per transport component" if ranked else "Nothing to rank",
                               "done" if ranked else NOTHING, self.summary.get(), stats if ranked else [],
                               highlights[:6], actions))

    def _buttons(self) -> None:
        """The file buttons: on when the ranking of the tab in front was written."""
        mine = self.written_by.get(self.component, [])
        for button, suffix in ((self.open_report_button, ".html"), (self.open_workbook_button, ".xlsx")):
            button.configure(state="normal" if any(p.suffix == suffix for p in mine) else "disabled")
        # The results folder can be opened and browsed whenever it exists (an earlier ranking's too).

    def _fill_tables(self) -> None:
        for component in self.tabs:
            self._fill_table(component)
        parts = []
        for component, selection in self.selections.items():
            counts = " · ".join(f"{c.name} {selection.count(c)}" for c in selection.criteria.classes)
            parts.append(f"{component_word(component).capitalize()}: {len(selection.materials)} materials — {counts}"
                         if selection.materials else f"{component_word(component).capitalize()}: none")
        first = next(iter(self.selections.values()), None)
        if first is None:
            return
        if any(s.materials for s in self.selections.values()):
            text = ("; ".join(parts) + f". From {sum(s.values_used for s in self.selections.values())} of the "
                    f"{first.values_read} values read, Ea of a material: {first.policy}.")
        elif first.values_read:
            text = f"None of the {first.values_read} values read passes the filters."
        else:
            text = "No activation energy to rank in the folders ticked above."
        if self.written:
            text += f"  Written to {_shown(self._out_dir)}: one folder per component, and summary.csv."
        for note in first.notes:
            text += f"  Note: {note}"
        self.summary.set(text)
        self._buttons()

    def _fill_table(self, component: str) -> None:
        tab = self.tabs[component]
        table = tab["table"]
        table.delete(*table.get_children())
        selection = self.selections.get(component)
        word = component_word(component)
        if selection is None:
            tab["shown"] = []
            tab["caption"].set("")
            return
        accepted = [c for c in selection.criteria.classes if c.accepted]
        for energy_class, colour in zip(accepted, class_colours(len(accepted))):
            table.tag_configure(energy_class.name, foreground=colour)
        table.tag_configure(selection.criteria.rejected.name, foreground=REJECTED)

        shown = list(selection.top[:self._top]) + (list(selection.rejected) if self.rejected_var.get() else [])
        tab["shown"] = shown
        for index, m in enumerate(shown):
            spread = (f"{format_energy(m.energy_min_eV)} – {format_energy(m.energy_max_eV)}"
                      if len(m.values) > 1 else format_energy(m.energy_min_eV))
            table.insert("", "end", iid=str(index), tags=(m.energy_class.name, *(("stripe",) if index % 2 else ())), values=(
                m.rank, m.material, m.energy_class.name, format_energy(m.energy_eV), spread, len(m.values),
                len(m.papers), rank_interval(m) or "–", m.evidence_tier + (f" ✓{m.verified}" if m.verified else ""),
                origin_summary(m), " | ".join(m.checks) or "ok"))
        self.book.tab(tab["frame"], text=f"{word.capitalize()} ({len(selection.materials)})")
        tab["caption"].set(
            f"The materials ranked by their {word} activation energy only — {selection.values_used} values, "
            f"{selection.papers_used} papers. Double-click a material for its values." if selection.materials else
            f"No {word} activation energy in the folders ticked above"
            + ("" if selection.filters.describe() == f"{word} transport" else " with these filters") + ".")


    def _fill_about(self) -> None:
        selection = self.selection
        if selection is None:
            return
        criteria = selection.criteria
        lines = [f"The rule ({criteria.source})", ""]
        lines += [f"    {c.name:<12} {c.rule}" for c in criteria.classes]
        lines += ["", f"Ea of a material: {selection.policy} — {POLICIES[selection.policy]}",
                  f"Values: {selection.filters.describe()}",
                  f"Checks: within {criteria.borderline_margin:g} eV of a limit is borderline; "
                  f"a confidence under {criteria.low_confidence:g} is low", "", "The data", ""]
        lines += [f"    {report.path:<36} {loader.describe(report)}" for report in selection.databases]
        lines += ["", *selection.notes]
        self.about.configure(state="normal")
        self.about.delete("1.0", "end")
        self.about.insert("1.0", "\n".join(lines))
        self.about.configure(state="disabled")

    # ------------------------------------------------------------------
    # One material, and the files
    # ------------------------------------------------------------------
    def _opened(self, event: "tk.Event") -> None:
        chosen = self.table.focus()
        if chosen:
            self.details(self._shown_materials[int(chosen)])

    def details(self, m: RankedMaterial) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title(f"{m.material}: {format_energy(m.energy_eV)} eV ({m.energy_class.name})")
        from LocalExtraction.gui import layout
        layout.place(window, (820, 560), (520, 320), parent=self.root)
        window.transient(self.root)
        window.bind("<Escape>", lambda event: window.destroy())
        text = tk.Text(window, wrap="word", relief="flat", padx=10, pady=8)
        bar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.tag_configure("head", font=("TkDefaultFont", 11, "bold"))
        text.tag_configure("dim", foreground="#8c8c8c")
        votes = ", ".join(f"{name} {count}" for name, count in m.votes)
        text.insert("end", f"#{m.rank}  {m.material} — {m.energy_class.name}\n", "head")
        text.insert("end", f"Ea {format_energy(m.energy_eV)} eV ({self.selection.policy if self.selection else ''}) · "
                           f"its values: {votes} · checks: {' | '.join(m.checks) or 'ok'}\n")
        if m.rank_high:
            text.insert("end", f"Rank {m.rank}, 95 % interval {rank_interval(m)} · in the top 10 in "
                               f"{round(100 * m.p_top)} % of the resamplings · evidence {m.evidence_tier} · "
                               f"{m.verified} of {len(m.values)} values checked by hand\n", "dim")
        text.insert("end", "\n")
        for v in m.values:
            text.insert("end", f"{format_energy(v.energy_eV)} eV — {v.reported_as}\n", "head")
            text.insert("end", f"{v.data_origin} · {v.transport_component} · {v.attribution} · {v.temperature} · "
                               f"confidence {v.confidence:g}\n", "dim")
            text.insert("end", f"{v.paper_title or v.paper_id} ({v.year}) {v.doi} — page {v.page}, {v.extracted_from}, "
                               f"from {v.database}\n", "dim")
            if v.verification or v.arrhenius_text:
                text.insert("end", " · ".join(filter(None, (f"checked by hand: {v.verification}" if v.verification else "",
                                                           f"Arrhenius: {v.arrhenius_text}" if v.arrhenius_text else "")))
                            + "\n", "dim")
            if v.sentence:
                text.insert("end", f"“{v.sentence}”\n")
            text.insert("end", "\n")
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        from LocalExtraction.gui.design import website_line
        website_line(window)
        return window

    def _open(self, suffix: str) -> None:
        """A file of the ranking of the tab in front (else of the first component that has one)."""
        mine = self.written_by.get(self.component, []) + self.written
        path = next((p for p in mine if p.suffix == suffix), None)
        if path is not None and path.exists():
            open_path(path)
        else:
            messagebox.showinfo(NAME, "That file was not written: rank with “write the files” ticked.", parent=self.root)

    def _outputs_deleted(self, deleted: bool) -> None:
        if deleted:
            self.written = [p for p in self.written if p.exists()]
            self.written_by = {c: [p for p in paths if p.exists()] for c, paths in self.written_by.items()}
            self._buttons()
            self.summary.set("The ranking files were deleted. Press Rank to write them again.")

    def _browse(self) -> None:
        """The files of the ranking, table by table."""
        from LocalExtraction.gui.browser import ResultsBrowser, part_tables
        title, _, tables = part_tables("rank")
        folder = getattr(self, "_out_dir", DEFAULT_RESULTS)
        tables = [(label, folder / path.relative_to(part_tables("rank")[1])) for label, path in tables]
        ResultsBrowser(self.root, title, folder, tables)

    def _open_folder(self) -> None:
        if self.written:
            open_path(getattr(self, "_out_dir", self.written[0].parent))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"{command_name('mme-rank', NAME)} gui", description="The window of the selection.")
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Results folder(s) to offer, the most trusted first (default: "
                             + ", ".join(loader.KNOWN_DATABASES) + ")")
    parser.add_argument("--out", "-o", default=str(DEFAULT_RESULTS), metavar="DIR",
                        help="Folder to write the ranking into (default: SelectingTopMaterial/results)")
    parser.add_argument("--criteria", metavar="FILE", help="Criteria file to use instead of criteria.toml")
    args = parser.parse_args(argv)
    enter_project_home("rank")  # after the options are read: --help makes no folder
    root = tk.Tk()
    from LocalExtraction.crashlog import watch
    watch(root)  # a window's own errors: written to a crash file, and said
    App(root, sources=[source_folder(name) for name in args.source] if args.source else None,
        out_dir=Path(args.out).expanduser(), criteria_path=args.criteria)
    from LocalExtraction.crashlog import run
    run(root)  # the loop, then the window closed cleanly
    return 0
