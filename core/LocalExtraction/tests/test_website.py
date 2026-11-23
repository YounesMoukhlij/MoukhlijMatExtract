# LocalExtraction/tests/test_website.py
"""The project's website: its address is at the bottom of every window (the footer of the parts, a line under the
smaller windows), a click opens it, and the main window announces it for 7 seconds when it opens (or until its ✕)."""

import time
import unittest
from unittest import mock

from LocalExtraction import about
from LocalExtraction.gui import design
from LocalExtraction.tests.test_gui import has_screen, tk


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _click(widget) -> None:
    """A click on a widget drawn on screen (Tk sends no mouse event to a widget not drawn yet)."""
    widget.update()
    widget.event_generate("<Button-1>", x=2, y=2)
    widget.update()


def _website_links(widget):
    return [w for w in _descendants(widget) if getattr(w, "website", False)]


class AddressTests(unittest.TestCase):
    def test_the_address_is_one_https_link_shown_without_its_scheme(self):
        self.assertTrue(about.WEBSITE.startswith("https://"))
        self.assertEqual(design.website_address(), about.WEBSITE[len("https://"):].rstrip("/"))

    def test_opening_it_opens_the_browser_on_the_website(self):
        with mock.patch("webbrowser.open") as browser:
            design.open_website()
        browser.assert_called_once_with(about.WEBSITE)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def test_the_footer_of_the_parts_shows_the_website_and_a_click_opens_it(self):
        design.footer(self.root, about=lambda: None).pack(side="bottom", fill="x")
        links = _website_links(self.root)
        self.assertEqual(len(links), 1)
        self.assertIn(design.website_address(), links[0].cget("text"))
        with mock.patch("webbrowser.open") as browser:
            _click(links[0])
        browser.assert_called_once_with(about.WEBSITE)

    def test_every_dialog_ends_with_the_website_line(self):
        from LocalExtraction.gui.dialogs import Dialog
        dialog = Dialog(self.root, "A dialog", "400x300")
        self.root.update_idletasks()
        self.assertEqual(len(_website_links(dialog)), 1)
        # The line is packed first, at the bottom: however small the dialog, the body never pushes it out.
        line = dialog.pack_slaves()[0]
        self.assertEqual(line.pack_info()["side"], "bottom")
        self.assertIn(dialog.body, dialog.pack_slaves())

    def test_a_window_laid_out_with_grid_is_left_as_it_is(self):
        window = tk.Toplevel(self.root)
        tk.Label(window, text="gridded").grid(row=0, column=0)
        design.website_line(window)  # must not raise (Tk mixes no pack with grid)
        self.assertEqual(_website_links(window), [])

    def test_the_guides_and_tables_show_it(self):
        from LocalExtraction.gui.about_window import open_about
        from mme_gui import hub
        from mme_gui import manual
        with mock.patch.object(manual, "help_text", lambda command: (True, "usage: …")):
            windows = (open_about(self.root), hub.open_requirements(self.root), manual.open_manual(self.root))
        for window in windows:
            self.root.update_idletasks()
            self.assertEqual(len(_website_links(window)), 1, window.title())
            window.destroy()


@unittest.skipUnless(has_screen(), "the window needs a screen")
class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        from mme_gui import hub
        self.hub = hub
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        hub.build(self.root)

    def wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)

    def test_it_lasts_seven_seconds_by_default(self):
        self.assertEqual(self.hub.ANNOUNCEMENT_SECONDS, 7)

    def test_it_tells_of_the_website_with_its_link_over_the_main_window(self):
        card = self.hub.announce_website(self.root)
        self.addCleanup(card.close)
        self.root.update_idletasks()
        self.assertEqual(card.winfo_manager(), "place")  # inside the window, over its top: not a window of its own
        texts = " ".join(w.cget("text") for w in _descendants(card) if isinstance(w, tk.Label))
        self.assertIn("website", texts.lower())
        self.assertIn("how to use", texts.lower())
        self.assertIn("overview", texts.lower())
        self.assertEqual(len(_website_links(card)), 1)
        self.assertEqual(card.cross.cget("text"), "✕")

    def test_it_closes_by_itself(self):
        card = self.hub.announce_website(self.root, seconds=1)
        self.root.update()
        self.assertTrue(card.winfo_exists())
        self.wait(1.6)
        self.assertFalse(card.winfo_exists())

    def test_its_bar_shrinks_and_its_countdown_says_the_seconds_left(self):
        card = self.hub.announce_website(self.root, seconds=3)
        self.addCleanup(card.close)
        self.wait(0.3)
        self.assertIn("Closes in 3 s", card.note.cget("text"))
        width = card.bar.winfo_width()
        first = card.bar.coords(card.bar.find_all()[0])[2]
        self.wait(1.2)
        self.assertIn("Closes in 2 s", card.note.cget("text"))
        later = card.bar.coords(card.bar.find_all()[0])[2]
        self.assertLess(later, first)  # it shrank
        self.assertAlmostEqual(later / width, 1.5 / 3, delta=0.15)  # in step with the time left

    def test_the_pointer_on_it_holds_the_countdown(self):
        card = self.hub.announce_website(self.root, seconds=1)
        self.addCleanup(card.close)
        self.root.update()
        card.event_generate("<Enter>")
        self.wait(1.4)
        self.assertTrue(card.winfo_exists())  # held: still there after its second
        self.assertIn("Held while the pointer is here", card.note.cget("text"))
        with mock.patch.object(self.hub, "_pointer_inside", return_value=False):
            card.event_generate("<Leave>")
            self.wait(1.5)
        self.assertFalse(card.winfo_exists())  # let go: it goes on and closes

    def test_its_cross_closes_it_at_once_and_the_timer_does_nothing_after(self):
        card = self.hub.announce_website(self.root, seconds=0.5)
        _click(card.cross)
        self.assertFalse(card.winfo_exists())
        self.wait(0.8)  # the timer was cancelled: nothing left to close, nothing raised

    def test_the_main_window_shows_it_when_it_opens(self):
        with mock.patch.object(self.hub, "build"), mock.patch.object(self.hub, "warm_up"), \
                mock.patch.object(self.hub, "announce_website") as announce, \
                mock.patch("LocalExtraction.crashlog.run") as run, mock.patch("LocalExtraction.crashlog.install"), \
                mock.patch("LocalExtraction.crashlog.watch"), mock.patch("tkinter.Tk", return_value=self.root), \
                mock.patch.object(self.hub.os, "chdir"), mock.patch.object(self.hub, "warn_if_missing"):
            run.side_effect = lambda root: self.wait(0.5)
            self.hub.main([])
        announce.assert_called_once_with(self.root)

    def test_the_main_window_footer_links_the_website(self):
        links = [w for w in _descendants(self.root)
                 if isinstance(w, tk.Label) and design.website_address() in str(w.cget("text"))]
        self.assertTrue(links)


if __name__ == "__main__":
    unittest.main()
