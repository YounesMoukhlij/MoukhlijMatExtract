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
        self.choice = "add"  # the answer to "There is already data here": add / new / None (Cancel)
        self.choices = []
        patcher = mock.patch("LocalExtraction.gui.dialogs.ask_choice", side_effect=lambda parent, title, message, options: (
            self.choices.append((message, [key for key, _, _ in options])), self.choice)[1])
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
        # A step still under way is stopped and waited for: its thread must not outlive the window.
        panel = getattr(self.app, "panel", None)
        if panel is not None and panel.running():
            panel.stop()
            self.pump(until=lambda: not panel.running(), limit=30)
        thread = getattr(panel, "_thread", None)
        if thread is not None:
            thread.join(30)
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
    def test_clear_the_log_empties_the_activity_and_the_log_strip(self):
        panel = self.app.panel
        panel.activity.write("a line of the step")
        self.app.log.write("a line of the engine")
        self.pump(0.2)
        panel.activity.clear_button.invoke()
        self.pump(0.2)
        self.assertEqual((panel.activity.contents().strip(), self.app.log.contents().strip()), ("", ""))
        panel.activity.write("after")  # what comes next is shown as before
        self.pump(0.2)
        self.assertIn("after", panel.activity.contents())

    def test_the_window_shows_its_folder_of_results(self):
        energies = self.app.panel.energies
        self.assertEqual(len(energies.table), 2)
        self.assertIn("local_output: 1 article read, 2 activation energies from 1 of them", energies.count.get())
        # The part of the paper each value was read from, and the page, are in the table.
        row = dict(zip(energies.table.columns, energies.table.tree.item("0", "values")))
        self.assertEqual((row["extracted_from"], str(row["page"])), ("Text", "1"))

    def test_an_older_database_too_different_can_only_be_moved_aside(self):
        output = self.output
        papers = os.path.join(output, "papers.csv")
        pd.read_csv(papers).drop(columns="metadata_basis").to_csv(papers, index=False)  # what an earlier version wrote
        self.app.database_changed()
        self.assertIn("earlier version", self.app.panel.energies.count.get())
        self.choice = None  # Cancel
        self.assertFalse(self.app.ready_to_extract(output))
        self.assertEqual(self.choices[-1][1], ["new"])  # adding to it is not offered
        self.assertTrue(os.path.exists(os.path.join(output, "papers.csv")))
        self.choice = "new"
        self.assertTrue(self.app.ready_to_extract(output))
        self.assertFalse(os.path.exists(os.path.join(output, "papers.csv")))
        kept = [name for name in os.listdir(output) if name.startswith("previous_")]
        self.assertEqual(len(kept), 1)
        self.assertIn("papers.csv", os.listdir(os.path.join(output, kept[0])))  # moved, not deleted
        self.assertIn("Nothing extracted into", self.app.panel.energies.count.get())

    def test_an_older_database_can_take_the_new_articles(self):
        output = self.output
        for name, columns in (("papers", ["extracted_with"]), ("activation_energy", ["mobile_ion", "plausibility"])):
            path = os.path.join(output, f"{name}.csv")
            pd.read_csv(path).drop(columns=columns).to_csv(path, index=False)  # what the previous version wrote
        self.assertTrue(StrictExporter.is_outdated(output))
        self.choice = "add"
        self.assertTrue(self.app.ready_to_extract(output, new_pdfs=2))
        self.assertEqual(self.choices[-1][1], ["add", "new"])
        self.assertIn("2 new PDFs are about to be extracted", self.choices[-1][0])
        self.assertFalse(StrictExporter.is_outdated(output))  # brought up to date, in place
        energies = pd.read_csv(os.path.join(output, "activation_energy.csv"), dtype=str)
        self.assertEqual(len(energies), 2)  # every value kept
        self.assertTrue(energies["mobile_ion"].str.endswith("+").all())
        self.assertTrue(energies["basis"].str.contains("ion: ").all())
        kept = [name for name in os.listdir(output) if name.startswith("previous_")]
        self.assertEqual(len(kept), 1)  # a copy of the files as they were
        self.assertNotIn("mobile_ion", pd.read_csv(os.path.join(output, kept[0], "activation_energy.csv")).columns)

    def test_existing_data_asks_whether_to_add_or_start_anew(self):
        output = self.output
        self.assertTrue(self.app.ready_to_extract(output, new_pdfs=0))  # nothing new to read: nothing asked
        self.assertTrue(self.app.ready_to_extract(output))  # the web part: asked only for an earlier version's data
        self.assertEqual(self.choices, [])
        self.choice = "add"
        self.assertTrue(self.app.ready_to_extract(output, new_pdfs=1))
        self.assertIn("already holds the data of 1 article", self.choices[-1][0])
        self.assertEqual(self.choices[-1][1], ["add", "new"])
        self.assertTrue(os.path.exists(os.path.join(output, "papers.csv")))  # kept as it was
        self.choice = None
        self.assertFalse(self.app.ready_to_extract(output, new_pdfs=1))  # Cancel: nothing starts
        self.choice = "new"
        self.assertTrue(self.app.ready_to_extract(output, new_pdfs=1))
        self.assertFalse(os.path.exists(os.path.join(output, "papers.csv")))
        self.assertEqual(len([n for n in os.listdir(output) if n.startswith("previous_")]), 1)

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
        said = panel.activity.contents()
        self.assertIn("[DONE] new.pdf", said)
        self.assertIn("Papers with Activation Energy: 1 (2 values)", said)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class PauseTests(WindowTest):
    """Pause holds the extraction between two PDFs; the status says so, and that the internet is gone."""

    def make_app(self, root):
        from LocalExtraction.gui.app import App
        folder = os.path.join(self.root_folder, "papers")
        os.makedirs(folder)
        Path(folder, "a.pdf").write_bytes(b"%PDF-1.4")
        return App(root, folder, os.path.join(self.root_folder, "out"))

    def test_pause_holds_then_resume_goes_on(self):
        import threading
        from LocalExtraction import runcontrol
        panel, done = self.app.panel, []
        paused = threading.Event()  # the first PDF lasts until Pause is pressed (under load, the three
        # could otherwise be read before the pause lands)

        def extraction(folder, output, max_workers, stop_event, progress_callback, **more):
            for name in ("a.pdf", "b.pdf", "c.pdf"):
                runcontrol.checkpoint(stop_event)
                done.append(name)
                if name == "a.pdf":
                    paused.wait(10)
                time.sleep(0.1)
            return 0
        with mock.patch("LocalExtraction.gui.panel.run_extraction", side_effect=extraction):
            panel.start()
            self.pump(until=lambda: done)
            from LocalExtraction.gui.theme import CURRENT
            self.assertEqual(panel.start_button.cget("style"), CURRENT)  # the step that runs: its button stays blue
            panel.toggle_pause()
            paused.set()
            self.assertEqual(panel._pause.cget("text"), "Resume")
            self.assertEqual(panel._pause.cget("style"), CURRENT)  # blue while paused
            self.assertTrue(panel.status.get().startswith("Paused"))
            self.pump(0.5)
            held = len(done)
            self.pump(0.5)
            self.assertEqual(len(done), held)  # nothing more while paused
            runcontrol._tell(False)
            self.pump(0.2)
            self.assertTrue(panel.status.get().startswith("Paused"))  # the pause notice stays first
            panel.toggle_pause()
            # waited for, not timed: under load the status may take longer than a fixed 0.2 s to change
            self.assertTrue(self.pump(until=lambda: panel.status.get().startswith("No internet")), panel.status.get())
            runcontrol._tell(True)
            self.assertTrue(self.pump(until=lambda: not panel.running()))
        self.assertEqual(done, ["a.pdf", "b.pdf", "c.pdf"])
        self.assertTrue(self.pump(until=lambda: str(panel._pause.cget("state")) == "disabled"))
        self.assertEqual((str(panel.start_button.cget("style")), str(panel._pause.cget("style"))), ("TButton", "TButton"))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class ThemeTests(unittest.TestCase):
    """Every button lights up under the mouse, darkens when pressed, and the running step's stays blue."""

    def test_the_buttons_answer_the_mouse(self):
        from tkinter import ttk
        from LocalExtraction.gui import theme
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        theme.apply(root)
        theme.apply(root)  # a second window of the same program: nothing done twice
        style = ttk.Style(root)
        colours = {state: style.lookup("TButton", "background", [state]) for state in ("active", "pressed", "disabled")}
        rest = style.lookup("TButton", "background")
        self.assertEqual(len({rest, *colours.values()}), 4)  # at rest, hover, pressed, disabled: four colours
        button = ttk.Button(root, text="2 · Download")
        theme.mark(button)
        self.assertEqual(button.cget("style"), theme.CURRENT)
        self.assertNotIn(style.lookup(theme.CURRENT, "background"), (rest, *colours.values()))
        theme.unmark(button)
        self.assertEqual(button.cget("style"), "TButton")


if __name__ == "__main__":
    unittest.main()


class WorkerThreadTests(unittest.TestCase):
    """A Tk variable freed on a worker thread is released by the main thread, without an error."""

    def test_a_variable_freed_on_a_worker_thread(self):
        import gc
        import threading

        from LocalExtraction.gui import theme, tkthreads
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        theme.apply(root)
        variable = tk.StringVar(root, value="x")
        name = variable._name
        box = [variable]
        del variable
        problems = []
        hook, threading.excepthook = threading.excepthook, lambda args: problems.append(args.exc_value)
        self.addCleanup(setattr, threading, "excepthook", hook)
        worker = threading.Thread(target=lambda: (box.clear(), gc.collect()))
        worker.start()
        worker.join()
        self.assertEqual(problems, [])
        self.assertTrue(root.getboolean(root.tk.call("info", "exists", name)))  # not yet: waiting
        self.assertEqual(tkthreads.release_waiting(), 1)
        self.assertFalse(root.getboolean(root.tk.call("info", "exists", name)))
