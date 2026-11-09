# LocalExtraction/tests/test_cli.py
"""Tests of the terminal gate of Project 1: python -m LocalExtraction. The extraction itself is
replaced by a stand-in; what is checked is which folders it is given and when it is not run.

    python -m unittest discover -s LocalExtraction/tests -t . -v   (or: pytest LocalExtraction)
"""

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

from LocalExtraction import about, cli
from LocalExtraction.about import DEFAULT_INPUT, DEFAULT_OUTPUT, PART_FOLDERS


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

    @unittest.skipUnless(importlib.util.find_spec("_tkinter"), "this Python has no Tk")
    def test_the_window_is_given_the_folders(self):
        opened = []
        with mock.patch("LocalExtraction.gui.main", side_effect=lambda **k: opened.append(k)), \
                mock.patch.object(cli, "print_banner"):
            self.assertEqual(cli.main(["gui", "--input", "pdfs", "-w", "3"]), 0)
        self.assertEqual(opened, [{"input_dir": "pdfs", "output_dir": DEFAULT_OUTPUT, "workers": 3, "lookup": True}])
        opened.clear()
        with mock.patch("LocalExtraction.gui.main", side_effect=lambda **k: opened.append(k)), \
                mock.patch.object(cli, "print_banner"):
            self.assertEqual(cli.main(["gui", "--offline"]), 0)
        self.assertFalse(opened[0]["lookup"])  # --offline reaches the window

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

    def test_it_works_inside_the_project_home_and_makes_its_folders(self):
        home = Path(tempfile.mkdtemp()) / "MoukhlijMatExtract"
        self.addCleanup(shutil.rmtree, home.parent, True)
        self.addCleanup(os.chdir, os.getcwd())
        with mock.patch.object(about, "PROJECT_HOME", home), mock.patch.object(cli, "run_extraction", return_value=0), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)  # makes the home folder and the folders of part 1
            self.assertEqual(cli.main([]), 0)  # finds them already there
        self.assertEqual(sorted(path.name for path in (home / "LocalExtraction").iterdir()), ["local_output", "papers"])
        self.assertEqual(Path.cwd().resolve(), home.resolve())

    def test_every_part_has_its_folders_made(self):
        home = Path(tempfile.mkdtemp()) / "MoukhlijMatExtract"
        self.addCleanup(shutil.rmtree, home.parent, True)
        self.addCleanup(os.chdir, os.getcwd())
        with mock.patch.object(about, "PROJECT_HOME", home):
            about.enter_project_home(*PART_FOLDERS)
        for folders in PART_FOLDERS.values():
            for folder in folders:
                self.assertTrue((home / folder).is_dir(), folder)



class EarlierDatabaseTests(unittest.TestCase):
    """A database of an earlier version, in the terminal: added to, or a new one — asked when a person is there."""

    def setUp(self):
        from LocalExtraction.exporter import COLUMNS, TABLE_NAMES
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        for name in TABLE_NAMES:  # every table, each without the columns the last version added
            columns = [c for c in COLUMNS[name] if c not in ("extracted_with", "mobile_ion", "plausibility")]
            row = {c: "x" for c in columns}
            row.update(paper_id="a.pdf", material_formula="Li3PS4", sentence="The Ea of Li3PS4 is 0.3 eV.")
            pd.DataFrame([row] if name in ("papers", "activation_energy") else [], columns=columns).to_csv(
                self.folder / f"{name}.csv", index=False)

    def run_it(self, rebuild=False, typed=None):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(sys.stdin, "isatty", return_value=typed is not None), \
                mock.patch("builtins.input", side_effect=list(typed or [])):
            go_on = cli.rebuild_if_asked(str(self.folder), rebuild)
        return go_on, out.getvalue()

    def kept(self):
        return [p.name for p in self.folder.iterdir() if p.name.startswith("previous_")]

    def test_a_script_keeps_the_data_and_adds_to_it(self):
        go_on, said = self.run_it()
        self.assertTrue(go_on)
        self.assertIn("brought up to date", said)
        self.assertTrue((self.folder / "papers.csv").exists())
        self.assertIn("mobile_ion", pd.read_csv(self.folder / "activation_energy.csv").columns)
        self.assertEqual(len(self.kept()), 1)

    def test_a_person_chooses(self):
        go_on, said = self.run_it(typed=["?", "q"])  # a wrong key is asked again
        self.assertFalse(go_on)
        self.assertEqual(self.kept(), [])  # stopped: nothing changed
        go_on, said = self.run_it(typed=["n"])
        self.assertTrue(go_on)
        self.assertFalse((self.folder / "papers.csv").exists())  # moved aside for a new database
        self.assertIn("papers.csv", os.listdir(self.folder / self.kept()[0]))

    def test_rebuild_starts_a_new_database_without_asking(self):
        go_on, said = self.run_it(rebuild=True, typed=[])
        self.assertTrue(go_on)
        self.assertIn("A new database", said)
        self.assertFalse((self.folder / "papers.csv").exists())


if __name__ == "__main__":
    unittest.main()
