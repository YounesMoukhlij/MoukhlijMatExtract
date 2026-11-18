# WebScraping/tests/test_browser_helper.py
"""The browser helper: which papers of the hand list it opens, and which PDFs of the Downloads folder it moves into
the by_hand folder — only new, complete PDFs that name a DOI of the list; nothing else is touched."""

import os
import tempfile
import time
import unittest
from pathlib import Path

import pymupdf

from WebScraping.averageScrap.browser_helper import DownloadsWatcher, next_batch, to_open
from WebScraping.averageScrap.by_hand import BLOCKED, BUSY, NO_COPY, SUBSCRIPTION


def pdf_naming(doi: str = "", text: str = "A paper") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 60), text, fontsize=11)
    if doi:
        page.insert_text((50, 80), f"https://doi.org/{doi}", fontsize=9)
    return document.tobytes()


def row(key, reason=BLOCKED, doi=None, link=True):
    doi = key if doi is None else doi
    return {"key": key, "doi": doi, "title": key, "reason": reason, "link": f"https://doi.org/{doi}" if link and doi else ""}


class ChoosingTests(unittest.TestCase):
    def test_it_opens_the_papers_it_can_match_and_leaves_the_busy_ones_to_the_next_download(self):
        rows = [row("10.1000/a"), row("10.1000/b", SUBSCRIPTION), row("10.1000/c", NO_COPY), row("10.1000/d", BUSY),
                row("W1", doi=""), row("10.1000/e", link=False)]
        self.assertEqual([r["key"] for r in to_open(rows)], ["10.1000/a", "10.1000/b", "10.1000/c"])

    def test_batches_follow_the_list_and_skip_what_was_opened(self):
        rows = [row(f"10.1000/{n}") for n in range(5)]
        self.assertEqual([r["key"] for r in next_batch(rows, set(), 2)], ["10.1000/0", "10.1000/1"])
        self.assertEqual([r["key"] for r in next_batch(rows, {"10.1000/0", "10.1000/1"}, 2)], ["10.1000/2", "10.1000/3"])
        self.assertEqual(next_batch(rows, {r["key"] for r in rows}, 2), [])


class WatcherTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.downloads, self.box = base / "Downloads", base / "papers" / "by_hand"
        self.downloads.mkdir()
        self.old = self.downloads / "old.pdf"
        self.old.write_bytes(pdf_naming("10.1000/wanted"))
        past = time.time() - 3600
        os.utime(self.old, (past, past))  # there before the helper started
        self.watcher = DownloadsWatcher(str(self.downloads), str(self.box), ["10.1000/wanted", "10.1000/other"])

    def test_a_new_pdf_of_the_list_is_moved_once_its_size_has_settled(self):
        (self.downloads / "article.pdf").write_bytes(pdf_naming("10.1000/wanted"))
        self.assertEqual(self.watcher.scan(), [])  # first look: it may still be growing
        moved = self.watcher.scan()
        self.assertEqual(moved, [str(self.box / "article.pdf")])
        self.assertFalse((self.downloads / "article.pdf").exists())
        self.assertEqual(self.watcher.scan(), [])  # once

    def test_other_files_are_never_touched(self):
        (self.downloads / "invoice.pdf").write_bytes(pdf_naming("", "An invoice"))
        (self.downloads / "other_paper.pdf").write_bytes(pdf_naming("10.9999/not-on-the-list"))
        (self.downloads / "notes.txt").write_text("10.1000/wanted")
        for _ in range(3):
            self.assertEqual(self.watcher.scan(), [])
        self.assertTrue(self.old.exists())  # older than the helper, even though it names a listed paper
        self.assertEqual(sorted(p.name for p in self.downloads.iterdir()),
                         ["invoice.pdf", "notes.txt", "old.pdf", "other_paper.pdf"])
        self.assertFalse(self.box.exists())

    def test_a_pdf_named_after_its_doi_is_matched_by_its_name(self):
        (self.downloads / "10.1000_other.pdf").write_bytes(pdf_naming("", "No DOI printed"))
        self.watcher.scan()
        self.assertEqual(self.watcher.scan(), [str(self.box / "10.1000_other.pdf")])

    def test_a_file_of_the_same_name_in_by_hand_is_kept(self):
        self.box.mkdir(parents=True)
        (self.box / "article.pdf").write_bytes(b"%PDF earlier")
        (self.downloads / "article.pdf").write_bytes(pdf_naming("10.1000/wanted"))
        self.watcher.scan()
        self.assertEqual(self.watcher.scan(), [str(self.box / "article (2).pdf")])
        self.assertEqual((self.box / "article.pdf").read_bytes(), b"%PDF earlier")


if __name__ == "__main__":
    unittest.main()
