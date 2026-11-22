# WebScraping/tests/test_coverage.py
"""The coverage of each job: found → screened → proposed → downloaded → extracted, and by publisher — read from
each job's ledger and results folder, never written to."""

import csv
import os
import shutil
import tempfile
import unittest

from WebScraping.tests.test_web import candidate  # also: offline, sys.path
from WebScraping.averageScrap import coverage
from WebScraping.averageScrap.job import FetchConfig, Job, SearchConfig, dump_job
from WebScraping.averageScrap.ledger import CLOSED, DOWNLOADED, EXTRACTED, REJECTED, SCREENED, Ledger


def write_job(home: str, name: str) -> None:
    os.makedirs(os.path.join(home, "configs"), exist_ok=True)
    job = Job(name=name, search=SearchConfig(queries=["garnet"], sources=["openalex"]),
              fetch=FetchConfig(folder=os.path.join("WebScraping", f"papers_{name}")))
    with open(os.path.join(home, "configs", f"{name}.yaml"), "w", encoding="utf-8") as f:
        f.write(dump_job(job))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.home)
        write_job(self.home, "garnet")
        write_job(self.home, "halide")  # no ledger yet: listed with zeros
        ledger = Ledger(os.path.join("WebScraping", "papers_garnet", "ledger.sqlite"))
        rows = [("a", "Elsevier BV", "yes", EXTRACTED), ("b", "Elsevier BV", "yes", CLOSED),
                ("c", "Elsevier BV", "no", REJECTED), ("d", "MDPI", "yes", DOWNLOADED), ("e", "MDPI", "yes", SCREENED),
                ("f", "", "", "new")]
        for key, publisher, decision, status in rows:
            ledger.add(candidate(key=f"10.1/{key}", doi=f"10.1/{key}", publisher=publisher))
            ledger.update(f"10.1/{key}", decision=decision, status=status)
        ledger.close()
        out = os.path.join("WebScraping", "web_output_garnet")
        os.makedirs(out)
        with open(os.path.join(out, "activation_energy.csv"), "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["paper_id", "activation_energy_eV"])
            writer.writerows([["a.pdf", "0.3"], ["a.pdf", "0.35"]])
        with open(os.path.join(out, "papers.csv"), "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([["paper_id"], ["a.pdf"]])

    def test_each_job_from_found_to_extracted(self):
        families = {row["job"]: row for row in coverage.by_family()}
        self.assertEqual(set(families), {"garnet", "halide"})
        garnet = families["garnet"]
        self.assertEqual((garnet["found"], garnet["screened"], garnet["proposed"], garnet["downloaded"],
                          garnet["no_copy"], garnet["extracted_papers"], garnet["activation_energies"]),
                         (6, 5, 4, 2, 1, 1, 2))
        self.assertEqual(garnet["download_rate"], 0.5)  # 2 of the 4 proposed
        self.assertEqual(families["halide"]["found"], 0)

    def test_by_publisher_shows_who_could_not_be_had(self):
        rows = {row["publisher"]: row for row in coverage.by_publisher()}
        self.assertEqual((rows["Elsevier BV"]["proposed"], rows["Elsevier BV"]["downloaded"]), (2, 1))
        self.assertEqual((rows["MDPI"]["proposed"], rows["MDPI"]["downloaded"]), (2, 1))
        self.assertIn("unknown", rows)  # a paper whose publisher no source named

    def test_the_report_is_written_and_the_ledgers_are_left_as_they_were(self):
        ledger = os.path.join("WebScraping", "papers_garnet", "ledger.sqlite")
        before = os.path.getmtime(ledger)
        folder = coverage.write(os.path.join(self.home, "WebScraping", "coverage"))
        self.assertEqual(sorted(os.listdir(folder)), ["coverage.md", "coverage_by_family.csv",
                                                      "coverage_by_publisher.csv"])
        text = open(os.path.join(folder, "coverage.md"), encoding="utf-8").read()
        self.assertIn("| garnet | 6 | 5 | 4 | 2 (50 %) | 1 | 1 | 2 |", text)
        self.assertEqual(os.path.getmtime(ledger), before)
        self.assertFalse(os.path.exists(os.path.join("WebScraping", "papers_halide")))  # nothing made for it


    def test_the_command_writes_it_and_says_where(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        from WebScraping.averageScrap import cli
        out = io.StringIO()
        with mock.patch.object(cli, "enter_project_home"), mock.patch.object(cli, "print_banner"), redirect_stdout(out):
            self.assertEqual(cli.main(["coverage"]), 0)
        self.assertTrue(os.path.isfile(os.path.join("WebScraping", "coverage", "coverage.md")))
        self.assertIn("garnet: 6 found, 4 proposed, 2 downloaded (50 %), 2 activation energies", out.getvalue())


    def test_the_window_shows_both_tables(self):
        from LocalExtraction.tests.test_gui import has_screen
        if not has_screen():
            self.skipTest("the window needs a screen")
        import tkinter as tk
        from WebScraping.averageScrap.gui.dialogs import CoverageDialog
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        dialog = CoverageDialog(root)
        root.update()
        families = {dialog.families.tree.item(i, "values")[0]: dialog.families.tree.item(i, "values")
                    for i in dialog.families.tree.get_children()}
        self.assertEqual(families["garnet"][1:5], ("6", "5", "4", "2 (50 %)"))
        publishers = [dialog.publishers.tree.item(i, "values")[0] for i in dialog.publishers.tree.get_children()]
        self.assertEqual(publishers[:2], ["Elsevier BV", "MDPI"])
        self.assertTrue(os.path.isfile(os.path.join(dialog.folder, "coverage.md")))


if __name__ == "__main__":
    unittest.main()
