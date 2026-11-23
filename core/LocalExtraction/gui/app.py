# LocalExtraction/gui/app.py
"""The window of Project 1: the PDFs of a folder read into a folder of results, its activation
energies shown as they land.

    python -m LocalExtraction gui"""

import tkinter as tk
from tkinter import ttk

from ..about import DEFAULT_INPUT, DEFAULT_OUTPUT
from .panel import LocalPanel
from .window import Window


class App(Window):
    def __init__(self, root: tk.Tk, input_dir: str = DEFAULT_INPUT, output_dir: str = DEFAULT_OUTPUT,
                 workers: int = 4, lookup: bool = True, domain: str = "electrolyte"):
        self._folders = (input_dir, output_dir)
        self.lookup = lookup  # False (--offline): the papers' details are not completed from OpenAlex
        self.domain = domain  # electrolyte / cathode / anode (--domain): what the database is about
        super().__init__(root, "MoukhlijMatExtract (MME) · Local extraction",
                         "the PDFs on this computer, read into a folder of results", workers,
                         size="1040x820", minsize=(820, 600))

    def header_buttons(self, bar: ttk.Frame) -> None:
        from .csv_browser import results_buttons  # its folder is read when a button is pressed
        results_buttons(bar, "1 · Local extraction", lambda: self.panel.output_dir, statistics=self._statistics)

    def _statistics(self):
        """The charts of the database the window extracts into (📊 Statistics…)."""
        from pathlib import Path
        from ..stats import database_charts
        folder = Path(self.panel.output_dir).expanduser()
        return f"local-{folder.name}", lambda: database_charts(folder, f"the local database {folder.name}")

    def build_panel(self, parent: tk.Misc) -> ttk.Frame:
        return LocalPanel(parent, self, *self._folders)


def main(input_dir: str = DEFAULT_INPUT, output_dir: str = DEFAULT_OUTPUT, workers: int = 4,
         lookup: bool = True, domain: str = "electrolyte") -> None:
    root = tk.Tk()
    from LocalExtraction.crashlog import watch
    watch(root)  # a window's own errors: written to a crash file, and said
    App(root, input_dir, output_dir, workers, lookup, domain)
    from LocalExtraction.crashlog import run
    run(root)  # the loop, then the window closed cleanly
