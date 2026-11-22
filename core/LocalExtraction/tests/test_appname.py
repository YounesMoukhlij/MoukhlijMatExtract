# LocalExtraction/tests/test_appname.py
"""The program's own name on macOS — the Dock, the app switcher, the menu bar — in place of “python”."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from LocalExtraction.gui import appname
from LocalExtraction.tests.test_gui import has_screen

ROOT = Path(__file__).resolve().parents[2]  # core/: its packages import from here


class NameTests(unittest.TestCase):
    def test_nothing_is_done_outside_macos(self):
        self.assertFalse(appname.set_app_name(platform="linux"))
        self.assertFalse(appname.set_app_name(platform="win32"))

    @unittest.skipUnless(sys.platform == "darwin" and has_screen(), "the Dock of macOS")
    def test_macos_shows_the_program_by_its_name(self):
        script = ("import os, subprocess, tkinter as tk\n"
                  "from LocalExtraction.about import require_tk\n"
                  "require_tk('test')\n"
                  "root = tk.Tk(); root.withdraw()\n"
                  "from LocalExtraction.gui import theme\n"
                  "theme.apply(root); root.update()\n"
                  "print(subprocess.run(['lsappinfo', 'info', '-only', 'name', str(os.getpid())],"
                  " capture_output=True, text=True).stdout)\n"
                  "root.destroy()\n")
        run = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertIn('"MoukhlijMatExtract"', run.stdout, run.stderr)


if __name__ == "__main__":
    unittest.main()
