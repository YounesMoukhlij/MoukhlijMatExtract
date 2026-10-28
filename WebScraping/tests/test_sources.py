# WebScraping/tests/test_sources.py
"""Offline tests for the search sources, the completion of their records (OpenAlex's record, the
missing abstracts) and the copies the newer services offer. Every network call is answered by the
fake session of test_web, so these never touch a real service."""

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from WebScraping.tests.test_web import FakeResponse, FakeSession, candidate, client_for  # also: offline, sys.path

from WebScraping.averageScrap import abstracts, screening, sources
from WebScraping.averageScrap.doctor import check as check_setup
from WebScraping.averageScrap.harvest import Harvest
from WebScraping.averageScrap.http import HttpError
from WebScraping.averageScrap.job import ABSTRACT_SOURCES, KEY_SIGNUP, SOURCES, ENV_SETTINGS, FetchConfig, Job, ScreenConfig, SearchConfig
from WebScraping.averageScrap.ledger import NEW, REJECTED, SCREENED, Candidate, Ledger, abstract_basis
from WebScraping.averageScrap.resolve import Resolver
from WebScraping.averageScrap.sources.ads import ADS
from WebScraping.averageScrap.sources.common import Source, plain, spell_license
from WebScraping.averageScrap.sources.core import Core, build_query as core_query
from WebScraping.averageScrap.sources.crossref import Crossref
from WebScraping.averageScrap.sources.doaj import DOAJ
from WebScraping.averageScrap.sources.europepmc import EuropePMC
from WebScraping.averageScrap.sources.ieee import IEEE
from WebScraping.averageScrap.sources.jstage import JStage
from WebScraping.averageScrap.sources.openaire import OpenAIRE
from WebScraping.averageScrap.sources.scopus import Scopus, build_query as scopus_query
from WebScraping.averageScrap.sources.semanticscholar import SemanticScholar
from WebScraping.averageScrap.sources.springernature import SpringerNature
from WebScraping.averageScrap.sources.wos import WebOfScience, build_query as wos_query

ABSTRACT = ("We report the ionic conductivity and the activation energy of the argyrodite Li6PS5Cl, a solid "
            "electrolyte for all-solid-state batteries.")
KEYS = {"CORE_API_KEY": "core-key", "SPRINGER_NATURE_API_KEY": "sn-key", "ELSEVIER_API_KEY": "els-key",
        "ADS_API_TOKEN": "ads-token", "IEEE_API_KEY": "ieee-key", "WOS_API_KEY": "wos-key"}


def first(source: Source, query: str = "argyrodite", **kwargs):
    return list(source.search(query, **kwargs))


class KeyedTestCase(unittest.TestCase):
    """Every key in the environment, unless a test removes it."""

    def setUp(self):
        environment = mock.patch.dict(os.environ, KEYS)
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("SEMANTIC_SCHOLAR_API_KEY", "ELSEVIER_INSTTOKEN", "MME_EMAIL"):
            os.environ.pop(name, None)


# ----------------------------------------------------------------------
# What the sources share
# ----------------------------------------------------------------------
class CommonTests(unittest.TestCase):
    def test_markup_goes_and_formulas_stay_whole(self):
        self.assertEqual(plain("<jats:title>Abstract</jats:title><jats:p>Li<jats:sub>6</jats:sub>PS<sub>5</sub>Cl "
                               "conducts for x &lt; 0.5</jats:p>"), "Li6PS5Cl conducts for x < 0.5")
        self.assertEqual(plain("Superionic Li&lt;sub&gt;6&lt;/sub&gt;PS&lt;sub&gt;5&lt;/sub&gt;Br."), "Superionic Li6PS5Br.")
        self.assertEqual(plain(None), "")

    def test_one_spelling_of_a_licence(self):
        for text, spelled in (("http://creativecommons.org/licenses/by-nc/4.0/", "cc-by-nc"), ("CC BY", "cc-by"),
                              ("CCBYNCND", "cc-by-nc-nd"), ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
                              ("Elsevier user licence", "Elsevier user licence")):
            self.assertEqual(spell_license(text), spelled)

    def test_the_job_names_every_source_there_is(self):
        self.assertEqual(set(sources.CLASSES), set(SOURCES))
        for name in ABSTRACT_SOURCES:  # each one can be asked about one paper
            self.assertIsNot(type(sources.make(name, client_for(FakeSession()))).abstract, Source.abstract, name)
        # Every key a source needs is a setting of the window, with the place it is had.
        settings = {name for name, _, _ in ENV_SETTINGS}
        for cls in sources.CLASSES.values():
            if getattr(cls, "key_name", ""):
                self.assertIn(cls.key_name, settings)
                self.assertIn(cls.key_name, KEY_SIGNUP)

    def test_without_its_key_a_source_is_not_used(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for name in ("core", "springernature", "scopus", "ads", "ieee", "wos"):
                self.assertFalse(sources.make(name, client_for(FakeSession())).available(), name)
            for name in ("openalex", "arxiv", "crossref", "semanticscholar", "europepmc", "openaire", "doaj", "jstage"):
                self.assertTrue(sources.make(name, client_for(FakeSession())).available(), name)


# ----------------------------------------------------------------------
# One source each
# ----------------------------------------------------------------------
class SearchTests(KeyedTestCase):
    def test_crossref(self):
        item = {"DOI": "10.1149/1945-7111/ABC0A9", "title": ["Li<sub>6</sub>PS<sub>5</sub>Cl conduction"], "type": "journal-article",
                "abstract": f"<jats:p>{ABSTRACT}</jats:p>", "issued": {"date-parts": [[2021, 3]]},
                "container-title": ["Journal of The Electrochemical Society"], "publisher": "IOP Publishing",
                "author": [{"given": "A.", "family": "Author"}],
                "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/", "content-version": "vor"}],
                "link": [{"URL": "https://iopscience.iop.org/article/10.1149/1945-7111/abc0a9/pdf", "content-type": "application/pdf"},
                         {"URL": "https://iopscience.iop.org/article/10.1149/1945-7111/abc0a9", "content-type": "unspecified"}]}
        session = FakeSession([("api.crossref.org", [FakeResponse(200, json_data={"message": {"items": [item], "next-cursor": "x"}}),
                                                     FakeResponse(200, json_data={"message": {"items": [], "next-cursor": "y"}})])])
        found = first(Crossref(client_for(session), "me@example.org"), years=(2014, 2026), include_preprints=False)
        c = found[0]
        self.assertEqual((c.key, c.title, c.year, c.journal, c.license, c.abstract_from),
                         ("10.1149/1945-7111/abc0a9", "Li6PS5Cl conduction", 2021, "Journal of The Electrochemical Society",
                          "cc-by", "crossref"))
        self.assertEqual(c.abstract, ABSTRACT)
        self.assertEqual(c.oa_urls, ["https://iopscience.iop.org/article/10.1149/1945-7111/abc0a9/pdf"])  # under an open licence
        params = session.calls[0][1]
        self.assertEqual((params["filter"], params["mailto"]), ("type:journal-article,from-pub-date:2014,until-pub-date:2026",
                                                                "me@example.org"))
        self.assertEqual(session.hits("api.crossref.org"), 2)  # the next page came back empty: the end

    def test_semantic_scholar(self):
        paper = {"title": "Superionic argyrodites", "abstract": ABSTRACT, "externalIds": {"ArXiv": "2101.01234"}, "year": 2021,
                 "venue": "arXiv.org", "publicationTypes": None, "openAccessPdf": {"url": "https://arxiv.org/pdf/2101.01234",
                                                                                    "status": "GREEN", "license": "CCBY"}}
        session = FakeSession([("paper/search", FakeResponse(200, json_data={"data": [paper], "next": None}))])
        with mock.patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "s2"}):
            (c,) = first(SemanticScholar(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.key, c.is_preprint, c.oa_status, c.license), ("arxiv:2101.01234", True, "green", "cc-by"))
        self.assertEqual(session.calls[0][2], {"x-api-key": "s2"})
        self.assertEqual(session.calls[0][1]["year"], "2014-2026")
        self.assertEqual(first(SemanticScholar(client_for(session)), include_preprints=False), [])

    def test_europe_pmc(self):
        result = {"doi": "10.26434/chemrxiv-2024-x", "title": "Li&lt;sub&gt;3&lt;/sub&gt;YCl&lt;sub&gt;6&lt;/sub&gt; conduction.",
                  "abstractText": ABSTRACT, "pubYear": "2024", "source": "PPR", "authorString": "Ann A, Bo B.",
                  "license": "cc by-nc",
                  "fullTextUrlList": {"fullTextUrl": [
                      {"documentStyle": "pdf", "availabilityCode": "OA", "url": "https://europepmc.org/articles/PPR1/pdf"},
                      {"documentStyle": "pdf", "availabilityCode": "OA", "url": "https://chemrxiv.example/x.pdf"}]}}
        session = FakeSession([("europepmc", FakeResponse(200, json_data={"resultList": {"result": [result]}, "nextCursorMark": "*"}))])
        (c,) = first(EuropePMC(client_for(session)), years=(2020, 2026))
        self.assertEqual((c.title, c.is_preprint, c.license, c.authors), ("Li3YCl6 conduction", True, "cc-by-nc", ["Ann A", "Bo B"]))
        self.assertEqual(c.oa_urls, ["https://chemrxiv.example/x.pdf"])  # not Europe PMC's own pages: they turn scripts away
        self.assertIn("PUB_YEAR:[2020 TO 2026]", session.calls[0][1]["query"])

    def test_openaire(self):
        product = {"mainTitle": "Lithium transport in argyrodite thin films", "descriptions": ["Short note.", ABSTRACT],
                   "publicationDate": "2023-01-01", "publisher": "NTNU", "pids": [], "authors": [{"fullName": "A, B"}],
                   "bestAccessRight": {"label": "OPEN"}, "openAccessColor": None,
                   "instances": [{"type": "Doctoral thesis", "pids": [{"scheme": "doi", "value": "10.5281/ZENODO.1"}],
                                  "accessRight": {"label": "OPEN"}, "license": "CC BY",
                                  "urls": ["https://doi.org/10.5281/zenodo.1", "https://repo.example.org/handle/1",
                                           "https://repo.example.org/files/thesis.pdf"]}]}
        session = FakeSession([("researchProducts", FakeResponse(200, json_data={"results": [product], "header": {}}))])
        (c,) = first(OpenAIRE(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.doi, c.work_type, c.abstract, c.oa_status, c.license),
                         ("10.5281/zenodo.1", "thesis", ABSTRACT, "green", "cc-by"))
        self.assertEqual((c.oa_urls, c.landing_url), (["https://repo.example.org/files/thesis.pdf"], "https://repo.example.org/handle/1"))
        self.assertEqual(OpenAIRE(client_for(session)).abstract(candidate(doi="10.5281/zenodo.1")), ABSTRACT)

    def test_doaj(self):
        record = {"bibjson": {"title": "Argyrodite cathode composites", "abstract": ABSTRACT, "year": "2024",
                              "identifier": [{"type": "eissn", "id": "2666-8211"}, {"type": "doi", "id": "10.1016/j.ceja.2024.100610"}],
                              "journal": {"title": "Chemical Engineering Journal Advances", "publisher": "Elsevier"},
                              "link": [{"type": "fulltext", "url": "https://www.sciencedirect.com/science/article/pii/S1"}]}}
        session = FakeSession([("doaj.org", FakeResponse(200, json_data={"results": [record]}))])
        (c,) = first(DOAJ(client_for(session)), years=(2023, 2026))
        self.assertEqual((c.doi, c.oa_status, c.landing_url), ("10.1016/j.ceja.2024.100610", "gold",
                                                               "https://www.sciencedirect.com/science/article/pii/S1"))
        self.assertIn("argyrodite%20AND%20bibjson.year%3A%5B2023%20TO%202026%5D", session.calls[0][0])

    def test_jstage(self):
        feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
  <result><status>0</status><message/></result>
  <entry>
    <article_title><en><![CDATA[Ionic conduction in Li<sub>3</sub>PS<sub>4</sub> glass]]></en><ja/></article_title>
    <article_link><en>https://www.jstage.jst.go.jp/article/jcersj2/132/10/132_24062/_article</en></article_link>
    <author><en><name><![CDATA[Masato Torii]]></name><name><![CDATA[Akitoshi Hayashi]]></name></en></author>
    <material_title><en><![CDATA[Journal of the Ceramic Society of Japan]]></en></material_title>
    <pubyear>2024</pubyear><prism:doi>10.2109/jcersj2.24062</prism:doi>
  </entry>
</feed>"""
        session = FakeSession([("jstage", FakeResponse(200, feed))])
        (c,) = first(JStage(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.doi, c.title, c.journal, c.authors, c.year),
                         ("10.2109/jcersj2.24062", "Ionic conduction in Li3PS4 glass", "Journal of the Ceramic Society of Japan",
                          ["Masato Torii", "Akitoshi Hayashi"], 2024))
        self.assertEqual(c.abstract, "")  # J-STAGE gives none: the abstract services are asked
        many = FakeSession([("jstage", FakeResponse(200, feed.replace("<status>0</status>", "<status>WARN_002</status>")))])
        self.assertEqual(len(first(JStage(client_for(many)))), 1)  # "more than it lists": the list is still there
        none = FakeSession([("jstage", FakeResponse(200, feed.replace("<status>0</status>", "<status>ERR_001</status>")))])
        self.assertEqual(first(JStage(client_for(none))), [])
        refused = FakeSession([("jstage", FakeResponse(200, feed.replace("<status>0</status>", "<status>ERR_012</status>")))])
        with self.assertRaises(HttpError):
            first(JStage(client_for(refused)))

    def test_core(self):
        self.assertEqual(core_query('argyrodite "ionic conductivity"'), 'argyrodite AND "ionic conductivity"')
        work = {"doi": "10.1038/nmat4136", "title": "Lithium argyrodites", "abstract": ABSTRACT, "yearPublished": 2015,
                "downloadUrl": "https://core.ac.uk/download/30319204.pdf", "authors": [{"name": "Verbraeken, M"}]}
        old = {**work, "doi": "10.1000/old", "yearPublished": 2001}
        session = FakeSession([("api.core.ac.uk", FakeResponse(200, json_data={"results": [work, old]}))])
        found = first(Core(client_for(session)), years=(2014, 2026))
        self.assertEqual([c.key for c in found], ["10.1038/nmat4136"])  # the years are checked here
        self.assertEqual((found[0].oa_urls, found[0].oa_status), (["https://core.ac.uk/download/30319204.pdf"], "green"))
        self.assertEqual(session.calls[0][2], {"Authorization": "Bearer core-key"})

    def test_springer_nature(self):
        record = {"doi": "10.1007/s10832-017-0071-4", "title": "Garnet conductors", "publicationDate": "2017-05-01",
                  "publicationName": "Journal of Electroceramics", "openaccess": "true",
                  "abstract": {"h1": "Abstract", "p": [ABSTRACT, "More."]},
                  "url": [{"format": "html", "value": "http://link.springer.com/10.1007/s10832-017-0071-4"},
                          {"format": "pdf", "value": "http://link.springer.com/content/pdf/10.1007/s10832-017-0071-4.pdf"}]}
        session = FakeSession([("api.springernature.com", FakeResponse(200, json_data={"records": [record]}))])
        sn = SpringerNature(client_for(session))
        (c,) = first(sn, years=(2014, 2026))
        self.assertEqual((c.abstract, c.oa_status, c.year), (f"{ABSTRACT} More.", "gold", 2017))
        self.assertEqual(session.calls[0][1]["api_key"], "sn-key")
        self.assertEqual(first(sn, years=(2020, 2026)), [])  # its free plan cannot filter by year: done here
        self.assertTrue(sn.applies(candidate(doi="10.1038/s41467-021-1")))
        self.assertFalse(sn.applies(candidate(doi="10.1016/j.ssi.2020.1")))
        self.assertEqual(sn.abstract(candidate(doi="10.1007/s10832-017-0071-4")), f"{ABSTRACT} More.")

    def test_scopus(self):
        self.assertEqual(scopus_query('garnet "ionic conductivity"'), 'TITLE-ABS-KEY(garnet AND "ionic conductivity")')
        entry = {"dc:title": "Garnet LLZO", "prism:doi": "10.1016/j.ssi.2016.01.042", "prism:coverDate": "2016-04-01",
                 "prism:publicationName": "Solid State Ionics", "dc:creator": "Shao C.", "subtypeDescription": "Article"}
        session = FakeSession([
            ("search/scopus", FakeResponse(200, json_data={"search-results": {"entry": [entry]}})),
            ("content/abstract", FakeResponse(200, json_data={"abstracts-retrieval-response": {"coredata": {
                "dc:description": f"{ABSTRACT} © 2016 Elsevier B.V. All rights reserved."}}}))])
        scopus = Scopus(client_for(session))
        (c,) = first(scopus, years=(2014, 2026))
        self.assertEqual((c.doi, c.journal, c.year, c.abstract), ("10.1016/j.ssi.2016.01.042", "Solid State Ionics", 2016, ""))
        self.assertEqual((session.calls[0][1]["date"], session.calls[0][2]["X-ELS-APIKey"]), ("2014-2026", "els-key"))
        self.assertEqual(scopus.abstract(c), ABSTRACT)  # without the copyright line
        empty = FakeSession([("search/scopus", FakeResponse(200, json_data={"search-results": {"entry": [{"error": "Result set was empty"}]}}))])
        self.assertEqual(first(Scopus(client_for(empty))), [])

    def test_ads(self):
        doc = {"bibcode": "2020PhRvM...4a5401X", "doi": ["10.1103/PhysRevMaterials.4.015401", "10.48550/arXiv.1910.01234"],
               "title": ["Li diffusion in argyrodites"], "abstract": ABSTRACT, "year": "2020", "pub": "Physical Review Materials",
               "identifier": ["2020PhRvM...4a5401X", "arXiv:1910.01234"], "doctype": "article"}
        session = FakeSession([("adsabs", FakeResponse(200, json_data={"response": {"docs": [doc]}}))])
        (c,) = first(ADS(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.doi, c.arxiv_id, c.is_preprint, c.journal), ("10.1103/physrevmaterials.4.015401", "1910.01234",
                                                                         False, "Physical Review Materials"))
        self.assertEqual(session.calls[0][1]["q"], "abs:(argyrodite) year:2014-2026")
        self.assertEqual(session.calls[0][2], {"Authorization": "Bearer ads-token"})

    def test_ieee(self):
        articles = [{"doi": "10.1109/TEC.2021.1", "title": "Solid-state battery model", "abstract": ABSTRACT,
                     "publication_year": 2021, "content_type": "Journals", "access_type": "OPEN_ACCESS",
                     "authors": {"authors": [{"full_name": "A. B"}]}},
                    {"doi": "10.1109/IEEESTD.2020.1", "title": "A standard", "content_type": "Standards"}]
        session = FakeSession([("ieeexploreapi", FakeResponse(200, json_data={"articles": articles}))])
        found = first(IEEE(client_for(session)), years=(2014, 2026))
        self.assertEqual([(c.key, c.oa_status) for c in found], [("10.1109/tec.2021.1", "gold")])  # not the standard
        self.assertEqual(session.calls[0][1]["apikey"], "ieee-key")
        self.assertFalse(IEEE(client_for(session)).applies(candidate(doi="10.1016/j.ssi.2020.1")))

    def test_web_of_science(self):
        self.assertEqual(wos_query("garnet LLZO", (2014, 2026)), "TS=(garnet AND LLZO) AND PY=(2014-2026)")
        hit = {"title": "LLZO garnets", "types": ["Review"], "source": {"sourceTitle": "J MATER CHEM A", "publishYear": 2022},
               "identifiers": {"doi": "10.1039/D1TA10966A"}, "names": {"authors": [{"displayName": "Doe, J"}]}}
        session = FakeSession([("wos-starter", FakeResponse(200, json_data={"hits": [hit]}))])
        (c,) = first(WebOfScience(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.key, c.work_type, c.year, c.authors), ("10.1039/d1ta10966a", "review", 2022, ["Doe, J"]))
        self.assertEqual(session.calls[0][2], {"X-ApiKey": "wos-key"})


# ----------------------------------------------------------------------
# Completing the records
# ----------------------------------------------------------------------
class CompletionTests(KeyedTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.ledger = Ledger(os.path.join(folder, "ledger.sqlite"))
        self.addCleanup(self.ledger.close)

    def test_an_abstract_comes_with_the_name_of_who_gave_it(self):
        self.ledger.add(Candidate(key="10.1/a", doi="10.1/a", title="T", found_by=["scopus: q"]))
        self.ledger.add(Candidate(key="10.1/a", doi="10.1/a", abstract=ABSTRACT, abstract_from="crossref", found_by=["crossref: q"]))
        self.ledger.add(Candidate(key="10.1/a", doi="10.1/a", abstract="Another abstract " * 9, abstract_from="core"))
        c = self.ledger.get("10.1/a")
        self.assertEqual((c.abstract, c.abstract_from, abstract_basis(c)), (ABSTRACT, "crossref", "crossref"))
        # A paper filed before the name was recorded: its first source's, said to be inferred.
        self.assertEqual(abstract_basis(Candidate(key="k", abstract=ABSTRACT, found_by=["openalex: q"])),
                         "openalex (inferred: the first source that found it)")
        self.assertEqual(abstract_basis(Candidate(key="k", abstract_asked=["openaire", "crossref"])),
                         "none found (asked: openaire, crossref)")
        self.assertEqual(abstract_basis(Candidate(key="k")), "none in the search record (not asked yet)")

    def test_openalex_completes_what_another_source_found(self):
        self.ledger.add(Candidate(key="10.1000/a", doi="10.1000/a", title="Garnet", found_by=["scopus: q"]))
        work = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/a", "title": "Garnet", "type": "article",
                "open_access": {"is_oa": True, "oa_status": "gold"}, "is_retracted": False,
                "best_oa_location": {"pdf_url": "https://pub.example.org/a.pdf", "landing_page_url": "https://pub.example.org/a"}}
        session = FakeSession([("api.openalex.org/works", FakeResponse(200, json_data={"results": [work]}))])
        self.assertEqual(abstracts.complete_from_openalex(self.ledger, client_for(session)), 1)
        c = self.ledger.get("10.1000/a")
        self.assertEqual((c.openalex_id, c.oa_status, c.oa_urls, c.found_by), ("W1", "gold", ["https://pub.example.org/a.pdf"],
                                                                               ["scopus: q"]))  # a lookup, not a search
        self.assertEqual(session.calls[0][1]["filter"], "doi:10.1000/a")

    def test_the_missing_abstracts_are_asked_for_in_order_and_once(self):
        self.ledger.add(Candidate(key="10.1016/j.a", doi="10.1016/j.a", title="Argyrodite electrolyte", found_by=["openalex: q"]))
        session = FakeSession([
            ("api.openaire.eu", FakeResponse(200, json_data={"results": []})),            # it does not know the paper
            ("api.crossref.org", FakeResponse(200, json_data={"message": {"abstract": ""}})),
            ("api.elsevier.com", FakeResponse(200, json_data={"abstracts-retrieval-response": {"coredata": {"dc:description": ABSTRACT}}}))])
        finder = abstracts.AbstractFinder(client_for(session), ["openaire", "crossref", "springernature", "scopus", "core"])
        self.assertEqual(abstracts.fill(self.ledger, finder), 1)
        c = self.ledger.get("10.1016/j.a")
        self.assertEqual((c.abstract, c.abstract_from, c.abstract_asked), (ABSTRACT, "scopus", ["openaire", "crossref", "scopus"]))
        self.assertEqual(session.hits("springernature"), 0)  # an Elsevier paper is not Springer Nature's
        self.assertEqual(session.hits("core.ac.uk"), 0)       # found before it was CORE's turn
        self.assertEqual(abstracts.fill(self.ledger, finder), 0)  # nobody is asked twice

    def test_a_service_that_refuses_is_left_alone_and_asked_again_next_run(self):
        for n in range(3):
            self.ledger.add(Candidate(key=f"10.1016/j.{n}", doi=f"10.1016/j.{n}", title="Garnet"))
        session = FakeSession([("api.elsevier.com", FakeResponse(401))])
        finder = abstracts.AbstractFinder(client_for(session), ["scopus"])
        with self.assertLogs(level="WARNING") as logs:
            self.assertEqual(abstracts.fill(self.ledger, finder, workers=1), 0)
        self.assertEqual(session.hits("api.elsevier.com"), 1)
        self.assertIn("university's network", "\n".join(logs.output))
        self.assertEqual([c.abstract_asked for c in self.ledger.all()], [[], [], []])  # not counted as asked

    def test_a_paper_declined_for_want_of_an_abstract_is_screened_again(self):
        cfg = ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"], review=False)
        self.ledger.add(Candidate(key="10.1016/j.a", doi="10.1016/j.a", title="A sulfide solid electrolyte", oa_status="gold",
                                  found_by=["openalex: q"]))
        screening.screen(self.ledger, cfg, approve=True)
        self.assertEqual(self.ledger.get("10.1016/j.a").status, REJECTED)  # no property word in its title
        session = FakeSession([("api.openaire.eu", FakeResponse(200, json_data={"results": [{"descriptions": [ABSTRACT]}]}))])
        abstracts.fill(self.ledger, abstracts.AbstractFinder(client_for(session), ["openaire"]))
        self.assertEqual(self.ledger.get("10.1016/j.a").status, NEW)
        screening.screen(self.ledger, cfg, approve=True)
        c = self.ledger.get("10.1016/j.a")
        self.assertEqual((c.decision, c.why), ("yes", "topic: solid electrolyte (title); property: activation energy (abstract)"))


# ----------------------------------------------------------------------
# The copies the newer services offer
# ----------------------------------------------------------------------
class ResolverSourceTests(KeyedTestCase):
    def options(self, c, names, session):
        return [(o.service, o.url, o.landing) for o in Resolver(client_for(session), names).options(c)]

    def test_crossref_offers_the_text_mining_links_a_page_can_be_followed_from(self):
        message = {"license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}], "link": [
            {"URL": "https://api.elsevier.com/content/article/PII:S1?httpAccept=text/xml", "content-type": "text/xml",
             "intended-application": "text-mining"},
            {"URL": "https://api.elsevier.com/content/article/PII:S1?httpAccept=application/pdf", "content-type": "application/pdf",
             "intended-application": "text-mining"},
            {"URL": "https://link.springer.com/content/pdf/10.1007/x.pdf", "content-type": "application/pdf",
             "intended-application": "text-mining"},
            {"URL": "https://link.springer.com/article/10.1007/x", "content-type": "text/html", "intended-application": "text-mining"},
            {"URL": "https://link.springer.com/x.pdf", "content-type": "application/pdf", "intended-application": "similarity-checking"}]}
        session = FakeSession([("api.crossref.org", FakeResponse(200, json_data={"message": message}))])
        self.assertEqual(self.options(candidate(doi="10.1007/x"), ["crossref"], session), [
            ("crossref", "https://link.springer.com/content/pdf/10.1007/x.pdf", False),
            ("crossref", "https://link.springer.com/article/10.1007/x", True)])  # Elsevier's need its key: its own source

    def test_core_offers_the_repository_copies_of_the_paper(self):
        results = [{"doi": "10.1000/test", "downloadUrl": "https://core.ac.uk/download/1.pdf"},
                   {"doi": "10.1000/other", "downloadUrl": "https://core.ac.uk/download/2.pdf"}]
        session = FakeSession([("api.core.ac.uk", FakeResponse(200, json_data={"results": results}))])
        self.assertEqual(self.options(candidate(), ["core"], session), [("core", "https://core.ac.uk/download/1.pdf", True)])
        with mock.patch.dict(os.environ, {"CORE_API_KEY": ""}):
            self.assertEqual(self.options(candidate(), ["core"], FakeSession()), [])  # no key, not asked

    def test_ads_offers_the_arxiv_version_and_its_own_scan(self):
        doc = {"bibcode": "1999SSI...1..1X", "identifier": ["arXiv:cond-mat/9901001"], "esources": ["ADS_PDF", "PUB_PDF"]}
        session = FakeSession([("adsabs", FakeResponse(200, json_data={"response": {"docs": [doc]}}))])
        self.assertEqual(self.options(candidate(), ["ads"], session), [
            ("ads", "https://arxiv.org/pdf/cond-mat/9901001", False),
            ("ads", "https://ui.adsabs.harvard.edu/link_gateway/1999SSI...1..1X/ADS_PDF", False)])


# ----------------------------------------------------------------------
# The whole discovery, and the check of the setup
# ----------------------------------------------------------------------
class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_a_paper_another_source_found_is_completed_then_screened(self):
        item = {"DOI": "10.1016/j.ssi.2020.1", "title": ["Garnet solid electrolyte"], "type": "journal-article",
                "issued": {"date-parts": [[2020]]}}
        work = {"id": "https://openalex.org/W9", "doi": "https://doi.org/10.1016/j.ssi.2020.1", "title": "Garnet solid electrolyte",
                "type": "article", "open_access": {"is_oa": True, "oa_status": "green"},
                "best_oa_location": {"pdf_url": "https://repo.example.org/g.pdf"}}
        session = FakeSession([
            ("api.crossref.org", FakeResponse(200, json_data={"message": {"items": [item]}})),
            ("api.openalex.org/works", FakeResponse(200, json_data={"results": [work]})),
            ("api.openaire.eu", FakeResponse(200, json_data={"results": [{"descriptions": [ABSTRACT]}]}))])
        job = Job(search=SearchConfig(queries=["garnet"], sources=["crossref", "core"], abstract_sources=["openaire"]),
                  screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"], review=True),
                  fetch=FetchConfig(folder=os.path.join(self.root, "papers"), sources=["openalex"]))
        harvest = Harvest(job, os.path.join(self.root, "out"), client=client_for(session))
        self.addCleanup(harvest.ledger.close)
        with self.assertLogs(level="INFO") as logs:
            self.assertEqual(harvest.discover(), 1)
        self.assertIn("core: skipped — CORE_API_KEY is not set", "\n".join(logs.output))
        self.assertEqual(session.hits("core.ac.uk"), 0)
        harvest.screen()
        c = harvest.ledger.get("10.1016/j.ssi.2020.1")
        self.assertEqual((c.status, c.decision, c.access, c.abstract_from), (SCREENED, "yes", "open", "openaire"))

    def test_the_check_says_which_key_is_missing_and_where_it_is_had(self):
        session = FakeSession([("api.openalex.org", FakeResponse(200, json_data={})), ("export.arxiv.org", FakeResponse(200)),
                               ("api.crossref.org", FakeResponse(200, json_data={"message": {"items": []}})),
                               ("api.elsevier.com/content/search", FakeResponse(200, json_data={"search-results": {"entry": []}})),
                               ("api.elsevier.com/content/abstract", FakeResponse(401))])
        job = Job(search=SearchConfig(queries=["a"], sources=["openalex", "crossref", "core", "scopus"], abstract_sources=["scopus"]),
                  fetch=FetchConfig(folder=os.path.join(self.root, "papers"), sources=["openalex"]))
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.dict(os.environ, {"ELSEVIER_API_KEY": "els-key"}):
            check_setup(job, client_for(session))
        printed = out.getvalue()
        self.assertIn("[ok] Crossref: reachable", printed)
        self.assertIn("[!!] CORE: CORE_API_KEY is not set, so it is skipped. A key is free: https://core.ac.uk/services/api", printed)
        self.assertIn("[ok] Scopus: the key works", printed)
        self.assertIn("[!!] Scopus abstracts: HTTP 401 (only on your university's network, or with ELSEVIER_INSTTOKEN)", printed)


if __name__ == "__main__":
    unittest.main()
