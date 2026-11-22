# Classification/tests/test_branches.py
"""The classification by property: one table per family ▸ property ▸ type ▸ origin, the quality defaults of the ML
datasets applied, a branch no value reaches not written, and the tree of branches in the window."""

import csv
import tempfile
import unittest
from pathlib import Path

from Classification import branches
from LocalExtraction.tests.test_gui import has_screen, tk
from MLDataset.tests.test_export import EA, SIGMA, ea, write


class BranchTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.out = self.home / "Classification"
        garnet = self.out / "crystal_structure" / "garnet"
        write(garnet / "activation_energy.csv", EA, [
            ea("p1", "Li7La3Zr2O12", "0.30"), ea("p2", "Li7La3Zr2O12", "0.34"),
            ea("p3", "Li6.4La3Zr1.4Ta0.6O12", "0.40", component="total"),
            ea("p4", "Li7La3Zr2O12", "0.20", origin="simulation"),
            ea("p5", "Li7La3Zr2O12", "0.25", kind="migration_barrier"),            # not Arrhenius: left out
            ea("p6", "LiCoO2", "0.6", plausibility="check: it is an electrode material")])  # flagged: left out
        write(garnet / "ionic_conductivity.csv", SIGMA, [
            dict(ea("q1", "Li7La3Zr2O12", "0", component="total"), ionic_conductivity_S_cm="5e-4",
                 temperature="room temperature"),
            dict(ea("q2", "Li6.4La3Zr1.4Ta0.6O12", "0", component="total"), ionic_conductivity_S_cm="1e-3",
                 temperature="298 K"),
            dict(ea("q3", "Li7La3Zr2O12", "0", component="total"), ionic_conductivity_S_cm="2e-2",
                 temperature="573 K")])  # not at room temperature: left out
        oxide = self.out / "structure_families" / "oxide"
        write(oxide / "activation_energy.csv", EA, [ea("p1", "Li7La3Zr2O12", "0.30")])

    def test_one_table_per_family_property_type_and_origin_and_none_empty(self):
        written = branches.write_all(self.out, self.home)
        paths = sorted(Path(b.folder).relative_to(branches.FOLDER).as_posix() for b in written)
        self.assertEqual(paths, [
            "crystal_structure/garnet/activation_energy/bulk/experimental",
            "crystal_structure/garnet/activation_energy/bulk/simulation",
            "crystal_structure/garnet/activation_energy/total/experimental",
            "crystal_structure/garnet/ionic_conductivity/total/experimental",
            "structure_families/oxide/activation_energy/bulk/experimental"])
        for b in written:
            self.assertTrue((self.out / b.folder / "dataset.csv").is_file())
            self.assertTrue((self.out / b.folder / "values.csv").is_file())
        self.assertFalse((self.out / branches.FOLDER / "crystal_structure/garnet/activation_energy/grain_boundary").exists())

    def test_the_quality_defaults_and_the_best_end_of_each_property(self):
        written = {(b.target, b.component, b.origin): b for b in branches.write_all(self.out, self.home)
                   if b.family == "garnet"}
        bulk = written[("Ea", "bulk", "experimental")]
        self.assertEqual((bulk.materials, bulk.values), (1, 2))  # p1, p2; not the barrier, not the flagged one
        self.assertAlmostEqual(bulk.middle, 0.32)
        sigma = written[("sigma", "total", "experimental")]
        self.assertEqual(sigma.values, 2)  # not the 573 K value
        self.assertEqual(sigma.best_material, "Li6.4La3Zr1.4Ta0.6O12")  # the highest conductivity is the best

    def test_the_tree_and_its_overview(self):
        branches.write_all(self.out, self.home)
        tree = branches.read_tree(self.out)
        self.assertEqual(len(tree), 5)
        self.assertEqual(tree[0]["property"], "Activation energy")
        readme = (self.out / branches.FOLDER / "README.md").read_text(encoding="utf-8")
        for words in ("## Crystal families", "## Chemical families", "**garnet**", "Ionic conductivity (S/cm)"):
            self.assertIn(words, readme)
        branches.write_all(self.out, self.home)  # again: replaced whole, nothing left aside
        self.assertFalse((self.out / f".{branches.FOLDER}.writing").exists())


@unittest.skipUnless(has_screen(), "the window needs a screen")
class ViewTests(BranchTests):
    def test_the_tab_shows_the_tree_and_the_materials_of_a_branch(self):
        from Classification.branches_view import BranchesView
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        view = BranchesView(root, lambda: self.out)
        view.pack()
        self.assertIn("Classify everything", view.headline.get())  # nothing yet
        branches.write_all(self.out, self.home)
        view.show()
        self.assertIn("5 branches", view.headline.get())
        leaf = next(k for k, r in view.leaves.items() if r["property"] == "Activation energy"
                    and r["component"] == "bulk" and r["origin"] == "experimental" and r["family"] == "garnet")
        view.tree.see(leaf)
        view.tree.focus(leaf)
        view._selected()
        self.assertEqual(len(view.materials.tree.get_children()), 1)
        self.assertIn("garnet ▸ Activation energy ▸ Bulk ▸ Experimental", view.caption.get())


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(has_screen(), "the window needs a screen")
class FlowWindowTests(BranchTests):
    def test_the_flow_window_draws_every_step_with_the_numbers_of_the_last_classification(self):
        from Classification.flow_window import open_flow
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        empty = open_flow(root, self.out)  # before any classification: the steps, no numbers
        for words in ("▶  CLASSIFY EVERYTHING", "Crystal family", "Chemical family", "Activation energy",
                      "Ionic conductivity", "Diffusion coefficient", "Electronic conductivity", "bulk",
                      "grain boundary", "total", "experimental (measured)", "simulation (computed)", "One table per branch"):
            self.assertIn(words, empty.diagram.texts)
        empty.destroy()
        branches.write_all(self.out, self.home)
        window = open_flow(root, self.out)
        root.update()
        self.assertTrue(any("5 branches" in t for t in window.diagram.texts))
        self.assertIn("1 family", window.diagram.texts)  # one chemical family: oxide
        backs = [w for w in window.winfo_children() if getattr(getattr(w, "back", None), "back", False)]
        self.assertEqual(len(backs), 1)  # the header band with its ‹ Back
