# LocalExtraction/tests/test_back.py
"""“‹ Back”: every window opened from another one has a way back to it besides the title bar's close button — at the
left of its header band, or at the bottom of a window without one — that asks first while a step still runs."""

import unittest
from unittest import mock

from LocalExtraction.gui import design
from LocalExtraction.tests.test_gui import has_screen, tk


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _backs(widget):
    return [w for w in _walk(widget) if getattr(w, "back", False) is True]


@unittest.skipUnless(has_screen(), "the window needs a screen")
class BackTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.root._mme_hub = True
        self.addCleanup(self.root.destroy)

    def window(self):
        window = tk.Toplevel(self.root)
        design.header(window, "A part", "what it does", compact=True)
        self.root.update()
        return window

    def test_a_window_opened_from_the_main_window_has_back_to_it(self):
        window = self.window()
        pill, = _backs(window)
        self.assertEqual(pill.cget("text"), design.BACK_TO_MAIN)
        pill.event_generate("<Button-1>")
        self.root.update()
        self.assertFalse(window.winfo_exists())
        self.assertTrue(self.root.winfo_exists())  # the main window is still there

    def test_a_window_opened_from_another_one_says_back(self):
        second = tk.Toplevel(self.window())
        design.header(second, "About", "")
        self.assertEqual(_backs(second)[0].cget("text"), design.BACK)

    def test_a_window_started_alone_has_no_back(self):
        design.header(self.root, "Alone", "")
        self.assertEqual(_backs(self.root), [])

    def test_while_a_step_runs_it_asks_first_and_stays_on_no(self):
        window = self.window()
        closed = []
        window._mme_busy, window._mme_close = (lambda: True), (lambda: closed.append(True))
        with mock.patch("tkinter.messagebox.askyesno", return_value=False) as asked:
            self.assertFalse(design.go_back(window))
        self.assertIn("Going back stops it", asked.call_args.args[1])
        self.assertEqual(closed, [])
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            self.assertTrue(design.go_back(window))
        self.assertEqual(closed, [True])  # the window's own close: it stops its step and lets go of its files

    def test_work_that_cannot_be_stopped_is_waited_for_without_a_question(self):
        """A classification or a ranking (seconds, its files written in one go): “‹ Back” pressed while it runs asks
        nothing, says it goes back when it is done, and does once it is."""
        import time
        window = self.window()
        state = {"busy": True}
        window._mme_busy, window._mme_finish_first = (lambda: state["busy"]), True
        with mock.patch("tkinter.messagebox.askyesno") as asked:
            self.assertFalse(design.go_back(window))
            self.assertIn("Going back when it's done", window._mme_back_pill.cget("text"))
            self.root.update()
            self.assertTrue(window.winfo_exists())  # still writing: the window waits
            state["busy"] = False
            end = time.monotonic() + 3
            while window.winfo_exists() and time.monotonic() < end:
                self.root.update()
                time.sleep(0.02)
        asked.assert_not_called()
        self.assertFalse(window.winfo_exists())

    def test_classification_and_ranking_wait_instead_of_asking(self):
        """Opened, the classification starts at once: “‹ Back” then must not ask to stop what cannot be stopped."""
        from mme_gui import hub
        hub.build(self.root)
        for opener in (hub.open_classify, hub.open_rank):
            before = set(self.root.winfo_children())
            opener(self.root)
            self.root.update()
            window, = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w not in before]
            self.assertTrue(getattr(window, "_mme_finish_first", False), opener.__name__)
            self.assertIn(window._mme_busy(), (True, False))
            design.go_back(window)
            for _ in range(200):
                if not window.winfo_exists():
                    break
                self.root.update()
                __import__("time").sleep(0.02)

    def test_a_window_without_a_header_band_has_back_at_the_bottom(self):
        window = tk.Toplevel(self.root)
        button = design.back_button(window)
        button.pack()
        self.assertEqual(button.cget("text"), design.BACK_TO_MAIN)
        button.invoke()
        self.assertFalse(window.winfo_exists())

    def test_the_part_windows_and_guides_opened_from_the_main_window_have_it(self):
        from mme_gui import hub
        hub.build(self.root)
        for opener in (hub.open_rank, hub.open_ml, hub.open_requirements):
            before = set(self.root.winfo_children())
            opener(self.root)
            self.root.update()
            window, = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w not in before]
            self.assertEqual([w.cget("text") for w in _backs(window)], [design.BACK_TO_MAIN], opener.__name__)
            design.go_back(window)
            self.root.update()


if __name__ == "__main__":
    unittest.main()
