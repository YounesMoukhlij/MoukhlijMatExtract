# WebScraping/tests/test_keys.py
"""The API keys of the web project, offline: every key the programs read has its card in the window,
under the organization that issues it, and the window saves what is typed into the .env file.

The window test needs a screen; without one it is skipped. Nothing touches the real .env: the
window is given a temporary one."""

import os
import tempfile
import unittest
from unittest import mock

from LocalExtraction.tests.test_gui import has_screen
from WebScraping.averageScrap.job import ENV_SETTINGS, KEY_GROUPS, read_env


class GroupTests(unittest.TestCase):
    def test_every_key_is_in_exactly_one_organization(self):
        grouped = [name for group in KEY_GROUPS for name, _ in group.fields]
        self.assertEqual(sorted(grouped), sorted(name for name, _, _ in ENV_SETTINGS))
        self.assertEqual(len(grouped), len(set(grouped)))

    def test_each_organization_says_what_it_opens_who_uses_it_and_where_a_key_is_had(self):
        names = [group.organization for group in KEY_GROUPS]
        self.assertEqual(len(names), len(set(names)))
        for group in KEY_GROUPS:
            self.assertTrue(group.opens and group.used_by and group.fields, group.organization)
            if group.fields[0][0] != "MME_EMAIL":  # an e-mail is your own: nothing to sign up for
                self.assertTrue(group.signup.startswith("https://"), group.organization)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.env = os.path.join(tempfile.mkdtemp(), ".env")
        with open(self.env, "w", encoding="utf-8") as f:
            f.write("# keys of a test\nMME_EMAIL=me@uni.edu\nCORE_API_KEY=core-123\n")
        # The window falls back on the environment for a key the file lacks: make sure none is set,
        # and give back whatever was there afterwards (saving also sets the environment).
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, _, _ in ENV_SETTINGS:
            os.environ.pop(name, None)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def dialog(self):
        from WebScraping.averageScrap.gui.dialogs import SettingsDialog
        window = SettingsDialog(self.root, path=self.env)
        window.attributes("-alpha", 0.0)
        self.root.update_idletasks()
        return window

    def test_one_card_per_organization_showing_what_is_set(self):
        window = self.dialog()
        self.assertEqual(list(window.status), [group.organization for group in KEY_GROUPS])
        self.assertEqual(window.status["Your contact e-mail"].get(), "✓ set")
        self.assertEqual(window.status["CORE"].get(), "✓ set")
        self.assertEqual(window.status["Elsevier"].get(), "not set")
        window._vars["ELSEVIER_API_KEY"].set("els-456")  # typing a key sets its card at once
        self.assertEqual(window.status["Elsevier"].get(), "✓ set")

    def test_saving_writes_the_keys_into_the_env_file(self):
        window = self.dialog()
        window._vars["ELSEVIER_API_KEY"].set("  els-456 ")
        window._vars["CORE_API_KEY"].set("")  # emptied: removed
        window._save()
        saved = read_env(self.env)
        self.assertEqual(saved["ELSEVIER_API_KEY"], "els-456")
        self.assertEqual(saved["MME_EMAIL"], "me@uni.edu")
        self.assertEqual(saved.get("CORE_API_KEY", ""), "")

    def test_an_address_that_is_not_an_email_is_not_saved(self):
        window = self.dialog()
        window._vars["MME_EMAIL"].set("not an address")
        with mock.patch("WebScraping.averageScrap.gui.dialogs.messagebox.showerror") as error:
            window._save()
        error.assert_called_once()
        self.assertEqual(read_env(self.env)["MME_EMAIL"], "me@uni.edu")  # the file is unchanged


if __name__ == "__main__":
    unittest.main()
