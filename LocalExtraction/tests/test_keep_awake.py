# LocalExtraction/tests/test_keep_awake.py
"""“Keep the computer awake”: one switch for the whole program — the platform's own way to prevent sleep while it
is on, nothing once it is off — and every window's switch showing the same state."""

import os
import unittest
from unittest import mock

from LocalExtraction import keep_awake
from LocalExtraction.tests.test_gui import has_screen, tk


class SwitchTests(unittest.TestCase):
    def test_macos_runs_caffeinate_tied_to_this_program_and_stops_it(self):
        awake = keep_awake.KeepAwake(platform="darwin")
        process = mock.Mock()
        with mock.patch.object(keep_awake.shutil, "which", return_value="/usr/bin/caffeinate"), \
                mock.patch.object(keep_awake.subprocess, "Popen", return_value=process) as popen:
            self.assertTrue(awake.set(True))
            self.assertTrue(awake.set(True))  # on already: no second process
            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertEqual(command, ["/usr/bin/caffeinate", "-dims", "-w", str(os.getpid())])
            self.assertFalse(awake.set(False))
        process.terminate.assert_called_once()
        self.assertFalse(awake.on)

    def test_linux_holds_a_systemd_inhibit_lock(self):
        awake = keep_awake.KeepAwake(platform="linux")
        with mock.patch.object(keep_awake.shutil, "which", return_value="/usr/bin/systemd-inhibit"), \
                mock.patch.object(keep_awake.subprocess, "Popen") as popen:
            self.assertTrue(awake.set(True))
        self.assertIn("--what=idle:sleep", popen.call_args.args[0])
        awake.set(False)

    def test_without_a_way_it_stays_off_and_says_so(self):
        awake = keep_awake.KeepAwake(platform="linux")
        with mock.patch.object(keep_awake.shutil, "which", return_value=None):
            self.assertFalse(awake.supported())
            self.assertFalse(awake.set(True))
        self.assertFalse(awake.on)

    def test_every_listener_is_told(self):
        awake = keep_awake.KeepAwake(platform="darwin")
        heard = []
        forget = awake.listen(heard.append)
        with mock.patch.object(keep_awake.shutil, "which", return_value="/usr/bin/caffeinate"), \
                mock.patch.object(keep_awake.subprocess, "Popen"):
            awake.set(True)
            awake.set(False)
            forget()
            awake.set(True)
        self.assertEqual(heard, [True, False])
        awake.set(False)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.awake = keep_awake.KeepAwake(platform="darwin")
        patch = mock.patch.object(keep_awake, "AWAKE", self.awake)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: self.awake.set(False))

    def test_the_footer_of_every_window_has_the_switch_and_all_follow_one_click(self):
        from LocalExtraction.gui import design
        first = design.footer(self.root)
        second = design.footer(tk.Toplevel(self.root))
        switches = [w for bar in (first, second) for w in _descendants(bar) if hasattr(w, "var")]
        self.assertEqual(len(switches), 2)
        self.assertEqual(switches[0].cget("text"), design.KEEP_AWAKE_TEXT)
        with mock.patch.object(keep_awake.shutil, "which", return_value="/usr/bin/caffeinate"), \
                mock.patch.object(keep_awake.subprocess, "Popen"):
            switches[0].invoke()
            self.assertTrue(self.awake.on)
            self.assertTrue(switches[1].var.get())  # the other window follows
            switches[1].invoke()
        self.assertFalse(self.awake.on)
        self.assertFalse(switches[0].var.get())

    def test_the_main_window_has_it_too(self):
        from LocalExtraction.gui import design
        from mme_gui import hub
        hub.build(self.root)
        texts = [w.cget("text") for w in _descendants(self.root) if hasattr(w, "var")]
        self.assertIn(design.KEEP_AWAKE_TEXT, texts)


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


if __name__ == "__main__":
    unittest.main()
