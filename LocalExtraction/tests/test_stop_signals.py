# LocalExtraction/tests/test_stop_signals.py
"""Stopping from the terminal: every stop signal (Ctrl-C, kill, the terminal closed) says in a box to wait while the
work is saved, the run finishes cleanly and says so; a second signal quits at once."""

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction import runcontrol

ROOT = Path(__file__).resolve().parents[2]


class BoxTests(unittest.TestCase):
    def test_the_boxes_say_what_to_expect(self):
        wait = runcontrol.stop_box("wait", "Ctrl-C", "Web scraping")
        for words in ("Stop requested — Ctrl-C", "Please wait: Web scraping is saving its work and finishing peacefully",
                      "Press Ctrl-C again only to quit at once"):
            self.assertIn(words, wait)
        self.assertIn("Stopped cleanly", runcontrol.stop_box("done"))
        self.assertIn("Quitting at once", runcontrol.stop_box("quit"))

    def test_every_line_of_a_box_has_the_same_width_on_screen(self):
        lines = runcontrol.stop_box("wait", "Ctrl-C").strip("\n").splitlines()
        self.assertEqual(len({runcontrol._columns(line) for line in lines}), 1, lines)

    def test_every_way_a_terminal_stops_a_program_is_caught(self):
        names = {signal.Signals(s).name for s in runcontrol.stop_signals()}
        self.assertTrue({"SIGINT", "SIGTERM"} <= names)
        if os.name == "posix":
            self.assertIn("SIGHUP", names)
        self.assertEqual(runcontrol.signal_words(signal.SIGINT), "Ctrl-C")


@unittest.skipUnless(os.name == "posix", "signals sent to this process: POSIX")
class SignalTests(unittest.TestCase):
    def boxes(self):
        said = []
        return said, mock.patch.object(runcontrol, "say_box", side_effect=lambda kind, *a, **k: said.append(kind))

    def test_a_long_step_stops_at_the_first_signal_and_says_when_it_is_saved(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            said, patch = self.boxes()
            with patch:
                with runcontrol.ctrl_c_stops("Test") as control:
                    os.kill(os.getpid(), sig)
                    self.assertTrue(control.is_set(), sig)  # the step sees Stop, as in the window
                self.assertEqual(said, ["wait", "done"], sig)

    def test_a_second_signal_quits_at_once(self):
        said, patch = self.boxes()
        with patch, self.assertRaises(KeyboardInterrupt):
            with runcontrol.ctrl_c_stops("Test"):
                os.kill(os.getpid(), signal.SIGTERM)
                os.kill(os.getpid(), signal.SIGINT)
        self.assertEqual(said, ["wait", "quit"])  # never “stopped cleanly” after “quitting at once”

    def test_a_short_command_finishes_its_work_before_stopping(self):
        said, patch = self.boxes()
        finished = []
        with patch:
            with runcontrol.finish_then_stop("Ranking"):
                os.kill(os.getpid(), signal.SIGINT)
                finished.append("written")  # not cut short
        self.assertEqual((finished, said), (["written"], ["wait", "done"]))

    def test_the_handlers_are_given_back(self):
        before = signal.getsignal(signal.SIGTERM)
        with runcontrol.ctrl_c_stops():
            self.assertIsNot(signal.getsignal(signal.SIGTERM), before)
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


@unittest.skipUnless(os.name == "posix", "a real terminal command stopped by a signal: POSIX")
class CommandTests(unittest.TestCase):
    def test_a_real_command_stopped_by_kill_says_so_and_ends_cleanly(self):
        script = ("import os, signal, sys, time\n"
                  "from LocalExtraction import runcontrol\n"
                  "with runcontrol.finish_then_stop('Ranking'):\n"
                  "    os.kill(os.getpid(), signal.SIGTERM)\n"
                  "    time.sleep(0.2)\n"
                  "    print('work finished and saved', flush=True)\n")
        run = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, NO_COLOR="1"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("work finished and saved", run.stdout)
        self.assertIn("Stop requested — a stop signal (SIGTERM)", run.stderr)
        self.assertIn("Stopped cleanly", run.stderr)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.name == "posix", "signals sent to this process: POSIX")
class WindowSignalTests(unittest.TestCase):
    """A freeze once: Ctrl-C closed a window while its step ran; the step's threads went on with no window and the
    program never ended. Now the running steps are stopped first, the window kept until they have."""

    def test_ctrl_c_stops_the_running_step_then_closes_the_window(self):
        from LocalExtraction.tests.test_gui import has_screen, tk
        if not has_screen():
            self.skipTest("the window needs a screen")
        from LocalExtraction import crashlog
        before = {s: signal.getsignal(s) for s in runcontrol.stop_signals()}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in before.items()])
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        step = {"running": True, "stopped_at": None}

        def stop():
            step["stopped_at"] = time.monotonic()
            root.after(400, lambda: step.update(running=False))  # the step saves, then ends
        forget = runcontrol.register_step(lambda: step["running"], stop)
        self.addCleanup(forget)
        said = []
        with mock.patch.object(runcontrol, "say_box", side_effect=lambda kind, *a, **k: said.append(kind)):
            crashlog.watch(root)
            root.after(300, lambda: os.kill(os.getpid(), signal.SIGINT))
            start = time.monotonic()
            crashlog.run(root)
        self.assertIsNotNone(step["stopped_at"])  # Stop pressed by the signal
        self.assertFalse(step["running"])        # the window waited for the step to end
        self.assertEqual(said, ["wait", "done"])
        self.assertLess(time.monotonic() - start, 10)

    def test_ctrl_c_with_nothing_running_closes_at_once(self):
        from LocalExtraction.tests.test_gui import has_screen, tk
        if not has_screen():
            self.skipTest("the window needs a screen")
        from LocalExtraction import crashlog
        before = {s: signal.getsignal(s) for s in runcontrol.stop_signals()}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in before.items()])
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        said = []
        with mock.patch.object(runcontrol, "say_box", side_effect=lambda kind, *a, **k: said.append(kind)):
            crashlog.watch(root)
            root.after(300, lambda: os.kill(os.getpid(), signal.SIGINT))
            crashlog.run(root)
        self.assertEqual(said, [])
