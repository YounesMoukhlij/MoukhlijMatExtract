# LocalExtraction/tests/test_append.py
"""Adding papers to a database that already has some: the new rows go after the old ones, which are
never lost — not when a spreadsheet saved a table, not when a table cannot be read, not when a file
of a known name is another paper, not when the database is rebuilt. Offline: the PDFs are made here."""

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import pandas as pd
import pymupdf

from LocalExtraction.exporter import ADDED_BY_HAND, TABLE_NAMES, StrictExporter, UnreadableTable, read_table
from LocalExtraction.models import ExtractedField, PaperData
from LocalExtraction.pipeline import NaLiXPipeline

TEXT = ("Abstract. {formula} has an activation energy of {energy} eV and an ionic conductivity of 3 mS/cm at 25 C. "
        "doi: {doi}\n")


def make_pdf(path: str, title: str, formula: str = "Li6PS5Cl", energy: str = "0.30", doi: str = "10.1234/one.2024") -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), f"{title}\n\n" + TEXT.format(formula=formula, energy=energy, doi=doi),
                        fontsize=10)
    document.save(path)


def paper(filename: str, title: str = "A paper") -> PaperData:
    return PaperData(filename=filename, metadata={"title": ExtractedField(title, title, 1.0, "1", "Metadata", title, "Metadata")})


class AppendTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.pdfs, self.out = os.path.join(self.root, "papers"), os.path.join(self.root, "out")
        os.makedirs(self.pdfs)

    def run_pipeline(self, pdfs=None) -> int:
        with redirect_stdout(io.StringIO()):
            return NaLiXPipeline(pdfs or self.pdfs, self.out).execute(max_workers=1)

    def table(self, name: str) -> pd.DataFrame:
        return read_table(os.path.join(self.out, f"{name}.csv"))

    def test_the_database_is_the_same_whatever_order_the_papers_finish_in(self):
        """Several workers finish papers in any order: the files must not depend on it (release checksums)."""
        for name in ("b.pdf", "a.pdf", "c.pdf"):
            make_pdf(os.path.join(self.pdfs, name), f"Paper {name}", energy={"a.pdf": "0.31", "b.pdf": "0.32", "c.pdf": "0.33"}[name],
                     doi=f"10.1234/{name[0]}.2024")
        files = {}
        for order in (["a.pdf", "b.pdf", "c.pdf"], ["c.pdf", "a.pdf", "b.pdf"]):
            out = os.path.join(self.root, "out_" + "".join(n[0] for n in order))
            with redirect_stdout(io.StringIO()):
                pipeline = NaLiXPipeline(self.pdfs, out, lookup=False)
                results = {n: pipeline.process_document(n, os.path.join(self.pdfs, n)) for n in order}
                for n in order:  # one paper at a time, as batches of finished papers are saved
                    results[n].paper_id = n
                    StrictExporter(out).export([results[n]], excel=False)
            files[tuple(order)] = {name: open(os.path.join(out, f"{name}.csv"), "rb").read()
                                   for name in ("papers", "activation_energy", "ionic_conductivity")}
            files[tuple(order)]["json"] = open(os.path.join(out, "database.json"), "rb").read()
        first, second = files.values()
        for name in first:
            self.assertEqual(first[name], second[name], name)

    def test_a_pdf_already_extracted_is_said_and_skipped(self):
        make_pdf(os.path.join(self.pdfs, "a.pdf"), "First paper on argyrodite conductors")
        self.assertEqual(self.run_pipeline(), 1)
        with self.assertLogs(level="INFO") as said:
            self.assertEqual(self.run_pipeline(), 0)
        self.assertTrue(any("Already extracted: a.pdf" in line for line in said.output))
        self.assertTrue(any("already extracted — nothing to do" in line for line in said.output))

    # ------------------------------------------------------------------
    # The files
    # ------------------------------------------------------------------
    def test_a_table_saved_by_a_spreadsheet_is_read_and_appended_to(self):
        StrictExporter(self.out).export([paper("a.pdf", "First paper")], excel=False)
        path = os.path.join(self.out, "papers.csv")
        read_table(path).to_csv(path, sep=";", index=False, encoding="cp1252")  # as Excel saves it in some locales
        StrictExporter(self.out).export([paper("b.pdf", "Second paper — é")], excel=False)
        papers = self.table("papers")
        self.assertEqual((list(papers.paper_id), papers.title[1]), (["a.pdf", "b.pdf"], "Second paper — é"))
        with open(path, encoding="utf-8-sig") as f:
            self.assertIn("paper_id,filename", f.readline())  # written back as this program writes it

    def test_a_table_that_cannot_be_read_stops_everything_before_anything_is_written(self):
        StrictExporter(self.out).export([paper("a.pdf")], excel=False)
        with open(os.path.join(self.out, "materials.csv"), "ab") as f:
            f.write(b'\n"an unclosed quote,' + b"x," * 100 + b"\n")
        before = {name: open(os.path.join(self.out, name), "rb").read() for name in os.listdir(self.out)}
        with self.assertRaisesRegex(UnreadableTable, "materials.csv .* none of its rows are lost"):
            StrictExporter(self.out).export([paper("b.pdf")], excel=False)
        self.assertEqual({name: open(os.path.join(self.out, name), "rb").read() for name in os.listdir(self.out)}, before)

    def test_a_paper_written_again_replaces_its_rows_and_a_column_added_by_hand_is_kept(self):
        StrictExporter(self.out).export([paper("a.pdf", "Old title"), paper("b.pdf")], excel=False)
        path = os.path.join(self.out, "papers.csv")
        papers = read_table(path)
        papers["my_notes"] = ["read it", "skip"]
        papers.to_csv(path, index=False)
        StrictExporter(self.out).export([paper("a.pdf", "New title"), paper("c.pdf")], excel=False)
        papers = self.table("papers")
        self.assertEqual(list(papers.paper_id), ["a.pdf", "b.pdf", "c.pdf"])  # a.pdf once, in paper order
        self.assertEqual(list(papers.my_notes), [ADDED_BY_HAND, "skip", ADDED_BY_HAND])  # a.pdf was written again
        import json
        with open(os.path.join(self.out, "database.json"), encoding="utf-8") as f:
            self.assertEqual([p["paper_id"] for p in json.load(f)["papers"]], ["a.pdf", "b.pdf", "c.pdf"])

    def test_a_database_lacking_a_table_or_a_column_is_an_earlier_version(self):
        StrictExporter(self.out).export([paper("a.pdf")], excel=False)
        self.assertFalse(StrictExporter.is_outdated(self.out))
        path = os.path.join(self.out, "figures.csv")
        read_table(path).drop(columns="caption").to_csv(path, index=False)
        self.assertTrue(StrictExporter.is_outdated(self.out))
        os.remove(path)
        self.assertTrue(StrictExporter.is_outdated(self.out))

    # ------------------------------------------------------------------
    # The PDFs
    # ------------------------------------------------------------------
    def test_new_pdfs_are_added_after_the_papers_already_there(self):
        make_pdf(os.path.join(self.pdfs, "one.pdf"), "Lithium conduction in argyrodites")
        self.assertEqual(self.run_pipeline(), 1)
        first = self.table("activation_energy")
        make_pdf(os.path.join(self.pdfs, "two.pdf"), "Sodium conduction in NASICON", "Na3Zr2Si2PO12", "0.35", "10.1234/two.2024")
        self.assertEqual(self.run_pipeline(), 1)
        energies = self.table("activation_energy")
        self.assertEqual(energies.iloc[:len(first)].to_dict("records"), first.to_dict("records"))  # untouched, first
        self.assertEqual(list(energies.paper_id), ["one.pdf", "two.pdf"])
        self.assertEqual(self.run_pipeline(), 0)  # nothing twice
        self.assertEqual(len(self.table("papers")), 2)

    def test_another_paper_under_a_known_name_is_added_and_a_copy_is_not(self):
        make_pdf(os.path.join(self.pdfs, "Article 1.pdf"), "Lithium conduction in argyrodites")
        self.run_pipeline()
        make_pdf(os.path.join(self.pdfs, "Article 1.pdf"), "Sodium conduction in NASICON", "Na3Zr2Si2PO12", "0.35",
                 "10.1234/two.2024")  # the folder's file replaced by another paper
        shutil.copy(os.path.join(self.pdfs, "Article 1.pdf"), os.path.join(self.pdfs, "copy.pdf"))
        self.assertEqual(self.run_pipeline(), 1)
        papers = self.table("papers")
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers.paper_id[0], "Article 1.pdf")
        self.assertRegex(papers.paper_id[1], r"^Article 1\.pdf#[0-9a-f]{8}$")
        self.assertEqual(set(self.table("activation_energy").material_formula), {"Li6PS5Cl", "Na3Zr2Si2PO12"})

    def test_a_new_copy_of_the_same_paper_replaces_its_rows(self):
        make_pdf(os.path.join(self.pdfs, "paper.pdf"), "Lithium conduction in argyrodites", energy="0.30")
        self.run_pipeline()
        make_pdf(os.path.join(self.pdfs, "paper.pdf"), "Lithium conduction in argyrodites", energy="0.25")  # corrected
        self.assertEqual(self.run_pipeline(), 1)
        self.assertEqual(list(self.table("papers").paper_id), ["paper.pdf"])
        self.assertEqual(list(self.table("activation_energy").activation_energy_eV), ["0.25"])

    def test_a_rebuild_keeps_every_paper_also_when_its_pdf_is_elsewhere_or_gone(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        make_pdf(os.path.join(self.pdfs, "here.pdf"), "Lithium conduction in argyrodites")
        make_pdf(os.path.join(elsewhere, "there.pdf"), "Sodium conduction in NASICON", "Na3Zr2Si2PO12", "0.35", "10.1234/two.2024")
        make_pdf(os.path.join(elsewhere, "gone.pdf"), "Halide electrolytes", "Li3YCl6", "0.40", "10.1234/three.2024")
        self.run_pipeline()
        self.run_pipeline(elsewhere)  # another folder, the same database
        os.remove(os.path.join(elsewhere, "gone.pdf"))
        before = self.table("activation_energy")
        kept = StrictExporter.archive(self.out)  # --rebuild
        self.assertEqual(StrictExporter.pending_rebuilds(self.out), [kept])
        self.run_pipeline()
        energies = self.table("activation_energy")
        self.assertEqual(sorted(energies.paper_id), sorted(before.paper_id))
        self.assertEqual(sorted(self.table("papers").paper_id), ["gone.pdf", "here.pdf", "there.pdf"])
        self.assertEqual(StrictExporter.pending_rebuilds(self.out), [])  # done
        for name in TABLE_NAMES:
            self.assertTrue(os.path.exists(os.path.join(self.out, f"{name}.csv")), name)



class LongCellTests(unittest.TestCase):
    def test_a_table_cell_of_any_length_can_be_read_once_the_program_is_loaded(self):
        """A record's abstract or a table's text can exceed the 131,072 characters Python's CSV reader takes by
        default; the program lifts that limit as soon as it is loaded, for every part that reads a CSV file."""
        import subprocess
        import sys
        script = "import csv, LocalExtraction; print(csv.field_size_limit() > 10_000_000)"
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        done = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.stdout.strip(), "True", done.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
