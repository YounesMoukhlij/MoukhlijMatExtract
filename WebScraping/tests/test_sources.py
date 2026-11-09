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

from WebScraping.tests.test_web import WORK, FakeResponse, FakeSession, candidate, client_for  # also: offline, sys.path

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
from WebScraping.averageScrap.sources.openalex import OpenAlex
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
                              ("cc-by-4.0", "cc-by"), ("cc-by-nc-sa-4.0", "cc-by-nc-sa"), ("cc0-1.0", "cc0"),
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
    def test_openalex_pages_past_the_first_only_with_a_key(self):
        works = [{**WORK, "doi": f"https://doi.org/10.1000/{n}"} for n in range(3)]
        pages = [FakeResponse(200, json_data={"results": works[:2], "meta": {"next_cursor": "page-2"}}),
                 FakeResponse(200, json_data={"results": works[2:], "meta": {"next_cursor": None}})]
        os.environ.pop("OPENALEX_API_KEY", None)
        session = FakeSession([("api.openalex.org/works", list(pages))])
        self.assertEqual(len(first(OpenAlex(client_for(session)), limit=200)), 2)
        self.assertEqual(session.hits("api.openalex.org"), 1)  # OpenAlex refuses (HTTP 401) a second page without a key
        session = FakeSession([("api.openalex.org/works", list(pages))])
        self.assertEqual(len(first(OpenAlex(client_for(session), api_key="key"), limit=200)), 3)
        self.assertEqual(session.hits("api.openalex.org"), 2)

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

    def test_arxiv_goes_on_through_openalex_when_its_search_says_too_many_requests(self):
        from WebScraping.averageScrap.sources.arxiv import ArXiv
        work = {"id": "https://openalex.org/W1", "title": "Li6PS5Cl argyrodite conductivity", "publication_year": 2024,
                "type": "preprint", "doi": "https://doi.org/10.48550/arxiv.2407.15258",
                "locations": [{"source": {"id": "https://openalex.org/S4306400194"}, "landing_page_url": "http://arxiv.org/abs/2407.15258"}],
                "open_access": {"is_oa": True, "oa_status": "green"}}
        session = FakeSession([("export.arxiv.org", FakeResponse(429)),
                               ("api.openalex.org/works", FakeResponse(200, json_data={"results": [work], "meta": {}}))])
        source = ArXiv(client_for(session), ["cond-mat.mtrl-sci"])
        with self.assertLogs(level="WARNING") as said:
            (c,) = list(source.search("argyrodite", (2014, 2026), 50))
        self.assertEqual((c.arxiv_id, c.found_by), ("2407.15258", ["arxiv: argyrodite (through OpenAlex)"]))
        self.assertIn("https://arxiv.org/pdf/2407.15258", c.oa_urls)
        self.assertIn("locations.source.id:S4306400194", session.calls[-1][1]["filter"])
        self.assertTrue(any("OpenAlex's copy of the arXiv catalogue" in line for line in said.output))
        self.assertEqual(session.hits("export.arxiv.org"), 1)  # asked once, not four times: no pauses
        list(source.search("garnet", None, 50))
        self.assertEqual(session.hits("export.arxiv.org"), 1)  # the rest of the run goes to OpenAlex

    def _watched_harvest(self, session, queries):
        harvest = Harvest(Job(search=SearchConfig(queries=queries, sources=["doaj"], abstract_sources=[]),
                              fetch=FetchConfig(folder=os.path.join(self.root, "papers"))),
                          os.path.join(self.root, "out"), client=client_for(session))
        self.addCleanup(harvest.ledger.close)
        self.waits = []
        harvest.watcher.sleep = self.waits.append
        harvest.watcher.say = lambda text: None
        return harvest

    def test_the_watcher_keeps_the_searches_a_site_refuses_and_asks_again_in_rounds(self):
        queries = [f"query {n}" for n in range(10)]
        session = FakeSession([("doaj.org", FakeResponse(429))])  # a site that never lets up
        harvest = self._watched_harvest(session, queries)
        with self.assertLogs(level="INFO") as said:
            harvest.discover()
        # First pass: three searches refused (each asked four times by the client), the other seven not asked;
        # then four rounds — after 2, 5, 10 and 15 minutes — of two tries each.
        self.assertEqual(session.hits("doaj.org"), 3 * 4 + 4 * 2 * 4)
        self.assertEqual(sum(self.waits) / 60, 2 + 5 + 10 + 15)
        waiting = harvest.ledger.watch_list("search")
        self.assertEqual(sorted(row["item"] for row in waiting), sorted(queries))  # all kept for the next run
        self.assertIsNone(harvest.ledger.searched("doaj|query 0|None|True", 200))
        report = "\n".join(said.output)
        self.assertIn("searches (keyword × source): 11 asked, 0 answered, 11 refused", report)
        self.assertIn("waiting on the watch list: 10 searches (10 keywords)", report)

    def test_a_search_refused_then_answered_on_a_later_round_comes_off_the_watch_list(self):
        record = {"bibjson": {"title": "Argyrodite electrolytes", "abstract": ABSTRACT, "year": "2024",
                              "identifier": [{"type": "doi", "id": "10.1/watch"}]}}
        answers = [FakeResponse(429)] * 4 + [FakeResponse(200, json_data={"results": [record]})]
        session = FakeSession([("doaj.org", answers)])
        harvest = self._watched_harvest(session, ["argyrodite"])
        with self.assertLogs(level="INFO") as said:
            added = harvest.discover()
        self.assertEqual(added, 1)
        self.assertEqual(self.waits and sum(self.waits) / 60, 2)  # one round was enough
        self.assertEqual(harvest.ledger.watch_list("search"), [])
        self.assertIsNotNone(harvest.ledger.searched("doaj|argyrodite|None|True", 200))
        self.assertIn("1 answered on a later try", "\n".join(said.output))

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


# ----------------------------------------------------------------------
# The repositories, preprint servers, national platforms and large indexes added later. Each record
# below is the shape the service gave (trimmed), from a real answer.
# ----------------------------------------------------------------------
class AddedSourceTests(KeyedTestCase):
    def setUp(self):
        super().setUp()
        os.environ.update({"LENS_API_TOKEN": "lens-token", "DIMENSIONS_API_KEY": "dim-key", "BASE_ACCESS": "yes"})

    def test_zenodo_keeps_papers_with_their_pdf_and_leaves_out_the_rest(self):
        from WebScraping.averageScrap.sources.zenodo import Zenodo
        paper = {"doi": "10.1039/D4YA00618F", "links": {"self_html": "https://zenodo.org/records/15862968"},
                 "metadata": {"title": "Halide and sulfide electrolytes", "publication_date": "2025-02-12", "description": ABSTRACT,
                              "access_right": "open", "license": {"id": "cc-by-4.0"}, "creators": [{"name": "Doe, J."}],
                              "resource_type": {"type": "publication", "subtype": "article"}},
                 "files": [{"key": "d4ya00618f.pdf", "links": {"self": "https://zenodo.org/api/records/15862968/files/d4ya00618f.pdf/content"}},
                           {"key": "data.csv", "links": {"self": "https://zenodo.org/x/data.csv"}}]}
        review = {**paper, "doi": "10.5281/zenodo.1", "metadata": {**paper["metadata"], "resource_type": {"subtype": "peerreview"}}}
        session = FakeSession([("zenodo.org/api/records", FakeResponse(200, json_data={"hits": {"hits": [paper, review]}}))])
        (c,) = first(Zenodo(client_for(session)), years=(2020, 2026))
        self.assertEqual((c.doi, c.oa_status, c.license, c.abstract_from), ("10.1039/d4ya00618f", "green", "cc-by", "zenodo"))
        self.assertEqual(c.oa_urls, ["https://zenodo.org/api/records/15862968/files/d4ya00618f.pdf/content"])
        self.assertIn("publication_date:[2020-01-01 TO 2026-12-31]", session.calls[0][1]["q"])

    def test_datacite_files_the_repository_copy_and_leaves_arxiv_to_arxiv(self):
        from WebScraping.averageScrap.sources.datacite import DataCite
        record = {"id": "10.34734/fzj-2026-04397", "attributes": {
            "doi": "10.34734/fzj-2026-04397", "titles": [{"title": "Extrinsic anion vacancies in $Li_6PS_5Cl$"}],
            "publicationYear": 2026, "publisher": "Forschungszentrum Jülich", "url": "https://juser.fz-juelich.de/record/1060971",
            "types": {"resourceTypeGeneral": "Text", "resourceType": "Journal article"},
            "descriptions": [{"descriptionType": "Abstract", "description": ABSTRACT}],
            "rightsList": [{"rightsUri": "info:eu-repo/semantics/openAccess"}],
            "relatedIdentifiers": [{"relationType": "IsVariantFormOf", "relatedIdentifier": "10.1021/acsaem.6c02127",
                                    "relatedIdentifierType": "DOI"}]}}
        arxiv = {"id": "10.48550/arxiv.2411.06804", "attributes": {"doi": "10.48550/arXiv.2411.06804",
                                                                     "titles": [{"title": "A preprint"}], "publicationYear": 2024}}
        session = FakeSession([("api.datacite.org", FakeResponse(200, json_data={"data": [record, arxiv]}))])
        c, preprint = first(DataCite(client_for(session)), years=(2014, 2026))
        self.assertEqual((c.doi, c.work_type, c.oa_status, c.copy_pages), ("10.34734/fzj-2026-04397", "article", "green",
                                                                          ["https://juser.fz-juelich.de/record/1060971"]))
        self.assertEqual((preprint.doi, preprint.arxiv_id, preprint.key), ("", "2411.06804", "arxiv:2411.06804"))
        self.assertEqual(session.calls[0][1]["published"], "2014,2026")

    def test_plos_asks_for_every_word_in_the_title_or_abstract_and_offers_the_printable_pdf(self):
        from WebScraping.averageScrap.sources.plos import PLOS, build_query
        self.assertEqual(build_query('argyrodite "ionic conductivity"'),
                         'title:(argyrodite AND "ionic conductivity") OR abstract:(argyrodite AND "ionic conductivity")')
        doc = {"id": "10.1371/journal.pone.0049182", "title_display": "Li K-edge spectroscopy of Li<sub>2</sub>O<sub>2</sub>",
               "abstract": ["\n  " + ABSTRACT], "publication_date": "2012-11-07T00:00:00Z", "journal": "PLoS ONE",
               "author_display": ["Ruimin Qiao"], "article_type": "Research Article"}
        session = FakeSession([("api.plos.org", FakeResponse(200, json_data={"response": {"docs": [doc]}}))])
        (c,) = first(PLOS(client_for(session)))
        self.assertEqual((c.title, c.oa_status, c.license), ("Li K-edge spectroscopy of Li2O2", "gold", "cc-by"))
        self.assertEqual(c.oa_urls, ["https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0049182&type=printable"])
        self.assertIn("doc_type:full", session.calls[0][1]["fq"])

    def test_ntrs_offers_the_pdf_nasa_released_for_public_use(self):
        from WebScraping.averageScrap.sources.ntrs import NTRS
        record = {"id": 20110013625, "title": "Self-Passivating Lithium/Solid Electrolyte/Iodine Cells", "abstract": ABSTRACT,
                  "stiType": "OTHER", "created": "2013-08-25T07:44:00", "downloadsAvailable": True,
                  "copyright": {"determinationType": "PUBLIC_USE_PERMITTED"},
                  "publications": [{"publicationName": "NASA Tech Briefs", "publicationDate": "2006-12-01T00:00:00"}],
                  "authorAffiliations": [{"meta": {"author": {"name": "Bugga, Ratnakumar"}}}],
                  "downloads": [{"mimetype": "application/pdf", "links": {"pdf": "/api/citations/20110013625/downloads/20110013625.pdf"}}]}
        session = FakeSession([("ntrs.nasa.gov", FakeResponse(200, json_data={"results": [record]}))])
        (c,) = first(NTRS(client_for(session)))
        self.assertEqual((c.year, c.journal, c.authors, c.doi), (2006, "NASA Tech Briefs", ["Bugga, Ratnakumar"], ""))
        self.assertEqual(c.oa_urls, ["https://ntrs.nasa.gov/api/citations/20110013625/downloads/20110013625.pdf"])

    def test_figshare_leaves_out_supporting_information_and_reads_the_record_of_each_paper(self):
        from WebScraping.averageScrap.sources.figshare import Figshare
        items = [{"id": 1, "doi": "10.1021/acs.chemmater.6c01878.s001", "defined_type": 6},  # an article's supporting information
                 {"id": 2, "doi": "", "defined_type": 3},                                   # a dataset
                 {"id": 3, "doi": "10.25394/PGS.34751169.v1", "defined_type": 8}]           # a thesis
        thesis = {"id": 3, "doi": "10.25394/PGS.34751169.v1", "defined_type": 8, "title": "Instability at solid-state interfaces",
                  "description": ABSTRACT, "published_date": "2026-09-01T00:00:00Z", "url_public_html": "https://hammer.purdue.edu/x/3",
                  "license": {"url": "https://creativecommons.org/licenses/by/4.0/"}, "authors": [{"full_name": "A. Student"}],
                  "files": [{"name": "thesis.pdf", "download_url": "https://ndownloader.figshare.com/files/9"}]}
        session = FakeSession([("articles/search", FakeResponse(200, json_data=items)),
                               ("api.figshare.com/v2/articles/3", FakeResponse(200, json_data=thesis))])
        (c,) = first(Figshare(client_for(session)))
        self.assertEqual((c.work_type, c.license, c.oa_urls), ("thesis", "cc-by", ["https://ndownloader.figshare.com/files/9"]))
        self.assertEqual(session.hits("v2/articles/1"), 0)  # the supporting information is not even looked at

    def test_osf_takes_the_preprints_osf_hosts_with_their_file(self):
        from WebScraping.averageScrap.sources.osf import OSFPreprints
        record = {"@id": "https://osf.io/fszk6", "title": [{"@value": "MgHf4P6O24 electrolyte in a Mg sensor"}],
                  "description": [{"@value": ABSTRACT}], "dateCreated": [{"@value": "2020-02-15"}],
                  "identifier": [{"@value": "https://doi.org/10.1149/osf.io/fszk6"}, {"@value": "https://osf.io/fszk6"}],
                  "publisher": [{"name": [{"@value": "ECSarXiv"}]}], "creator": [{"name": [{"@value": "Mohammed Adamu"}]}],
                  "rights": [{"@id": "https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode"}]}
        elsewhere = {**record, "@id": "https://example.org/x"}
        session = FakeSession([("share.osf.io", FakeResponse(200, json_data={"data": [record, elsewhere], "links": {}}))])
        (c,) = first(OSFPreprints(client_for(session)))
        self.assertEqual((c.doi, c.journal, c.is_preprint, c.license), ("10.1149/osf.io/fszk6", "ECSarXiv", True, "cc-by-nc-nd"))
        self.assertEqual(c.oa_urls, ["https://osf.io/fszk6/download"])
        self.assertEqual(first(OSFPreprints(client_for(session)), include_preprints=False), [])

    def test_la_referencia_keeps_the_repository_page_of_an_open_paper(self):
        from WebScraping.averageScrap.sources.lareferencia import LAReferencia
        record = {"title": "LATP thin film electrolytes", "urls": [{"url": "http://zaguan.unizar.es/record/119656"}],
                  "publicationDates": ["2021"], "formats": ["article"], "summary": [ABSTRACT],
                  "authors": {"primary": {"A. Author": {}}, "secondary": {}},
                  "rawData": {"eu_rights_str_mv": ["openAccess"], "doi_str_mv": ["10.1016/j.x.2021.1"], "network_name_str": "España"}}
        session = FakeSession([("lareferencia", FakeResponse(200, json_data={"records": [record]}))])
        (c,) = first(LAReferencia(client_for(session)))
        self.assertEqual((c.doi, c.oa_status, c.copy_pages), ("10.1016/j.x.2021.1", "green", ["http://zaguan.unizar.es/record/119656"]))

    def test_theses_fr_takes_defended_theses_with_their_abstract_and_public_text(self):
        from WebScraping.averageScrap.sources.thesesfr import ThesesFr
        found = {"theses": [{"nnt": "2021NORMC251", "status": "soutenue", "dateSoutenance": "09/12/2021",
                             "titreEN": "Discovery of new ionic conductor", "auteurs": [{"prenom": "A.", "nom": "Student"}],
                             "etabSoutenanceN": "Normandie"},
                            {"nnt": None, "status": "enCours", "titreEN": "Not defended yet"}]}
        details = {"nnt": "2021NORMC251", "titres": {"en": "Discovery of new ionic conductor for all solid-state battery"},
                   "resumes": {"en": ABSTRACT}, "accessible": "oui", "doi": "10.70675/abc"}
        session = FakeSession([("recherche", FakeResponse(200, json_data=found)), ("these/2021NORMC251", FakeResponse(200, json_data=details))])
        (c,) = first(ThesesFr(client_for(session)), years=(2015, 2026))
        self.assertEqual((c.work_type, c.year, c.doi, c.abstract_from), ("thesis", 2021, "10.70675/abc", "theses.fr"))
        self.assertEqual(c.copy_pages, ["https://theses.fr/api/v1/document/2021NORMC251"])

    def test_lens_and_dimensions_send_their_key_and_read_their_answer(self):
        from WebScraping.averageScrap.sources.dimensions import Dimensions, build_query
        from WebScraping.averageScrap.sources.lens import Lens
        record = {"lens_id": "000-111", "title": "Garnet LLZO", "abstract": ABSTRACT, "year_published": 2022,
                  "external_ids": [{"type": "doi", "value": "10.1000/LENS"}], "source": {"title": "Solid State Ionics"},
                  "open_access": {"colour": "gold", "license": "cc-by"}, "authors": [{"first_name": "A", "last_name": "B"}]}
        session = FakeSession([("api.lens.org", FakeResponse(200, json_data={"data": [record]}))])
        (c,) = first(Lens(client_for(session)), years=(2020, 2026))
        self.assertEqual((c.doi, c.oa_status, c.journal), ("10.1000/lens", "gold", "Solid State Ionics"))
        body = session.calls[0][1]
        self.assertEqual(session.calls[0][2], {"Authorization": "Bearer lens-token"})
        self.assertEqual(body["query"]["bool"]["must"][1], {"range": {"year_published": {"gte": 2020, "lte": 2026}}})

        self.assertEqual(build_query('a "b"', (2015, 2026), 0, 10), 'search publications in title_abstract_only for "a \\"b\\"" '
                         'where year in [2015:2026] return publications[doi+title+abstract+year+journal+publisher+authors+'
                         'open_access+linkout+type] limit 10 skip 0')
        publication = {"doi": "10.1000/DIM", "title": "Argyrodite", "abstract": ABSTRACT, "year": 2023,
                       "journal": {"title": "J"}, "open_access": ["oa_all", "green"], "type": "article"}
        session = FakeSession([("api/auth", FakeResponse(200, json_data={"token": "t"})),
                               ("dsl/v2", FakeResponse(200, json_data={"publications": [publication]}))])
        (c,) = first(Dimensions(client_for(session)))
        self.assertEqual((c.doi, c.oa_status), ("10.1000/dim", "green"))
        self.assertEqual(session.calls[0][1], {"key": "dim-key"})
        self.assertEqual(session.calls[1][2], {"Authorization": "JWT t"})

    def test_base_says_how_to_be_registered_when_it_refuses_the_network(self):
        from WebScraping.averageScrap.sources.base import BASE
        refused = FakeResponse(200, json_data={"error": "Access denied for IP address 1.2.3.4."})
        with self.assertLogs(level="WARNING") as said, self.assertRaises(HttpError) as raised:
            first(BASE(client_for(FakeSession([("base-search", refused)]))))
        self.assertEqual(raised.exception.status, 403)
        self.assertIn("base-search.net/about/en/contact.php", said.output[0])
        doc = {"dctitle": "Argyrodite", "dcdoi": ["10.1000/BASE"], "dclink": "https://repo.example/1", "dcoa": 1,
               "dcyear": "2021", "dccreator": ["A. B"], "dcdescription": ABSTRACT}
        session = FakeSession([("base-search", FakeResponse(200, json_data={"response": {"docs": [doc]}}))])
        (c,) = first(BASE(client_for(session)))
        self.assertEqual((c.doi, c.copy_pages), ("10.1000/base", ["https://repo.example/1"]))
        with mock.patch.dict(os.environ, {"BASE_ACCESS": ""}):
            self.assertFalse(BASE(client_for(FakeSession())).available())  # not asked until registered

    def test_a_repository_copy_found_second_is_kept_and_offered(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ledger = Ledger(os.path.join(folder, "ledger.sqlite"))
        self.addCleanup(ledger.close)
        ledger.add(Candidate(key="10.1/x", doi="10.1/x", title="T", landing_url="https://publisher.example/x"))
        ledger.add(Candidate(key="10.1/x", doi="10.1/x", landing_url="https://repo.example/1", copy_pages=["https://repo.example/1"]))
        c = ledger.get("10.1/x")
        self.assertEqual((c.landing_url, c.copy_pages), ("https://publisher.example/x", ["https://repo.example/1"]))
        self.assertEqual(screening.access_of(c, False), "open")
        options = [(o.service, o.url, o.landing) for o in Resolver(client_for(FakeSession()), ["openalex"]).options(c)]
        self.assertEqual(options, [("repository", "https://repo.example/1", True)])


class RefusedLookupTests(KeyedTestCase):
    def test_a_doi_whose_lookups_were_refused_is_waiting_not_closed(self):
        """Unpaywall answered "too many requests" for this DOI: nothing was offered, but that is not
        "no legal copy" — the paper was not checked, and the watcher checks it again later."""
        from WebScraping.averageScrap.fetch import Downloader
        from WebScraping.averageScrap.ledger import CLOSED, FAILED
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        busy = FakeSession([("api.unpaywall.org", FakeResponse(429))])
        client = client_for(busy, contact="me@university.edu")
        outcome = Downloader(folder, client, Resolver(client, ["unpaywall"], "me@university.edu")).fetch(candidate())
        self.assertEqual((outcome.status, outcome.refused), (FAILED, ["Unpaywall"]))
        quiet = FakeSession([("api.unpaywall.org", FakeResponse(404))])  # an answer: Unpaywall does not know it
        client = client_for(quiet, contact="me@university.edu")
        outcome = Downloader(folder, client, Resolver(client, ["unpaywall"], "me@university.edu")).fetch(candidate())
        self.assertEqual((outcome.status, outcome.refused), (CLOSED, []))


class AddedResolverTests(ResolverSourceTests):
    def test_the_publisher_page_of_an_open_access_journal_is_asked_where_the_doi_points(self):
        handle = {"values": [{"type": "URL", "data": {"value": "https://www.frontiersin.org/article/10.3389/fchem.2020.00468/full"}}]}
        session = FakeSession([("doi.org/api/handles", FakeResponse(200, json_data=handle))])
        self.assertEqual(self.options(candidate(doi="10.3389/fchem.2020.00468"), ["publisher"], session),
                         [("publisher", "https://www.frontiersin.org/article/10.3389/fchem.2020.00468/full", True)])
        # A subscription journal's paper that no index says is open: its page is not asked.
        self.assertEqual(self.options(candidate(doi="10.1021/x", oa_status="closed"), ["publisher"], FakeSession()), [])

    def test_zenodo_offers_the_file_deposited_under_the_doi(self):
        record = {"doi": "10.1000/TEST", "metadata": {"access_right": "open", "license": {"id": "cc-by-4.0"}},
                  "files": [{"key": "paper.pdf", "links": {"self": "https://zenodo.org/api/records/1/files/paper.pdf/content"}}]}
        other = {**record, "doi": "10.1000/other"}
        session = FakeSession([("zenodo.org", FakeResponse(200, json_data={"hits": {"hits": [record, other]}}))])
        self.assertEqual(self.options(candidate(), ["zenodo"], session),
                         [("zenodo", "https://zenodo.org/api/records/1/files/paper.pdf/content", False)])

    def test_datacite_offers_the_repository_copies_that_name_the_doi(self):
        copy = {"attributes": {"url": "https://juser.fz-juelich.de/record/1", "types": {"resourceTypeGeneral": "Text"},
                               "relatedIdentifiers": [{"relationType": "IsVariantFormOf", "relatedIdentifier": "10.1000/test",
                                                       "relatedIdentifierType": "DOI"}]}}
        data = {"attributes": {**copy["attributes"], "url": "https://data.example/1", "types": {"resourceTypeGeneral": "Dataset"}}}
        cites = {"attributes": {**copy["attributes"], "url": "https://other.example/1",
                                "relatedIdentifiers": [{"relationType": "References", "relatedIdentifier": "10.1000/test",
                                                        "relatedIdentifierType": "DOI"}]}}
        session = FakeSession([("api.datacite.org", FakeResponse(200, json_data={"data": [copy, data, cites]}))])
        self.assertEqual(self.options(candidate(), ["datacite"], session), [("datacite", "https://juser.fz-juelich.de/record/1", True)])
