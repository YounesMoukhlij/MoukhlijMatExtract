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
                 workers: int = 4):
        self._folders = (input_dir, output_dir)
        super().__init__(root, "MoukhlijMatExtract (MME) · Local extraction",
                         "the PDFs on this computer, read into a folder of results", workers,
                         size="1040x820", minsize=(820, 600))

    def build_panel(self, parent: tk.Misc) -> ttk.Frame:
        return LocalPanel(parent, self, *self._folders)


def main(input_dir: str = DEFAULT_INPUT, output_dir: str = DEFAULT_OUTPUT, workers: int = 4) -> None:
    root = tk.Tk()
    App(root, input_dir, output_dir, workers)
    root.mainloop()
