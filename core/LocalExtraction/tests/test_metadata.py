# LocalExtraction/tests/test_metadata.py
"""Tests of how a paper's description is completed (LocalExtraction/metadata.py): which work of
OpenAlex or Crossref is accepted for a PDF, and which is not. The network is replaced by stand-ins.

    python -m pytest LocalExtraction/tests/test_metadata.py
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from LocalExtraction import metadata
from LocalExtraction.parser import DocumentParser

FIRST_PAGE = ("Nature Communications | Article\nUnsupervised discovery of solid-\nstate lithium ion conductors\n"
              "Ying Zhang, Xingfeng He ...\nSee also https://doi.org/10.1000/a-reference for the method.")
WORK = {
    "id": "https://openalex.org/W2990048788", "doi": "https://doi.org/10.1038/s41467-019-13214-1",
    "display_name": "Unsupervised discovery of solid-state lithium ion conductors", "publication_year": 2019,
    "authorships": [{"author": {"display_name": "Ying Zhang"}}, {"author": {"display_name": "Xingfeng He"}}],
    "primary_location": {"source": {"display_name": "Nature Communications"}, "license": "cc-by"},
    "best_oa_location": {"license": "cc-by"}, "open_access": {"oa_status": "gold"},
}
OTHER_WORK = dict(WORK, display_name="A different paper about garnets", id="https://openalex.org/W1")


class _Answer:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body


class TitleTests(unittest.TestCase):
    def test_a_title_is_found_on_the_first_page_whatever_the_line_breaks(self):
        self.assertTrue(metadata.title_is_printed(WORK["display_name"], FIRST_PAGE))
        self.assertFalse(metadata.title_is_printed(OTHER_WORK["display_name"], FIRST_PAGE))
        self.assertFalse(metadata.title_is_printed("Short", FIRST_PAGE))  # too short to tell a title by

    def test_a_typesetters_file_name_is_not_a_title(self):
        for name in ("SpringerNature_NatCommun_77363_AIP 1..9", "manuscript.docx", "", "Untitled",
                     "arXiv:2411.06804v2 [cond-mat.mtrl-sci]", "Experimentally Measured"):
            self.assertTrue(DocumentParser._not_a_title(name), name)
        self.assertFalse(DocumentParser._not_a_title("Unsupervised discovery of solid-state lithium ion conductors"))


@mock.patch.dict(os.environ, {"MME_OFFLINE": ""})
class LookupTests(unittest.TestCase):
    def test_the_work_of_the_dois_paper_is_taken(self):
        with mock.patch.object(metadata.requests, "get", return_value=_Answer(200, WORK)) as get:
            found = metadata.lookup("10.1038/s41467-019-13214-1", "NONE", FIRST_PAGE)
        self.assertIn("/doi:10.1038/s41467-019-13214-1", get.call_args[0][0])
        self.assertEqual((found["title"], found["journal"], found["publication_year"], found["openalex_id"], found["license"]),
                         (WORK["display_name"], "Nature Communications", "2019", "W2990048788", "cc-by"))
        self.assertEqual(found["authors"], "Ying Zhang; Xingfeng He")
        self.assertEqual(found["basis"], "OpenAlex (by its DOI; its title is printed on the first page)")

    def test_the_doi_of_a_reference_is_not_taken_for_the_papers_own(self):
        answers = [_Answer(200, OTHER_WORK), _Answer(200, {"results": [WORK]})]
        with mock.patch.object(metadata.requests, "get", side_effect=answers):
            found = metadata.lookup("10.1000/a-reference", WORK["display_name"], FIRST_PAGE)
        self.assertEqual((found["doi"], found["basis"]),
                         ("10.1038/s41467-019-13214-1", "OpenAlex (by its title; its title is printed on the first page)"))

    def test_the_doi_a_source_reported_names_the_paper_even_for_a_manuscript(self):
        manuscript = FIRST_PAGE.replace("Unsupervised discovery of solid-\nstate lithium ion conductors",
                                        "Discovering lithium ion conductors without supervision")
        with mock.patch.object(metadata.requests, "get", return_value=_Answer(200, WORK)):
            guessed = metadata.lookup("10.1038/s41467-019-13214-1", "NONE", manuscript)
            reported = metadata.lookup("10.1038/s41467-019-13214-1", "NONE", manuscript, trusted_doi=True)
        self.assertIsNone(guessed)  # a DOI read from the PDF must be the paper's own
        self.assertEqual((reported["openalex_id"], reported["basis"]),
                         ("W2990048788", "OpenAlex (by the DOI its source reported)"))

    def test_crossref_answers_for_a_paper_openalex_does_not_know(self):
        crossref = {"message": {"title": [WORK["display_name"]], "DOI": "10.1038/S41467-019-13214-1",
                                "author": [{"given": "Ying", "family": "Zhang"}], "container-title": ["Nature Communications"],
                                "published": {"date-parts": [[2019, 11, 28]]},
                                "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}]}}
        answers = [_Answer(404), _Answer(200, crossref)]
        with mock.patch.object(metadata.requests, "get", side_effect=answers):
            found = metadata.lookup("10.1038/s41467-019-13214-1", "NONE", FIRST_PAGE)
        self.assertEqual((found["authors"], found["doi"], found["publication_year"], found["license"], found["basis"]),
                         ("Ying Zhang", "10.1038/s41467-019-13214-1", "2019", "cc-by",
                          "Crossref (by its DOI; its title is printed on the first page)"))

    def test_too_many_requests_is_asked_again(self):
        answers = [_Answer(429, headers={"Retry-After": "0"}), _Answer(200, WORK)]
        with mock.patch.object(metadata.requests, "get", side_effect=answers), mock.patch.object(metadata.time, "sleep"):
            found = metadata.lookup("10.1038/s41467-019-13214-1", "NONE", FIRST_PAGE)
        self.assertEqual(found["openalex_id"], "W2990048788")

    def test_no_network_means_no_lookup(self):
        with mock.patch.dict(os.environ, {"MME_OFFLINE": "1"}), \
                mock.patch.object(metadata.requests, "get") as get:
            self.assertIsNone(metadata.lookup("10.1038/s41467-019-13214-1", WORK["display_name"], FIRST_PAGE))
        get.assert_not_called()


    def test_a_service_that_cannot_be_reached_is_not_taken_for_no_match(self):
        metadata._outage["until"] = 0.0
        self.addCleanup(metadata._outage.update, {"until": 0.0})
        with mock.patch.object(metadata.requests, "get", side_effect=metadata.requests.ConnectionError("down")), \
                mock.patch.object(metadata.time, "sleep"):
            self.assertEqual(metadata.find("10.1038/s41467-019-13214-1", "NONE", FIRST_PAGE), (None, True))
        # ... and for a minute it is not asked again for every paper.
        with mock.patch.object(metadata.requests, "get") as get:
            self.assertEqual(metadata.find("10.1038/s41467-019-13214-1", "NONE", FIRST_PAGE), (None, True))
        get.assert_not_called()


class CacheTests(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_what_was_found_is_kept_for_the_next_run(self):
        path = os.path.join(self.folder, metadata.CACHE_NAME)
        cache = metadata.Cache(path)
        cache.put("abc", {"title": "A title", "openalex_id": "W1"})
        cache.save()
        self.assertEqual(metadata.Cache(path).get("abc"), {"title": "A title", "openalex_id": "W1"})
        self.assertIsNone(metadata.Cache(path).get("another"))

    def test_a_rebuild_takes_the_papers_description_from_the_cache(self):
        import pymupdf
        from LocalExtraction.pipeline import NaLiXPipeline
        pdfs, out = os.path.join(self.folder, "pdfs"), os.path.join(self.folder, "out")
        os.makedirs(pdfs)
        doc = pymupdf.open()
        doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), FIRST_PAGE + "\nLi6PS5Cl has an activation "
                                      "energy of 0.30 eV.", fontsize=10)
        doc.save(os.path.join(pdfs, "a.pdf"))
        described = metadata._describe(WORK, "by its DOI")
        with mock.patch.object(metadata, "find", return_value=(described, False)) as find:
            NaLiXPipeline(pdfs, out, lookup=True).execute(max_workers=1)  # the cache file is written with the batch
        self.assertEqual(find.call_count, 1)
        self.assertTrue(os.path.exists(os.path.join(out, metadata.CACHE_NAME)))
        with mock.patch.object(metadata, "find") as find:
            again = NaLiXPipeline(pdfs, out, lookup=True).process_document("a.pdf")
        find.assert_not_called()
        self.assertEqual((again.metadata["title"].normalized_value, again.provenance["openalex_id"]),
                         (WORK["display_name"], "W2990048788"))

if __name__ == "__main__":
    unittest.main()
