# WebScraping/gui/app.py
"""The window of Project 2: a job, its candidates to review, the downloads and the extraction into
a folder of results — in the frame of the window of Project 1 (LocalExtraction/gui/window.py).

    python -m WebScraping gui"""

import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

from LocalExtraction.gui.window import Window

from ..about import DEFAULT_JOB, DEFAULT_OUTPUT
from ..job import load_env
from .dialogs import SettingsDialog
from .panel import WebPanel


class App(Window):
    def __init__(self, root: tk.Tk, job_path: str = "", output_dir: str = DEFAULT_OUTPUT, workers: int = 4):
        self._job_path, self._output_dir = job_path, output_dir
        super().__init__(root, "MoukhlijMatExtract (MME) · Web scraping",
                         "search the literature, download the legal copies, extract them", workers,
                         size="1280x860", minsize=(1000, 660))

    def header_buttons(self, bar: ttk.Frame) -> None:
        ttk.Button(bar, text="Settings…", command=self._settings).pack(side="right")

    def build_panel(self, parent: tk.Misc) -> ttk.Frame:
        return WebPanel(parent, self, self._job_path, self._output_dir)

    def _settings(self) -> None:
        SettingsDialog(self.root, on_saved=self.panel.settings_changed)


def main(job_path: Optional[str] = None, output_dir: str = DEFAULT_OUTPUT, workers: int = 4) -> None:
    load_env()  # the keys and the contact address, from WebScraping/.env
    if job_path is None:
        job_path = DEFAULT_JOB if os.path.exists(DEFAULT_JOB) else ""
    root = tk.Tk()
    App(root, job_path, output_dir, workers)
    root.mainloop()
