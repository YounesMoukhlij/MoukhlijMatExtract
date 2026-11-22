# WebScraping/tests/test_snowball.py
"""Citation snowballing: the papers kept so far give the papers they cite (backward) and the papers citing them
(forward), through OpenAlex; what is new goes into the ledger and is screened like the rest. No network."""

import os
import shutil
import tempfile
import unittest

from WebScraping.tests.test_web import FakeResponse, FakeSession, candidate, client_for  # also: offline, sys.path
from WebScraping.averageScrap.harvest import Harvest
from WebScraping.averageScrap.job import FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from WebScraping.averageScrap.ledger import NEW, SCREENED
from WebScraping.averageScrap.sources.openalex import OpenAlex


def work(n: int, title: str, year: int = 2021, refs=()):
    return {"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.1000/w{n}", "title": title,
            "publication_year": year, "type": "article", "open_access": {"is_oa": True, "oa_status": "gold"},
            "best_oa_location": {"pdf_url": f"https://repo.example.org/w{n}.pdf"},
            "referenced_works": [f"https://openalex.org/W{r}" for r in refs]}


SEED = work(1, "Garnet solid electrolyte Li7La3Zr2O12", refs=(2, 3))
CITED = [work(2, "Ta-doped garnet solid electrolyte: activation energy of lithium conduction"),
         work(3, "Graphite anode for sodium batteries")]
CITING = [work(4, "Ga-doped garnet solid electrolyte with low activation energy")]


def openalex_answers(url, params, headers):
    wanted = params.get("filter", "")
    if wanted.startswith("cites:W1"):
        return FakeResponse(200, json_data={"results": CITING, "meta": {"next_cursor": None}})
    if wanted.startswith("openalex:W1") and params.get("select") == "id,referenced_works":
        return FakeResponse(200, json_data={"results": [SEED]})
    if wanted.startswith("openalex:W2|W3"):
        return FakeResponse(200, json_data={"results": CITED})
    return FakeResponse(200, json_data={"results": []})


class OpenAlexSnowballTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession([("api.openalex.org/works", openalex_answers)])
        self.source = OpenAlex(client_for(self.session))

    def test_the_references_of_a_paper_are_its_cited_works_kept_to_the_job(self):
        found = list(self.source.references(["W1"], years=(2015, 2026), include_preprints=False))
        self.assertEqual([(seed, c.doi) for seed, c in found], [("W1", "10.1000/w2"), ("W1", "10.1000/w3")])
        self.assertEqual(found[0][1].found_by, ["snowball: cited by W1"])
        asked = self.session.calls[-1][1]["filter"]
        self.assertIn("openalex:W2|W3", asked)
        self.assertIn("type:article|review", asked)
        self.assertNotIn("preprint", asked)
        self.assertIn("from_publication_date:2015-01-01", asked)

    def test_the_papers_citing_a_paper_the_most_cited_first(self):
        found = list(self.source.citing("W1", years=None, limit=50))
        self.assertEqual([c.doi for c in found], ["10.1000/w4"])
        self.assertEqual(found[0].found_by, ["snowball: cites W1"])
        params = self.session.calls[-1][1]
        self.assertEqual((params["sort"], params["per-page"]), ("cited_by_count:desc", 50))


class HarvestSnowballTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.session = FakeSession([("api.openalex.org/works", openalex_answers)])
        self.job = Job(search=SearchConfig(queries=["garnet"], sources=["openalex"], abstract_sources=[], snowball=True),
                       screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"]),
                       fetch=FetchConfig(folder=os.path.join(self.root, "papers")))
        self.harvest = Harvest(self.job, os.path.join(self.root, "out"), client=client_for(self.session))
        self.addCleanup(self.harvest.ledger.close)
        self.harvest.ledger.add(candidate(key="10.1000/w1", doi="10.1000/w1", openalex_id="W1"))
        self.harvest.ledger.update("10.1000/w1", decision="yes", status=SCREENED)
        self.harvest.ledger.add(candidate(key="10.1000/no", doi="10.1000/no", openalex_id="W9"))
        self.harvest.ledger.update("10.1000/no", decision="no", status=SCREENED)

    def test_the_kept_papers_bring_their_neighbours_which_are_screened_like_the_rest(self):
        self.assertEqual(self.harvest.snowball(), 3)                      # 2 cited, 1 citing
        self.assertFalse(any("W9" in str(params) for _, params, _ in self.session.calls))  # a rejected paper is no seed
        new = {c.doi: c for c in self.harvest.ledger.all(NEW)}
        self.assertEqual(sorted(new), ["10.1000/w2", "10.1000/w3", "10.1000/w4"])
        self.harvest.screen()
        decided = {doi: self.harvest.ledger.get(doi).decision for doi in new}
        self.assertEqual(decided, {"10.1000/w2": "yes", "10.1000/w3": "no", "10.1000/w4": "yes"})

    def test_a_paper_already_snowballed_is_not_asked_again_unless_refreshed(self):
        self.harvest.snowball()
        asked = len(self.session.calls)
        self.assertEqual(self.harvest.snowball(), 0)
        self.assertEqual(len(self.session.calls), asked)
        self.harvest.snowball(refresh=True)
        self.assertGreater(len(self.session.calls), asked)

    def test_the_search_snowballs_only_when_the_job_says_so(self):
        self.assertEqual(self.harvest.discover(), 3)
        self.job.search.snowball = False
        other = Harvest(self.job, os.path.join(self.root, "out2"), client=client_for(FakeSession(
            [("api.openalex.org/works", openalex_answers)])))
        self.addCleanup(other.ledger.close)
        other.ledger.add(candidate(key="10.1000/w1", doi="10.1000/w1", openalex_id="W1"))
        other.ledger.update("10.1000/w1", decision="yes", status=SCREENED)
        self.assertEqual(other.discover(), 0)

    def test_the_job_file_keeps_the_setting(self):
        path = os.path.join(self.root, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump_job(self.job))
        job = load_job(path)
        self.assertEqual((job.search.snowball, job.search.snowball_citing), (True, 100))


class CommandTests(unittest.TestCase):
    def test_snowball_turns_it_on_for_one_run(self):
        from unittest import mock
        from WebScraping.averageScrap import cli
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump_job(Job(search=SearchConfig(queries=["garnet"], sources=["openalex"]),
                                 fetch=FetchConfig(folder=os.path.join(root, "papers")))))
        seen = []
        with mock.patch.object(cli, "_run_stages", side_effect=lambda args, job, harvest, control: (
                seen.append(job.search.snowball), harvest.ledger.close(), 0)[-1]):
            for extra in ([], ["--snowball"]):
                args = cli.parse_args(["run", "--job", path, "--output", os.path.join(root, "out"), *extra])
                self.assertEqual(cli.run_web(args), 0)
        self.assertEqual(seen, [False, True])


if __name__ == "__main__":
    unittest.main()
