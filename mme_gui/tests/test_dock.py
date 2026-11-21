# mme_gui/tests/test_dock.py
"""“Add MoukhlijMatExtract to the Dock?”: offered on macOS only, when the program is not in the Dock and the offer was
not declined; “Add” makes the app when missing, adds it once and restarts the Dock; “Don't ask again” is remembered.
The real Dock is never touched: its contents and the commands are stand-ins."""

import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen
from mme_gui import dock

APPS = [{"tile-data": {"file-data": {"_CFURLString": "file:///System/Applications/Mail.app/", "_CFURLStringType": 15},
                       "file-label": "Mail"}, "tile-type": "file-tile"}]
WITH_MME = APPS + [{"tile-data": {"file-data": {"_CFURLString": "file:///Users/me/Applications/MoukhlijMatExtract.app/"}},
                    "tile-type": "file-tile"}]


class DockTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        patch = mock.patch.object(dock, "DECLINED", self.base / "dock_declined")
        patch.start()
        self.addCleanup(patch.stop)
        self.app = self.base / "MoukhlijMatExtract.app"
        self.app.mkdir()

    def test_it_knows_whether_the_program_is_in_the_dock(self):
        self.assertFalse(dock.in_dock(APPS))
        self.assertTrue(dock.in_dock(WITH_MME))
        self.assertFalse(dock.in_dock([{"tile-type": "spacer-tile"}]))  # entries without a file

    def test_it_is_offered_on_macos_only_when_missing_and_not_declined(self):
        with mock.patch.object(dock, "dock_apps", return_value=APPS):
            self.assertTrue(dock.should_offer("darwin"))
            self.assertFalse(dock.should_offer("linux"))
            self.assertFalse(dock.should_offer("win32"))
            dock.decline()
            self.assertFalse(dock.should_offer("darwin"))  # “Don't ask again” is remembered
        self.assertTrue((self.base / "dock_declined").exists())
        (self.base / "dock_declined").unlink()
        with mock.patch.object(dock, "dock_apps", return_value=WITH_MME):
            self.assertFalse(dock.should_offer("darwin"))  # already there

    def test_the_entry_is_one_the_dock_reads(self):
        entry = plistlib.loads(('<?xml version="1.0"?><plist version="1.0">' + dock.tile(self.app) + "</plist>").encode())
        url = entry["tile-data"]["file-data"]["_CFURLString"]
        self.assertTrue(url.startswith("file:///") and url.endswith("MoukhlijMatExtract.app/"))
        self.assertEqual(entry["tile-type"], "file-tile")

    def test_add_puts_it_in_the_dock_once_and_restarts_the_dock(self):
        calls = []
        run = lambda args, **k: calls.append(args) or subprocess.CompletedProcess(args, 0)  # noqa: E731
        with mock.patch.object(dock, "dock_apps", return_value=APPS):
            self.assertEqual(dock.add(self.app, run=run), self.app)
        self.assertEqual(calls[0][:5], ["defaults", "write", "com.apple.dock", "persistent-apps", "-array-add"])
        self.assertIn("MoukhlijMatExtract.app", calls[0][5])
        self.assertEqual(calls[1], ["killall", "Dock"])
        calls.clear()
        with mock.patch.object(dock, "dock_apps", return_value=WITH_MME):
            dock.add(self.app, run=run)
        self.assertEqual(calls, [])  # never twice

    def test_a_missing_app_is_made_first(self):
        made = self.base / "made" / "MoukhlijMatExtract.app"
        run = lambda args, **k: subprocess.CompletedProcess(args, 0)  # noqa: E731
        with mock.patch.object(dock, "dock_apps", return_value=APPS):
            self.assertEqual(dock.add(self.base / "none.app", build=lambda: made, run=run), made)

    def test_a_dock_that_cannot_be_changed_is_said(self):
        run = lambda args, **k: subprocess.CompletedProcess(args, 1)  # noqa: E731
        with mock.patch.object(dock, "dock_apps", return_value=APPS), self.assertRaisesRegex(RuntimeError, "drag"):
            dock.add(self.app, run=run)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class DialogTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        patch = mock.patch.object(dock, "DECLINED", self.base / "dock_declined")
        patch.start()
        self.addCleanup(patch.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def test_the_question_and_its_three_answers(self):
        win = dock._dialog(self.root)
        win.attributes("-alpha", 0.0)
        self.root.update_idletasks()
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:
                    pass
                walk(child)
        walk(win)
        for words in ("Add MoukhlijMatExtract to the Dock?", "Add to the Dock", "Not now", "Don't ask again"):
            self.assertIn(words, texts)
        win.never()
        self.assertTrue((self.base / "dock_declined").exists())
        self.assertFalse(win.winfo_exists())

    def test_add_says_it_was_added(self):
        win = dock._dialog(self.root)
        win.attributes("-alpha", 0.0)
        with mock.patch.object(dock, "add", return_value=Path("/Users/me/Applications/MoukhlijMatExtract.app")), \
                mock.patch("tkinter.messagebox.showinfo") as said:
            win.add_it()
        self.assertIn("Added", said.call_args[0][1])
