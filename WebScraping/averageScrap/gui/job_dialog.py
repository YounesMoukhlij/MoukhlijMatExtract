# WebScraping/averageScrap/gui/job_dialog.py
"""The settings of the web search (the job file, configs/sse.yaml) as a form.

Only what a person may change is offered, each within its bounds (job.LIMITS):
  - the searches, the years, the sources, how many results each source gives;
  - the words that decide which papers are kept;
  - where copies are looked for, how many downloads at once, the largest PDF;
  - which data are extracted.
What may not be changed is shown, not offered: the folder of the PDFs (both methods, the ledger
and "Delete outputs" look for them there) and the job's name. The contact e-mail and the keys are
set in the "API keys…" window. The "# headings" among the words of a list are kept when saving."""

from __future__ import annotations

import dataclasses
import os
import tempfile
import tkinter as tk
import weakref
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from LocalExtraction.config import SchemaConfig
from LocalExtraction.gui.dialogs import Dialog
from LocalExtraction.gui.widgets import WrapLabel

from ..job import (ABSTRACT_SOURCES, DEFAULT_FOLDER, LABELS, LIMITS, NEEDS, RESOLVERS, SOURCES, Job, dump_job,
                   load_job, read_comments)

TITLE = "Web search settings"
_GREY = "#888888"
_COLUMNS = 4
# The data the web extraction can keep, by kind, in the order of the extraction's schema.
PROPERTY_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = tuple(
    (kind.capitalize(), tuple(props)) for kind, props in SchemaConfig.SCHEMA.items())
ALL_PROPERTIES = tuple(p for _, props in PROPERTY_GROUPS for p in props)
TRANSPORT = ("Activation_Energy", "Ionic_Conductivity", "Diffusion_Coefficient", "Electronic_Conductivity")


# ---------------------------------------------------------------------------
# Who wants to know when the settings are saved (an open "Search open sources" window reloads them)
# ---------------------------------------------------------------------------
_listeners: List["weakref.WeakMethod"] = []


def when_saved(method: Callable[[str], None]) -> None:
    """`method(path)` (a method of a window) is called each time a job file is saved from the form."""
    _listeners.append(weakref.WeakMethod(method))


def _tell_saved(path: str) -> None:
    for ref in list(_listeners):
        method = ref()
        if method is None:
            _listeners.remove(ref)
            continue
        try:
            method(path)
        except tk.TclError:  # a window being closed
            pass


def shipped_job() -> Tuple[Job, Dict[str, List[str]], Dict[str, List[str]]]:
    """The settings MoukhlijMatExtract comes with (default_job.yaml), with their comments."""
    from importlib import resources
    from ..about import SHIPPED_JOB
    source = resources.files("WebScraping.averageScrap").joinpath(SHIPPED_JOB)
    with resources.as_file(source) as real:
        headings, notes = read_comments(str(real))
        return load_job(str(real)), headings, notes


def open_job_settings(parent: tk.Misc, path: Optional[str] = None,
                      on_saved: Optional[Callable[[str], None]] = None) -> Optional["JobDialog"]:
    """The form for a job file (default: configs/sse.yaml, made from the shipped one if missing).
    A file that cannot be read is offered to be started over from the default settings."""
    from ..about import DEFAULT_JOB, ensure_default_job
    from ..job import load_env
    load_env()  # which keys are set: a source without its key is marked so
    path = path or DEFAULT_JOB
    if path == DEFAULT_JOB:
        ensure_default_job(path)
    try:
        job = load_job(path)
        headings, notes = read_comments(path)
    except (OSError, ValueError) as error:
        if not messagebox.askyesno(TITLE, f"{path} cannot be read:\n\n{error}\n\nOpen the settings with the "
                                          "default values instead? Your file is only replaced when you press Save.",
                                   parent=parent):
            return None
        job, headings, notes = shipped_job()
    return JobDialog(parent, job, path, on_saved or (lambda saved: None), headings, notes)


# ---------------------------------------------------------------------------
# Small widgets
# ---------------------------------------------------------------------------
class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls up and down (each tab of the form is one)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner = ttk.Frame(self.canvas, padding=(14, 10))
        window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._window = window
        self.inner.bind("<Configure>", lambda e: self._fit())
        self.canvas.bind("<Configure>", lambda e: self._fit())
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

    def _fit(self) -> None:
        """The content as wide as the tab, and at least as high (no bare canvas shows below it)."""
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.itemconfigure(self._window, width=width, height=max(height, self.inner.winfo_reqheight()))
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", 0) in (4, 5):  # Linux
            step = -1 if event.num == 4 else 1
        else:
            step = -event.delta if abs(event.delta) < 120 else -event.delta // 120
        self.canvas.yview_scroll(int(step) or (1 if event.delta < 0 else -1), "units")
        return "break"

    def wheel_everywhere(self) -> None:
        """The wheel scrolls the tab wherever the pointer is on it — but a text box scrolls itself."""
        def walk(widget: tk.Misc) -> None:
            if isinstance(widget, tk.Text):
                return
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(sequence, self._wheel)
            for child in widget.winfo_children():
                walk(child)
        walk(self.canvas)


def _heading(parent: tk.Misc, text: str, used_by: str = "") -> None:
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(14, 2))
    ttk.Label(row, text=text, font=("TkDefaultFont", 12, "bold")).pack(side="left")
    if used_by:
        ttk.Label(row, text=f"  ·  {used_by}", foreground=_GREY).pack(side="left")


def _note(parent: tk.Misc, text: str) -> None:
    WrapLabel(parent, text=text, foreground=_GREY, justify="left").pack(fill="x", anchor="w")


def _words_box(parent: tk.Misc, height: int) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill="x", pady=(4, 0))
    box = tk.Text(frame, height=height, wrap="none", relief="solid", borderwidth=1, padx=5, pady=3, undo=True)
    bar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
    box.configure(yscrollcommand=bar.set)
    box.tag_configure("heading", foreground="#4a90d9")
    box.pack(side="left", fill="x", expand=True)
    bar.pack(side="right", fill="y")
    box.bind("<KeyRelease>", lambda e: _colour_headings(box), add="+")
    return box


def _colour_headings(box: tk.Text) -> None:
    box.tag_remove("heading", "1.0", "end")
    for number, line in enumerate(box.get("1.0", "end").splitlines(), start=1):
        if line.strip().startswith("#"):
            box.tag_add("heading", f"{number}.0", f"{number}.end")


def _layout(box: tk.Text) -> List[str]:
    """A list as the box shows it: its words (one per line, each once) and its "# headings"."""
    out, seen = [], set()
    for line in box.get("1.0", "end").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            out.append("# " + line.lstrip("#").strip())
        elif line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _words(layout: Sequence[str]) -> List[str]:
    return [entry for entry in layout if not entry.startswith("#")]


def _spin(parent: tk.Misc, label: str, limit: str, increment: float = 1, after: str = "") -> tk.StringVar:
    low, high = LIMITS[limit]
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(8, 0))
    ttk.Label(row, text=label).pack(side="left")
    var = tk.StringVar()
    ttk.Spinbox(row, textvariable=var, from_=low, to=high, increment=increment, width=7).pack(side="left", padx=6)
    ttk.Label(row, text=after or f"({low} to {high})", foreground=_GREY).pack(side="left")
    return var


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------
class JobDialog(Dialog):
    """The settings of a job file, as a form. `on_saved(path)` is called once it is saved."""

    def __init__(self, parent: tk.Misc, job: Job, path: str, on_saved: Callable[[str], None],
                 headings: Optional[Dict[str, List[str]]] = None, notes: Optional[Dict[str, List[str]]] = None):
        super().__init__(parent, f"{TITLE} — {os.path.basename(path) or 'new'}", "900x760")
        self.minsize(760, 560)
        if headings is None and notes is None and os.path.exists(path):
            headings, notes = read_comments(path)
        self.job, self.path, self._on_saved = job, path, on_saved
        self.headings, self.notes = headings or {}, notes or {}

        WrapLabel(self.body, justify="left",
                  text=f"Saved in {os.path.abspath(path)}. Method 1 (Search open sources) uses every setting; "
                       "method 2 (moukhlij4scraping) uses the searches, the years, the sources, the results per "
                       "source and the topic and property words.").pack(fill="x")
        book = ttk.Notebook(self.body)
        book.pack(fill="both", expand=True, pady=(8, 0))
        self._scrolls: List[ScrollFrame] = []
        self._searches_tab(self._tab(book, "1 · Searches"))
        self._sources_tab(self._tab(book, "2 · Sources and years"))
        self._screening_tab(self._tab(book, "3 · Which papers"))
        self._download_tab(self._tab(book, "4 · Download"))
        self._extraction_tab(self._tab(book, "5 · Data extracted"))

        WrapLabel(self.body, foreground=_GREY, justify="left",
                  text=f"Not set here — the contact e-mail and the API keys: “API keys…” in the web window. "
                       f"Fixed — the folder of the PDFs ({DEFAULT_FOLDER}/) and the job's name.").pack(fill="x", pady=(8, 0))
        buttons = ttk.Frame(self.body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Reset to defaults", command=self._reset).pack(side="left")
        ttk.Button(buttons, text="Save", command=lambda: self._save(self.path)).pack(side="right")
        ttk.Button(buttons, text="Save as…", command=self._save_as).pack(side="right", padx=6)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        self._fill(job, self.headings)

    def _tab(self, book: ttk.Notebook, title: str) -> ttk.Frame:
        scroll = ScrollFrame(book)
        book.add(scroll, text=title)
        self._scrolls.append(scroll)
        return scroll.inner

    # --- the tabs ------------------------------------------------------
    def _searches_tab(self, tab: ttk.Frame) -> None:
        _heading(tab, "What to search for", "both methods")
        _note(tab, "One search per line. A line starting with # is a heading: it groups the searches below it and "
                   "is not searched.")
        self.queries = _words_box(tab, 18)
        self.query_count = tk.StringVar()
        ttk.Label(tab, textvariable=self.query_count, foreground=_GREY).pack(anchor="w")
        self.queries.bind("<KeyRelease>", lambda e: self._count(), add="+")

        _heading(tab, "Papers you already know", "method 1")
        _note(tab, "Optional: a text file with one DOI, DOI link or arXiv id per line. They are added to what the "
                   "searches find.")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 0))
        self.ids_file = tk.StringVar()
        ttk.Entry(row, textvariable=self.ids_file).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._pick_ids).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Clear", command=lambda: self.ids_file.set("")).pack(side="left", padx=(6, 0))

    def _sources_tab(self, tab: ttk.Frame) -> None:
        _heading(tab, "Years", "both methods")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 0))
        low, high = LIMITS["years"]
        self.year_from, self.year_to = tk.StringVar(), tk.StringVar()
        ttk.Label(row, text="Published from").pack(side="left")
        ttk.Spinbox(row, textvariable=self.year_from, from_=low, to=high, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="to").pack(side="left")
        ttk.Spinbox(row, textvariable=self.year_to, from_=low, to=high, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="(both empty: any year)", foreground=_GREY).pack(side="left")

        _heading(tab, "How many results", "both methods")
        self.max_per_query = _spin(tab, "Results asked of each source, for each search", "max_per_query")

        _heading(tab, "Where to search", "method 1 — method 2 uses OpenAlex, Crossref, Semantic Scholar, arXiv "
                                         "(and Google Scholar)")
        _note(tab, "A source marked “key missing” is skipped until its key is set in “API keys…”.")
        self.search_frame = ttk.Frame(tab)
        self.search_frame.pack(fill="x", pady=(4, 0))
        self.include_preprints = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Preprints count too (arXiv and the like)",
                        variable=self.include_preprints).pack(anchor="w", pady=(8, 0))

        _heading(tab, "Missing abstracts are asked of", "method 1")
        _note(tab, "A paper found without its abstract is looked up there, in this order. Untick them all to ask "
                   "nobody (screening then reads the title only).")
        self.abstract_frame = ttk.Frame(tab)
        self.abstract_frame.pack(fill="x", pady=(4, 0))

    def _screening_tab(self, tab: ttk.Frame) -> None:
        _heading(tab, "How a paper is kept", "method 1")
        _note(tab, "A paper is kept when its title or abstract has a topic word AND a property word, and its score "
                   "reaches the minimum: a word in the title counts 2 points, in the abstract 1, and each excluded "
                   "word costs 3. One word per line; a line starting with # is a heading.")
        _heading(tab, "Topic words", "both methods (method 2 makes more searches of them when they run dry)")
        self.topic_words = _words_box(tab, 8)
        _heading(tab, "Property words", "both methods")
        self.property_words = _words_box(tab, 7)
        _heading(tab, "Excluded words", "method 1")
        self.exclude_words = _words_box(tab, 6)
        self.min_score = _spin(tab, "Minimum score", "min_score", increment=0.5)
        self.propose_closed = tk.BooleanVar()
        ttk.Checkbutton(tab, variable=self.propose_closed,
                        text="Also keep papers no free copy is known for (the repositories are asked; what nobody "
                             "has is listed as “closed”, to get by hand)").pack(anchor="w", pady=(10, 0))
        self.review = tk.BooleanVar()
        ttk.Checkbutton(tab, variable=self.review,
                        text="In the terminal (mme-web): stop after the search, so the papers can be reviewed "
                             "before anything is downloaded").pack(anchor="w", pady=(6, 0))

    def _download_tab(self, tab: ttk.Frame) -> None:
        _heading(tab, "Where a copy is looked for", "method 1")
        _note(tab, "Only legal copies. They are asked in this order; untick a place to skip it.")
        self.fetch_frame = ttk.Frame(tab)
        self.fetch_frame.pack(fill="x", pady=(4, 0))
        _heading(tab, "Downloads", "method 1")
        self.fetch_workers = _spin(tab, "Downloads at once", "workers", after="(1 to 8 — more is impolite to the servers)")
        self.max_pdf_mb = _spin(tab, "Largest PDF accepted, in MB", "max_pdf_mb")
        _heading(tab, "Folder of the PDFs")
        ttk.Label(tab, text=f"{DEFAULT_FOLDER}/   (fixed)").pack(anchor="w")
        _note(tab, "Not a setting: both methods, the ledger of the search and “Delete outputs” look for the "
                   "papers there.")

    def _extraction_tab(self, tab: ttk.Frame) -> None:
        _heading(tab, "Data to extract", "both methods")
        _note(tab, "Activation_Energy covers every name a paper gives it: migration barrier, energy barrier, Ea, …")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Every property", command=lambda: self._tick(ALL_PROPERTIES)).pack(side="left")
        ttk.Button(row, text="Ion transport only", command=lambda: self._tick(TRANSPORT)).pack(side="left", padx=6)
        ttk.Button(row, text="None", command=lambda: self._tick(())).pack(side="left")
        self.properties: Dict[str, tk.BooleanVar] = {}
        for kind, props in PROPERTY_GROUPS:
            ttk.Label(tab, text=kind, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(10, 2))
            grid = ttk.Frame(tab)
            grid.pack(fill="x")
            for index, name in enumerate(props):
                var = self.properties.setdefault(name, tk.BooleanVar())
                ttk.Checkbutton(grid, text=name.replace("_", " "), variable=var).grid(
                    row=index // _COLUMNS, column=index % _COLUMNS, sticky="w", padx=(0, 16))
        self.require_material = tk.BooleanVar()
        ttk.Checkbutton(tab, text="Drop a value that cannot be tied to a material",
                        variable=self.require_material).pack(anchor="w", pady=(12, 0))

    # --- filling the form ----------------------------------------------
    def _fill(self, job: Job, headings: Dict[str, List[str]]) -> None:
        def words(box: tk.Text, name: str, values: List[str]) -> None:
            box.delete("1.0", "end")
            layout = headings.get(name) if headings.get(name) and _words(headings[name]) == values else values
            box.insert("1.0", "\n".join(layout))
            _colour_headings(box)

        s, c, f, e = job.search, job.screen, job.fetch, job.extract
        words(self.queries, "search.queries", s.queries)
        self._count()
        self.ids_file.set(s.ids_file)
        self.year_from.set(str(s.years[0]) if s.years else "")
        self.year_to.set(str(s.years[1]) if s.years else "")
        self.max_per_query.set(f"{s.max_per_query:g}")
        self.include_preprints.set(s.include_preprints)
        self.search_sources = self._checks(self.search_frame, SOURCES, s.sources)
        self.abstract_sources = self._checks(self.abstract_frame, ABSTRACT_SOURCES, s.abstract_sources)
        words(self.topic_words, "screen.topic_words", c.topic_words)
        words(self.property_words, "screen.property_words", c.property_words)
        words(self.exclude_words, "screen.exclude_words", c.exclude_words)
        self.min_score.set(f"{c.min_score:g}")
        self.propose_closed.set(c.propose_closed)
        self.review.set(c.review)
        self.fetch_sources = self._checks(self.fetch_frame, RESOLVERS, f.sources)
        self.fetch_workers.set(str(f.workers))
        self.max_pdf_mb.set(f"{f.max_pdf_mb:g}")
        self._tick(e.properties or ALL_PROPERTIES)
        self.require_material.set(e.require_material)
        for scroll in self._scrolls:  # the boxes of the sources were made again
            scroll.wheel_everywhere()

    def _checks(self, frame: ttk.Frame, known: Sequence[str], chosen: Sequence[str]) -> Dict[str, tk.BooleanVar]:
        """A box per known name — those chosen first, in their order (it is the order they are asked
        in), then the others."""
        for child in frame.winfo_children():
            child.destroy()
        order = [n for n in chosen if n in known] + [n for n in known if n not in chosen]
        variables: Dict[str, tk.BooleanVar] = {}
        for index, name in enumerate(order):
            variables[name] = tk.BooleanVar(value=name in chosen)
            missing = NEEDS.get(name) and not os.environ.get(NEEDS[name])
            text = LABELS.get(name, name) + (f"  ({'e-mail' if NEEDS[name] == 'MME_EMAIL' else 'key'} missing)"
                                             if missing else "")
            ttk.Checkbutton(frame, text=text, variable=variables[name]).grid(
                row=index // _COLUMNS, column=index % _COLUMNS, sticky="w", padx=(0, 16), pady=1)
        return variables

    def _tick(self, names: Sequence[str]) -> None:
        for name, var in self.properties.items():
            var.set(name in names)

    def _count(self) -> None:
        count = len(_words(_layout(self.queries)))
        self.query_count.set(f"{count} search{'es' if count != 1 else ''}")

    def _pick_ids(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="A list of papers (one DOI or arXiv id per line)",
                                          filetypes=[("Text file", "*.txt *.csv"), ("Any file", "*")])
        if path:
            self.ids_file.set(path)

    def _reset(self) -> None:
        if not messagebox.askyesno(TITLE, "Put back the settings MoukhlijMatExtract comes with?\n\nNothing is "
                                          "saved until you press Save.", parent=self):
            return
        job, headings, notes = shipped_job()
        self.job = dataclasses.replace(job, fetch=dataclasses.replace(job.fetch, folder=self.job.fetch.folder))
        self.notes = notes
        self._fill(self.job, headings)

    # --- reading the form ----------------------------------------------
    def _read(self) -> Job:
        """The job the form describes. Raises ValueError saying what is wrong in it."""
        def number(var: tk.StringVar, limit: str, what: str, whole: bool = True) -> float:
            low, high = LIMITS[limit]
            try:
                value = float(var.get().strip())
            except ValueError:
                raise ValueError(f"{what}: a number from {low} to {high} is expected") from None
            if whole and value != int(value):
                raise ValueError(f"{what}: a whole number is expected")
            if not low <= value <= high:
                raise ValueError(f"{what}: a number from {low} to {high} is expected")
            return int(value) if whole else value

        first, last = self.year_from.get().strip(), self.year_to.get().strip()
        if bool(first) != bool(last):
            raise ValueError("Years: give both the first and the last year, or neither")
        years = None
        if first:
            years = (int(number(self.year_from, "years", "First year")), int(number(self.year_to, "years", "Last year")))
            if years[0] > years[1]:
                raise ValueError("Years: the first year comes after the last one")
        queries = _words(_layout(self.queries))
        ids_file = self.ids_file.get().strip()
        if not queries and not ids_file:
            raise ValueError("Searches: give at least one search (or a file of papers you already know)")
        search_sources = [n for n, v in self.search_sources.items() if v.get()]
        if not search_sources:
            raise ValueError("Where to search: tick at least one source")
        fetch_sources = [n for n, v in self.fetch_sources.items() if v.get()]
        if not fetch_sources:
            raise ValueError("Where a copy is looked for: tick at least one place")
        topic, prop = _words(_layout(self.topic_words)), _words(_layout(self.property_words))
        if not topic or not prop:
            raise ValueError("Which papers: give at least one topic word and one property word")
        ticked = [name for name, var in self.properties.items() if var.get()]
        if not ticked:
            raise ValueError("Data to extract: tick at least one property")
        before = self.job.extract.properties
        if len(ticked) == len(ALL_PROPERTIES) and not before:
            properties: List[str] = []  # every property, as the file had it
        else:
            properties = [p for p in before if p in ticked] + [p for p in ticked if p not in before]

        job = self.job
        return dataclasses.replace(
            job,
            search=dataclasses.replace(
                job.search, queries=queries, ids_file=ids_file, years=years, sources=search_sources,
                max_per_query=number(self.max_per_query, "max_per_query", "Results per source"),
                include_preprints=self.include_preprints.get(),
                abstract_sources=[n for n, v in self.abstract_sources.items() if v.get()]),
            screen=dataclasses.replace(
                job.screen, topic_words=topic, property_words=prop, exclude_words=_words(_layout(self.exclude_words)),
                min_score=number(self.min_score, "min_score", "Minimum score", whole=False),
                review=self.review.get(), propose_closed=self.propose_closed.get()),
            fetch=dataclasses.replace(
                job.fetch, sources=fetch_sources, workers=number(self.fetch_workers, "workers", "Downloads at once"),
                max_pdf_mb=number(self.max_pdf_mb, "max_pdf_mb", "Largest PDF")),
            extract=dataclasses.replace(job.extract, properties=properties,
                                        require_material=self.require_material.get()))

    def _layouts(self) -> Dict[str, List[str]]:
        return {"search.queries": _layout(self.queries), "screen.topic_words": _layout(self.topic_words),
                "screen.property_words": _layout(self.property_words),
                "screen.exclude_words": _layout(self.exclude_words)}

    # --- saving ----------------------------------------------------------
    def _save_as(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Save the settings as", defaultextension=".yaml",
                                            initialdir=os.path.dirname(os.path.abspath(self.path)),
                                            filetypes=[("Job file", "*.yaml *.yml")])
        if path:
            self._save(path)

    def _save(self, path: str) -> None:
        try:
            text = dump_job(self._read(), self._layouts(), self.notes)
            # The loader is the judge of a job file: what it refuses is not saved.
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as trial:
                trial.write(text)
            try:
                load_job(trial.name)
            finally:
                os.remove(trial.name)
        except (ValueError, OSError) as error:
            messagebox.showerror(TITLE, str(error), parent=self)
            return
        lost = _comments_lost(path, text)
        if lost and not messagebox.askyesno(
                TITLE, f"{os.path.basename(path)} has {len(lost)} comment line(s) written by hand that the form "
                       f"cannot keep, e.g.:\n\n{lost[0]}\n\nSave anyway? (“Save as…” writes another file.)", parent=self):
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            part = path + ".part"
            with open(part, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(part, path)
        except OSError as error:
            messagebox.showerror(TITLE, f"The settings could not be saved:\n{error}", parent=self)
            return
        self._on_saved(path)
        _tell_saved(path)
        self.destroy()


def _comments_lost(path: str, text: str) -> List[str]:
    """The comment lines of the file at `path` that `text` (what replaces it) no longer holds,
    leaving out the headings of words that were removed (those go with their words)."""
    try:
        with open(path, encoding="utf-8") as f:
            old = [line.strip() for line in f if line.strip().startswith("#")]
    except OSError:
        return []
    kept = {line.strip() for line in text.splitlines()}
    headings, _ = read_comments(path)
    with_words = {entry for layout in headings.values() for entry in layout if entry.startswith("#")}
    return [line for line in old if line not in kept and line not in with_words]
