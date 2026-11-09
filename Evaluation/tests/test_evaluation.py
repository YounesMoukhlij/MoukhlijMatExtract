# Evaluation/tests/test_evaluation.py
"""mme-eval: numbers and units read as an annotator writes them, materials compared by composition, the
matching, the scores on a small database whose right answers are known, the workbook (drawn the same
way twice, never overwritten), the annotations checked, and the agreement of two annotators."""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import openpyxl
import pandas as pd

from Evaluation import cli, compare, score, sheet


class NumbersAndUnitsTests(unittest.TestCase):
    def test_numbers_as_people_write_them(self):
        for text, expected in [("0.31", 0.31), ("0,31", 0.31), ("1.16e-3", 1.16e-3), ("1.16 × 10−3", 1.16e-3),
                               ("1.16x10^-3", 1.16e-3), ("10^-4", 1e-4), ("10−4", 1e-4), (0.5, 0.5)]:
            self.assertAlmostEqual(compare.parse_number(text), expected, msg=text)
        for text in ("", "about 0.3", "n/a", None, float("nan")):
            self.assertIsNone(compare.parse_number(text), text)

    def test_units_to_the_database_unit(self):
        cases = [("activation_energy", "310", "meV", 0.31), ("activation_energy", "29.9", "kJ/mol", 0.30989),
                 ("ionic_conductivity", "1.16", "mS cm−1", 1.16e-3), ("ionic_conductivity", "0.1", "S/m", 1e-3),
                 ("ionic_conductivity", "5", "µS/cm", 5e-6), ("diffusion_coefficient", "1e-12", "m2/s", 1e-8),
                 ("diffusion_coefficient", "3e-9", "cm² s⁻¹", 3e-9), ("activation_energy", "0.3", "", 0.3),
                 # glued, as ChemDataExtractor writes them
                 ("ionic_conductivity", "0.5", "mScm-1", 5e-4), ("ionic_conductivity", "1.6e-4", "Scm−1", 1.6e-4),
                 ("ionic_conductivity", "2", "Sm-1", 2e-2), ("activation_energy", "29.9", "kJmol-1", 0.30989)]
        for prop, value, unit, expected in cases:
            number, why = compare.to_database_unit(prop, value, unit)
            self.assertAlmostEqual(number / expected, 1.0, places=3, msg=(value, unit, why))
        number, why = compare.to_database_unit("activation_energy", "0.3", "furlong")
        self.assertIsNone(number)
        self.assertIn("furlong", why)

    def test_same_value_within_the_tolerance(self):
        self.assertTrue(compare.same_value("activation_energy", 0.310, 0.311))
        self.assertFalse(compare.same_value("activation_energy", 0.30, 0.31))
        self.assertTrue(compare.same_value("ionic_conductivity", 1.16e-3, 1.17e-3))
        self.assertFalse(compare.same_value("ionic_conductivity", 1.16e-3, 1.16e-4))  # a decade apart


class MaterialTests(unittest.TestCase):
    def test_the_same_composition_written_two_ways(self):
        self.assertTrue(compare.same_material("Li6PS5Cl", "Li12P2S10Cl2"))
        self.assertTrue(compare.same_material("Li 6 PS 5 Cl", "Li6PS5Cl"))
        self.assertTrue(compare.same_material("Li6.4La3Zr1.4Ta0.6O12", "Li6.4La3Zr1.4Ta0.6O12"))
        self.assertTrue(compare.same_material("LLZO", "llzo"))  # names: the same text

    def test_different_materials(self):
        self.assertFalse(compare.same_material("PSe", "Na3PSe4"))
        self.assertFalse(compare.same_material("Li6PS5Cl", "Li6PS5Br"))
        self.assertFalse(compare.same_material("Li7La3Zr2O12", "Li6.4La3Zr1.4Ta0.6O12"))
        self.assertFalse(compare.same_material("", "Li6PS5Cl"))


class MatchingTests(unittest.TestCase):
    def test_the_largest_matching(self):
        # a greedy choice (0 -> 0) would leave 1 alone; the largest matching pairs both
        pairs = compare.max_matching(["a", "b"], ["x", "y"], lambda l, r: (l, r) in {("a", "x"), ("a", "y"), ("b", "x")})
        self.assertEqual(len(pairs), 2)
        self.assertIn((1, 0), pairs)

    def test_agreeing_partners_are_preferred(self):
        def item(component):
            return score.Item("p", "activation_energy", "Li6PS5Cl", 0.3, component=component)
        extracted, gold = [item("bulk"), item("total")], [item("total"), item("bulk")]
        found = score.match(extracted, gold)[("p", "activation_energy")]
        self.assertTrue(all(e.component == g.component for e, g in found.record))


# ---- a small database whose right answers are known --------------------------------------------------

def _write_database(folder: Path) -> None:
    folder.mkdir(parents=True)
    pd.DataFrame([{"paper_id": f"p{n}.pdf", "filename": f"p{n}.pdf", "title": f"Paper {n}", "doi": f"10.1/p{n}",
                   "publication_year": "2024", "source_url": f"file:///papers/p{n}.pdf", "file_sha256": f"s{n}",
                   "source_service": "unpaywall"}
                  for n in range(1, 5)]).to_csv(folder / "papers.csv", index=False)
    rows = [  # paper, material, value, component
        ("p1.pdf", "Li6PS5Cl", "0.31", "bulk"),     # correct
        ("p1.pdf", "Li6PS5Cl", "2.07", "total"),    # wrong: an electron-transfer barrier
        ("p2.pdf", "PSe", "0.25", "total"),         # partly: the material is Na3PSe4
        ("p3.pdf", "Li3InCl6", "0.33", "bulk"),     # correct
    ]
    pd.DataFrame([{"paper_id": p, "title": "t", "material_formula": m, "activation_energy_eV": v,
                   "transport_component": c, "data_origin": "experimental", "extracted_from": "Text",
                   "confidence": "0.7", "sentence": "s"} for p, m, v, c in rows]).to_csv(
        folder / "activation_energy.csv", index=False)
    pd.DataFrame([{"paper_id": "p3.pdf", "title": "t", "material_formula": "Li3InCl6", "ionic_conductivity_S_cm": "0.00149",
                   "transport_component": "total", "data_origin": "experimental", "extracted_from": "Table",
                   "confidence": "0.9", "sentence": "s"}]).to_csv(folder / "ionic_conductivity.csv", index=False)


def _annotate(path: Path, out: Path, verdicts, missed=(), done=None):
    book = openpyxl.load_workbook(path)
    values, papers, missed_sheet = book["Values"], book["Papers"], book["Missed"]
    head = [c.value for c in values[1]]
    for row in values.iter_rows(min_row=2):
        key = (row[head.index("paper_id")].value, row[head.index("value")].value)
        for name, value in verdicts.get(key, {}).items():
            row[head.index(name)].value = value
    phead = [c.value for c in papers[1]]
    for row in papers.iter_rows(min_row=2):
        if done is None or row[phead.index("paper_id")].value in done:
            row[phead.index("done")].value = "yes"
    for n, record in enumerate(missed, start=2):
        for col, value in enumerate(record, start=1):
            missed_sheet.cell(row=n, column=col, value=value)
    book.save(out)


VERDICTS = {
    ("p1.pdf", 0.31): {"verdict": "correct"},
    ("p1.pdf", 2.07): {"verdict": "wrong", "error_type": "wrong ion or species"},
    ("p2.pdf", 0.25): {"verdict": "partly", "true_material": "Na3PSe4", "error_type": "wrong material"},
    ("p3.pdf", 0.33): {"verdict": "correct"},
    ("p3.pdf", 0.00149): {"verdict": "correct"},
}
# p4 has no extracted value, but reports one: missed (in mS/cm, as the paper writes it)
MISSED = [("p4.pdf", "ionic_conductivity", "Li10GeP2S12", "12", "mS/cm", "bulk", "experimental")]


class WorkbookAndScoreTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = self.base / "web_output"
        _write_database(self.db)
        self.book = self.base / "annotation.xlsx"
        sheet.make([self.db], self.book, count=10, seed=7, version="test")

    def test_the_workbook_holds_every_paper_and_value(self):
        book = openpyxl.load_workbook(self.book)
        self.assertEqual(book.sheetnames, ["Guide", "Papers", "Values", "Missed", "About"])
        self.assertEqual(book["Papers"].max_row - 1, 4)   # p4, without values, is drawn too
        self.assertEqual(book["Values"].max_row - 1, 5)
        self.assertTrue(book["Values"].data_validations.dataValidation)  # drop-down lists

    def test_papers_without_any_value_still_make_a_workbook(self):
        for name in ("activation_energy", "ionic_conductivity"):  # a database with papers but no value yet
            path = self.db / f"{name}.csv"
            pd.read_csv(path).iloc[0:0].to_csv(path, index=False)
        book = self.base / "empty.xlsx"
        sheet.make([self.db], book, count=2, seed=1, version="test")
        workbook = openpyxl.load_workbook(book)
        self.assertEqual(workbook["Papers"].max_row - 1, 2)
        self.assertEqual(workbook["Values"].max_row, 1)  # the header only: the missed values go in "Missed"

    def test_only_papers_with_a_legal_copy_are_drawn(self):
        papers = pd.read_csv(self.db / "papers.csv", dtype=str, keep_default_na=False)
        papers["source_service"] = ["unpaywall", "a file of this computer", "pmc", "already in the folder"][:len(papers)]
        papers.to_csv(self.db / "papers.csv", index=False)
        log = self.base / "scrape_log.csv"  # the earlier downloader: p3 came from a shadow library, then legally again
        pd.DataFrame([{"doi": papers.loc[2, "doi"] or "10.1/p3", "title": "", "result": "saved", "source": "Sci-Hub",
                       "file": "p3.pdf", "tried_at": "2026"}]).to_csv(log, index=False)
        book = self.base / "legal.xlsx"
        counts = sheet.make([self.db], book, count=10, seed=7, version="test", legal_only=True, log=log)
        rows = list(openpyxl.load_workbook(book)["Papers"].values)
        drawn = sorted(row[rows[0].index("paper_id")] for row in rows[1:])
        self.assertEqual(counts["left_out"], 2)
        self.assertEqual(len(drawn), 2)
        self.assertTrue(all(paper_id.startswith(("p1", "p3")) for paper_id in drawn), drawn)

    def test_the_draw_is_the_same_for_the_same_seed(self):
        databases = [sheet.read_database(self.db)]
        first = sheet.sample_papers(databases, 2, seed=3)["paper_id"].tolist()
        self.assertEqual(first, sheet.sample_papers(databases, 2, seed=3)["paper_id"].tolist())
        self.assertEqual(len(first), 2)

    def test_the_scores_of_a_known_case(self):
        annotated = self.base / "done.xlsx"
        _annotate(self.book, annotated, VERDICTS, MISSED)
        annotation = score.read_annotation(annotated)
        self.assertEqual(annotation.warnings, [])
        metrics = score.evaluate(annotation)
        # gold: 0.31, 0.25 (Na3PSe4), 0.33, 1.49e-3, 1.2e-2 = 5; extracted: 5
        record = metrics["levels"]["record"]["all"]
        self.assertEqual((record["tp"], record["fp"], record["fn"]), (3, 2, 2))
        value = metrics["levels"]["value"]["all"]
        self.assertEqual((value["tp"], value["fp"], value["fn"]), (4, 1, 1))  # PSe: right value, wrong material
        self.assertAlmostEqual(value["precision"], 0.8)
        self.assertEqual(metrics["error_types"], {"wrong ion or species": 1, "wrong material": 1})
        self.assertEqual(metrics["fields"]["component"]["accuracy"], 1.0)

        out = self.base / "scores"
        paths = score.write_report(out, metrics, annotation, "test", {})
        errors = pd.read_csv(paths["errors"])
        self.assertEqual(sorted(errors["error"]), ["false positive", "false positive", "missed", "wrong material"])
        self.assertTrue(errors["title"].notna().all())
        self.assertIn("Record level", paths["report"].read_text(encoding="utf-8"))

    def test_only_the_papers_marked_done_count(self):
        annotated = self.base / "half.xlsx"
        _annotate(self.book, annotated, VERDICTS, done={"p1.pdf"})
        metrics = score.evaluate(score.read_annotation(annotated))
        self.assertEqual(metrics["papers"], 1)
        self.assertEqual(metrics["extracted"], 2)

    def test_a_paper_done_with_a_value_left_unjudged_is_left_out_and_said(self):
        annotated = self.base / "gap.xlsx"
        verdicts = {k: v for k, v in VERDICTS.items() if k != ("p3.pdf", 0.33)}
        _annotate(self.book, annotated, verdicts)
        annotation = score.read_annotation(annotated)
        self.assertNotIn("p3.pdf", annotation.done)
        self.assertTrue(any("p3.pdf" in w for w in annotation.warnings))

    def test_a_mistake_in_the_annotations_says_where(self):
        annotated = self.base / "bad.xlsx"
        _annotate(self.book, annotated, {**VERDICTS, ("p1.pdf", 0.31): {"verdict": "maybe"}})
        with self.assertRaisesRegex(score.AnnotationError, "row 2.*maybe"):
            score.read_annotation(annotated)
        _annotate(self.book, annotated, VERDICTS, [("p4.pdf", "ionic_conductivity", "LGPS", "12", "furlong")])
        with self.assertRaisesRegex(score.AnnotationError, "Missed sheet, row 2.*furlong"):
            score.read_annotation(annotated)

    def test_a_newer_run_is_scored_against_the_same_reference(self):
        annotated = self.base / "done.xlsx"
        _annotate(self.book, annotated, VERDICTS, MISSED)
        annotation = score.read_annotation(annotated)
        # the new version drops the wrong 2.07 eV and gets Na3PSe4 right
        table = pd.read_csv(self.db / "activation_energy.csv", dtype=str)
        table = table[table["activation_energy_eV"] != "2.07"]
        table.loc[table["material_formula"] == "PSe", "material_formula"] = "Na3PSe4"
        table.to_csv(self.db / "activation_energy.csv", index=False)
        metrics = score.evaluate(annotation, score.extracted_from_databases(annotation, [self.db]))
        record = metrics["levels"]["record"]["all"]
        self.assertEqual((record["tp"], record["fp"], record["fn"]), (4, 0, 1))

    def test_two_annotators(self):
        first, second = self.base / "a.xlsx", self.base / "b.xlsx"
        _annotate(self.book, first, VERDICTS, MISSED)
        _annotate(self.book, second, {**VERDICTS, ("p3.pdf", 0.33): {"verdict": "wrong", "error_type": "other"}})
        result = score.agreement(score.read_annotation(first), score.read_annotation(second))
        self.assertEqual(result["rows"], 5)
        self.assertAlmostEqual(result["raw_agreement"], 0.8)
        self.assertLess(result["kappa"], 1.0)
        self.assertEqual(score.cohen_kappa(["a", "b"], ["a", "b"]), 1.0)


class CommandTests(unittest.TestCase):
    def setUp(self):
        from LocalExtraction import about
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        patch = mock.patch.object(about, "PROJECT_HOME", self.base / "home")
        patch.start()
        self.addCleanup(patch.stop)
        cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(cwd))
        self.db = self.base / "web_output"
        _write_database(self.db)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_an_annotated_workbook_is_never_replaced(self):
        book = self.base / "a.xlsx"
        code, out, _ = self._run("sheet", "--source", str(self.db), "--out", str(book))
        self.assertEqual(code, 0, out)
        self.assertIn("4 papers drawn", out)
        code, _, err = self._run("sheet", "--source", str(self.db), "--out", str(book))
        self.assertEqual(code, 1)
        self.assertIn("not replaced", err)
        code, out, _ = self._run("sheet", "--source", str(self.db), "--out", str(book), "--force")
        self.assertEqual(code, 0)
        self.assertEqual(len(list(self.base.glob("a.*.xlsx"))), 1)  # the old one is kept

    def test_score_end_to_end(self):
        book, done = self.base / "a.xlsx", self.base / "done.xlsx"
        self._run("sheet", "--source", str(self.db), "--out", str(book))
        code, _, err = self._run("score", "--gold", str(book), "--out", str(self.base / "s"))
        self.assertEqual(code, 1)
        self.assertIn("marked done", err)
        _annotate(book, done, VERDICTS, MISSED)
        code, out, _ = self._run("score", "--gold", str(done), "--out", str(self.base / "s"))
        self.assertEqual(code, 0)
        self.assertIn("record · all", out)
        for name in ("report.md", "metrics.json", "errors.csv"):
            self.assertTrue((self.base / "s" / name).exists(), name)

    def test_help_makes_no_folder(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["sheet", "--help"])
        self.assertFalse((self.base / "home").exists())


if __name__ == "__main__":
    unittest.main()


class OtherToolsTests(WorkbookAndScoreTests):
    """Another tool's values, scored against the same annotations and compared with MoukhlijMatExtract."""

    def _annotation(self):
        annotated = self.base / "done.xlsx"
        _annotate(self.book, annotated, VERDICTS, MISSED)
        return score.read_annotation(annotated)

    def test_a_tool_s_csv_is_scored_the_same_way(self):
        annotation = self._annotation()
        path = self.base / "other.csv"
        pd.DataFrame([
            {"paper_id": "p1.pdf", "property": "activation_energy", "material": "Li6PS5Cl", "value": "310", "unit": "meV"},
            {"paper_id": "p4.pdf", "property": "ionic conductivity", "material": "Li10GeP2S12", "value": "12", "unit": "mS/cm"},
            {"paper_id": "p9.pdf", "property": "activation_energy", "material": "X", "value": "1"},  # not annotated: ignored
        ]).to_csv(path, index=False)
        theirs = score.predictions_from_csv(path, annotation)
        self.assertEqual(len(theirs), 2)
        record = score.evaluate(annotation, theirs)["levels"]["record"]["all"]
        self.assertEqual((record["tp"], record["fp"], record["fn"]), (2, 0, 3))

    def test_a_tool_s_csv_with_a_mistake_says_where(self):
        annotation = self._annotation()
        path = self.base / "bad.csv"
        pd.DataFrame([{"paper_id": "p1.pdf", "property": "activation_energy", "value": "0.3"}]).to_csv(path, index=False)
        with self.assertRaisesRegex(score.AnnotationError, "material"):
            score.predictions_from_csv(path, annotation)

    def test_the_paired_difference(self):
        annotation = self._annotation()
        same = score.paired_difference(annotation, annotation.extracted, annotation.extracted)
        self.assertEqual(same["difference"], 0.0)
        nothing = score.paired_difference(annotation, annotation.extracted, [])
        self.assertGreater(nothing["difference"], 0)
        self.assertLess(nothing["p_value"], 0.1)  # 4 papers only: a resampling of papers without values ties
        text = score.comparison_text({"MoukhlijMatExtract": score.evaluate(annotation)}, {"none": nothing})
        self.assertIn("paired bootstrap", text)


class ReferenceTests(unittest.TestCase):
    """Recall against a curated database, on its own papers."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.out = self.base / "output"
        self.out.mkdir()
        pd.DataFrame([{"paper_id": "a.pdf", "doi": "10.1/a"}, {"paper_id": "b.pdf", "doi": "NONE"}]).to_csv(
            self.out / "papers.csv", index=False)
        pd.DataFrame([
            {"paper_id": "a.pdf", "material_formula": "Li6PS5Cl", "ionic_conductivity_S_cm": "0.00119", "temperature": "room temperature"},
            {"paper_id": "a.pdf", "material_formula": "Li7La3Zr2O12", "ionic_conductivity_S_cm": "0.0005", "temperature": "298 K"},
            {"paper_id": "b.pdf", "material_formula": "Li3InCl6", "ionic_conductivity_S_cm": "0.0015", "temperature": "373 K"},
        ]).to_csv(self.out / "ionic_conductivity.csv", index=False)

    def test_entries_found_by_material_value_and_temperature(self):
        from Evaluation import reference
        curated = pd.DataFrame([
            {"reference": "X", "ref_id": 1, "doi": "10.1/a", "composition": "Li6.0P1.0S5.0Cl1.0", "conductivity_S_cm": 1.2e-3, "temperature_K": None},
            {"reference": "X", "ref_id": 2, "doi": "10.1/a", "composition": "Li7La3Zr2O12", "conductivity_S_cm": 5e-6, "temperature_K": None},
            {"reference": "X", "ref_id": 3, "doi": "10.1/a", "composition": "Li3PS4", "conductivity_S_cm": 1e-4, "temperature_K": None},
            {"reference": "X", "ref_id": 4, "doi": "10.9/z|10.1/b", "composition": "Li3InCl6", "conductivity_S_cm": 1.5e-3, "temperature_K": 373.15},
            {"reference": "X", "ref_id": 5, "doi": "10.1/unread", "composition": "Li3YCl6", "conductivity_S_cm": 5e-4, "temperature_K": None},
        ])
        result = reference.compare(curated, self.out, {"b.pdf": "10.1/b"})  # b's DOI from its sidecar
        self.assertEqual((result.papers, result.papers_read, result.entries_read), (3, 2, 4))
        self.assertEqual((result.material, result.record_loose, result.record_strict), (3, 2, 2))  # 1.19 vs 1.2: within 2 %
        found = dict(zip(result.rows.ref_id, result.rows.found))
        self.assertTrue(found[1].startswith("material and value"))
        self.assertEqual(found[2], "material, another value")  # 5e-4 against 5e-6: two decades apart
        self.assertEqual(found[3], "not found")
        self.assertEqual(found[5], "paper not read")

    def test_another_tool_on_the_same_papers(self):
        from Evaluation import reference
        curated = pd.DataFrame([
            {"reference": "X", "ref_id": 1, "doi": "10.1/a", "composition": "Li6PS5Cl", "conductivity_S_cm": 1.2e-3, "temperature_K": None},
            {"reference": "X", "ref_id": 2, "doi": "10.1/a", "composition": "Li3PS4", "conductivity_S_cm": 1e-4, "temperature_K": None},
        ])
        tool = self.base / "cde.csv"
        pd.DataFrame([{"paper_id": "a.pdf", "property": "ionic_conductivity", "material": "Li3PS4", "value": "0.1", "unit": "mScm-1"},
                      {"paper_id": "a.pdf", "property": "activation_energy", "material": "Li3PS4", "value": "0.3", "unit": "eV"}]
                     ).to_csv(tool, index=False)
        folder = reference.tool_output(tool, self.out, self.base / "tools" / "cde")
        result = reference.compare(curated, folder, {})
        self.assertEqual((result.entries_read, result.material, result.record_loose), (2, 1, 1))  # Li3PS4 only
        text = reference.report([reference.compare(curated, self.out, {})], {}, "t", {"cde": [result]})
        self.assertIn("| cde | X | 2 | 1 (50.0 %) | 1 (50.0 %)", text)

    def test_the_doi_fields_of_the_databases(self):
        from Evaluation.reference import _doi, dois_of
        self.assertEqual(dois_of(_doi("10.1/A|https://doi.org/10.2/b")), ["10.1/a", "10.2/b"])
        self.assertEqual(_doi("n/a"), "")

