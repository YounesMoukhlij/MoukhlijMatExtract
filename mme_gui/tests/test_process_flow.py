# mme_gui/tests/test_process_flow.py
"""The process flow and its floating “⇄ Flow” button: every step drawn once and joined by known arrows, inside its
lane; the window it is opened from marked “You are here”; a click on a step says where to click, and opens the part
when it is one; the button in every window with a header band, never over a control, opening the flow on a click and
moving on a drag.

The window tests need a screen; without one they are skipped."""

import unittest
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen
from mme_gui import process_flow as flow


class ContentTests(unittest.TestCase):
    def test_every_step_is_drawn_once_and_joined_by_known_arrows(self):
        self.assertEqual(set(flow.NODES), set(flow.BY_KEY))
        known = set(flow.NODES) | set(flow.PLACES)
        for a, b in flow.EDGES:
            self.assertIn(a, known)
            self.assertIn(b, known)
        self.assertIn(("release", "zenodo"), flow.EDGES)   # the ends of the process
        self.assertIn(("paper", "article"), flow.EDGES)

    def test_each_step_says_where_what_and_why(self):
        for step in flow.STEPS:
            with self.subTest(step=step.key):
                self.assertTrue(step.where and step.what and step.why)
                self.assertIn(step.stage, flow.STAGE)
                self.assertIn(step.opens, ("", "local", "web", "rank", "classify", "ml"))

    def test_the_windows_it_marks_are_steps(self):
        for title, keys in flow.HERE.items():
            for key in keys:
                self.assertIn(key, flow.BY_KEY, title)
        self.assertEqual(flow.here_of("Web scraping"), ("job", "dois", "search", "review", "download", "extract"))
        self.assertEqual(flow.here_of("A window it does not know"), ())

    def test_a_spot_is_the_first_that_covers_no_control(self):
        rect = flow._rectangle(flow.SPOTS[0], 1000, 800, 80, 30)  # bottom right, 18 px in, 40 px up
        self.assertEqual(rect, (902, 730, 80, 30))
        self.assertEqual(flow._rectangle(("sw", 0.0, 1.0, 18, -40), 1000, 800, 80, 30), (18, 730, 80, 30))
        self.assertEqual(flow._rectangle(("s", 0.5, 1.0, 0, -40), 1000, 800, 80, 30), (460, 730, 80, 30))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def pump(self, seconds=0.8):
        import time
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def test_every_step_is_inside_its_lane_and_the_window_it_came_from_is_marked(self):
        win = flow.open_flow(self.root, "Web scraping")
        win.attributes("-alpha", 0.0)
        self.root.update_idletasks()
        canvas = win.diagram.canvas
        for key in flow.NODES:
            x1, y1, x2, y2 = canvas.bbox(f"s:{key}")
            self.assertTrue(any(top - 1 <= y1 and y2 <= bottom + 1 for _, top, bottom in flow.LANES), key)
            self.assertLessEqual(x2, flow.WIDTH - 12)
        self.assertEqual(win.diagram.texts.count("You are here"), 6)
        self.assertIn("2 · Search", win.diagram.texts)

    def test_a_step_says_where_and_opens_its_part(self):
        win = flow.open_flow(self.root, "Ranking the materials")
        win.attributes("-alpha", 0.0)
        win.diagram.choose("classify", tell=True)  # as a click on the step does
        self.assertEqual(win.chosen, "classify")
        from mme_gui import hub
        with mock.patch.object(hub, "_open") as opened:
            win.show("classify")

            def find(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == "TButton" and str(child.cget("text")).startswith("Open "):
                        return child
                    found = find(child)
                    if found is not None:
                        return found
            button = find(win)
            self.assertEqual(button.cget("text"), "Open Classification")
            button.invoke()
        self.assertIs(opened.call_args[0][1], hub.open_classify)

    def test_every_window_with_a_header_has_the_button_and_the_flow_window_none(self):
        import tkinter as tk
        from LocalExtraction.gui import design
        top = tk.Toplevel(self.root)
        top.attributes("-alpha", 0.0)
        band = design.header(top, "Classification", "the materials")
        self.assertIsNotNone(band.flow)
        self.assertIs(top._mme_flow_button, band.flow)
        win = flow.open_flow(self.root)
        win.attributes("-alpha", 0.0)
        self.assertFalse(hasattr(win, "_mme_flow_button"))

    def test_the_button_never_covers_a_control(self):
        import tkinter as tk
        from tkinter import ttk
        from LocalExtraction.gui import design
        top = tk.Toplevel(self.root)
        top.attributes("-alpha", 0.0)
        top.geometry("700x500")
        design.header(top, "Classification", "the materials")
        corner = ttk.Button(top, text="A button in the corner")
        corner.place(relx=1.0, rely=1.0, x=-10, y=-30, anchor="se")  # where the button would go first
        self.pump()
        top._mme_flow_button.settle()
        self.pump(0.3)
        b, c = top._mme_flow_button, corner
        overlap = (b.winfo_rootx() < c.winfo_rootx() + c.winfo_width() and c.winfo_rootx() < b.winfo_rootx() + b.winfo_width()
                   and b.winfo_rooty() < c.winfo_rooty() + c.winfo_height() and c.winfo_rooty() < b.winfo_rooty() + b.winfo_height())
        self.assertFalse(overlap)
        self.assertTrue(b.winfo_ismapped())

    def test_another_tab_moves_the_button_off_its_controls(self):
        import tkinter as tk
        from tkinter import ttk
        from LocalExtraction.gui import design
        top = tk.Toplevel(self.root)
        top.attributes("-alpha", 0.0)
        top.geometry("700x500")
        design.header(top, "Web scraping", "")
        book = ttk.Notebook(top)
        book.pack(fill="both", expand=True)
        empty, busy = ttk.Frame(book), ttk.Frame(book)
        book.add(empty, text="Empty")
        book.add(busy, text="With a button")
        corner = ttk.Button(busy, text="In the corner of this tab")
        corner.place(relx=1.0, rely=1.0, x=-10, y=-30, anchor="se")  # on the first spot
        self.pump()  # on the empty tab: the first spot
        book.select(busy)
        self.pump(0.8)  # the tab changed: the spot is looked at again
        b, c = top._mme_flow_button, corner
        overlap = (b.winfo_rootx() < c.winfo_rootx() + c.winfo_width() and c.winfo_rootx() < b.winfo_rootx() + b.winfo_width()
                   and b.winfo_rooty() < c.winfo_rooty() + c.winfo_height() and c.winfo_rooty() < b.winfo_rooty() + b.winfo_height())
        self.assertFalse(overlap)

    def test_a_click_opens_the_flow_and_a_drag_moves_the_button(self):
        import tkinter as tk
        from LocalExtraction.gui import design
        top = tk.Toplevel(self.root)
        top.attributes("-alpha", 0.0)
        top.geometry("700x500")
        design.header(top, "ML datasets", "")
        self.pump()
        button = top._mme_flow_button
        with mock.patch.object(flow, "open_flow") as opened:
            button.event_generate("<ButtonPress-1>", x=5, y=5, rootx=100, rooty=100)
            button.event_generate("<ButtonRelease-1>", x=5, y=5, rootx=100, rooty=100)
            self.assertEqual(opened.call_args[0][1], "ML datasets")  # a click: the flow, its steps marked
            opened.reset_mock()
            before = button.winfo_x()
            button.event_generate("<ButtonPress-1>", x=5, y=5, rootx=300, rooty=300)
            button.event_generate("<B1-Motion>", x=5, y=5, rootx=200, rooty=280)
            button.event_generate("<ButtonRelease-1>", x=5, y=5, rootx=200, rooty=280)
            self.pump(0.2)
            opened.assert_not_called()  # a drag moves it, opens nothing
            self.assertLess(button.winfo_x(), before)
