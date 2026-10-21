# WebScraping/tests/test_gui.py
"""Tests of the second gate of Project 2, the window — built transparent on a small made-up database
and ledger, and driven through its panel. No network: the engine's long steps are replaced by stand-ins.

The window tests need a screen; without one (a server, a CI runner) they are skipped. Set
MME_NO_WINDOW_TESTS=1 to skip them anyway.

    python -m unittest discover -s WebScraping/tests -t . -v   (or: pytest WebScraping)
"""

import csv
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

from LocalExtraction.exporter import StrictExporter
from LocalExtraction.tests.test_gui import WEB, WindowTest, has_screen, paper
from WebScraping.fetch import Outcome
from WebScraping.job import ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from WebScraping.ledger import DOWNLOADED, SCREENED, Candidate, Ledger


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(WindowTest):
    def prepare(self):
        self.web_output = os.path.join(self.root_folder, "web_output")
        self.web_folder = os.path.join(self.root_folder, "papers_web")
        StrictExporter(self.web_output).export([paper("10.1000_found.pdf", WEB, "web")])
        self.job_path = os.path.join(self.root_folder, "job.yaml")
        self.job = Job(search=SearchConfig(queries=["solid electrolyte"], sources=["openalex"]),
                       screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"]),
                       fetch=FetchConfig(folder=self.web_folder, sources=["openalex"]),
                       extract=ExtractConfig(properties=["Activation_Energy"], require_material=True))
        with open(self.job_path, "w", encoding="utf-8") as f:
            f.write(dump_job(self.job))
        ledger = Ledger(os.path.join(self.web_folder, "ledger.sqlite"))
        ledger.add(Candidate(key="10.1000/found", doi="10.1000/found", title="Garnet conductors", year=2022, score=5.0,
                             access="open", decision="yes", status=DOWNLOADED, source_used="pmc", file="10.1000_found.pdf"))
        ledger.add(Candidate(key="10.1000/wanted", doi="10.1000/wanted", title="Argyrodite conductors", year=2023, score=4.0,
                             access="open", decision="yes", status=SCREENED, abstract="About argyrodites."))
        ledger.add(Candidate(key="10.1000/other", doi="10.1000/other", title="Graphite anodes", year=2021, score=0.0,
                             access="closed", decision="no", status=SCREENED, flags=["no-open-copy-known"]))
        ledger.write_review(os.path.join(self.web_folder, "candidates.csv"))
        ledger.close()

    def make_app(self, root):
        from WebScraping.gui.app import App
        return App(root, job_path=self.job_path, output_dir=self.web_output, workers=2)

    # ------------------------------------------------------------------
    def test_the_window_shows_its_folder_of_results(self):
        energies = self.app.panel.energies
        self.assertEqual(len(energies.table), 1)
        self.assertIn("web_output: 1 article read, 1 activation energies from 1 of them", energies.count.get())
        row = dict(zip(energies.table.columns, energies.table.tree.item("0", "values")))
        self.assertEqual((row["material_formula"], str(row["activation_energy_eV"]), row["extracted_from"], str(row["page"])),
                         ("Li7La3Zr2O12", "0.41", "Text", "1"))

    def test_the_candidates_are_shown_and_filtered(self):
        web = self.app.panel
        self.assertEqual(len(web.table), 2)  # the proposed ones
        self.assertIn("1 yes, 1 no · 1 downloaded", web.counts.get())
        web.filter_var.set("All")
        web.show_candidates()
        self.assertEqual(len(web.table), 3)
        web.search_var.set("graphite")
        web.show_candidates()
        self.assertEqual(web.table.tree.get_children(), ("10.1000/other",))
        self.assertEqual(web.table.tree.item("10.1000/other", "values")[0], "✗")

    def test_a_decision_made_in_the_table_reaches_the_ledger_and_the_review_list(self):
        web = self.app.panel
        web.table.tree.selection_set(["10.1000/wanted", "10.1000/found"])
        web._decide("no")
        self.assertEqual(web.harvest.ledger.get("10.1000/wanted").decision, "no")
        self.assertEqual(web.harvest.ledger.get("10.1000/found").decision, "yes")  # already fetched: left alone
        with open(os.path.join(self.web_folder, "candidates.csv"), encoding="utf-8-sig") as f:
            written = {row["key"]: row["decision"] for row in csv.DictReader(f)}
        self.assertEqual(written["10.1000/wanted"], "no")  # what the terminal's fetch stage will read

    def test_a_list_reviewed_in_a_spreadsheet_is_what_the_table_shows(self):
        path = os.path.join(self.web_folder, "candidates.csv")
        text = Path(path).read_text(encoding="utf-8-sig").replace("no,0,closed", "yes,0,closed")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.app.panel.load_job()
        self.assertEqual(self.app.panel.harvest.ledger.get("10.1000/other").decision, "yes")

    def test_the_job_form_gives_back_the_job_it_was_given(self):
        from WebScraping.gui.dialogs import JobDialog
        saved = []
        form = JobDialog(self.app.panel, self.job, self.job_path, saved.append)
        self.pump(0.1)
        self.assertEqual(form._read(), self.job)
        form.queries.insert("end", "\nsodium conductor")
        form.year_from.set("2015")
        form._save(self.job_path)  # nothing to ask: the file has no comments of its own
        self.assertEqual(self.asked, [("showerror", "Years: give both the first and the last year, or neither")])
        form.year_to.set("2026")
        form._save(self.job_path)
        self.assertEqual(saved, [self.job_path])
        again = load_job(self.job_path)
        self.assertEqual((again.search.queries, again.search.years), (["solid electrolyte", "sodium conductor"], (2015, 2026)))

    def test_it_runs_the_steps_of_the_terminal_gate(self):
        web = self.app.panel
        harvest = web._harvest()
        done = []

        def discover():
            harvest.ledger.add(Candidate(key="10.1000/new", doi="10.1000/new", title="A halide conductor", year=2024,
                                         abstract="solid electrolyte activation energy", oa_status="gold"))
            return 1

        def fetch(limit=None, stop_event=None, progress_callback=None):
            done.append(("fetch", limit))
            wanted = harvest.ledger.get("10.1000/wanted")
            harvest.ledger.update("10.1000/wanted", status=DOWNLOADED, source_used="osti")
            progress_callback(wanted, Outcome("10.1000/wanted", DOWNLOADED, service="osti"), 1, 1)
            return {DOWNLOADED: 1}

        def extract(max_workers=4, stop_event=None, progress_callback=None):
            done.append(("extract", max_workers, harvest.output_dir))
            return 0

        with mock.patch.object(harvest, "discover", side_effect=discover), \
                mock.patch.object(harvest, "fetch", side_effect=fetch), mock.patch.object(harvest, "extract", side_effect=extract):
            web.search()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
            self.assertEqual(harvest.ledger.get("10.1000/new").decision, "yes")  # screened, proposed, still to review
            self.assertIn("10.1000/new", web.table.tree.get_children())

            web.limit_var.set("5")
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(done, [("fetch", 5), ("extract", 2, self.web_output)])  # the extraction follows, into the web folder
        self.assertEqual(web.table.tree.item("10.1000/wanted", "values")[3], "downloaded (osti)")
        self.assertIn("[1/1] downloaded: 10.1000/wanted via osti", web.activity.text.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
