# mme_gui/tests/test_manual.py
"""The hub's Manual: every command is listed with its python -m form and make shortcut, the options come
from each command's own --help, the make shortcuts from the Makefile, and asking a command for its
--help creates no folder. The window tests need a screen; without one they are skipped."""

import io
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen
from mme_gui import manual

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except ImportError:  # a Python built without Tk: the windows cannot be opened
    _HAS_TK = False


class ContentTests(unittest.TestCase):
    def test_every_installed_command_is_in_the_manual(self):
        import tomllib
        project = tomllib.loads((manual.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        listed = {command.name.split()[0] for command in manual.COMMANDS}
        self.assertEqual(set(project["project"]["scripts"]), listed)

    def test_every_make_shortcut_named_exists_in_the_makefile(self):
        makefile = (manual.ROOT / "Makefile").read_text(encoding="utf-8")
        for command in manual.COMMANDS:
            target = command.make.split()[1]
            self.assertRegex(makefile, rf"(?m)^{target}:", command.name)

    def test_the_overview_has_one_row_per_command(self):
        lines = manual.overview()
        self.assertEqual(len(lines), len(manual.COMMANDS) + 2)  # the header and its rule
        self.assertTrue(all("python -m" in line for line in lines[2:]))

    def test_the_make_shortcuts_are_read_from_the_makefile(self):
        lines = manual.make_lines()
        self.assertTrue(any(line.strip().startswith("make web-dois") for line in lines))
        self.assertFalse(any("$(" in line for line in lines))
        self.assertEqual(manual.make_lines(Path(tempfile.mkdtemp())), [])  # no Makefile: none

    def test_the_options_come_from_the_command_itself(self):
        command = manual.COMMANDS[0]  # mme-gui: the quickest to start
        with mock.patch.dict(manual._HELP, clear=True):
            ok, text = manual.help_text(command)
        self.assertTrue(ok, text)
        self.assertIn("--version", text)

    def test_each_help_names_the_command_a_user_types(self):
        # The manual reads each help with `python -m`; it still shows "usage: mme-rank …", not "python -m …".
        command = next(c for c in manual.COMMANDS if c.name == "mme-rank")
        with mock.patch.dict(manual._HELP, clear=True):
            ok, text = manual.help_text(command)
        self.assertTrue(ok, text)
        self.assertTrue(text.startswith("usage: mme-rank"), text[:80])

    def test_every_command_tells_its_version(self):
        from LocalExtraction.about import version_text
        self.assertTrue(version_text("mme-local").startswith("MoukhlijMatExtract "))

    def test_a_command_that_fails_says_why(self):
        broken = manual.Command("mme-none", "no_such_module_here", (), "", "", "")
        ok, text = manual.help_text(broken)
        self.assertFalse(ok)
        self.assertIn("code", text)


class HelpMakesNoFolderTests(unittest.TestCase):
    """--help only prints: the main results folder is not made by asking a command for its options."""

    def setUp(self):
        from LocalExtraction import about
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        self.home = base / "MoukhlijMatExtract"
        patch = mock.patch.object(about, "PROJECT_HOME", self.home)
        patch.start()
        self.addCleanup(patch.stop)

    def _help(self, main, argv):
        with redirect_stdout(io.StringIO()) as printed, self.assertRaises(SystemExit):
            main(argv)
        self.assertIn("usage:", printed.getvalue())
        self.assertFalse(self.home.exists(), argv)

    def test_ranking(self):
        from SelectingTopMaterial.cli import main
        self._help(main, ["--help"])
        if _HAS_TK:  # the window's own options are read by the window, which needs Tk
            self._help(main, ["gui", "--help"])

    def test_classification(self):
        from Classification.cli import main
        self._help(main, ["--help"])
        if _HAS_TK:
            self._help(main, ["gui", "--help"])

    def test_fetch_dois(self):
        from WebScraping.Fetch_DOIs.get_dois import main
        self._help(main, ["--help"])


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def _wait(self, window, seconds=10):
        end = time.time() + seconds
        while window.manual_pending and time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def test_the_hub_has_a_manual_button_beside_requirements(self):
        from mme_gui import hub
        with mock.patch.object(hub, "_MARKER", Path(tempfile.mkdtemp()) / "seen"), \
             mock.patch.object(manual, "help_text", lambda command: (True, f"usage: {command.name}")):
            requirements = hub.build(self.root)
            self.root.update()
            button = self.root._mme_manual
            self.assertIn("Manual", button.cget("text"))
            self.assertEqual(button.master, requirements.master)
            window = button.open()
            self._wait(window)
            window.destroy()

    def test_the_window_fills_each_command_as_its_options_come(self):
        import threading
        go = threading.Event()

        def fake(command):
            go.wait(10)
            if command.name == "mme-rank":
                return False, "It ended with code 1."
            return True, f"usage: {command.name} [--an-option]"

        with mock.patch.object(manual, "help_text", fake):
            window = manual.open_manual(self.root)
            self.root.update()
            self.assertEqual(len(window.manual_pending), len(manual.COMMANDS))  # the window does not wait
            self.assertIn("Reading its options", window.manual_text.get("1.0", "end"))
            go.set()
            self._wait(window)
        self.assertFalse(window.manual_pending)
        shown = window.manual_text.get("1.0", "end")
        self.assertNotIn("Reading its options", shown)
        self.assertIn("usage: mme-web gui [--an-option]", shown)
        self.assertIn("In a terminal: mme-rank --help", shown)  # a failure says what to type instead
        self.assertIn("make shortcuts", shown)
        window.destroy()

    def test_find_lights_every_match(self):
        with mock.patch.object(manual, "help_text", lambda command: (True, "usage: --findme")):
            window = manual.open_manual(self.root)
            self._wait(window)
        entry = next(w for w in window.winfo_children()[0].winfo_children() if w.winfo_class() == "TEntry")
        entry.insert(0, "--FINDME")
        self.root.update()
        self.assertEqual(len(window.manual_text.tag_ranges("found")) // 2, len(manual.COMMANDS))
        window.destroy()


if __name__ == "__main__":
    unittest.main()
