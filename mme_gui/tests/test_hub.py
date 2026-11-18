# mme_gui/tests/test_hub.py
"""The hub window: the Requirements button is red until the guide is opened, then green (and that is
remembered on disk), and the guide holds the manual and the requirements (Tesseract, the language model, …).

The window tests need a screen; without one they are skipped."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen
from mme_gui import hub


class MarkerTests(unittest.TestCase):
    """The red/green state, remembered between sessions — no screen needed."""

    def setUp(self):
        self.marker = Path(tempfile.mkdtemp()) / "sub" / "requirements_seen"
        patch = mock.patch.object(hub, "_MARKER", self.marker)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_starts_unseen_and_is_remembered_once_opened(self):
        self.assertFalse(hub.requirements_seen())
        hub.mark_requirements_seen()
        self.assertTrue(hub.requirements_seen())
        self.assertTrue(self.marker.exists())  # written to disk, so the next session reads green

    def test_a_read_only_home_does_not_crash(self):
        with mock.patch.object(Path, "mkdir", side_effect=OSError):
            hub.mark_requirements_seen()  # must not raise
        self.assertFalse(hub.requirements_seen())


class ManualTests(unittest.TestCase):
    def test_the_manual_names_what_the_program_needs(self):
        for needed in ("Tesseract", "spacy download en_core_web_sm", "API keys",
                       "Local extraction", "Web scraping", "Ranking", "Classification"):
            self.assertIn(needed, hub.MANUAL, needed)
        # … and the features a newcomer would not find alone.
        for needed in ("Search settings", "Pause", "main results folder", "results card", "Delete outputs",
                       "skipped"):
            self.assertIn(needed, hub.MANUAL, needed)


@unittest.skipUnless(has_screen(), "the window needs a screen")
def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)


class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.marker = Path(tempfile.mkdtemp()) / "requirements_seen"
        patch = mock.patch.object(hub, "_MARKER", self.marker)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def _close_dialogs(self):
        import tkinter as tk
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()

    def test_the_button_is_red_until_opened_then_green(self):
        button = hub.build(self.root)
        self.root.update_idletasks()
        self.assertIn("Requirements", button.cget("text"))
        self.assertEqual(str(button.cget("background")), hub._RED)  # red the first time

        button.open()  # opening the guide marks it seen and turns the button green
        self.root.update_idletasks()
        self.assertTrue(self.marker.exists())
        self.assertEqual(str(button.cget("background")), hub._GREEN)
        self._close_dialogs()

    def test_a_later_session_starts_green(self):
        hub.mark_requirements_seen()  # as if opened in an earlier session
        button = hub.build(self.root)
        self.root.update_idletasks()
        self.assertEqual(str(button.cget("background")), hub._GREEN)

    def test_at_its_smallest_each_part_says_what_it_does_whole(self):
        """The line under each part's name wraps to the room it has, rather than being cut at the card's edge."""
        hub.build(self.root)
        width, height = self.root.minsize()
        self.root.geometry(f"{width}x{height}")
        for _ in range(10):
            self.root.update()
        descriptions = {d for _, d, _, _ in hub.PARTS}
        labels = [w for w in _widgets(self.root) if w.winfo_class() == "TLabel" and str(w.cget("text")) in descriptions]
        self.assertEqual(len(labels), len(descriptions))
        for label in labels:
            self.assertLessEqual(label.winfo_reqwidth(), label.winfo_width() + 2, label.cget("text"))
        # Smaller than all it holds: the rest is a scroll away, never cut off.
        body = next(w for w in _widgets(self.root) if hasattr(w, "scrolls"))
        self.assertTrue(body.scrolls())

    def test_it_opens_tall_enough_for_all_it_holds_as_far_as_the_screen_allows(self):
        from LocalExtraction.gui import layout
        hub.build(self.root)
        for _ in range(20):
            self.root.update()
        body = next(w for w in _widgets(self.root) if hasattr(w, "scrolls"))
        content = body.inner.winfo_reqheight()
        if content + 200 < layout.usable(self.root)[1]:  # a screen tall enough: everything in view, no bar
            self.assertFalse(body.scrolls())
        self.assertLessEqual(self.root.winfo_height(), layout.usable(self.root)[1] + 2)

    def test_the_guide_opens_with_the_manual(self):
        import tkinter as tk
        window = hub.open_requirements(self.root)
        self.root.update_idletasks()
        self.assertIsInstance(window, tk.Toplevel)
        texts = [w for w in _descendants(window) if isinstance(w, tk.Text)]
        self.assertTrue(texts)
        shown = texts[0].get("1.0", "end")
        self.assertIn("Tesseract", shown)
        self.assertIn("spacy download", shown)
        window.destroy()


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(has_screen(), "the window needs a screen")
class FolderButtonTests(unittest.TestCase):
    """The main results folder button: "Create …" while ~/MoukhlijMatExtract is missing, then "Open …"."""

    def setUp(self):
        import tkinter as tk
        import shutil
        from LocalExtraction import about
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        self.home = base / "MoukhlijMatExtract"
        patch = mock.patch.object(about, "PROJECT_HOME", self.home)
        patch.start()
        self.addCleanup(patch.stop)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def button(self, row):
        return [w for w in row.winfo_children() if w.winfo_class() == "TButton"][0]

    def test_create_then_open(self):
        row = hub.folder_button(self.root, self.root)
        self.assertEqual(self.button(row).cget("text"), "Create the main results folder")
        with mock.patch("tkinter.messagebox.showinfo") as told:
            self.button(row).invoke()
        told.assert_called_once()
        self.assertTrue((self.home / "LocalExtraction" / "papers").is_dir())
        self.assertTrue((self.home / "configs" / "garnet_nasicon.yaml").is_file())  # the job files with it
        self.assertTrue((self.home / "docs" / "MANUAL.md").is_file())  # … and the documents
        self.assertTrue((self.home / "Classification" / "crystal_structure").is_dir())
        self.assertEqual(self.button(row).cget("text"), "Open the main results folder")
        with mock.patch("LocalExtraction.gui.widgets.open_path") as opened:
            self.button(row).invoke()
        opened.assert_called_once_with(str(self.home))

    def test_the_hub_does_not_make_the_folder_but_asks_before_a_part_opens(self):
        hub.build(self.root)
        self.assertFalse(self.home.exists())
        opened = []
        with mock.patch("tkinter.messagebox.askyesno", return_value=False) as asked:
            hub._open(self.root, opened.append, what="Web scraping")
        self.assertIn("Web scraping needs it", asked.call_args[0][1])
        self.assertEqual((opened, self.home.exists()), ([], False))  # “No”: not opened, nothing made
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            hub._open(self.root, opened.append, what="Web scraping")
        self.assertEqual(len(opened), 1)
        self.assertTrue((self.home / "configs" / "garnet_nasicon.yaml").is_file())
        self.assertTrue((self.home / "docs" / "MANUAL.md").is_file())

    def test_deleted_job_files_are_said_and_made_again_without_touching_the_edited_ones(self):
        import mme_home
        row = hub.folder_button(self.root, self.root)
        with mock.patch("tkinter.messagebox.showinfo") as told:
            self.button(row).invoke()  # “Create the main results folder”
        made = told.call_args[1].get("message") or told.call_args[0][1]
        jobs, documents = len(mme_home.shipped(mme_home.CONFIGS)), len(mme_home.shipped(mme_home.DOCS))
        self.assertIn(f"configs — the {jobs} job files", made)
        self.assertIn("garnet_nasicon.yaml", made)
        self.assertIn(f"docs — the {documents} documents", made)
        status = [w for w in row.winfo_children() if w.winfo_class() == "TLabel"][0]
        self.assertTrue(status.cget("text").startswith(f"✓ {jobs} job files in configs/"))

        (self.home / "configs" / "halide.yaml").unlink()
        (self.home / "configs" / "garnet.yaml").write_text("name: mine\n", encoding="utf-8")
        row.refresh()
        self.assertIn(f"1 of the {jobs} job files are missing", status.cget("text"))
        self.assertTrue(status.cget("text").startswith("⚠"))
        restore = [w for w in row.winfo_children() if w.winfo_class() == "TButton"][1]
        self.assertEqual(restore.cget("text"), "Restore the job files")
        with mock.patch("tkinter.messagebox.showinfo") as told:
            restore.invoke()
        self.assertIn("halide.yaml", told.call_args[0][1] if len(told.call_args[0]) > 1 else told.call_args[1]["message"])
        self.assertTrue((self.home / "configs" / "halide.yaml").is_file())
        self.assertEqual((self.home / "configs" / "garnet.yaml").read_text(encoding="utf-8"), "name: mine\n")
        self.assertEqual(mme_home.status(self.home)["configs"], [])

    def test_the_main_window_warns_at_its_start_when_the_folder_is_missing(self):
        hub.build(self.root)
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as asked, \
                mock.patch("tkinter.messagebox.showinfo"):
            hub.warn_if_missing(self.root)
        self.assertIn("does not exist", asked.call_args[0][1])
        self.assertTrue((self.home / "configs" / "sse.yaml").is_file())
        with mock.patch("tkinter.messagebox.askyesno") as asked:
            hub.warn_if_missing(self.root)  # nothing missing: nothing asked
        asked.assert_not_called()


@unittest.skipUnless(has_screen(), "the window needs a screen")
class ResultsButtonTests(unittest.TestCase):
    def test_each_part_has_a_results_button_that_opens_its_tables(self):
        import tkinter as tk
        from LocalExtraction.gui.browser import ResultsBrowser
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        hub.build(root)

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        buttons = [w for w in walk(root) if w.winfo_class() == "TButton" and w.cget("text") == "Results…"]
        self.assertEqual(len(buttons), 4)
        buttons[0].invoke()
        root.update()
        self.assertTrue(any(isinstance(w, ResultsBrowser) for w in walk(root)))


class PartStatusTests(unittest.TestCase):
    def test_each_part_says_what_its_folder_holds(self):
        import tempfile
        from LocalExtraction.gui import browser
        home = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, home, True)
        web = home / "WebScraping" / "web_output"
        web.mkdir(parents=True)
        (web / "papers.csv").write_text("paper_id\na\nb\n", encoding="utf-8")
        (web / "activation_energy.csv").write_text("paper_id\na\n", encoding="utf-8")
        real = browser.part_tables
        with mock.patch.object(browser, "part_tables", side_effect=lambda part: real(part, home)):
            self.assertEqual(hub.part_status("web"), "database: 2 papers, 1 activation energies · 0 checked by hand")
            self.assertEqual(hub.part_status("local"), "no database yet")
            self.assertEqual(hub.part_status("rank"), "no ranking written yet")
            self.assertEqual(hub.part_status("classify"), "no classes written yet")
