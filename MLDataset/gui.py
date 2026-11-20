# MLDataset/gui.py
"""The window of part 5: a dataset for machine learning, chosen step by step. Each step appears once the one before is
answered — ① the family, ② the property, ③ the transport component, ④ measured or computed, ⑤ the filters, with the
count of what will be kept, updated as they change — then ⑥ the big button that writes the dataset into
~/MoukhlijMatExtract/Ready for ML/. Changing an earlier step clears the later ones."""

from __future__ import annotations

import collections
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from LocalExtraction.gui import design, theme
from LocalExtraction.gui.widgets import Scrolled, WrapLabel, open_path

from . import export
from .export import ANY, PROPERTIES, Settings

_WORDS = {"bulk": "Bulk", "grain_boundary": "Grain boundary", "total": "Total", "surface": "Surface",
          "experimental": "Experimental (measured)", "simulation": "Simulation (computed)", ANY: "Any"}
_STEP = ("①", "②", "③", "④", "⑤", "⑥")
_QUIET = "#6b7280"


class MLWindow:
    def __init__(self, root: tk.Misc, home: Optional[Path] = None):
        self.root, self.home = root, Path(home or export.home())
        root.title("MoukhlijMatExtract (MME) · ML datasets")
        theme.apply(root)
        from LocalExtraction.gui import layout
        layout.place(root, (1000, 860), (760, 600))
        design.header(root, "ML datasets", "filter the extracted data and prepare datasets for machine learning")
        design.footer(root).pack(side="bottom", fill="x")
        style = ttk.Style(root)
        style.configure("Big.Current.TButton", font=("TkDefaultFont", 16, "bold"), padding=(28, 14))
        body = Scrolled(root)
        body.pack(fill="both", expand=True)
        self.frame = ttk.Frame(body.inner, padding=(24, 14, 24, 18))
        self.frame.pack(fill="both", expand=True)
        WrapLabel(self.frame, foreground=_QUIET, justify="left", text=(
            "ⓘ  Choose step by step what the dataset holds; each choice shows how many values it keeps. The dataset is "
            "written into ~/MoukhlijMatExtract/Ready for ML/ with one row per material, every value with its sentence "
            "and page, what was left out and why, and a datasheet. The families are the classes of 4 · Classification "
            "(run it again after new extractions), and the databases themselves.")).pack(fill="x", pady=(0, 10))

        self.families = export.families(self.home)
        self.family: Optional[export.Family] = None
        self.rows: List[Dict[str, str]] = []
        self.vars: Dict[str, tk.Variable] = {}
        self.steps: List[ttk.LabelFrame] = []
        self._pending: Optional[str] = None
        self.result = tk.StringVar()
        self.preview = tk.StringVar()
        self.folder: Optional[Path] = None
        self._family_step()

    # ------------------------------------------------------------------ the steps
    def _new_step(self, number: int, title: str) -> ttk.LabelFrame:
        """A step's frame; every later step is removed first (an earlier answer changed)."""
        for frame in self.steps[number:]:
            frame.destroy()
        del self.steps[number:]
        frame = ttk.LabelFrame(self.frame, text=f"  {_STEP[number]}  {title}  ", padding=(12, 8))
        frame.pack(fill="x", pady=(0, 10))
        self.steps.append(frame)
        return frame

    def _family_step(self) -> None:
        step = self._new_step(0, "Family of materials")
        if not self.families:
            WrapLabel(step, foreground="#b3261e", text="No family yet: run 4 · Classification (or extract a database) "
                                                       "first.").pack(fill="x")
            return
        labels = [f"{f.label}" for f in self.families]
        self.vars["family"] = tk.StringVar()
        row = ttk.Frame(step)
        row.pack(fill="x")
        ttk.Label(row, text="Family:").pack(side="left")
        self.family_box = ttk.Combobox(row, values=labels, textvariable=self.vars["family"], state="readonly", width=48)
        self.family_box.pack(side="left", padx=8)
        self.family_box.bind("<<ComboboxSelected>>", lambda event: self.choose_family(self.family_box.current()))
        WrapLabel(step, foreground=_QUIET, justify="left", text="Crystal structures (garnet, NASICON …) and structure "
                  "families (oxide, sulfide …) come from 4 · Classification; a database is every material of one results "
                  "folder.").pack(fill="x", anchor="w", pady=(6, 0))

    def choose_family(self, index: int) -> None:
        self.family = self.families[index]
        self.vars["family"].set(self.family.label)
        step = self._new_step(1, "Property")
        self.vars["target"] = tk.StringVar()
        found = export.counts(self.family)
        for key, prop in PROPERTIES.items():
            button = ttk.Radiobutton(step, text=f"{prop.label}  ({found[key]:,} values, {prop.unit})", value=key,
                                     variable=self.vars["target"], command=lambda k=key: self.choose_target(k))
            button.pack(anchor="w", pady=1)
            if not found[key]:
                button.state(["disabled"])

    def choose_target(self, key: str) -> None:
        self.vars["target"].set(key)
        self.rows = export.read_rows(self.family, key)
        step = self._new_step(2, "Transport component")
        self.vars["component"] = tk.StringVar()
        self._radios(step, "component", "transport_component", ("bulk", "grain_boundary", "total", "surface"),
                     self.rows, self.choose_component)

    def choose_component(self, value: str) -> None:
        self.vars["component"].set(value)
        step = self._new_step(3, "Measured or computed")
        self.vars["origin"] = tk.StringVar()
        rows = [r for r in self.rows if value == ANY or r.get("transport_component") == value]
        self._radios(step, "origin", "data_origin", ("experimental", "simulation"), rows, self.choose_origin)

    def _radios(self, step: ttk.Frame, name: str, column: str, values, rows, then) -> None:
        count = collections.Counter(r.get(column, "") for r in rows)
        for value in (*values, ANY):
            n = len(rows) if value == ANY else count.get(value, 0)
            button = ttk.Radiobutton(step, text=f"{_WORDS[value]}  ({n:,} values)", value=value,
                                     variable=self.vars[name], command=lambda v=value: then(v))
            button.pack(anchor="w", pady=1)
            if not n:
                button.state(["disabled"])

    def choose_origin(self, value: str) -> None:
        self.vars["origin"].set(value)
        target = self.vars["target"].get()
        step = self._new_step(4, "Filters")
        v = self.vars
        grid = ttk.Frame(step)
        grid.pack(fill="x")
        line = 0

        def label(text: str) -> None:
            ttk.Label(grid, text=text).grid(row=line, column=0, sticky="nw", padx=(0, 12), pady=4)

        v["attribution"] = tk.StringVar(value="this work")
        label("Result of")
        box = ttk.Frame(grid)
        box.grid(row=line, column=1, sticky="w")
        for value_, text in (("this work", "the paper's own work"), ("cited", "values it cites"), (ANY, "any")):
            ttk.Radiobutton(box, text=text, value=value_, variable=v["attribution"]).pack(side="left", padx=(0, 10))
        line += 1
        if target == "Ea":
            kinds = sorted({r.get("energy_kind", "") for r in self.rows if r.get("energy_kind")})
            v["energy_kind"] = tk.StringVar(value="arrhenius" if "arrhenius" in kinds else ANY)
            label("Kind of energy")
            ttk.Combobox(grid, values=(*kinds, ANY), textvariable=v["energy_kind"], state="readonly", width=20).grid(
                row=line, column=1, sticky="w")
            line += 1
            WrapLabel(grid, foreground=_QUIET, justify="left", text="arrhenius: long-range transport (impedance, MD); "
                      "migration_barrier: one hop (NEB). They are different quantities: keep one kind per dataset.").grid(
                row=line, column=1, columnspan=2, sticky="ew", pady=(0, 4))
            line += 1
        else:
            v["temperature"] = tk.StringVar(value="room")
            v["t_low"], v["t_high"] = tk.StringVar(value="290"), tk.StringVar(value="400")
            label("Temperature")
            box = ttk.Frame(grid)
            box.grid(row=line, column=1, columnspan=2, sticky="w")
            ttk.Radiobutton(box, text="room temperature", value="room", variable=v["temperature"]).pack(side="left")
            ttk.Radiobutton(box, text="any", value=ANY, variable=v["temperature"]).pack(side="left", padx=10)
            ttk.Radiobutton(box, text="from", value="range", variable=v["temperature"]).pack(side="left")
            ttk.Entry(box, textvariable=v["t_low"], width=6).pack(side="left", padx=4)
            ttk.Label(box, text="to").pack(side="left")
            ttk.Entry(box, textvariable=v["t_high"], width=6).pack(side="left", padx=4)
            ttk.Label(box, text="K").pack(side="left")
            line += 1
        ions = [ion for ion, _ in collections.Counter(r.get("mobile_ion", "") for r in self.rows).most_common() if ion]
        v["mobile_ion"] = tk.StringVar(value=ANY)
        label("Mobile ion")
        ttk.Combobox(grid, values=(ANY, *ions), textvariable=v["mobile_ion"], state="readonly", width=20).grid(
            row=line, column=1, sticky="w")
        line += 1
        unit = PROPERTIES[target].unit
        v["value_min"], v["value_max"] = tk.StringVar(), tk.StringVar()
        label("Value range")
        box = ttk.Frame(grid)
        box.grid(row=line, column=1, columnspan=2, sticky="w")
        ttk.Label(box, text="from").pack(side="left")
        ttk.Entry(box, textvariable=v["value_min"], width=10).pack(side="left", padx=4)
        ttk.Label(box, text="to").pack(side="left")
        ttk.Entry(box, textvariable=v["value_max"], width=10).pack(side="left", padx=4)
        ttk.Label(box, text=f"{unit}  (empty: no limit)", foreground=_QUIET).pack(side="left")
        line += 1
        label("Quality")
        box = ttk.Frame(grid)
        box.grid(row=line, column=1, columnspan=2, sticky="w")
        v["plausible_only"], v["no_needs_check"] = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
        v["verified_only"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="leave out the values the extraction flagged (plausibility)",
                        variable=v["plausible_only"]).pack(anchor="w")
        ttk.Checkbutton(box, text="leave out the values marked worth a look (needs_check)",
                        variable=v["no_needs_check"]).pack(anchor="w")
        if target == "Ea":
            ttk.Checkbutton(box, text="only the values checked by hand (Verify tab)",
                            variable=v["verified_only"]).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(4, 0))
        v["min_confidence"], v["min_values"] = tk.StringVar(value="0"), tk.StringVar(value="1")
        ttk.Label(row, text="confidence at least").pack(side="left")
        ttk.Spinbox(row, from_=0, to=1, increment=0.05, width=5, textvariable=v["min_confidence"]).pack(side="left", padx=4)
        ttk.Label(row, text="· values per material at least").pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=1, to=20, width=4, textvariable=v["min_values"]).pack(side="left", padx=4)
        line += 1
        v["per_material"] = tk.BooleanVar(value=True)
        label("Rows")
        box = ttk.Frame(grid)
        box.grid(row=line, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(box, text="one per material (median of its values)", value=True,
                        variable=v["per_material"]).pack(side="left")
        ttk.Radiobutton(box, text="one per value", value=False, variable=v["per_material"]).pack(side="left", padx=10)
        line += 1
        v["name"] = tk.StringVar()
        label("Dataset name")
        ttk.Entry(grid, textvariable=v["name"], width=50).grid(row=line, column=1, columnspan=2, sticky="w")
        grid.columnconfigure(2, weight=1)
        ttk.Label(step, textvariable=self.preview, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(10, 0))
        for name in ("attribution", "energy_kind", "temperature", "t_low", "t_high", "mobile_ion", "value_min", "value_max",
                     "plausible_only", "no_needs_check", "verified_only", "min_confidence", "min_values", "per_material"):
            if name in v:
                v[name].trace_add("write", lambda *a: self._later())
        self._generate_step()
        self.update_preview()

    def _generate_step(self) -> None:
        step = self._new_step(5, "Generate")
        self.generate_button = ttk.Button(step, text="Generate the dataset for ML", style="Big.Current.TButton",
                                          command=self.generate)
        self.generate_button.pack(fill="x", pady=(4, 6))
        ttk.Label(step, foreground=_QUIET, text=f"Saved in {self.home / export.READY}/<dataset name>/").pack(anchor="w")
        WrapLabel(step, textvariable=self.result, justify="left").pack(fill="x", pady=(6, 0))
        self.open_row = ttk.Frame(step)
        self.open_row.pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------ settings, preview, generate
    def settings(self) -> Settings:
        v = self.vars
        temperature = ANY
        if "temperature" in v:
            temperature = v["temperature"].get()
            if temperature == "range":
                temperature = f"{float(v['t_low'].get())}-{float(v['t_high'].get())}"

        def optional(name: str) -> Optional[float]:
            text = v[name].get().strip()
            return float(text) if text else None
        return Settings(
            family=self.family.key, target=v["target"].get(), component=v["component"].get(), origin=v["origin"].get(),
            attribution=v["attribution"].get(), energy_kind=v["energy_kind"].get() if "energy_kind" in v else ANY,
            mobile_ion=v["mobile_ion"].get(), temperature=temperature, value_min=optional("value_min"),
            value_max=optional("value_max"), plausible_only=v["plausible_only"].get(),
            no_needs_check=v["no_needs_check"].get(), verified_only=v["verified_only"].get(),
            min_confidence=float(v["min_confidence"].get() or 0), min_values=int(float(v["min_values"].get() or 1)),
            per_material=bool(v["per_material"].get()), name=v["name"].get().strip())

    def _later(self) -> None:
        if self._pending is not None:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(250, self.update_preview)

    def update_preview(self) -> None:
        self._pending = None
        try:
            settings = self.settings()
            chosen = export.select(settings, self.home)
        except (ValueError, tk.TclError) as error:
            self.preview.set(f"⚠ {error}")
            self.generate_button.state(["disabled"])
            return
        if not self.vars["name"].get().strip():
            self.vars["name"].set(export.default_name(settings, self.family))
        ok = bool(chosen.kept)
        self.preview.set(f"→ {chosen.materials():,} materials · {len(chosen.kept):,} values from {chosen.papers():,} "
                         f"papers  ({len(chosen.excluded):,} left out)" if ok else
                         f"→ no value passes these settings ({len(chosen.excluded):,} left out): loosen a filter")
        self.generate_button.state(["!disabled"] if ok else ["disabled"])

    def generate(self) -> Optional[Path]:
        try:
            self.folder = export.generate(self.settings(), self.home)
        except (ValueError, OSError) as error:
            messagebox.showerror("ML datasets", str(error), parent=self.root)
            return None
        self.result.set(f"✓ Dataset written: {self.folder}  —  dataset.csv (one row per material), values.csv, "
                        f"excluded.csv, README.md, settings.json")
        for child in self.open_row.winfo_children():
            child.destroy()
        ttk.Button(self.open_row, text="Open the folder", command=lambda: open_path(self.folder)).pack(side="left")
        ttk.Button(self.open_row, text="Open dataset.csv",
                   command=lambda: open_path(self.folder / "dataset.csv")).pack(side="left", padx=6)
        ttk.Button(self.open_row, text="Read the datasheet",
                   command=lambda: open_path(self.folder / "README.md")).pack(side="left")
        return self.folder


def main(argv=None) -> int:
    """`mme-ml-export gui`: the window. --help and --version answer without opening it."""
    import argparse
    import os
    from LocalExtraction.about import PROJECT_HOME, command_name, require_tk, version_text
    parser = argparse.ArgumentParser(prog=f"{command_name('mme-ml-export', 'MLDataset')} gui",
                                     description="The window of the ML datasets: choose the family, the property, the "
                                                 "component, the origin and the filters step by step, then generate the "
                                                 "dataset into ~/MoukhlijMatExtract/Ready for ML/.",
                                     epilog="MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
    parser.add_argument("--version", action="version", version=version_text("mme-ml-export"))
    parser.parse_args(argv)
    require_tk("mme-ml-export gui")
    if PROJECT_HOME.is_dir():
        os.chdir(PROJECT_HOME)
    root = tk.Tk()
    from LocalExtraction.crashlog import watch
    watch(root)  # a window's own errors: written to a crash file, and said
    MLWindow(root)
    root.mainloop()
    return 0
