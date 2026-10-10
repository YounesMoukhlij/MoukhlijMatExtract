# tests/test_gui.py
"""Tests of the second gate, the window: what it reads back from the database, what it says about a
paper, and the window itself — built transparent on a small made-up database and ledger, and driven
through its two panels. No network: the engine's long steps are replaced by stand-ins.

The window tests need a screen; without one (a server, a CI runner) they are skipped. Set
AUTOMATEXTRACT_NO_WINDOW_TESTS=1 to skip them anyway.

    python -m unittest discover -s tests -v   (or: pytest tests)
"""

import csv
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from exporter import StrictExporter
from extractor import ExtractorEngine
from gui.summary import final_summary, summarize_paper
from models import ExtractedField, PaperData
from ranking import Ranker
from web.fetch import Outcome
from web.job import ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from web.ledger import DOWNLOADED, SCREENED, Candidate, Ledger

try:
    import tkinter as tk
except ImportError:  # a Python built without Tk
    tk = None


def paper(filename: str, text: str, origin: str = "local") -> PaperData:
    ranked = Ranker.process(ExtractorEngine.extract_all([{"text": text, "page": 1, "section": "Results", "type": "Text"}]))
    return PaperData(
        filename=filename, metadata={"title": ExtractedField.empty()}, materials=ranked["materials"],
        electrochemical=ranked["ELECTROCHEMICAL"], thermodynamic=ranked["THERMODYNAMIC"], mechanical=ranked["MECHANICAL"],
        structural=ranked["STRUCTURAL"], electronic=ranked["ELECTRONIC"], thermal=ranked["THERMAL"],
        spectroscopy=ranked["SPECTROSCOPY"], dft=ranked["DFT"], aimd=ranked["AIMD"], ml=ranked["ML"],
        synthesis=ranked["SYNTHESIS"], characterization=ranked["CHARACTERIZATION"], battery_perf={}, interfaces={},
        relations=ranked["relations"], workflow=ranked["workflow"], figures=ranked["figures"], tables=ranked["tables"],
        equations=ranked["equations"], references=[], origin=origin)


LOCAL = "Li6PS5Cl has a migration barrier of 0.30 eV and Li6PS5Br an activation energy of 0.35 eV."
WEB = "The activation energy of Li7La3Zr2O12 is 0.41 eV."


def make_database(folder: str) -> None:
    """Both kinds of paper in one folder: what `overview` and the origin filter are for."""
    StrictExporter(folder).export([paper("mine.pdf", LOCAL, "local"), paper("10.1000_found.pdf", WEB, "web")])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_an_empty_folder_is_an_empty_database(self):
        self.assertTrue(database.table(self.folder, "papers").empty)
        self.assertTrue(database.activation_energies(self.folder, "web").empty)
        self.assertEqual(database.overview(self.folder), {"papers": {}, "activation_energies": {}})

    def test_each_side_reads_its_part_of_the_one_database(self):
        make_database(self.folder)
        local, web = (database.activation_energies(self.folder, origin) for origin in ("local", "web"))
        self.assertEqual(sorted(zip(local.material_formula, local.activation_energy_eV)), [("Li6PS5Br", "0.35"), ("Li6PS5Cl", "0.3")])
        self.assertEqual(list(zip(web.material_formula, web.activation_energy_eV, web.origin)), [("Li7La3Zr2O12", "0.41", "web")])
        self.assertEqual(len(database.activation_energies(self.folder)), 3)
        self.assertEqual(database.overview(self.folder), {"papers": {"local": 1, "web": 1},
                                                          "activation_energies": {"local": 2, "web": 1}})

    def test_a_paper_that_is_not_marked_web_is_local(self):
        make_database(self.folder)
        path = os.path.join(self.folder, "papers.csv")
        text = Path(path).read_text(encoding="utf-8-sig").replace(",local,", ",NONE,")  # as an earlier version wrote it
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertEqual(database.overview(self.folder)["papers"], {"local": 1, "web": 1})
        self.assertEqual(len(database.activation_energies(self.folder, "local")), 2)


class SummaryTests(unittest.TestCase):
    def test_what_is_said_about_a_paper(self):
        one = paper("mine.pdf", LOCAL)
        text = summarize_paper(one)
        self.assertIn("Materials (2): Li6PS5Cl, Li6PS5Br", text)
        self.assertIn("Activation_Energy: 0.3 eV [bulk] (+1 more)", text)
        self.assertIn("Papers with Activation Energy: 1 (2 values)", final_summary([one]))
        self.assertEqual(final_summary([]), "No papers were successfully processed.")


def _has_screen() -> bool:
    if tk is None or os.environ.get("AUTOMATEXTRACT_NO_WINDOW_TESTS"):
        return False
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from gui.app import App
        self.root_folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root_folder, True)
        self.local_output = os.path.join(self.root_folder, "local_output")
        self.web_output = os.path.join(self.root_folder, "web_output")
        self.pdfs, self.web_folder = os.path.join(self.root_folder, "pdfs"), os.path.join(self.root_folder, "papers_web")
        os.makedirs(self.pdfs)
        # Each side has its folder of results: the local articles in one, the web articles in the other.
        StrictExporter(self.local_output).export([paper("mine.pdf", LOCAL, "local")])
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

        self.asked = []
        self.answer = True
        for name in ("askyesno", "showinfo", "showerror"):
            patcher = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, _n=name, **k: (
                self.asked.append((_n, k.get("message") or (a[1] if len(a) > 1 else ""))), self.answer)[1])
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)  # drawn, as in real use, but not seen
        self.app = App(self.root, local_output=self.local_output, web_output=self.web_output, input_dir=self.pdfs,
                       job_path=self.job_path, workers=2)
        self.addCleanup(self._close)
        self.pump(0.2)

    def _close(self):
        self.app.close()
        self.pump(0.3)

    def pump(self, seconds=0.1, until=None, limit=20.0):
        end = time.time() + (limit if until else seconds)
        while time.time() < end:
            self.root.update()
            if until is not None and until():
                self.root.update()
                return True
            time.sleep(0.01)
        return until is None

    # ------------------------------------------------------------------
    def test_each_side_shows_its_own_folder_of_results(self):
        local, web = self.app.local.energies, self.app.web.energies
        self.assertEqual((len(local.table), len(web.table)), (2, 1))
        self.assertIn("local_output: 1 article read, 2 activation energies from 1 of them", local.count.get())
        self.assertIn("web_output: 1 article read, 1 activation energies from 1 of them", web.count.get())
        # The part of the paper each value was read from, and the page, are in the table.
        row = dict(zip(web.table.columns, web.table.tree.item("0", "values")))
        self.assertEqual((row["material_formula"], str(row["activation_energy_eV"]), row["extracted_from"], str(row["page"])),
                         ("Li7La3Zr2O12", "0.41", "Text", "1"))
        # A side pointed at another folder shows that folder.
        self.app.local.output.set(self.web_output)
        self.app.local.show_results()
        self.assertEqual(len(local.table), 1)

    def test_the_candidates_are_shown_and_filtered(self):
        web = self.app.web
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
        web = self.app.web
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
        self.app.web.load_job()
        self.assertEqual(self.app.web.harvest.ledger.get("10.1000/other").decision, "yes")

    def test_the_job_form_gives_back_the_job_it_was_given(self):
        from gui.dialogs import JobDialog
        saved = []
        form = JobDialog(self.app.web, self.job, self.job_path, saved.append)
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

    def test_an_older_database_is_moved_aside_only_on_a_yes(self):
        output = self.local_output
        os.remove(os.path.join(output, "methods.csv"))  # what an earlier version did not write
        os.remove(os.path.join(output, "properties.csv"))
        self.app.database_changed()
        self.assertIn("earlier version", self.app.local.energies.count.get())
        self.answer = False
        self.assertFalse(self.app.ready_to_extract(output))
        self.assertTrue(os.path.exists(os.path.join(output, "papers.csv")))
        self.answer = True
        self.assertTrue(self.app.ready_to_extract(output))
        self.assertFalse(os.path.exists(os.path.join(output, "papers.csv")))
        kept = [name for name in os.listdir(output) if name.startswith("previous_")]
        self.assertEqual(len(kept), 1)
        self.assertIn("papers.csv", os.listdir(os.path.join(output, kept[0])))  # moved, not deleted
        self.assertIn("Nothing extracted into", self.app.local.energies.count.get())
        self.assertTrue(os.path.exists(os.path.join(self.web_output, "papers.csv")))  # the other side's folder is its own

    def test_the_local_side_runs_the_extraction_of_the_terminal_gate(self):
        open(os.path.join(self.pdfs, "new.pdf"), "wb").close()
        calls = []

        def extraction(folder, output, max_workers=4, stop_event=None, progress_callback=None, **more):
            calls.append((folder, output, max_workers))
            progress_callback("new.pdf", paper("new.pdf", LOCAL))
            return 0

        local = self.app.local
        with mock.patch("gui.local_panel.run_extraction", side_effect=extraction):
            local.start()
            self.assertTrue(self.pump(until=lambda: not local.running() and local.status.get() == "Idle."))
        self.assertEqual(calls, [(self.pdfs, self.local_output, 2)])
        self.assertEqual((local._done, local._total), (1, 1))
        said = local.activity.text.get("1.0", "end")
        self.assertIn("[DONE] new.pdf", said)
        self.assertIn("Papers with Activation Energy: 1 (2 values)", said)

    def test_the_web_side_runs_the_steps_of_the_terminal_gate(self):
        web = self.app.web
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
