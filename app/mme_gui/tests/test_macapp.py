# mme_gui/tests/test_macapp.py
"""MoukhlijMatExtract.app (macOS): the main window with the program's own name and icon in the Dock."""

import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mme_gui import hub, macapp


class LauncherTests(unittest.TestCase):
    def test_the_launcher_runs_this_python_through_the_bundle_with_this_environment(self):
        text = macapp.launcher("/x/python3.13", ["/env/site-packages"])
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn('exec "$HERE/python"', text)  # the link inside the bundle: macOS takes it for the app
        self.assertIn("site.addsitedir(d)", text)
        self.assertIn("'/env/site-packages'", text)
        self.assertIn("run_module('mme_gui'", text)
        self.assertIn("/opt/homebrew/bin", text)  # Tesseract found when opened from the Dock

    def test_the_bundle_says_its_name(self):
        info = macapp.info("1.1.0")
        self.assertEqual((info["CFBundleName"], info["CFBundleExecutable"]), ("MoukhlijMatExtract", "MoukhlijMatExtract"))
        self.assertEqual(info["CFBundlePackageType"], "APPL")

    def test_install_app_makes_it_and_opens_no_window(self):
        with mock.patch.object(macapp, "build", return_value=Path("/Apps/MoukhlijMatExtract.app")) as made, \
                mock.patch("builtins.print") as said, mock.patch.object(hub, "require_tk", create=True):
            hub.main(["--install-app"])
        made.assert_called_once()
        self.assertIn("MoukhlijMatExtract.app", said.call_args.args[0])

    def test_the_main_window_still_starts_without_the_option(self):
        """A bug once: the option's import hid the window's own build(), and every start failed."""
        with mock.patch.object(hub, "build") as built, mock.patch.object(hub, "warm_up"), \
                mock.patch("tkinter.Tk"), mock.patch("LocalExtraction.crashlog.run"), \
                mock.patch("LocalExtraction.crashlog.install"), mock.patch("LocalExtraction.crashlog.watch"), \
                mock.patch.object(hub.os, "chdir"):
            hub.main([])
        built.assert_called_once()


@unittest.skipUnless(sys.platform == "darwin", "a Mac app")
class BuildTests(unittest.TestCase):
    def test_the_app_bundle(self):
        dest = Path(tempfile.mkdtemp()) / "MoukhlijMatExtract.app"
        macapp.build(dest, register=False)
        contents = dest / "Contents"
        with open(contents / "Info.plist", "rb") as f:
            self.assertEqual(plistlib.load(f)["CFBundleName"], "MoukhlijMatExtract")
        self.assertTrue((contents / "MacOS" / "MoukhlijMatExtract").stat().st_mode & 0o111)
        self.assertTrue((contents / "MacOS" / "python").is_symlink())
        self.assertTrue((contents / "Resources" / "MoukhlijMatExtract.icns").is_file())
        run = subprocess.run(["sh", "-n", str(contents / "MacOS" / "MoukhlijMatExtract")], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)  # the launcher is valid shell


if __name__ == "__main__":
    unittest.main()
