# tests/test_web.py
"""Offline tests for the web project (Project 2) and the shared changes it needed.

Every network call is answered by a fake session, so these run anywhere, instantly, and never touch a
real service. Run them with:  python -m unittest discover -s tests -v   (or: pytest tests)
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pymupdf
import requests

from web import screening
from web.elsevier import Elsevier
from web.fetch import Downloader, check_pdf
from web.harvest import Harvest
from web.http import Disallowed, HttpError, PoliteClient
from web.doctor import check as check_setup
from web.ids import aps_doi, arxiv_id, candidate_key, file_stem, normalize_doi
from web.job import (ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job, read_env,
                     save_env)
from web.ledger import (APPROVED, CLOSED, DOWNLOADED, FAILED, NEW, REJECTED, SCREENED, Candidate, Ledger)
from web.resolve import FetchOption, Resolver
from web.sidecar import read_provenance
from web.sources.arxiv import ArXiv, build_query, parse_feed
from web.sources.openalex import OpenAlex, abstract_from_index, candidate_from_work
from web.wiley import Wiley


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, json_data=None):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode("utf-8", "replace")
        self.headers = {"Content-Type": "application/octet-stream", **(headers or {})}
        self._json = json_data

    def json(self):
        return self._json if self._json is not None else json.loads(self.text)

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        pass


class FakeSession:
    """Answers GETs from (url fragment, answer) routes, first match wins; an answer is a response, a
    function of (url, params, headers) or a list of responses handed out one by one."""

    def __init__(self, routes=None):
        self.headers = {}
        self.routes = list(routes or [])
        self.calls = []

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        self.calls.append((url, params, headers))
        for fragment, answer in self.routes:
            if fragment in url:
                if callable(answer):
                    return answer(url, params, headers)
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        return FakeResponse(404, b"not found")

    def hits(self, fragment):
        return sum(1 for url, _, _ in self.calls if fragment in url)


def client_for(session, contact=""):
    return PoliteClient(contact=contact, session=session, sleep=lambda seconds: None)


def make_pdf(title="Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte", pages=3) -> bytes:
    document = pymupdf.open()
    filler = ("The activation energy was obtained from an Arrhenius fit of impedance spectra measured between "
              "room temperature and one hundred degrees. ") * 8
    for index in range(pages):
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), (title + "\n\n" if index == 0 else "") + filler, fontsize=10)
    return document.tobytes()


def candidate(**values) -> Candidate:
    defaults = dict(key="10.1000/test", doi="10.1000/test", title="Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte",
                    abstract="We measure the ionic conductivity and activation energy of a solid electrolyte.", year=2022,
                    access="open", oa_status="gold")
    defaults.update(values)
    return Candidate(**defaults)


WORK = {
    "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1016/J.SSI.2020.115234",
    "title": "Li6PS5Cl ionic conductivity", "publication_year": 2020, "type": "article",
    "abstract_inverted_index": {"Argyrodite": [0], "electrolytes": [1], "show": [2], "high": [3], "ionic": [4],
                                "conductivity": [5]},
    "is_retracted": False, "cited_by_count": 12,
    "open_access": {"is_oa": True, "oa_status": "green"},
    "best_oa_location": {"is_oa": True, "pdf_url": "https://repo.example.org/paper.pdf",
                         "landing_page_url": "https://repo.example.org/paper", "license": "cc-by"},
    "primary_location": {"source": {"display_name": "Solid State Ionics", "host_organization_name": "Elsevier BV"}},
    "locations": [{"is_oa": True, "pdf_url": "https://arxiv.org/pdf/2001.00001",
                   "landing_page_url": "https://arxiv.org/abs/2001.00001"}, {"is_oa": False, "pdf_url": None}],
    "authorships": [{"author": {"display_name": "A. Author"}}],
}

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2411.06804v2</id>
    <published>2024-11-11T10:00:00Z</published>
    <title>Predicting ionic conductivity
      in solids</title>
    <summary>  An abstract about  conductivity. </summary>
    <author><name>A. One</name></author><author><name>B. Two</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2411.06804v2" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2001.00002v1</id>
    <published>2020-01-02T10:00:00Z</published>
    <title>A published one</title>
    <summary>Abstract.</summary>
    <author><name>C. Three</name></author>
    <arxiv:doi>10.1038/s41467-020-0001-x</arxiv:doi>
    <arxiv:journal_ref>Nat. Commun. 11, 1 (2020)</arxiv:journal_ref>
  </entry>
</feed>"""


# ----------------------------------------------------------------------
# Identifiers, job file, HTTP
# ----------------------------------------------------------------------
class IdsTests(unittest.TestCase):
    def test_doi(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1016/J.SSI.2020.115234."), "10.1016/j.ssi.2020.115234")
        self.assertEqual(normalize_doi("doi:10.1021/acs.chemmater.8b03272)"), "10.1021/acs.chemmater.8b03272")
        self.assertEqual(normalize_doi("10.1016/S0022-2860(96)01234-5"), "10.1016/s0022-2860(96)01234-5")
        self.assertEqual(normalize_doi("no identifier here"), "")

    def test_arxiv(self):
        self.assertEqual(arxiv_id("https://arxiv.org/abs/2411.06804v2"), "2411.06804")
        self.assertEqual(arxiv_id("arXiv:2411.06804"), "2411.06804")
        self.assertEqual(arxiv_id("https://arxiv.org/pdf/2411.06804v2.pdf"), "2411.06804")
        self.assertEqual(arxiv_id("10.48550/arXiv.2411.06804"), "2411.06804")
        self.assertEqual(arxiv_id("cond-mat/0501234"), "cond-mat/0501234")
        self.assertEqual(arxiv_id("10.1016/j.ssi.2020.115234"), "")  # a DOI is never searched for an arXiv id

    def test_key_is_the_same_whichever_source_found_the_paper(self):
        self.assertEqual(candidate_key(doi="10.48550/arXiv.2411.06804"), "arxiv:2411.06804")
        self.assertEqual(candidate_key(arxiv="2411.06804"), "arxiv:2411.06804")
        self.assertEqual(candidate_key(doi="10.1038/X", arxiv="2411.06804"), "10.1038/x")  # the journal DOI wins
        self.assertTrue(candidate_key(title="A Title: with Punctuation!").startswith("title:"))
        self.assertEqual(candidate_key(title="A Title"), candidate_key(title="a  title"))
        self.assertEqual(candidate_key(), "")

    def test_an_aps_doi_in_the_journals_own_spelling(self):
        self.assertEqual(aps_doi("10.1103/physrevb.99.094106"), "10.1103/PhysRevB.99.094106")
        self.assertEqual(aps_doi("10.1103/physrevresearch.6.043210"), "10.1103/PhysRevResearch.6.043210")
        self.assertEqual(aps_doi("10.1103/prxenergy.2.013005"), "10.1103/PRXEnergy.2.013005")
        self.assertEqual(aps_doi("10.1103/lx5w-x6wl"), "10.1103/lx5w-x6wl")  # the newer kind names no journal

    def test_file_stem(self):
        self.assertEqual(file_stem("10.1016/j.ssi.2020.115234"), "10.1016_j.ssi.2020.115234")
        self.assertEqual(file_stem("arxiv:2411.06804"), "arxiv_2411.06804")
        self.assertLessEqual(len(file_stem("10.1/" + "x" * 400)), 140)


class JobTests(unittest.TestCase):
    def write(self, text):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_defaults_and_values(self):
        job = load_job(self.write("search:\n  queries: [solid electrolyte]\n  years: [2015, 2026]\n"
                                  "extract:\n  properties: [Activation_Energy]\n"))
        self.assertEqual(job.search.years, (2015, 2026))
        self.assertTrue(job.screen.review)
        self.assertEqual(job.fetch.folder, os.path.join("papers", "web"))
        self.assertEqual(job.extract.properties, ["Activation_Energy"])
        # Every source is tried unless the job names its own; closed papers are not proposed unless it says so.
        self.assertEqual(job.fetch.sources, ["elsevier", "wiley", "aps", "openalex", "unpaywall", "arxiv", "pmc", "osti",
                                             "hal", "semanticscholar", "openaire"])
        self.assertFalse(job.screen.propose_closed)

    def test_the_sources_and_the_closed_papers_are_the_jobs_choice(self):
        job = load_job(self.write("search: {queries: [a]}\nscreen: {propose_closed: true}\nfetch: {sources: [arxiv, osti, hal]}\n"))
        self.assertEqual((job.fetch.sources, job.screen.propose_closed), (["arxiv", "osti", "hal"], True))
        with self.assertRaisesRegex(ValueError, "fetch.sources"):
            load_job(self.write("search: {queries: [a]}\nfetch: {sources: [scihub]}\n"))  # only the sources above exist

    def test_a_misspelled_key_is_an_error_not_ignored(self):
        with self.assertRaisesRegex(ValueError, "min_score"):
            load_job(self.write("search: {queries: [a]}\nscreen: {min_scor: 3}\n"))

    def test_other_mistakes(self):
        with self.assertRaisesRegex(ValueError, "at least one query"):
            load_job(self.write("name: x\n"))
        with self.assertRaisesRegex(ValueError, "Activation_Energy"):
            load_job(self.write("search: {queries: [a]}\nextract: {properties: [Activation_Energi]}\n"))
        with self.assertRaisesRegex(ValueError, "search.sources"):
            load_job(self.write("search: {queries: [a], sources: [google]}\n"))

    def test_a_job_written_out_is_read_back_as_the_same_job(self):
        job = Job(name="sse", contact_email="",
                  search=SearchConfig(queries=["solid electrolyte: ionic conductivity", "argyrodite"], years=(2014, 2026),
                                      sources=["openalex"], max_per_query=50, include_preprints=False),
                  screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"],
                                      exclude_words=["supercapacitor"], min_score=3, propose_closed=True),
                  fetch=FetchConfig(folder="papers/web", sources=["arxiv", "osti"], workers=2, max_pdf_mb=40),
                  extract=ExtractConfig(properties=["Activation_Energy"], require_material=True))
        self.assertEqual(load_job(self.write(dump_job(job))), job)
        no_years = Job(search=SearchConfig(queries=["a"]))
        self.assertEqual(load_job(self.write(dump_job(no_years))), no_years)

    def test_settings_are_saved_into_the_env_file_and_the_environment(self):
        path = self.write("# my keys\nELSEVIER_API_KEY=old\nOTHER=kept\n").replace("job.yaml", ".env")
        os.replace(path.replace(".env", "job.yaml"), path)
        with mock.patch.dict(os.environ, {"AUTOMATEXTRACT_EMAIL": "was@example.org"}, clear=True):
            save_env({"ELSEVIER_API_KEY": "new-key", "WILEY_TDM_TOKEN": " token ", "AUTOMATEXTRACT_EMAIL": ""}, path)
            self.assertEqual((os.environ["ELSEVIER_API_KEY"], os.environ["WILEY_TDM_TOKEN"]), ("new-key", "token"))
            self.assertNotIn("AUTOMATEXTRACT_EMAIL", os.environ)  # emptied: unset for this run too
        text = Path(path).read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[:3], ["# my keys", "ELSEVIER_API_KEY=new-key", "OTHER=kept"])
        self.assertEqual(read_env(path), {"ELSEVIER_API_KEY": "new-key", "OTHER": "kept", "WILEY_TDM_TOKEN": "token",
                                          "AUTOMATEXTRACT_EMAIL": ""})
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)  # the keys are the owner's alone
        with self.assertRaisesRegex(ValueError, "one line"):
            save_env({"ELSEVIER_API_KEY": "two\nlines"}, path)

    def test_email_comes_from_the_job_or_the_environment_and_nowhere_else(self):
        with mock.patch.dict(os.environ, {"AUTOMATEXTRACT_EMAIL": "env@example.org"}):
            self.assertEqual(Job(contact_email="job@example.org").email(), "job@example.org")
            self.assertEqual(Job().email(), "env@example.org")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Job().email(), "")


class HttpTests(unittest.TestCase):
    def test_a_503_is_retried(self):
        slept = []
        session = FakeSession([("api.example.org", [FakeResponse(503), FakeResponse(200, json_data={"ok": True})])])
        client = PoliteClient(session=session, sleep=slept.append)
        self.assertEqual(client.get_json("https://api.example.org/x"), {"ok": True})
        self.assertEqual(session.hits("api.example.org"), 2)
        self.assertTrue(any(s >= 2 for s in slept))

    def test_an_error_status_that_stays_is_reported(self):
        client = client_for(FakeSession([("api.example.org", FakeResponse(404, "nothing here"))]))
        with self.assertRaises(HttpError) as raised:
            client.get_json("https://api.example.org/x")
        self.assertEqual(raised.exception.status, 404)

    def test_no_retry_statuses_come_straight_back(self):
        session = FakeSession([("api.example.org", FakeResponse(429))])
        self.assertEqual(client_for(session).get("https://api.example.org/x", no_retry={429}).status_code, 429)
        self.assertEqual(session.hits("api.example.org"), 1)

    def test_requests_to_one_host_are_spaced(self):
        class Clock:
            now = 100.0
        slept = []

        def sleep(seconds):
            slept.append(round(seconds, 3))
            Clock.now += seconds
        client = PoliteClient(session=FakeSession([("api.openalex.org", FakeResponse(200, "{}"))]), sleep=sleep,
                              clock=lambda: Clock.now)
        for _ in range(3):
            client.get("https://api.openalex.org/works")
        self.assertEqual(slept, [0.2, 0.2])  # nothing before the first request, then the host's interval

    def test_who_is_asking(self):
        plain, polite = FakeSession(), FakeSession()
        client_for(plain)
        client_for(polite, contact="me@example.org")
        self.assertEqual(plain.headers["User-Agent"], "AutoMatExtract/0.1")
        self.assertEqual(polite.headers["User-Agent"], "AutoMatExtract/0.1 (mailto:me@example.org)")

    def test_robots_txt_is_obeyed_for_files_and_its_crawl_delay_slows_the_host(self):
        robots = "User-agent: *\nDisallow: /private\nCrawl-delay: 7\n"
        session = FakeSession([("robots.txt", FakeResponse(200, robots)), ("example.org", FakeResponse(200, b"x"))])
        client = client_for(session)
        with self.assertRaises(Disallowed):
            client.get("https://example.org/private/paper.pdf", api=False)
        self.assertEqual(client.get("https://example.org/open/paper.pdf", api=False).status_code, 200)
        self.assertEqual(client._crawl_delay["example.org"], 7.0)
        # an API call is under its own terms: robots.txt is not consulted
        self.assertEqual(client.get("https://example.org/private/api").status_code, 200)

    def test_robots_rules_for_a_missing_or_broken_robots_txt(self):
        self.assertTrue(client_for(FakeSession([("robots.txt", FakeResponse(404))])).allowed("https://a.org/x.pdf"))
        self.assertFalse(client_for(FakeSession([("robots.txt", FakeResponse(503))])).allowed("https://a.org/x.pdf"))


# ----------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------
class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.ledger = Ledger(os.path.join(self.folder, "ledger.sqlite"))
        self.addCleanup(self.ledger.close)

    def test_two_sources_one_paper(self):
        self.assertTrue(self.ledger.add(candidate(oa_urls=["https://a/x.pdf"], found_by=["openalex: q"], journal="")))
        self.ledger.update("10.1000/test", status=APPROVED, decision="yes", score=4.0)
        self.assertFalse(self.ledger.add(candidate(oa_urls=["https://b/y.pdf"], found_by=["arxiv: q"], journal="SSI")))
        merged = self.ledger.get("10.1000/test")
        self.assertEqual(merged.oa_urls, ["https://a/x.pdf", "https://b/y.pdf"])
        self.assertEqual(merged.found_by, ["openalex: q", "arxiv: q"])
        self.assertEqual(merged.journal, "SSI")  # an empty field is filled by the second source
        self.assertEqual((merged.status, merged.decision, merged.score), (APPROVED, "yes", 4.0))  # state untouched

    def test_counts_and_order(self):
        self.ledger.add(candidate(key="a", doi="a"))
        self.ledger.add(candidate(key="b", doi="b"))
        self.ledger.update("a", status=SCREENED, score=1.0)
        self.ledger.update("b", status=SCREENED, score=5.0)
        self.assertEqual([c.key for c in self.ledger.all(SCREENED)], ["b", "a"])
        self.assertEqual(self.ledger.counts(), {SCREENED: 2})

    def test_the_review_list_round_trip(self):
        for key, score in (("a", 4.0), ("b", 2.0), ("c", 3.0)):
            self.ledger.add(candidate(key=key, doi=key, title=f"Paper {key}"))
            self.ledger.update(key, status=SCREENED, score=score, decision="yes" if score >= 3 else "no")
        path = os.path.join(self.folder, "candidates.csv")
        self.assertEqual(self.ledger.write_review(path), 3)
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[0].startswith("decision,score,access"))
        # the person flips one decision and leaves another empty; their spreadsheet saves with ';'
        edited = "\n".join(line.replace(",", ";") for line in lines)
        edited = edited.replace("yes;4;", "no;4;").replace("no;2;", ";2;")
        with open(path, "w", encoding="utf-8") as f:
            f.write(edited)
        outcome = self.ledger.apply_decisions(path)
        self.assertEqual(outcome, {"approved": 1, "rejected": 1, "waiting": 1, "unreadable": 0})
        self.assertEqual((self.ledger.get("a").status, self.ledger.get("c").status, self.ledger.get("b").status),
                         (REJECTED, APPROVED, SCREENED))

    def test_decisions_can_be_read_without_being_made_final(self):
        for key in ("10.1/a", "10.1/b", "10.1/c"):
            self.ledger.add(candidate(key=key, doi=key, status=SCREENED, decision="yes"))
        self.ledger.update("10.1/c", status=DOWNLOADED)
        path = os.path.join(self.folder, "candidates.csv")
        self.ledger.write_review(path)
        text = Path(path).read_text(encoding="utf-8-sig").replace("yes,", "no,")  # a person said no to all three
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertEqual(self.ledger.take_decisions(path), 2)
        self.assertEqual([(self.ledger.get(k).decision, self.ledger.get(k).status) for k in ("10.1/a", "10.1/b", "10.1/c")],
                         [("no", SCREENED), ("no", SCREENED), ("yes", DOWNLOADED)])  # nothing rejected yet, the fetched one untouched
        self.assertEqual(self.ledger.take_decisions(path), 0)

    def test_decisions_do_not_change_a_paper_already_fetched(self):
        self.ledger.add(candidate())
        self.ledger.update("10.1000/test", status=DOWNLOADED, decision="yes")
        path = os.path.join(self.folder, "candidates.csv")
        self.ledger.write_review(path)
        text = Path(path).read_text(encoding="utf-8-sig").replace("yes,", "no,", 1)
        Path(path).write_text(text, encoding="utf-8")
        self.assertEqual(self.ledger.apply_decisions(path)["rejected"], 0)
        self.assertEqual(self.ledger.get("10.1000/test").status, DOWNLOADED)


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------
class OpenAlexTests(unittest.TestCase):
    def test_a_work_becomes_a_candidate(self):
        c = candidate_from_work(WORK, "openalex: q")
        self.assertEqual(c.key, "10.1016/j.ssi.2020.115234")
        self.assertEqual(c.abstract, "Argyrodite electrolytes show high ionic conductivity")
        self.assertEqual(c.arxiv_id, "2001.00001")  # found among the locations
        self.assertEqual(c.oa_urls, ["https://repo.example.org/paper.pdf", "https://arxiv.org/pdf/2001.00001"])
        self.assertEqual((c.journal, c.publisher, c.year, c.oa_status, c.license), ("Solid State Ionics", "Elsevier BV", 2020, "green", "cc-by"))
        self.assertEqual(c.authors, ["A. Author"])
        self.assertFalse(c.is_preprint)

    def test_an_arxiv_doi_makes_an_arxiv_key(self):
        c = candidate_from_work({**WORK, "doi": "https://doi.org/10.48550/arXiv.2411.06804", "type": "preprint"}, "q")
        self.assertEqual((c.key, c.arxiv_id, c.is_preprint), ("arxiv:2411.06804", "2411.06804", True))

    def test_a_work_with_nothing_to_identify_it_is_dropped(self):
        self.assertIsNone(candidate_from_work({"id": "https://openalex.org/W1"}, "q"))

    def test_abstract_order(self):
        self.assertEqual(abstract_from_index({"b": [1], "a": [0, 2]}), "a b a")
        self.assertEqual(abstract_from_index(None), "")

    def test_search_follows_the_cursor_and_stops_at_the_limit(self):
        def page(url, params, headers):
            cursor = params["cursor"]
            work = {**WORK, "doi": f"https://doi.org/10.1000/p{cursor}"}
            return FakeResponse(200, json_data={"results": [work], "meta": {"next_cursor": "second" if cursor == "*" else None}})
        session = FakeSession([("api.openalex.org/works", page)])
        found = list(OpenAlex(client_for(session), contact="x@example.org").search("solid electrolyte", (2015, 2026), limit=10))
        self.assertEqual([c.key for c in found], ["10.1000/p*", "10.1000/psecond"])
        first = session.calls[0][1]
        self.assertIn("from_publication_date:2015-01-01", first["filter"])
        self.assertIn("type:article|review|preprint", first["filter"])
        self.assertEqual(first["mailto"], "x@example.org")
        self.assertEqual(len(list(OpenAlex(client_for(session)).search("q", limit=1))), 1)

    def test_lookup_of_an_unknown_doi(self):
        self.assertIsNone(OpenAlex(client_for(FakeSession([("api.openalex.org", FakeResponse(404, "{}"))]))).lookup("10.1/none"))


class ArXivTests(unittest.TestCase):
    def test_feed(self):
        first, second = parse_feed(ATOM, "arxiv: q")
        self.assertEqual((first.key, first.title, first.year, first.is_preprint), ("arxiv:2411.06804", "Predicting ionic conductivity in solids", 2024, True))
        self.assertEqual(first.abstract, "An abstract about conductivity.")
        self.assertEqual(first.oa_urls, ["https://arxiv.org/pdf/2411.06804"])
        self.assertEqual(first.authors, ["A. One", "B. Two"])
        # a paper with a journal DOI is keyed by it, so it merges with the OpenAlex record of the journal version
        self.assertEqual((second.key, second.arxiv_id, second.is_preprint, second.journal), ("10.1038/s41467-020-0001-x", "2001.00002", False, "Nat. Commun. 11, 1 (2020)"))

    def test_query(self):
        self.assertEqual(build_query('argyrodite "ionic conductivity"', ["cond-mat.mtrl-sci"], (2015, 2026)),
                         'all:argyrodite AND all:"ionic conductivity" AND (cat:cond-mat.mtrl-sci) '
                         'AND submittedDate:[201501010000 TO 202612312359]')

    def test_search_pages(self):
        session = FakeSession([("export.arxiv.org", FakeResponse(200, ATOM))])
        found = list(ArXiv(client_for(session)).search("conductivity", limit=100))
        self.assertEqual(len(found), 2)
        self.assertEqual(session.hits("export.arxiv.org"), 1)  # a short page ends the search


# ----------------------------------------------------------------------
# Screening
# ----------------------------------------------------------------------
class ScreeningTests(unittest.TestCase):
    cfg = ScreenConfig(topic_words=["solid electrolyte", "garnet"], property_words=["activation energy", "ionic conductivity"],
                       exclude_words=["supercapacitor"], min_score=2)

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.ledger = Ledger(os.path.join(self.folder, "ledger.sqlite"))
        self.addCleanup(self.ledger.close)

    def screen_one(self, **values):
        self.ledger.add(candidate(**values))
        screening.screen(self.ledger, self.cfg)
        return self.ledger.get(values.get("key", "10.1000/test"))

    def test_a_good_paper_is_proposed_with_its_reasons(self):
        c = self.screen_one(title="Garnet solid electrolytes", abstract="We report the ionic conductivity.")
        self.assertEqual((c.decision, c.status, c.score), ("yes", SCREENED, 2 + 2 + 1))
        self.assertIn("solid electrolyte (title)", c.why)
        self.assertIn("ionic conductivity (abstract)", c.why)

    def test_plurals_and_hyphens(self):
        c = self.screen_one(title="Solid-electrolytes", abstract="Their ionic conductivities are measured.")
        self.assertEqual((c.decision, c.score), ("yes", 3))

    def test_both_a_topic_word_and_a_property_word_are_needed(self):
        self.assertEqual(self.screen_one(title="Garnet solid electrolytes", abstract="Nothing else.").decision, "no")

    def test_an_excluded_word_costs_points(self):
        c = self.screen_one(title="Solid electrolyte for a supercapacitor", abstract="ionic conductivity")
        self.assertEqual((c.decision, c.score), ("no", 2 + 1 - 3))  # topic in the title, property in the abstract, one excluded word
        self.assertIn("excluded: supercapacitor (title)", c.why)

    def test_retracted_and_closed_papers_are_not_proposed(self):
        retracted = self.screen_one(key="r", doi="r", title="Garnet solid electrolytes ionic conductivity", is_retracted=True)
        self.assertEqual(retracted.decision, "no")
        self.assertIn("RETRACTED", retracted.flags)
        closed = self.screen_one(key="c", doi="c", title="Garnet solid electrolytes ionic conductivity", oa_status="closed", access="")
        self.assertEqual((closed.decision, closed.access), ("no", "closed"))
        self.assertIn("no-open-copy-known", closed.flags)

    def test_a_closed_paper_is_proposed_when_the_job_wants_the_repositories_asked(self):
        self.ledger.add(candidate(title="Garnet solid electrolytes ionic conductivity", oa_status="closed", access=""))
        screening.screen(self.ledger, ScreenConfig(**{**vars(self.cfg), "propose_closed": True}))
        c = self.ledger.get("10.1000/test")
        self.assertEqual((c.decision, c.access), ("yes", "closed"))
        self.assertIn("no-open-copy-known", c.flags)  # ... and says so in the review list

    def test_a_wiley_token_makes_a_closed_wiley_paper_fetchable(self):
        self.ledger.add(candidate(doi="10.1002/aenm.1", key="10.1002/aenm.1", title="Garnet solid electrolytes ionic conductivity",
                                  oa_status="closed", access=""))
        screening.screen(self.ledger, self.cfg, wiley_ok=True)
        c = self.ledger.get("10.1002/aenm.1")
        self.assertEqual((c.access, c.decision), ("wiley", "yes"))

    def test_elsevier_makes_a_closed_paper_fetchable(self):
        self.ledger.add(candidate(doi="10.1016/j.ssi.1", key="10.1016/j.ssi.1", title="Garnet solid electrolytes ionic conductivity",
                                  oa_status="closed", access="", publisher="Elsevier BV"))
        screening.screen(self.ledger, self.cfg, elsevier_ok=True)
        c = self.ledger.get("10.1016/j.ssi.1")
        self.assertEqual((c.access, c.decision), ("elsevier", "yes"))

    def test_a_preprint_and_its_journal_version_are_one_paper(self):
        title = "Predicting the ionic conductivity of garnet solid electrolytes"
        self.ledger.add(candidate(key="arxiv:1", doi="", arxiv_id="1", title=title, is_preprint=True, oa_urls=["https://arxiv.org/pdf/1"]))
        self.ledger.add(candidate(key="10.1/journal", doi="10.1/journal", title=title, oa_urls=["https://x/y.pdf"]))
        screening.screen(self.ledger, self.cfg)
        self.assertEqual(self.ledger.get("10.1/journal").decision, "yes")
        loser = self.ledger.get("arxiv:1")
        self.assertEqual(loser.decision, "no")
        self.assertIn("duplicate-of:10.1/journal", loser.flags)

    def test_approve_makes_the_proposals_final(self):
        self.ledger.add(candidate(title="Garnet solid electrolytes ionic conductivity"))
        self.ledger.add(candidate(key="x", doi="x", title="Something else entirely", abstract="Graphite anodes."))
        screening.screen(self.ledger, self.cfg, approve=True)
        self.assertEqual(self.ledger.get("10.1000/test").status, APPROVED)
        self.assertEqual(self.ledger.get("x").status, REJECTED)

    def test_nothing_is_scored_twice(self):
        self.screen_one(title="Garnet solid electrolytes ionic conductivity")
        self.ledger.update("10.1000/test", decision="no", score=0.0)  # a person's edit
        screening.screen(self.ledger, self.cfg)
        self.assertEqual(self.ledger.get("10.1000/test").decision, "no")


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------
class PdfCheckTests(unittest.TestCase):
    def test_a_real_paper(self):
        check = check_pdf(make_pdf(), "Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte")
        self.assertTrue(check.ok, check.reason)
        self.assertEqual(check.pages, 3)

    def test_a_web_page_under_a_pdf_name(self):
        self.assertFalse(check_pdf(b"<!DOCTYPE html><html>Please log in to read this article</html>", "x").ok)

    def test_a_one_page_notice_is_not_an_article(self):
        notice = pymupdf.open()
        notice.new_page().insert_text((72, 72), "Access denied", fontsize=12)
        self.assertEqual(check_pdf(notice.tobytes(), "").reason, "too short to be an article")

    def test_another_document(self):
        check = check_pdf(make_pdf(title="Lithium plating on graphite anodes in fast charging"),
                          "Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte")
        self.assertFalse(check.ok)
        self.assertIn("title", check.reason)

    def test_a_scan_cannot_be_judged_and_is_accepted(self):
        scan = pymupdf.open()
        for _ in range(3):
            scan.new_page()
        self.assertTrue(check_pdf(scan.tobytes(), "Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte").ok)

    def test_a_title_too_short_to_judge(self):
        self.assertTrue(check_pdf(make_pdf(), "Li6PS5Cl").ok)


class StubResolver:
    def __init__(self, options):
        self._options = options

    def options(self, c):
        return iter(self._options)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.pdf = make_pdf()

    def downloader(self, routes, options):
        self.session = FakeSession(routes)
        return Downloader(self.folder, client_for(self.session), StubResolver(options), max_mb=5)

    def test_the_first_good_option_wins_and_leaves_a_file_and_a_sidecar(self):
        d = self.downloader([("repo.example.org/p.pdf", FakeResponse(200, self.pdf, {"Content-Type": "application/pdf"}))],
                            [FetchOption("openalex", "https://repo.example.org/p.pdf", license="cc-by")])
        outcome = d.fetch(candidate(authors=["A. Author"], journal="SSI", year=2022))
        self.assertEqual((outcome.status, outcome.file, outcome.service), (DOWNLOADED, "10.1000_test.pdf", "openalex"))
        self.assertTrue(Path(self.folder, "10.1000_test.pdf").read_bytes().startswith(b"%PDF"))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "10.1000_test.pdf.part")))
        sidecar = json.loads(Path(self.folder, "10.1000_test.json").read_text(encoding="utf-8"))
        self.assertEqual((sidecar["source_service"], sidecar["license"], sidecar["doi"], sidecar["pages"]), ("openalex", "cc-by", "10.1000/test", 3))
        self.assertEqual(len(sidecar["sha256"]), 64)

    def test_refusals_and_fake_pdfs_mean_next_option(self):
        d = self.downloader(
            [("paywall.example.org/p.pdf", FakeResponse(403)),
             ("html.example.org/p.pdf", FakeResponse(200, "<html>login</html>", {"Content-Type": "text/html"})),
             ("good.example.org/p.pdf", FakeResponse(200, self.pdf, {"Content-Type": "application/pdf"}))],
            [FetchOption("openalex", "https://paywall.example.org/p.pdf"), FetchOption("unpaywall", "https://html.example.org/p.pdf"),
             FetchOption("arxiv", "https://good.example.org/p.pdf")])
        outcome = d.fetch(candidate())
        self.assertEqual((outcome.status, outcome.service), (DOWNLOADED, "arxiv"))

    def test_a_landing_page_is_followed_to_the_pdf_it_declares(self):
        page = '<html><head><meta content="/files/p.pdf" name="citation_pdf_url"></head></html>'
        d = self.downloader([("pub.example.org/landing", FakeResponse(200, page, {"Content-Type": "text/html"})),
                             ("pub.example.org/files/p.pdf", FakeResponse(200, self.pdf, {"Content-Type": "application/pdf"}))],
                            [FetchOption("openalex", "https://pub.example.org/landing", landing=True)])
        self.assertEqual(d.fetch(candidate()).status, DOWNLOADED)

    def test_the_wrong_document_is_refused(self):
        d = self.downloader([("x.example.org/p.pdf", FakeResponse(200, make_pdf(title="Lithium plating on graphite anodes in fast charging"),
                                                            {"Content-Type": "application/pdf"}))],
                            [FetchOption("openalex", "https://x.example.org/p.pdf")])
        outcome = d.fetch(candidate())
        self.assertEqual(outcome.status, FAILED)
        self.assertIn("title", outcome.error)
        self.assertEqual(os.listdir(self.folder), [])

    def test_nothing_to_try_means_closed(self):
        self.assertEqual(self.downloader([], []).fetch(candidate()).status, CLOSED)

    def test_robots_txt_stops_a_file_download(self):
        d = self.downloader([("robots.txt", FakeResponse(200, "User-agent: *\nDisallow: /")),
                             ("x.example.org/p.pdf", FakeResponse(200, self.pdf))], [FetchOption("openalex", "https://x.example.org/p.pdf")])
        outcome = d.fetch(candidate())
        self.assertEqual(outcome.status, FAILED)
        self.assertIn("robots.txt", outcome.error)

    def test_a_rejected_elsevier_key_is_not_tried_again(self):
        elsevier = Elsevier("BAD-KEY")
        options = [FetchOption("elsevier", Elsevier.url("10.1016/j.a.1"), elsevier.headers("application/pdf"), api=True)]
        d = self.downloader([("api.elsevier.com", FakeResponse(401))], options)
        self.assertEqual(d.fetch(candidate()).status, FAILED)
        self.assertEqual(d.fetch(candidate(key="b", doi="b")).status, CLOSED)  # the service is off: nothing left to try
        self.assertEqual(self.session.hits("api.elsevier.com"), 1)

    def test_a_publisher_api_out_of_requests_is_not_asked_again(self):
        wiley = Wiley("TOKEN")
        options = [FetchOption("wiley", Wiley.url("10.1002/aenm.1"), wiley.headers(), api=True)]
        d = self.downloader([("api.wiley.com", FakeResponse(429))], options)
        self.assertEqual(d.fetch(candidate()).status, FAILED)
        self.assertEqual(d.fetch(candidate(key="b", doi="b")).status, CLOSED)
        self.assertEqual(self.session.hits("api.wiley.com"), 1)  # not retried, not asked again

    def test_a_file_served_as_plain_bytes_is_still_a_pdf(self):
        d = self.downloader([("pmc-oa-opendata", FakeResponse(200, self.pdf, {"Content-Type": "binary/octet-stream"}))],
                            [FetchOption("pmc", "https://pmc-oa-opendata.s3.amazonaws.com/PMC1.1/PMC1.1.pdf", license="cc-by")])
        outcome = d.fetch(candidate())
        self.assertEqual((outcome.status, outcome.service, outcome.license), (DOWNLOADED, "pmc", "cc-by"))

    def test_elsevier_answering_with_xml_is_reported_as_such(self):
        d = self.downloader([("api.elsevier.com", FakeResponse(200, "<full-text-retrieval-response/>", {"Content-Type": "text/xml"}))],
                            [FetchOption("elsevier", Elsevier.url("10.1016/j.a.1"), {"X-ELS-APIKey": "k"}, api=True)])
        self.assertIn("text/xml", d.fetch(candidate()).error)

    def test_a_file_over_the_size_limit_is_refused(self):
        d = self.downloader([("big.example.org/p.pdf", FakeResponse(200, b"%PDF-" + b"0" * (6 * 1024 * 1024)))],
                            [FetchOption("openalex", "https://big.example.org/p.pdf")])
        self.assertIn("larger than 5 MB", d.fetch(candidate()).error)


class ResolverTests(unittest.TestCase):
    def options(self, c, sources, contact="", elsevier=None, session=None):
        resolver = Resolver(client_for(session or FakeSession()), sources, contact, elsevier)
        return [(o.service, o.url) for o in resolver.options(c)]

    def test_the_order_is_the_jobs(self):
        c = candidate(oa_urls=["https://a/p.pdf"], arxiv_id="2001.00001", landing_url="https://a/landing")
        self.assertEqual(self.options(c, ["arxiv", "openalex"]),
                         [("arxiv", "https://arxiv.org/pdf/2001.00001"), ("openalex", "https://a/p.pdf"), ("openalex", "https://a/landing")])

    def test_elsevier_only_for_elsevier_papers_and_only_with_a_key(self):
        elsevier = Elsevier("KEY")
        self.assertEqual(self.options(candidate(doi="10.1016/j.ssi.2020.1"), ["elsevier"], elsevier=elsevier),
                         [("elsevier", "https://api.elsevier.com/content/article/doi/10.1016/j.ssi.2020.1")])
        self.assertEqual(self.options(candidate(doi="10.1038/s41467-1"), ["elsevier"], elsevier=elsevier), [])
        self.assertEqual(self.options(candidate(doi="10.1016/j.ssi.2020.1"), ["elsevier"]), [])

    def test_unpaywall_needs_a_contact_email(self):
        data = {"best_oa_location": {"url_for_pdf": "https://up/best.pdf", "license": "cc-by"},
                "oa_locations": [{"url_for_pdf": "https://up/best.pdf"}, {"url_for_pdf": None, "url_for_landing_page": "https://up/land"}]}
        session = FakeSession([("api.unpaywall.org", FakeResponse(200, json_data=data))])
        self.assertEqual(self.options(candidate(), ["unpaywall"], session=session), [])
        self.assertEqual(session.hits("unpaywall"), 0)
        self.assertEqual(self.options(candidate(), ["unpaywall"], contact="me@example.org", session=session),
                         [("unpaywall", "https://up/best.pdf"), ("unpaywall", "https://up/land")])
        self.assertEqual(session.calls[0][1], {"email": "me@example.org"})

    # The answers below are cut-down copies of what each service really sends.
    def test_wiley_only_for_wiley_papers_and_only_with_a_token(self):
        wiley = Wiley("TOKEN")
        self.assertEqual(self.options(candidate(doi="10.1002/aenm.202001234"), ["wiley"]), [])
        resolver = Resolver(client_for(FakeSession()), ["wiley"], wiley=wiley)
        option, = resolver.options(candidate(doi="10.1002/aenm.202001234"))
        self.assertEqual(option.url, "https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1002%2Faenm.202001234")
        self.assertEqual((option.headers, option.api), ({"Wiley-TDM-Client-Token": "TOKEN"}, True))
        self.assertEqual(list(resolver.options(candidate(doi="10.1038/s41467-1"))), [])

    def test_aps_is_asked_in_the_journals_spelling(self):
        resolver = Resolver(client_for(FakeSession()), ["aps"])
        option, = resolver.options(candidate(doi="10.1103/physrevmaterials.3.035405"))
        self.assertEqual(option.url, "https://harvest.aps.org/v2/journals/articles/10.1103/PhysRevMaterials.3.035405")
        self.assertEqual((option.headers, option.api), ({"Accept": "application/pdf"}, True))
        self.assertEqual(list(resolver.options(candidate(doi="10.1021/acs.chemmater.1"))), [])

    def test_pubmed_central_gives_the_newest_version_of_its_open_copy(self):
        found = {"resultList": {"result": [{"pmcid": "PMC7902639", "doi": "10.1000/TEST", "license": "cc by"}]}}
        listing = ("<ListBucketResult><Contents><Key>PMC7902639.1/41467_MOESM1_ESM.pdf</Key></Contents>"
                   "<Contents><Key>PMC7902639.1/PMC7902639.1.pdf</Key></Contents>"
                   "<Contents><Key>PMC7902639.2/PMC7902639.2.pdf</Key></Contents>"
                   "<Contents><Key>PMC7902639.2/PMC7902639.2.xml</Key></Contents></ListBucketResult>")
        session = FakeSession([("europepmc", FakeResponse(200, json_data=found)), ("pmc-oa-opendata", FakeResponse(200, listing))])
        resolver = Resolver(client_for(session), ["pmc"])
        option, = resolver.options(candidate())
        self.assertEqual((option.service, option.url, option.license),
                         ("pmc", "https://pmc-oa-opendata.s3.amazonaws.com/PMC7902639.2/PMC7902639.2.pdf", "cc-by"))
        self.assertEqual(session.calls[0][1]["query"], 'DOI:"10.1000/test"')
        self.assertEqual(session.calls[1][1]["prefix"], "PMC7902639.")
        # A paper that is not in PubMed Central, or another paper's record, offers nothing.
        nothing = FakeSession([("europepmc", FakeResponse(200, json_data={"resultList": {"result": [
            {"pmcid": None, "doi": "10.1000/test"}, {"pmcid": "PMC1", "doi": "10.1000/other"}]}}))])
        self.assertEqual(self.options(candidate(), ["pmc"], session=nothing), [])
        self.assertEqual(nothing.hits("pmc-oa-opendata"), 0)

    def test_osti_gives_the_deposited_manuscript(self):
        records = [{"osti_id": "1783756", "doi": "10.1000/test", "links": [
            {"rel": "citation", "href": "https://www.osti.gov/biblio/1783756"},
            {"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/1783756"}]},
            {"osti_id": "2", "doi": "10.1000/other", "links": [{"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/2"}]}]
        session = FakeSession([("osti.gov/api", FakeResponse(200, json_data=records))])
        self.assertEqual(self.options(candidate(), ["osti"], session=session), [("osti", "https://www.osti.gov/servlets/purl/1783756")])
        self.assertEqual(session.calls[0][1], {"doi": "10.1000/test"})
        self.assertEqual(self.options(candidate(), ["osti"], session=FakeSession([("osti.gov/api", FakeResponse(200, json_data=[]))])), [])

    def test_hal_gives_the_deposited_file(self):
        found = {"response": {"docs": [{"doiId_s": "10.1000/test", "fileMain_s": "https://hal.science/hal-02907292/document",
                                        "licence_s": "https://about.hal.science/hal-authorisation-v1/"}, {"doiId_s": "10.1000/test"}]}}
        session = FakeSession([("archives-ouvertes", FakeResponse(200, json_data=found))])
        resolver = Resolver(client_for(session), ["hal"])
        option, = resolver.options(candidate())
        self.assertEqual((option.service, option.url), ("hal", "https://hal.science/hal-02907292/document"))
        self.assertEqual(session.calls[0][1]["q"], 'doiId_s:"10.1000/test"')

    def test_semantic_scholar_gives_the_arxiv_version_of_a_journal_paper(self):
        found = {"externalIds": {"ArXiv": "1811.07936", "DOI": "10.1000/Test"},
                 "openAccessPdf": {"url": "https://repository.example.org/item/7", "status": "GREEN", "license": "CCBY"}}
        session = FakeSession([("semanticscholar", FakeResponse(200, json_data=found))])
        resolver = Resolver(client_for(session), ["semanticscholar"])
        preprint, copy = resolver.options(candidate())
        self.assertEqual((preprint.url, preprint.license), ("https://arxiv.org/pdf/1811.07936", "arxiv"))
        self.assertEqual((copy.url, copy.license, copy.landing), ("https://repository.example.org/item/7", "cc-by", True))
        self.assertIn("/paper/DOI:10.1000/test", session.calls[0][0])
        # The publisher's own link (gold, hybrid, bronze) is nothing new, and a closed paper has none.
        for answer in ({"externalIds": {}, "openAccessPdf": {"url": "https://doi.org/10.1000/test", "status": "GOLD"}},
                       {"externalIds": {}, "openAccessPdf": {"url": "", "status": "CLOSED"}}):
            other = FakeSession([("semanticscholar", FakeResponse(200, json_data=answer))])
            self.assertEqual(self.options(candidate(), ["semanticscholar"], session=other), [])

    def test_openaire_gives_the_repository_copies_a_file_first(self):
        found = {"results": [{"bestAccessRight": {"label": "CLOSED"}, "instances": [
            {"urls": ["https://doi.org/10.1000/test"], "license": "CC BY"},
            {"urls": ["https://pubmed.ncbi.nlm.nih.gov/33623048"]},
            {"urls": ["https://publisher.example.org/article/1"]},
            {"urls": ["https://u-picardie.hal.science/hal-05283692v1"]},
            {"urls": ["https://escholarship.org/content/qt8j4332sw/qt8j4332sw.pdf", "https://escholarship.org/uc/item/8j4332sw"], "license": "CC BY"},
            {"urls": ["https://www.researchgate.net/publication/1"]}]}]}
        session = FakeSession([("openaire", FakeResponse(200, json_data=found))])
        resolver = Resolver(client_for(session), ["openaire"])
        options = list(resolver.options(candidate(landing_url="https://publisher.example.org/article/1")))
        self.assertEqual([o.url for o in options], ["https://escholarship.org/content/qt8j4332sw/qt8j4332sw.pdf",
                                                    "https://u-picardie.hal.science/hal-05283692v1", "https://escholarship.org/uc/item/8j4332sw"])
        self.assertTrue(all(o.landing and o.service == "openaire" for o in options))
        self.assertEqual(options[0].license, "cc-by")
        self.assertEqual(session.calls[0][1], {"pid": "10.1000/test"})

    def test_a_source_is_only_asked_when_the_ones_before_it_gave_nothing_to_keep(self):
        session = FakeSession([("osti.gov/api", FakeResponse(200, json_data=[]))])
        resolver = Resolver(client_for(session), ["openalex", "osti"])
        options = resolver.options(candidate(oa_urls=["https://a/p.pdf"]))
        self.assertEqual(next(options).url, "https://a/p.pdf")
        self.assertEqual(session.calls, [])  # the downloader stops here when this file is the paper
        self.assertEqual(list(options), [])
        self.assertEqual(session.hits("osti.gov/api"), 1)

    def test_a_service_that_is_down_or_out_of_requests_offers_nothing(self):
        session = FakeSession([("semanticscholar", FakeResponse(429)), ("osti.gov/api", FakeResponse(503)),
                               ("archives-ouvertes", FakeResponse(200, "not json"))])
        resolver = Resolver(client_for(session), ["semanticscholar", "osti", "hal"])
        for key in ("10.1/a", "10.1/b", "10.1/c", "10.1/d"):
            self.assertEqual(list(resolver.options(candidate(key=key, doi=key))), [])
        # Each failed three papers running (the client retried the 429 and the 503 four times each):
        # the fourth paper does not ask them, and a long run does not wait on them any more.
        self.assertEqual(session.hits("/paper/DOI:10.1/a"), 4)
        self.assertEqual(session.hits("/paper/DOI:10.1/d"), 0)
        self.assertEqual(session.hits("osti.gov/api"), 3 * 4)
        self.assertEqual(session.hits("archives-ouvertes"), 3)

    def test_a_paper_a_service_does_not_know_does_not_count_against_it(self):
        session = FakeSession([("semanticscholar", FakeResponse(404, b'{"error": "Paper not found"}'))])
        resolver = Resolver(client_for(session), ["semanticscholar"])
        for key in ("10.1/a", "10.1/b", "10.1/c", "10.1/d", "10.1/e"):
            self.assertEqual(list(resolver.options(candidate(key=key, doi=key))), [])
        self.assertEqual(session.hits("semanticscholar"), 5)

    def test_a_paper_without_a_doi_is_not_looked_up(self):
        session = FakeSession()
        c = candidate(key="arxiv:2001.00001", doi="", arxiv_id="2001.00001")
        self.assertEqual(self.options(c, ["aps", "wiley", "pmc", "osti", "hal", "semanticscholar", "openaire", "arxiv"], session=session),
                         [("arxiv", "https://arxiv.org/pdf/2001.00001")])
        self.assertEqual(session.calls, [])

    def test_the_setup_check_tries_every_source_of_the_job(self):
        session = FakeSession([("osti.gov", FakeResponse(200, json_data=[])), ("archives-ouvertes", FakeResponse(503)),
                               ("api.wiley.com", FakeResponse(403)), ("api.openalex.org", FakeResponse(200, json_data={})),
                               ("export.arxiv.org", FakeResponse(200))])
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        job = Job(fetch=FetchConfig(folder=folder, sources=["wiley", "openalex", "osti", "hal"]))
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.dict(os.environ, {}, clear=True):
            code = check_setup(job, client_for(session), wiley=Wiley("TOKEN"))
        printed = out.getvalue()
        self.assertEqual(code, 0)  # the essentials (OpenAlex, the folder) are there
        self.assertIn("[ok] OSTI (US Department of Energy): reachable", printed)
        self.assertIn("[!!] HAL (France): HTTP 503", printed)
        self.assertIn("[!!] Wiley: HTTP 403 (the token was refused", printed)
        self.assertNotIn("OpenAIRE", printed)  # not one of this job's sources
        self.assertEqual(session.hits("archives-ouvertes"), 1)  # a service in trouble is reported, not waited for

    def test_elsevier_headers(self):
        self.assertEqual(Elsevier("K", "T").headers("application/pdf"),
                         {"X-ELS-APIKey": "K", "Accept": "application/pdf", "X-ELS-Insttoken": "T"})
        self.assertNotIn("X-ELS-Insttoken", Elsevier("K").headers("text/xml"))

    def test_elsevier_check_says_what_the_key_can_do(self):
        def answer(url, params, headers):
            accept = headers["Accept"]
            if accept == "application/pdf":
                return FakeResponse(403, headers={"X-ELS-Status": "not entitled"})
            return FakeResponse(200)
        report = Elsevier("K").check(client_for(FakeSession([("api.elsevier.com", answer)])), "10.1016/j.a.1")
        self.assertEqual([ok for ok, _ in report], [True, True, False])
        self.assertIn("not entitled", report[2][1])


class ProvenanceTests(unittest.TestCase):
    def test_a_sidecar_becomes_provenance(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "p.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "T", "authors": ["A", "B"], "doi": "10.1/x", "year": 2022, "journal": "", "source_service": "arxiv",
                       "source_url": "https://arxiv.org/pdf/1", "license": "arxiv", "retrieved_at": "2026-10-07", "sha256": "ab" * 32}, f)
        provenance = read_provenance(folder)("p.pdf")
        self.assertEqual(provenance["authors"], "A; B")
        self.assertEqual((provenance["publication_year"], provenance["file_sha256"], provenance["source_service"]), ("2022", "ab" * 32, "arxiv"))
        self.assertNotIn("journal", provenance)  # empty is absent
        self.assertEqual(read_provenance(folder)("dropped_in_by_hand.pdf"), {})


# ----------------------------------------------------------------------
# The whole web flow, with the network faked and the extraction mocked
# ----------------------------------------------------------------------
class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("AUTOMATEXTRACT_EMAIL", "OPENALEX_API_KEY", "ELSEVIER_API_KEY"):
            os.environ.pop(name, None)
        self.pdf = make_pdf()
        good = {**WORK, "doi": "https://doi.org/10.1000/good", "title": "Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte",
                "abstract_inverted_index": {"We": [0], "measure": [1], "the": [2], "ionic": [3], "conductivity": [4], "and": [5],
                                            "activation": [6], "energy": [7], "of": [8], "a": [9], "solid": [10], "electrolyte": [11]},
                "best_oa_location": {"is_oa": True, "pdf_url": "https://repo.example.org/good.pdf", "landing_page_url": "", "license": "cc-by"},
                "locations": []}
        other = {**WORK, "doi": "https://doi.org/10.1000/other", "title": "Lithium plating on graphite", "abstract_inverted_index": {"Nothing": [0]}}
        self.session = FakeSession([
            ("api.openalex.org/works", FakeResponse(200, json_data={"results": [good, other], "meta": {"next_cursor": None}})),
            ("repo.example.org/good.pdf", FakeResponse(200, self.pdf, {"Content-Type": "application/pdf"})),
        ])
        self.job = Job(
            name="t", search=SearchConfig(queries=["solid electrolyte"], sources=["openalex"]),
            screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"], review=True),
            fetch=FetchConfig(folder=os.path.join(self.root, "papers", "web"), sources=["openalex"], workers=2),
            extract=ExtractConfig(properties=["Activation_Energy"], require_material=True))
        self.harvest = Harvest(self.job, os.path.join(self.root, "output"), client=client_for(self.session))
        self.addCleanup(self.harvest.ledger.close)

    def run_stage(self, **kwargs):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("web.harvest.NaLiXPipeline") as pipeline:
            code = self.harvest.run(job_path="job.yaml", **kwargs)
        return code, out.getvalue(), pipeline

    def test_the_review_comes_before_any_download(self):
        code, printed, pipeline = self.run_stage(start="discover")
        self.assertEqual(code, 0)
        self.assertIn("python main.py web --job job.yaml --stage fetch", printed)
        self.assertIn("2 waiting for a decision", printed)
        self.assertEqual(self.session.hits("good.pdf"), 0)
        self.assertEqual(os.listdir(self.job.fetch.folder).count("10.1000_good.pdf"), 0)
        self.assertEqual({c.key: c.decision for c in self.harvest.ledger.all()}, {"10.1000/good": "yes", "10.1000/other": "no"})
        pipeline.assert_not_called()

    def test_fetch_after_the_review_then_a_second_run_does_nothing(self):
        self.run_stage(start="discover")
        code, _, pipeline = self.run_stage(start="fetch")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.job.fetch.folder, "10.1000_good.pdf")))
        self.assertTrue(os.path.exists(os.path.join(self.job.fetch.folder, "10.1000_good.json")))
        good = self.harvest.ledger.get("10.1000/good")
        self.assertEqual((good.status, good.source_used, good.file, good.license), (DOWNLOADED, "openalex", "10.1000_good.pdf", "cc-by"))
        self.assertEqual(self.harvest.ledger.get("10.1000/other").status, REJECTED)
        # the extraction is Project 1's pipeline, told where the files came from and what to keep
        _, kwargs = pipeline.call_args
        self.assertEqual((kwargs["origin"], kwargs["properties"], kwargs["require_material"]), ("web", ["Activation_Energy"], True))
        self.assertEqual(kwargs["provenance"]("10.1000_good.pdf")["source_service"], "openalex")
        # resume: the paper is not fetched twice
        before = self.session.hits("good.pdf")
        self.run_stage(start="fetch")
        self.assertEqual(self.session.hits("good.pdf"), before)

    def test_the_fetch_reports_each_paper_as_it_ends(self):
        self.run_stage(start="discover")
        seen = []
        self.harvest.ledger.apply_decisions(self.harvest.review_path)
        self.harvest.fetch(progress_callback=lambda c, outcome, done, total: seen.append((c.key, outcome.status, done, total)))
        self.assertEqual(seen, [("10.1000/good", DOWNLOADED, 1, 1)])

    def test_a_decision_changed_in_the_review_list_is_respected(self):
        self.run_stage(start="discover")
        path = os.path.join(self.job.fetch.folder, "candidates.csv")
        text = Path(path).read_text(encoding="utf-8-sig")
        Path(path).write_text(text.replace("yes,", "no,", 1), encoding="utf-8")
        self.run_stage(start="fetch")
        self.assertEqual(self.harvest.ledger.get("10.1000/good").status, REJECTED)
        self.assertEqual(self.session.hits("good.pdf"), 0)

    def test_yes_skips_the_review(self):
        code, printed, _ = self.run_stage(start="discover", approve=True)
        self.assertNotIn("Review the candidates", printed)
        self.assertEqual(self.harvest.ledger.get("10.1000/good").status, DOWNLOADED)

    def test_limit(self):
        self.run_stage(start="discover")
        self.run_stage(start="fetch", limit=0)
        self.assertEqual(self.harvest.ledger.get("10.1000/good").status, APPROVED)

    def test_a_failing_paper_is_retried_then_given_up_on(self):
        self.session.routes[1] = ("repo.example.org/good.pdf", FakeResponse(500))
        self.run_stage(start="discover")
        for expected in (FAILED, FAILED, CLOSED):
            self.run_stage(start="fetch")
            self.assertEqual(self.harvest.ledger.get("10.1000/good").status, expected)

    def test_a_closed_paper_is_fetched_from_a_repository_or_listed_as_closed(self):
        def work(doi, title):
            return {**WORK, "doi": f"https://doi.org/{doi}", "title": title, "open_access": {"is_oa": False, "oa_status": "closed"},
                    "abstract_inverted_index": {"The": [0], "activation": [1], "energy": [2], "of": [3], "a": [4], "solid": [5], "electrolyte": [6]},
                    "best_oa_location": None, "locations": []}
        deposited = "Lithium transport in a garnet ceramic measured by impedance spectroscopy"
        self.session.routes[:1] = [
            ("api.openalex.org/works", FakeResponse(200, json_data={"results": [
                work("10.1000/deposited", deposited), work("10.1000/nowhere", "Sodium conduction in a NASICON framework")],
                "meta": {"next_cursor": None}})),
            ("osti.gov/api", lambda url, params, headers: FakeResponse(200, json_data=[
                {"doi": "10.1000/deposited", "links": [{"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/1"}]}]
                if params["doi"] == "10.1000/deposited" else [])),
            ("osti.gov/servlets/purl/1", FakeResponse(200, make_pdf(title=deposited), {"Content-Type": "application/pdf"})),
        ]
        self.job.fetch.sources, self.job.screen.propose_closed = ["openalex", "osti"], True
        self.run_stage(start="discover")
        self.assertEqual({c.key: (c.decision, c.access) for c in self.harvest.ledger.all()},
                         {"10.1000/deposited": ("yes", "closed"), "10.1000/nowhere": ("yes", "closed")})
        self.run_stage(start="fetch")
        found, missing = self.harvest.ledger.get("10.1000/deposited"), self.harvest.ledger.get("10.1000/nowhere")
        self.assertEqual((found.status, found.source_used, found.license), (DOWNLOADED, "osti", "public access (US DOE)"))
        self.assertEqual(missing.status, CLOSED)
        self.assertIn("needs a manual PDF", missing.error)

    def test_no_email_in_the_requests_unless_one_was_configured(self):
        self.run_stage(start="discover")
        self.assertEqual(self.session.headers["User-Agent"], "AutoMatExtract/0.1")
        self.assertNotIn("mailto", self.session.calls[0][1])


# ----------------------------------------------------------------------
# The gate
# ----------------------------------------------------------------------
class GateTests(unittest.TestCase):
    def test_commands(self):
        from main import parse_args
        local = parse_args(["local", "--input", "x", "-w", "2"])
        self.assertEqual((local.command, local.input, local.workers, local.gui), ("local", "x", 2, False))
        web = parse_args(["web", "--job", "j.yaml", "--stage", "fetch", "--yes", "--limit", "5"])
        self.assertEqual((web.command, web.job, web.stage, web.yes, web.limit), ("web", "j.yaml", "fetch", True, 5))
        both = parse_args(["both", "--job", "j.yaml", "--input", "pdfs"])
        self.assertEqual((both.command, both.input, both.stage), ("both", "pdfs", "discover"))
        # Each project has its own folder of results.
        self.assertEqual((local.output, parse_args(["web", "--job", "j.yaml"]).output), ("local_output", "web_output"))
        self.assertEqual((both.local_output, both.web_output), ("local_output", "web_output"))
        window = parse_args(["gui", "--web-output", "elsewhere"])
        self.assertEqual((window.command, window.local_output, window.web_output), ("gui", "local_output", "elsewhere"))

    def test_the_old_way_of_running_project_1_still_means_local(self):
        import main
        seen = []
        # (whatever database the folder these tests run in happens to hold is not their subject)
        with mock.patch.object(main, "run_extraction", side_effect=lambda *a, **k: seen.append((a, k)) or 0), \
                mock.patch.object(main, "_is_outdated", return_value=False), \
                mock.patch.object(main, "_print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--input", "pdfs", "--output", "out"]), 0)
            self.assertEqual(main.main([]), 0)
        self.assertEqual(seen[0][0][:2], ("pdfs", "out"))
        self.assertEqual(seen[1][0][:2], ("papers", "local_output"))

    def test_both_projects_write_their_own_folders(self):
        import main
        local, web = [], []
        with mock.patch.object(main, "run_extraction", side_effect=lambda *a, **k: local.append(a) or 0), \
                mock.patch.object(main, "run_web", side_effect=lambda args, output: web.append(output) or 0), \
                mock.patch.object(main, "_is_outdated", return_value=False), \
                mock.patch.object(main, "_print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["both", "--job", "j.yaml"]), 0)
            self.assertEqual(main.main(["both", "--job", "j.yaml", "--local-output", "a", "--web-output", "b"]), 0)
            self.assertEqual(main.main(["web", "--job", "j.yaml"]), 0)
        self.assertEqual(web, ["web_output", "b", "web_output"])
        self.assertEqual([call[:2] for call in local], [("papers", "local_output"), ("papers", "a")])

    def test_web_needs_a_job_file(self):
        import main
        with mock.patch.object(main, "_print_banner"), mock.patch.object(main, "_is_outdated", return_value=False), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["web"]), 2)
            self.assertEqual(main.main(["web", "--job", "no/such/job.yaml"]), 2)

    def test_a_database_of_an_earlier_version_is_rebuilt_not_added_to(self):
        import main
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        pdfs, out = os.path.join(folder, "pdfs"), os.path.join(folder, "out")
        os.makedirs(pdfs), os.makedirs(out)
        pd.DataFrame([{"paper_id": "a.pdf", "property_name": "Migration_Barrier"}]).to_csv(os.path.join(out, "properties.csv"), index=False)
        pd.DataFrame([{"paper_id": "a.pdf", "filename": "a.pdf"}]).to_csv(os.path.join(out, "papers.csv"), index=False)
        runs = []
        with mock.patch.object(main, "run_extraction", side_effect=lambda *a, **k: runs.append(a) or 0), \
                mock.patch.object(main, "_print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["local", "--input", pdfs, "--output", out]), 1)
            self.assertEqual(runs, [])  # nothing is added to the old tables
            self.assertEqual(main.main(["local", "--input", pdfs, "--output", out, "--rebuild"]), 0)
        self.assertEqual(len(runs), 1)
        kept, = [name for name in os.listdir(out) if name.startswith("previous_")]
        self.assertEqual(sorted(os.listdir(os.path.join(out, kept))), ["papers.csv", "properties.csv"])  # moved, not deleted
        self.assertFalse(os.path.exists(os.path.join(out, "papers.csv")))


# ----------------------------------------------------------------------
# The shared pipeline and exporter
# ----------------------------------------------------------------------
class SharedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from extractor import ExtractorEngine
        from ranking import Ranker
        cls.ExtractorEngine, cls.Ranker = ExtractorEngine, Ranker

    def paper(self, text, **kwargs):
        from models import ExtractedField, PaperData
        from pipeline import NaLiXPipeline
        ranked = self.Ranker.process(self.ExtractorEngine.extract_all(
            [{"text": text, "page": 1, "section": "Results", "type": "Text"}]))
        paper = PaperData(
            filename="p.pdf", metadata={"title": ExtractedField("T", "T", 1.0, "1", "Metadata", "T", "Metadata")},
            materials=ranked["materials"], electrochemical=ranked["ELECTROCHEMICAL"], thermodynamic=ranked["THERMODYNAMIC"],
            mechanical=ranked["MECHANICAL"], structural=ranked["STRUCTURAL"], electronic=ranked["ELECTRONIC"],
            thermal=ranked["THERMAL"], spectroscopy=ranked["SPECTROSCOPY"], dft=ranked["DFT"], aimd=ranked["AIMD"],
            ml=ranked["ML"], synthesis=ranked["SYNTHESIS"], characterization=ranked["CHARACTERIZATION"],
            battery_perf={}, interfaces={}, relations=ranked["relations"], workflow=ranked["workflow"],
            figures=ranked["figures"], tables=ranked["tables"], equations=ranked["equations"], references=[])
        for key, value in kwargs.items():
            setattr(paper, key, value)
        return paper, NaLiXPipeline

    TEXT = ("LiBiO2 has a migration barrier of 0.27 eV, a band gap of 3 eV and an ionic conductivity of 3 mS/cm. "
            "The band gap of the pristine sample is 4 eV. DFT calculations used VASP with the PBE functional.")

    def test_wished_properties_only(self):
        paper, Pipeline = self.paper(self.TEXT)
        Pipeline("in", "out", properties=["Activation_Energy"])._restrict(paper)
        barrier, = paper.electrochemical["Activation_Energy"]
        self.assertEqual((barrier.normalized_value, barrier.reported_as), ("0.27 eV", "migration barrier"))
        self.assertEqual(paper.electrochemical["Ionic_Conductivity"], [])
        self.assertEqual(paper.electronic["Band_Gap"], [])
        self.assertEqual(paper.dft["Software"], [])
        self.assertEqual({r.property_name for r in paper.relations}, {"Activation_Energy"})
        self.assertEqual([m.normalized_formula for m in paper.materials], ["LiBiO2"])

    def test_require_material_drops_unlinked_numbers_but_not_settings(self):
        paper, Pipeline = self.paper(self.TEXT)
        self.assertTrue(any(c.material_id == "NONE" for c in paper.electronic["Band_Gap"]))
        Pipeline("in", "out", require_material=True)._restrict(paper)
        self.assertTrue(all(c.material_id != "NONE" for c in paper.electronic["Band_Gap"]))
        self.assertTrue(paper.dft["Software"])  # VASP has no material and is not a material property

    def test_a_papers_own_record_beats_the_guess_from_its_first_page(self):
        from pipeline import NaLiXPipeline
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        document = pymupdf.open()
        for index in range(2):  # a preprint whose first page cites another paper's DOI
            document.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 780), "A preprint about garnets. See 10.1016/j.ssi.2019.05.027 "
                                               "for the earlier work. " * 12 if index == 0 else "More text. " * 60, fontsize=10)
        document.save(os.path.join(folder, "arxiv_1.pdf"))
        with open(os.path.join(folder, "arxiv_1.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "The Real Title of the Preprint", "doi": "", "year": 2024, "journal": "arXiv"}, f)
        paper = NaLiXPipeline(folder, folder, provenance=read_provenance(folder), origin="web").process_document("arxiv_1.pdf")
        self.assertEqual(paper.metadata["doi"].normalized_value, "NONE")  # not the reference's DOI
        self.assertEqual(paper.metadata["title"].normalized_value, "The Real Title of the Preprint")
        plain = NaLiXPipeline(folder, folder).process_document("arxiv_1.pdf")
        self.assertEqual(plain.metadata["doi"].normalized_value, "10.1016/j.ssi.2019.05.027")  # local mode is unchanged

    def test_batches_then_one_workbook(self):
        from exporter import StrictExporter
        paper, _ = self.paper(self.TEXT, origin="web", provenance={"source_service": "arxiv", "license": "arxiv"})
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        exporter = StrictExporter(folder)
        exporter.export([paper], excel=False)
        self.assertFalse(os.path.exists(os.path.join(folder, "database.xlsx")))
        papers = pd.read_csv(os.path.join(folder, "papers.csv"), dtype=str, keep_default_na=False)
        self.assertEqual((papers.origin[0], papers.source_service[0], papers.license[0], papers.source_url[0]), ("web", "arxiv", "arxiv", "NONE"))
        exporter.export_excel()
        csv_rows = len(pd.read_csv(os.path.join(folder, "properties.csv")))
        with pd.ExcelFile(os.path.join(folder, "database.xlsx")) as book:
            self.assertEqual(len(book.parse("properties")), csv_rows)
        self.assertEqual(json.loads(Path(folder, "database.json").read_text(encoding="utf-8"))["papers"][0]["origin"], "web")


if __name__ == "__main__":
    unittest.main()
