# LocalExtraction/tests/test_single.py
"""One copy of each window: asked again, the open window comes to the front and a message says only one can be open;
once it is closed, the next request opens a new one. Checked on the registry itself and on real windows: a part of the
main window, the process flow (its “You are here” follows the window it is asked from), a “Delete outputs” button
(the window keeps its files while the dialog it would open is already open).

The window tests need a screen; without one they are skipped."""

import unittest
from unittest import mock

from LocalExtraction.gui import single
from LocalExtraction.tests.test_gui import has_screen


@unittest.skipUnless(has_screen(), "the window needs a screen")
class SingleWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        patch = mock.patch("tkinter.messagebox.showinfo")
        self.said = patch.start()
        self.addCleanup(patch.stop)

    def window(self):
        top = self.tk.Toplevel(self.root)
        top.attributes("-alpha", 0.0)
        return top

    def toplevels(self):
        return [w for w in self.root.winfo_children() if isinstance(w, self.tk.Toplevel) and w.winfo_exists()]

    def test_asked_again_the_open_one_comes_back_and_it_is_said(self):
        made = []

        def make():
            made.append(self.window())
            return made[-1]
        first = single.open_once("test:a", "The test window", self.root, make)
        again = single.open_once("test:a", "The test window", self.root, make)
        self.assertIs(again, first)
        self.assertEqual(len(made), 1)  # not opened a second time
        self.assertIn("The test window is already open", self.said.call_args[0][1])
        self.assertIn("Only one can be open at a time", self.said.call_args[0][1])
        first.destroy()
        self.root.update()
        third = single.open_once("test:a", "The test window", self.root, make)
        self.assertIsNot(third, first)  # closed: a new one
        self.assertEqual(len(made), 2)

    def test_other_windows_open_side_by_side(self):
        a = single.open_once("test:a", "A", self.root, self.window)
        b = single.open_once("test:b", "B", self.root, self.window)
        self.assertIsNot(a, b)
        self.said.assert_not_called()

    def test_a_minimised_window_is_shown_again(self):
        top = single.open_once("test:a", "A", self.root, self.window)
        top.iconify()
        self.root.update()
        single.open_once("test:a", "A", self.root, self.window)
        self.root.update()
        self.assertNotEqual(top.state(), "iconic")

    def test_a_window_that_did_not_open_is_not_remembered(self):
        self.assertIsNone(single.open_once("test:a", "A", self.root, lambda: None))  # a question cancelled
        self.assertIsNone(single.existing("test:a"))

    def test_the_decorator_brings_the_window_up_to_date(self):
        brought = []

        @single.once("test:deco", "The decorated window", again=lambda window, parent, word="": brought.append(word))
        def open_it(parent, word=""):
            return self.window()
        first = open_it(self.root, "one")
        self.assertIs(open_it(self.root, "two"), first)
        self.assertEqual(brought, ["two"])

    def test_a_part_of_the_main_window_opens_once(self):
        from mme_gui import hub
        with mock.patch("SelectingTopMaterial.gui.App") as app:
            hub.open_rank(self.root)
            hub.open_rank(self.root)
        self.assertEqual(app.call_count, 1)
        self.assertIn("Ranking is already open", self.said.call_args[0][1])

    def test_the_process_flow_opens_once_and_marks_the_window_it_is_asked_from(self):
        from mme_gui import process_flow
        win = process_flow.open_flow(self.root, "Web scraping")
        win.attributes("-alpha", 0.0)
        self.assertEqual(win.here, process_flow.here_of("Web scraping"))
        again = process_flow.open_flow(self.root, "Ranking the materials")
        self.assertIs(again, win)
        self.assertEqual(win.here, ("rank",))  # “You are here” moved
        self.assertEqual(win.diagram.texts.count("You are here"), 1)
        self.assertEqual(len([t for t in self.toplevels() if t.title() == "MoukhlijMatExtract · Process flow"]), 1)

    def test_a_delete_button_keeps_the_window_s_files_while_its_dialog_is_open(self):
        from LocalExtraction.gui import delete_outputs
        holder = self.window()
        before = mock.Mock()
        with mock.patch.object(delete_outputs, "DeleteOutputsDialog", side_effect=lambda *a, **k: self.window()) as dialog:
            button = delete_outputs.delete_outputs_button(holder, "rank", before=before)
            button.invoke()
            button.invoke()
        self.assertEqual(dialog.call_count, 1)
        self.assertEqual(before.call_count, 1)  # not let go of its files a second time for nothing
        self.assertIn("is already open", self.said.call_args[0][1])
