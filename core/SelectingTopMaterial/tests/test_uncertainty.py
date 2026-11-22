# SelectingTopMaterial/tests/test_uncertainty.py
"""How sure a ranking is (rank intervals, evidence tiers), and the checks a person made of the values (verified,
corrected, marked wrong) and the Arrhenius cross-check, as the ranking takes them."""

from __future__ import annotations

import csv
import math
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from LocalExtraction.verification import CORRECTED, WRONG, Verifications
from SelectingTopMaterial import exporters, loader
from SelectingTopMaterial.criteria import Criteria
from SelectingTopMaterial.models import Filters
from SelectingTopMaterial.selection import _resampled, evidence_tier, rank_intervals, representative, select, \
    select_from_each
from SelectingTopMaterial.tests.test_selection import row, value, write_database


class ResamplingTests(unittest.TestCase):
    def test_the_fast_median_is_the_median_of_the_ranking(self):
        """Every resampling's energy is what `representative` gives for the same values: ties, values of no weight,
        groups with no weight at all."""
        rng = random.Random(3)
        for _ in range(200):
            n = rng.randint(1, 6)
            group = [value("Li6PS5Cl", round(rng.choice([0.2, 0.25, 0.3, rng.uniform(0.1, 0.6)]), 3),
                           confidence=rng.choice([0.0, 0.5, 0.8, 1.0])) for _ in range(n)]
            for policy in ("consensus", "optimistic", "conservative"):
                generator = np.random.default_rng(7)
                fast = _resampled(group, policy, generator, 5)
                picks = np.random.default_rng(7).integers(0, n, size=(5, n))
                slow = [representative([group[i] for i in pick], policy) for pick in picks]
                self.assertEqual(list(fast), slow, (policy, [(v.energy_eV, v.confidence) for v in group]))

    def test_well_separated_materials_have_certain_ranks_and_close_ones_do_not(self):
        apart = [[value("A", 0.20 + 0.001 * i) for i in range(4)], [value("B", 0.50 + 0.001 * i) for i in range(4)]]
        self.assertEqual(rank_intervals(apart, "consensus", rounds=300, top=1), [(1, 1, 1.0), (2, 2, 0.0)])
        close = [[value("A", e) for e in (0.20, 0.35)], [value("B", e) for e in (0.25, 0.30)]]
        (low_a, high_a, p_a), _ = rank_intervals(close, "consensus", rounds=300, top=1)
        self.assertEqual((low_a, high_a), (1, 2))
        self.assertTrue(0 < p_a < 1)
        self.assertEqual(rank_intervals(close, "consensus", rounds=300, top=1),
                         rank_intervals(close, "consensus", rounds=300, top=1))  # the same seed, the same intervals

    def test_the_evidence_tier_says_how_many_values_and_papers(self):
        self.assertEqual(evidence_tier([value("A", 0.2)]), "C")
        self.assertEqual(evidence_tier([value("A", 0.2), value("A", 0.3)]), "B")
        self.assertEqual(evidence_tier([value("A", 0.2), value("A", 0.3), value("A", 0.25, paper_key="B.pdf")]), "A")

    def test_the_ranking_carries_them_and_the_files_show_them(self):
        values = [value("Li6PS5Cl", e) for e in (0.20, 0.22, 0.21)] + [value("Li3PS4", 0.40)]
        selection = select(values, Criteria.load())
        first, second = selection.materials
        self.assertEqual((first.rank_low, first.rank_high, first.p_top, first.evidence_tier), (1, 1, 1.0, "B"))
        self.assertEqual(second.evidence_tier, "C")
        row = exporters.material_row(first)
        self.assertEqual((row["rank_95"], row["p_top10"], row["evidence"], row["verified"]), ("1", 1.0, "B", "0 of 3"))
        self.assertIn(("Rank intervals", next(a for w, a in exporters.rule_rows(selection) if w == "Rank intervals")),
                      exporters.rule_rows(selection))
        self.assertEqual(select(values, Criteria.load(), bootstrap=0).materials[0].rank_high, 0)


class CheckedValueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.rows = [row("Li6PS5Cl", 0.22), row("Li6PS5Cl", 0.24, paper="B.pdf"), row("Li3PS4", 0.05),
                     row("Li7La3Zr2O12", 0.35)]
        self.db = write_database(self.tmp / "web_output", self.rows)
        self.home = self.tmp / "home"

    def ranked(self, **filters):
        return select_from_each([self.db], Criteria.load(), filters=Filters(component="total", **filters),
                                verifications=self.home, bootstrap=50)["total"]

    def test_a_value_marked_wrong_takes_no_part_and_a_corrected_one_takes_part_as_corrected(self):
        store = Verifications.of(self.db, self.home)
        store.set(self.rows[2], WRONG)                                     # the 0.05 eV misreading
        store.set(self.rows[3], CORRECTED, {"activation_energy_eV": "0.45"})
        store.set(self.rows[0], "correct")
        selection = self.ranked()
        names = {m.material: m for m in selection.materials}
        self.assertNotIn("Li3PS4", names)
        self.assertEqual(names["Li7La3Zr2O12"].energy_eV, 0.45)
        self.assertEqual(names["Li7La3Zr2O12"].values[0].verification, CORRECTED)
        report = selection.databases[0]
        self.assertEqual((report.marked_wrong, report.verified), (1, 2))
        self.assertIn("2 values checked by hand, 1 marked wrong (left out)", loader.describe(report))
        only = self.ranked(verified_only=True)
        self.assertEqual(sorted(m.material for m in only.materials), ["Li6PS5Cl", "Li7La3Zr2O12"])
        self.assertEqual(only.materials[0].values[0].energy_eV, 0.22)  # the unchecked 0.24 is not in it

    def test_the_checks_are_part_of_the_rankings_fingerprint(self):
        from SelectingTopMaterial.cli import ranking_settings
        from LocalExtraction import about
        from unittest import mock
        with mock.patch.object(about, "PROJECT_HOME", self.home):
            before = ranking_settings([self.db], Criteria.load(), None, False, Filters(), None, ["csv"])
            Verifications.of(self.db).set(self.rows[2], WRONG)
            after = ranking_settings([self.db], Criteria.load(), None, False, Filters(), None, ["csv"])
        self.assertNotEqual(before["checked_by_hand"], after["checked_by_hand"])

    def test_a_value_its_papers_conductivities_disagree_with_is_flagged(self):
        sigma = lambda t: 1e5 / t * math.exp(-0.30 / (8.617333262e-5 * t))  # noqa: E731
        with open(self.db / "ionic_conductivity.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["paper_id", "material_formula", "ionic_conductivity_S_cm",
                                                   "temperature", "transport_component"])
            writer.writeheader()
            for t in (300.0, 340.0, 380.0):
                writer.writerow({"paper_id": "A.pdf", "material_formula": "Li7La3Zr2O12",
                                 "ionic_conductivity_S_cm": f"{sigma(t):.6e}", "temperature": f"{t:g} K",
                                 "transport_component": "total"})
        llzo = next(m for m in self.ranked().materials if m.material == "Li7La3Zr2O12")
        self.assertEqual(llzo.values[0].arrhenius, "consistent")  # 0.35 reported, 0.30 fitted: within 0.07
        Verifications.of(self.db, self.home).set(self.rows[3], CORRECTED, {"activation_energy_eV": "0.60"})
        llzo = next(m for m in self.ranked().materials if m.material == "Li7La3Zr2O12")
        self.assertIn("Arrhenius fit disagrees (1 value)", llzo.checks)  # the corrected number is judged anew


if __name__ == "__main__":
    unittest.main()
