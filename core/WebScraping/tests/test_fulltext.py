# WebScraping/tests/test_fulltext.py
"""The search at scale: OpenAlex's full-text search (every paper whose full text holds the data words, the papers worth
downloading), arXiv's bulk copy (its PDFs without the 15 s between two), and `mme-web update --all` (every job, even
those never run). No network."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from WebScraping.tests.test_web import FakeResponse, FakeSession, candidate, client_for  # also: offline, sys.path
from WebScraping.averageScrap import cli
from WebScraping.averageScrap.harvest import Harvest
from WebScraping.averageScrap.job import FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from WebScraping.averageScrap.ledger import NEW, REJECTED, SCREENED
from WebScraping.averageScrap.resolve import Resolver, arxiv_bulk_prefix
from WebScraping.averageScrap.screening import screen
from WebScraping.averageScrap.sources.openalex import FULLTEXT, OpenAlex, fulltext_phrases


def work(n: int, title: str, abstract_words=("garnet", "solid", "electrolyte")):
    return {"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.1000/f{n}", "title": title,
            "publication_year": 2022, "type": "article", "open_access": {"is_oa": True, "oa_status": "gold"},
            "best_oa_location": {"pdf_url": f"https://repo.example.org/f{n}.pdf"},
            "abstract_inverted_index": {word: [i] for i, word in enumerate(abstract_words)}}


PAGES = {"*": ([work(1, "Garnet solid electrolyte made by sol-gel"), work(2, "A garnet solid electrolyte film")], "c2"),
         "c2": ([work(3, "Sintering a garnet solid electrolyte")], None)}


def fulltext_answers(url, params, headers):
    if "fulltext.search" not in params.get("filter", ""):
        return FakeResponse(200, json_data={"results": [], "meta": {"next_cursor": None}})
    results, cursor = PAGES[params["cursor"]]
    return FakeResponse(200, json_data={"results": results, "meta": {"count": 3, "next_cursor": cursor}})


class FullTextSearchTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession([("api.openalex.org/works", fulltext_answers)])

    def test_the_phrases_of_a_query(self):
        self.assertEqual(fulltext_phrases('"activation energy" "ionic conductivity"'),
                         ["activation energy", "ionic conductivity"])
        self.assertEqual(fulltext_phrases("activation energy"), ["activation energy"])
        self.assertEqual(fulltext_phrases('"a, b"'), ["a b"])  # a comma would end OpenAlex's filter

    def test_every_page_is_taken_each_phrase_exact_and_the_total_told(self):
        totals = []
        source = OpenAlex(client_for(self.session), api_key="k")
        found = list(source.fulltext_search('"activation energy" "garnet"', years=(2015, 2026), open_only=True,
                                            on_total=totals.append))
        self.assertEqual([c.doi for c in found], ["10.1000/f1", "10.1000/f2", "10.1000/f3"])
        self.assertEqual(totals, [3])
        self.assertEqual(found[0].found_by, [f'{FULLTEXT}: "activation energy" "garnet"'])
        asked = self.session.calls[0][1]["filter"]
        self.assertIn('fulltext.search:"activation energy"', asked)  # quoted: the exact phrase
        self.assertIn('fulltext.search:"garnet"', asked)
        self.assertIn("is_oa:true", asked)
        self.assertIn("from_publication_date:2015-01-01", asked)
        self.assertEqual(self.session.calls[0][1]["per-page"], 200)

    def test_without_a_key_only_the_first_page(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("OPENALEX_API_KEY", None)
            found = list(OpenAlex(client_for(self.session)).fulltext_search('"activation energy"'))
        self.assertEqual(len(found), 2)


class FullTextHarvestTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.environ["OPENALEX_API_KEY"] = "k"
        self.addCleanup(os.environ.pop, "OPENALEX_API_KEY", None)
        self.session = FakeSession([("api.openalex.org/works", fulltext_answers)])
        self.job = Job(search=SearchConfig(queries=[], sources=["openalex"], abstract_sources=[],
                                           fulltext_queries=['"activation energy" "garnet"']),
                       screen=ScreenConfig(topic_words=["garnet"], property_words=["activation energy"]),
                       fetch=FetchConfig(folder=os.path.join(self.root, "papers")))
        self.harvest = Harvest(self.job, os.path.join(self.root, "out"), client=client_for(self.session))
        self.addCleanup(self.harvest.ledger.close)

    def test_the_sweep_files_every_match_and_their_full_text_counts_as_the_property_words(self):
        # A paper the keywords found before, turned down because its abstract lacks "activation energy":
        self.harvest.ledger.add(candidate(key="10.1000/f3", doi="10.1000/f3", title="Sintering a garnet solid electrolyte",
                                          abstract="A garnet solid electrolyte, sintered."))
        self.harvest.ledger.update("10.1000/f3", status=REJECTED, decision="no")
        # ... and one a person turned down: their decision stays.
        self.harvest.ledger.add(candidate(key="10.1000/f2", doi="10.1000/f2", title="A garnet solid electrolyte film"))
        self.harvest.ledger.update("10.1000/f2", status=SCREENED, decision="no", decided_by="hand")
        phases = []
        self.harvest.on_progress = lambda phase, done, total, detail, new: phases.append((phase, done, total))
        self.assertEqual(self.harvest._search_fulltext(refresh=False), 1)  # f1 is new
        self.assertEqual(self.harvest.ledger.get("10.1000/f3").status, NEW)  # scored again
        self.assertEqual(self.harvest.ledger.get("10.1000/f2").status, SCREENED)
        self.assertEqual(phases[-1], ("fulltext", 3, 3))

        screen(self.harvest.ledger, self.job.screen)
        for key in ("10.1000/f1", "10.1000/f3"):
            paper = self.harvest.ledger.get(key)
            self.assertEqual(paper.decision, "yes", key)  # no "activation energy" in title or abstract: in the full text
            self.assertIn("(full text)", paper.why)
        self.assertEqual(self.harvest.ledger.get("10.1000/f2").decision, "no")

        calls = len(self.session.calls)
        self.assertEqual(self.harvest._search_fulltext(refresh=False), 0)  # searched already: not asked again
        self.assertEqual(len(self.session.calls), calls)

    def test_a_paper_without_the_topic_is_still_turned_down(self):
        self.harvest.ledger.add(candidate(key="10.1000/x", doi="10.1000/x", title="Silicon anodes",
                                          found_by=[f"{FULLTEXT}: \"activation energy\""]))
        screen(self.harvest.ledger, self.job.screen)
        self.assertEqual(self.harvest.ledger.get("10.1000/x").decision, "no")


class FullTextJobTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, text: str) -> str:
        path = os.path.join(self.root, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_a_job_of_full_text_searches_only_loads_and_is_written_back_the_same(self):
        job = load_job(self.write('search:\n  fulltext_queries:\n    - \'"activation energy" "garnet"\'\n'
                                  '  fulltext_max: 5000\n  fulltext_open_only: true\n'))
        self.assertEqual(job.search.fulltext_queries, ['"activation energy" "garnet"'])
        self.assertEqual((job.search.fulltext_max, job.search.fulltext_open_only), (5000, True))
        self.assertEqual(load_job(self.write(dump_job(job))), job)

    def test_the_number_taken_is_held_within_its_bounds(self):
        with self.assertRaisesRegex(ValueError, "search.fulltext_max"):
            load_job(self.write("search: {queries: [a], fulltext_max: 0}\n"))

    def test_every_shipped_job_has_full_text_searches(self):
        configs = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "resources", "configs")
        for name in sorted(os.listdir(configs)):
            with self.subTest(name):
                job = load_job(os.path.join(configs, name))
                self.assertTrue(job.search.fulltext_queries)
                self.assertTrue(all(fulltext_phrases(q) for q in job.search.fulltext_queries))


def bulk_answers(url, params, headers):
    names = {"arxiv/arxiv/pdf/2401/2401.00001v": ["2401.00001v1.pdf", "2401.00001v2.pdf"],
             "arxiv/cond-mat/pdf/0101/0101001v": ["0101001v1.pdf"]}
    prefix = params.get("prefix", "")
    folder = prefix.rsplit("/", 1)[0]
    return FakeResponse(200, json_data={"items": [{"name": f"{folder}/{n}"} for n in names.get(prefix, [])]})


class ArxivBulkTests(unittest.TestCase):
    def test_where_a_paper_is_in_the_bulk_copy(self):
        self.assertEqual(arxiv_bulk_prefix("2401.00001v3"), "arxiv/arxiv/pdf/2401/2401.00001v")
        self.assertEqual(arxiv_bulk_prefix("cond-mat/0101001"), "arxiv/cond-mat/pdf/0101/0101001v")
        self.assertEqual(arxiv_bulk_prefix("math.AG/0101001"), "arxiv/math/pdf/0101/0101001v")
        self.assertEqual(arxiv_bulk_prefix("not an id"), "")

    def test_an_arxiv_pdf_is_first_taken_from_the_bulk_copy_newest_version(self):
        session = FakeSession([("storage.googleapis.com/storage/v1", bulk_answers)])
        resolver = Resolver(client_for(session), ["arxiv"])
        options = list(resolver.options(candidate(key="arxiv:2401.00001", arxiv_id="2401.00001")))
        self.assertEqual([o.url for o in options],
                         ["https://storage.googleapis.com/arxiv-dataset/arxiv/arxiv/pdf/2401/2401.00001v2.pdf",
                          "https://arxiv.org/pdf/2401.00001"])
        self.assertEqual({(o.service, o.license) for o in options}, {("arxiv", "arxiv")})

    def test_a_paper_not_in_the_bulk_copy_yet_comes_from_arxiv_org(self):
        session = FakeSession([("storage.googleapis.com/storage/v1", bulk_answers)])
        options = list(Resolver(client_for(session), ["arxiv"]).options(
            candidate(key="arxiv:2611.00009", arxiv_id="2611.00009")))
        self.assertEqual([o.url for o in options], ["https://arxiv.org/pdf/2611.00009"])


class ResumedSearchTests(unittest.TestCase):
    """A search stopped part-way (the window quit) and started again: its progress starts at what was finished."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.session = FakeSession([("api.openalex.org/works", FakeResponse(200, json_data={"results": [], "meta": {}})),
                                    ("export.arxiv.org", FakeResponse(200, body="<feed xmlns='http://www.w3.org/2005/Atom'></feed>"))])
        self.job = Job(search=SearchConfig(queries=["a", "b", "c", "d"], sources=["openalex", "arxiv"], abstract_sources=[]),
                       screen=ScreenConfig(topic_words=["garnet"], property_words=["activation energy"]),
                       fetch=FetchConfig(folder=os.path.join(self.root, "papers")))
        self.harvest = Harvest(self.job, os.path.join(self.root, "out"), client=client_for(self.session))
        self.addCleanup(self.harvest.ledger.close)

    def test_the_progress_starts_at_the_searches_already_finished(self):
        s = self.job.search
        for query in ("a", "b", "c", "d"):  # the earlier run finished OpenAlex and half of arXiv
            self.harvest.ledger.mark_searched(self.harvest._search_key("openalex", query), s.max_per_query)
        for query in ("a", "b"):
            self.harvest.ledger.mark_searched(self.harvest._search_key("arxiv", query), s.max_per_query)
        self.assertEqual(self.harvest.searches_planned(), (6, 8))
        seen = []
        self.harvest.on_progress = lambda phase, done, total, detail, new: seen.append((done, total)) if phase == "keywords" else None
        self.harvest._search_all(refresh=False)
        self.assertEqual(seen[0], (6, 8))  # not 0 %: 75 % at once
        self.assertEqual([done for done, _ in seen], sorted(done for done, _ in seen))  # it never goes back
        self.assertEqual(seen[-1], (8, 8))
        asked = [call for call in self.session.calls if "arxiv" in call[0]]
        self.assertEqual(len(asked), 2)  # only "c" and "d" of arXiv were asked; nothing of OpenAlex
        self.assertFalse([call for call in self.session.calls if "openalex" in call[0]])

    def test_with_refresh_everything_is_asked_and_counted_from_zero(self):
        for query in ("a", "b", "c", "d"):
            self.harvest.ledger.mark_searched(self.harvest._search_key("openalex", query), self.job.search.max_per_query)
        seen = []
        self.harvest.on_progress = lambda phase, done, total, detail, new: seen.append(done) if phase == "keywords" else None
        self.harvest._search_all(refresh=True)
        self.assertEqual((seen[0], seen[-1]), (1, 8))


class UpdateAllTests(unittest.TestCase):
    def test_update_all_is_a_switch(self):
        self.assertTrue(cli.parse_args(["update", "--all", "--yes"]).all)
        self.assertFalse(cli.parse_args(["update"]).all)


if __name__ == "__main__":
    unittest.main()
