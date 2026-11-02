# LocalExtraction/tests/test_gui.py
"""Tests of the second gate of Project 1, the window: what it reads back from the database, what it
says about a paper, and the window itself — built transparent on a small made-up database and driven
through its panel. The extraction is replaced by a stand-in.

The window tests need a screen; without one (a server, a CI runner) they are skipped. Set
MME_NO_WINDOW_TESTS=1 to skip them anyway.

    python -m unittest discover -s LocalExtraction/tests -t . -v   (or: pytest LocalExtraction)
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

import pandas as pd

from LocalExtraction import database
from LocalExtraction.exporter import StrictExporter
from LocalExtraction.extractor import ExtractorEngine
from LocalExtraction.gui.summary import final_summary, summarize_paper
from LocalExtraction.models import ExtractedField, PaperData
from LocalExtraction.ranking import Ranker

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

    def test_each_origin_reads_its_part_of_the_one_database(self):
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


def has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


class WindowTest(unittest.TestCase):
    """What every window test needs: the message boxes answered, the window drawn but not seen,
    and its loop turned until something has happened. A subclass makes `self.app` in `make_app`."""

    def setUp(self):
        self.root_folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root_folder, True)
        self.asked = []
        self.answer = True
        for name in ("askyesno", "showinfo", "showerror"):
            patcher = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, _n=name, **k: (
                self.asked.append((_n, k.get("message") or (a[1] if len(a) > 1 else ""))), self.answer)[1])
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prepare()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)  # drawn, as in real use, but not seen
        self.app = self.make_app(self.root)
        self.addCleanup(self._close)
        self.pump(0.2)

    def prepare(self) -> None:
        """The folders the window is opened on."""

    def make_app(self, root):
        raise NotImplementedError

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


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(WindowTest):
    def prepare(self):
        self.output = os.path.join(self.root_folder, "local_output")
        self.pdfs = os.path.join(self.root_folder, "pdfs")
        os.makedirs(self.pdfs)
        StrictExporter(self.output).export([paper("mine.pdf", LOCAL, "local")])

    def make_app(self, root):
        from LocalExtraction.gui.app import App
        return App(root, input_dir=self.pdfs, output_dir=self.output, workers=2)

    # ------------------------------------------------------------------
    def test_the_window_shows_its_folder_of_results(self):
        energies = self.app.panel.energies
        self.assertEqual(len(energies.table), 2)
        self.assertIn("local_output: 1 article read, 2 activation energies from 1 of them", energies.count.get())
        # The part of the paper each value was read from, and the page, are in the table.
        row = dict(zip(energies.table.columns, energies.table.tree.item("0", "values")))
        self.assertEqual((row["extracted_from"], str(row["page"])), ("Text", "1"))

    def test_an_older_database_is_moved_aside_only_on_a_yes(self):
        output = self.output
        papers = os.path.join(output, "papers.csv")
        pd.read_csv(papers).drop(columns="metadata_basis").to_csv(papers, index=False)  # what an earlier version wrote
        self.app.database_changed()
        self.assertIn("earlier version", self.app.panel.energies.count.get())
        self.answer = False
        self.assertFalse(self.app.ready_to_extract(output))
        self.assertTrue(os.path.exists(os.path.join(output, "papers.csv")))
        self.answer = True
        self.assertTrue(self.app.ready_to_extract(output))
        self.assertFalse(os.path.exists(os.path.join(output, "papers.csv")))
        kept = [name for name in os.listdir(output) if name.startswith("previous_")]
        self.assertEqual(len(kept), 1)
        self.assertIn("papers.csv", os.listdir(os.path.join(output, kept[0])))  # moved, not deleted
        self.assertIn("Nothing extracted into", self.app.panel.energies.count.get())

    def test_it_runs_the_extraction_of_the_terminal_gate(self):
        open(os.path.join(self.pdfs, "new.pdf"), "wb").close()
        calls = []

        def extraction(folder, output, max_workers=4, stop_event=None, progress_callback=None, **more):
            calls.append((folder, output, max_workers))
            progress_callback("new.pdf", paper("new.pdf", LOCAL))
            return 0

        panel = self.app.panel
        with mock.patch("LocalExtraction.gui.panel.run_extraction", side_effect=extraction):
            panel.start()
            self.assertTrue(self.pump(until=lambda: not panel.running() and panel.status.get() == "Idle."))
        self.assertEqual(calls, [(self.pdfs, self.output, 2)])
        self.assertEqual((panel._done, panel._total), (1, 1))
        said = panel.activity.text.get("1.0", "end")
        self.assertIn("[DONE] new.pdf", said)
        self.assertIn("Papers with Activation Energy: 1 (2 values)", said)


if __name__ == "__main__":
    unittest.main()
