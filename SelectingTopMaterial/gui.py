# SelectingTopMaterial/gui.py
"""The window of the selection: the options of the command line as fields, the ranked materials in
a table, and the files it writes one click away.

    python -m SelectingTopMaterial gui

It reads the results folders and writes into its own results/ (which "Delete outputs…" empties)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tkinter as tk
from collections.abc import Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from LocalExtraction.gui.delete_outputs import delete_outputs_button
from LocalExtraction.gui.result_card import NOTHING, Outcome, ResultCard, Stat, number

from . import loader
from LocalExtraction.about import command_name

from .about import DEFAULT_RESULTS, NAME, PROJECT_ROOT, VERSION
from .cli import FORMATS, source_folder, write_rankings
from .console import origin_summary
from .criteria import POLICIES, Criteria, CriteriaError, format_energy
from .models import COMPONENTS, Filters, RankedMaterial, Selection, component_word
from .palette import REJECTED, class_colours
from .selection import select_from_each

_ANY = "any"
# (column, heading, width, anchor)
_COLUMNS = (("rank", "#", 44, "e"), ("material", "material", 230, "w"), ("class", "class", 104, "w"),
            ("ea", "Ea (eV)", 70, "e"), ("range", "range (eV)", 110, "w"), ("values", "values", 58, "e"),
            ("papers", "papers", 58, "e"), ("origin", "origin", 130, "w"), ("checks", "checks", 340, "w"))


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
        root.title(f"MoukhlijMatExtract (MME) · {NAME} · Ranking the materials")
        root.geometry("1260x820")
        root.minsize(1000, 640)
        self.criteria_path = criteria_path
        self.selections: dict[str, Selection] = {}   # one ranking per transport component
        self.written: list[Path] = []
        self.written_by: dict[str, list[Path]] = {}
        self.tabs: dict[str, dict] = {}                # component → its tab: frame, table, materials shown
        self._top: int | None = None
        known = [PROJECT_ROOT / name for name in loader.KNOWN_DATABASES]
        self._build(list(sources) if sources else known, out_dir, ticked_missing=bool(sources))
        self.rank(write=False)  # what the folders hold, at once; the files are written on “Rank”

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build(self, folders: list[Path], out_dir: Path, ticked_missing: bool) -> None:
        top = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Selecting the top materials", font=("TkDefaultFont", 16, "bold")).pack(side="left")
        ttk.Label(top, text="the materials of the databases, ranked by activation energy",
                  foreground="#8c8c8c").pack(side="left", padx=12)
        ttk.Label(top, text=f"{NAME} {VERSION}", foreground="gray").pack(side="right")

        settings = ttk.Frame(self.root, padding=(12, 4, 12, 4))
        settings.pack(fill="x")
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=1)

        # Where the values come from
        sources = ttk.LabelFrame(settings, text=" Results folders — the most trusted first ", padding=8)
        sources.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._sources_frame = sources
        self.sources: list[tuple[Path, tk.BooleanVar, tk.StringVar]] = []
        for folder in folders:
            self._add_source(folder, ticked=ticked_missing or (folder / loader.TABLE).is_file())
        ttk.Button(sources, text="Add a folder…", command=self._pick_source).grid(
            row=999, column=0, sticky="w", pady=(6, 0))

        # Which values take part, and how one stands for a material
        options = ttk.LabelFrame(settings, text=" Which values, and which one stands for a material ", padding=8)
        options.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.policy_var = tk.StringVar()
        self.origin_var = tk.StringVar(value=_ANY)
        self.attribution_var = tk.StringVar(value=_ANY)
        self.component_var = tk.StringVar()
        self.elements_var = tk.StringVar()
        self.confidence_var = tk.StringVar(value="0")
        self.by_phase_var = tk.BooleanVar(value=False)
        self.top_var = tk.StringVar()
        self.rejected_var = tk.BooleanVar(value=True)

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

        # Where the ranking is written, and the buttons
        actions = ttk.Frame(self.root, padding=(12, 6, 12, 4))
        actions.pack(fill="x")
        self.rank_button = ttk.Button(actions, text="Rank", command=self.rank)
        self.rank_button.pack(side="left")
        self.write_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="and write the files into", variable=self.write_var).pack(side="left", padx=(10, 4))
        self.out_var = tk.StringVar(value=str(out_dir))
        ttk.Entry(actions, textvariable=self.out_var, width=30).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Browse…", command=self._pick_out).pack(side="left", padx=4)
        delete_outputs_button(actions, "rank", after=self._outputs_deleted).pack(side="right", padx=(4, 0))
        self.open_folder_button = ttk.Button(actions, text="Open the folder", command=self._open_folder)
        self.open_folder_button.pack(side="right")
        self.open_workbook_button = ttk.Button(actions, text="Open the workbook", command=lambda: self._open(".xlsx"))
        self.open_workbook_button.pack(side="right", padx=4)
        self.open_report_button = ttk.Button(actions, text="Open the report", command=lambda: self._open(".html"))
        self.open_report_button.pack(side="right")

        self.summary = tk.StringVar(value="")
        self.summary_label = ttk.Label(self.root, textvariable=self.summary, wraplength=1200, justify="left",
                                       padding=(12, 4))
        self.summary_label.pack(fill="x")

        self.book = ttk.Notebook(self.root)
        self.card = ResultCard(self.root, before=self.book, padx=8)  # what the last ranking found
        self.book.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.about = tk.Text(self.book, wrap="word", relief="flat", padx=10, pady=8, state="disabled")
        self.book.add(self.about, text="Rule and data")
        for component in COMPONENTS:  # bulk, grain boundary, total: each ranked on its own
            self._ranking_tab(component)
        self.book.select(0)
        self.book.bind("<<NotebookTabChanged>>", lambda event: self._buttons())

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
        return Filters(min_confidence=confidence, origin="" if origin == _ANY else origin,
                       attribution="" if attribution == _ANY else attribution,
                       component=self.component_var.get().strip(), elements=elements(self.elements_var.get()))

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
            criteria = Criteria.load(self.criteria_path)
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
            self.summary_label.pack(fill="x", before=self.book)
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

        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            selections = select_from_each([folder for folder, _ in ticked], criteria, root=PROJECT_ROOT,
                                          policy=self.policy_var.get(), by_phase=self.by_phase_var.get(),
                                          filters=filters)
            written_by: dict[str, list[Path]] = {}
            if write and any(s.materials for s in selections.values()):
                try:
                    written_by = write_rankings(selections, out_dir, FORMATS, top)
                except OSError as error:
                    messagebox.showerror(NAME, f"The files could not be written:\n{error}", parent=self.root)
        finally:
            self.root.configure(cursor="")
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
        actions = [(f"Show {component_word(c)}", lambda c=c: self.book.select(self.tabs[c]["frame"]))
                   for c, s in self.selections.items() if s.materials]
        if self.written:
            actions += [("Open the report", lambda: self._open(".html")), ("Browse the files", self._browse),
                        ("Open the folder", self._open_folder)]
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
        self.open_folder_button.configure(state="normal" if self.written else "disabled")

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
            table.insert("", "end", iid=str(index), tags=(m.energy_class.name,), values=(
                m.rank, m.material, m.energy_class.name, format_energy(m.energy_eV), spread, len(m.values),
                len(m.papers), origin_summary(m), " | ".join(m.checks) or "ok"))
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
        window.geometry("820x560")
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
                           f"its values: {votes} · checks: {' | '.join(m.checks) or 'ok'}\n\n")
        for v in m.values:
            text.insert("end", f"{format_energy(v.energy_eV)} eV — {v.reported_as}\n", "head")
            text.insert("end", f"{v.data_origin} · {v.transport_component} · {v.attribution} · {v.temperature} · "
                               f"confidence {v.confidence:g}\n", "dim")
            text.insert("end", f"{v.paper_title or v.paper_id} ({v.year}) {v.doi} — page {v.page}, {v.extracted_from}, "
                               f"from {v.database}\n", "dim")
            if v.sentence:
                text.insert("end", f"“{v.sentence}”\n")
            text.insert("end", "\n")
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
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
    root = tk.Tk()
    App(root, sources=[source_folder(name) for name in args.source] if args.source else None,
        out_dir=Path(args.out).expanduser(), criteria_path=args.criteria)
    root.mainloop()
    return 0
