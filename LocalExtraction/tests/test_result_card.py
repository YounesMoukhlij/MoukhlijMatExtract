# LocalExtraction/tests/test_result_card.py
"""The card every window shows when a step ends: what an extraction added (from the database before
and after it), with the article titles in its highlights, and the card itself — its tiles, its
buttons, hidden by a new run. Offline, in a folder made here; the card tests need a screen."""

import csv
import os
import shutil
import tempfile
import unittest

from LocalExtraction.gui.outcomes import extraction_outcome, snapshot
from LocalExtraction.gui.result_card import DONE, FAILED, NOTHING, WARNING, Outcome, Stat, took

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class Database(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.papers([("old.pdf", "An old paper")])

    def papers(self, rows):
        write(os.path.join(self.folder, "papers.csv"), ["paper_id", "filename", "title"],
              [(pid, pid, title) for pid, title in rows])

    def energies(self, rows):
        write(os.path.join(self.folder, "activation_energy.csv"),
              ["paper_id", "title", "material_formula", "activation_energy_eV"], rows)


class OutcomeTests(Database):
    def test_nothing_new_says_so(self):
        before = snapshot(self.folder)
        outcome = extraction_outcome(self.folder, before)
        self.assertEqual((outcome.status, outcome.title), (NOTHING, "Nothing new to extract"))
        self.assertIn("already in the database (1 article)", outcome.detail)

    def test_new_papers_their_values_and_the_lowest_with_its_article(self):
        before = snapshot(self.folder)
        self.papers([("old.pdf", "An old paper"), ("new.pdf", "Fast lithium argyrodites"), ("quiet.pdf", "A review")])
        self.energies([("old.pdf", "An old paper", "LiFePO4", "0.5"), ("new.pdf", "Fast lithium argyrodites", "Li6PS5Cl", "0.19"),
                       ("new.pdf", "Fast lithium argyrodites", "Li6PS5Br", "0.21")])
        outcome = extraction_outcome(self.folder, before, started=0)
        self.assertEqual(outcome.status, DONE)
        tiles = {stat.label: stat.value for stat in outcome.stats}
        self.assertEqual((tiles["articles read"], tiles["activation energies"]), ("2", "2"))
        self.assertIn("Low activation energy: Li6PS5Cl — 0.19 eV  (Fast lithium argyrodites)", outcome.highlights)
        self.assertIn("1 of the new articles gave no transport value", " ".join(outcome.highlights))

    def test_failures_and_stops_are_told(self):
        before = snapshot(self.folder)
        self.assertEqual(extraction_outcome(self.folder, before, failed=2).status, FAILED)
        self.papers([("old.pdf", "An old paper"), ("new.pdf", "New")])
        self.assertEqual(extraction_outcome(self.folder, before, failed=1).status, WARNING)
        stopped = extraction_outcome(self.folder, before, stopped=True, pdfs_pending=4)
        self.assertEqual((stopped.status, stopped.title), (WARNING, "Extraction stopped"))
        self.assertIn("4 PDF(s) are left to read", stopped.detail)

    def test_durations(self):
        self.assertEqual((took(42), took(194), took(7300)), ("42 s", "3 min 14 s", "2 h 01 min"))
        self.assertEqual((took(26 * 3600 + 300), took(3 * 86400)), ("1 day 2 h", "3 days"))  # many hours: days


from LocalExtraction.tests.test_gui import has_screen  # noqa: E402  (one check, made safely)


@unittest.skipUnless(has_screen(), "the card needs a screen")
class CardTests(unittest.TestCase):
    def test_the_card_shows_its_tiles_and_buttons_and_hides(self):
        from LocalExtraction.gui.result_card import ResultCard
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        below = tk.Frame(root)
        below.pack()
        card = ResultCard(root, before=below)
        self.assertFalse(card.winfo_manager())  # nothing to show yet
        pressed = []
        card.show(Outcome("Extraction finished", DONE, "2 new articles", [Stat("2", "articles read"), Stat("3", "Ea")],
                          ["Low activation energy: Li6PS5Cl"], [("Open", lambda: pressed.append(True))]), bell=False)
        root.update()
        self.assertEqual(card.winfo_manager(), "pack")
        self.assertEqual(root.pack_slaves().index(card), 0)  # above what it was put before
        self.assertEqual(len(card._tiles), 2)

        def buttons(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TButton":
                    yield child
                yield from buttons(child)
        [b for b in buttons(card) if b.cget("text") == "Open"][0].invoke()
        self.assertEqual(pressed, [True])
        card.hide()
        self.assertFalse(card.winfo_manager())


if __name__ == "__main__":
    unittest.main()
