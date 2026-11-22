# mme_home/tests/test_home.py
"""What a user's ~/MoukhlijMatExtract gets from the package: configs/ (every job file, made when missing, never written
over) and docs/ (every document, kept up to date)."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mme_home


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()) / "MoukhlijMatExtract"
        self.addCleanup(shutil.rmtree, self.home.parent, True)

    def test_a_fresh_home_gets_every_job_file_and_every_document(self):
        mme_home.populate(self.home)
        configs = sorted(p.name for p in (self.home / "configs").iterdir())
        docs = sorted(p.name for p in (self.home / "docs").iterdir())
        self.assertEqual(configs, mme_home.shipped(mme_home.CONFIGS))
        self.assertEqual(docs, mme_home.shipped(mme_home.DOCS))
        for name in ("sse.yaml", "cathode.yaml", "anode.yaml", "garnet_nasicon.yaml", "garnet.yaml", "nasicon.yaml",
                     "lisicon.yaml", "perovskite.yaml", "halide.yaml"):
            self.assertIn(name, configs)
        for name in ("MANUAL.md", "COMMANDS.md", "DATA_DICTIONARY.md", "LIMITATIONS.md", "EVALUATION_PROTOCOL.md"):
            self.assertIn(name, docs)
        self.assertNotIn("PUBLISHING.md", docs)  # the maintainer's guide stays in the repository's docs/ only

    def test_a_job_file_the_user_edited_is_never_written_over_but_a_document_is_brought_up_to_date(self):
        mme_home.populate(self.home)
        job, manual = self.home / "configs" / "garnet.yaml", self.home / "docs" / "MANUAL.md"
        job.write_text("name: mine\n", encoding="utf-8")
        manual.write_text("an older manual", encoding="utf-8")
        written = mme_home.populate(self.home)
        self.assertEqual(job.read_text(encoding="utf-8"), "name: mine\n")
        self.assertNotEqual(manual.read_text(encoding="utf-8"), "an older manual")
        self.assertEqual(written, [manual])
        self.assertEqual(mme_home.populate(self.home), [])  # nothing to do the next time

    def test_every_command_fills_the_home_when_it_starts(self):
        from LocalExtraction import about
        here = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(here))
        with mock.patch.object(about, "PROJECT_HOME", self.home):
            about.enter_project_home("local")
        self.assertTrue((self.home / "configs" / "garnet_nasicon.yaml").is_file())
        self.assertTrue((self.home / "docs" / "MANUAL.md").is_file())


if __name__ == "__main__":
    unittest.main()
