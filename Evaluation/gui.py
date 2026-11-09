# Evaluation/gui.py
"""The Evaluate window of parts 1 and 2: how accurate is the extraction in one results folder?

The program cannot grade its own answers, so the window takes the three steps of `mme-eval`: draw papers at
random into a workbook, let a person mark each extracted value in it (correct / partly / wrong, and the
values missed), then compute precision, recall and F1 from those marks. Each window keeps its own workbook
(Evaluation/annotation_<part>.xlsx) and report (Evaluation/scores_<part>/)."""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

from LocalExtraction.gui import theme
from LocalExtraction.gui.dialogs import Dialog
from LocalExtraction.gui.widgets import WrapLabel, open_path
from LocalExtraction.gui.window import fit_to_screen

from .about import DEFAULT_DIR

_QUIET = "#8c8c8c"
_BOLD = ("TkDefaultFont", 11, "bold")


def workbook_of(part: str) -> Path:
    return DEFAULT_DIR / f"annotation_{part}.xlsx"


def scores_of(part: str) -> Path:
    return DEFAULT_DIR / f"scores_{part}"


def _pct(x: Optional[float]) -> str:
    return "–" if x is None else f"{100 * x:.1f} %"


class EvaluationDialog(Dialog):
    """The three steps for the database in `source`; `part` ("local" or "web") names its workbook."""

    def __init__(self, parent: tk.Misc, source: str, part: str, title: str):
        super().__init__(parent, f"Evaluate — {title}", fit_to_screen(parent, "760x780"))
        theme.apply(self)
        self.source, self.part = Path(source), part
        self.workbook, self.scores = workbook_of(part), scores_of(part)
        self._busy = False
        body = self.body

        WrapLabel(body, text="How accurate is this extraction? The program cannot grade its own answers: a person "
                             "checks the values of a few papers drawn at random, then the scores are computed from "
                             "those checks.").pack(fill="x")
        WrapLabel(body, text=f"Results folder: {self.source}", foreground=_QUIET).pack(fill="x", pady=(2, 10))

        # 1 · Make the Excel file (the "workbook" of mme-eval)
        one = ttk.LabelFrame(body, text=" 1 · Make the Excel file to check ", padding=8)
        one.pack(fill="x")
        row = ttk.Frame(one)
        row.pack(fill="x")
        ttk.Label(row, text="Papers to check:").pack(side="left")
        self.count = tk.IntVar(value=60)
        ttk.Spinbox(row, from_=1, to=1000, width=6, textvariable=self.count).pack(side="left", padx=6)
        self.make_button = ttk.Button(row, text="Make the Excel file", command=self.make)
        self.make_button.pack(side="left", padx=(6, 0))
        drawn = ("your PDFs" if part == "local" else "the papers with a record of a legal copy")
        WrapLabel(one, text=f"Drawn at random among {drawn}; the file lists every value extracted from them. "
                            "10 papers give a quick idea; an article needs 50–60.",
                  foreground=_QUIET).pack(fill="x", pady=(4, 0))

        # 2 · Check the values
        two = ttk.LabelFrame(body, text=" 2 · Check the values — your part ", padding=8)
        two.pack(fill="x", pady=(10, 0))
        WrapLabel(two, text="Open the Excel file (its first sheet, Guide, explains it). For each value, look at the "
                            "paper at the page given and choose correct, partly or wrong; write the values it missed in "
                            "the Missed sheet; write yes under done for each paper you finished; save.").pack(fill="x")
        row = ttk.Frame(two)
        row.pack(fill="x", pady=(6, 0))
        self.open_button = ttk.Button(row, text="Open the Excel file", command=lambda: open_path(str(self.workbook)))
        self.open_button.pack(side="left")
        self.workbook_note = tk.StringVar()
        ttk.Label(row, textvariable=self.workbook_note, foreground=_QUIET).pack(side="left", padx=8)

        # 3 · Score
        three = ttk.LabelFrame(body, text=" 3 · Compute the scores ", padding=8)
        three.pack(fill="both", expand=True, pady=(10, 0))
        row = ttk.Frame(three)
        row.pack(fill="x")
        self.score_button = ttk.Button(row, text="Compute the scores", command=self.score)
        self.score_button.pack(side="left")
        self.report_button = ttk.Button(row, text="Open the report",
                                        command=lambda: open_path(str(self.scores / "report.md")))
        self.report_button.pack(side="left", padx=6)
        self.rescore = tk.BooleanVar(value=False)
        ttk.Checkbutton(three, text="Score the values now in the results folder (after the program changed and the "
                                    "papers were extracted again)", variable=self.rescore).pack(anchor="w", pady=(6, 0))
        self.result = tk.Text(three, height=9, wrap="word", relief="flat", padx=6, pady=4, font=("TkFixedFont", 11))
        self.result.pack(fill="both", expand=True, pady=(6, 0))
        self.result.tag_configure("bold", font=_BOLD)

        self.status = tk.StringVar()
        WrapLabel(body, textvariable=self.status, foreground=_QUIET).pack(fill="x", pady=(8, 0))
        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")
        self._refresh()
        self._show_last_scores()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        has_book = self.workbook.exists()
        has_report = (self.scores / "report.md").exists()
        idle = "disabled" if self._busy else "normal"
        self.make_button.configure(state=idle)
        self.open_button.configure(state="normal" if has_book else "disabled")
        self.score_button.configure(state=idle if has_book else "disabled")
        self.report_button.configure(state="normal" if has_report else "disabled")
        self.workbook_note.set(self.workbook.name if has_book else "no file yet: make it first (step 1)")
        # The step to take next is blue: make the file, then check it, then score it.
        theme.suggest(self.make_button, not has_book)
        theme.suggest(self.open_button, has_book and not has_report)
        theme.suggest(self.score_button, has_book and has_report)

    def _in_background(self, what: str, work: Callable[[], object], done: Callable[[object], None]) -> None:
        """Runs `work` on its own thread (reading the databases and the bootstrap take seconds) and gives its
        result to `done` on the window's thread; an error is shown, not raised."""
        self._busy = True
        self.status.set(what + " …")
        self.configure(cursor="watch")
        self._refresh()
        box: dict = {}

        def run() -> None:
            try:
                box["result"] = work()
            except Exception as error:  # shown in the window
                logging.getLogger(__name__).debug("Evaluation step failed", exc_info=True)
                box["error"] = error

        thread = threading.Thread(target=run, name="mme-evaluation", daemon=True)
        thread.start()
        root = self.master  # waits on the main window: this one may be closed before the step ends

        def wait() -> None:
            if thread.is_alive():
                root.after(100, wait)
                return
            self._busy = False
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            self.configure(cursor="")
            self.status.set("")
            if "error" in box:
                messagebox.showerror("Evaluate", str(box["error"]), parent=self)
            else:
                done(box["result"])
            self._refresh()

        root.after(100, wait)

    # ------------------------------------------------------------------
    def make(self) -> None:
        from .steps import keep_old, make_sheet
        try:
            count = int(self.count.get())
        except (tk.TclError, ValueError):
            count = 0
        if count < 1:
            messagebox.showerror("Evaluate", "The number of papers must be 1 or more.", parent=self)
            return
        if not (self.source / "papers.csv").exists():
            messagebox.showerror("Evaluate", f"There is no database in {self.source} yet: extract papers first.",
                                 parent=self)
            return
        if self.workbook.exists():
            if not messagebox.askyesno(
                    "Evaluate", "An Excel file is already there, and it may hold your checks.\n\nMake a new one? The "
                    "old one is kept next to it, with the date in its name.", parent=self):
                return

        def work():
            kept = keep_old(self.workbook) if self.workbook.exists() else None
            self.workbook.parent.mkdir(parents=True, exist_ok=True)
            # The PDFs of part 1 are the user's own; the web ones are drawn only with a record of a legal copy.
            return kept, make_sheet([self.source], self.workbook, papers=count, legal_only=self.part != "local")

        def done(result) -> None:
            kept, counts = result
            lines = [f"{counts['papers']} papers drawn, {counts['values']} extracted values to check."]
            if counts["without_values"]:
                lines.append(f"Papers with no value extracted: {counts['without_values']} (the values you find in them "
                             "count as missed).")
            if counts["papers"] < count:
                lines.append(f"Only {counts['papers']} papers could be drawn.")
            if counts.get("left_out"):
                lines.append(f"{counts['left_out']} paper(s) without a record of a legal copy were not drawn.")
            if kept:
                lines.append(f"The old file is kept as {kept.name}.")
            lines.append("Next: open the Excel file and check the values (step 2).")
            self._write("Excel file made", "\n".join(lines))

        self._in_background("Drawing the papers and writing the Excel file", work, done)

    def score(self) -> None:
        from .steps import score_sheet
        sources = [self.source] if self.rescore.get() else None
        self._in_background("Computing the scores", lambda: score_sheet(self.workbook, self.scores, sources),
                            lambda result: self._show_scores(result[0], result[2].warnings))

    # ------------------------------------------------------------------
    def _write(self, title: str, text: str) -> None:
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("end", title + "\n", "bold")
        self.result.insert("end", text)
        self.result.configure(state="disabled")

    def _show_scores(self, metrics: dict, warnings=()) -> None:
        from .steps import summary_rows
        rows = summary_rows(metrics)
        width = max([22] + [len(row[0]) for row in rows]) + 2
        lines = [f"{metrics['papers']} papers checked: {metrics['gold']} values in them, {metrics['extracted']} extracted.",
                 "", f"{'':{width}}{'precision':>11}{'recall':>9}{'F1':>9}"]
        lines += [f"{name:{width}}{_pct(p):>11}{_pct(r):>9}{_pct(f):>9}" for name, p, r, f in rows]
        lines += ["", "precision: of the values extracted, the share that is right · recall: of the values in the "
                      "papers, the share extracted · record: the right value for the right material · value: the "
                      "right value. The report has the 95 % intervals and every error."]
        if warnings:
            lines += ["", f"{len(warnings)} warning(s) — see the report, e.g.: {warnings[0]}"]
        self._write("Scores", "\n".join(lines))

    def _show_last_scores(self) -> None:
        """The scores of the last time, when there are any: the window opens on them."""
        path = self.scores / "metrics.json"
        if not path.exists():
            self._write("No scores yet", "Make the Excel file (1), check the values in it (2), then compute the "
                                         "scores (3).")
            return
        try:
            import json
            with open(path, encoding="utf-8") as f:
                self._show_scores(json.load(f))
        except (OSError, ValueError, KeyError) as error:
            logging.getLogger(__name__).debug("Could not read %s: %s", path, error)


def evaluate_button(parent: tk.Misc, source: Callable[[], str], part: str, title: str) -> ttk.Button:
    """The “Evaluate…” button of a part's window: opens the evaluation of the results folder `source()` gives."""
    return ttk.Button(parent, text="Evaluate…",
                      command=lambda: EvaluationDialog(parent, os.path.abspath(source()), part, title))
