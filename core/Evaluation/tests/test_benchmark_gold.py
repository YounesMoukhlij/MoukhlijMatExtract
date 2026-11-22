# Evaluation/tests/test_benchmark_gold.py
"""mme-eval benchmark (MoukhlijMatExtract, the keyword baseline and other tools on the same annotated papers) and
mme-eval gold (the annotated papers as a public dataset): on the small database of test_evaluation, whose right
answers are known, with PDFs written for the test."""

import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import openpyxl
import pandas as pd

from Evaluation import baseline, benchmark, cli, gold, score, sheet
from Evaluation.tests.test_evaluation import MISSED, VERDICTS, _annotate, _write_database

TEXTS = {  # what each test paper says
    "p1.pdf": "We report Li6PS5Cl. The activation energy of Li6PS5Cl is 0.31 eV in the bulk.",
    "p2.pdf": "The activation energy of Na3PSe4 is 0.25 eV.",
    "p3.pdf": "The conductivity of Li3InCl6 is 1.49 x 10^-3 S cm-1. Its activation energy is 0.33 eV.",
    "p4.pdf": "Li10GeP2S12 shows a bulk conductivity of 12 mS/cm at room temperature.",
}


class BaselineTests(unittest.TestCase):
    def test_values_with_their_units_and_powers_of_ten(self):
        cases = [("The ionic conductivity reached 1.2 × 10−3 S cm−1 for Li7La3Zr2O12.", "Li7La3Zr2O12", 1.2e-3),
                 ("Conductivities of 10− 4 –10− 3 S cm−1 were found.", "", 1e-3),
                 ("Its conductivity is 1.2e-3 S/cm.", "", 1.2e-3),
                 ("A conductivity of 12 mS/cm in Li10GeP2S12.", "Li10GeP2S12", 0.012),
                 ("The activation energy of Li6PS5Cl is 0.35 eV.", "Li6PS5Cl", 0.35),
                 ("The activation energy is 350 meV.", "", 0.35),
                 ("The diffusion coefficient is 3.4 × 10−9 cm2 s−1.", "", 3.4e-9)]
        for text, material, value in cases:
            found = baseline.find_in_text(text)
            self.assertEqual(len(found), 1, text)
            self.assertEqual(found[0].material, material, text)
            self.assertAlmostEqual(found[0].value, value, delta=value * 1e-6, msg=text)

    def test_an_exponent_is_never_read_as_a_value(self):
        for text in ("The conductivity is 10−10–10−12 S cm−1.", "No conductivity was measured.",
                     "The band gap is 3.1 eV."):
            self.assertEqual(baseline.find_in_text(text), [], text)


class BenchmarkAndGoldTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = self.base / "web_output"
        _write_database(self.db)
        made = self.base / "annotation.xlsx"
        sheet.make([self.db], made, count=10, seed=7, version="test")
        self.book = self.base / "done.xlsx"
        _annotate(made, self.book, VERDICTS, MISSED)
        self._link_pdfs(self.book)

    def _link_pdfs(self, book_path: Path) -> None:
        import pymupdf
        folder = self.base / "pdfs"
        folder.mkdir(exist_ok=True)
        for name, text in TEXTS.items():
            document = pymupdf.open()
            document.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
            document.save(folder / name)
            document.close()
        book = openpyxl.load_workbook(book_path)
        papers = book["Papers"]
        head = [c.value for c in papers[1]]
        for row in papers.iter_rows(min_row=2):
            cell = row[head.index("pdf")]
            cell.hyperlink, cell.value = (folder / row[head.index("paper_id")].value).as_uri(), "open the PDF"
        book.save(book_path)

    def test_the_baseline_reads_the_pdfs_behind_the_links(self):
        annotation = score.read_annotation(self.book)
        self.assertEqual(len(baseline.pdf_paths(self.book)), 4)
        found = baseline.predict(annotation, self.book)
        self.assertEqual({(i.paper, i.prop, round(i.value, 6)) for i in found},
                         {("p1.pdf", "activation_energy", 0.31), ("p2.pdf", "activation_energy", 0.25),
                          ("p3.pdf", "ionic_conductivity", 0.00149), ("p3.pdf", "activation_energy", 0.33),
                          ("p4.pdf", "ionic_conductivity", 0.012)})

    def test_the_benchmark_scores_every_system_and_writes_its_files(self):
        tool = self.base / "cde.csv"
        pd.DataFrame([{"paper_id": "p1.pdf", "property": "activation_energy", "material": "Li6PS5Cl", "value": "0.31",
                       "unit": "eV"}]).to_csv(tool, index=False)
        out = self.base / "bench"
        result = benchmark.run(self.book, out, tools=[f"ChemDataExtractor={tool}"])
        self.assertEqual(list(result["systems"]), ["MoukhlijMatExtract", "Keyword baseline", "ChemDataExtractor"])
        base = result["systems"]["Keyword baseline"]["levels"]["record"]["all"]
        # Every gold value is in the PDFs; only "Its activation energy is 0.33 eV" names no material (record level)
        self.assertEqual((base["tp"], base["fp"], base["fn"]), (4, 1, 1))
        value = result["systems"]["Keyword baseline"]["levels"]["value"]["all"]
        self.assertEqual((value["tp"], value["fp"], value["fn"]), (5, 0, 0))
        cde = result["systems"]["ChemDataExtractor"]["levels"]["record"]["all"]
        self.assertEqual((cde["tp"], cde["fp"], cde["fn"]), (1, 0, 4))
        for name in ("benchmark.md", "benchmark.csv", "benchmark.png", "baseline_predictions.csv", "run_manifest.json"):
            self.assertTrue((out / name).is_file(), name)
        text = (out / "benchmark.md").read_text(encoding="utf-8")
        self.assertIn("Keyword baseline", text)
        self.assertIn("ChemDataExtractor", text)
        self.assertIn("Adding another method", text)
        table = list(csv.DictReader(open(out / "benchmark.csv", encoding="utf-8-sig")))
        self.assertEqual({r["system"] for r in table}, {"MoukhlijMatExtract", "Keyword baseline", "ChemDataExtractor"})
        self.assertTrue(all(r["level"] in ("record", "value") for r in table))

    def test_the_benchmark_says_when_nothing_is_annotated(self):
        made = self.base / "fresh.xlsx"
        sheet.make([self.db], made, count=10, seed=7, version="test")
        with self.assertRaisesRegex(score.AnnotationError, "done"):
            benchmark.run(made, self.base / "bench")

    def test_a_tool_named_by_its_file_alone(self):
        self.assertEqual(benchmark.parse_tool("llm.csv"), ("llm", Path("llm.csv")))
        self.assertEqual(benchmark.parse_tool("LLM prompt=out/llm.csv"), ("LLM prompt", Path("out/llm.csv")))

    def test_the_command(self):
        cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(cwd))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "enter_project_home"), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["benchmark", "--gold", str(self.book), "--out", str(self.base / "b"), "--no-baseline"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("MoukhlijMatExtract", out.getvalue())
        self.assertNotIn("Keyword baseline", out.getvalue())

    def test_the_gold_standard_dataset(self):
        papers = pd.read_csv(self.db / "papers.csv", dtype=str)
        papers["license"] = ["CC BY 4.0", "", "CC BY 4.0", ""]  # p2 and p4: no licence stated
        papers.to_csv(self.db / "papers.csv", index=False)
        folder = gold.export(self.book, self.base / "gold", name="test_set", sources=[self.db])
        self.assertEqual(folder, self.base / "gold" / "test_set")
        rows = list(csv.DictReader(open(folder / "gold.csv", encoding="utf-8")))
        # correct p1, p3 ×2; partly p2 (corrected material); missed p4 — the wrong one is not a reference value
        self.assertEqual(sorted((r["paper_id"], r["kind"]) for r in rows),
                         [("p1.pdf", "correct"), ("p2.pdf", "partly"), ("p3.pdf", "correct"), ("p3.pdf", "correct"),
                          ("p4.pdf", "missed")])
        partly = next(r for r in rows if r["kind"] == "partly")
        self.assertEqual(partly["material"], "Na3PSe4")
        self.assertEqual(next(r for r in rows if r["kind"] == "missed")["value"], "0.012")
        self.assertEqual(partly["sentence"], "")  # no licence: not quoted
        self.assertEqual(next(r for r in rows if r["paper_id"] == "p1.pdf")["sentence"], "s")
        listed = list(csv.DictReader(open(folder / "papers.csv", encoding="utf-8")))
        self.assertEqual({r["paper_id"]: r["reference_values"] for r in listed},
                         {"p1.pdf": "1", "p2.pdf": "1", "p3.pdf": "2", "p4.pdf": "1"})
        meta = json.loads((folder / ".zenodo.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["upload_type"], meta["license"]), ("dataset", "cc-by-4.0"))
        self.assertTrue(meta["creators"][0]["name"])
        self.assertIn("Annotation guide", (folder / "annotation_guide.md").read_text(encoding="utf-8"))
        readme = (folder / "README.md").read_text(encoding="utf-8")
        self.assertIn("5 values", readme)
        self.assertIn("sentences of other papers were left out", readme)
        sums = dict(line.split("  ")[::-1] for line in (folder / "SHA256SUMS").read_text().splitlines())
        self.assertEqual(sums["gold.csv"], hashlib.sha256((folder / "gold.csv").read_bytes()).hexdigest())
        self.assertNotIn("agreement.json", sums)

    def test_the_agreement_of_two_annotators_goes_in_the_set(self):
        folder = gold.export(self.book, self.base / "gold", second=self.book, sources=[self.db])
        agreed = json.loads((folder / "agreement.json").read_text(encoding="utf-8"))
        self.assertEqual(agreed["kappa"], 1.0)
        self.assertIn("Cohen's kappa 1.00", (folder / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
