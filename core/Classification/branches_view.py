# Classification/branches_view.py
"""The “By property” tab of the Classification window: the classification by property (branches.py) as a tree —
family ▸ property ▸ type ▸ origin — each branch with its counts, its range and its best material; the materials of the
branch selected below, one row each."""

from __future__ import annotations

import csv
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Dict, List

from LocalExtraction.gui.widgets import Table, WrapLabel, open_path

from .branches import AXES, FOLDER, PLURAL, read_tree

INFO = ("ⓘ  One click on “▶ Classify everything” sorts every family (crystal and chemical) into its properties — "
        "activation energy, ionic conductivity, diffusion coefficient, electronic conductivity — each alone, then by "
        "type (bulk, grain boundary, total) and by origin (experimental, simulation). Each branch is one table, never "
        "two quantities mixed: open a branch to see its materials. Quality: the papers' own results, flagged values "
        "left out, Arrhenius Ea only, conductivities and diffusion at room temperature, hand checks applied.")
_WORDS = {"bulk": "Bulk", "grain_boundary": "Grain boundary", "total": "Total", "experimental": "Experimental",
          "simulation": "Simulation"}


class BranchesView(ttk.Frame):
    """`out_dir()`: the folder the classes are written into (by_property/ is inside it)."""

    def __init__(self, parent: tk.Misc, out_dir: Callable[[], Path]):
        super().__init__(parent, padding=(0, 6, 0, 0))
        self.out_dir = out_dir
        self.leaves: Dict[str, Dict[str, str]] = {}
        WrapLabel(self, text=INFO, foreground="#6b7280", justify="left").pack(fill="x", pady=(0, 6))
        self.headline = tk.StringVar()
        ttk.Label(self, textvariable=self.headline, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 4))
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        upper = ttk.Frame(panes)
        columns = ("materials", "values", "papers", "range", "best")
        self.tree = ttk.Treeview(upper, columns=columns, height=12)
        self.tree.heading("#0", text="Family ▸ property ▸ type ▸ origin", anchor="w")
        self.tree.column("#0", width=360, stretch=True)
        for name, text, width in (("materials", "materials", 76), ("values", "values", 64), ("papers", "papers", 64),
                                  ("range", "range (min – max)", 190), ("best", "best material", 230)):
            self.tree.heading(name, text=text, anchor="w")
            self.tree.column(name, width=width, stretch=name == "best")
        bar = ttk.Scrollbar(upper, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.tag_configure("family", font=("TkDefaultFont", 11, "bold"))
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._selected())
        panes.add(upper, weight=3)
        lower = ttk.Frame(panes, padding=(0, 6, 0, 0))
        row = ttk.Frame(lower)
        row.pack(fill="x")
        self.caption = tk.StringVar(value="Select a branch (…▸ experimental / simulation) to see its materials.")
        ttk.Label(row, textvariable=self.caption, foreground="#6b7280").pack(side="left")
        self.open_button = ttk.Button(row, text="Open its folder", state="disabled", command=self._open_folder)
        self.open_button.pack(side="right")
        self.csv_button = ttk.Button(row, text="Open dataset.csv", state="disabled", command=self._open_csv)
        self.csv_button.pack(side="right", padx=(0, 6))
        self.materials = Table(lower, [("material", "material", 230), ("target", "value", 90), ("unit", "unit", 60),
                                       ("std", "spread (std)", 90), ("n_values", "values", 60), ("n_papers", "papers", 60),
                                       ("verified_values", "checked by hand", 110), ("paper_ids", "papers (files)", 320)],
                               stretch="paper_ids", height=9)
        self.materials.pack(fill="both", expand=True, pady=(4, 0))
        panes.add(lower, weight=2)
        self.show()

    def show(self) -> None:
        """Reads by_property/tree.csv again and fills the tree."""
        self.tree.delete(*self.tree.get_children())
        self.leaves = {}
        rows = read_tree(self.out_dir())
        if not rows:
            self.headline.set("No classification by property yet: press “▶ Classify everything”.")
            return
        families = {(r["axis"], r["family"]) for r in rows}
        self.headline.set(f"{len(rows):,} branches · {len(families):,} families · "
                          f"{sum(int(r['n_values']) for r in rows):,} values")
        nodes: Dict[tuple, str] = {}

        def node(key: tuple, parent: str, text: str, tags=()) -> str:
            if key not in nodes:
                nodes[key] = self.tree.insert(parent, "end", text=text, open=len(key) <= 1, tags=tags)
            return nodes[key]
        for axis, _ in AXES:
            mine = [r for r in rows if r["axis"] == axis]
            if not mine:
                continue
            top = node((axis,), "", f"{PLURAL[axis]}  ({len({r['family'] for r in mine})})")
            for r in mine:
                family = node((axis, r["family"]), top, r["family"], tags=("family",))
                prop = node((axis, r["family"], r["property"]), family, f"{r['property']} ({r['unit']})")
                kind = node((axis, r["family"], r["property"], r["component"]), prop, _WORDS.get(r["component"], r["component"]))
                leaf = self.tree.insert(kind, "end", text=_WORDS.get(r["origin"], r["origin"]), values=(
                    r["n_materials"], r["n_values"], r["n_papers"], f"{r['min']} – {r['max']}", r["best_material"]))
                self.leaves[leaf] = r

    def _selected(self) -> None:
        chosen = self.tree.focus()
        branch = self.leaves.get(chosen)
        if branch is None:
            self.materials.fill([])
            self.open_button.state(["disabled"])
            self.csv_button.state(["disabled"])
            return
        self.caption.set(f"{branch['family']} ▸ {branch['property']} ▸ {_WORDS.get(branch['component'])} ▸ "
                         f"{_WORDS.get(branch['origin'])}: {branch['n_materials']} materials, one row each")
        rows: List[tuple] = []
        try:
            with open(self.folder_of(branch) / "dataset.csv", encoding="utf-8-sig", newline="") as f:
                for index, r in enumerate(csv.DictReader(f)):
                    rows.append((str(index), [r.get(c, "") for c in ("material_formula", "target", "unit", "std",
                                                                     "n_values", "n_papers", "verified_values",
                                                                     "paper_ids")], []))
        except OSError:
            pass
        self.materials.fill(rows)
        self.open_button.state(["!disabled"])
        self.csv_button.state(["!disabled"])

    def folder_of(self, branch: Dict[str, str]) -> Path:
        return Path(self.out_dir()) / branch["folder"]

    def _open_folder(self) -> None:
        branch = self.leaves.get(self.tree.focus())
        if branch:
            open_path(self.folder_of(branch))

    def _open_csv(self) -> None:
        branch = self.leaves.get(self.tree.focus())
        if branch:
            open_path(self.folder_of(branch) / "dataset.csv")


__all__ = ["BranchesView", "FOLDER"]
