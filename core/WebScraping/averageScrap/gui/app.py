# WebScraping/gui/app.py
"""The window of Project 2: a job, its candidates to review, the downloads and the extraction into
a folder of results — in the frame of the window of Project 1 (LocalExtraction/gui/window.py).

    python -m WebScraping gui"""

import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

from LocalExtraction.gui.window import Window

from ..about import DEFAULT_JOB
from ..job import load_env
from .dialogs import SettingsDialog
from .panel import WebPanel


class App(Window):
    def __init__(self, root: tk.Tk, job_path: str = "", output_dir: str = "", workers: int = 4):
        """`output_dir` "": the results folder of the job chosen (about.output_for), following it when another is."""
        self._job_path, self._output_dir = job_path, output_dir
        super().__init__(root, "MoukhlijMatExtract (MME) · Web scraping",
                         "search the literature, download the legal copies, extract them", workers,
                         size="1280x860", minsize=(960, 760))  # at 600 high the tabs had no room left

    def header_buttons(self, bar: ttk.Frame) -> None:
        from LocalExtraction.gui.csv_browser import results_buttons
        ttk.Button(bar, text="API keys…", command=self._settings).pack(side="right")
        ttk.Button(bar, text="Coverage…", command=self._coverage).pack(side="right", padx=(0, 6))
        results_buttons(bar, "2 · Web scraping", lambda: self.panel.output.get(), extra=lambda: self.panel.results_extra())

    def build_panel(self, parent: tk.Misc) -> ttk.Frame:
        return WebPanel(parent, self, self._job_path, self._output_dir)

    def _coverage(self) -> None:
        from .dialogs import CoverageDialog  # every job's ledger read, the report written
        CoverageDialog(self.root)

    def _settings(self) -> None:
        from LocalExtraction.gui.single import open_once  # one API keys window: asked again, it comes back
        open_once("api-keys", "The API keys window", self.root,
                  lambda: SettingsDialog(self.root, on_saved=self.panel.settings_changed))

    def open_keys(self) -> None:
        """The "API keys…" window (the contact e-mail is its first card)."""
        self._settings()


def main(job_path: Optional[str] = None, output_dir: str = "", workers: int = 4) -> None:
    load_env()  # the keys and the contact address, from ~/MoukhlijMatExtract/.env
    if job_path is None:
        job_path = DEFAULT_JOB if os.path.exists(DEFAULT_JOB) else ""
    root = tk.Tk()
    from LocalExtraction.crashlog import watch
    watch(root)  # a window's own errors: written to a crash file, and said
    App(root, job_path, output_dir, workers)
    from LocalExtraction.crashlog import run
    run(root)  # the loop, then the window closed cleanly
