# mme_gui/tests/test_make_guide.py
"""The “Make commands” window: every target of the Makefile explained and drawn in the flow (so the window never
falls behind the Makefile), the arrows joining known steps, every box and chip inside its lane, a click explaining
its command, the search of the list, and the button of the main window.

The window tests need a screen; without one they are skipped."""

import re
import unittest
from collections import Counter

from LocalExtraction.tests.test_gui import has_screen
from mme_gui import make_guide as guide
from mme_gui.manual import ROOT


def makefile_targets() -> set:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    phony = re.search(r"(?m)^\.PHONY:((?:.*\\\n)*.*)$", text).group(1)
    return set(phony.replace("\\", " ").split())


class ContentTests(unittest.TestCase):
    def test_every_make_target_is_explained(self):
        explained = set(guide.BY_TARGET)
        self.assertEqual(makefile_targets() - explained, set(), "explain these in mme_gui/make_guide.py")
        self.assertEqual(explained - makefile_targets(), set(), "no longer in the Makefile")

    def test_every_command_says_what_and_why(self):
        for command in guide.COMMANDS:
            with self.subTest(target=command.target):
                self.assertTrue(command.what.strip() and command.why.strip())
                self.assertIn(command.stage, guide.STAGE)
                self.assertTrue(command.command.startswith(f"make {command.target}"))

    def test_every_command_is_in_the_flow_once(self):
        shown = guide.in_diagram()
        self.assertEqual([t for t, n in Counter(shown).items() if n > 1], [])
        self.assertEqual(set(shown), set(guide.BY_TARGET))

    def test_the_arrows_join_known_steps(self):
        steps = set(guide.NODES) | set(guide.PLACES)
        for a, b in guide.EDGES:
            self.assertIn(a, steps)
            self.assertIn(b, steps)
        # the flow reaches its two ends: the deposit and the article
        self.assertIn(("release", "zenodo"), guide.EDGES)
        self.assertIn(("paper", "article"), guide.EDGES)


@unittest.skipUnless(has_screen(), "needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.win = guide.open_make_guide(self.root)
        self.win.attributes("-alpha", 0.0)
        self.root.update_idletasks()

    def test_every_box_and_chip_is_drawn_inside_its_lane(self):
        canvas = self.win.diagram.canvas
        lanes = list(guide.LANES) + [("care", guide.CARE_TOP, guide.HEIGHT - 14)]
        for target in guide.in_diagram():
            with self.subTest(target=target):
                x1, y1, x2, y2 = canvas.bbox(f"t:{target}")
                self.assertTrue(any(top <= y1 and y2 <= bottom for _, top, bottom in lanes), (y1, y2))
                self.assertLessEqual(x2, guide.WIDTH - 12)
        self.assertIn("make web", self.win.diagram.texts)

    def test_a_click_explains_the_command(self):
        canvas = self.win.diagram.canvas
        self.win.diagram.choose("eval-benchmark", tell=True)  # as a click on the box does
        self.root.update_idletasks()
        self.assertEqual(self.win.chosen, "eval-benchmark")
        self.assertEqual(int(float(canvas.itemcget(self.win.diagram.items["eval-benchmark"], "width"))), 3)
        self.win.show("web-dois")
        self.assertEqual(self.win.chosen, "web-dois")
        self.assertEqual(int(float(canvas.itemcget(self.win.diagram.items["eval-benchmark"], "width"))), 1)

    def test_the_list_holds_every_command_and_the_search_narrows_it(self):
        listing = self.win.listing.get("1.0", "end")
        for command in guide.COMMANDS:
            self.assertIn(f"make {command.target}\n", listing)
        self.win.search.set("zenodo")
        found = self.win.listing.get("1.0", "end")
        self.assertIn("make release", found)
        self.assertIn("make eval-gold", found)
        self.assertNotIn("make rank\n", found)

    def test_the_main_window_has_the_button(self):
        import tkinter as tk
        from mme_gui import hub
        holder = tk.Toplevel(self.root)
        holder.attributes("-alpha", 0.0)
        hub.build(holder)
        self.assertIn("Make commands", holder._mme_make.cget("text"))
        window = holder._mme_make.open()
        self.assertEqual(window.title(), "MoukhlijMatExtract · Make commands")


if __name__ == "__main__":
    unittest.main()
