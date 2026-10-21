# LocalExtraction/gui/panel.py
"""The articles on this computer. A folder of PDFs is read with LocalExtraction.cli.run_extraction —
what `python -m LocalExtraction` runs — and its activation energies are shown as they land in the database."""

import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, List, Optional

from ..cli import run_extraction
from ..models import PaperData
from .results import EnergiesView, pending_pdfs
from .summary import final_summary, summarize_paper
from .widgets import FolderRow, LogPane, Stopped, WrapLabel

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

        self.folder = FolderRow(self, "Folder of PDFs:", input_dir, label_width=15)
        self.folder.pack(fill="x")
        self.output = FolderRow(self, "Results folder:", output_dir, label_width=15, on_change=self.show_results)
        self.output.pack(fill="x", pady=(4, 0))
        WrapLabel(self, text="Reads the PDFs of the first folder that the results do not hold yet (not its sub-folders).",
                  foreground="#666666").pack(fill="x", pady=(2, 8))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="Start extraction", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(buttons, mode="determinate", length=150)
        self.progress.pack(side="right", padx=(8, 0))
        self.status = tk.StringVar(value="Idle.")
        WrapLabel(buttons, textvariable=self.status, wraplength=220).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Frame(self, height=6).pack(fill="x")

        self.book = ttk.Notebook(self)
        self.book.pack(fill="both", expand=True)
        self.energies = EnergiesView(self.book, app, self.output.get)
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
        folder = self.folder.get()
        if not os.path.isdir(folder):
            messagebox.showerror("MoukhlijMatExtract", f"This folder does not exist:\n{folder}", parent=self)
            return
        output = self.output.get()
        if not self.app.ready_to_extract(output):
            return
        self._total, self._done, self._papers = pending_pdfs(folder, output), 0, []
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
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
            self.activity.write(f"[FAILED] {filename}")
            return
        self._papers.append(paper)
        self.activity.write(f"[DONE] {filename}\n{summarize_paper(paper)}")

    def _summed_up(self, code: int) -> None:
        self.activity.write(final_summary(self._papers) if code == 0 and self._total
                            else "Nothing new to read." if code == 0 else "The extraction did not run: see the log below.")

    def _finished(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set("Stopped." if self.stop_event.is_set() else "Idle.")
        self.app.database_changed()
        if self._papers:
            self.book.select(self.energies)

    def close(self) -> None:
        """Nothing is held open between two extractions."""

    def stop(self) -> None:
        if self.running():
            # The PDFs being read are finished (their work is not thrown away); the queued ones are dropped.
            self.stop_event.set()
            self.status.set("Stopping — the PDFs being read are finished first …")
            self.stop_button.configure(state="disabled")
