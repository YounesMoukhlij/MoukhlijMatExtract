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


from LocalExtraction.tests.test_gui import has_screen as _has_screen  # noqa: E402  (one check, made safely)


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

    def test_at_its_smallest_the_window_still_shows_the_ranking(self):
        """The settings and the card of the last ranking above, the ranked materials below: the table keeps room
        for a few rows whatever the card holds."""
        self.app.book.select(self.app.tabs[self.app.component]["frame"])
        width, height = self.root.minsize()
        for size, card_in_view in ((f"{width}x{height}", False), ("1320x820", True)):  # smallest, then as it opens
            self.root.geometry(size)
            for _ in range(20):
                self.root.update()
            self.assertGreater(self.app.table.winfo_height(), 150, size)
            self.assertTrue(self.app.rank_button.winfo_ismapped(), size)  # the settings and their buttons stay whole
            self.assertTrue(self.app.mp_key_entry.winfo_ismapped(), size)  # and the Materials Project key
            rows = (self.app._actions, self.app._files_row)
            for button in (w for row in rows for w in row.winfo_children() if w.winfo_class() == "TButton"):
                self.assertLessEqual(button.winfo_reqwidth(), button.winfo_width() + 2, (size, button.cget("text")))
            if card_in_view:  # the card of the ranking done when it opened (smaller: drag the divider up to it)
                self.assertTrue(self.app.card.winfo_ismapped())

    def test_the_materials_project_key_is_typed_in_the_window_hidden_and_saved(self):
        from WebScraping.averageScrap import job as web_job
        env = Path(tempfile.mkdtemp()) / ".env"
        self.addCleanup(shutil.rmtree, env.parent, True)
        self.assertEqual(self.app.mp_key_entry.cget("show"), "•")  # never shown as typed
        with mock.patch.object(web_job, "ENV_PATH", str(env)), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MP_API_KEY", None)
            self.app.mp_key_var.set("  my-own-key  ")
            self.app.save_mp_key()
            self.assertIn("MP_API_KEY=my-own-key", env.read_text(encoding="utf-8"))
            self.assertEqual(os.environ["MP_API_KEY"], "my-own-key")  # this run uses it at once
            self.assertIn("saved", self.app.mp_status.get())
            self.assertNotIn("my-own-key", self.app.mp_status.get())
            self.app.mp_show_var.set(True)
            self.app._show_mp_key()
            self.assertEqual(self.app.mp_key_entry.cget("show"), "")

    def test_with_the_box_ticked_the_ranking_writes_the_materials_project_entries(self):
        from SelectingTopMaterial import materials_project
        calls = []
        with mock.patch.object(materials_project, "link", side_effect=lambda selections, out_dir, **k: calls.append(
                out_dir) or Path(out_dir) / materials_project.FILE):
            self.app.rank(write=True)
            self.app.wait_ranked()
            self.assertEqual(calls, [])  # not asked for
            self.app.mp_var.set(True)
            self.app.mp_key_var.set("a-key")  # typed, not saved: used for this ranking
            self.app.rank(write=True)
            self.app.wait_ranked()
        self.assertEqual(calls, [self.out])
        self.assertIn("Open the Materials Project entries", [label for label, _ in self.app.card.outcome.actions])

    def test_a_ranking_asked_for_after_the_main_folder_was_deleted_asks_first(self):
        from LocalExtraction.gui import home_guard
        asked = []
        with mock.patch.object(home_guard, "home_lost", return_value=True), \
                mock.patch("tkinter.messagebox.askyesno", side_effect=lambda *a, **k: asked.append(a) or False), \
                mock.patch.object(gui, "write_rankings") as write:
            self.app.rank(write=True)
            self.app.wait_ranked()
        self.assertEqual(len(asked), 1)  # "… was deleted while this window was open … make it again?"
        write.assert_not_called()        # said no: nothing ranked into a folder that is gone

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

    def test_while_it_ranks_it_says_so_and_a_failed_ranking_says_it_failed(self):
        with mock.patch.object(gui, "select_from_each", side_effect=RuntimeError("the database is unreadable")):
            self.app.rank(write=False)
            self.assertEqual(self.app.summary.get(), "Reading the databases and ranking the materials …")
            self.assertTrue(self.app.rank_progress.winfo_manager())  # the bar, beside Rank
            self.assertTrue(self.app.wait_ranked())
        self.assertFalse(self.app.rank_progress.winfo_manager())
        said = self.app.summary.get()
        self.assertNotIn("Reading the databases", said)  # not the step it was at
        self.assertIn("The ranking failed", said)
        self.assertIn("Press Rank to try again", said)
        self.assertTrue(any(name == "showerror" for name, _ in self.asked))

    def test_the_ranking_is_never_written_into_a_database(self):
        self.app.out_var.set(str(self.database))
        self.app.rank()
        self.app.wait_ranked()
        self.assertEqual(self.asked[0][0], "showerror")
        self.assertEqual(sorted(p.name for p in self.database.iterdir()), ["activation_energy.csv"])

    def test_the_window_has_the_filters_of_the_command(self):
        """The kind of energy (the screening ranks Arrhenius values only), the flagged values and the domain's
        classes, as mme-rank --kind, --include-flagged and --domain."""
        from SelectingTopMaterial.criteria import DOMAIN_CRITERIA, Criteria
        self.assertEqual(self.app.filters().kind, "")  # the same defaults as the command
        self.assertFalse(self.app.filters().include_flagged)
        self.assertEqual(self.app.criteria(), Criteria.load(DOMAIN_CRITERIA["electrolyte"]))
        self.app.kind_var.set("arrhenius")
        self.app.flagged_var.set(True)
        self.app.domain_var.set("cathode")
        filters = self.app.filters()
        self.assertEqual((filters.kind, filters.include_flagged), ("arrhenius", True))
        self.assertEqual(self.app.criteria(), Criteria.load(DOMAIN_CRITERIA["cathode"]))
        self.app.kind_var.set("migration_barrier")
        self.app.domain_var.set("electrolyte")
        self.app.rejected_var.set(False)
        self.app.rank(write=False)
        self.app.wait_ranked()
        self.assertEqual(self.rows(), [])  # no value of that kind

    def test_a_ranking_written_from_the_window_is_recorded_like_one_of_the_command(self):
        """The command skips a ranking already done with the same settings. The window writes the same files: it must
        say what it wrote, or the command would take the window's ranking for its own and skip."""
        import json
        from LocalExtraction.done import STAMP
        self.out.mkdir()
        (self.out / "summary.csv").write_text("written by the command\n")
        (self.out / STAMP).write_text(json.dumps({"rank": {"fingerprint": "the command's", "written": ["summary.csv"],
                                                           "at": "earlier"}}))
        self.app.origin_var.set("experimental")
        self.app.rank()
        self.app.wait_ranked()
        stamp = json.loads((self.out / STAMP).read_text())["rank"]
        self.assertNotEqual(stamp["fingerprint"], "the command's")
        self.assertIn("total/top_materials.csv", stamp["written"])
        run = json.loads((self.out / "run_manifest.json").read_text())["runs"][-1]
        self.assertEqual(run["part"], "ranking")
        self.assertIn("origin='experimental'", run["settings"]["filters"])


if __name__ == "__main__":
    unittest.main()
