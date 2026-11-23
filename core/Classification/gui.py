# Classification/gui.py
"""The window of the classification: the materials of the databases, classified by crystal-structure
type and by structure family, with the activation energies of each class told apart by the transport
component they describe — each class with its sub-classes: NASICON → bulk, grain boundary, total.

    python -m Classification gui

It classifies what the databases hold when it opens (and writes the class folders, as the command
does, unless told not to). Each tab lists the classes of one axis, each with its sub-classes under
it; selecting a class or a sub-class lists its materials below, and a double click on a material shows every activation energy of it. The filters choose which
activation energies count: measured or computed ones, the papers' own results only, only those whose
component the paper itself states."""

from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from LocalExtraction import outputs
from LocalExtraction.gui.delete_outputs import delete_outputs_button
from LocalExtraction.gui.result_card import FAILED, NOTHING, Outcome, ResultCard, Stat, number
from LocalExtraction.exporter import article_title
from LocalExtraction.gui.widgets import FolderRow, Table, WrapLabel, _sort_key, open_path

from LocalExtraction.about import command_name, enter_project_home

from .about import CRYSTAL_STRUCTURE, DEFAULT_OUT, DEFAULT_SOURCES, NAME, PROJECT_ROOT
from .classify import COMPONENT_WORDS, COMPONENTS, NO_FAMILY

# The one button: the classes, then every family ▸ property ▸ type ▸ origin (branches.py).
CLASSIFY_ALL = "▶  Classify everything"
from .database import (AXES, Classified, Source, class_groups, class_kind, classify, component_stats,
                       conductivities_of, energies_of, material_rows, partly_rebuilt, read, write)

TITLE = f"MoukhlijMatExtract (MME) · {NAME}"
ORIGINS = {"measured and computed": "", "measured only": "experiment", "computed only": "simul"}
# How the classes are listed: each class with its sub-classes under it (NASICON → bulk, grain
# boundary, total), or bulk, grain boundary and total side by side on one line per class.
TREE = "each class with its sub-classes: NASICON → bulk, grain boundary, total"
SIDE_BY_SIDE = "bulk, grain boundary and total side by side on one line per class"
VIEWS = (TREE, SIDE_BY_SIDE)
_SEP = "\x1f"  # between a class and its component in the id of a sub-class line
NO_VALUE = "—"  # a cell of the window with no value of that kind: no such activation energy is reported
_AXIS_WORD = {CRYSTAL_STRUCTURE: "Crystal structure"}


@dataclass
class Result:
    """A classification of the chosen databases, and what came of writing it."""
    sources: list[Source] = field(default_factory=list)
    classified: Classified | None = None
    energies: pd.DataFrame = field(default_factory=pd.DataFrame)
    conductivities: dict[str, list[float]] = field(default_factory=dict)
    written: Path | None = None
    error: str = ""


def run(folders: Sequence[Path], out_dir: Path | None, progress=None) -> Result:
    """Reads the databases, classifies their materials and — given a folder — writes the classes. `progress`
    (optional) gets (how far, 0 to 1; what it does now; the phase — read, classify, write, by_property —; how many of
    how many in it), at each step and for each family of the classification by property, the longest step."""
    def say(fraction: float, text: str, phase: str = "", done: int = 0, total: int = 0) -> None:
        if progress is not None:
            try:
                progress(min(max(fraction, 0.0), 1.0), text, phase, done, total)
            except Exception:  # what shows the progress never stops the classification
                pass
    steps = 4 if out_dir is not None else 2
    sources = []
    for index, folder in enumerate(folders):
        say(0.10 * index / max(len(folders), 1), f"Step 1 of {steps} · reading the databases — {index + 1} of "
                                                  f"{len(folders)}: {Path(folder).name}", "read", index, len(folders))
        source = read(Path(folder))
        if source is not None:
            sources.append(source)
    if not sources:
        return Result(error="No database to classify in the folders chosen (none holds a materials.csv). "
                            "Run the extraction first: python -m LocalExtraction, or python -m WebScraping.")
    if out_dir is not None and any(s.path.resolve() == out_dir.resolve() for s in sources):
        return Result(error=f"{out_dir} is a database it reads: choose another folder to write the classes into.")
    from .cli import classify_run, record_classes  # recorded as the command records it
    record = classify_run(sources, out_dir) if out_dir is not None else None
    say(0.10, f"Step 2 of {steps} · classifying the materials by crystal family and chemical family …", "classify")
    classified = classify(sources)
    result = Result(sources, classified, energies_of(classified), conductivities_of(classified))
    if out_dir is not None:
        say(0.35, f"Step 3 of {steps} · writing one database per class …", "write")
        write(classified, out_dir)
        from .branches import write_all  # every family ▸ property ▸ type ▸ origin, one table each
        write_all(out_dir, progress=lambda done, total, name: say(
            0.50 + 0.50 * done / max(total, 1),
            f"Step 4 of {steps} · classification by property — family {min(done + 1, total)} of {total}: {name}",
            "by_property", done, total))
        record_classes(out_dir, sources, record, classified)
        result.written = out_dir
    return result


def kept(energies: pd.DataFrame, origin: str = "", this_work: bool = False, stated: bool = False) -> pd.DataFrame:
    """The activation energies a filter keeps: measured (origin "experiment") or computed ("simul")
    ones, the papers' own results only, only those whose transport component the paper states."""
    if energies.empty:
        return energies
    keep = pd.Series(True, index=energies.index)
    if origin:
        column = energies["data_origin"] if "data_origin" in energies else pd.Series("", index=energies.index)
        keep &= column.astype(str).str.lower().str.startswith(origin)
    if this_work:
        column = energies["attribution"] if "attribution" in energies else pd.Series("", index=energies.index)
        keep &= column.astype(str).str.lower() == "this work"
    if stated:
        keep &= energies["component_basis"] == "stated"
    return energies[keep]


def _cell(value: object) -> str:
    """A number as the window shows it; NO_VALUE for an answer that says no value was reported."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}"
    text = str(value)
    return NO_VALUE if text.startswith("no ") else text


class ClassTree(ttk.Frame):
    """The classes as a tree: each class on a line, and under it its sub-classes — bulk, grain
    boundary, total. Click a heading to sort the classes by it (numbers as numbers, again to
    reverse); the sub-classes of a class keep their order under it."""

    def __init__(self, parent: tk.Misc, heading: str, columns: Sequence[tuple[str, str, int]], height: int = 10):
        super().__init__(parent)
        self.columns = [name for name, _, _ in columns]
        self._headings = {"#0": heading, **{name: text for name, text, _ in columns}}
        self.tree = ttk.Treeview(self, columns=self.columns, show="tree headings", selectmode="extended", height=height)
        self.tree.heading("#0", text=heading, anchor="w", command=lambda: self.sort_by("#0"))
        self.tree.column("#0", width=230, minwidth=120, anchor="w", stretch=True)
        for name, text, width in columns:
            self.tree.heading(name, text=text, anchor="w", command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, minwidth=36, anchor="w", stretch=False)
        self.tree.tag_configure("composition", foreground="#8c8c8c")
        self.tree.tag_configure("sub", foreground="#1f4e79")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._branches: list[tuple] = []
        self._sorted: tuple[str, bool] | None = None
        self._closed: set[str] = set()  # the classes closed by hand stay closed when the tree is filled again

    def fill(self, branches: Sequence[tuple]) -> None:
        """(id, label, values, tags, [(sub id, sub label, sub values), ...]) for each class."""
        self._branches = list(branches)
        self._show()

    def _show(self) -> None:
        branches = self._branches
        if self._sorted is not None:
            column, reverse = self._sorted
            index = None if column == "#0" else self.columns.index(column)
            branches = sorted(branches, key=lambda b: _sort_key(str(b[1] if index is None else b[2][index])), reverse=reverse)
        for item in self.tree.get_children():
            if not self.tree.item(item, "open"):
                self._closed.add(item)
            else:
                self._closed.discard(item)
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for identifier, label, values, tags, children in branches:
            self.tree.insert("", "end", iid=identifier, text=label, values=list(values), tags=list(tags),
                             open=identifier not in self._closed)
            for sub_id, sub_label, sub_values in children:
                self.tree.insert(identifier, "end", iid=sub_id, text=sub_label, values=list(sub_values), tags=["sub"])
        kept = [item for item in selected if self.tree.exists(item)]
        if kept:
            self.tree.selection_set(kept)

    def sort_by(self, column: str) -> None:
        reverse = self._sorted is not None and self._sorted[0] == column and not self._sorted[1]
        self._sorted = (column, reverse)
        for name, text in self._headings.items():
            self.tree.heading(name, text=text + ((" ▼" if reverse else " ▲") if name == column else ""))
        self._show()

    def expand(self, opened: bool) -> None:
        for item in self.tree.get_children():
            self.tree.item(item, open=opened)

    def selected(self) -> list[str]:
        return list(self.tree.selection())

    def __len__(self) -> int:
        return len(self._branches)


_PER_LINE = 4  # database boxes on one line of the window


class App:
    def __init__(self, root: tk.Tk, sources: Sequence[Path] | None = None, out_dir: Path = DEFAULT_OUT,
                 write_files: bool = True, start: bool = True):
        self.root = root
        from LocalExtraction.gui import theme
        theme.apply(root)  # buttons that light up under the mouse and show the step that runs
        root.title(TITLE)
        from LocalExtraction.gui import layout
        layout.place(root, (1320, 860), (980, 640))  # fitted to the screen it opens on, centred
        self.result = Result()
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._started: float | None = None  # when the classification running began
        self._rows: dict[str, dict[str, object]] = {}
        # The databases of the other web jobs (WebScraping/web_output_<job>) are offered, not ticked: each is a corpus
        # of its own, classified with the others only when asked.
        from SelectingTopMaterial.loader import job_databases
        self._other_jobs = [] if sources else job_databases(PROJECT_ROOT)
        self._build(list(sources) if sources else [*DEFAULT_SOURCES, *self._other_jobs], out_dir, write_files,
                    chosen=bool(sources))
        if start and any(var.get() for var in self.sources.values()):
            self.classify()
        elif start:  # a fresh project: nothing extracted yet, so nothing to tick
            self.status.configure(text="No database yet: run 1 · Local extraction or 2 · Web scraping first, "
                                       "then press Classify.")

    # ------------------------------------------------------------------
    # The window
    # ------------------------------------------------------------------
    def _build(self, folders: list[Path], out_dir: Path, write_files: bool, chosen: bool) -> None:
        from LocalExtraction.gui import design
        from LocalExtraction.gui.about_window import open_about
        design.header(self.root, "Classification", "the materials by crystal-structure type and structure family",
                      compact=True)
        # “‹ Back” while the classes are being written (seconds, all files in one go): it goes back once they are.
        self.root._mme_busy, self.root._mme_finish_first = (lambda: self._busy), True
        design.footer(self.root, about=lambda: open_about(self.root)).pack(side="bottom", fill="x")
        # The settings above (they scroll when short), the classes below, a line to drag between them.
        from LocalExtraction.gui.layout import Stack
        self.stack = Stack(self.root, keep=0.5)
        host = self.stack.host
        top = ttk.Frame(host, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        line = ttk.Frame(top)
        line.pack(fill="x")
        ttk.Label(line, text="Databases:").pack(side="left")
        self.sources_frame = ttk.Frame(line)
        self.sources_frame.pack(side="left")
        self.sources: dict[Path, tk.BooleanVar] = {}
        for folder in folders:  # the databases named on the command line; else those of the two extractions that exist
            self._add_source(Path(folder), ticked=chosen or ((Path(folder) / "materials.csv").is_file()
                                                            and Path(folder) not in self._other_jobs))
        # The buttons on a line of their own: a database per job file wraps onto more lines above them.
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="Add a database…", command=self._pick_source).pack(side="left")
        self.classify_button = ttk.Button(buttons, text=CLASSIFY_ALL, command=self.classify, style="Next.TButton")
        self.classify_button.pack(side="right")
        from LocalExtraction.gui.csv_browser import results_buttons
        results_buttons(buttons, "4 · Classification", lambda: str(_folder(self.out.get())))
        self.delete_button = delete_outputs_button(buttons, "classify", after=self._outputs_deleted)
        self.delete_button.pack(side="right")
        # The views of the classes on a line of their own (the line above is full at the window's smallest):
        # how “Classify everything” works, drawn (family ▸ property ▸ type ▸ origin ▸ one table per branch), and the
        # statistics of the classes.
        views = ttk.Frame(top)
        views.pack(fill="x", pady=(4, 0))
        ttk.Button(views, text="Classification flow…", command=self.show_flow).pack(side="left")
        from LocalExtraction.gui.statistics import statistics_button
        statistics_button(views, "4 · Classification", self._statistics, side="left")
        outputs.register("classify", self.busy, "a classification is running")

        line = ttk.Frame(top)
        line.pack(fill="x", pady=(6, 0))
        self.out = FolderRow(line, "Classes written into:", _shown(out_dir), label_width=20)
        self.out.pack(side="left", fill="x", expand=True)
        self.write_files = tk.BooleanVar(value=write_files)
        ttk.Checkbutton(line, text="write the class folders when classifying (as the command does)",
                        variable=self.write_files).pack(side="left", padx=8)

        filters = ttk.LabelFrame(host, text="Which activation energies count", padding=(10, 4))
        filters.pack(fill="x", padx=10, pady=(8, 0))
        self.origin = tk.StringVar(value="measured and computed")
        ttk.Combobox(filters, textvariable=self.origin, values=list(ORIGINS), state="readonly", width=22).pack(side="left")
        self.this_work = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text="the papers' own results only (not the values they cite)",
                        variable=self.this_work, command=self.refresh).pack(side="left", padx=10)
        self.stated = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text="only where the paper states bulk / grain boundary / total",
                        variable=self.stated, command=self.refresh).pack(side="left", padx=10)
        ttk.Label(filters, text="Find a material:").pack(side="left", padx=(16, 4))
        self.find = tk.StringVar(value="")
        entry = ttk.Entry(filters, textvariable=self.find, width=16)
        entry.pack(side="left")
        self.origin.trace_add("write", lambda *_: self.refresh())
        self.find.trace_add("write", lambda *_: self._fill_materials_all())

        line = ttk.Frame(host, padding=(10, 6, 10, 0))
        line.pack(fill="x")
        ttk.Label(line, text="Classes:").pack(side="left")
        self.view = tk.StringVar(value=TREE)
        ttk.Combobox(line, textvariable=self.view, values=list(VIEWS), state="readonly", width=64).pack(side="left", padx=6)
        self.view.trace_add("write", lambda *_: self._show_view())
        ttk.Button(line, text="Open every class", command=lambda: self._expand(True)).pack(side="left", padx=(12, 4))
        ttk.Button(line, text="Close every class", command=lambda: self._expand(False)).pack(side="left")

        status_row = ttk.Frame(host)
        status_row.pack(fill="x", padx=12, pady=(6, 2))
        # How far a classification is: shown while it runs, beside what it is doing.
        self.progress = ttk.Progressbar(status_row, mode="determinate", maximum=1000, length=180)
        self.status = WrapLabel(status_row, text="", foreground="#8c8c8c", wraplength=1200)
        from LocalExtraction.gui.progress import Tracker, details_button
        self.tracker: Tracker | None = None  # the classification followed in “⏱ Progress details”
        details_button(status_row, lambda: self.tracker, "Classification").pack(side="right", padx=(10, 0))
        self.status.pack(side="left", fill="x", expand=True)
        self._steps: queue.Queue = queue.Queue()

        self.book = ttk.Notebook(self.root)
        self.card = ResultCard(host, padx=10)  # what the last classification found
        self.stack.below(self.book, cards=[self.card])
        self.classes: dict[str, Table] = {}
        self.trees: dict[str, ClassTree] = {}
        self.materials: dict[str, Table] = {}
        self.captions: dict[str, ttk.Label] = {}
        self.headlines: dict[str, ttk.Label] = {}
        for axis, _, column in AXES:
            word = _AXIS_WORD.get(axis, "Structure family")
            pane = ttk.Panedwindow(self.book, orient="vertical")
            self.book.add(pane, text=f"  {word}s  " if axis == CRYSTAL_STRUCTURE else "  Structure families  ")
            upper = ttk.Frame(pane, padding=(0, 6, 0, 0))
            headline = ttk.Label(upper, text="", foreground="#8c8c8c")
            headline.pack(anchor="w")
            self.headlines[axis] = headline
            columns = [("class", word, 180), ("kind", "kind", 120), ("n_materials", "materials", 66),
                       ("n_papers", "papers", 54), ("n_Ea", "Ea values", 64)]
            for component in COMPONENTS:  # the grain-boundary headings are the longest
                name, wide = COMPONENT_WORDS[component], component == "grain_boundary"
                columns += [(f"{component}_n", f"{name} n", 92 if wide else 56),
                            (f"{component}_min", f"{name} min", 110 if wide else 76),
                            (f"{component}_median", f"{name} median", 124 if wide else 90)]
            table = Table(upper, columns, stretch="class", height=11)
            table.tag("composition", foreground="#8c8c8c")
            table.tree.bind("<<TreeviewSelect>>", lambda event, a=axis: self._fill_materials(a))
            tree = ClassTree(upper, f"{word} → sub-class", [
                ("kind", "kind", 170), ("n_materials", "materials", 70), ("n_papers", "papers", 60),
                ("n_values", "Ea values", 72), ("min", "lowest Ea", 80), ("min_material", "lowest of", 190),
                ("median", "median Ea", 84), ("max", "highest Ea", 84), ("stated", "component stated by the paper", 180)],
                height=11)
            tree.tree.bind("<<TreeviewSelect>>", lambda event, a=axis: self._fill_materials(a))
            pane.add(upper, weight=3)
            lower = ttk.Frame(pane, padding=(0, 6, 0, 0))
            caption = ttk.Label(lower, text="", foreground="#8c8c8c")
            caption.pack(anchor="w")
            materials = Table(lower, [
                ("material", "material", 190), ("crystal_structure", "crystal structure", 130),
                ("structure_family", "family", 90), ("basis", "how its structure is known", 260),
                ("n_papers", "papers", 56), ("bulk", "bulk Ea min", 90), ("grain_boundary", "grain-boundary Ea min", 140),
                ("total", "total Ea min", 90), ("Ea_min", "lowest Ea", 80), ("sigma", "σ max (S/cm)", 100)],
                on_open=self.details, stretch="basis", height=12)
            materials.pack(fill="both", expand=True, pady=(2, 0))
            ttk.Label(lower, text=f"{NO_VALUE} no activation energy of that component is reported for it (with the "
                                  "filters above). Double-click a material for all of its activation energies.",
                      foreground="#8c8c8c").pack(anchor="w", pady=(2, 0))
            pane.add(lower, weight=2)
            self.classes[axis], self.trees[axis], self.materials[axis], self.captions[axis] = table, tree, materials, caption
        # The classification by property (family ▸ property ▸ type ▸ origin), first: what “Classify everything” makes.
        from .branches_view import BranchesView
        self.by_property = BranchesView(self.book, lambda: _folder(self.out.get()))
        self.book.insert(0, self.by_property, text="  By property  ")
        self.book.select(self.by_property)
        self._show_view(refresh=False)

    def _show_view(self, refresh: bool = True) -> None:
        """Shows the list of classes the view asks for: the tree of classes and sub-classes, or side by side."""
        tree = self.view.get() == TREE
        for axis, _, _ in AXES:
            word = _AXIS_WORD.get(axis, "Structure family")
            shown, hidden = (self.trees[axis], self.classes[axis]) if tree else (self.classes[axis], self.trees[axis])
            hidden.pack_forget()
            shown.pack(fill="both", expand=True, pady=(2, 0))
            self.headlines[axis].configure(text=(
                f"Each {word.lower()} class and its sub-classes — bulk, grain boundary, total — with their activation "
                "energies (eV). Select a class or a sub-class to list its materials." if tree else
                f"{word} classes — activation energies (eV) by the transport component they describe. "
                "Select a class to list its materials."))
        if refresh:
            self._fill_materials_all()

    def _expand(self, opened: bool) -> None:
        for tree in self.trees.values():
            tree.expand(opened)

    def _add_source(self, folder: Path, ticked: bool) -> None:
        var = tk.BooleanVar(value=ticked)
        self.sources[folder] = var
        index = len(self.sources) - 1  # four to a line
        ttk.Checkbutton(self.sources_frame, text=_shown(folder), variable=var).grid(
            row=index // _PER_LINE, column=index % _PER_LINE, sticky="w", padx=4)

    def _pick_source(self) -> None:
        path = filedialog.askdirectory(title="A database folder (with materials.csv)", initialdir=str(PROJECT_ROOT))
        if path and Path(path) not in self.sources:
            self._add_source(Path(path), ticked=True)

    def _browse(self) -> None:
        """The tables of the classification, one tab each."""
        from LocalExtraction.gui.browser import ResultsBrowser, part_tables
        title, home_folder, tables = part_tables("classify")
        folder = self.result.written or home_folder
        ResultsBrowser(self.root, title, folder, [(label, folder / path.relative_to(home_folder)) for label, path in tables])

    def _open_folder(self) -> None:
        folder = _folder(self.out.get())
        if folder.is_dir():
            open_path(str(folder))
        else:
            messagebox.showinfo(TITLE, "The class folders are written by the first classification.", parent=self.root)

    # ------------------------------------------------------------------
    # Classifying (on its own thread: the window stays responsive)
    # ------------------------------------------------------------------
    def busy(self) -> bool:
        return self._busy

    def _statistics(self):
        """The charts of the classification in the window's folder (📊 Statistics…)."""
        from .stats import classification_charts
        folder = _folder(self.out.get())
        return "classification", lambda: classification_charts(folder)

    def show_flow(self) -> tk.Toplevel:
        """The window that draws the classification flow, with the numbers of the last classification."""
        from .flow_window import open_flow
        return open_flow(self.root, _folder(self.out.get()))

    def _outputs_deleted(self, deleted: bool) -> None:
        if deleted:
            self.status.configure(text="The class folders were deleted. Press Classify to write them again.")

    def classify(self) -> None:
        if self._busy:
            return
        from LocalExtraction.gui.home_guard import ensure_home
        if not ensure_home(self.root, "The classification"):  # the main folder deleted meanwhile: made again, or not
            return
        folders = [folder for folder, var in self.sources.items() if var.get()]
        if not folders:
            messagebox.showinfo(TITLE, "Tick at least one database to classify.", parent=self.root)
            return
        out_dir = _folder(self.out.get()) if self.write_files.get() else None
        self._busy = True
        from LocalExtraction.gui import theme
        theme.mark(self.classify_button)  # stays blue while it runs
        self.classify_button.configure(state="disabled")
        self.delete_button.configure(state="disabled")
        self.status.configure(text="Classifying the materials of " + ", ".join(_shown(f) for f in folders) + " …")
        self.card.hide()
        self._started = time.time()

        from LocalExtraction.gui.progress import Tracker, style_running
        from LocalExtraction.gui.progress_text import Pace
        self._pace = Pace()
        phases = [("read", "Reading the databases", "databases"), ("classify", "Classifying the materials", "")]
        if out_dir is not None:
            phases += [("write", "Writing one database per class", ""),
                       ("by_property", "Classification by property", "families")]
        self.tracker = Tracker("classify", "Classification · ▶ Classify everything", phases)
        self.tracker.start({"read": len(folders)})
        self.status.configure(text=self.tracker.start_text(self.status.cget("text").rstrip(" …")))
        style_running(self.status, True)
        from LocalExtraction.gui.single import existing
        open_one = existing("progress:Classification")
        if open_one is not None:
            open_one.follow(self.tracker)
        self.progress.configure(value=0)
        self.progress.pack(side="right", padx=(10, 0), before=self.status)
        steps = self._steps

        def work() -> None:
            try:
                self._queue.put(run(folders, out_dir, progress=lambda *said: steps.put(said)))
            except Exception as error:  # the window must survive a failed run
                self._queue.put(Result(error=f"The classification failed: {type(error).__name__}: {error}"))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll)

    def _poll(self) -> None:
        latest = None
        while True:  # the newest step said: the line and the bar follow the classification
            try:
                latest = self._steps.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            fraction, text, phase, done, total = latest
            self.progress.configure(value=int(fraction * 1000))
            tracker = self.tracker
            if tracker is not None and phase in tracker.phases:
                step = [key for key, _, _ in tracker.phases_spec].index(phase) + 1
                detail = text.rsplit(": ", 1)[1] if ": " in text and phase in ("read", "by_property") else ""
                tracker.update(phase, done, total, detail)
                self.status.configure(text=f"Step {step} of {len(tracker.phases_spec)} · " + tracker.line())
            else:
                self.status.configure(text=text + self._pace.left("classify", int(fraction * 1000), 1000))
        try:
            result = self._queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        self._busy = False
        self.progress.pack_forget()
        from LocalExtraction.gui.progress import style_running
        if self.tracker is not None and self.tracker.ended is None:
            self.tracker.finish("failed" if result.error else "done")
        style_running(self.status, False, rest="#8c8c8c")
        from LocalExtraction.gui import theme
        theme.unmark(self.classify_button)
        self.classify_button.configure(state="normal", style="Next.TButton")  # the one button stays the one to press
        self.delete_button.configure(state="normal")
        if result.error:
            self.status.configure(text=result.error)
            self.card.show(Outcome("Classification not done", FAILED, result.error, started=self._started))
            return
        self.result = result
        self.refresh()
        self.by_property.show()  # the branches just written
        self.show_outcome()

    def show_outcome(self) -> None:
        """The card of the classification: how many materials and classes, the largest classes with their
        lowest activation energy, and the article it comes from."""
        classified = self.result.classified
        if classified is None:
            return
        energies = self.counted()
        titles = {}
        for source in self.result.sources:
            papers = source.tables.get("papers", pd.DataFrame())
            if {"paper_id", "title"} <= set(papers.columns):
                titles.update({pid: article_title(title, pid) for pid, title in zip(papers["paper_id"], papers["title"])})
        groups = {axis: class_groups(classified, attribute, axis) for axis, attribute, _ in AXES}
        crystal, families = groups.get(CRYSTAL_STRUCTURE, {}), next(
            (g for axis, g in groups.items() if axis != CRYSTAL_STRUCTURE), {})
        if not classified.materials:
            self.card.show(Outcome("Nothing to classify", NOTHING, "The databases hold no material yet.",
                                   started=self._started))
            return
        in_family = sum(len(keys) for keys in crystal.values())
        stats = [Stat(number(len(classified.materials)), "materials classified"),
                 Stat(number(len(crystal)), "crystal families", hint=f"{number(in_family)} materials in one"),
                 Stat(number(len(families)), "structure families"),
                 Stat(number(len(energies)), "activation energies", hint="with the filters above")]
        highlights = []
        column = next(c for axis, _, c in AXES if axis == CRYSTAL_STRUCTURE)
        for label, keys in list(crystal.items())[:3]:
            its = energies[energies[column] == label] if len(energies) else energies
            line = f"{label}: {number(len(keys))} material{'s' if len(keys) != 1 else ''}"
            if len(its):
                best = its.loc[its["Ea_eV"].idxmin()]
                line += (f" · lowest Ea {round(float(best['Ea_eV']), 3)} eV, {best['material']} "
                         f"({titles.get(best['paper_id'], article_title('', best['paper_id']))})")
            highlights.append(line)
        if not crystal:
            highlights.append("No material could be placed in a known crystal family; see the structure families.")
        actions = [("Show the crystal structures", lambda: self.book.select(0)),
                   ("Show the structure families", lambda: self.book.select(1))]
        if self.result.written:
            every = self.result.written / "all_materials.csv"
            actions += [("Browse the files", self._browse), ("Open the class folders", self._open_folder),
                        ("Open all_materials.csv", lambda: open_path(str(every)))]
        detail = (f"From {', '.join(s.name for s in self.result.sources)}"
                  + (f"; the class folders are written into {_shown(self.result.written)}." if self.result.written
                     else "; nothing was written (the box above is unticked)."))
        self.card.show(Outcome("Classification done", "done", detail, stats, highlights, actions, self._started))

    # ------------------------------------------------------------------
    # Showing it
    # ------------------------------------------------------------------
    def counted(self) -> pd.DataFrame:
        """The activation energies the filters keep."""
        return kept(self.result.energies, ORIGINS[self.origin.get()], self.this_work.get(), self.stated.get())

    def refresh(self) -> None:
        classified = self.result.classified
        if classified is None:
            return
        energies = self.counted()
        self._rows = material_rows(classified, energies, self.result.conductivities)
        for axis, attribute, column in AXES:
            groups = class_groups(classified, attribute, axis)
            stats = component_stats(energies, column)
            mine = {(row[column], row["component"]): row for row in stats.to_dict("records")}
            counts = energies[column].value_counts() if len(energies) else pd.Series(dtype=int)
            rows = []
            for label in groups:
                keys = groups[label]
                papers = {paper for key in keys for paper in classified.materials[key].papers}
                cells = [label, class_kind(axis, label), str(len(keys)), str(len(papers)), str(int(counts.get(label, 0)))]
                for component in COMPONENTS:
                    row = mine.get((label, component))
                    cells += [str(row["n_values"]), _cell(row["min_eV"]), _cell(row["median_eV"])] if row else \
                        ["0", NO_VALUE, NO_VALUE]
                rows.append((label, cells, []))
            self.classes[axis].fill(rows)
            self.trees[axis].fill(self._branches(axis, column, groups, energies, stats))
            self._fill_materials(axis)
        total = len(self.result.energies)
        parts = energies["component"].value_counts() if len(energies) else pd.Series(dtype=int)
        stated = int((energies["component_basis"] == "stated").sum()) if len(energies) else 0
        written = f" The class folders were written into {_shown(self.result.written)}." if self.result.written else ""
        self.status.configure(text=(
            f"{len(classified.materials)} materials from {', '.join(s.name for s in self.result.sources)}. "
            f"{len(energies)} of the {total} activation energies count with these filters — "
            + ", ".join(f"{COMPONENT_WORDS.get(c, c)} {int(parts.get(c, 0))}" for c in COMPONENTS)
            + (f", other {len(energies) - sum(int(parts.get(c, 0)) for c in COMPONENTS)}"
               if len(energies) > sum(int(parts.get(c, 0)) for c in COMPONENTS) else "")
            + f"; the paper itself states the component of {stated} of them (the extraction assumed the others, "
              f"saying why in its basis)." + written
            + "".join(f" Warning: {s.name} is only partly rebuilt (a run was stopped): run that part again to "
                      "classify all its papers." for s in self.result.sources if partly_rebuilt(s.path))))

    def _branches(self, axis: str, column: str, groups: dict[str, list[str]], energies: pd.DataFrame,
                  stats: pd.DataFrame) -> list[tuple]:
        """Each class with its overall activation energies, and under it its sub-classes — bulk, grain
        boundary, total (and surface, when there is a value of it) — with theirs."""
        classified = self.result.classified
        mine = {(row[column], row["component"]): row for row in stats.to_dict("records")}
        papers = energies.groupby([column, "component"])["paper_id"].nunique() if len(energies) else pd.Series(dtype=int)
        branches = []
        for label in groups:
            keys = groups[label]
            its = energies[energies[column] == label] if len(energies) else energies
            kind = class_kind(axis, label)
            if len(its):
                best = its.loc[its["Ea_eV"].idxmin()]
                overall = [_cell(round(float(best["Ea_eV"]), 4)), best["material"], _cell(round(float(its["Ea_eV"].median()), 4)),
                           _cell(round(float(its["Ea_eV"].max()), 4)), f"{int((its['component_basis'] == 'stated').sum())} of {len(its)}"]
            else:
                overall = [NO_VALUE, NO_VALUE, NO_VALUE, NO_VALUE, "0 of 0"]
            values = [kind, str(len(keys)), str(len({p for k in keys for p in classified.materials[k].papers})),
                      str(len(its)), *overall]
            children = []
            extra = sorted(c for (group, c) in mine if group == label and c not in COMPONENTS)
            for component in [*COMPONENTS, *extra]:
                row = mine.get((label, component))
                word = COMPONENT_WORDS.get(component, component)
                cells = [f"{word} transport", str(row["n_materials"]), str(int(papers.get((label, component), 0))),
                         str(row["n_values"]), _cell(row["min_eV"]), row["min_material"], _cell(row["median_eV"]),
                         _cell(row["max_eV"]), f"{row['n_component_stated']} of {row['n_values']}"] if row else \
                    [f"{word} transport", "0", "0", "0", NO_VALUE, NO_VALUE, NO_VALUE, NO_VALUE, "0 of 0"]
                children.append((f"{label}{_SEP}{component}", word, cells))
            branches.append((label, label, values, [], children))
        return branches

    def _fill_materials_all(self) -> None:
        for axis, _, _ in AXES:
            self._fill_materials(axis)

    def _chosen(self, axis: str) -> tuple[list[str], str]:
        """The classes selected in the list shown, and the component the materials are listed for
        ("" for every component): a sub-class selected is its class for that component."""
        if self.view.get() != TREE:
            return self.classes[axis].selected(), ""
        picked = [line.split(_SEP) if _SEP in line else [line, ""] for line in self.trees[axis].selected()]
        components = {c for _, c in picked}
        return sorted({label for label, _ in picked}), (components.pop() if len(components) == 1 else "")

    def _fill_materials(self, axis: str) -> None:
        classified = self.result.classified
        if classified is None:
            return
        attribute = next(a for x, a, _ in AXES if x == axis)
        chosen, component = self._chosen(axis)
        keys = [key for key, m in classified.materials.items() if not chosen or getattr(m, attribute) in chosen]
        if axis == CRYSTAL_STRUCTURE:  # the known crystal families only: a material of none is in its structure family
            keys = [key for key in keys if classified.materials[key].structure_type != NO_FAMILY]
        if component:  # a class for one component: its materials with an activation energy of that component
            counted = self.counted()
            having = set(counted.loc[counted["component"] == component, "material_key"]) if len(counted) else set()
            keys = [key for key in keys if key in having]
        find = self.find.get().strip().casefold()
        if find:
            keys = [key for key in keys if find in classified.materials[key].name.casefold()
                    or find in str(self._rows[key]["spellings"]).casefold()]
        rows = []
        for key in keys:
            row = self._rows[key]
            rows.append((key, [row["material"], row["crystal_structure"], row["structure_family"],
                               row["crystal_structure_basis"], str(row["n_papers"]),
                               *(_cell(row[f"Ea_{c}_min_eV"]) for c in COMPONENTS), _cell(row["Ea_min_eV"]),
                               _cell(row["sigma_max_S_cm"])], []))
        by = 5 + COMPONENTS.index(component) if component in COMPONENTS else 8  # the lowest Ea of the component shown
        rows.sort(key=lambda r: (r[1][by] == NO_VALUE, float(r[1][by]) if r[1][by] != NO_VALUE else 0.0, r[1][0].casefold()))
        self.materials[axis].fill(rows)
        what = " and ".join(chosen) if chosen else "every class"
        part = f" — {COMPONENT_WORDS.get(component, component)}" if component else ""
        lowest = f"lowest {COMPONENT_WORDS.get(component, component)} Ea first" if component else "lowest Ea first"
        self.captions[axis].configure(text=f"Materials of {what}{part} ({len(rows)})"
                                           + (f", matching “{self.find.get().strip()}”" if find else "") + f", {lowest}")

    def details(self, key: str) -> tk.Toplevel:
        """Every activation energy of one material — those the filters leave out too — with its
        component and how that is known."""
        material, row = self.result.classified.materials[key], self._rows[key]
        window = tk.Toplevel(self.root)
        window.title(f"{material.name} — {row['crystal_structure']}, {row['structure_family']}")
        from LocalExtraction.gui import layout
        layout.place(window, (1180, 560), (640, 320), parent=self.root)
        window.bind("<Escape>", lambda event: window.destroy())
        body = ttk.Frame(window, padding=10)
        body.pack(fill="both", expand=True)
        from LocalExtraction.gui.design import website_line
        website_line(window)
        about = (f"{material.name}  ·  crystal structure: {row['crystal_structure']} ({row['crystal_structure_basis']})  ·  "
                 f"family: {row['structure_family']} ({row['compound_class']})\n"
                 f"Spellings: {row['spellings']}  ·  {row['n_papers']} paper(s): {row['papers']}  ·  databases: {row['databases']}")
        WrapLabel(body, text=about, wraplength=1140).pack(fill="x")
        energies = self.result.energies[self.result.energies["material_key"] == key]
        counting = set(self.counted().index)
        table = Table(body, [("Ea", "Ea (eV)", 66), ("component", "component", 104), ("known", "component is", 92),
                             ("counted", "counted", 64), ("origin", "origin", 92), ("attribution", "result of", 76),
                             ("reported_as", "the paper calls it", 140), ("where", "read from", 110),
                             ("paper", "paper", 180), ("sentence", "sentence", 420)], stretch="sentence", height=16)
        table.pack(fill="both", expand=True, pady=(8, 0))
        order = {c: i for i, c in enumerate(COMPONENTS)}
        energies = energies.assign(_order=energies["component"].map(order).fillna(len(order))).sort_values(["_order", "Ea_eV"])
        rows = []
        for index, e in energies.iterrows():  # bulk, grain boundary, total, then any other; lowest first
            rows.append((str(index), [f"{e['Ea_eV']:g}", COMPONENT_WORDS.get(e["component"], e["component"]),
                                      e["component_basis"], "yes" if index in counting else "no (filters)",
                                      e.get("data_origin", ""), e.get("attribution", ""), e.get("reported_as", ""),
                                      f"{e.get('extracted_from', '')}, p. {e.get('page', '')}", e.get("paper_id", ""),
                                      e.get("sentence", "")], []))
        table.fill(rows)
        if not rows:
            ttk.Label(body, text="No activation energy of this material is reported.").pack(anchor="w")
        ttk.Button(body, text="Close", command=window.destroy).pack(anchor="e", pady=(8, 0))
        return window


def _folder(text: str) -> Path:
    path = Path(text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _shown(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"{command_name('mme-classify', 'Classification')} gui", description="The window of the classification.",
                                     epilog="MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Database folder(s) to classify (default: LocalExtraction/local_output and "
                             "WebScraping/web_output)")
    parser.add_argument("--out", "-o", default=str(DEFAULT_OUT), metavar="DIR",
                        help="Folder the class folders are written into (default: Classification/)")
    parser.add_argument("--no-write", action="store_true", help="Only show the classes; write no file")
    args = parser.parse_args(argv)
    enter_project_home("classify")  # after the options are read: --help makes no folder
    root = tk.Tk()
    from LocalExtraction.crashlog import watch
    watch(root)  # a window's own errors: written to a crash file, and said
    App(root, [_folder(s) for s in args.source] if args.source else None, _folder(args.out), not args.no_write)
    from LocalExtraction.crashlog import run
    run(root)  # the loop, then the window closed cleanly
    return 0
