# Classification/tests/test_window.py
"""The activation energies of each class told apart by transport component (bulk, grain boundary,
total) — in the files the classification writes and in its window. On small made-up databases in a
temporary folder; the window tests are skipped without a screen (as they are with MME_NO_WINDOW_TESTS=1).

    python -m pytest Classification
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from Classification.database import classify, energies_of, read, write
from Classification.gui import NO_VALUE, SIDE_BY_SIDE, kept

try:
    import tkinter as tk
except ImportError:  # a Python built without Tk
    tk = None

COMPOSITIONS = {"Li7La3Zr2O12": {"La": 3.0, "Li": 7.0, "O": 12.0, "Zr": 2.0},
                "Li6PS5Cl": {"Cl": 1.0, "Li": 6.0, "P": 1.0, "S": 5.0}}
ENERGY_COLUMNS = ["paper_id", "material_formula", "activation_energy_eV", "data_origin", "transport_component",
                  "attribution", "basis", "material_id", "sentence"]
# (paper, formula, Ea, origin, component, stated?, attribution)
ENERGIES = [
    ("A.pdf", "Li7La3Zr2O12", 0.30, "experimental", "bulk", True, "this work"),
    ("A.pdf", "Li7La3Zr2O12", 0.52, "experimental", "grain_boundary", True, "this work"),
    ("A.pdf", "Li7La3Zr2O12", 0.42, "experimental", "total", False, "this work"),
    ("B.pdf", "Li7La3Zr2O12", 0.24, "simulation", "bulk", False, "cited"),
    ("B.pdf", "Li6PS5Cl", 0.21, "simulation", "bulk", False, "this work"),
]


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_database(folder: Path) -> Path:
    folder.mkdir(parents=True)
    pairs = sorted({(paper, formula) for paper, formula, *_ in ENERGIES})
    ids = {pair: f"MAT_{n}" for n, pair in enumerate(pairs, 1)}
    _write(folder / "materials.csv", ["paper_id", "material_id", "raw_formula", "normalized_formula", "elements", "structure"],
           [{"paper_id": p, "material_id": ids[(p, f)], "raw_formula": f, "normalized_formula": f,
             "elements": json.dumps(COMPOSITIONS[f]), "structure": "NONE"} for p, f in pairs])
    _write(folder / "activation_energy.csv", ENERGY_COLUMNS, [
        {"paper_id": p, "material_formula": f, "activation_energy_eV": e, "data_origin": origin, "transport_component": c,
         "attribution": who, "material_id": ids[(p, f)], "sentence": f"{f}: {e} eV.",
         "basis": f"origin: stated; component: {'stated (the paper says so)' if stated else 'assumed (measured on a pellet)'}"}
        for p, f, e, origin, c, stated, who in ENERGIES])
    _write(folder / "ionic_conductivity.csv", ["paper_id", "material_formula", "ionic_conductivity_S_cm",
                                                "transport_component", "material_id"], [
        {"paper_id": "A.pdf", "material_formula": "Li7La3Zr2O12", "ionic_conductivity_S_cm": sigma, "transport_component": c,
         "material_id": ids[("A.pdf", "Li7La3Zr2O12")]} for sigma, c in (("0.0001", "total"), ("1e-06", "grain boundary"))])
    _write(folder / "papers.csv", ["paper_id", "title"], [{"paper_id": p, "title": p} for p in ("A.pdf", "B.pdf")])
    return folder


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.database = make_database(self.tmp / "web_output")
        self.classified = classify([read(self.database)])

    def test_each_activation_energy_says_its_component_and_how_that_is_known(self):
        energies = energies_of(self.classified)
        self.assertEqual(sorted(zip(energies.material, energies.component, energies.component_basis, energies.Ea_eV)),
                         [("Li6PS5Cl", "bulk", "assumed", 0.21), ("Li7La3Zr2O12", "bulk", "assumed", 0.24),
                          ("Li7La3Zr2O12", "bulk", "stated", 0.30), ("Li7La3Zr2O12", "grain_boundary", "stated", 0.52),
                          ("Li7La3Zr2O12", "total", "assumed", 0.42)])
        self.assertEqual(set(energies.crystal_structure), {"garnet", "argyrodite"})

    def test_the_classes_are_written_with_bulk_grain_boundary_and_total_apart(self):
        out = self.tmp / "classes"
        write(self.classified, out)
        garnet = {row["crystal_structure"]: row for row in read_csv(out / "crystal_structure" / "summary.csv")}["garnet"]
        self.assertEqual((garnet["n_Ea_bulk"], garnet["Ea_bulk_min_eV"], garnet["Ea_bulk_min_material"], garnet["Ea_bulk_median_eV"]),
                         ("2", "0.24", "Li7La3Zr2O12", "0.27"))
        self.assertEqual((garnet["n_Ea_grain_boundary"], garnet["Ea_grain_boundary_min_eV"]), ("1", "0.52"))
        self.assertEqual((garnet["n_Ea_total"], garnet["Ea_total_min_eV"]), ("1", "0.42"))
        argyrodite = {row["crystal_structure"]: row for row in read_csv(out / "crystal_structure" / "summary.csv")}["argyrodite"]
        self.assertEqual(argyrodite["Ea_total_min_eV"], "no total value reported")  # an answer, never an empty cell
        by_component = read_csv(out / "structure_families" / "activation_energy_by_component.csv")
        self.assertEqual([(r["structure_family"], r["component"], r["n_values"], r["n_component_stated"]) for r in by_component],
                         [("oxide", "bulk", "2", "1"), ("oxide", "grain_boundary", "1", "1"), ("oxide", "total", "1", "0"),
                          ("sulfide", "bulk", "1", "0"), ("sulfide", "grain_boundary", "0", "0"), ("sulfide", "total", "0", "0")])
        materials = read_csv(out / "crystal_structure" / "garnet" / "materials.csv")
        self.assertEqual((materials[0]["Ea_bulk_min_eV"], materials[0]["Ea_grain_boundary_min_eV"], materials[0]["n_Ea_total"]),
                         ("0.24", "0.52", "1"))
        for row in read_csv(out / "all_materials.csv"):
            self.assertFalse({"", "NONE"} & set(row.values()), row)

    def test_each_class_is_also_one_database_per_component(self):
        out = self.tmp / "classes"
        write(self.classified, out)
        garnet = out / "crystal_structure" / "garnet"
        self.assertEqual(sorted(p.name for p in garnet.iterdir() if p.is_dir()), ["bulk", "grain_boundary", "total"])
        # Every class has the three sub-classes; one with no value of a component has it empty.
        argyrodite = out / "crystal_structure" / "argyrodite"
        self.assertEqual(sorted(p.name for p in argyrodite.iterdir() if p.is_dir()), ["bulk", "grain_boundary", "total"])
        self.assertEqual(read_csv(argyrodite / "total" / "materials.csv"), [])
        with (argyrodite / "total" / "materials.csv").open(encoding="utf-8-sig") as handle:
            self.assertIn("transport_component", handle.readline())  # the header, for a table with no row
        bulk = garnet / "bulk"
        self.assertEqual(sorted(p.name for p in bulk.iterdir()),
                         ["activation_energy.csv", "diffusion_coefficient.csv", "electronic_conductivity.csv",
                          "ionic_conductivity.csv", "materials.csv", "papers.csv"])
        energies = read_csv(bulk / "activation_energy.csv")
        self.assertEqual(sorted((e["activation_energy_eV"], e["transport_component"]) for e in energies),
                         [("0.24", "bulk"), ("0.3", "bulk")])
        (material,) = read_csv(bulk / "materials.csv")
        self.assertEqual((material["material"], material["transport_component"], material["Ea_min_eV"], material["n_papers"]),
                         ("Li7La3Zr2O12", "bulk", "0.24", "2"))
        self.assertNotIn("Ea_total_min_eV", material)  # a folder of one component holds that component only
        self.assertEqual({p["paper_id"] for p in read_csv(bulk / "papers.csv")}, {"A.pdf", "B.pdf"})
        boundary = garnet / "grain_boundary"
        self.assertEqual([e["activation_energy_eV"] for e in read_csv(boundary / "activation_energy.csv")], ["0.52"])
        self.assertEqual([c["ionic_conductivity_S_cm"] for c in read_csv(boundary / "ionic_conductivity.csv")], ["1e-06"])
        self.assertEqual(read_csv(boundary / "materials.csv")[0]["sigma_max_S_cm"], "1e-06")
        self.assertEqual([c["ionic_conductivity_S_cm"] for c in read_csv(garnet / "total" / "ionic_conductivity.csv")], ["0.0001"])
        subs = read_csv(out / "crystal_structure" / "activation_energy_by_component.csv")
        self.assertEqual([(r["crystal_structure"], r["component"], r["n_values"]) for r in subs],
                         [("argyrodite", "bulk", "1"), ("argyrodite", "grain_boundary", "0"), ("argyrodite", "total", "0"),
                          ("garnet", "bulk", "2"), ("garnet", "grain_boundary", "1"), ("garnet", "total", "1")])
        empty = next(r for r in subs if (r["crystal_structure"], r["component"]) == ("argyrodite", "total"))
        self.assertEqual((empty["min_eV"], empty["folder"]), ("no total activation energy reported", "crystal_structure/argyrodite/total"))
        self.assertEqual(next(r for r in subs if (r["crystal_structure"], r["component"]) == ("garnet", "grain_boundary"))["folder"],
                         "crystal_structure/garnet/grain_boundary")

    def test_the_filters_choose_which_activation_energies_count(self):
        energies = energies_of(self.classified)
        self.assertEqual(len(kept(energies)), 5)
        self.assertEqual(sorted(kept(energies, origin="experiment").Ea_eV), [0.30, 0.42, 0.52])
        self.assertEqual(sorted(kept(energies, origin="simul").Ea_eV), [0.21, 0.24])
        self.assertEqual(sorted(kept(energies, this_work=True).Ea_eV), [0.21, 0.30, 0.42, 0.52])
        self.assertEqual(sorted(kept(energies, stated=True).component), ["bulk", "grain_boundary"])

    def test_a_database_without_components_still_classifies(self):
        rows = read_csv(self.database / "activation_energy.csv")
        _write(self.database / "activation_energy.csv", ["paper_id", "material_formula", "activation_energy_eV", "material_id"], rows)
        energies = energies_of(classify([read(self.database)]))
        self.assertEqual(set(energies.component), {"not given by the database"})
        self.assertEqual(set(energies.component_basis), {"not given by the database"})


def _has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from Classification.gui import App
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.database = make_database(self.tmp / "web_output")
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)  # built, but not in the way
        self.addCleanup(self.root.destroy)
        self.out = self.tmp / "classes"
        self.app = App(self.root, [self.database], self.out)
        deadline = time.time() + 30
        while self.app.result.classified is None and time.time() < deadline:
            self.root.update()
            time.sleep(0.02)

    def settle(self, seconds: float = 0.3) -> None:
        """Lets the window finish what it was doing (a refresh, a redraw) before the test acts."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.01)

    def select(self, table, row: str, axis: str) -> None:
        """Selects a row as a click does, and lists its materials. A click makes Tk send <<TreeviewSelect>>; a
        selection made in code is not sent the same way by every Tk build (python.org's for macOS and Windows),
        so the window's handler is called as the event would call it."""
        table.tree.selection_set(row)
        self.settle(0.1)
        self.assertEqual(list(table.tree.selection()), [row])
        self.app._fill_materials(axis)

    def cells(self, table, row):
        return dict(zip(table.columns, table.tree.item(row, "values")))

    def test_it_classifies_on_opening_and_writes_the_class_folders(self):
        self.assertTrue((self.out / "crystal_structure" / "garnet" / "materials.csv").is_file())
        classes = self.app.classes["crystal_structure"]
        self.assertEqual(set(classes.tree.get_children()), {"garnet", "argyrodite"})
        garnet = self.cells(classes, "garnet")
        self.assertEqual((garnet["bulk_n"], garnet["bulk_min"], garnet["grain_boundary_min"], garnet["total_min"]),
                         ("2", "0.24", "0.52", "0.42"))
        self.assertEqual(self.cells(classes, "argyrodite")["total_min"], NO_VALUE)
        families = self.app.classes["structure_families"]
        self.assertEqual(set(families.tree.get_children()), {"oxide", "sulfide"})

    def test_a_class_lists_its_materials_and_the_filters_recount(self):
        self.app.view.set(SIDE_BY_SIDE)
        self.settle()
        classes, materials = self.app.classes["crystal_structure"], self.app.materials["crystal_structure"]
        self.select(classes, "garnet", "crystal_structure")
        self.assertEqual([self.cells(materials, row)["material"] for row in materials.tree.get_children()], ["Li7La3Zr2O12"])
        self.app.stated.set(True)
        self.app.refresh()
        garnet = self.cells(classes, "garnet")
        self.assertEqual((garnet["bulk_n"], garnet["bulk_min"], garnet["total_n"]), ("1", "0.3", "0"))
        self.app.stated.set(False)
        self.app.origin.set("computed only")
        self.root.update()
        self.assertEqual(self.cells(classes, "garnet")["n_Ea"], "1")
        self.assertIn("2 of the 5 activation energies count", self.app.status.cget("text"))

    def test_each_class_has_its_sub_classes_under_it(self):
        tree, materials = self.app.trees["crystal_structure"], self.app.materials["crystal_structure"]
        self.assertEqual(list(tree.tree.get_children()), ["argyrodite", "garnet"])  # as many materials: by name
        subs = tree.tree.get_children("garnet")
        self.assertEqual([tree.tree.item(sub, "text") for sub in subs], ["bulk", "grain-boundary", "total"])
        self.assertTrue(tree.tree.item("garnet", "open"))
        boundary = self.cells(tree, subs[1])
        self.assertEqual((boundary["n_values"], boundary["min"], boundary["stated"]), ("1", "0.52", "1 of 1"))
        overall = self.cells(tree, "garnet")
        self.assertEqual((overall["n_values"], overall["min"], overall["min_material"]), ("4", "0.24", "Li7La3Zr2O12"))
        empty = self.cells(tree, tree.tree.get_children("argyrodite")[2])  # argyrodite → total: none
        self.assertEqual((empty["n_values"], empty["min"]), ("0", NO_VALUE))
        self.select(tree, "argyrodite\x1fbulk", "crystal_structure")
        self.assertEqual([self.cells(materials, row)["material"] for row in materials.tree.get_children()], ["Li6PS5Cl"])
        self.assertIn("argyrodite — bulk", self.app.captions["crystal_structure"].cget("text"))
        self.select(tree, "garnet\x1ftotal", "crystal_structure")
        self.assertEqual([self.cells(materials, row)["material"] for row in materials.tree.get_children()], ["Li7La3Zr2O12"])
        tree.tree.item("garnet", open=False)
        self.app.refresh()  # a class closed by hand stays closed
        self.assertFalse(tree.tree.item("garnet", "open"))
        self.app.view.set(SIDE_BY_SIDE)
        self.root.update()
        self.assertFalse(tree.winfo_ismapped())

    def test_a_material_opens_with_every_activation_energy_of_it(self):
        materials = self.app.materials["crystal_structure"]
        key = next(row for row in materials.tree.get_children() if self.cells(materials, row)["material"] == "Li7La3Zr2O12")
        window = self.app.details(key)
        self.addCleanup(window.destroy)
        from LocalExtraction.gui.widgets import Table
        table = next(child for child in window.winfo_children()[0].winfo_children() if isinstance(child, Table))
        rows = [dict(zip(table.columns, table.tree.item(row, "values"))) for row in table.tree.get_children()]
        self.assertEqual([(r["component"], r["Ea"], r["known"]) for r in rows],
                         [("bulk", "0.24", "assumed"), ("bulk", "0.3", "stated"), ("grain-boundary", "0.52", "stated"),
                          ("total", "0.42", "assumed")])


@unittest.skipUnless(_has_screen(), "the window needs a screen")
class FreshProjectTests(unittest.TestCase):
    def test_a_project_with_no_database_yet_opens_without_asking_anything(self):
        from Classification.gui import App
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        with mock.patch("Classification.gui.messagebox.showinfo") as asked:
            app = App(root, None, tmp / "classes")  # the databases of the project home, which has none yet
        asked.assert_not_called()
        self.assertIn("No database yet", app.status.cget("text"))


if __name__ == "__main__":
    unittest.main()
