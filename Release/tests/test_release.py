# Release/tests/test_release.py
"""Reproducibility: the run manifest and the extracted_with column say how a result was made; the data
dictionary describes every column the program writes, and docs/DATA_DICTIONARY.md is current; the
release keeps every value, withholds only the text a paper's license does not let be shared, and its
checksums hold."""

import hashlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pandas as pd

from LocalExtraction import provenance, schema
from Release import cli, release


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_each_run_is_appended_with_its_settings_environment_and_files(self):
        (self.folder / "a.csv").write_text("x\n1\n2\n", encoding="utf-8")
        (self.folder / "previous_20260101").mkdir()
        (self.folder / "previous_20260101" / "old.csv").write_text("x\n", encoding="utf-8")
        provenance.Run("test", self.folder, settings={"k": 1}).finish({"n": 2})
        provenance.Run("test", self.folder, settings={"k": 2}).finish({"n": 3}, status="stopped")
        runs = json.loads((self.folder / provenance.MANIFEST).read_text(encoding="utf-8"))["runs"]
        self.assertEqual([r["settings"]["k"] for r in runs], [1, 2])
        self.assertEqual(runs[1]["status"], "stopped")
        first = runs[0]
        self.assertEqual(first["outputs"]["a.csv"]["rows"], 2)
        self.assertEqual(first["outputs"]["a.csv"]["sha256"],
                         hashlib.sha256((self.folder / "a.csv").read_bytes()).hexdigest())
        self.assertNotIn("previous_20260101/old.csv", first["outputs"])  # earlier databases are not outputs
        self.assertIn("pandas", first["environment"]["packages"])
        self.assertIn("python", first["environment"])

    def test_an_unreadable_manifest_is_kept_aside_not_lost(self):
        (self.folder / provenance.MANIFEST).write_text("{ broken", encoding="utf-8")
        provenance.Run("test", self.folder, settings={}).finish()
        self.assertEqual(len(list(self.folder.glob(f"{provenance.MANIFEST}.unreadable-*"))), 1)
        self.assertEqual(len(json.loads((self.folder / provenance.MANIFEST).read_text())["runs"]), 1)

    def test_each_paper_says_what_read_it(self):
        text = provenance.extracted_with()
        self.assertIn("MoukhlijMatExtract", text)
        self.assertRegex(text, r"en_core_\w+ \d|no language model")


class DictionaryTests(unittest.TestCase):
    def test_every_column_is_described(self):
        self.assertEqual(schema.missing(), [])
        for row in schema.rows():
            self.assertTrue(row["description"].strip(), row)

    def test_the_published_dictionary_is_current(self):
        doc = schema.DOC
        self.assertTrue(doc.exists(), "docs/DATA_DICTIONARY.md is missing: make dictionary")
        self.assertEqual(doc.read_text(encoding="utf-8"), schema.markdown(),
                         "docs/DATA_DICTIONARY.md is out of date: make dictionary")


def _database(folder: Path) -> Path:
    folder.mkdir(parents=True)
    pd.DataFrame([{"paper_id": "open.pdf", "title": "Open", "license": "cc-by", "doi": "10.1/open", "source_service": "pmc"},
                  {"paper_id": "closed.pdf", "title": "Closed", "license": "no open license (closed access)",
                   "doi": "10.1/closed", "source_service": "elsevier"},
                  {"paper_id": "nd.pdf", "title": "ND", "license": "cc-by-nc-nd", "doi": "10.1/nd",
                   "source_service": "unpaywall"}]).to_csv(folder / "papers.csv", index=False)
    pd.DataFrame([{"paper_id": p, "material_formula": "Li6PS5Cl", "activation_energy_eV": e, "page": "3",
                   "sentence": f"The Ea of Li6PS5Cl is {e} eV."} for p, e in
                  [("open.pdf", "0.3"), ("closed.pdf", "0.31"), ("nd.pdf", "0.32")]]).to_csv(
        folder / "activation_energy.csv", index=False)
    (folder / "database.json").write_text("{}", encoding="utf-8")
    (folder / "previous_20260101").mkdir()
    (folder / "previous_20260101" / "papers.csv").write_text("paper_id\nold.pdf\n", encoding="utf-8")
    return folder


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.db = _database(self.base / "web_output")

    def test_licenses(self):
        for text in ("cc-by", "CC-BY-4.0", "cc0", "public-domain"):
            self.assertTrue(release.shareable(text), text)
        for text in ("cc-by-nc", "cc-by-nc-nd", "cc-by-sa", "other-oa", "no open license (closed access)", ""):
            self.assertFalse(release.shareable(text), text)

    def test_values_kept_text_withheld_by_license(self):
        report = release.make([self.db], [], self.base / "out", "1.2.3")
        table = pd.read_csv(report.folder / "web_output" / "activation_energy.csv", dtype=str).set_index("paper_id")
        self.assertEqual(table.activation_energy_eV.tolist(), ["0.3", "0.31", "0.32"])  # every value
        self.assertTrue(table.loc["open.pdf", "sentence"].startswith("The Ea"))
        for paper in ("closed.pdf", "nd.pdf"):
            self.assertTrue(table.loc[paper, "sentence"].startswith("withheld"), paper)
            self.assertIn("page 3", table.loc[paper, "sentence"])
        self.assertEqual((report.papers, report.papers_with_text, report.cells_withheld), (3, 1, 2))
        self.assertFalse((report.folder / "web_output" / "database.json").exists())  # it holds every text
        self.assertFalse((report.folder / "web_output" / "previous_20260101").exists())

    def test_checksums_and_the_archive(self):
        report = release.make([self.db], [], self.base / "out", "1.2.3")
        self.assertEqual(report.archive.name, report.folder.name + ".zip")  # the version's dots kept
        for line in (report.folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((report.folder / name).read_bytes()).hexdigest(), digest, name)
        with zipfile.ZipFile(report.archive) as archive:
            self.assertIn(f"{report.folder.name}/README.md", archive.namelist())
        # the README completed by hand, then sealed again
        readme = report.folder / "README.md"
        readme.write_text(readme.read_text().replace("TO COMPLETE", "done"), encoding="utf-8")
        release.seal(report.folder)
        self.assertEqual(release.unfinished(report.folder), 0)
        sums = dict(reversed(line.split("  ", 1)) for line in (report.folder / "SHA256SUMS").read_text().splitlines())
        self.assertEqual(sums["README.md"], hashlib.sha256(readme.read_bytes()).hexdigest())

    def test_only_legally_obtained_copies_are_released(self):
        papers = pd.read_csv(self.db / "papers.csv", dtype=str)
        papers.loc[papers.paper_id == "closed.pdf", "source_service"] = "a file of this computer"  # no record
        papers.loc[papers.paper_id == "nd.pdf", "source_service"] = "a file of this computer"
        papers.to_csv(self.db / "papers.csv", index=False)
        log = self.base / "scrape_log.csv"
        pd.DataFrame([{"doi": "10.1/nd", "title": "ND", "result": "saved", "source": "Sci-Hub", "file": "nd.pdf",
                       "tried_at": "2026"}]).to_csv(log, index=False)
        report = release.make([self.db], [], self.base / "out", "1.2.3", log=log)
        kept = pd.read_csv(report.folder / "web_output" / "activation_energy.csv", dtype=str)
        self.assertEqual(kept.paper_id.tolist(), ["open.pdf"])
        excluded = pd.read_csv(report.folder / "excluded.csv", dtype=str).set_index("paper_id")["why"].to_dict()
        self.assertEqual(excluded, {"closed.pdf": "no record of where the copy came from",
                                    "nd.pdf": "a copy from a shadow library (Sci-Hub)"})
        self.assertEqual(report.papers, 1)
        self.assertIn("2 paper(s) were left out", (report.folder / "README.md").read_text(encoding="utf-8"))
        # the authors' own PDFs (part 1) are theirs to answer for; a private copy may keep everything
        own = self.base / "local_output"
        shutil.copytree(self.db, own)
        report = release.make([own], [], self.base / "out2", "1.2.3", log=log)
        self.assertEqual(report.papers, 2)  # nd.pdf: the log says a shadow library, even in part 1
        report = release.make([self.db], [], self.base / "out3", "1.2.3", log=log, keep_unrecorded=True)
        self.assertEqual(report.papers, 3)

    def test_keep_text_keeps_everything(self):
        report = release.make([self.db], [], self.base / "out", "1.2.3", keep_text=True)
        table = pd.read_csv(report.folder / "web_output" / "activation_energy.csv", dtype=str)
        self.assertFalse(table.sentence.str.startswith("withheld").any())

    def test_the_command(self):
        import os
        from LocalExtraction import about
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)  # the command works from the (patched) project home
        with mock.patch.object(about, "PROJECT_HOME", self.base / "home"):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--source", str(self.db), "--no-results", "--out", str(self.base / "rel")])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("1 openly licensed", out.getvalue())
        self.assertEqual(len(list((self.base / "rel").glob("*.zip"))), 1)
        runs = json.loads((self.base / "rel" / provenance.MANIFEST).read_text())["runs"]
        self.assertEqual(runs[-1]["part"], "release")


if __name__ == "__main__":
    unittest.main()
