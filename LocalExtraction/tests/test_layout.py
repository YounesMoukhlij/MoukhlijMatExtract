# LocalExtraction/tests/test_layout.py
"""Windows that fit the screen they open on, and areas a person resizes by dragging the line between them."""

import unittest
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen, tk


def screen(width, height):
    return mock.patch.multiple(tk.Misc, winfo_screenwidth=lambda self: width, winfo_screenheight=lambda self: height)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class PlaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def placed(self, width, height, size, minsize):
        from LocalExtraction.gui import layout
        asked = []  # the geometry asked for (this computer's own screen would pull it back onto itself)
        with screen(width, height), mock.patch.object(self.root, "geometry", side_effect=asked.append):
            layout.place(self.root, size, minsize)
            usable = layout.usable(self.root)
        geometry = asked[-1]
        w, rest = geometry.split("x")
        h, x, y = rest.split("+")
        return (int(w), int(h), int(x), int(y)), self.root.minsize(), usable

    def test_a_small_laptop_gets_a_window_within_its_screen_and_a_minimum_it_can_hold(self):
        (w, h, x, y), (mw, mh), (uw, uh) = self.placed(1280, 720, (1280, 860), (960, 760))
        self.assertLessEqual((w, h), (uw, uh))
        self.assertLessEqual(w, uw)
        self.assertLessEqual(h, uh)
        self.assertLessEqual(mh, h)
        self.assertLessEqual(mw, w)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)

    def test_a_large_screen_gets_a_larger_window_centred(self):
        (w, h, x, y), _, (uw, uh) = self.placed(2560, 1440, (1260, 820), (1000, 640))
        self.assertGreater(w, 1260)
        self.assertGreater(h, 820)
        self.assertLessEqual(w, uw)
        self.assertLessEqual(abs((2560 - w) // 2 - x), 2)  # centred across

    def test_a_dialog_opens_over_the_window_it_belongs_to(self):
        from LocalExtraction.gui import layout
        self.root.geometry("800x600+300+200")
        self.root.update()
        dialog = tk.Toplevel(self.root)
        layout.place(dialog, (400, 300), parent=self.root)
        dialog.update_idletasks()
        x, y = (int(v) for v in dialog.geometry().split("+")[1:])
        self.assertLessEqual(abs(x - (self.root.winfo_rootx() + 200)), 40)
        self.assertLessEqual(abs(y - (self.root.winfo_rooty() + 150)), 60)


def seen(widget) -> bool:
    """What is drawn at the middle of the widget is the widget (or a part of it): it is in view, not merely mapped."""
    x = widget.winfo_rootx() + widget.winfo_width() // 2
    y = widget.winfo_rooty() + widget.winfo_height() // 2
    found = widget.winfo_containing(x, y)
    return found is not None and str(found).startswith(str(widget))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class StackTests(unittest.TestCase):
    def setUp(self):
        from tkinter import ttk
        from LocalExtraction.gui import layout
        self.root = tk.Tk()
        self.root.geometry("700x500+40+40")
        self.root.attributes("-alpha", 0.0)  # drawn, as in real use, but not seen
        self.addCleanup(self.root.destroy)
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)
        self.stack = layout.Stack(self.frame)
        self.rows = []
        for n in range(4):
            row = ttk.Button(self.stack.host, text=f"row {n}")
            row.pack(fill="x", pady=4)
            self.rows.append(row)
        self.book = ttk.Notebook(self.frame)
        self.book.add(ttk.Frame(self.book, height=300), text="tab")

    def pump(self):
        for _ in range(20):
            self.root.update()

    def test_the_controls_above_and_the_tabs_below_are_drawn(self):
        self.stack.below(self.book)
        self.pump()
        self.assertTrue(all(seen(row) for row in self.rows))  # in view, not hidden behind another widget
        self.assertTrue(seen(self.book))
        ys = [row.winfo_rooty() for row in self.rows]
        self.assertEqual(ys, sorted(ys))
        self.assertLess(ys[-1], self.book.winfo_rooty())
        self.assertGreater(self.book.winfo_height(), 150)

    def test_a_short_window_keeps_room_for_the_tabs_and_the_controls_scroll(self):
        from tkinter import ttk
        for n in range(20):  # far more controls than the window can show
            ttk.Label(self.stack.host, text=f"more {n}").pack(fill="x")
        self.stack.below(self.book)
        self.pump()
        self.assertGreaterEqual(self.book.winfo_height(), int(0.38 * self.stack.split.winfo_height()))
        self.assertTrue(self.stack.upper.scrolls())  # its bar is there, the rest is a scroll away
        self.assertTrue(seen(self.rows[0]))

    def test_a_card_shown_later_goes_above_the_tabs(self):
        from LocalExtraction.gui.result_card import Outcome, ResultCard
        card = ResultCard(self.stack.host)
        self.stack.below(self.book, cards=(card,))
        card.show(Outcome("Done", detail="all went well"), bell=False)
        self.pump()
        self.assertTrue(seen(card))
        self.assertLess(card.winfo_rooty(), self.book.winfo_rooty())



class ScrolledTests(unittest.TestCase):
    @unittest.skipUnless(has_screen(), "the window needs a screen")
    def test_wrapped_text_near_the_edge_settles(self):
        """Text that wraps to the width it has, about as tall as the area: showing the bar made the text narrower and
        taller (the bar stayed), hiding it made the text wider and shorter (the bar went), without end."""
        import os
        import subprocess
        import sys
        script = (
            "import tkinter as tk\n"
            "from LocalExtraction.gui.widgets import Scrolled, WrapLabel\n"
            "root = tk.Tk(); root.attributes('-alpha', 0.0)\n"
            "area = Scrolled(root); area.pack(fill='both', expand=True)\n"
            "for n in range(6):\n"
            "    WrapLabel(area.inner, text=' '.join(['a fairly long sentence that wraps'] * 6)).pack(fill='x')\n"
            "for height in range(60, 400, 3):\n"
            "    root.geometry(f'420x{height}')\n"
            "    for _ in range(20): root.update()\n"
            "print('settled')\n")
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        done = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True, timeout=90)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "settled"), done.stderr[-500:])

    @unittest.skipUnless(has_screen(), "the window needs a screen")
    def test_a_late_resize_while_the_window_closes_is_no_error(self):
        """Closing a window, Tk may still deliver a resize to a scrolling area whose canvas is already gone: it used
        to raise (shown as "Something went wrong" while the window closed)."""
        from LocalExtraction.gui.widgets import Scrolled
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(lambda: root.winfo_exists() and root.destroy())
        area = Scrolled(root)
        area.pack(fill="both", expand=True)
        root.update()
        area.canvas.destroy()
        area._resized()                                       # no TclError
        area._canvas_resized(type("Event", (), {"width": 200})())

    @unittest.skipUnless(has_screen(), "the window needs a screen")
    def test_a_window_sized_by_what_it_holds_settles(self):
        """Without a size of its own, a window takes the size its content asks for. The scroll bar of a short frame
        once asked for height, the window grew, the bar went, the window shrank, and so on: the window never settled
        (and Tk's stack ran out: a crash)."""
        import os
        import subprocess
        import sys
        script = (
            "import tkinter as tk\n"
            "from LocalExtraction.gui.widgets import Scrolled\n"
            "root = tk.Tk(); root.attributes('-alpha', 0.0)\n"
            "for _ in range(3):\n"
            "    s = Scrolled(root); s.pack(fill='both', expand=True)\n"
            "    tk.Label(s.inner, text='x').pack()\n"
            "for _ in range(50): root.update()\n"
            "print('settled')\n")
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        done = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "settled"), done.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
