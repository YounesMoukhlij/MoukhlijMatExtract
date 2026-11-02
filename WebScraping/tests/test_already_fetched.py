# WebScraping/tests/test_already_fetched.py
"""moukhlij4scraping (web method 2): a DOI whose PDF is already in the folder — under its own name or
under the name averageScrap gives it — is not downloaded again. Offline."""

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from WebScraping.moukhlij4scraping.moukhlij4scraping import download


class AlreadyFetchedTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.location = os.path.join(self.folder, "")

    def test_a_pdf_already_there_is_skipped(self):
        open(os.path.join(self.folder, "10.1000_abc.pdf"), "wb").write(b"%PDF-1.4 stand-in")
        source = mock.Mock(return_value=(False, None))
        with mock.patch.object(download, "SOURCES", [("Stand-in", source)]), redirect_stdout(io.StringIO()) as said:
            self.assertTrue(download.download_from_doi("10.1000/ABC", self.location))
        source.assert_not_called()
        self.assertIn("Already fetched", said.getvalue())

    def test_a_pdf_averagescrap_saved_is_skipped(self):
        open(os.path.join(self.folder, "10.1016_s0022-2860_96_01234-5.pdf"), "wb").write(b"%PDF-1.4 stand-in")
        source = mock.Mock(return_value=(False, None))
        with mock.patch.object(download, "SOURCES", [("Stand-in", source)]), redirect_stdout(io.StringIO()):
            self.assertTrue(download.download_from_doi("10.1016/S0022-2860(96)01234-5", self.location))
        source.assert_not_called()

    def test_a_new_doi_is_looked_for(self):
        source = mock.Mock(return_value=(False, None))
        with mock.patch.object(download, "SOURCES", [("Stand-in", source)]), redirect_stdout(io.StringIO()):
            self.assertFalse(download.download_from_doi("10.1000/new", self.location))
        source.assert_called_once()


if __name__ == "__main__":
    unittest.main()
