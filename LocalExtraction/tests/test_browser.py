# LocalExtraction/tests/test_browser.py
"""The results browser: every table of a part, listed with its number of rows, every column, a
search over all of them, and every cell of the selected row. Offline, in a folder made here; the
window tests need a screen."""

import csv
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from LocalExtraction.gui.browser import EXTRACTION_TABLES, has_results, part_tables

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


def write(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class Home(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        db = self.home / "LocalExtraction/local_output"
        write(db / "papers.csv", ["paper_id", "title", "doi"], [["a.pdf", "Garnet conductors", "10.1000/a"],
                                                               ["b.pdf", "Argyrodite conductors", "NONE"]])
        write(db / "activation_energy.csv", ["paper_id", "title", "material_formula", "activation_energy_eV"],
              [["a.pdf", "Garnet conductors", "Li7La3Zr2O12", "0.32"], ["b.pdf", "Argyrodite conductors", "Li6PS5Cl", "0.19"]])
        write(db / "diffusion_coefficient.csv", ["paper_id", "title", "material_formula"], [])


class PartTests(Home):
    def test_what_each_part_shows(self):
        title, folder, tables = part_tables("local", self.home)
        self.assertEqual(folder, self.home / "LocalExtraction/local_output")
        self.assertEqual([label for label, _ in tables], [label for _, label in EXTRACTION_TABLES])
        web = [label for label, _ in part_tables("web", self.home)[2]]
        self.assertIn("Downloads (moukhlij4scraping)", web)
        self.assertIn("DOI list (Fetch DOIs)", web)
        rank = [label for label, _ in part_tables("rank", self.home)[2]]
        self.assertEqual(rank[:4], ["Summary of the components", "Bulk — top materials", "Bulk — all materials",
                                    "Bulk — values"])
        self.assertIn("Grain boundary — top materials", rank)
        self.assertIn("Crystal families", [label for label, _ in part_tables("classify", self.home)[2]])

    def test_a_part_with_nothing_yet(self):
        self.assertTrue(has_results("local", self.home))
        self.assertFalse(has_results("classify", self.home))
        with self.assertRaises(ValueError):
            part_tables("nothing", self.home)


def has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(Home):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def browser(self, part="local"):
        from LocalExtraction.gui.browser import open_results
        window = open_results(self.root, part, self.home)
        self.root.update()
        return window

    def test_every_table_listed_with_its_rows_and_shown_whole(self):
        window = self.browser()
        listed = {window.menu.item(i, "text"): window.menu.item(i, "values")[0] for i in window.menu.get_children()}
        self.assertEqual(listed, {"Papers": "2", "Activation energies": "2", "Diffusion coefficients": "0"})
        self.assertIn("3 tables, 4 rows", window.headline.get())
        window.select(1)
        table = window._current()["table"]
        self.assertEqual(len(table), 2)
        self.assertEqual([table.tree.heading(c, "text") for c in table.columns],
                         ["paper_id", "title", "material_formula", "activation_energy_eV"])

    def test_search_details_and_doi(self):
        window = self.browser()
        window.select(1)
        window.search.set("argyrodite")
        window._filter()
        self.assertEqual(window.shown.get(), "Activation energies: showing 1 of 2")
        table = window._current()["table"]
        first = table.tree.get_children()[0]
        table.tree.focus(first)
        window._show_row()
        self.assertIn("material_formula: Li6PS5Cl", window.details.get("1.0", "end"))
        window.search.set("")
        window.select(0)
        table = window._current()["table"]
        table.tree.focus("0")
        window._show_row()
        self.assertEqual(str(window.doi_button["state"]), "normal")  # a paper with a DOI: open it
        table.tree.focus("1")
        window._show_row()
        self.assertEqual(str(window.doi_button["state"]), "disabled")

    def test_a_part_with_no_result_says_so(self):
        window = self.browser("classify")
        self.assertIn("No results yet", window.headline.get())


if __name__ == "__main__":
    unittest.main()
