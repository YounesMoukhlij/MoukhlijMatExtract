# LocalExtraction/gui/csv_browser.py
"""Every CSV file of a part's results folder, in a window that stays quick however big the files are.

On the left, every .csv file of the folder and of its subfolders (and the part's other files, such as
the web scraping's review list and DOI list), with its size and date. Pick one: it is read on a
working thread — the window never waits for it — and shown a page at a time (first, previous, next,
last, or straight to a row), so a file of a million rows is browsed as quickly as one of ten. A search
over every column and a sort by any column (click its heading) run on a working thread too. Every
cell of the selected row is shown in full below. The files are only read: nothing here changes them.

    results_buttons(bar, "1 · Local extraction", lambda: output_folder)   # the two buttons of a window
    CsvBrowser(parent, "1 · Local extraction", folder)                     # the window itself"""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .widgets import WrapLabel, open_path

PAGE_SIZES = (100, 500, 1000, 5000)
_DEFAULT_PAGE = 500
_CHUNK_ROWS = 200_000      # rows read at a time from a big file (the window says how far it is)
_POLL_MS = 60              # how often the window looks at what the working threads sent it
_QUIET = "#8c8c8c"


# ----------------------------------------------------------------------
# The two buttons of a part's window
# ----------------------------------------------------------------------
def results_buttons(bar: tk.Misc, part: str, folder: Callable[[], str],
                    extra: Optional[Callable[[], Sequence[Tuple[str, str]]]] = None,
                    side: str = "right") -> Tuple[ttk.Button, ttk.Button]:
    """"Open the results folder" and "Browse the CSV files…", packed in `bar`. `folder` gives the part's
    results folder when a button is pressed (it may change: a folder chosen in the window); `extra`
    gives the part's other files to list, as (name, path)."""
    window = bar.winfo_toplevel()

    def open_folder() -> None:
        path = Path(folder()).expanduser()
        if path.is_dir():
            open_path(str(path))
        else:
            messagebox.showinfo("MoukhlijMatExtract", f"There is no results folder yet ({path}): run {part} first.",
                                parent=window)

    def browse() -> None:
        path = Path(folder()).expanduser()
        files = [(label, Path(p)) for label, p in (extra() if extra else [])]
        if not path.is_dir() and not any(p.is_file() for _, p in files):
            messagebox.showinfo("MoukhlijMatExtract", f"There is no results folder yet ({path}): run {part} first.",
                                parent=window)
            return
        CsvBrowser(window, part, path, files)

    browse_button = ttk.Button(bar, text="Browse the CSV files…", command=browse)
    open_button = ttk.Button(bar, text="Open the results folder", command=open_folder)
    if side == "right":  # packed from the right: the open button ends up on the left of the browse one
        browse_button.pack(side="right", padx=(6, 0))
        open_button.pack(side="right", padx=(6, 0))
    else:
        open_button.pack(side=side, padx=(6, 0))
        browse_button.pack(side=side, padx=(6, 0))
    return open_button, browse_button


# ----------------------------------------------------------------------
# Reading, searching and sorting a file — on working threads
# ----------------------------------------------------------------------
def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} GB"


def csv_files(folder: Path) -> List[Path]:
    """Every .csv file under a folder (hidden folders and backups left out), in path order."""
    found: List[Path] = []
    if not folder.is_dir():
        return found
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        found += [Path(root) / name for name in sorted(files) if name.lower().endswith(".csv") and not name.startswith(".")]
    return found


def read_csv(path: Path, progress: Callable[[int], None], cancelled: Callable[[], bool]):
    """The whole file as text (every cell a string, nothing guessed), read by chunks so that a big file
    reports how far it is and can be given up when another one is picked. None when given up."""
    import pandas as pd
    attempts = (dict(encoding="utf-8-sig"), dict(encoding="cp1252"),
                dict(encoding="utf-8-sig", sep=None, engine="python"))
    last_error: Optional[Exception] = None
    for options in attempts:
        try:
            options = {"dtype": str, "keep_default_na": False, "na_filter": False, "on_bad_lines": "skip", **options}
            if options.get("engine") == "python":  # the separator guessed (";" of a French spreadsheet, a tab)
                return pd.read_csv(path, **options)
            chunks, rows = [], 0
            for chunk in pd.read_csv(path, chunksize=_CHUNK_ROWS, low_memory=False, **options):
                if cancelled():
                    return None
                chunks.append(chunk)
                rows += len(chunk)
                progress(rows)
            if not chunks:
                return pd.read_csv(path, nrows=0, **options)  # a header only
            return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error
            continue
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    raise ValueError(f"cannot be read as CSV: {last_error}")


def search(data, text: str):
    """The positions of the rows holding `text` (in any column, case ignored)."""
    import numpy as np
    needle = text.casefold()
    hit = np.zeros(len(data), dtype=bool)
    for column in data.columns:
        hit |= data[column].str.casefold().str.contains(needle, regex=False, na=False).to_numpy()
    return np.flatnonzero(hit)


def sort_order(data, rows, column: str, descending: bool):
    """`rows` (positions) ordered by a column: as numbers when it holds numbers, else as text; the empty
    cells last either way."""
    import numpy as np
    import pandas as pd
    values = data[column].iloc[rows]
    numbers = pd.to_numeric(values, errors="coerce")
    empty = (values.str.strip() == "").to_numpy()
    if numbers.notna().sum() >= max(1, int(0.8 * (~empty).sum())):  # a column of numbers
        keys = numbers.to_numpy(dtype=float)
        keys = np.where(np.isnan(keys), np.inf, -keys if descending else keys)
        order = np.argsort(keys, kind="stable")
    else:
        text = values.str.casefold().to_numpy()
        order = np.argsort(text, kind="stable")
        if descending:
            order = order[::-1]
        order = np.concatenate([order[~empty[order]], order[empty[order]]])
    return np.asarray(rows)[order]


# ----------------------------------------------------------------------
# The window
# ----------------------------------------------------------------------
class CsvBrowser(tk.Toplevel):
    """The CSV files of a folder: the list on the left, the file picked on the right, a page at a time."""

    def __init__(self, parent: tk.Misc, part: str, folder: Path, extra: Sequence[Tuple[str, Path]] = ()):
        super().__init__(parent)
        self.folder, self.part, self.extra = Path(folder), part, [(label, Path(p)) for label, p in extra]
        self.title(f"CSV files — {part}")
        from . import layout
        layout.place(self, (1280, 820), (760, 480), parent=parent)  # fitted to the screen, centred
        self.bind("<Escape>", lambda e: self.destroy())

        self._inbox: "queue.Queue[Tuple[int, str, object]]" = queue.Queue()
        # What the working threads did is kept only for the latest request. They are handed this list and
        # the inbox, never the window: a thread must not be the one to free a window (Tk forbids it).
        self._latest = [0]
        self._data = None             # the file shown (a pandas DataFrame of strings)
        self._path: Optional[Path] = None
        self._rows = None             # the positions shown, in order (all of them, or those found)
        self._page = 0
        self._sorted: Optional[Tuple[str, bool]] = None
        self._files: Dict[str, Path] = {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        from .design import website_line
        website_line(self)
        ttk.Label(body, text=f"{part} — the CSV files of the results", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        self.headline = tk.StringVar()
        WrapLabel(body, textvariable=self.headline, foreground=_QUIET, justify="left").pack(fill="x", pady=(2, 8))

        sides = ttk.PanedWindow(body, orient="horizontal")
        sides.pack(fill="both", expand=True)

        # On the left: the files.
        left = ttk.Frame(sides)
        sides.add(left, weight=0)
        self.files = ttk.Treeview(left, columns=("size", "date"), show="tree headings", selectmode="browse")
        self.files.heading("#0", text="File", anchor="w")
        self.files.heading("size", text="Size", anchor="e")
        self.files.heading("date", text="Changed", anchor="w")
        self.files.column("#0", width=260, stretch=True)
        self.files.column("size", width=80, anchor="e", stretch=False)
        self.files.column("date", width=110, stretch=False)
        files_bar = ttk.Scrollbar(left, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=files_bar.set)
        self.files.pack(side="left", fill="both", expand=True)
        files_bar.pack(side="right", fill="y")
        self.files.bind("<<TreeviewSelect>>", lambda e: self._pick())

        # On the right: the search, the rows of a page, the pages, the row in full.
        right = ttk.Frame(sides, padding=(10, 0, 0, 0))
        sides.add(right, weight=1)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        ttk.Label(bar, text="Search in every column").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda e: self._search())
        ttk.Button(bar, text="Search", command=self._search).pack(side="left")
        ttk.Button(bar, text="Clear", command=self._clear_search).pack(side="left", padx=(6, 0))
        self.status = tk.StringVar(value="Pick a file on the left.")
        ttk.Label(right, textvariable=self.status, foreground=_QUIET).pack(fill="x", pady=(6, 4))

        panes = ttk.PanedWindow(right, orient="vertical")
        panes.pack(fill="both", expand=True)
        grid = ttk.Frame(panes)
        panes.add(grid, weight=5)
        self.table = ttk.Treeview(grid, show="headings", selectmode="browse")
        down = ttk.Scrollbar(grid, orient="vertical", command=self.table.yview)
        across = ttk.Scrollbar(grid, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", lambda e: self._show_row())
        from .design import stripes
        stripes(self.table)

        cell = ttk.Frame(panes)
        panes.add(cell, weight=1)
        self.details = tk.Text(cell, height=7, wrap="word", relief="flat", padx=8, pady=6, state="disabled")
        self.details.tag_configure("name", foreground=_QUIET)
        details_bar = ttk.Scrollbar(cell, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=details_bar.set)
        self.details.pack(side="left", fill="both", expand=True)
        details_bar.pack(side="right", fill="y")

        pages = ttk.Frame(right)
        pages.pack(fill="x", pady=(6, 0))
        self.first_button = ttk.Button(pages, text="⏮ First", command=lambda: self._go(0))
        self.first_button.pack(side="left")
        self.previous_button = ttk.Button(pages, text="◀ Previous", command=lambda: self._go(self._page - 1))
        self.previous_button.pack(side="left", padx=(6, 0))
        self.page_text = tk.StringVar()
        ttk.Label(pages, textvariable=self.page_text, width=22, anchor="center").pack(side="left", padx=6)
        self.next_button = ttk.Button(pages, text="Next ▶", command=lambda: self._go(self._page + 1))
        self.next_button.pack(side="left")
        self.last_button = ttk.Button(pages, text="Last ⏭", command=lambda: self._go(self._pages() - 1))
        self.last_button.pack(side="left", padx=(6, 0))
        ttk.Label(pages, text="Go to row").pack(side="left", padx=(16, 4))
        self.row_var = tk.StringVar()
        row_entry = ttk.Entry(pages, textvariable=self.row_var, width=9)
        row_entry.pack(side="left")
        row_entry.bind("<Return>", lambda e: self._go_to_row())
        ttk.Label(pages, text="Rows per page").pack(side="left", padx=(16, 4))
        self.page_size = tk.StringVar(value=str(_DEFAULT_PAGE))
        sizes = ttk.Combobox(pages, textvariable=self.page_size, values=[str(n) for n in PAGE_SIZES], width=6,
                             state="readonly")
        sizes.pack(side="left")
        sizes.bind("<<ComboboxSelected>>", lambda e: self._go(0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        self.open_file_button = ttk.Button(buttons, text="Open this file", command=self._open_file)
        self.open_file_button.pack(side="left")
        ttk.Button(buttons, text="Open the results folder", command=self._open_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Refresh the list", command=self.list_files).pack(side="right", padx=6)

        self._pages_buttons(False)
        self.list_files()
        self.after(_POLL_MS, self._poll)

    # ------------------------------------------------------------------
    # The list of files
    # ------------------------------------------------------------------
    def list_files(self) -> None:
        """Lists the files again (a step may have written new ones since)."""
        self.files.delete(*self.files.get_children())
        self._files.clear()
        folders: Dict[str, str] = {}
        total, count = 0, 0
        for path in csv_files(self.folder):
            relative = path.relative_to(self.folder)
            parent = ""
            for depth in range(len(relative.parts) - 1):  # one branch per subfolder
                key = "/".join(relative.parts[:depth + 1])
                if key not in folders:
                    folders[key] = self.files.insert(folders.get("/".join(relative.parts[:depth]), ""), "end",
                                                     text=f"📁 {relative.parts[depth]}", open=depth == 0)
                parent = folders[key]
            count, total = count + 1, total + self._add_file(parent, relative.name, path)
        others = [(label, path) for label, path in self.extra if path.is_file()]
        if others:
            branch = self.files.insert("", "end", text="Other files of this part", open=True)
            for label, path in others:
                count, total = count + 1, total + self._add_file(branch, f"{label} ({path.name})", path)
        if not count:
            self.headline.set(f"No CSV file yet in {self.folder}: run this part first.")
        else:
            self.headline.set(f"{count} CSV file{'s' if count != 1 else ''} ({_size(total)}) in {self.folder}"
                              + (" and beside it" if others else "") + ". Pick one: it is read without holding the "
                              "window, then shown a page at a time; search in every column, click a heading to sort, "
                              "select a row to see it in full.")

    def _add_file(self, parent: str, name: str, path: Path) -> int:
        try:
            stat = path.stat()
        except OSError:
            return 0
        item = self.files.insert(parent, "end", text=name, values=(
            _size(stat.st_size), time.strftime("%d %b %Y %H:%M", time.localtime(stat.st_mtime))))
        self._files[item] = path
        return stat.st_size

    # ------------------------------------------------------------------
    # A file picked: read on a working thread
    # ------------------------------------------------------------------
    def _pick(self) -> None:
        chosen = self.files.selection()
        path = self._files.get(chosen[0]) if chosen else None
        if path is None or path == self._path:
            return
        job = self._next_job()
        self._path, self._data, self._rows, self._page, self._sorted = path, None, None, 0, None
        self.query.set("")
        self._clear_table()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.status.set(f"Reading {path.name} ({_size(size)}) …")
        self._pages_buttons(False)

        inbox, latest = self._inbox, self._latest

        def work() -> None:
            try:
                data = read_csv(path, lambda rows: inbox.put((job, "progress", rows)), lambda: job != latest[0])
                if data is not None:
                    inbox.put((job, "loaded", data))
            except Exception as error:  # the window must survive a file it cannot read
                inbox.put((job, "failed", f"{type(error).__name__}: {error}"))
        threading.Thread(target=work, daemon=True).start()

    def _next_job(self) -> int:
        self._latest[0] += 1
        return self._latest[0]

    def _poll(self) -> None:
        """What the working threads sent: kept only when it answers the latest request."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            while True:
                job, kind, value = self._inbox.get_nowait()
                if job != self._latest[0]:
                    continue
                if kind == "progress":
                    self.status.set(f"Reading {self._path.name} … {value:,} rows so far")
                elif kind == "loaded":
                    self._loaded(value)
                elif kind == "failed":
                    self.status.set(f"{self._path.name} {value}")
                elif kind == "rows":
                    rows, what = value
                    self._rows, self._page = rows, 0
                    self.status.set(what)
                    self._show_page()
        except queue.Empty:
            pass
        self.after(_POLL_MS, self._poll)

    def _loaded(self, data) -> None:
        import numpy as np
        self._data = data
        self._rows = np.arange(len(data))
        columns = [str(c) for c in data.columns]
        self.table.configure(columns=[f"c{i}" for i in range(len(columns))])
        sample = data.head(200)
        for i, name in enumerate(columns):
            longest = max([len(name)] + [len(str(v)) for v in sample.iloc[:, i]]) if len(sample) else len(name)
            self.table.heading(f"c{i}", text=name, anchor="w", command=lambda n=name: self._sort(n))
            self.table.column(f"c{i}", width=max(70, min(380, 8 * longest + 16)), stretch=False, anchor="w")
        self.status.set(f"{self._path.name}: {len(data):,} rows · {len(columns)} columns")
        self._show_page()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _per_page(self) -> int:
        try:
            return max(1, int(self.page_size.get()))
        except ValueError:
            return _DEFAULT_PAGE

    def _pages(self) -> int:
        count = 0 if self._rows is None else len(self._rows)
        return max(1, -(-count // self._per_page()))

    def _go(self, page: int) -> None:
        if self._rows is None:
            return
        self._page = min(max(0, page), self._pages() - 1)
        self._show_page()

    def _go_to_row(self) -> None:
        """Straight to a row of the file (its number, from 1), among those shown."""
        if self._rows is None:
            return
        try:
            wanted = int(self.row_var.get().replace(",", "").strip()) - 1
        except ValueError:
            return
        import numpy as np
        where = np.flatnonzero(self._rows == wanted)
        if not len(where):
            self.status.set(f"Row {wanted + 1:,} is not among the rows shown (a search may hide it).")
            return
        self._page = int(where[0]) // self._per_page()
        self._show_page(select=str(wanted))

    def _show_page(self, select: str = "") -> None:
        self._clear_table()
        if self._data is None or self._rows is None:
            return
        per = self._per_page()
        start = self._page * per
        chosen = self._rows[start:start + per]
        page = self._data.iloc[chosen]
        for row, (position, values) in enumerate(zip(chosen, page.itertuples(index=False, name=None))):
            self.table.insert("", "end", iid=str(int(position)), values=[str(v) for v in values],
                              tags=("stripe",) if row % 2 else ())
        shown = len(self._rows)
        self.page_text.set(f"page {self._page + 1:,} of {self._pages():,}")
        if shown:
            sorted_by = f" · sorted by {self._sorted[0]} ({'↓' if self._sorted[1] else '↑'})" if self._sorted else ""
            what = (f"found {shown:,} of {len(self._data):,} rows" if shown != len(self._data)
                    else f"{len(self._data):,} rows")
            self.status.set(f"{self._path.name}: {what} · {len(self._data.columns)} columns · rows "
                            f"{start + 1:,}–{start + len(chosen):,} shown{sorted_by}")
        self._pages_buttons(True)
        if select and self.table.exists(select):
            self.table.selection_set(select)
            self.table.see(select)

    def _pages_buttons(self, on: bool) -> None:
        first_page = self._page == 0
        last_page = self._rows is None or self._page >= self._pages() - 1
        for button, usable in ((self.first_button, on and not first_page), (self.previous_button, on and not first_page),
                               (self.next_button, on and not last_page), (self.last_button, on and not last_page)):
            button.configure(state="normal" if usable else "disabled")
        self.open_file_button.configure(state="normal" if self._path is not None else "disabled")

    def _clear_table(self) -> None:
        self.table.delete(*self.table.get_children())
        self._show_row()

    # ------------------------------------------------------------------
    # Search and sort, on a working thread
    # ------------------------------------------------------------------
    def _in_background(self, what: str, compute: Callable[[], Tuple[object, str]]) -> None:
        job = self._next_job()
        self.status.set(what)
        self._pages_buttons(False)
        inbox = self._inbox

        def work() -> None:
            try:
                inbox.put((job, "rows", compute()))
            except Exception as error:
                inbox.put((job, "failed", f"{type(error).__name__}: {error}"))
        threading.Thread(target=work, daemon=True).start()

    def _search(self) -> None:
        if self._data is None:
            return
        text = self.query.get().strip()
        data, sorted_by = self._data, self._sorted
        if not text:
            self._clear_search()
            return

        def compute():
            import numpy as np
            rows = search(data, text)
            if sorted_by:
                rows = sort_order(data, rows, *sorted_by)
            return np.asarray(rows), ("" if len(rows) else f"No row holds “{text}”.")
        self._in_background(f"Searching “{text}” in {len(data):,} rows …", compute)

    def _clear_search(self) -> None:
        if self._data is None:
            return
        self.query.set("")
        data, sorted_by = self._data, self._sorted

        def compute():
            import numpy as np
            rows = np.arange(len(data))
            return (sort_order(data, rows, *sorted_by) if sorted_by else rows), ""
        self._in_background("Showing every row …", compute)

    def _sort(self, column: str) -> None:
        if self._data is None or self._rows is None:
            return
        descending = bool(self._sorted and self._sorted[0] == column and not self._sorted[1])
        self._sorted = (column, descending)
        data, rows = self._data, self._rows
        self._in_background(f"Sorting {len(rows):,} rows by {column} …",
                            lambda: (sort_order(data, rows, column, descending), ""))

    # ------------------------------------------------------------------
    # The row in full, and the files
    # ------------------------------------------------------------------
    def _show_row(self) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        chosen = self.table.focus() or next(iter(self.table.selection()), "")
        if chosen and self._data is not None:
            row = self._data.iloc[int(chosen)]
            self.details.insert("end", f"row {int(chosen) + 1:,} of {self._path.name}\n", "name")
            for name, value in row.items():
                if str(value).strip():
                    self.details.insert("end", f"{name}: ", "name")
                    self.details.insert("end", f"{value}\n")
        self.details.configure(state="disabled")

    def _open_file(self) -> None:
        if self._path is not None:
            open_path(str(self._path))

    def _open_folder(self) -> None:
        open_path(str(self.folder if self.folder.is_dir() else self.folder.parent))
