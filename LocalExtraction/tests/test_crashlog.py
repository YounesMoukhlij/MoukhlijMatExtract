# LocalExtraction/tests/test_crashlog.py
"""When the program fails where it should not, the whole story goes to a file a person can send with a report:
~/MoukhlijMatExtract/logs/crash_<date>.log."""

import io
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from LocalExtraction import about, crashlog


class CrashLogTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()) / "MoukhlijMatExtract"
        self.home.mkdir()
        self.addCleanup(shutil.rmtree, self.home.parent, True)
        patcher = mock.patch.object(about, "PROJECT_HOME", self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def boom(self):
        try:
            raise ZeroDivisionError("a division the code did not expect")
        except ZeroDivisionError:
            return sys.exc_info()

    def test_a_crash_is_written_with_what_is_needed_to_understand_it(self):
        path = crashlog.report(*self.boom(), where="mme-rank")
        self.assertEqual(path.parent, self.home / "logs")
        self.assertTrue(path.name.startswith("crash_") and path.name.endswith(".log"))
        text = path.read_text(encoding="utf-8")
        for expected in ("MoukhlijMatExtract", "mme-rank", "Python", "ZeroDivisionError: a division the code did not expect",
                         "Traceback"):
            self.assertIn(expected, text)

    def test_without_the_main_folder_it_goes_to_the_temporary_folder(self):
        shutil.rmtree(self.home)
        path = crashlog.report(*self.boom())
        self.assertEqual(path.parent, Path(tempfile.gettempdir()) / "MoukhlijMatExtract-logs")
        self.addCleanup(path.unlink)
        self.assertFalse(self.home.exists())  # the main folder is not made for it

    def test_the_hook_says_where_and_lets_the_usual_ending_happen(self):
        said = io.StringIO()
        previous = mock.Mock()
        with mock.patch.object(sys, "excepthook", previous), redirect_stderr(said):
            crashlog.install("mme-web")
            sys.excepthook(*self.boom())
            crashlog.install("mme-web")  # twice: still one hook
            self.assertIs(sys.excepthook.__wrapped__, previous)
        previous.assert_called_once()
        self.assertIn("The details are in", said.getvalue())
        self.assertEqual(len(list((self.home / "logs").glob("crash_*.log"))), 1)

    def test_ctrl_c_is_no_crash(self):
        with mock.patch.object(sys, "excepthook", mock.Mock()), redirect_stderr(io.StringIO()):
            crashlog.install()
            try:
                raise KeyboardInterrupt
            except KeyboardInterrupt:
                sys.excepthook(*sys.exc_info())
        self.assertFalse((self.home / "logs").exists())

    def test_a_worker_thread_crash_is_written_too(self):
        with mock.patch.object(threading, "excepthook", mock.Mock()), redirect_stderr(io.StringIO()):
            crashlog.install()
            worker = threading.Thread(target=lambda: 1 / 0)
            worker.start()
            worker.join()
        self.assertEqual(len(list((self.home / "logs").glob("crash_*.log"))), 1)



class SignalTests(unittest.TestCase):
    """Ctrl-C in the terminal, closing it, or being told to stop (SIGTERM) closes a window cleanly. Left to Tk, the
    signal shut Tcl down from whatever thread it reached and called Python from there: Python stopped with a fatal
    error (macOS: "Python quit unexpectedly")."""

    def test_a_watched_window_closes_itself_on_the_stop_signals(self):
        import signal
        from LocalExtraction.tests.test_gui import has_screen, tk
        if not has_screen():
            self.skipTest("the window needs a screen")
        stops = [s for s in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)) if s is not None]
        saved = {s: signal.getsignal(s) for s in stops}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in saved.items()])
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        crashlog.watch(root)
        for sig in saved:
            handler = signal.getsignal(sig)
            self.assertTrue(callable(handler) and getattr(handler, "_mme_closes", False), sig)
        # The signal only ends the window's loop (closing it there, in the middle of Tk's own work, crashed Tk);
        # run() closes the window once the loop has ended.
        root.after(100, lambda: signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None))
        crashlog.run(root)
        with self.assertRaises(tk.TclError):  # closed
            root.winfo_exists() and root.title()


if __name__ == "__main__":
    unittest.main()
