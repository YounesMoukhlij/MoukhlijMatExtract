"""The tests run with a home folder of their own, so a command they start never makes or writes the
real ~/MoukhlijMatExtract; and every test gets back the working folder a command moved it out of."""

import os
import shutil
import tempfile

import pytest


def pytest_configure(config):
    config.mme_home = tempfile.mkdtemp(prefix="mme-home-")
    os.environ["HOME"] = os.environ["USERPROFILE"] = config.mme_home  # Path.home() on POSIX / Windows


def pytest_unconfigure(config):
    shutil.rmtree(config.mme_home, ignore_errors=True)


@pytest.fixture(autouse=True)
def _same_working_folder():
    folder = os.getcwd()
    yield
    os.chdir(folder)
