# mme_gui/tests/test_hub.py
"""The hub window: the Requirements button is red until the guide is opened, then green (and that is
remembered on disk), and the guide holds the manual and the requirements (Chrome, Tesseract, …).

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
        for needed in ("Tesseract", "Google Chrome", "spacy download en_core_web_sm", "API keys",
                       "Local extraction", "Web scraping", "Ranking", "Classification"):
            self.assertIn(needed, hub.MANUAL, needed)
        # … and the features a newcomer would not find alone.
        for needed in ("Search settings", "Fetched DOIs", "main results folder", "results card", "Delete outputs",
                       "skipped"):
            self.assertIn(needed, hub.MANUAL, needed)


@unittest.skipUnless(has_screen(), "the window needs a screen")
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

    def test_the_guide_opens_with_the_manual(self):
        import tkinter as tk
        window = hub.open_requirements(self.root)
        self.root.update_idletasks()
        self.assertIsInstance(window, tk.Toplevel)
        texts = [w for w in _descendants(window) if isinstance(w, tk.Text)]
        self.assertTrue(texts)
        shown = texts[0].get("1.0", "end")
        self.assertIn("Tesseract", shown)
        self.assertIn("Chrome", shown)
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
        self.assertTrue((self.home / "Classification" / "crystal_structure").is_dir())
        self.assertEqual(self.button(row).cget("text"), "Open the main results folder")
        with mock.patch("LocalExtraction.gui.widgets.open_path") as opened:
            self.button(row).invoke()
        opened.assert_called_once_with(str(self.home))

    def test_the_hub_does_not_make_the_folder_but_a_part_does(self):
        hub.build(self.root)
        self.assertFalse(self.home.exists())
        hub._open(self.root, lambda root: None)
        self.assertTrue(self.home.is_dir())


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
