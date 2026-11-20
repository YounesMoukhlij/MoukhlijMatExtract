# LocalExtraction/tests/test_duplicates.py
"""One measurement counted once: a value repeated in its paper or quoted by another paper traced back to its
original; two papers' own equal values flagged, never merged; different temperatures, components or materials kept
apart; the report across databases; and the ML export counting each measurement once."""

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from LocalExtraction import duplicates
from MLDataset import export
from MLDataset.export import Settings
from MLDataset.tests.test_export import EA, ea, write


def sigma(paper, formula, value, attribution="this work", temperature="298 K", component="total"):
    return {"paper_id": paper, "material_formula": formula, "ionic_conductivity_S_cm": value,
            "temperature": temperature, "transport_component": component, "data_origin": "experimental",
            "attribution": attribution, "confidence": "0.8", "page": "2", "sentence": f"{paper} {value}"}


class MarkTests(unittest.TestCase):
    def test_quotes_and_repeats_lead_back_to_the_original(self):
        rows = [sigma("late", "Li7La3Zr2O12", "1.0e-3", attribution="cited"),     # quotes "early"
                sigma("early", "Li7La3Zr2O12", "1.01e-3"),                        # the measurement (2 % apart: same)
                sigma("early", "Li7La3Zr2O12", "1e-3"),                           # repeated in its abstract
                sigma("other", "Li7La3Zr2O12", "1e-3"),                           # its own equal value: possible
                sigma("hot", "Li7La3Zr2O12", "1e-3", temperature="373 K"),        # another temperature: another one
                sigma("gb", "Li7La3Zr2O12", "1e-3", component="grain boundary"),  # another component
                sigma("x", "Li7La3Zr2O12", "1.2e-3")]                             # another value
        marked = duplicates.mark(rows, "ionic_conductivity", years={"early": 2016, "other": 2020, "late": 2023})
        by = {(r["paper_id"], r["ionic_conductivity_S_cm"]): r for r in marked}
        original = by[("early", "1.01e-3")]
        self.assertEqual(original["duplicate_kind"], "")
        self.assertEqual(by[("late", "1.0e-3")]["duplicate_kind"], "cited")
        self.assertEqual(by[("early", "1e-3")]["duplicate_kind"], "same paper")
        self.assertEqual(by[("other", "1e-3")]["duplicate_kind"], "possible")
        for key in (("late", "1.0e-3"), ("early", "1e-3"), ("other", "1e-3")):
            self.assertEqual(by[key]["measurement_id"], original["measurement_id"])
            self.assertEqual(by[key]["duplicate_of"], duplicates.row_key(original, "ionic_conductivity_S_cm"))
            self.assertEqual(by[key]["original_paper"], "early")
            self.assertEqual(by[key]["n_papers"], 3)
        for key in (("hot", "1e-3"), ("gb", "1e-3"), ("x", "1.2e-3")):
            self.assertNotEqual(by[key]["measurement_id"], original["measurement_id"], key)
            self.assertEqual(by[key]["duplicate_kind"], "", key)
        self.assertEqual(len(duplicates.unique(marked)), 5)  # the quote and the repeat dropped; "possible" kept
        self.assertEqual(duplicates.summary(marked)["measurements"], 4)

    def test_the_same_material_however_its_formula_is_written(self):
        rows = [{**ea("a", "Li1.3Al0.3Ti1.7(PO4)3", "0.30"), "material_key": "",
                 "composition": '{"Li": 1.3, "Al": 0.3, "Ti": 1.7, "P": 3, "O": 12}'},
                {**ea("b", "Li1.3Ti1.7Al0.3(PO4)3", "0.30", attribution="cited"), "material_key": "",
                 "composition": '{"Li": 1.3, "Ti": 1.7, "Al": 0.3, "P": 3, "O": 12}'}]
        marked = duplicates.mark(rows, "activation_energy")
        self.assertEqual(marked[1]["duplicate_kind"], "cited")

    def test_a_value_only_quoted_has_no_original_paper(self):
        rows = [sigma("a", "Li3InCl6", "1.5e-3", attribution="cited"), sigma("b", "Li3InCl6", "1.5e-3", attribution="cited")]
        marked = duplicates.mark(rows, "ionic_conductivity", years={"a": 2019, "b": 2022})
        self.assertEqual([r["duplicate_kind"] for r in marked], ["", "cited"])
        self.assertEqual({r["original_paper"] for r in marked}, {""})

    def test_activation_energies_of_other_kinds_are_other_measurements(self):
        rows = [ea("a", "Li6PS5Cl", "0.30"), ea("a", "Li6PS5Cl", "0.30", kind="migration_barrier")]
        self.assertEqual([r["duplicate_kind"] for r in duplicates.mark(rows, "activation_energy")], ["", ""])

    def test_the_report_finds_a_quote_in_another_database(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        columns = list(sigma("a", "b", "c"))
        write(base / "local_output" / "ionic_conductivity.csv", columns, [sigma("own", "Li3InCl6", "1.49e-3")])
        write(base / "web_output" / "ionic_conductivity.csv", columns,
              [sigma("review", "Li3InCl6", "1.5e-3", attribution="cited")])
        write(base / "web_output" / "papers.csv", ["paper_id", "publication_year"],
              [{"paper_id": "review", "publication_year": "2024"}])
        result = duplicates.report([base / "local_output", base / "web_output"], base / "out")
        self.assertEqual(result["ionic_conductivity"]["cited"], 1)
        rows = list(csv.DictReader(open(base / "out" / "duplicates_ionic_conductivity.csv", encoding="utf-8-sig")))
        self.assertEqual([(r["database"], r["duplicate_kind"]) for r in rows],
                         [("local_output", ""), ("web_output", "cited")])


class MLExportCountsOnceTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        garnet = self.home / "Classification" / "crystal_structure" / "garnet"
        repeat = dict(ea("p1", "Li7La3Zr2O12", "0.30"), page="9", sentence="In short, 0.30 eV.")
        write(garnet / "activation_energy.csv", EA, [ea("p1", "Li7La3Zr2O12", "0.30"), repeat,
                                                     ea("p2", "Li7La3Zr2O12", "0.34")])

    def settings(self, **values):
        return Settings(**{"family": "garnet", "target": "Ea", "component": "bulk", "origin": "experimental", **values})

    def test_a_repeated_value_is_left_out_with_why(self):
        chosen = export.select(self.settings(), self.home)
        self.assertEqual(len(chosen.kept), 2)
        self.assertEqual(chosen.reasons(), {"the same measurement, repeated in its paper": 1})
        folder = export.generate(self.settings(name="once"), self.home)
        row = next(csv.DictReader(open(folder / "dataset.csv", encoding="utf-8-sig")))
        self.assertEqual((row["n_values"], row["n_measurements"], row["n_papers"]), ("2", "2", "2"))
        self.assertIn("counted once", (folder / "README.md").read_text(encoding="utf-8"))

    def test_kept_when_asked(self):
        chosen = export.select(self.settings(keep_duplicates=True), self.home)
        self.assertEqual(len(chosen.kept), 3)
        folder = export.generate(self.settings(keep_duplicates=True, name="all"), self.home)
        row = next(csv.DictReader(open(folder / "dataset.csv", encoding="utf-8-sig")))
        self.assertEqual((row["n_values"], row["n_measurements"]), ("3", "2"))
        kinds = [r["duplicate_kind"] for r in csv.DictReader(open(folder / "values.csv", encoding="utf-8-sig"))]
        self.assertEqual(sorted(kinds), ["", "", "same paper"])


if __name__ == "__main__":
    unittest.main()
