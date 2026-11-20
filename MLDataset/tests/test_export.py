# MLDataset/tests/test_export.py
"""ML datasets: the values a family, a property, a component, an origin and the filters keep; the checks by hand
applied; one row per material; the folder in Ready for ML; the command and the step-by-step window."""

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from LocalExtraction.tests.test_gui import has_screen, tk
from LocalExtraction.verification import COLUMNS as VERIFY_COLUMNS, row_id
from MLDataset import cli, export
from MLDataset.export import Settings

EA = ["paper_id", "title", "material_formula", "activation_energy_eV", "plausibility", "needs_check", "energy_kind",
      "temperature", "data_origin", "transport_component", "mobile_ion", "attribution", "confidence", "page", "sentence",
      "database", "material_key", "crystal_structure", "structure_family", "extracted_from"]
SIGMA = [c if c != "activation_energy_eV" else "ionic_conductivity_S_cm" for c in EA if c != "energy_kind"]


def ea(paper, formula, value, component="bulk", origin="experimental", kind="arrhenius", plausibility="in range",
       attribution="this work", needs="no"):
    return {"paper_id": paper, "title": f"Paper {paper}", "material_formula": formula, "activation_energy_eV": value,
            "plausibility": plausibility, "needs_check": needs, "energy_kind": kind, "temperature": "300-500 K",
            "data_origin": origin, "transport_component": component, "mobile_ion": "Li+", "attribution": attribution,
            "confidence": "0.9", "page": "3", "sentence": f"{formula} shows {value} eV.", "database": "web_output",
            "material_key": formula, "crystal_structure": "garnet", "structure_family": "oxide", "extracted_from": "Text"}


def write(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        garnet = self.home / "Classification" / "crystal_structure" / "garnet"
        self.rows = [ea("p1", "Li7La3Zr2O12", "0.30"), ea("p2", "Li7La3Zr2O12", "0.34"),
                     ea("p3", "Li6.4La3Zr1.4Ta0.6O12", "0.40"),
                     ea("p4", "Li7La3Zr2O12", "0.50", component="total"),
                     ea("p5", "Li7La3Zr2O12", "0.20", origin="simulation"),
                     ea("p6", "Li7La3Zr2O12", "0.25", kind="migration_barrier"),
                     ea("p7", "LiCoO2", "0.6", plausibility="check: it is an electrode material"),
                     ea("p8", "Li7La3Zr2O12", "0.33", attribution="cited"),
                     ea("p9", "Li6.5La3Zr1.5Nb0.5O12", "0.90")]
        write(garnet / "activation_energy.csv", EA, self.rows)
        sigma = [dict(ea("q1", "Li7La3Zr2O12", "0"), ionic_conductivity_S_cm="5e-4", temperature="room temperature"),
                 dict(ea("q2", "Li7La3Zr2O12", "0"), ionic_conductivity_S_cm="1e-3", temperature="298.1 K"),
                 dict(ea("q3", "Li7La3Zr2O12", "0"), ionic_conductivity_S_cm="2e-2", temperature="573.1 K")]
        write(garnet / "ionic_conductivity.csv", SIGMA, sigma)
        # Li6.5…Nb0.5 at 0.90 eV marked wrong by hand; Li6.4…Ta0.6 corrected to 0.42.
        checks = self.home / "Verification" / "web_output.csv"
        write(checks, VERIFY_COLUMNS, [
            {"value_id": row_id(self.rows[8]), "verdict": "wrong"},
            {"value_id": row_id(self.rows[2]), "verdict": "corrected", "corrected_activation_energy_eV": "0.42"},
            {"value_id": row_id(self.rows[0]), "verdict": "correct"}])

    def settings(self, **values):
        return Settings(**{"family": "garnet", "target": "Ea", "component": "bulk", "origin": "experimental", **values})

    def test_the_families_are_the_classes_and_the_databases(self):
        found = export.families(self.home)
        self.assertEqual([f.key for f in found], ["crystal_structure/garnet"])
        self.assertEqual(export.counts(found[0]), {"Ea": 9, "sigma": 3, "sigma_e": 0, "D": 0})
        self.assertEqual(export.find_family("GARNET", self.home).key, "crystal_structure/garnet")
        with self.assertRaises(ValueError):
            export.find_family("perovskite", self.home)

    def test_each_filter_keeps_only_comparable_values_and_says_why_the_others_went(self):
        chosen = export.select(self.settings(), self.home)
        kept = sorted((r["paper_id"], r["activation_energy_eV"]) for r in chosen.kept)
        self.assertEqual(kept, [("p1", "0.30"), ("p2", "0.34"), ("p3", "0.42")])  # p3 as corrected by hand
        reasons = chosen.reasons()
        for why in ("component is total", "origin is simulation", "kind of energy is migration_barrier",
                    "flagged by the extraction (plausibility)", "result of cited", "marked wrong by hand"):
            self.assertEqual(reasons.get(why), 1, why)
        self.assertEqual((chosen.materials(), chosen.papers()), (2, 3))
        only = export.select(self.settings(verified_only=True), self.home)
        self.assertEqual(sorted(r["paper_id"] for r in only.kept), ["p1", "p3"])

    def test_the_dataset_folder_has_one_row_per_material_and_everything_to_check_it(self):
        folder = export.generate(self.settings(), self.home)
        self.assertEqual(folder, self.home / "Ready for ML" / "garnet_Ea_bulk_experimental_arrhenius")
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["README.md", "dataset.csv", "excluded.csv", "settings.json", "values.csv"])
        with open(folder / "dataset.csv", encoding="utf-8-sig") as f:
            rows = {r["material"]: r for r in csv.DictReader(f)}
        llzo = rows["Li7La3Zr2O12"]
        self.assertEqual((llzo["target"], llzo["n_values"], llzo["n_papers"], llzo["verified_values"]), ("0.32", "2", "2", "1"))
        self.assertEqual(llzo["group"], "garnet")
        with open(folder / "values.csv", encoding="utf-8-sig") as f:
            self.assertIn("shows 0.30 eV", next(csv.DictReader(f))["sentence"])
        with open(folder / "excluded.csv", encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 6)
        readme = (folder / "README.md").read_text(encoding="utf-8")
        for words in ("2 materials", "Split by group", "component is total"):
            self.assertIn(words, readme)
        again = Settings(**{k: v for k, v in json.loads((folder / "settings.json").read_text()).items()
                            if k in Settings.__dataclass_fields__})
        self.assertEqual(export.select(again, self.home).kept, export.select(self.settings(), self.home).kept)

    def test_conductivities_are_learned_in_log10_and_room_temperature_is_understood(self):
        chosen = export.select(Settings(family="garnet", target="sigma", temperature="room"), self.home)
        self.assertEqual(sorted(r["paper_id"] for r in chosen.kept), ["q1", "q2"])  # not the 573 K value
        self.assertEqual(export.temperature_K("600-1200 K")[:2], (600.0, 1200.0))
        self.assertEqual(export.temperature_K("25 °C")[2], True)
        folder = export.generate(Settings(family="garnet", target="sigma", temperature="room"), self.home)
        with open(folder / "dataset.csv", encoding="utf-8-sig") as f:
            row = next(csv.DictReader(f))
        self.assertAlmostEqual(float(row["log10_target"]), math.log10(7.5e-4), places=3)

    def test_settings_that_keep_nothing_are_refused(self):
        with self.assertRaises(ValueError):
            export.generate(self.settings(value_min=5.0), self.home)

    def test_the_command(self):
        from unittest import mock
        with mock.patch.object(export, "home", return_value=self.home):
            self.assertEqual(cli._main(["--family", "garnet", "--target", "Ea", "--component", "bulk",
                                        "--origin", "experimental"]), 0)
            self.assertTrue((self.home / "Ready for ML" / "garnet_Ea_bulk_experimental_arrhenius" / "dataset.csv").is_file())
            self.assertEqual(cli._main(["--list"]), 0)
            self.assertEqual(cli._main(["--target", "Ea"]), 2)  # no family


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(ExportTests):
    def test_the_window_asks_step_by_step_then_generates(self):
        from MLDataset.gui import MLWindow
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        window = MLWindow(root, home=self.home)
        self.assertEqual(len(window.steps), 1)  # only ① the family at first
        window.choose_family(0)
        self.assertEqual(len(window.steps), 2)
        window.choose_target("Ea")
        window.choose_component("bulk")
        self.assertEqual(len(window.steps), 4)
        window.choose_origin("experimental")
        self.assertEqual(len(window.steps), 6)  # ⑤ the filters and ⑥ the button
        root.update()
        self.assertIn("2 materials · 3 values from 3 papers", window.preview.get())
        self.assertEqual(window.generate_button.cget("text"), "Generate the dataset for ML")
        folder = window.generate()
        self.assertTrue((folder / "dataset.csv").is_file())
        self.assertIn("Dataset written", window.result.get())
        window.choose_target("sigma")  # an earlier answer changed: the later steps go
        self.assertEqual(len(window.steps), 3)


if __name__ == "__main__":
    unittest.main()
