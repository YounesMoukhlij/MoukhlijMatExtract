# LocalExtraction/tests/test_verification.py
"""A person's checks of the extracted values (verification.py), and the Arrhenius cross-check (arrhenius.py)."""

import csv
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from LocalExtraction import arrhenius
from LocalExtraction.verification import CORRECT, CORRECTED, WRONG, Verifications, apply, row_id, store_path, value_id

ROW = {"paper_id": "A.pdf", "page": "3", "sentence": "LLZO shows  an Ea of 0.30 eV.", "activation_energy_eV": "0.30",
       "material_formula": "Li7La3Zr2O12", "energy_kind": "arrhenius", "transport_component": "total",
       "data_origin": "experimental", "attribution": "this work", "composition": '{"Li": 7}'}


def write(path: Path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_a_value_is_known_again_whatever_the_spacing_of_its_sentence(self):
        self.assertEqual(row_id(ROW), value_id("A.pdf", "3", "LLZO shows an Ea of 0.30 eV.", 0.3, "Li7La3Zr2O12"))
        self.assertNotEqual(row_id(ROW), value_id("A.pdf", "4", "LLZO shows an Ea of 0.30 eV.", 0.3))

    def test_two_materials_of_one_table_with_the_same_number_are_two_values(self):
        """A table gives its caption as the sentence of every row: two of its materials with the same energy must not
        share a check (marking one wrong would leave the other out too)."""
        table = dict(ROW, sentence="Table 3 Summary of electrochemical properties of sulfide electrolytes.",
                     activation_energy_eV="0.37")
        other = dict(table, material_formula="Li4P2S7")
        self.assertNotEqual(row_id(table), row_id(other))
        store = Verifications(self.home / "checks.csv")
        store.set(other, WRONG)
        self.assertIsNone(store.get(row_id(table)))
        checks_of = {row_id(r) for r in (table, other)}
        self.assertEqual(len(checks_of), 2)

    def test_checks_are_kept_outside_the_database_and_read_back(self):
        path = store_path(self.home / "WebScraping" / "web_output_garnet", self.home)
        self.assertEqual(path, self.home / "Verification" / "web_output_garnet.csv")
        store = Verifications(path)
        key = store.set(ROW, CORRECTED, {"material_formula": "Li6.4Ga0.2La3Zr2O12", "energy_kind": "arrhenius"},
                        note="the doped sample")
        again = Verifications(path).get(key)
        self.assertEqual(again.verdict, CORRECTED)
        self.assertEqual(again.corrections, {"material_formula": "Li6.4Ga0.2La3Zr2O12"})  # unchanged fields dropped
        self.assertEqual(again.note, "the doped sample")
        fixed = apply(ROW, again)
        self.assertEqual((fixed["material_formula"], fixed["composition"]), ("Li6.4Ga0.2La3Zr2O12", ""))

    def test_a_correction_that_changes_nothing_is_correct_and_wrong_is_left_out(self):
        store = Verifications(self.home / "v.csv")
        key = store.set(ROW, CORRECTED, {"activation_energy_eV": "0.30"})
        self.assertEqual(store.get(key).verdict, CORRECT)
        store.set(ROW, WRONG)
        self.assertIsNone(apply(ROW, store.get(key)))
        self.assertEqual(store.counts(), {CORRECT: 0, WRONG: 1, CORRECTED: 0})
        digest = store.digest()
        store.clear(key)
        self.assertEqual((len(store), store.digest()), (0, ""))
        self.assertTrue(digest)
        with self.assertRaises(ValueError):
            store.set(ROW, CORRECTED, {"activation_energy_eV": "about 0.3"})


class ArrheniusTests(unittest.TestCase):
    def sigma(self, t, ea=0.30, prefactor=1e5):
        return prefactor / t * math.exp(-ea / (arrhenius.K_B * t))

    def test_the_conductivities_give_back_the_energy_they_were_made_with(self):
        points = [(t, self.sigma(t)) for t in (298.15, 323.15, 348.15, 373.15)]
        sigma_t, sigma = arrhenius.fit(points)
        self.assertAlmostEqual(sigma_t, 0.30, places=6)
        self.assertLess(sigma, 0.30)  # the other convention: lower by about kT
        self.assertEqual(arrhenius.judge(0.30, points).status, arrhenius.CONSISTENT)
        bad = arrhenius.judge(0.10, points)
        self.assertEqual(bad.status, arrhenius.INCONSISTENT)
        self.assertIn("give 0.27 eV (4 temperatures, 298–373 K); reported 0.1 eV", bad.text)  # the nearer fit
        self.assertIsNone(arrhenius.fit([(298.15, 1e-4), (303.15, 2e-4)]))  # 5 K apart: no fit

    def test_a_database_is_checked_value_by_value(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        write(folder / "activation_energy.csv", [
            dict(ROW), dict(ROW, sentence="Another value.", activation_energy_eV="0.10"),
            dict(ROW, paper_id="B.pdf", material_formula="Li3PS4")])
        write(folder / "ionic_conductivity.csv", [
            {"paper_id": "A.pdf", "material_formula": "Li7La3Zr2O12", "ionic_conductivity_S_cm": f"{self.sigma(t):.6e}",
             "temperature": label, "transport_component": "total"}
            for t, label in ((298.15, "room temperature"), (333.15, "333.1 K"), (373.15, "373.1 K"))] + [
            {"paper_id": "B.pdf", "material_formula": "Li3PS4", "ionic_conductivity_S_cm": "1e-4",
             "temperature": "room temperature", "transport_component": "total"}])
        checks = arrhenius.cross_check(folder)
        self.assertEqual(checks[row_id(ROW)].status, arrhenius.CONSISTENT)
        self.assertTrue(checks[row_id(ROW)].room_assumed)
        self.assertEqual(checks[row_id(dict(ROW, sentence="Another value.", activation_energy_eV="0.10"))].status,
                         arrhenius.INCONSISTENT)
        self.assertEqual(checks[row_id(dict(ROW, paper_id="B.pdf", material_formula="Li3PS4"))].status,
                         arrhenius.NOT_CHECKABLE)  # room temperature alone is no series


if __name__ == "__main__":
    unittest.main()
