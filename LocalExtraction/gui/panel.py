# LocalExtraction/gui/panel.py
"""The articles on this computer. A folder of PDFs is read with LocalExtraction.cli.run_extraction —
what `python -m LocalExtraction` runs — and its activation energies are shown as they land in the database."""

import logging
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, List, Optional

from .. import outputs
from ..cli import run_extraction
from ..models import PaperData
from .delete_outputs import delete_outputs_button
from .outcomes import extraction_outcome, snapshot
from .result_card import ResultCard
from .results import EnergiesView, pending_pdfs
from .summary import final_summary, summarize_paper
from .widgets import LogPane, Stopped, WrapLabel, open_path

if TYPE_CHECKING:
    from .window import Window


class LocalPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: "Window", input_dir: str, output_dir: str):
        super().__init__(parent, text=" Local articles — the PDFs on this computer ", padding=10)
        self.app = app
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._papers: List[PaperData] = []
        self._done = self._total = 0

        self.input_dir, self.output_dir = os.path.abspath(input_dir), os.path.abspath(output_dir)
        folders = ttk.Frame(self)
        folders.pack(fill="x")
        ttk.Label(folders, text="Folder of PDFs:", width=15).grid(row=0, column=0, sticky="w")
        ttk.Label(folders, text=self.input_dir).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(folders, text="Open", width=6, command=lambda: open_path(self.input_dir)).grid(row=0, column=2)
        ttk.Label(folders, text="Results folder:", width=15).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(folders, text=self.output_dir).grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        folders.columnconfigure(1, weight=1)
        WrapLabel(self, text="Put your PDFs in the first folder. Reads the ones the results do not hold yet "
                             "(not its sub-folders).", foreground="#8c8c8c").pack(fill="x", pady=(2, 8))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="Start extraction", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.delete_button = delete_outputs_button(buttons, "local", after=self._outputs_deleted)
        self.delete_button.pack(side="left")
        outputs.register("local", self.running, "an extraction is running")
        self.progress = ttk.Progressbar(buttons, mode="determinate", length=150)
        self.progress.pack(side="right", padx=(8, 0))
        self.status = tk.StringVar(value="Idle.")
        WrapLabel(buttons, textvariable=self.status, wraplength=220).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Frame(self, height=6).pack(fill="x")

        self.book = ttk.Notebook(self)
        self.card = ResultCard(self, before=self.book)  # what the last run did, above the tables
        self.book.pack(fill="both", expand=True)
        self.energies = EnergiesView(self.book, app, lambda: self.output_dir)
        self.book.add(self.energies, text="Activation energies")
        self.activity = LogPane(self.book, height=14)
        self.book.add(self.activity, text="Activity")

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def show_results(self) -> None:
        self.energies.show()

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.running():
            return
        folder, output = self.input_dir, self.output_dir
        if not os.path.isdir(folder):
            messagebox.showerror("MoukhlijMatExtract", f"This folder does not exist:\n{folder}", parent=self)
            return
        if not self.app.ready_to_extract(output):
            return
        self._total, self._done, self._papers = pending_pdfs(folder, output), 0, []
        self._failed, self._started, self._before = 0, time.time(), snapshot(output)
        self.card.hide()
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.delete_button.configure(state="disabled")
        self.progress.configure(maximum=max(self._total, 1), value=0)
        self.status.set(f"Reading {self._total} new PDF(s) …" if self._total else "Nothing new in this folder.")
        self.activity.write(f"--- Extraction of {folder} into {output}: {self._total} new PDF(s)")
        self.book.select(self.activity)
        self._thread = threading.Thread(target=self._work, args=(folder, output, self.app.workers()), daemon=True)
        self._thread.start()

    def _work(self, folder: str, output: str, workers: int) -> None:
        """On its own thread: everything it wants shown goes through app.post."""
        try:
            with self.app.writing("Local extraction", output, self.stop_event):
                code = run_extraction(folder, output, max_workers=workers, stop_event=self.stop_event,
                                      progress_callback=lambda name, paper: self.app.post(self._paper_done, name, paper))
            self.app.post(self._summed_up, code)
        except Stopped:
            self.app.post(self.activity.write, "Stopped before it started.")
        except Exception as error:  # the window must survive a failed run
            logging.getLogger(__name__).exception("The local extraction failed")
            self.app.post(self.activity.write, f"The extraction failed: {type(error).__name__}: {error}")
        finally:
            self.app.post(self._finished)

    def _paper_done(self, filename: str, paper: Optional[PaperData]) -> None:
        self._done += 1
        self.progress.configure(value=self._done)
        self.status.set(f"{self._done} / {self._total} — {filename}")
        if paper is None:
            self._failed += 1
            self.activity.write(f"[FAILED] {filename}")
            return
        self._papers.append(paper)
        self.activity.write(f"[DONE] {filename}\n{summarize_paper(paper)}")

    def _summed_up(self, code: int) -> None:
        self.activity.write(final_summary(self._papers) if code == 0 and self._total
                            else "Nothing new to read." if code == 0 else "The extraction did not run: see the log below.")

    def _outputs_deleted(self, deleted: bool) -> None:
        if deleted:
            self._papers = []
            self.activity.write("--- Outputs deleted: the database is empty; the next extraction reads every PDF.")
            self.app.database_changed()

    def _finished(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.delete_button.configure(state="normal")
        self.status.set("Stopped." if self.stop_event.is_set() else "Idle.")
        self.app.database_changed()
        if self._papers:
            self.book.select(self.energies)
        self.show_outcome()

    def show_outcome(self) -> None:
        """The card of the run that just ended: what it added to the database, and where to go next."""
        output = self.output_dir
        workbook = os.path.join(output, "database.xlsx")
        actions = [("Show the activation energies", lambda: self.book.select(self.energies)),
                   ("Open the workbook", lambda: open_path(workbook) if os.path.exists(workbook) else None),
                   ("Open the results folder", lambda: open_path(output)),
                   ("Show the log", lambda: self.book.select(self.activity))]
        stopped = self.stop_event.is_set()
        self.card.show(extraction_outcome(output, getattr(self, "_before", set()), failed=getattr(self, "_failed", 0),
                                          stopped=stopped, started=getattr(self, "_started", None),
                                          pdfs_pending=pending_pdfs(self.input_dir, output) if stopped else None,
                                          actions=actions))

    def close(self) -> None:
        """Nothing is held open between two extractions."""

    def stop(self) -> None:
        if self.running():
            # The PDFs being read are finished (their work is not thrown away); the queued ones are dropped.
            self.stop_event.set()
            self.status.set("Stopping — the PDFs being read are finished first …")
            self.stop_button.configure(state="disabled")
