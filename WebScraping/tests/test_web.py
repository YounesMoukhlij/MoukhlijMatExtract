# WebScraping/tests/test_web.py
"""Offline tests for the web project (Project 2) and the shared changes it needed.

Every network call is answered by a fake session, so these run anywhere, instantly, and never touch a
real service. Run them with:  python -m unittest discover -s WebScraping/tests -t . -v   (or: pytest WebScraping)
"""

import csv
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

import pandas as pd
import pymupdf

from WebScraping.averageScrap import by_hand, screening
from WebScraping.averageScrap.elsevier import Elsevier
from WebScraping.averageScrap.fetch import HAND_LIST, SITE_BLOCKED_MARK, Downloader, Outcome, SiteBlocks, check_pdf
from WebScraping.averageScrap.harvest import Harvest
from WebScraping.averageScrap.http import Disallowed, HttpError, PoliteClient
from WebScraping.averageScrap.doctor import check as check_setup
from WebScraping.averageScrap.ids import aps_doi, arxiv_id, candidate_key, file_stem, normalize_doi
from WebScraping.averageScrap.job import (ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job, read_env,
                     save_env)
from WebScraping.averageScrap.ledger import (APPROVED, CLOSED, DOWNLOADED, FAILED, REJECTED, SCREENED, Candidate, Ledger)
from WebScraping.averageScrap.resolve import FetchOption, Resolver
from WebScraping.averageScrap.sidecar import read_provenance
from WebScraping.averageScrap.sources.arxiv import ArXiv, build_query, parse_feed
from WebScraping.averageScrap.sources.openalex import OpenAlex, abstract_from_index, candidate_from_work
from WebScraping.averageScrap.wiley import Wiley


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

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        return self.get(url, params=json if json is not None else data, headers=headers)

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
        self.assertEqual(job.fetch.folder, os.path.join("WebScraping", "papers"))
        self.assertEqual(job.extract.properties, ["Activation_Energy"])
        # Every source is tried unless the job names its own; closed papers are not proposed unless it says so.
        self.assertEqual(job.fetch.sources, ["elsevier", "wiley", "springeroa", "aps", "openalex", "unpaywall", "publisher", "arxiv", "pmc",
                                             "osti", "hal", "zenodo", "datacite", "semanticscholar", "ads", "openaire", "core",
                                             "crossref"])
        # Every search source too (one whose key is missing is skipped), and every service asked for a missing abstract.
        self.assertEqual(job.search.sources[:2], ["openalex", "arxiv"])
        self.assertEqual(len(job.search.sources), 25)
        self.assertEqual(job.search.abstract_sources[0], "openaire")
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
                  fetch=FetchConfig(folder="WebScraping/papers", sources=["arxiv", "osti"], workers=2, max_pdf_mb=40),
                  extract=ExtractConfig(properties=["Activation_Energy"], require_material=True))
        self.assertEqual(load_job(self.write(dump_job(job))), job)
        no_years = Job(search=SearchConfig(queries=["a"]))
        self.assertEqual(load_job(self.write(dump_job(no_years))), no_years)

    def test_settings_are_saved_into_the_env_file_and_the_environment(self):
        path = self.write("# my keys\nELSEVIER_API_KEY=old\nOTHER=kept\n").replace("job.yaml", ".env")
        os.replace(path.replace(".env", "job.yaml"), path)
        with mock.patch.dict(os.environ, {"MME_EMAIL": "was@example.org"}, clear=True):
            save_env({"ELSEVIER_API_KEY": "new-key", "WILEY_TDM_TOKEN": " token ", "MME_EMAIL": ""}, path)
            self.assertEqual((os.environ["ELSEVIER_API_KEY"], os.environ["WILEY_TDM_TOKEN"]), ("new-key", "token"))
            self.assertNotIn("MME_EMAIL", os.environ)  # emptied: unset for this run too
        text = Path(path).read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[:3], ["# my keys", "ELSEVIER_API_KEY=new-key", "OTHER=kept"])
        self.assertEqual(read_env(path), {"ELSEVIER_API_KEY": "new-key", "OTHER": "kept", "WILEY_TDM_TOKEN": "token",
                                          "MME_EMAIL": ""})
        if os.name != "nt":  # Windows has no owner/group/other permission bits to check
            self.assertEqual(os.stat(path).st_mode & 0o077, 0)  # the keys are the owner's alone
        with self.assertRaisesRegex(ValueError, "one line"):
            save_env({"ELSEVIER_API_KEY": "two\nlines"}, path)

    def test_a_setting_under_its_former_name_still_counts(self):
        from WebScraping.averageScrap.job import load_env
        path = self.write("AUTOMATEXTRACT_EMAIL=me@example.org\n")  # the name before MoukhlijMatExtract
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_env(path), 1)
            self.assertEqual(os.environ.get("MME_EMAIL"), "me@example.org")

    def test_email_comes_from_the_job_or_the_environment_and_nowhere_else(self):
        with mock.patch.dict(os.environ, {"MME_EMAIL": "env@example.org"}):
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

    def test_a_site_that_says_too_many_requests_gets_a_real_pause_then_a_slower_pace(self):
        """arXiv answers 429 when this network asked too much: the client waits 15 s, then 30 s (not 2, 4, 8),
        and keeps a slower pace with that host for the rest of the run instead of running into the limit again."""
        class Clock:
            now = 100.0
        slept = []

        def sleep(seconds):
            slept.append(round(seconds, 3))
            Clock.now += seconds
        answers = [FakeResponse(429), FakeResponse(429), FakeResponse(200, "{}"), FakeResponse(200, "{}")]
        client = PoliteClient(session=FakeSession([("export.arxiv.org", answers)]), sleep=sleep, clock=lambda: Clock.now)
        with self.assertLogs(level="INFO") as said:
            self.assertEqual(client.get("https://export.arxiv.org/api/query").status_code, 200)
            client.get("https://export.arxiv.org/api/query")
        waits = [s for s in slept if s >= 1]
        self.assertEqual(waits[:2], [15.0, 30.0])        # the pauses after each 429 (spacing slots aside)
        self.assertEqual(slept[-1], 12.0)                 # the next request: one every 12 s now (3 s, doubled twice)
        self.assertEqual(sum("asked to slow down" in line for line in said.output), 2)

    def test_who_is_asking(self):
        plain, polite = FakeSession(), FakeSession()
        client_for(plain)
        client_for(polite, contact="me@example.org")
        self.assertEqual(plain.headers["User-Agent"], "MoukhlijMatExtract/1.0.0")
        self.assertEqual(polite.headers["User-Agent"], "MoukhlijMatExtract/1.0.0 (mailto:me@example.org)")

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

    def test_robots_txt_wildcards_and_the_longest_rule(self):
        # RFC 9309: "*" is any characters, "$" the end of the path, and the longest matching rule wins.
        robots = "User-agent: *\nDisallow: /*_pdf\nDisallow: /*.json$\nDisallow: /private\nAllow: /private/open\n"
        client = client_for(FakeSession([("robots.txt", FakeResponse(200, robots))]))
        self.assertFalse(client.allowed("https://www.jstage.jst.go.jp/article/jcersj2/132/10/132_24062/_pdf"))
        self.assertTrue(client.allowed("https://www.jstage.jst.go.jp/article/jcersj2/132/10/132_24062/_article"))
        self.assertFalse(client.allowed("https://a.org/data/x.json"))
        self.assertTrue(client.allowed("https://a.org/data/x.json?page=2"))
        self.assertFalse(client.allowed("https://a.org/private/x.pdf"))
        self.assertTrue(client.allowed("https://a.org/private/open/x.pdf"))

    def test_a_robots_rule_for_another_bot_whose_name_is_part_of_ours_does_not_apply(self):
        robots = "User-agent: Extract\nDisallow: /\n\nUser-agent: *\nDisallow: /private\n"
        client = client_for(FakeSession([("robots.txt", FakeResponse(200, robots))]))
        self.assertTrue(client.allowed("https://a.org/paper.pdf"))
        self.assertFalse(client.allowed("https://a.org/private/paper.pdf"))

    def test_a_blank_line_does_not_end_a_group_of_robots_rules(self):
        robots = "User-agent: *\nCrawl-delay: 30\n\nDisallow: */search\n# a comment\nDisallow: */user\n"  # as PLOS's
        client = client_for(FakeSession([("robots.txt", FakeResponse(200, robots))]))
        self.assertFalse(client.allowed("https://journals.plos.org/plosone/search?q=x"))
        self.assertFalse(client.allowed("https://journals.plos.org/plosone/user"))
        self.assertTrue(client.allowed("https://journals.plos.org/plosone/article?id=1"))
        self.assertEqual(client._crawl_delay["journals.plos.org"], 30.0)

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

    def test_a_search_already_run_is_remembered_for_a_while(self):
        search = "openalex|li argyrodite|[2015, 2026]|True"
        self.assertIsNone(self.ledger.searched(search, 200))
        self.ledger.mark_searched(search, 200)
        self.assertIsNotNone(self.ledger.searched(search, 200))
        self.assertIsNotNone(self.ledger.searched(search, 100))   # less deep: done already
        self.assertIsNone(self.ledger.searched(search, 500))      # deeper: not yet
        self.assertIsNone(self.ledger.searched(search, 200, max_age_days=0))  # too long ago: run again

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

    def test_a_record_with_a_huge_abstract_does_not_stop_the_download(self):
        """Some repository records give a whole text as their abstract (a Zenodo record: 465,682 characters). The
        review list could then not be read back — a cell longer than the CSV reader allows — and the download stopped
        before its first paper."""
        huge = "word " * 100_000                                          # 500,000 characters
        self.ledger.add(candidate(key="z", doi="z", title="A Zenodo record", abstract=huge))
        self.ledger.add(candidate(key="a", doi="a", title="Garnet electrolyte"))
        self.ledger.update("z", status=SCREENED, decision="no")
        self.ledger.update("a", status=SCREENED, decision="yes")
        path = os.path.join(self.folder, "candidates.csv")
        self.ledger.write_review(path)
        rows = {r["key"]: r for r in self.ledger._read_review(path)}
        self.assertLess(len(rows["z"]["abstract"]), 10_100)               # the list shows its beginning
        self.assertTrue(rows["z"]["abstract"].endswith("[cut: 500,000 characters in all]"))
        self.assertEqual(len(self.ledger.get("z").abstract), len(huge))  # the ledger keeps all of it
        self.assertEqual(self.ledger.apply_decisions(path)["approved"], 1)
        # A list written by an earlier version, with the whole text in it, is read too.
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("decision,key,abstract\nyes,a,short\nno,z," + "x" * 300_000 + "\n")
        self.assertEqual(self.ledger.apply_decisions(path)["approved"], 1)

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
        # With a key: without one, OpenAlex gives only the first page.
        found = list(OpenAlex(client_for(session), contact="x@example.org", api_key="test-key")
                     .search("solid electrolyte", (2015, 2026), limit=10))
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

    def test_a_formula_is_found_however_it_is_written(self):
        """A formula word is found with spaces in it (as Crossref gives sub-scripted titles), with subscript digits,
        with <sub> tags — and a part of a formula is found inside a doped one (La3Zr2O12 in Li6.4Ga0.2La3Zr2O12).
        A formula keeps its case: CO is not Co."""
        cfg = ScreenConfig(topic_words=["Li7La3Zr2O12", "La3Zr2O12", "LiZr2(PO4)3", "Si2PO12"],
                           property_words=["ionic conductivity"], min_score=2)
        for n, title in enumerate(("Enhanced ionic conductivity of titanium doped Li 7 La 3 Zr 2 O 12",
                                   "Ionic conductivity of Li₇La₃Zr₂O₁₂ thin films",
                                   "Ionic conductivity of Li<sub>7</sub>La<sub>3</sub>Zr<sub>2</sub>O<sub>12</sub>",
                                   "Ionic conductivity of Li6.4Ga0.2La3Zr2O12 pellets",
                                   "Enhanced lithium-ion conductivity in a LiZr 2 (PO 4 ) 3 solid electrolyte, ionic conductivity",
                                   "Cold sintering and ionic conductivities of Na3.256Mg0.128Zr1.872Si2PO12 solid electrolytes")):
            self.ledger.add(candidate(key=f"k{n}", doi=f"k{n}", title=title, abstract=""))
        self.ledger.add(candidate(key="lower", doi="lower", title="Ionic conductivity of li7la3zr2o12", abstract=""))
        screening.screen(self.ledger, cfg)
        self.assertEqual([self.ledger.get(f"k{n}").decision for n in range(6)], ["yes"] * 6)
        self.assertIn("Li7La3Zr2O12 (title)", self.ledger.get("k0").why)
        self.assertIn("La3Zr2O12 (title)", self.ledger.get("k3").why)
        self.assertEqual(self.ledger.get("lower").decision, "no")  # a formula keeps its case

    def test_a_formula_is_not_found_inside_another_element(self):
        """Li3N (lithium nitride) is not Li3NbO4 (a niobate): an element symbol goes on in lower case, so a formula
        must not be followed by one. Spaces before a word stay, so a formula is not glued to the next word."""
        cfg = ScreenConfig(topic_words=["Li3N", "LiZr2(PO4)3"], property_words=["ionic conductivity"], min_score=2)
        for key, title in (("nitride", "Ionic conductivity of Li3N single crystals"),
                           ("niobate", "Ionic conductivity of Li3NbO4 ceramics"),
                           ("spread", "Ionic conductivity of the LiZr 2 (PO 4 ) 3 solid electrolyte"),
                           ("subscripts", "Ionic conductivity of Li₃N films")):
            self.ledger.add(candidate(key=key, doi=key, title=title, abstract=""))
        screening.screen(self.ledger, cfg)
        self.assertEqual({k: self.ledger.get(k).decision for k in ("nitride", "niobate", "spread", "subscripts")},
                         {"nitride": "yes", "niobate": "no", "spread": "yes", "subscripts": "yes"})

    def test_papers_already_screened_are_screened_again_with_the_settings_of_now(self):
        """The settings changed after the search (“also keep papers no free copy is known for” ticked, a word
        excluded): the papers not downloaded yet are decided again. A paper downloaded, and a duplicate, are left."""
        title = "Garnet solid electrolytes ionic conductivity"
        self.ledger.add(candidate(key="closed", doi="closed", title=title, oa_status="closed", access=""))
        self.ledger.add(candidate(key="open", doi="open", title=title + " again"))
        self.ledger.add(candidate(key="twin", doi="twin", title=title + " twin"))
        self.ledger.add(candidate(key="got", doi="got", title="Graphite anodes", abstract="Graphite.", status=DOWNLOADED,
                                  decision="yes"))
        cfg = ScreenConfig(**{**vars(self.cfg), "min_score": 5})
        screening.screen(self.ledger, cfg, approve=True)
        self.ledger.update("twin", flags=["duplicate-of:open"], decision="no", status=REJECTED)
        self.assertEqual((self.ledger.get("closed").status, self.ledger.get("open").status), (REJECTED, APPROVED))

        now = ScreenConfig(**{**vars(cfg), "propose_closed": True, "exclude_words": ["supercapacitor", "again"]})
        counts = screening.rescreen(self.ledger, now)
        self.assertEqual(counts, {"rescored": 2, "proposed": 1, "dropped": 1})
        closed, opened, twin = (self.ledger.get(k) for k in ("closed", "open", "twin"))
        self.assertEqual((closed.decision, closed.status), ("yes", SCREENED))  # proposed: waiting for the download
        self.assertIn("no-open-copy-known", closed.flags)
        self.assertEqual((opened.decision, opened.status), ("no", SCREENED))
        self.assertIn("excluded: again (title)", opened.why)
        self.assertEqual((twin.decision, twin.flags), ("no", ["duplicate-of:open"]))  # a duplicate stays declined
        self.assertEqual((self.ledger.get("got").status, self.ledger.get("got").decision), (DOWNLOADED, "yes"))
        self.assertEqual(screening.rescreen(self.ledger, now), {"rescored": 2, "proposed": 0, "dropped": 0})

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

    def refused(self):
        return []


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

    def test_a_site_refusing_three_downloads_in_a_row_is_not_asked_again_this_run(self):
        blocks = SiteBlocks(after=3)
        self.session = FakeSession([("www.mdpi.com", FakeResponse(403))])
        d = Downloader(self.folder, client_for(self.session), StubResolver(
            [FetchOption("openalex", "https://www.mdpi.com/p.pdf"), FetchOption("publisher", "https://www.mdpi.com/page", landing=True)]),
            max_mb=5, blocks=blocks)
        with self.assertLogs(level="WARNING") as said:
            first, second = d.fetch(candidate(key="10.3390/a", doi="10.3390/a")), d.fetch(candidate(key="10.3390/b", doi="10.3390/b"))
        self.assertTrue(blocks.blocked("www.mdpi.com"))
        self.assertIn(SITE_BLOCKED_MARK, "\n".join(said.output))
        downloads = lambda: self.session.hits("www.mdpi.com") - self.session.hits("robots.txt")  # noqa: E731
        self.assertEqual(downloads(), 3)  # the fourth request was never sent
        self.assertFalse(first.not_asked)
        self.assertIn("skipped this run", second.error)
        self.assertFalse(second.not_asked)  # its first option was still asked (the third refusal)
        third = d.fetch(candidate(key="10.3390/c", doi="10.3390/c"))
        self.assertEqual((third.status, third.not_asked), (FAILED, True))
        self.assertEqual(downloads(), 3)

    def test_a_refusal_reached_through_a_doi_link_blocks_the_publisher_not_doi_org(self):
        def refused_at_the_publisher(url, params, headers):
            response = FakeResponse(403)
            response.url = "https://www.mdpi.com/2313-0105/9/2/137/pdf"  # where doi.org sent the request
            return response
        blocks = SiteBlocks(after=2)
        self.session = FakeSession([("doi.org/", refused_at_the_publisher)])
        d = Downloader(self.folder, client_for(self.session), StubResolver(
            [FetchOption("openalex", "https://doi.org/10.3390/a")]), max_mb=5, blocks=blocks)
        for key in ("10.3390/a", "10.3390/b"):
            d.fetch(candidate(key=key, doi=key))
        self.assertEqual(blocks.hosts(), ["www.mdpi.com"])
        self.assertFalse(blocks.blocked("doi.org"))  # every other publisher's DOI links still go through

    def test_a_download_a_site_lets_through_clears_its_refusals(self):
        blocks = SiteBlocks(after=2)
        blocks.refused("repo.example.org")
        blocks.answered("repo.example.org")
        blocks.refused("repo.example.org")
        self.assertFalse(blocks.blocked("repo.example.org"))

    def test_a_publisher_apis_403_is_about_the_subscription_and_blocks_nothing(self):
        blocks = SiteBlocks(after=1)
        self.session = FakeSession([("api.elsevier.com", FakeResponse(403))])
        d = Downloader(self.folder, client_for(self.session), StubResolver(
            [FetchOption("elsevier", "https://api.elsevier.com/content/article/doi/10.1016/x")]), max_mb=5, blocks=blocks)
        outcome = d.fetch(candidate(key="10.1016/x", doi="10.1016/x"))
        self.assertIn("not entitled", outcome.error)
        self.assertEqual(blocks.hosts(), [])

    def test_nothing_to_try_means_closed(self):
        self.assertEqual(self.downloader([], []).fetch(candidate()).status, CLOSED)

    def test_a_pdf_fetched_legally_is_not_downloaded_again(self):
        Path(self.folder, "10.1000_test.pdf").write_bytes(self.pdf)  # named after its DOI, as earlier versions did
        Path(self.folder, "10.1000_test.json").write_text('{"source_service": "unpaywall"}', encoding="utf-8")
        d = self.downloader([], [FetchOption("openalex", "https://repo.example.org/p.pdf")])
        with self.assertLogs(level="INFO") as said:
            outcome = d.fetch(candidate())
        self.assertEqual((outcome.status, outcome.file), (DOWNLOADED, "10.1000_test.pdf"))
        self.assertEqual(self.session.calls, [])  # nothing was asked of the network
        self.assertIn("Already fetched", "\n".join(said.output))

    def test_a_pdf_with_no_record_of_its_source_is_replaced_by_a_legal_copy(self):
        Path(self.folder, "10.1000_test.pdf").write_bytes(b"%PDF- a copy from somewhere")  # by hand, or an earlier tool
        d = self.downloader([("repo.example.org/p.pdf", FakeResponse(200, self.pdf, {"Content-Type": "application/pdf"}))],
                            [FetchOption("openalex", "https://repo.example.org/p.pdf", license="cc-by")])
        outcome = d.fetch(candidate())
        self.assertEqual((outcome.status, outcome.service), (DOWNLOADED, "openalex"))
        self.assertEqual(Path(self.folder, "10.1000_test.pdf").read_bytes(), self.pdf)  # the legal copy now
        self.assertIn('"openalex"', Path(self.folder, "10.1000_test.json").read_text(encoding="utf-8"))

    def test_with_no_legal_copy_the_pdf_there_stays(self):
        Path(self.folder, "10.1000_test.pdf").write_bytes(self.pdf)
        outcome = self.downloader([], []).fetch(candidate())
        self.assertNotEqual(outcome.status, DOWNLOADED)  # not recorded as fetched from a legal source
        self.assertEqual(Path(self.folder, "10.1000_test.pdf").read_bytes(), self.pdf)  # never deleted

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

    def test_elsevier_s_first_page_alone_is_not_the_paper(self):
        # Not entitled: the API sends the article's first page — dense enough to pass for an article.
        document = pymupdf.open()
        document.new_page().insert_textbox(pymupdf.Rect(30, 30, 580, 810), "Ionic conductivity of the argyrodite "
                                           "Li6PS5Cl solid electrolyte\n\n" + "Impedance spectra were measured. " * 70,
                                           fontsize=7)
        first_page = document.tobytes()
        d = self.downloader([("api.elsevier.com", FakeResponse(200, first_page, {"Content-Type": "application/pdf"}))],
                            [FetchOption("elsevier", Elsevier.url("10.1016/j.a.1"), {"X-ELS-APIKey": "k"}, api=True)])
        outcome = d.fetch(candidate())
        self.assertNotEqual(outcome.status, DOWNLOADED)
        self.assertIn("only the first page", outcome.error)
        self.assertEqual(list(Path(self.folder).glob("*.pdf")), [])

    def test_a_403_from_elsevier_says_where_the_subscription_works(self):
        d = self.downloader([("api.elsevier.com", FakeResponse(403))],
                            [FetchOption("elsevier", Elsevier.url("10.1016/j.a.1"), {"X-ELS-APIKey": "k"}, api=True)])
        error = d.fetch(candidate()).error
        self.assertIn("not entitled", error)
        self.assertIn("university's network", error)

    def test_a_file_over_the_size_limit_is_refused(self):
        d = self.downloader([("big.example.org/p.pdf", FakeResponse(200, b"%PDF-" + b"0" * (6 * 1024 * 1024)))],
                            [FetchOption("openalex", "https://big.example.org/p.pdf")])
        self.assertIn("larger than 5 MB", d.fetch(candidate()).error)


class ResolverTests(unittest.TestCase):
    def options(self, c, sources, contact="", elsevier=None, session=None):
        resolver = Resolver(client_for(session or FakeSession()), sources, contact, elsevier)
        return [(o.service, o.url) for o in resolver.options(c)]

    def test_a_service_that_does_not_answer_is_known_as_down_and_a_busy_one_is_not(self):
        import requests
        def no_answer(url, params, headers):
            raise requests.ConnectionError("no route")
        session = FakeSession([("osti.gov", no_answer), ("busy.example.org", FakeResponse(429))])
        resolver = Resolver(client_for(session), [], "")
        resolver._local.refused = []
        self.assertIsNone(resolver._ask("OSTI", "https://www.osti.gov/api/v1/records"))
        self.assertIsNone(resolver._ask("Busy", "https://busy.example.org/api"))
        self.assertEqual(resolver.down, {"OSTI"})
        self.assertEqual(resolver.refused(), ["OSTI", "Busy"])  # neither checked the paper: both still refused

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

    def test_springer_nature_open_access_gives_the_pdf_of_an_open_paper_only(self):
        """The Open Access API knows a paper only when it is open (404 otherwise): then its PDF from link.springer.com.
        Asked only for Springer, Nature and BMC papers, and only with SPRINGER_NATURE_OA_KEY."""
        open_paper = {"records": [{"doi": "10.1186/s40580-020-00001-1", "title": "Open"}]}
        session = FakeSession([("api.springernature.com/openaccess", lambda url, params, headers: FakeResponse(
            200, json_data=open_paper) if "s40580" in params["q"] else FakeResponse(404, json_data={"status": "Fail"}))])
        self.assertEqual(self.options(candidate(doi="10.1186/s40580-020-00001-1"), ["springeroa"], session=session), [])
        self.assertEqual(session.hits("springernature"), 0)  # no key: not asked
        with mock.patch.dict(os.environ, {"SPRINGER_NATURE_OA_KEY": "oa-key"}):
            option, = Resolver(client_for(session), ["springeroa"]).options(candidate(doi="10.1186/s40580-020-00001-1"))
            self.assertEqual((option.service, option.url, option.landing),  # BMC: its own site, the article page
                             ("springeroa", "https://doi.org/10.1186/s40580-020-00001-1", True))
            self.assertEqual(session.calls[-1][1], {"q": "doi:10.1186/s40580-020-00001-1", "api_key": "oa-key"})
            resolver = Resolver(client_for(session), ["springeroa"])
            self.assertEqual(list(resolver.options(candidate(doi="10.1007/s12598-020-01441-1"))), [])  # closed: 404
            self.assertEqual(resolver.refused(), [])  # a 404 is an answer, not a refusal
            asked = session.hits("springernature")
            self.assertEqual(list(resolver.options(candidate(doi="10.1021/acs.chemmater.1"))), [])
            self.assertEqual(session.hits("springernature"), asked)  # not a Springer paper: not asked

    def test_osti_is_asked_only_of_papers_openalex_ties_to_the_us_department_of_energy(self):
        """OSTI holds DOE-funded papers only: a paper OpenAlex ties to no DOE funder or laboratory is not asked of it
        (and cannot wait on it); one OpenAlex does not know is asked, rather than a DOE paper missed."""
        from WebScraping.averageScrap.resolve import doe_linked
        self.assertTrue(doe_linked({"funders": [{"id": "https://openalex.org/F4320306084", "display_name": "U.S. Department of Energy"}]}))
        self.assertTrue(doe_linked({"funders": [{"id": "F1", "display_name": "Basic Energy Sciences"}]}))
        self.assertTrue(doe_linked({"authorships": [{"institutions": [{"display_name": "Argonne National Laboratory"}]}]}))
        self.assertFalse(doe_linked({"funders": [{"id": "F2", "display_name": "National Natural Science Foundation of China"}],
                                     "authorships": [{"institutions": [{"display_name": "Tsinghua University"}]}]}))
        self.assertFalse(doe_linked({"funders": [{"id": "F3", "display_name": "Department of Energy, Philippines"}]}))
        record = [{"doi": "10.1000/doe", "links": [{"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/1"}]}]
        works = {"10.1000/doe": {"id": "W1", "funders": [{"id": "https://openalex.org/F4320306084"}]},
                 "10.1000/nsfc": {"id": "W2", "funders": [{"id": "F2", "display_name": "NSFC"}], "authorships": []}}

        def openalex(url, params, headers):
            doi = url.split("doi:", 1)[1]
            return FakeResponse(200, json_data=works[doi]) if doi in works else FakeResponse(404, b"")
        session = FakeSession([("api.openalex.org", openalex), ("osti.gov", FakeResponse(200, json_data=record))])
        resolver = Resolver(client_for(session), ["osti"])
        self.assertEqual([o.url for o in resolver.options(candidate(doi="10.1000/doe"))], ["https://www.osti.gov/servlets/purl/1"])
        asked = session.hits("osti.gov")
        self.assertEqual(list(resolver.options(candidate(doi="10.1000/nsfc"))), [])
        self.assertEqual(session.hits("osti.gov"), asked)  # not a DOE paper: OSTI not asked
        list(resolver.options(candidate(doi="10.1000/unknown")))
        self.assertEqual(session.hits("osti.gov"), asked + 1)  # OpenAlex does not know it: OSTI is asked

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
        osti_call, = [params for url, params, _ in session.calls if "osti.gov" in url]  # after the OpenAlex lookup
        self.assertEqual(osti_call, {"doi": "10.1000/test"})
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
        job = Job(search=SearchConfig(queries=["a"], sources=["openalex"], abstract_sources=[]),
                  fetch=FetchConfig(folder=folder, sources=["wiley", "openalex", "osti", "hal"]))
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
        for name in ("MME_EMAIL", "OPENALEX_API_KEY", "ELSEVIER_API_KEY"):
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
        with redirect_stdout(out), mock.patch("LocalExtraction.pipeline.NaLiXPipeline") as pipeline:
            code = self.harvest.run(job_path="job.yaml", **kwargs)
        return code, out.getvalue(), pipeline

    def test_a_paper_refused_for_where_it_is_asked_from_keeps_its_tries(self):
        from WebScraping.averageScrap.fetch import Outcome
        self.harvest.ledger.add(Candidate(key="10.1016/j.a.1", doi="10.1016/j.a.1", status=APPROVED, decision="yes"))
        refused = Outcome("10.1016/j.a.1", FAILED, error="elsevier: HTTP 403 (not entitled: closed Elsevier papers …)")
        for _ in range(5):  # five downloads from home
            self.assertEqual(self.harvest._record(self.harvest.ledger.get("10.1016/j.a.1"), refused), FAILED)
        paper = self.harvest.ledger.get("10.1016/j.a.1")
        self.assertEqual((paper.status, paper.attempts), (FAILED, 0))  # still tried by the next download
        other = Outcome("10.1016/j.a.1", FAILED, error="openalex: HTTP 404")
        for _ in range(3):
            self.harvest._record(self.harvest.ledger.get("10.1016/j.a.1"), other)
        self.assertEqual(self.harvest.ledger.get("10.1016/j.a.1").status, CLOSED)  # a real failure still counts

    def test_a_rescreen_writes_the_review_list_the_download_reads(self):
        import dataclasses
        self.harvest.ledger.add(Candidate(key="10.1000/shut", doi="10.1000/shut", title="Activation energy of a solid electrolyte",
                                          abstract="", oa_status="closed", status=REJECTED, decision="no",
                                          flags=["no-open-copy-known"]))
        self.harvest.job = dataclasses.replace(self.job, screen=dataclasses.replace(self.job.screen, propose_closed=True))
        self.assertEqual(self.harvest.rescreen()["proposed"], 1)
        with open(self.harvest.review_path, encoding="utf-8-sig") as f:
            self.assertEqual({row["key"]: row["decision"] for row in csv.DictReader(f)}["10.1000/shut"], "yes")
        self.harvest.ledger.apply_decisions(self.harvest.review_path)  # what the download does first
        self.assertEqual(self.harvest.ledger.get("10.1000/shut").status, APPROVED)

    def test_papers_a_busy_service_refused_are_tried_again_at_the_end_one_after_another_spaced(self):
        """“Too many requests”: the papers are said to wait, then tried again at the end of the download — one at a
        time, with the slowest pace a service asked for between two of them (Semantic Scholar: 30 s). One still
        refused stays for the next download, which says so."""
        import threading
        import time as clock
        from WebScraping.averageScrap import harvest as module
        for n in (1, 2, 3):
            self.harvest.ledger.add(Candidate(key=f"10.1000/b{n}", doi=f"10.1000/b{n}", title=f"Busy {n}",
                                              status=APPROVED, decision="yes"))
        self.harvest.client._slowed["api.semanticscholar.org"] = 30.0  # what its 429s asked for, this run
        tries, lock, running, most_at_once = {}, threading.Lock(), [0], [0]

        def fetch(downloader, candidate):
            with lock:
                tries[candidate.key] = tries.get(candidate.key, 0) + 1
                later = tries[candidate.key] > 1
                running[0] += 1
                if later:
                    most_at_once[0] = max(most_at_once[0], running[0])
            clock.sleep(0.02)
            with lock:
                running[0] -= 1
            if later and candidate.key != "10.1000/b3":
                return Outcome(candidate.key, DOWNLOADED, service="osti", file=f"{file_stem(candidate.key)}.pdf")
            return Outcome(candidate.key, FAILED, error="osti: HTTP 429", refused=["OSTI"])
        notices, paused = [], []
        self.harvest.on_notice = notices.append
        with mock.patch.object(module.Downloader, "fetch", autospec=True, side_effect=fetch), \
                mock.patch.object(self.harvest.watcher, "wait"), \
                mock.patch.object(self.harvest.client, "pause", side_effect=paused.append):
            results = self.harvest.fetch()
        self.assertEqual((results[DOWNLOADED], results["waiting"]), (2, 1))
        self.assertEqual(most_at_once[0], 1)  # the papers tried again: one after another
        self.assertEqual(paused, [30.0, 30.0])  # between the three of the first round; one paper left after it
        first = notices[0]
        for words in ("3 paper(s) not downloaded yet", "OSTI", "api.semanticscholar.org (one request every 30 s)",
                      "one after another, 30 s apart", "round 1 of 4"):
            self.assertIn(words, first)
        self.assertIn("1 paper(s) still refused", notices[-1])
        self.assertIn("the next “3 · Download” tries them first", notices[-1])
        self.assertEqual(self.harvest.ledger.get("10.1000/b3").attempts, 0)  # a refusal is not a failed try

    def test_every_paper_of_a_download_gets_its_line_in_the_download_log(self):
        """download_log.csv: one line per paper tried — downloaded and from where, not downloaded with why and what
        to do, waiting — in plain words; a later download adds its own run without touching the earlier one."""
        from WebScraping.averageScrap import download_log
        from WebScraping.averageScrap import harvest as module
        for key in ("10.1000/got", "10.1000/shut", "10.1000/busy"):
            self.harvest.ledger.add(Candidate(key=key, doi=key, title=f"Paper {key[-4:]}", status=APPROVED, decision="yes"))

        def fetch(downloader, candidate):
            if candidate.key == "10.1000/got":
                Path(self.job.fetch.folder, "10.1000_got.pdf").write_bytes(b"%PDF-1.4")
                return Outcome(candidate.key, DOWNLOADED, service="osti", file="10.1000_got.pdf")
            if candidate.key == "10.1000/busy":
                return Outcome(candidate.key, FAILED, error="osti: HTTP 429", refused=["OSTI"])
            return Outcome(candidate.key, FAILED, error="publisher: HTTP 403")
        with mock.patch.object(module.Downloader, "fetch", autospec=True, side_effect=fetch), \
                mock.patch.object(self.harvest.watcher, "wait"), mock.patch.object(self.harvest.client, "pause"):
            self.harvest.fetch()
        rows = download_log.last_run(download_log.read(self.job.fetch.folder))
        by_key = {row["key"]: row for row in rows}
        self.assertEqual(set(by_key), {"10.1000/got", "10.1000/shut", "10.1000/busy"})
        self.assertEqual((by_key["10.1000/got"]["result"], by_key["10.1000/got"]["source"]), (download_log.GOT, "osti"))
        shut = by_key["10.1000/shut"]
        self.assertEqual((shut["result"], shut["why"]), (download_log.MISSED, by_hand.BLOCKED))
        self.assertEqual(shut["what_to_do"], by_hand.REASONS[by_hand.BLOCKED])
        self.assertEqual(by_key["10.1000/busy"]["result"], download_log.WAITING)
        with open(download_log.path_of(self.job.fetch.folder), "a", encoding="utf-8") as f:
            f.write("2026-11-20 10:00:00,run,downloaded,10.1000/half")  # a line still being written
        self.assertNotIn("10.1000/half", {row["key"] for row in download_log.read(self.job.fetch.folder)})
        with open(download_log.path_of(self.job.fetch.folder), "a", encoding="utf-8") as f:
            f.write("\n")
        first_run = rows[0]["run"]
        self.harvest.run_id = "a later run"
        download_log.add(self.job.fetch.folder, download_log.entry(self.harvest.ledger.get("10.1000/shut"), "a later run"))
        everything = download_log.read(self.job.fetch.folder)
        self.assertIn(first_run, {row["run"] for row in everything})  # the earlier run is kept
        self.assertEqual([row["key"] for row in download_log.last_run(everything)], ["10.1000/shut"])

    def test_a_paper_only_semantic_scholar_refused_is_filed_not_held_for_the_rounds(self):
        """Semantic Scholar only adds to what the others find: its “too many requests” alone does not make a paper
        wait for the rounds at the end (900 such papers took a day). The paper is filed with what the others
        answered — on the hand list with that reason — the try does not count, and the next download asks again."""
        self.harvest.ledger.add(Candidate(key="10.1000/s2", doi="10.1000/s2", title="Refused by S2", status=APPROVED,
                                          decision="yes"))
        outcome = Outcome("10.1000/s2", FAILED, error="openalex: HTTP 403; publisher: HTTP 403",
                          refused=["Semantic Scholar"])
        self.assertEqual(self.harvest._record(self.harvest.ledger.get("10.1000/s2"), outcome), FAILED)
        paper = self.harvest.ledger.get("10.1000/s2")
        self.assertEqual((paper.status, paper.attempts), (FAILED, 0))
        self.assertIn("not checked: Semantic Scholar refused", paper.error)
        self.assertFalse(paper.error.startswith("waiting"))
        self.assertEqual([row["item"] for row in self.harvest.watcher.pending("download")], [])
        from WebScraping.averageScrap.by_hand import BLOCKED, reason_of
        self.assertEqual(reason_of(paper), BLOCKED)  # its real reason, for the hand list

    def test_a_paper_another_service_refused_too_still_waits(self):
        self.harvest.ledger.add(Candidate(key="10.1000/both", doi="10.1000/both", status=APPROVED, decision="yes"))
        outcome = Outcome("10.1000/both", FAILED, error="osti: HTTP 429", refused=["Semantic Scholar", "OSTI"])
        self.assertEqual(self.harvest._record(self.harvest.ledger.get("10.1000/both"), outcome), "waiting")
        self.assertEqual([row["item"] for row in self.harvest.watcher.pending("download")], ["10.1000/both"])

    def test_a_round_at_the_end_never_runs_longer_than_its_budget(self):
        """At 30 s apart, a round of 30 minutes holds 60 papers; here a budget of 60 s holds 2 of 5: the others are
        left for the next download, which is said."""
        from WebScraping.averageScrap import harvest as module
        for n in range(5):
            self.harvest.ledger.add(Candidate(key=f"10.1000/r{n}", doi=f"10.1000/r{n}", status=APPROVED, decision="yes"))
        self.harvest.client._slowed["osti.gov"] = 30.0
        later = []

        def fetch(downloader, candidate):
            return Outcome(candidate.key, FAILED, error="osti: HTTP 429", refused=["OSTI"])
        real_batch = self.harvest._fetch_batch

        def batch(todo, stop_event, progress_callback, spacing=0.0, **kw):
            if kw.get("later"):
                later.append(len(todo))
            return real_batch(todo, stop_event, progress_callback, **kw, spacing=spacing)
        notices = []
        self.harvest.on_notice = notices.append
        with mock.patch.object(module, "LATER_ROUND_SECONDS", 60), \
                mock.patch.object(module.Downloader, "fetch", autospec=True, side_effect=fetch), \
                mock.patch.object(self.harvest.watcher, "wait"), mock.patch.object(self.harvest.client, "pause"), \
                mock.patch.object(self.harvest, "_fetch_batch", side_effect=batch):
            self.harvest.fetch()
        self.assertTrue(later)
        self.assertTrue(all(n <= 2 for n in later), later)
        self.assertTrue(any("left for the next “3 · Download”" in text for text in notices), notices)

    def test_a_paper_whose_sites_were_all_blocked_keeps_its_tries(self):
        self.harvest.ledger.add(Candidate(key="10.3390/b.1", doi="10.3390/b.1", status=APPROVED, decision="yes"))
        skipped = Outcome("10.3390/b.1", FAILED, error=f"openalex: www.mdpi.com {SITE_BLOCKED_MARK} (HTTP 403), skipped this run",
                          not_asked=True)
        for _ in range(5):
            self.harvest._record(self.harvest.ledger.get("10.3390/b.1"), skipped)
        self.assertEqual(self.harvest.ledger.get("10.3390/b.1").attempts, 0)

    def test_every_paper_not_downloaded_is_listed_with_why_and_what_to_do(self):
        add = self.harvest.ledger.add
        add(Candidate(key="10.3390/open", doi="10.3390/open", title="Open one", oa_status="gold", status=FAILED,
                      error="openalex: HTTP 403; publisher: HTTP 403"))
        add(Candidate(key="10.1016/shut", doi="10.1016/shut", title="Closed one", oa_status="closed", status=CLOSED,
                      error="elsevier: HTTP 403 (not entitled: closed Elsevier papers …)"))
        add(Candidate(key="10.1000/gone", doi="10.1000/gone", title="Not found", status=FAILED, error="openalex: HTTP 404"))
        add(Candidate(key="10.1000/none", doi="10.1000/none", title="No copy", status=CLOSED,
                      error="no legal copy found: needs a manual PDF"))
        add(Candidate(key="10.1000/busy", doi="10.1000/busy", title="Busy", status=FAILED,
                      error="waiting: OSTI refused (too many requests, busy or no answer)"))
        add(Candidate(key="10.3390/saved", doi="10.3390/saved", title="Saved by hand", status=FAILED, error="publisher: HTTP 403"))
        add(Candidate(key="10.1000/got", doi="10.1000/got", title="Got", status=DOWNLOADED))
        Path(self.job.fetch.folder, "10.3390_saved.pdf").write_bytes(b"%PDF-")
        self.assertEqual(self.harvest.write_hand_list(), 5)
        rows = pd.read_csv(Path(self.job.fetch.folder, HAND_LIST), encoding="utf-8-sig", keep_default_na=False)
        self.assertEqual(list(rows.columns), list(by_hand.HAND_COLUMNS))
        self.assertEqual(list(zip(rows["doi"], rows["reason"])), [
            ("10.3390/open", by_hand.BLOCKED), ("10.1016/shut", by_hand.SUBSCRIPTION), ("10.1000/none", by_hand.NO_COPY),
            ("10.1000/gone", by_hand.NOT_FOUND), ("10.1000/busy", by_hand.BUSY)])  # what a person can get at once first
        self.assertEqual(rows["link"][0], "https://doi.org/10.3390/open")
        self.assertIn("browser", rows["what_to_do"][0])
        self.assertIn("university", rows["what_to_do"][1])
        self.assertIn("HTTP 404", rows["detail"][3])
        for key in ("10.3390/open", "10.1016/shut", "10.1000/gone", "10.1000/none", "10.1000/busy"):
            self.harvest.ledger.update(key, status=DOWNLOADED, error="")
        self.assertEqual(self.harvest.write_hand_list(), 0)
        self.assertFalse(Path(self.job.fetch.folder, HAND_LIST).exists())

    def test_a_publishers_first_page_only_means_a_subscription_is_needed(self):
        paper = Candidate(key="10.1016/x", doi="10.1016/x", status=FAILED, error=(
            "elsevier: only the first page (not entitled: the institutional token is set, but …)"))
        self.assertEqual(by_hand.reason_of(paper), by_hand.SUBSCRIPTION)

    def hand_paper(self, key="10.3390/batteries9020137"):
        self.harvest.ledger.add(Candidate(key=key, doi=key, title="Ionic conductivity of the argyrodite Li6PS5Cl solid electrolyte",
                                          oa_status="gold", license="cc-by", status=FAILED, error="publisher: HTTP 403"))
        self.assertEqual(self.harvest.write_hand_list(), 1)

    def pdf_naming(self, doi):
        document = pymupdf.open(stream=self.pdf, filetype="pdf")
        document[0].insert_text((50, 30), f"https://doi.org/{doi}", fontsize=8)
        return document.tobytes()

    def test_a_pdf_saved_by_hand_is_taken_in_by_the_doi_on_its_first_page(self):
        self.hand_paper()
        box = Path(self.harvest.by_hand_folder)
        self.assertTrue(box.is_dir())  # made with the papers folder, for a fresh install too
        (box / "batteries-09-00137.pdf").write_bytes(self.pdf_naming("10.3390/batteries9020137"))
        with self.assertLogs(level="INFO"):
            self.harvest.fetch()
        paper = self.harvest.ledger.get("10.3390/batteries9020137")
        self.assertEqual((paper.status, paper.file), (DOWNLOADED, "10.3390_batteries9020137.pdf"))
        self.assertEqual(list(box.iterdir()), [])  # moved into the papers folder
        sidecar = json.loads(Path(self.job.fetch.folder, "10.3390_batteries9020137.json").read_text(encoding="utf-8"))
        self.assertEqual((sidecar["source_service"], sidecar["source_url"], sidecar["license"]),
                         (by_hand.BY_HAND_SERVICE, "https://doi.org/10.3390/batteries9020137", "cc-by"))
        self.assertFalse(Path(self.job.fetch.folder, HAND_LIST).exists())  # the list is done

    def test_a_pdf_named_after_its_doi_is_taken_in(self):
        self.hand_paper()
        Path(self.harvest.by_hand_folder, "10.3390_batteries9020137.pdf").write_bytes(self.pdf)
        self.assertEqual(by_hand.take_in(self.job.fetch.folder, self.harvest.ledger, self.harvest.hand_list_path), 1)

    def test_a_pdf_citing_another_listed_paper_first_is_taken_in_as_itself(self):
        self.hand_paper()  # 10.3390/batteries9020137, the argyrodite title of make_pdf
        self.harvest.ledger.add(Candidate(key="10.1016/cited.1", doi="10.1016/cited.1", status=FAILED,
                                          title="Grain boundaries of tantalum doped garnet ceramics", error="publisher: HTTP 403"))
        self.harvest.write_hand_list()
        document = pymupdf.open(stream=self.pdf, filetype="pdf")
        document[0].insert_text((50, 20), "As shown in doi:10.1016/cited.1, and here https://doi.org/10.3390/batteries9020137",
                                fontsize=7)
        Path(self.harvest.by_hand_folder, "download.pdf").write_bytes(document.tobytes())
        self.assertEqual(by_hand.take_in(self.job.fetch.folder, self.harvest.ledger, self.harvest.hand_list_path), 1)
        self.assertEqual(self.harvest.ledger.get("10.3390/batteries9020137").status, DOWNLOADED)
        self.assertEqual(self.harvest.ledger.get("10.1016/cited.1").status, FAILED)  # the paper only cited is not it

    def test_a_pdf_of_another_article_or_off_the_list_is_left_where_it_is(self):
        self.hand_paper()
        box = Path(self.harvest.by_hand_folder)
        (box / "wrong.pdf").write_bytes(self.pdf_naming("10.9999/not.on.the.list"))
        other = pymupdf.open(stream=make_pdf(title="Lithium plating on graphite anodes in fast charging"), filetype="pdf")
        other[0].insert_text((50, 30), "doi:10.3390/batteries9020137", fontsize=8)
        (box / "same-doi-other-title.pdf").write_bytes(other.tobytes())
        with self.assertLogs(level="WARNING") as said:
            self.assertEqual(by_hand.take_in(self.job.fetch.folder, self.harvest.ledger, self.harvest.hand_list_path), 0)
        self.assertEqual(sorted(p.name for p in box.iterdir()), ["same-doi-other-title.pdf", "wrong.pdf"])
        self.assertIn("names no DOI", "\n".join(said.output))
        self.assertIn("title", "\n".join(said.output))
        self.assertEqual(self.harvest.ledger.get("10.3390/batteries9020137").status, FAILED)

    def test_the_watcher_waits_in_the_run_only_for_busy_sites_not_for_ones_that_are_down(self):
        from WebScraping.averageScrap.harvest import worth_waiting
        rows = [{"item": "10.1/a", "reason": "OSTI"}, {"item": "10.1/b", "reason": "OSTI, Europe PMC"},
                {"item": "10.1/c", "reason": "Semantic Scholar"}]
        self.assertEqual([r["item"] for r in worth_waiting(rows, {"OSTI"})], ["10.1/b", "10.1/c"])
        self.assertEqual([r["item"] for r in worth_waiting(rows, {"OSTI", "Europe PMC", "Semantic Scholar"})], [])
        self.assertEqual(len(worth_waiting(rows, set())), 3)

    def test_the_review_comes_before_any_download(self):
        code, printed, pipeline = self.run_stage(start="discover")
        self.assertEqual(code, 0)
        self.assertIn("python -m WebScraping --job job.yaml --stage fetch", printed)
        self.assertIn("2 waiting for a decision", printed)
        self.assertEqual(self.session.hits("good.pdf"), 0)
        self.assertEqual(os.listdir(self.job.fetch.folder).count("10.1000_good.pdf"), 0)
        self.assertEqual({c.key: c.decision for c in self.harvest.ledger.all()}, {"10.1000/good": "yes", "10.1000/other": "no"})
        pipeline.assert_not_called()

    def test_a_source_without_a_key_that_refuses_the_search_is_skipped(self):
        self.session.routes.insert(0, ("api.openalex.org/works", FakeResponse(401, b'{"error": "API key required"}')))
        with self.assertLogs(level="WARNING") as said:
            code, _, _ = self.run_stage(start="discover")
        self.assertEqual(code, 0)
        self.assertTrue(any("openalex: it refused the search (HTTP 401)" in line for line in said.output), said.output)

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
        self.session.routes[1] = ("repo.example.org/good.pdf", FakeResponse(404))  # an answer: the file is not there
        self.run_stage(start="discover")
        for expected in (FAILED, FAILED, CLOSED):
            self.run_stage(start="fetch")
            self.assertEqual(self.harvest.ledger.get("10.1000/good").status, expected)

    def test_a_paper_a_busy_site_refuses_waits_on_the_watch_list_and_is_fetched_on_a_later_round(self):
        """HTTP 503 (busy) or 429 is not an answer: the paper is not counted as a failed try, nor closed;
        the watcher fetches it again after a pause, in the same run."""
        good = self.session.routes[1]
        self.session.routes[1] = ("repo.example.org/good.pdf", [FakeResponse(503)] * 4 + [good[1]])
        self.run_stage(start="discover")
        waits = []
        self.harvest.watcher.sleep, self.harvest.watcher.say = waits.append, lambda text: None
        with self.assertLogs(level="INFO") as said:
            results = self.harvest.fetch()
        paper = self.harvest.ledger.get("10.1000/good")
        self.assertEqual((paper.status, paper.attempts), (DOWNLOADED, 1))  # only the try that answered counts
        self.assertEqual((results[DOWNLOADED], results["waiting"]), (1, 0))
        self.assertEqual(sum(waits) / 60, 2)  # one round, after two minutes
        self.assertEqual(self.harvest.ledger.watch_list("download"), [])
        self.assertIn("1 downloaded (1 on a later try)", "\n".join(said.output))

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
        self.assertEqual(self.session.headers["User-Agent"], "MoukhlijMatExtract/1.0.0")
        self.assertNotIn("mailto", self.session.calls[0][1])


# ----------------------------------------------------------------------
# The gate
# ----------------------------------------------------------------------
class GateTests(unittest.TestCase):
    """The terminal gate of the web project: python -m WebScraping.averageScrap."""

    def test_commands(self):
        from WebScraping.averageScrap.about import DEFAULT_JOB
        from WebScraping.averageScrap.cli import parse_args
        run = parse_args(["run", "--job", "j.yaml", "--stage", "fetch", "--yes", "--limit", "5", "-w", "2"])
        self.assertEqual((run.command, run.job, run.stage, run.yes, run.limit, run.workers),
                         ("run", "j.yaml", "fetch", True, 5, 2))
        # The example job unless another is named; no folder of results named: the job's own, found by main().
        default = parse_args(["run"])
        self.assertEqual((default.job, default.output, default.stage), (DEFAULT_JOB, None, "discover"))
        window = parse_args(["gui", "--output", "elsewhere"])
        self.assertEqual((window.command, window.job, window.output), ("gui", None, "elsewhere"))

    def test_without_a_command_it_runs(self):
        from WebScraping.averageScrap import cli
        seen = []
        with mock.patch.object(cli, "run_web", side_effect=lambda args: seen.append((args.job, args.output, args.stage)) or 0), \
                mock.patch.object(cli, "rebuild_if_asked"), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(cli.main(["--job", "j.yaml", "--output", "out", "--stage", "fetch"]), 0)
            # Another job, no --output: its own database, never the default job's (two corpora in one database).
            folder = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, folder, True)
            garnet = os.path.join(folder, "garnet.yaml")
            with open(garnet, "w", encoding="utf-8") as f:
                f.write(dump_job(Job(search=SearchConfig(queries=["garnet"]),
                                     fetch=FetchConfig(folder=os.path.join("WebScraping", "papers_garnet")))))
            self.assertEqual(cli.main(["--job", garnet]), 0)
        self.assertEqual(seen, [(cli.DEFAULT_JOB, cli.DEFAULT_OUTPUT, "discover"), ("j.yaml", "out", "fetch"),
                                (garnet, os.path.join("WebScraping", "web_output_garnet"), "discover")])

    def test_a_job_file_that_cannot_be_read(self):
        from WebScraping.averageScrap import cli
        with mock.patch.object(cli, "print_banner"), mock.patch.object(cli, "rebuild_if_asked"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--job", "no/such/job.yaml"]), 2)

    def test_a_database_of_an_earlier_version_is_rebuilt_not_added_to(self):
        from WebScraping.averageScrap import cli
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out = os.path.join(folder, "out")
        os.makedirs(out)
        pd.DataFrame([{"paper_id": "a.pdf", "property_name": "Migration_Barrier"}]).to_csv(os.path.join(out, "properties.csv"), index=False)
        pd.DataFrame([{"paper_id": "a.pdf", "filename": "a.pdf"}]).to_csv(os.path.join(out, "papers.csv"), index=False)
        runs = []
        with mock.patch.object(cli, "run_web", side_effect=lambda args: runs.append(args) or 0), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()):
            # Nothing is added to the old tables: they are moved aside first, without being asked.
            self.assertEqual(cli.main(["--output", out, "--stage", "extract"]), 0)
        self.assertEqual(len(runs), 1)
        kept, = [name for name in os.listdir(out) if name.startswith("previous_")]
        self.assertEqual(sorted(os.listdir(os.path.join(out, kept))), ["papers.csv", "properties.csv"])  # moved, not deleted


# ----------------------------------------------------------------------
# The shared pipeline and exporter
# ----------------------------------------------------------------------
class SharedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from LocalExtraction.extractor import ExtractorEngine
        from LocalExtraction.ranking import Ranker
        cls.ExtractorEngine, cls.Ranker = ExtractorEngine, Ranker

    def paper(self, text, **kwargs):
        from LocalExtraction.models import ExtractedField, PaperData
        from LocalExtraction.pipeline import NaLiXPipeline
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
        from LocalExtraction.pipeline import NaLiXPipeline
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
        self.assertEqual(paper.metadata["doi"].normalized_value, "no DOI reported by the source")  # not the reference's DOI
        self.assertEqual(paper.metadata["title"].normalized_value, "The Real Title of the Preprint")
        plain = NaLiXPipeline(folder, folder).process_document("arxiv_1.pdf")
        self.assertEqual(plain.metadata["doi"].normalized_value, "10.1016/j.ssi.2019.05.027")  # local mode is unchanged

    def test_batches_then_one_workbook(self):
        from LocalExtraction.exporter import StrictExporter
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
            self.assertEqual(len(pd.read_excel(book, "properties")), csv_rows)
        self.assertEqual(json.loads(Path(folder, "database.json").read_text(encoding="utf-8"))["papers"][0]["origin"], "web")



class UnpaywallEmailTests(unittest.TestCase):
    """Unpaywall answers the same for every real address, and refuses a made-up one (HTTP 422)."""

    def resolver(self, error=None):
        from WebScraping.averageScrap.http import HttpError
        from WebScraping.averageScrap.resolve import Resolver
        client = mock.Mock()
        client.get_json.side_effect = HttpError("https://api.unpaywall.org/v2/x", 422, "use your own email") \
            if error else lambda url, params=None, headers=None: {"best_oa_location": {"url_for_pdf": "https://r.org/p.pdf"}}
        return Resolver(client, ["unpaywall"], contact="test@example.com"), client

    def test_a_refused_email_is_noted_and_not_sent_again(self):
        from WebScraping.averageScrap.ledger import Candidate
        from WebScraping.averageScrap.resolve import REFUSED_EMAIL, email_advice
        resolver, client = self.resolver(error=True)
        with self.assertLogs(level="WARNING") as said:
            for key in ("10.1/a", "10.1/b", "10.1/c"):
                self.assertEqual(list(resolver.options(Candidate(key=key, doi=key))), [])
        self.assertEqual(resolver.email_problem, REFUSED_EMAIL)
        self.assertEqual(client.get_json.call_count, 1)  # asked once, not for every paper
        self.assertEqual(len(said.records), 1)
        self.assertIn("refused the contact e-mail “test@example.com”", email_advice("test@example.com", REFUSED_EMAIL))
        self.assertIn("contact_email in the job file", email_advice("x@y.org", REFUSED_EMAIL, in_job_file=True))

    def test_an_accepted_email_is_no_problem(self):
        from WebScraping.averageScrap.ledger import Candidate
        resolver, _ = self.resolver()
        self.assertEqual([o.url for o in resolver.options(Candidate(key="10.1/a", doi="10.1/a"))], ["https://r.org/p.pdf"])
        self.assertEqual(resolver.email_problem, "")


class DoiListTests(unittest.TestCase):
    """A DOI list (Fetch DOIs) becomes candidates marked yes, for "3 · Download" to fetch their open copies."""

    def test_the_list_becomes_candidates_once(self):
        from WebScraping.averageScrap.harvest import Harvest
        from WebScraping.averageScrap.job import FetchConfig, Job, SearchConfig
        from WebScraping.averageScrap.ledger import NEW
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        listed = os.path.join(folder, "dois.csv")
        with open(listed, "w", encoding="utf-8") as f:
            f.write("doi,title,year,authors,venue\n"
                    "10.1000/A,Garnet conductors,2022,A. B; C. D,Solid State Ionics\n"
                    "https://doi.org/10.1000/b,not listed by OpenAlex or Crossref,not listed,,\n"
                    "not a doi,,,,\n")
        harvest = Harvest(Job(search=SearchConfig(queries=["x"], sources=["openalex"]), fetch=FetchConfig(folder=folder)),
                          os.path.join(folder, "out"))
        self.addCleanup(harvest.ledger.close)
        self.assertEqual(harvest.add_dois(listed), (2, 2))
        a, b = harvest.ledger.get("10.1000/a"), harvest.ledger.get("10.1000/b")
        # New candidates, not marked yes: they are checked like the papers the keywords found.
        self.assertEqual((a.title, a.year, a.journal, a.authors, a.decision, a.status, a.found_by),
                         ("Garnet conductors", 2022, "Solid State Ionics", ["A. B", "C. D"], "", NEW, ["doi list"]))
        self.assertEqual((b.title, b.year), ("", 0))  # "not listed": unknown, not a title
        self.assertEqual(harvest.add_dois(listed), (2, 0))  # a second time: nothing twice

    def test_the_search_takes_the_doi_list_in_and_checks_it_like_the_keyword_results(self):
        """The job's doi_list is taken in by the search; each DOI gets its OpenAlex record (abstract, open
        copy), then the same topic score: only the paper on topic is proposed for download."""
        from WebScraping.averageScrap.harvest import Harvest
        from WebScraping.averageScrap.job import FetchConfig, Job, ScreenConfig, SearchConfig
        from WebScraping.averageScrap.ledger import NEW, NO, YES
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        listed = os.path.join(folder, "dois.csv")
        with open(listed, "w", encoding="utf-8") as f:
            f.write("doi,title,year,authors,venue\n10.1000/on,Garnet conductors,2022,,\n10.1000/off,Water splitting,2023,,\n"
                    "10.1000/later,Unknown to OpenAlex yet,2024,,\n")

        def record(doi, title, abstract):
            return {**WORK, "doi": f"https://doi.org/{doi}", "id": f"https://openalex.org/W{doi[-2:]}", "title": title,
                    "abstract_inverted_index": {w: [i] for i, w in enumerate(abstract.split())}}
        records = [record("10.1000/on", "Garnet conductors", "the activation energy of a solid electrolyte"),
                   record("10.1000/off", "Water splitting", "hydrogen from water with a catalyst")]
        session = FakeSession([("api.openalex.org/works", FakeResponse(200, json_data={"results": records, "meta": {}}))])
        job = Job(search=SearchConfig(queries=["solid electrolyte"], sources=[], abstract_sources=[], doi_list=listed),
                  screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"], review=True),
                  fetch=FetchConfig(folder=folder))
        harvest = Harvest(job, os.path.join(folder, "out"), client=client_for(session))
        self.addCleanup(harvest.ledger.close)
        self.assertEqual(harvest.discover(), 3)
        harvest.screen()
        on, off, later = (harvest.ledger.get(k) for k in ("10.1000/on", "10.1000/off", "10.1000/later"))
        self.assertEqual((on.decision, on.abstract_from), (YES, "openalex"))
        self.assertEqual(off.decision, NO)
        # OpenAlex was asked and did not know it: screened on what the list gave, and not asked again.
        self.assertIn("openalex", later.abstract_asked)
        self.assertNotEqual(later.status, NEW)
        asked = session.hits("api.openalex.org/works")
        harvest.discover()
        self.assertEqual(session.hits("api.openalex.org/works"), asked)

    def test_the_search_runs_fetch_dois_first_and_says_its_steps(self):
        """collect_dois: the search first runs Fetch DOIs (its DOIs go to the list), then asks the keywords,
        then checks the new papers — the DOIs it just collected among them."""
        from WebScraping.Fetch_DOIs import get_dois
        from WebScraping.averageScrap.harvest import Harvest
        from WebScraping.averageScrap.job import FetchConfig, Job, SearchConfig
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        listed = os.path.join(folder, "dois.csv")

        def collect(argv):
            self.assertEqual(argv[:2], ["--out", listed])
            with open(listed, "w", encoding="utf-8") as f:
                f.write("doi,title,year,authors,venue\n10.1000/c1,Collected one,2024,,\n")
            with open(os.path.splitext(listed)[0] + ".txt", "w", encoding="utf-8") as f:
                f.write("10.1000/c1\n")
            print("=== [1/1] solid electrolyte   (new DOIs so far: 1)")
            return 0
        session = FakeSession([("api.openalex.org/works", FakeResponse(200, json_data={"results": [], "meta": {}}))])
        job = Job(search=SearchConfig(queries=["solid electrolyte"], sources=[], abstract_sources=[], doi_list=listed,
                                      collect_dois=True), fetch=FetchConfig(folder=folder))
        harvest = Harvest(job, os.path.join(folder, "out"), client=client_for(session))
        self.addCleanup(harvest.ledger.close)
        steps, lines = [], []
        harvest.on_step, harvest.on_line = steps.append, lines.append
        with mock.patch.object(get_dois, "main", side_effect=collect):
            self.assertEqual(harvest.discover(job_path=""), 1)
        self.assertEqual(steps, ["dois", "keywords", "check"])
        self.assertEqual(lines, ["=== [1/1] solid electrolyte   (new DOIs so far: 1)"])  # what it printed, handed on
        self.assertEqual(harvest.ledger.get("10.1000/c1").found_by, ["doi list"])

    def test_stop_during_fetch_dois_ends_the_search_there(self):
        from LocalExtraction import runcontrol
        from WebScraping.Fetch_DOIs import get_dois
        from WebScraping.averageScrap.harvest import Harvest
        from WebScraping.averageScrap.job import FetchConfig, Job, SearchConfig
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        control = runcontrol.RunControl()
        job = Job(search=SearchConfig(queries=["x"], sources=["doaj"], abstract_sources=[],
                                      doi_list=os.path.join(folder, "dois.csv"), collect_dois=True),
                  fetch=FetchConfig(folder=folder))
        session = FakeSession()
        harvest = Harvest(job, os.path.join(folder, "out"), client=client_for(session))
        self.addCleanup(harvest.ledger.close)
        steps = []
        harvest.on_step = steps.append
        with mock.patch.object(get_dois, "main", side_effect=lambda argv: control.set()), runcontrol.bound(control):
            harvest.discover()
        self.assertEqual(steps, ["dois"])  # Stop pressed during Fetch DOIs: no keyword search
        self.assertEqual(session.hits("doaj.org"), 0)

    def test_a_doi_list_paper_not_looked_up_yet_is_not_scored_on_its_title_alone(self):
        """Stopped (or refused) before its OpenAlex record was looked up, a paper of the DOI list stays new:
        scored on a bare title, it would be declined for good."""
        from WebScraping.averageScrap import screening
        from WebScraping.averageScrap.job import ScreenConfig
        from WebScraping.averageScrap.ledger import NEW, Candidate, Ledger
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ledger = Ledger(os.path.join(folder, "ledger.sqlite"))
        self.addCleanup(ledger.close)
        ledger.add(Candidate(key="10.1/x", doi="10.1/x", title="Garnet", found_by=["doi list"]))
        screening.screen(ledger, ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"]))
        self.assertEqual(ledger.get("10.1/x").status, NEW)


    def test_a_stopped_run_ends_with_the_stage_it_was_in_and_the_next_one_goes_on(self):
        """Ctrl-C in the terminal (mme-web) stops as Stop does in the window: the papers under way are left
        for next time, the finished ones are recorded, the extraction does not start, and the same command
        goes on with the papers left."""
        from LocalExtraction import runcontrol
        from WebScraping.averageScrap.fetch import Outcome
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        harvest = Harvest(Job(search=SearchConfig(queries=["x"], sources=["openalex"]),
                              fetch=FetchConfig(folder=folder, workers=2)), os.path.join(folder, "out"))
        self.addCleanup(harvest.ledger.close)
        harvest.ledger.add_new([Candidate(key=f"10.1/{i}", doi=f"10.1/{i}", decision="yes", status=SCREENED)
                                for i in range(12)])
        harvest.ledger.write_review(harvest.review_path)
        control = runcontrol.RunControl()

        def fetch(downloader, candidate):
            if harvest.ledger.counts().get(DOWNLOADED, 0) >= 3:
                control.set()  # Stop (Ctrl-C) once three are in
            runcontrol.sleep(0.05)
            return Outcome(candidate.key, DOWNLOADED, file=f"{candidate.key[-1]}.pdf", sha256="x", service="pmc", url="u")
        extracted = []
        with mock.patch.object(Downloader, "fetch", fetch), \
                mock.patch.object(Harvest, "extract", lambda self, **k: extracted.append(True)):
            harvest.run(start="fetch", stop_event=control)
            stopped_at = harvest.ledger.counts()
            self.assertEqual(extracted, [])  # stopped: no extraction
            self.assertGreater(stopped_at.get(APPROVED, 0), 0)  # left for next time, not failed
            self.assertNotIn(FAILED, stopped_at)
            harvest.run(start="fetch", stop_event=runcontrol.RunControl())
        self.assertEqual(harvest.ledger.counts(), {DOWNLOADED: 12})
        self.assertEqual(extracted, [True])


if __name__ == "__main__":
    unittest.main()
