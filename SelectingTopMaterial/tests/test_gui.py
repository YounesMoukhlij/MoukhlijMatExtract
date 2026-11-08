# SelectingTopMaterial/tests/test_gui.py
"""Tests of the window of the selection, built transparent on a small made-up database in a
temporary folder. Without a screen they are skipped (as they are with
MME_NO_WINDOW_TESTS=1).

    python -m unittest discover -s SelectingTopMaterial/tests -t .     # or: pytest SelectingTopMaterial
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from SelectingTopMaterial import gui
from SelectingTopMaterial.tests.test_selection import row, write_database

try:
    import tkinter as tk
except ImportError:  # a Python built without Tk
    tk = None


def _has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


class FieldTests(unittest.TestCase):
    def test_the_elements_of_a_field(self):
        self.assertEqual(gui.elements("li, Na  na"), ("Li", "Na"))
        self.assertEqual(gui.elements(""), ())
        with self.assertRaises(ValueError):
            gui.elements("Li Xx")


@unittest.skipUnless(_has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.database = write_database(self.tmp / "local_output", [
            row("Li6PS5Cl", 0.22), row("Li6PS5Cl", 0.24, paper="B.pdf"),
            row("Li7La3Zr2O12", 0.35, data_origin="simulation"), row("LiFePO4", 0.6)])
        self.out = self.tmp / "results"
        self.asked = []
        for name in ("showerror", "showinfo"):
            patcher = mock.patch(f"tkinter.messagebox.{name}",
                                 side_effect=lambda *a, _n=name, **k: self.asked.append((_n, a[1] if len(a) > 1 else "")))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)  # drawn, as in real use, but not seen
        self.addCleanup(self.root.destroy)
        self.app = gui.App(self.root, sources=[self.database], out_dir=self.out)
        self.assertTrue(self.app.wait_ranked())  # the ranking runs on its own thread

    def rows(self) -> list[tuple]:
        return [self.app.table.item(i, "values") for i in self.app.table.get_children()]

    def test_it_ranks_what_the_folder_holds_as_soon_as_it_opens_and_writes_nothing_yet(self):
        rows = self.rows()
        self.assertEqual([(r[1], r[2]) for r in rows],
                         [("Li6PS5Cl", "Superionic"), ("Li7La3Zr2O12", "Acceptable"), ("LiFePO4", "Rejected")])
        self.assertEqual(rows[0][5], "2")  # two values behind the first one
        self.assertIn("3 materials", self.app.summary.get())
        self.assertFalse(self.out.exists())
        self.assertEqual(str(self.app.open_report_button["state"]), "disabled")
        self.assertIn("4 values", self.app.sources[0][2].get())  # what the folder gave

    def test_rank_writes_the_files_and_opens_them(self):
        self.app.rank()
        self.app.wait_ranked()
        self.assertTrue((self.out / "total" / "top_materials.csv").is_file())  # one folder per component
        self.assertTrue((self.out / "total" / "report.html").is_file())
        self.assertTrue((self.out / "summary.csv").is_file())
        self.assertIn("Written to", self.app.summary.get())
        self.assertEqual(str(self.app.open_report_button["state"]), "normal")
        with mock.patch.object(gui, "open_path") as opened:
            self.app._open(".html")
        opened.assert_called_once_with(self.out / "total" / "report.html")

    def test_the_fields_choose_the_values(self):
        self.app.origin_var.set("experimental")
        self.app.rejected_var.set(False)
        self.app.rank(write=False)
        self.app.wait_ranked()
        self.assertEqual([r[1] for r in self.rows()], ["Li6PS5Cl"])
        self.app.elements_var.set("Xx")
        self.app.rank(write=False)
        self.app.wait_ranked()
        self.assertEqual(self.asked, [("showerror", "Elements: 'Xx' is not the symbol of an element (Li, Na, ...)")])

    def test_a_material_shows_its_values_and_where_they_were_read(self):
        window = self.app.details(self.app._shown_materials[0])
        text = window.winfo_children()[0].get("1.0", "end")
        self.assertIn("Li6PS5Cl shows an activation energy of 0.22 eV.", text)
        self.assertIn("page 3", text)

    def test_the_window_answers_while_it_ranks(self):
        import time
        real = gui.select_from_each

        def slow(*args, **kwargs):
            time.sleep(1.0)  # a large database
            return real(*args, **kwargs)
        with mock.patch.object(gui, "select_from_each", side_effect=slow):
            start = time.perf_counter()
            self.app.rank(write=False)
            self.assertLess(time.perf_counter() - start, 0.3)  # back to the window at once
            self.assertEqual(str(self.app.rank_button["state"]), "disabled")
            self.assertTrue(self.app.wait_ranked())
        self.assertEqual(str(self.app.rank_button["state"]), "normal")
        self.assertEqual(len(self.rows()), 3)

    def test_the_ranking_is_never_written_into_a_database(self):
        self.app.out_var.set(str(self.database))
        self.app.rank()
        self.app.wait_ranked()
        self.assertEqual(self.asked[0][0], "showerror")
        self.assertEqual(sorted(p.name for p in self.database.iterdir()), ["activation_energy.csv"])


if __name__ == "__main__":
    unittest.main()
