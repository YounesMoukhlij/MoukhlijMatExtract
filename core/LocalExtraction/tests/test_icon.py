# LocalExtraction/tests/test_icon.py
"""The program's icon: in the Dock (macOS), the taskbar (Windows) and the title bar (Linux) of every window, in place
of Tk's blank one. It ships inside the package."""

import tomllib
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction.gui import design
from LocalExtraction.tests.test_gui import has_screen, tk

ROOT = Path(__file__).resolve().parents[3]  # the repository


class IconFileTests(unittest.TestCase):
    def test_the_icon_is_a_large_square_png_inside_the_package(self):
        self.assertTrue(design.ICON.is_file(), design.ICON)
        self.assertTrue(str(design.ICON).startswith(str(ROOT / "core" / "LocalExtraction")))
        with open(design.ICON, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        self.assertEqual((width, height), (512, 512))  # sharp in the Dock on a Retina screen

    def test_the_package_ships_it(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]
        self.assertIn("gui/assets/*.png", data.get("LocalExtraction", []))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowIconTests(unittest.TestCase):
    def test_a_window_of_the_program_wears_the_icon(self):
        from LocalExtraction.gui import theme
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        with mock.patch.object(tk.Tk, "iconphoto", autospec=True) as set_icon:
            theme.apply(root)
        (window, default, *images), _ = set_icon.call_args
        self.assertIs(window, root)
        self.assertTrue(default)  # every window of this program, and the Dock
        self.assertEqual(images[0].width(), 512)
        self.assertIs(root._mme_icon[0], images[0])  # kept: an image Python lets go of disappears from the Dock

    def test_without_its_file_a_window_still_opens(self):
        from LocalExtraction.gui import theme
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        self.addCleanup(root.destroy)
        with mock.patch.object(design, "ICON", Path("/nowhere/mme.png")):
            theme.apply(root)  # no error: the window opens with Tk's own icon


if __name__ == "__main__":
    unittest.main()
