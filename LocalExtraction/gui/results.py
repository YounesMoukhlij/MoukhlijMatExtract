# LocalExtraction/gui/results.py
"""The activation energies of a folder of results, as it holds them."""

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable, Optional

import pandas as pd

from .. import database
from ..exporter import StrictExporter
from .dialogs import DetailsDialog
from .widgets import Table, WrapLabel, open_path

if TYPE_CHECKING:
    from .window import Window

# (column of activation_energy.csv, heading, width) — the ones worth a glance; a double click shows all.
_COLUMNS = (
    ("material_formula", "material", 140), ("activation_energy_eV", "Ea (eV)", 58), ("extracted_from", "from", 54),
    ("page", "page", 42), ("reported_as", "called", 104), ("structure", "structure", 104),
    ("temperature", "temperature", 104), ("data_origin", "origin", 84), ("transport_component", "component", 84),
    ("attribution", "result of", 66), ("n_assumed", "assumed", 60), ("paper_id", "paper", 180),
)


def pending_pdfs(folder: str, output_dir: str) -> int:
    """How many PDFs of a folder the database does not have yet (what an extraction will read)."""
    try:
        pdfs = {name for name in os.listdir(folder) if name.lower().endswith(".pdf")}
    except OSError:
        return 0
    papers = database.table(output_dir, "papers")
    return len(pdfs - set(papers["filename"])) if "filename" in papers else len(pdfs)


class EnergiesView(ttk.Frame):
    """The table of the activation energies in one folder of results, with how many there are and
    the ways to the files themselves."""

    def __init__(self, parent: tk.Misc, app: "Window", output_dir: Callable[[], str]):
        super().__init__(parent, padding=(0, 6, 0, 0))
        self.app, self._output_dir = app, output_dir
        self._rows: Optional[pd.DataFrame] = None
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        self.count = tk.StringVar(value="Nothing extracted yet.")
        files = ttk.Menubutton(bar, text="Results")
        menu = tk.Menu(files, tearoff=False)
        menu.add_command(label="Open the folder", command=self._open_folder)
        menu.add_command(label="Open the workbook (Excel)", command=self._open_workbook)
        menu.add_separator()
        menu.add_command(label="Rebuild…", command=lambda: self.app.rebuild(self._output_dir()))
        files.configure(menu=menu)
        files.pack(side="right")
        ttk.Button(bar, text="Refresh", command=self.show).pack(side="right", padx=4)
        WrapLabel(bar, textvariable=self.count, wraplength=300).pack(side="left", fill="x", expand=True)
        self.table = Table(self, _COLUMNS, on_open=self._details, stretch="paper_id")
        self.table.pack(fill="both", expand=True)

    def show(self) -> None:
        """Reads the folder again and shows its activation energies."""
        folder = self._output_dir()
        rows = database.activation_energies(folder)
        self._rows = rows
        shown = [name for name, _, _ in _COLUMNS]
        self.table.fill([(str(index), [row.get(name, "") for name in shown], ()) for index, row in rows.iterrows()])
        articles = len(database.table(folder, "papers"))
        if folder and StrictExporter.is_outdated(folder):
            self.count.set(f"{folder} holds a database of an earlier version: it is rebuilt (its files kept aside) "
                           "when an extraction starts.")
        elif not articles:
            self.count.set(f"Nothing extracted into {folder or 'a folder'} yet.")
        else:
            giving = rows["paper_id"].nunique() if len(rows) else 0
            self.count.set(f"{folder}: {articles} article{'s' if articles != 1 else ''} read, {len(rows)} activation "
                           f"energies from {giving} of them (double-click a row: its sentence)")

    def _details(self, identifier: str) -> None:
        if self._rows is None:
            return
        row = self._rows.iloc[int(identifier)]
        first = ("material_formula", "activation_energy_eV", "reported_as", "extracted_from", "page", "sentence",
                 "basis", "source", "title")
        pairs = [(name, row[name]) for name in first if name in row] + [
            (name, value) for name, value in row.items() if name not in first]
        DetailsDialog(self, f"{row.get('material_formula', '')}: {row.get('activation_energy_eV', '')} eV", pairs)

    def _open_folder(self) -> None:
        folder = self._output_dir()
        if folder and os.path.isdir(folder):
            open_path(folder)
        else:
            messagebox.showinfo("MoukhlijMatExtract", "This folder does not exist yet: the first extraction makes it.",
                                parent=self)

    def _open_workbook(self) -> None:
        path = os.path.join(self._output_dir(), "database.xlsx")
        if os.path.exists(path):
            open_path(path)
        else:
            messagebox.showinfo("MoukhlijMatExtract", "There is no workbook yet: it is written when an extraction ends.",
                                parent=self)
