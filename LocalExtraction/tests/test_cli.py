# LocalExtraction/tests/test_cli.py
"""Tests of the terminal gate of Project 1: python -m LocalExtraction. The extraction itself is
replaced by a stand-in; what is checked is which folders it is given and when it is not run.

    python -m unittest discover -s LocalExtraction/tests -t . -v   (or: pytest LocalExtraction)
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

from LocalExtraction import cli
from LocalExtraction.about import DEFAULT_INPUT, DEFAULT_OUTPUT


class GateTests(unittest.TestCase):
    def test_commands(self):
        extract = cli.parse_args(["extract", "--input", "x", "-w", "2"])
        self.assertEqual((extract.command, extract.input, extract.output, extract.workers, extract.rebuild),
                         ("extract", "x", DEFAULT_OUTPUT, 2, False))
        window = cli.parse_args(["gui", "--output", "elsewhere"])
        self.assertEqual((window.command, window.input, window.output), ("gui", DEFAULT_INPUT, "elsewhere"))

    def test_without_a_command_it_extracts(self):
        seen = []
        # (whatever database the folder these tests run in happens to hold is not their subject)
        with mock.patch.object(cli, "run_extraction", side_effect=lambda *a, **k: seen.append((a, k)) or 0), \
                mock.patch.object(cli, "is_outdated", return_value=False), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--input", "pdfs", "--output", "out"]), 0)
            self.assertEqual(cli.main([]), 0)
        self.assertEqual(seen[0][0][:2], ("pdfs", "out"))
        self.assertEqual(seen[1][0][:2], (DEFAULT_INPUT, DEFAULT_OUTPUT))

    def test_the_window_is_given_the_folders(self):
        opened = []
        with mock.patch("LocalExtraction.gui.main", side_effect=lambda **k: opened.append(k)), \
                mock.patch.object(cli, "print_banner"):
            self.assertEqual(cli.main(["gui", "--input", "pdfs", "-w", "3"]), 0)
        self.assertEqual(opened, [{"input_dir": "pdfs", "output_dir": DEFAULT_OUTPUT, "workers": 3}])

    def test_a_database_of_an_earlier_version_is_rebuilt_not_added_to(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        pdfs, out = os.path.join(folder, "pdfs"), os.path.join(folder, "out")
        os.makedirs(pdfs), os.makedirs(out)
        # An earlier version wrote no metadata_basis into papers.csv.
        pd.DataFrame([{"paper_id": "a.pdf", "filename": "a.pdf", "title": "An older one"}]).to_csv(
            os.path.join(out, "papers.csv"), index=False)
        pd.DataFrame([{"paper_id": "a.pdf", "property_name": "Migration_Barrier"}]).to_csv(os.path.join(out, "properties.csv"), index=False)
        runs = []
        printed = io.StringIO()
        with mock.patch.object(cli, "run_extraction", side_effect=lambda *a, **k: runs.append(a) or 0), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(printed):
            # Nothing is added to the old tables: they are moved aside and the PDFs read again, without being asked.
            self.assertEqual(cli.main(["--input", pdfs, "--output", out]), 0)
        self.assertEqual(len(runs), 1)
        self.assertIn("earlier version", printed.getvalue())
        kept, = [name for name in os.listdir(out) if name.startswith("previous_")]
        self.assertEqual(sorted(os.listdir(os.path.join(out, kept))), ["papers.csv", "properties.csv"])  # moved, not deleted
        self.assertFalse(os.path.exists(os.path.join(out, "papers.csv")))

    def test_the_metadata_is_looked_up_unless_offline(self):
        lookups = []
        with mock.patch.object(cli, "run_extraction", side_effect=lambda *a, **k: lookups.append(k["lookup"]) or 0), \
                mock.patch.object(cli, "is_outdated", return_value=False), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()):
            cli.main(["--input", "pdfs", "--output", "out"])
            cli.main(["--input", "pdfs", "--output", "out", "--offline"])
        self.assertEqual(lookups, [True, False])

if __name__ == "__main__":
    unittest.main()
