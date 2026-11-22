# WebScraping/averageScrap/gui/downloads_view.py
"""The Downloads tab of the Web scraping window: every paper of the last download, one line each, in plain words —
downloaded (and from where), not downloaded (why, and what to do), or waiting on a busy site. It reads
download_log.csv of the job's papers folder, the record every download writes, so it shows a run made from the
terminal too, and is filled live while a download runs."""

import os
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from .. import download_log
from ..download_log import GOT, MISSED, WAITING

_FILTERS = ("All", "Downloaded", "Not downloaded", "Waiting")
LAST, EVERY = "Last download", "Every paper tried so far"
_WANTED = {"Downloaded": GOT, "Not downloaded": MISSED, "Waiting": WAITING}
_MARK = {GOT: "✓ downloaded", MISSED: "✗ not downloaded", WAITING: "⏳ waiting"}
_COLUMNS = (("time", "time", 130), ("result", "result", 140), ("title", "title", 340), ("from_or_why", "from / why", 200),
            ("todo", "what to do", 300), ("year", "year", 46), ("journal", "journal", 150))
_EVERY = 1.5  # seconds between two readings of the log while a download runs
INFO = ("ⓘ  Every paper of the last download, one line each: ✓ downloaded and from where, ✗ not downloaded with why and "
        "what to do, ⏳ waiting on a busy site. Double-click a line: the PDF if it was downloaded, else the paper's page. "
        "Every download is kept in download_log.csv of the papers folder.")


class DownloadsView(ttk.Frame):
    """`folder()`: the job's papers folder (None without a job). `missed()`: opens the papers to get by hand."""

    def __init__(self, parent: tk.Misc, folder: Callable[[], Optional[str]], missed: Callable[[], None],
                 tried: Optional[Callable[[], List[Dict[str, str]]]] = None):
        """`tried()`: a line for every paper downloaded or tried so far, from the ledger (“Every paper tried so far”)."""
        from LocalExtraction.gui.widgets import Table, WrapLabel
        super().__init__(parent, padding=(0, 6, 0, 0))
        self.folder, self.tried = folder, tried
        self.rows: Dict[str, Dict[str, str]] = {}
        self._read_at = 0.0
        WrapLabel(self, text=INFO, foreground="#6b7280", justify="left").pack(fill="x", pady=(0, 6))
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 4))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        self.range_var = tk.StringVar(value=LAST)
        span = ttk.Combobox(bar, values=(LAST, EVERY) if tried else (LAST,), textvariable=self.range_var,
                            state="readonly", width=22)
        span.pack(side="left", padx=(0, 8))
        span.bind("<<ComboboxSelected>>", lambda event: self.show(force=True))
        ttk.Label(bar, text="Show").pack(side="left")
        self.filter_var = tk.StringVar(value=_FILTERS[0])
        choice = ttk.Combobox(bar, values=_FILTERS, textvariable=self.filter_var, state="readonly", width=15)
        choice.pack(side="left", padx=4)
        choice.bind("<<ComboboxSelected>>", lambda event: self._fill())
        ttk.Label(bar, text="containing").pack(side="left", padx=(8, 0))
        self.search_var = tk.StringVar()
        contains = ttk.Entry(bar, textvariable=self.search_var, width=18)
        contains.pack(side="left", padx=4)
        contains.bind("<KeyRelease>", lambda event: self._fill())
        ttk.Button(bar, text="Papers to get by hand…", command=missed).pack(side="right")
        ttk.Button(bar, text="Open the log (CSV)", command=self._open_log).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Refresh", command=lambda: self.show(force=True)).pack(side="right", padx=(0, 6))
        self.table = Table(self, _COLUMNS, on_open=self._open, stretch="title")
        self.table.tag(GOT, foreground="#1a7f37")
        self.table.tag(MISSED, foreground="#b3261e")
        self.table.tag(WAITING, foreground="#8c8c8c")
        self.table.pack(fill="both", expand=True)
        self.show(force=True)

    # ------------------------------------------------------------------ reading
    def show(self, force: bool = False) -> None:
        """Reads the log again (at most every _EVERY seconds unless `force`) and shows the last run."""
        if not force and time.monotonic() - self._read_at < _EVERY:
            return
        self._read_at = time.monotonic()
        folder = self.folder()
        if self.range_var.get() == EVERY and self.tried is not None:
            rows = self.tried()
        else:
            rows = download_log.last_run(download_log.read(folder)) if folder else []
        self.rows = {row["key"]: row for row in rows}
        self._fill()

    def _fill(self) -> None:
        wanted = _WANTED.get(self.filter_var.get())
        text = self.search_var.get().strip().lower()
        lines = []
        for key, row in self.rows.items():
            if wanted and row["result"] != wanted:
                continue
            if text and text not in f"{row['title']} {row['journal']} {row['doi']} {row['why']} {row['source']}".lower():
                continue
            from_or_why = (f"from {row['source']}" if row["result"] == GOT else row["why"])
            lines.append((key, [row["time"][:16] if self.range_var.get() == EVERY else row["time"][11:16], _MARK.get(row["result"], row["result"]), row["title"] or row["doi"],
                                from_or_why, row["what_to_do"], row["year"], row["journal"]], (row["result"],)))
        lines.sort(key=lambda line: self.rows[line[0]]["time"], reverse=True)  # the latest first
        self.table.fill(lines)
        self.summary.set(self.summary_text())

    def summary_text(self) -> str:
        if not self.rows:
            return ("No download recorded yet for this job: press “3 · Download”, or choose “Every paper tried so "
                    "far”." if self.range_var.get() == LAST else "No paper of this job has been tried yet.")
        count = {GOT: 0, MISSED: 0, WAITING: 0}
        for row in self.rows.values():
            count[row["result"]] = count.get(row["result"], 0) + 1
        run = next(iter(self.rows.values()))["run"]
        head = "Every paper tried so far" if self.range_var.get() == EVERY else f"Download of {run}"
        return (f"{head}:  {len(self.rows):,} paper(s) tried  ·  ✓ {count[GOT]:,} downloaded  ·  "
                f"✗ {count[MISSED]:,} not downloaded  ·  ⏳ {count[WAITING]:,} waiting")

    # ------------------------------------------------------------------ actions
    def _open(self, key: str) -> None:
        row, folder = self.rows.get(key), self.folder()
        if row is None:
            return
        pdf = os.path.join(folder, row["file"]) if folder and row.get("file") else ""
        if pdf and os.path.isfile(pdf):
            from LocalExtraction.gui.widgets import open_path
            open_path(pdf)
        elif row.get("link"):
            webbrowser.open(row["link"])

    def _open_log(self) -> None:
        folder = self.folder()
        path = download_log.path_of(folder) if folder else ""
        if not path or not os.path.isfile(path):
            messagebox.showinfo("MoukhlijMatExtract", "No download recorded yet for this job.", parent=self)
            return
        from LocalExtraction.gui.widgets import open_path
        open_path(path)

    def selected_results(self) -> List[str]:
        """The result of each line shown (for the tests)."""
        return [self.table.tree.item(item, "values")[1] for item in self.table.tree.get_children()]
