"""The tests run with a home folder of their own, so a command they start never makes or writes the
real ~/MoukhlijMatExtract; and every test gets back the working folder a command moved it out of."""

import gc
import os
import shutil
import tempfile

import pytest


def pytest_configure(config):
    config.mme_home = tempfile.mkdtemp(prefix="mme-home-")
    os.environ["HOME"] = os.environ["USERPROFILE"] = config.mme_home  # Path.home() on POSIX / Windows
    os.environ["MME_NO_NET_WAIT"] = "1"  # a test's failed request fails: it never waits for the internet


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
