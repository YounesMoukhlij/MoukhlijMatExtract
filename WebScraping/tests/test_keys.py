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
            self.assertTrue(group.opens and group.fields, group.organization)
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


@unittest.skipUnless(has_screen(), "the window needs a screen")
class StartTests(unittest.TestCase):
    """The question asked each time the Web scraping window opens."""

    def setUp(self):
        import tkinter as tk
        from WebScraping.averageScrap import job
        self.env = os.path.join(tempfile.mkdtemp(), ".env")
        for patcher in (mock.patch.dict(os.environ), mock.patch.object(job, "ENV_PATH", self.env),
                        mock.patch.object(job, "load_env", lambda *a, **k: None)):  # never the real .env
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("MME_EMAIL", None)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def open_window(self):
        from WebScraping import webgui
        from WebScraping.averageScrap.gui.dialogs import StartDialog
        os.chdir(tempfile.mkdtemp())  # the window's folders are made here (conftest gives the folder back)
        window = webgui.open_web(self.root)
        window.attributes("-alpha", 0.0)
        self.root.update_idletasks()
        question, = [child for child in window.winfo_children() if isinstance(child, StartDialog)]
        question.attributes("-alpha", 0.0)
        self.addCleanup(lambda: window.winfo_exists() and window.destroy())
        return window, question

    def pump(self, seconds):
        import time
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def test_the_window_waits_for_an_email_which_is_then_saved(self):
        window, question = self.open_window()
        self.pump(0.3)
        self.assertEqual(str(question.grab_current()), str(question))  # the window behind it waits
        with mock.patch("WebScraping.averageScrap.gui.dialogs.messagebox.showerror") as error:
            question._continue()  # no e-mail yet
            question.email.set("not an address")
            question._continue()
        self.assertEqual(error.call_count, 2)
        self.assertTrue(question.winfo_exists())
        question.email.set(" me@uni.edu ")
        question._continue()
        self.assertFalse(question.winfo_exists())
        self.assertTrue(window.winfo_exists())  # the Web scraping window, ready
        self.assertEqual((read_env(self.env)["MME_EMAIL"], os.environ["MME_EMAIL"]), ("me@uni.edu", "me@uni.edu"))

    def test_the_keys_opened_from_the_question_answer_the_mouse_and_save(self):
        """The question holds the mouse (the window behind it waits). "API keys…" opened from it must take
        the mouse while it is open — else its Save button, its boxes and its scrolling do not answer — and
        give it back to the question when it closes."""
        from tkinter import ttk
        from WebScraping.averageScrap.gui.dialogs import SettingsDialog
        window, question = self.open_window()
        self.pump(0.3)
        question._keys()
        self.pump(0.5)
        keys, = [child for child in question.winfo_children() if isinstance(child, SettingsDialog)]
        keys.attributes("-alpha", 0.0)
        self.assertEqual(str(keys.grab_current()), str(keys))
        cards = keys.body.winfo_children()[2]  # the wheel over a card scrolls the cards
        card = cards.inner.winfo_children()[3]
        # Which widget is under a point of the screen is the window system's answer, and a machine without a
        # screen (continuous integration) has none: it is given here, so that what is tested is how the cards
        # take it — a point over one of their cards is inside them, one over another window is not.
        with mock.patch.object(cards, "winfo_containing", return_value=card):
            self.assertTrue(cards._inside(card.winfo_rootx() + 20, card.winfo_rooty() + 10))
        with mock.patch.object(cards, "winfo_containing", return_value=question):
            self.assertFalse(cards._inside(0, 0))
        keys._vars["CORE_API_KEY"].set("core-456")
        save, = [b for b in keys.body.winfo_children()[-1].winfo_children()
                 if isinstance(b, ttk.Button) and b.cget("text") == "Save"]
        save.invoke()
        self.pump(0.3)
        self.assertFalse(keys.winfo_exists())
        self.assertEqual(read_env(self.env)["CORE_API_KEY"], "core-456")
        self.assertEqual(str(question.grab_current()), str(question))  # the question has the mouse again

    def test_it_is_asked_every_time_from_the_saved_email_and_closing_it_closes_the_window(self):
        with open(self.env, "w", encoding="utf-8") as f:
            f.write("MME_EMAIL=saved@uni.edu\n")
        window, question = self.open_window()
        self.assertEqual(question.email.get(), "saved@uni.edu")
        question._cancel()
        self.pump(0.4)  # the window closes itself (its step stopped, its log let go)
        self.assertFalse(window.winfo_exists())


if __name__ == "__main__":
    unittest.main()


class KeysFileTests(unittest.TestCase):
    """The keys live in the main folder (~/MoukhlijMatExtract/.env), where an upgrade of the package never reaches:
    inside the installed package, `pip install --upgrade` deleted them."""

    def setUp(self):
        from WebScraping.averageScrap import job
        self.job = job
        self.default = job.ENV_PATH  # where the keys go, before this test points it elsewhere
        base = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, base, True)
        self.home = os.path.join(base, "MoukhlijMatExtract")
        self.new = os.path.join(self.home, ".env")
        self.old = os.path.join(base, "package", ".env")
        os.makedirs(os.path.dirname(self.old))
        for patcher in (mock.patch.dict(os.environ), mock.patch.object(job, "ENV_PATH", self.new),
                        mock.patch.object(job, "OLD_ENV_PATH", self.old)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("MP_API_KEY", None)

    def test_the_keys_file_is_in_the_main_folder(self):
        from LocalExtraction.about import PROJECT_HOME
        self.assertEqual(self.default, str(PROJECT_HOME / ".env"))

    def test_keys_saved_before_are_carried_over_once_and_kept_private(self):
        with open(self.old, "w", encoding="utf-8") as f:
            f.write("MP_API_KEY=old-key\n")
        os.makedirs(self.home)
        self.assertEqual(self.job.load_env(), 1)
        self.assertEqual(os.environ["MP_API_KEY"], "old-key")
        self.assertEqual(self.job.read_env(), {"MP_API_KEY": "old-key"})
        self.assertTrue(os.path.isfile(self.new))
        if os.name == "posix":
            self.assertEqual(os.stat(self.new).st_mode & 0o777, 0o600)  # yours alone
        self.assertTrue(os.path.isfile(self.old))  # the old file left as it was

    def test_without_the_main_folder_the_old_keys_are_read_and_no_folder_is_made(self):
        with open(self.old, "w", encoding="utf-8") as f:
            f.write("MP_API_KEY=old-key\n")
        self.assertEqual(self.job.read_env(), {"MP_API_KEY": "old-key"})
        self.job.load_env()
        self.assertEqual(os.environ["MP_API_KEY"], "old-key")
        self.assertFalse(os.path.exists(self.home))

    def test_saving_makes_the_main_folder_when_it_is_missing(self):
        self.job.save_env({"MP_API_KEY": "new-key"})
        self.assertEqual(self.job.read_env(), {"MP_API_KEY": "new-key"})
        self.assertTrue(os.path.isfile(self.new))
        self.assertFalse(os.path.exists(self.old))  # nothing written where an upgrade deletes it
