# Evaluation/tests/test_gui.py
"""The steps the terminal and the Evaluate window share (Evaluation/steps.py), and the window itself."""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from Evaluation import steps
from Evaluation.tests.test_evaluation import MISSED, VERDICTS, _annotate, _write_database
from LocalExtraction.tests.test_gui import has_screen


class StepsTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = self.base / "web_output"
        _write_database(self.db)

    def test_no_database_says_where_it_looked(self):
        with self.assertRaisesRegex(steps.NoDatabase, "nowhere"):
            steps.make_sheet([self.base / "nowhere"], self.base / "a.xlsx")

    def test_make_annotate_score(self):
        book = self.base / "annotation.xlsx"
        counts = steps.make_sheet([self.db], book, papers=10)
        self.assertEqual((counts["papers"], counts["values"]), (4, 5))  # every paper has a legal copy (unpaywall)
        _annotate(book, book, VERDICTS, MISSED)
        metrics, paths, annotation, _, _ = steps.score_sheet(book, self.base / "scores")
        self.assertEqual(metrics["papers"], 4)
        self.assertTrue(paths["report"].exists())
        self.assertTrue((self.base / "scores" / "run_manifest.json").exists())
        rows = dict((name, (p, r, f)) for name, p, r, f in steps.summary_rows(metrics))
        self.assertAlmostEqual(rows["value · all"][0], 0.8)

    def test_a_workbook_with_nothing_done_is_refused(self):
        from Evaluation.score import AnnotationError
        book = self.base / "annotation.xlsx"
        steps.make_sheet([self.db], book)
        with self.assertRaisesRegex(AnnotationError, "marked done"):
            steps.score_sheet(book, self.base / "scores")

    def test_the_old_workbook_is_kept(self):
        book = self.base / "annotation.xlsx"
        book.write_text("x")
        kept = steps.keep_old(book)
        self.assertFalse(book.exists())
        self.assertTrue(kept.exists() and kept.name.startswith("annotation."))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from Evaluation import gui
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = self.base / "local_output"
        _write_database(self.db)
        patch = mock.patch.object(gui, "DEFAULT_DIR", self.base / "Evaluation")
        patch.start()
        self.addCleanup(patch.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.gui = gui

    def _until(self, condition, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if condition():
                return
            time.sleep(0.05)
        self.fail("timed out")

    def test_the_three_steps(self):
        dialog = self.gui.EvaluationDialog(self.root, str(self.db), "local", "local articles")
        book = self.base / "Evaluation" / "annotation_local.xlsx"
        self.assertEqual(str(dialog.score_button["state"]), "disabled")  # nothing to score before the workbook
        dialog.count.set(10)
        dialog.make()
        self._until(lambda: book.exists() and not dialog._busy)
        self.assertIn("4 papers drawn", dialog.result.get("1.0", "end"))  # local: every PDF is the user's own
        self.assertEqual(str(dialog.score_button["state"]), "normal")

        _annotate(book, book, VERDICTS, MISSED)
        dialog.score()
        self._until(lambda: not dialog._busy)
        text = dialog.result.get("1.0", "end")
        self.assertIn("4 papers checked", text)
        self.assertIn("80.0 %", text)  # value-level precision
        metrics = json.loads((self.base / "Evaluation" / "scores_local" / "metrics.json").read_text())
        self.assertEqual(metrics["papers"], 4)

        with mock.patch("tkinter.messagebox.askyesno", return_value=False) as asked:  # a workbook with checks
            dialog.make()
        asked.assert_called_once()
        self.assertTrue(book.exists())
        dialog.destroy()

        again = self.gui.EvaluationDialog(self.root, str(self.db), "local", "local articles")
        self.assertIn("4 papers checked", again.result.get("1.0", "end"))  # opens on the last scores
        again.destroy()

    def test_each_database_has_its_own_workbook_and_scores(self):
        """Two web databases (the general one and a job's own) are two evaluations: the scores of one must never be
        shown, or scored again, as those of the other."""
        base = self.base / "Evaluation"
        self.assertEqual(self.gui.workbook_of("web", "WebScraping/web_output"), base / "annotation_web.xlsx")
        self.assertEqual(self.gui.workbook_of("web", "/x/WebScraping/web_output_garnet_nasicon"),
                         base / "annotation_web_garnet_nasicon.xlsx")
        self.assertEqual(self.gui.scores_of("web", "/x/WebScraping/web_output_garnet_nasicon"),
                         base / "scores_web_garnet_nasicon")
        self.assertEqual(self.gui.workbook_of("local", "/x/elsewhere"), base / "annotation_local_elsewhere.xlsx")
        other = self.base / "web_output_garnet"
        _write_database(other)
        dialog = self.gui.EvaluationDialog(self.root, str(other), "web", "web articles")
        self.assertEqual(dialog.workbook, base / "annotation_web_garnet.xlsx")
        dialog.destroy()
