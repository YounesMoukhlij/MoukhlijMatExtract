# LocalExtraction/gui/browser.py
"""Every result of a part of MoukhlijMatExtract, table by table, in one window.

One entry of the list on the left per table of the part's folder in ~/MoukhlijMatExtract — for an extraction database: the
papers, the materials, each transport quantity, every property, the methods, the tables, figures and
equations of the papers… — each with its number of rows, every column, a search over all of them,
sorting by any column (click its heading), and every cell of the selected row in full below. The
files are only read: nothing in the window changes them.

`open_results(parent, part)` opens it for a part ("local", "web", "rank", "classify")."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ..about import PROJECT_HOME
from ..exporter import UnreadableTable, read_table
from .widgets import Table, WrapLabel, open_path

_SHOWN_AT_MOST = 5000  # rows put in a table at once (more would freeze the window); the search finds the others
_WIDE = ("title", "sentence", "caption", "basis", "context", "highlights", "materials", "source", "text",
         "keywords", "authors", "articles", "rows", "headers", "evidence", "variables", "folder", "url")

# The tables of an extraction database, in the order a reader looks for them, with their names.
EXTRACTION_TABLES: Tuple[Tuple[str, str], ...] = (
    ("papers", "Papers"), ("activation_energy", "Activation energies"),
    ("ionic_conductivity", "Ionic conductivities"), ("electronic_conductivity", "Electronic conductivities"),
    ("diffusion_coefficient", "Diffusion coefficients"), ("properties", "All properties"),
    ("materials", "Materials"), ("methods", "Methods"), ("unassigned_values", "Values without a material"),
    ("tables", "Tables of the papers"), ("figures", "Figures"), ("equations", "Equations"),
    ("workflow", "Workflow"), ("relations", "Material ↔ value links"), ("summary", "Summary per paper"),
)


def part_tables(part: str, home: Path = PROJECT_HOME) -> Tuple[str, Path, List[Tuple[str, Path]]]:
    """What the browser shows of a part: (its title, its folder, [(tab name, CSV file)])."""
    home = Path(home)
    if part in ("local", "web"):
        folder = home / ("LocalExtraction/local_output" if part == "local" else "WebScraping/web_output")
        tables = [(label, folder / f"{name}.csv") for name, label in EXTRACTION_TABLES]
        if part == "web":
            tables += [("Candidates of the search", home / "WebScraping/papers/candidates.csv"),
                       ("DOI list (Fetch DOIs)", home / "WebScraping/Fetch_DOIs/dois.csv")]
        title = "1 · Local extraction — the database of your PDFs" if part == "local" else \
            "2 · Web scraping — the database of the papers from the web"
        return title, folder, tables
    if part == "rank":
        folder = home / "SelectingTopMaterial/results"
        tables = [("Summary of the components", folder / "summary.csv")]
        components = ["bulk", "grain_boundary", "total"]
        if folder.is_dir():
            components += sorted(p.name for p in folder.iterdir() if p.is_dir() and p.name not in components
                                 and (p / "all_materials.csv").exists())
        for component in components:
            word = component.replace("_", " ").capitalize()
            tables += [(f"{word} — top materials", folder / component / "top_materials.csv"),
                       (f"{word} — all materials", folder / component / "all_materials.csv"),
                       (f"{word} — values", folder / component / "values.csv")]
        return "3 · Ranking — one ranking per transport component", folder, tables
    if part == "classify":
        folder = home / "Classification"
        return "4 · Classification — by crystal structure and structure family", folder, [
            ("All materials and their classes", folder / "all_materials.csv"),
            ("Crystal families", folder / "crystal_structure/summary.csv"),
            ("Crystal families — Ea by component", folder / "crystal_structure/activation_energy_by_component.csv"),
            ("Structure families", folder / "structure_families/summary.csv"),
            ("Structure families — Ea by component", folder / "structure_families/activation_energy_by_component.csv"),
        ]
    raise ValueError(f"unknown part {part!r}")


def has_results(part: str, home: Path = PROJECT_HOME) -> bool:
    return any(path.is_file() for _, path in part_tables(part, home)[2])


def open_results(parent: tk.Misc, part: str, home: Path = PROJECT_HOME) -> "ResultsBrowser":
    title, folder, tables = part_tables(part, home)
    return ResultsBrowser(parent, title, folder, tables)


def open_database(parent: tk.Misc, folder: str) -> "ResultsBrowser":
    """The browser of an extraction database, wherever it is (a part's own, or another folder)."""
    folder_path = Path(folder).resolve()
    for part in ("local", "web"):
        if part_tables(part)[1].resolve() == folder_path:
            return open_results(parent, part)
    return ResultsBrowser(parent, f"the database in {folder}", folder_path,
                          [(label, folder_path / f"{name}.csv") for name, label in EXTRACTION_TABLES])


def _width(column: str) -> int:
    name = column.casefold()
    if name in ("paper_id", "doi", "material", "material_formula", "normalized_formula", "raw_formula"):
        return 190
    return 320 if any(word in name for word in _WIDE) else 110


class ResultsBrowser(tk.Toplevel):
    """The tables of a folder of results, one tab each."""

    def __init__(self, parent: tk.Misc, title: str, folder: Path, tables: Sequence[Tuple[str, Path]]):
        super().__init__(parent)
        self.folder = Path(folder)
        self.title(f"Results — {title}")
        width, height = 1240, 800
        self.geometry(f"{min(width, int(self.winfo_screenwidth() * 0.95))}x"
                      f"{min(height, int(self.winfo_screenheight() * 0.85))}")
        self.minsize(720, 460)
        self.bind("<Escape>", lambda e: self.destroy())

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        self.headline = tk.StringVar()
        WrapLabel(body, textvariable=self.headline, foreground="#8c8c8c", justify="left").pack(fill="x", pady=(2, 8))

        bar = ttk.Frame(body)
        bar.pack(fill="x")
        ttk.Label(bar, text="Search").pack(side="left")
        self.search = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True, padx=(6, 12))
        entry.bind("<KeyRelease>", lambda e: self._later())
        self.shown = tk.StringVar()
        ttk.Label(bar, textvariable=self.shown, foreground="#8c8c8c").pack(side="left")

        panes = ttk.PanedWindow(body, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(8, 0))
        sides = ttk.PanedWindow(panes, orient="horizontal")
        panes.add(sides, weight=5)
        # The tables, on the left: their names and how many rows each holds — however many there are.
        menu = ttk.Frame(sides)
        sides.add(menu, weight=0)
        self.menu = ttk.Treeview(menu, columns=("rows",), show="tree headings", selectmode="browse", height=16)
        self.menu.heading("#0", text="Table", anchor="w")
        self.menu.heading("rows", text="Rows", anchor="e")
        self.menu.column("#0", width=250, stretch=True)
        self.menu.column("rows", width=70, anchor="e", stretch=False)
        self.menu.tag_configure("empty", foreground="#8c8c8c")
        self.menu.pack(fill="both", expand=True)
        self.menu.bind("<<TreeviewSelect>>", lambda e: self._show_tab())
        self.content = ttk.Frame(sides)
        sides.add(self.content, weight=4)
        details = ttk.Frame(panes)
        panes.add(details, weight=1)
        self.details = tk.Text(details, height=7, wrap="word", relief="flat", padx=8, pady=6, state="disabled")
        self.details.tag_configure("name", foreground="#8c8c8c")
        bar2 = ttk.Scrollbar(details, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=bar2.set)
        self.details.pack(side="left", fill="both", expand=True)
        bar2.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Open this table", command=self._open_table).pack(side="left")
        self.doi_button = ttk.Button(buttons, text="Open the paper at doi.org", command=self._open_doi)
        self.doi_button.pack(side="left", padx=6)
        workbook = self.folder / "database.xlsx"
        if workbook.exists():
            ttk.Button(buttons, text="Open the workbook", command=lambda: open_path(str(workbook))).pack(side="left")
        ttk.Button(buttons, text="Open the folder", command=self._open_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Refresh", command=self.load).pack(side="right", padx=6)

        self.tables = list(tables)
        self.tabs: List[Dict] = []
        self._pending: Optional[str] = None
        self._shown_tab: Optional[Dict] = None
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Reads every table again (each tab is filled when it is shown). The files are read on another
        thread — a large database takes seconds — and the window stays usable meanwhile."""
        for tab in self.tabs:
            tab["frame"].destroy()
        self.menu.delete(*self.menu.get_children())
        self.tabs, self._shown_tab, self._dois = [], None, {}
        self.headline.set(f"Reading the tables of {self.folder} …")
        self.shown.set("")
        self._reading = token = object()  # a Refresh pressed meanwhile: only the last reading is shown
        self._loaded = threading.Event()
        tables = list(self.tables)
        done: List = []

        def read_all() -> None:
            for label, path in tables:
                if not path.is_file():
                    continue
                try:
                    frame, problem = read_table(str(path)), ""
                except (UnreadableTable, OSError, ValueError, pd.errors.ParserError) as error:
                    frame, problem = pd.DataFrame(), f"cannot be read: {error}"
                done.append((label, path, frame.fillna(""), problem))
            done.append(None)  # the end

        def show_when_read() -> None:
            if token is not self._reading or not self.winfo_exists():
                return
            if not done or done[-1] is not None:
                self.after(50, show_when_read)
                return
            self._show_tables(done[:-1])
            self._loaded.set()

        threading.Thread(target=read_all, name="results-reader", daemon=True).start()
        self.after(50, show_when_read)

    def wait_loaded(self, timeout: float = 30.0) -> bool:
        """Turns the window's loop until the tables are read (for the tests)."""
        end = time.monotonic() + timeout
        while not self._loaded.is_set() and time.monotonic() < end:
            self.update()
            time.sleep(0.01)
        return self._loaded.is_set()

    def _show_tables(self, read: List[Tuple[str, Path, pd.DataFrame, str]]) -> None:
        rows = 0
        for label, path, frame, problem in read:
            box = ttk.Frame(self.content, padding=(8, 0, 0, 0))
            self.menu.insert("", "end", iid=str(len(self.tabs)), text=label, values=(f"{len(frame):,}",),
                             tags=() if len(frame) else ("empty",))
            self.tabs.append({"frame": box, "label": label, "path": path, "data": frame,
                              "table": None, "problem": problem, "filled": None})
            rows += len(frame)
            if path.name == "papers.csv" and {"paper_id", "doi"} <= set(frame.columns):
                # every row of a paper — a value, a material — can open the paper it comes from
                self._dois = {str(p): str(d).strip() for p, d in zip(frame["paper_id"], frame["doi"])}
        if not self.tabs:
            self.headline.set(f"No results yet in {self.folder}: run this part first.")
            self.shown.set("")
            return
        self.headline.set(f"{len(self.tabs)} table{'s' if len(self.tabs) != 1 else ''}, {rows:,} rows, read from "
                          f"{self.folder}. Pick a table on the left; click a heading to sort; select a row to see "
                          "every cell of it below.")
        self.select(0)

    def select(self, index: int) -> None:
        """Shows the table at this place of the list."""
        if 0 <= index < len(self.tabs):
            self.menu.selection_set(str(index))
            self.menu.focus(str(index))
            self._show_tab()

    def _current(self) -> Optional[Dict]:
        chosen = self.menu.selection()
        try:
            return self.tabs[int(chosen[0])] if chosen else None
        except (ValueError, IndexError):
            return None

    def _show_tab(self) -> None:
        tab = self._current()
        if tab is None:
            return
        if self._shown_tab is not tab:
            if self._shown_tab is not None:
                self._shown_tab["frame"].pack_forget()
            tab["frame"].pack(fill="both", expand=True)
            self._shown_tab = tab
        if tab["table"] is None:
            data = tab["data"]
            if tab["problem"] or data.empty:
                ttk.Label(tab["frame"], text=f"{tab['path'].name}: " + (tab["problem"] or "no row yet."),
                          foreground="#8c8c8c").pack(anchor="w")
            columns = [(f"c{i}", name, _width(name)) for i, name in enumerate(data.columns)]
            stretch = next((key for key, name, _ in columns if name.casefold() == "title"), "")
            tab["table"] = Table(tab["frame"], columns, stretch=stretch, height=14)
            tab["table"].pack(fill="both", expand=True)
            tab["table"].tree.bind("<<TreeviewSelect>>", lambda e: self._show_row())
        self._filter()

    def _later(self) -> None:
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = self.after(250, self._filter)

    def _filter(self) -> None:
        """The rows of the tab in front that hold the searched text (in any column)."""
        self._pending = None
        tab = self._current()
        if tab is None or tab["table"] is None:
            return
        data, text = tab["data"], self.search.get().strip().casefold()
        if text and len(data):
            mask = data.astype(str).apply(lambda column: column.str.casefold().str.contains(text, regex=False)).any(axis=1)
            matching = data[mask]
        else:
            matching = data
        rows = [(str(index), [str(v) for v in row], ()) for index, row in
                zip(matching.index[:_SHOWN_AT_MOST], matching.head(_SHOWN_AT_MOST).itertuples(index=False))]
        tab["table"].fill(rows)
        more = f" (the first {_SHOWN_AT_MOST:,}: search to find the others)" if len(matching) > _SHOWN_AT_MOST else ""
        self.shown.set(f"{tab['label']}: showing {min(len(matching), _SHOWN_AT_MOST):,} of {len(data):,}{more}")
        self._show_row()

    def _row(self) -> Optional[pd.Series]:
        tab = self._current()
        if tab is None or tab["table"] is None:
            return None
        chosen = tab["table"].tree.focus() or next(iter(tab["table"].selected()), "")
        try:
            return tab["data"].loc[int(chosen)] if chosen else None
        except (KeyError, ValueError):
            return None

    def _show_row(self) -> None:
        row = self._row()
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if row is not None:
            for name, value in row.items():
                if str(value).strip():
                    self.details.insert("end", f"{name}: ", "name")
                    self.details.insert("end", f"{value}\n")
        self.details.configure(state="disabled")
        self.doi_button.configure(state="normal" if self._doi(row) else "disabled")

    def _doi(self, row: Optional[pd.Series]) -> str:
        """The row's DOI, or that of the paper it comes from (papers.csv, by paper_id)."""
        if row is None:
            return ""
        doi = str(row.get("doi", "") or "").strip()
        if not doi.startswith("10."):
            doi = getattr(self, "_dois", {}).get(str(row.get("paper_id", "") or ""), "")
        return doi if doi.startswith("10.") else ""

    def _open_doi(self) -> None:
        doi = self._doi(self._row())
        if doi:
            webbrowser.open(f"https://doi.org/{doi}")

    def _open_table(self) -> None:
        tab = self._current()
        if tab is not None:
            open_path(str(tab["path"]))

    def _open_folder(self) -> None:
        open_path(str(self.folder if self.folder.is_dir() else self.folder.parent))
