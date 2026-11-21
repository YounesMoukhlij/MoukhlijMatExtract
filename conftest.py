"""The tests run with a home folder of their own, so a command they start never makes or writes the
real ~/MoukhlijMatExtract; and every test gets back the working folder a command moved it out of."""

import gc
import os
import shutil
import tempfile

import pytest

try:
    import tkinter
except ImportError:  # a Python built without Tk: the tests of the windows cannot run, the others do
    collect_ignore = ["LocalExtraction/tests/test_browser.py", "LocalExtraction/tests/test_result_card.py",
                      "SelectingTopMaterial/tests/test_gui.py", "Classification/tests/test_window.py"]


def _destroyed_once_settled():
    """A test's window finishes Tk's pending work before it is destroyed, as a window of the program does by running
    its loop. A window destroyed the moment it was made left Tk 9 a "show it" step for a window gone: the next window
    of the run crashed Python (macOS: "Python quit unexpectedly")."""
    try:
        destroy = tkinter.Tk.destroy
    except NameError:  # no Tk
        return

    def settled_destroy(self):
        try:
            self.update_idletasks()
        except tkinter.TclError:
            pass
        destroy(self)
    tkinter.Tk.destroy = settled_destroy


def pytest_configure(config):
    # The home folder first, before any module of the program is imported: the main folder's path is fixed when
    # LocalExtraction.about is first imported.
    config.mme_home = tempfile.mkdtemp(prefix="mme-home-")
    # Matplotlib keeps its font list in the home folder: the real one's, so it is not built again (20 s) every run.
    real_cache = os.path.join(os.path.expanduser("~"), ".matplotlib")
    if "MPLCONFIGDIR" not in os.environ and os.path.isdir(real_cache):
        os.environ["MPLCONFIGDIR"] = real_cache
    os.environ["HOME"] = os.environ["USERPROFILE"] = config.mme_home  # Path.home() on POSIX / Windows
    os.environ["MME_NO_NET_WAIT"] = "1"  # a test's failed request fails: it never waits for the internet
    from LocalExtraction import about
    if not str(about.PROJECT_HOME).startswith(config.mme_home):  # never a person's own ~/MoukhlijMatExtract
        raise pytest.UsageError(f"the tests would work in {about.PROJECT_HOME}, a person's own folder: "
                                "LocalExtraction.about was imported before conftest set the home folder")
    _destroyed_once_settled()
    # The keys of an earlier version (inside the package) are never read by a test: they are a person's own.
    from WebScraping.averageScrap import job
    job.OLD_ENV_PATH = os.path.join(tempfile.mkdtemp(prefix="mme-no-keys-"), ".env")
    if not job.ENV_PATH.startswith(config.mme_home):
        raise pytest.UsageError(f"the tests would read the keys of {job.ENV_PATH}, a person's own")


def pytest_unconfigure(config):
    shutil.rmtree(config.mme_home, ignore_errors=True)


@pytest.fixture(autouse=True)
def _windows_freed_on_the_main_thread():
    """The windows of the tests before are freed here, on the main thread. Left to the garbage collector,
    one could be freed by a working thread of a later test (a step loading the extraction, say) — and
    Tk aborts the whole process when its interpreter is freed by a thread other than its own."""
    gc.collect()
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _same_working_folder():
    folder = os.getcwd()
    yield
    os.chdir(folder)


@pytest.fixture(autouse=True)
def _no_real_dialog(monkeypatch):
    """A test never waits on a real message box or file dialog, which no one is there to answer: one it opens without
    stubbing fails at once, saying which (a test that expects one patches it, as before)."""
    try:
        from tkinter import filedialog, messagebox, simpledialog
    except ImportError:  # no Tk
        yield
        return

    def refused(kind):
        def dialog(*args, **kwargs):
            said = [str(a) for a in args[:2]] + [str(kwargs.get(k)) for k in ("title", "message") if kwargs.get(k)]
            raise AssertionError(f"the test opened a real {kind} ({' / '.join(said)[:200]}): patch it in the test")
        return dialog
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel", "askquestion",
                 "askretrycancel"):
        monkeypatch.setattr(messagebox, name, refused(f"message box ({name})"))
    for name in ("askstring", "askinteger", "askfloat"):
        monkeypatch.setattr(simpledialog, name, refused(f"question ({name})"))
    for name in ("askopenfilename", "asksaveasfilename", "askdirectory", "askopenfilenames"):
        monkeypatch.setattr(filedialog, name, refused(f"file dialog ({name})"))
    yield
