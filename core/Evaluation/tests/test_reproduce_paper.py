# Evaluation/tests/test_reproduce_paper.py
"""make paper (scripts/reproduce_paper.py): the tables, the figures, the environment and RESULTS.md made from a small
database; the program's commands planned with fixed settings (run here as stand-ins); the evaluation run only when the
workbook has annotated papers."""

import csv
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from Evaluation import sheet
from Evaluation.tests.test_evaluation import MISSED, VERDICTS, _annotate, _write_database

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reproduce_paper.py"
_spec = importlib.util.spec_from_file_location("reproduce_paper", SCRIPT)
reproduce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reproduce)


class ReproducePaperTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = self.base / "web_output"
        _write_database(self.db)
        self.calls = []

    def _run(self, *argv):
        def fake(name, args, logs):
            self.calls.append((name, args))
            return {"step": name, "command": "python " + " ".join(args), "ok": True, "code": 0, "seconds": 0.0}
        with mock.patch.object(reproduce, "run_step", fake), redirect_stdout(io.StringIO()):
            return reproduce.main(["--data", str(self.db), "--out", str(self.base / "paper"), *argv])

    def test_tables_figures_environment_and_results(self):
        self.assertEqual(self._run("--gold", str(self.base / "none.xlsx")), 0)
        out = self.base / "paper"
        summary = {r["property"]: r for r in csv.DictReader(open(out / "tables" / "database_summary.csv"))}
        self.assertEqual(summary["activation_energy"]["values"], "4")
        self.assertEqual(summary["activation_energy"]["papers"], "3")
        self.assertTrue((out / "tables" / "duplicates.csv").is_file())
        env = json.loads((out / "environment.json").read_text())
        self.assertEqual(env["seeds"]["bootstrap"], 7)
        self.assertIn("web_output/activation_energy.csv", env["inputs"])
        self.assertTrue(env["packages"])
        self.assertEqual([name for name, _ in self.calls], ["ranking", "classification"])
        ranking = self.calls[0][1]
        self.assertEqual(ranking[ranking.index("--out") + 1], str((out / "ranking").resolve()))
        text = (out / "RESULTS.md").read_text()
        self.assertIn("has no paper marked done yet", text)
        self.assertIn("| activation energy | 4 |", text)

    def test_the_evaluation_runs_when_papers_are_annotated(self):
        made, gold = self.base / "a.xlsx", self.base / "done.xlsx"
        sheet.make([self.db], made, count=10, seed=7, version="test")
        _annotate(made, gold, VERDICTS, MISSED)
        self.assertEqual(self._run("--gold", str(gold), "--tool", "CDE=cde.csv"), 0)
        names = [name for name, _ in self.calls]
        self.assertEqual(names, ["ranking", "classification", "evaluation-score", "evaluation-benchmark"])
        bench = self.calls[-1][1]
        self.assertEqual(bench[bench.index("--seed") + 1], "7")
        self.assertIn("CDE=cde.csv", bench)

    def test_no_data_is_said(self):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(reproduce.main(["--data", str(self.base / "missing"), "--out", str(self.base / "p")]), 1)
        self.assertIn("No results folder", err.getvalue())


if __name__ == "__main__":
    unittest.main()
