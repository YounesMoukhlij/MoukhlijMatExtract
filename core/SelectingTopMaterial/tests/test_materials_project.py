# SelectingTopMaterial/tests/test_materials_project.py
"""The ranked materials beside their Materials Project entries (computed data: stability, band gap, space group).
No network: a fake Materials Project answers."""

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from WebScraping.tests.test_web import FakeResponse, FakeSession, client_for  # also: offline, sys.path
from SelectingTopMaterial import materials_project as mp
from SelectingTopMaterial.criteria import Criteria
from SelectingTopMaterial.selection import select
from SelectingTopMaterial.tests.test_selection import value

ENTRIES = {
    "Li7La3Zr2O12": [
        {"material_id": "mp-942733", "formula_pretty": "Li7La3Zr2O12", "energy_above_hull": 0.0, "band_gap": 4.3,
         "symmetry": {"symbol": "I4_1/acd"}, "theoretical": False},
        {"material_id": "mp-1", "formula_pretty": "Li7La3Zr2O12", "energy_above_hull": 0.05, "band_gap": 4.0,
         "symmetry": {"symbol": "Ia-3d"}, "theoretical": True}],
    "Li6PS5Cl": [{"material_id": "mp-985592", "formula_pretty": "Li6PS5Cl", "energy_above_hull": 0.021,
                  "band_gap": 2.0, "symmetry": {"symbol": "F-43m"}, "theoretical": False}],
}


def answers(url, params, headers):
    return FakeResponse(200, json_data={"data": ENTRIES.get(params.get("formula"), [])})


class MaterialsProjectTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out, True)
        self.session = FakeSession([("api.materialsproject.org", answers)])
        self.client = client_for(self.session)

    def test_the_reduced_formula_and_none_for_a_variable_composition(self):
        self.assertEqual(mp.reduced("Li12P2S10Cl2"), "Li6PS5Cl")
        self.assertEqual(mp.reduced("Li7 La3 Zr2 O12"), "Li7La3Zr2O12")
        self.assertIsNone(mp.reduced("Li7-3xLa3Zr1.9GaxGe0.1O12"))
        self.assertIsNone(mp.reduced("LLZO"))

    def test_the_most_stable_entry_one_request_per_formula_with_the_key(self):
        found = mp.lookup(["Li7La3Zr2O12", "Li14La6Zr4O24", "Li6PS5Cl", "Li3PS4"], self.client, "the-key")
        self.assertEqual(found["Li7La3Zr2O12"]["material_id"], "mp-942733")  # 0 eV above the hull, not 0.05
        self.assertIsNone(found["Li3PS4"])
        self.assertEqual(self.session.hits("api.materialsproject.org"), 3)  # Li14La6Zr4O24 is Li7La3Zr2O12
        _, params, headers = self.session.calls[0]
        self.assertEqual(headers["X-API-KEY"], "the-key")
        self.assertIn("energy_above_hull", params["_fields"])

    def test_the_ranking_written_beside_its_entries(self):
        values = [value("Li6PS5Cl", 0.20), value("Li7La3Zr2O12", 0.30), value("Li6.4La3Zr1.4Ta0.6O12", 0.35)]
        selections = {"total": select(values, Criteria.load(), bootstrap=0)}
        path = mp.link(selections, self.out, client=self.client, key="the-key")
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        self.assertEqual([(r["rank"], r["material"], r["mp_id"]) for r in rows],
                         [("1", "Li6PS5Cl", "mp-985592"), ("2", "Li7La3Zr2O12", "mp-942733"),
                          ("3", "Li6.4La3Zr1.4Ta0.6O12", "")])
        self.assertEqual(rows[0]["mp_url"], "https://next-gen.materialsproject.org/materials/mp-985592")
        self.assertEqual((rows[0]["energy_above_hull_eV"], rows[0]["space_group"]), ("0.021", "F-43m"))
        self.assertIn("no entry", rows[2]["note"])

    def test_without_a_key_nothing_is_asked(self):
        selections = {"total": select([value("Li6PS5Cl", 0.20)], Criteria.load(), bootstrap=0)}
        with self.assertLogs(level="WARNING") as said:
            self.assertIsNone(mp.link(selections, self.out, client=self.client, key=""))
        self.assertIn("MP_API_KEY", "\n".join(said.output))
        self.assertEqual(self.session.calls, [])


class CommandTests(unittest.TestCase):
    def test_materials_project_asks_after_the_ranking_is_written(self):
        from unittest import mock
        from SelectingTopMaterial.tests.test_selection import CommandLineTests
        harness = CommandLineTests("test_from_a_database_to_the_files")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        calls = []
        with mock.patch.object(mp, "link", side_effect=lambda selections, out_dir, **k: calls.append(
                (sorted(selections), out_dir)) or Path(out_dir) / mp.FILE):
            code, said, _ = harness.run_cli("--source", str(harness.database), "--out", str(harness.out),
                                            "--materials-project")
            self.assertEqual(code, 0)
            self.assertEqual(calls, [(["bulk", "grain_boundary", "total"], harness.out)])
            self.assertIn("Materials Project entries:", said)
            harness.run_cli("--source", str(harness.database), "--out", str(harness.out), "--force")
        self.assertEqual(len(calls), 1)  # not asked without the option


if __name__ == "__main__":
    unittest.main()
