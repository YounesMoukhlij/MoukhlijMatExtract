# WebScraping/tests/test_doi_list.py
"""The "Fetched DOIs (N)…" window of moukhlij4scraping: the total of the list, which DOIs have their
PDF, which were tried without success, which were not tried yet; filtering and the details of a row.
Offline, in a folder made here; the window tests need a screen."""

import csv
import os
import shutil
import tempfile
import unittest

from WebScraping.moukhlij4scraping.doi_list import NOT_TRIED, WITH_PDF, count_dois, pdf_state, read_dois
from WebScraping.moukhlij4scraping.moukhlij4scraping.batch import LOG_COLUMNS

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.csv = os.path.join(self.folder, "dois.csv")
        self.txt = os.path.join(self.folder, "dois.txt")
        self.papers = os.path.join(self.folder, "papers")
        os.makedirs(self.papers)
        with open(self.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["doi", "title", "year", "venue", "found_by"])
            writer.writerow(["10.1000/a", "Garnet conductors", "2022", "Solid State Ionics", "OpenAlex"])
            writer.writerow(["10.1000/b", "Argyrodite conductors", "2023", "J. Mater. Chem. A", "Crossref"])
            writer.writerow(["10.1000/c", "Halide conductors", "2024", "ACS Energy Lett.", "arXiv"])
        with open(self.txt, "w", encoding="utf-8") as f:
            f.write("10.1000/a\n10.1000/b\n10.1000/c\n")
        open(os.path.join(self.papers, "10.1000_a.pdf"), "wb").write(b"%PDF-1.4")
        with open(os.path.join(self.papers, "scrape_log.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(LOG_COLUMNS)
            writer.writerow(["10.1000/b", "Argyrodite conductors", "not found", "", "", "2026-11-01T10:00:00+00:00"])


class ListTests(Folder):
    def test_the_list_and_where_each_pdf_stands(self):
        self.assertEqual(count_dois(self.txt), 3)
        rows = read_dois(self.csv, self.txt)
        self.assertEqual([r["doi"] for r in rows], ["10.1000/a", "10.1000/b", "10.1000/c"])
        from WebScraping.moukhlij4scraping.moukhlij4scraping.batch import read_log
        files, log = set(os.listdir(self.papers)), read_log(self.papers)
        self.assertEqual([pdf_state(r["doi"], files, log) for r in rows],
                         [WITH_PDF, "not found (2026-11-01)", NOT_TRIED])
        os.remove(self.csv)
        self.assertEqual(len(read_dois(self.csv, self.txt)), 3)  # the text file is enough


def has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(Folder):
    def test_the_window_shows_the_total_filters_and_details(self):
        from WebScraping.moukhlij4scraping.doi_list import DoiListWindow
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        window = DoiListWindow(root, self.csv, self.txt, self.papers)
        root.update()
        self.assertEqual(window.summary.get(), "3 DOIs fetched")
        self.assertIn("1 with their PDF", window.breakdown.get())
        self.assertIn("1 tried without success", window.breakdown.get())
        self.assertIn("1 not tried yet", window.breakdown.get())
        self.assertEqual(len(window.table), 3)
        window.show.set(NOT_TRIED)
        window._filter()
        self.assertEqual([window.rows[int(i)]["doi"] for i in window.table.tree.get_children()], ["10.1000/c"])
        window.show.set("All")
        window.search.set("argyrodite")
        window._filter()
        self.assertEqual(window.shown.get(), "showing 1 of 3")
        window.table.tree.focus("1")
        window._show_details()
        self.assertIn("Argyrodite conductors", window.details.get("1.0", "end"))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class ScrapeQuestionTests(unittest.TestCase):
    """“2 · Scrape articles” asks whether to start with the open-access copies."""

    def setUp(self):
        from unittest import mock
        from WebScraping.moukhlij4scraping import gui
        self.mock, self.gui = mock, gui
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.panel = gui.MoukhlijPanel.__new__(gui.MoukhlijPanel)  # only the asking and the command
        tk.Frame.__init__(self.panel, self.root)
        self.panel._open_first = True
        self.commands = []
        self.panel._stream = lambda label, command, on_line=None: self.commands.append(command) or 0
        self.panel.app = mock.Mock()
        self.panel.activity = mock.Mock()
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        patcher = mock.patch.object(gui, "HOME", home)  # never the real ~/MoukhlijMatExtract
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_leaves_the_open_copies_to_method_1_and_is_remembered(self):
        with self.mock.patch("tkinter.messagebox.askyesnocancel", return_value=False) as asked:
            self.assertFalse(self.panel._ask_open_access())
        self.assertEqual(asked.call_args.kwargs["default"], "yes")
        self.panel._scrape_work(None, False)
        self.assertIn("--no-open-access", self.commands[-1])
        with self.mock.patch("tkinter.messagebox.askyesnocancel", return_value=None) as asked:
            self.assertIsNone(self.panel._ask_open_access())  # cancelled: nothing changes
        self.assertEqual(asked.call_args.kwargs["default"], "no")
        self.panel._scrape_work(10, True)
        self.assertNotIn("--no-open-access", self.commands[-1])
        self.assertIn("10", self.commands[-1])


if __name__ == "__main__":
    unittest.main()
