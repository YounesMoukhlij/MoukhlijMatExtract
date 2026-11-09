# WebScraping/tests/test_gui.py
"""Tests of the second gate of Project 2, the window — built transparent on a small made-up database
and ledger, and driven through its panel. No network: the engine's long steps are replaced by stand-ins.

The window tests need a screen; without one (a server, a CI runner) they are skipped. Set
MME_NO_WINDOW_TESTS=1 to skip them anyway.

    python -m unittest discover -s WebScraping/tests -t . -v   (or: pytest WebScraping)
"""

import csv
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

from LocalExtraction.exporter import StrictExporter
from LocalExtraction.tests.test_gui import WEB, WindowTest, has_screen, paper
from WebScraping.averageScrap.fetch import Outcome
from WebScraping.averageScrap.job import ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from WebScraping.averageScrap.ledger import DOWNLOADED, SCREENED, Candidate, Ledger


@unittest.skipUnless(has_screen(), "the window needs a screen")
class WindowTests(WindowTest):
    def prepare(self):
        self.web_output = os.path.join(self.root_folder, "web_output")
        self.web_folder = os.path.join(self.root_folder, "papers_web")
        StrictExporter(self.web_output).export([paper("10.1000_found.pdf", WEB, "web")])
        self.job_path = os.path.join(self.root_folder, "job.yaml")
        self.job = Job(search=SearchConfig(queries=["solid electrolyte"], sources=["openalex"]),
                       screen=ScreenConfig(topic_words=["solid electrolyte"], property_words=["activation energy"]),
                       fetch=FetchConfig(folder=self.web_folder, sources=["openalex"]),
                       extract=ExtractConfig(properties=["Activation_Energy"], require_material=True))
        with open(self.job_path, "w", encoding="utf-8") as f:
            f.write(dump_job(self.job))
        ledger = Ledger(os.path.join(self.web_folder, "ledger.sqlite"))
        ledger.add(Candidate(key="10.1000/found", doi="10.1000/found", title="Garnet conductors", year=2022, score=5.0,
                             access="open", decision="yes", status=DOWNLOADED, source_used="pmc", file="10.1000_found.pdf"))
        ledger.add(Candidate(key="10.1000/wanted", doi="10.1000/wanted", title="Argyrodite conductors", year=2023, score=4.0,
                             access="open", decision="yes", status=SCREENED, abstract="About argyrodites."))
        ledger.add(Candidate(key="10.1000/other", doi="10.1000/other", title="Graphite anodes", year=2021, score=0.0,
                             access="closed", decision="no", status=SCREENED, flags=["no-open-copy-known"]))
        ledger.write_review(os.path.join(self.web_folder, "candidates.csv"))
        ledger.close()

    def make_app(self, root):
        from WebScraping.averageScrap.gui.app import App
        return App(root, job_path=self.job_path, output_dir=self.web_output, workers=2)

    # ------------------------------------------------------------------
    def test_the_window_shows_its_folder_of_results(self):
        energies = self.app.panel.energies
        self.assertEqual(len(energies.table), 1)
        self.assertIn("web_output: 1 article read, 1 activation energies from 1 of them", energies.count.get())
        row = dict(zip(energies.table.columns, energies.table.tree.item("0", "values")))
        self.assertEqual((row["material_formula"], str(row["activation_energy_eV"]), row["extracted_from"], str(row["page"])),
                         ("Li7La3Zr2O12", "0.41", "Text", "1"))

    def test_the_candidates_are_shown_and_filtered(self):
        web = self.app.panel
        self.assertEqual(len(web.table), 2)  # the proposed ones
        self.assertIn("1 yes, 1 no · 1 downloaded", web.counts.get())
        web.filter_var.set("All")
        web.show_candidates()
        self.assertEqual(len(web.table), 3)
        web.search_var.set("graphite")
        web.show_candidates()
        self.assertEqual(web.table.tree.get_children(), ("10.1000/other",))
        self.assertEqual(web.table.tree.item("10.1000/other", "values")[0], "✗")

    def test_a_decision_made_in_the_table_reaches_the_ledger_and_the_review_list(self):
        web = self.app.panel
        web.table.tree.selection_set(["10.1000/wanted", "10.1000/found"])
        web._decide("no")
        self.assertEqual(web.harvest.ledger.get("10.1000/wanted").decision, "no")
        self.assertEqual(web.harvest.ledger.get("10.1000/found").decision, "yes")  # already fetched: left alone
        with open(os.path.join(self.web_folder, "candidates.csv"), encoding="utf-8-sig") as f:
            written = {row["key"]: row["decision"] for row in csv.DictReader(f)}
        self.assertEqual(written["10.1000/wanted"], "no")  # what the terminal's fetch stage will read

    def test_a_list_reviewed_in_a_spreadsheet_is_what_the_table_shows(self):
        path = os.path.join(self.web_folder, "candidates.csv")
        text = Path(path).read_text(encoding="utf-8-sig").replace("no,0,closed", "yes,0,closed")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.app.panel.load_job()  # the list is read on a working thread: the table follows when it is in
        self.assertTrue(self.pump(until=lambda: self.app.panel.harvest.ledger.get("10.1000/other").decision == "yes"))
        self.assertTrue(self.pump(until=lambda: self.app.panel._candidates.get("10.1000/other") is not None
                                  and self.app.panel._candidates["10.1000/other"].decision == "yes"))

    def test_each_step_ends_with_its_results_card(self):
        import time
        from collections import Counter
        from WebScraping.averageScrap.ledger import CLOSED, FAILED
        web = self.app.panel
        web._started, web._services, web._fetched_titles = time.time(), Counter(), []
        web._searched(2, web._harvest().ledger.all())
        card = web.card.outcome
        self.assertEqual((card.title, card.status), ("Search finished", "done"))
        self.assertEqual({s.label: s.value for s in card.stats}["proposed"], "1")  # the paper marked yes, not fetched
        self.assertIn("Argyrodite conductors", card.highlights[0])
        self.assertIn("Download the 1 proposed", [label for label, _ in card.actions])
        web._searched(0, web._harvest().ledger.all())
        self.assertEqual(web.card.outcome.status, "nothing")
        web._services, web._fetched_titles = Counter({"pmc": 1}), ["Garnet conductors"]
        web._show_download_card({DOWNLOADED: 1, FAILED: 1, CLOSED: 0})
        card = web.card.outcome
        self.assertEqual((card.title, card.status), ("Download finished", "warning"))
        self.assertIn("From pmc: 1", card.highlights)
        self.assertIn("Extract them", [label for label, _ in card.actions])

    def test_the_job_form_gives_back_the_job_it_was_given(self):
        from WebScraping.averageScrap.gui.dialogs import JobDialog
        saved = []
        form = JobDialog(self.app.panel, self.job, self.job_path, saved.append)
        self.pump(0.1)
        self.assertEqual(form._read(), self.job)
        form.queries.insert("end", "\nsodium conductor")
        form.year_from.set("2015")
        form._save(self.job_path)  # nothing to ask: the file has no comments of its own
        self.assertEqual(self.asked, [("showerror", "Years: give both the first and the last year, or neither")])
        form.year_to.set("2026")
        form._save(self.job_path)
        self.assertEqual(saved, [self.job_path])
        again = load_job(self.job_path)
        self.assertEqual((again.search.queries, again.search.years), (["solid electrolyte", "sodium conductor"], (2015, 2026)))

    def test_it_runs_the_steps_of_the_terminal_gate(self):
        web = self.app.panel
        harvest = web._harvest()
        done = []

        def discover(**kwargs):
            harvest.ledger.add(Candidate(key="10.1000/new", doi="10.1000/new", title="A halide conductor", year=2024,
                                         abstract="solid electrolyte activation energy", oa_status="gold"))
            return 1

        def fetch(limit=None, stop_event=None, progress_callback=None):
            done.append(("fetch", limit))
            wanted = harvest.ledger.get("10.1000/wanted")
            harvest.ledger.update("10.1000/wanted", status=DOWNLOADED, source_used="osti")
            progress_callback(wanted, Outcome("10.1000/wanted", DOWNLOADED, service="osti"), 1, 1)
            return {DOWNLOADED: 1}

        def extract(max_workers=4, stop_event=None, progress_callback=None):
            done.append(("extract", max_workers, harvest.output_dir))
            return 0

        with mock.patch.object(harvest, "discover", side_effect=discover), \
                mock.patch.object(harvest, "fetch", side_effect=fetch), mock.patch.object(harvest, "extract", side_effect=extract):
            web.search()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
            self.pump(0.2)
            # The steps of the search are shown, each ticked once done; Fetch DOIs is its own button.
            self.assertTrue(web._step_labels["screen"].cget("text").startswith("✓ ③"))
            self.assertNotIn("dois", web._step_labels)
            self.assertEqual(harvest.ledger.get("10.1000/new").decision, "yes")  # screened, proposed, still to review
            self.assertIn("10.1000/new", web.table.tree.get_children())

            web.limit_var.set("5")
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(done, [("fetch", 5), ("extract", 2, self.web_output)])  # the extraction follows, into the web folder
        self.assertEqual(web.table.tree.item("10.1000/wanted", "values")[3], "downloaded (osti)")
        self.assertIn("[1/1] downloaded: 10.1000/wanted via osti", web.activity.contents())

    def download_with(self, email_problem):
        """A download that finds no copy of the paper wanted, Unpaywall having refused the e-mail or not."""
        from WebScraping.averageScrap.ledger import CLOSED
        web = self.app.panel
        harvest = web._harvest()

        def fetch(limit=None, stop_event=None, progress_callback=None):
            wanted = harvest.ledger.get("10.1000/wanted")
            harvest.ledger.update("10.1000/wanted", status=CLOSED)
            progress_callback(wanted, Outcome("10.1000/wanted", CLOSED, error="no legal copy found"), 1, 1)
            harvest.email_problem = email_problem
            return {CLOSED: 1}
        self.answer = False  # "Open API keys now?" — no
        with mock.patch.object(harvest, "fetch", side_effect=fetch):
            web.then_extract.set(False)
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.pump(0.2)
        return [message for kind, message in self.asked if kind in ("showinfo", "askyesno")]

    def test_a_paper_not_found_is_told_with_what_can_still_be_done(self):
        said, = self.download_with("")
        self.assertIn("No legal open-access copy was found for 1 of the 1 paper(s)", said)
        self.assertIn("Argyrodite conductors", said)
        self.assertIn("Your e-mail is not the reason", said)
        self.assertIn("university's network or VPN", said)

    def test_an_email_unpaywall_refused_is_told_with_where_to_change_it(self):
        os.environ["MME_EMAIL"] = "test@example.com"
        self.addCleanup(os.environ.pop, "MME_EMAIL", None)
        said, = self.download_with("refused")
        self.assertIn("refused the contact e-mail “test@example.com”", said)
        self.assertIn("academic or professional e-mail in “API keys…”", said)
        self.assertIn("Open “API keys…” now?", said)

    def test_fetch_dois_saves_the_dois_and_search_searches_with_them(self):
        """1 · Fetch DOIs collects and saves the DOIs (no paper is made of them yet); the window says how many
        are saved; 2 · Search searches with them and the saved keywords, without fetching any itself."""
        from WebScraping.Fetch_DOIs import get_dois
        web = self.app.panel
        listed = Path(self.root_folder, "Fetch_DOIs", "dois.csv")
        listed.parent.mkdir()

        def collect(argv):
            self.assertIn(str(listed), argv)  # saved where the search reads them
            print("=== [1/1] solid electrolyte   (new DOIs so far: 0 of 2)")
            listed.write_text("doi,title,year,authors,venue\n10.1000/x1,Halide conductors,2024,,\n"
                              "10.1000/x2,Sulfide conductors,2023,,\n", encoding="utf-8")
            listed.with_suffix(".txt").write_text("10.1000/x1\n10.1000/x2\n", encoding="utf-8")
            print("2 new DOIs added")
            return 0
        self.assertEqual(web.fetch_dois_button.cget("text"), "1 · Fetch DOIs")
        with mock.patch.object(get_dois, "OUTPUT", listed), mock.patch.object(get_dois, "main", side_effect=collect), \
                mock.patch("WebScraping.averageScrap.gui.panel.simpledialog.askstring", return_value="2"):
            web.fetch_dois()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
            self.pump(0.2)
            self.assertIn("2 new DOIs added", web.activity.contents())  # what it printed is in the log
            self.assertEqual(web.card.outcome.title, "DOIs fetched")
            self.assertEqual(web.dois_note.get(), "2 DOIs saved")
            self.assertIsNone(web._harvest().ledger.get("10.1000/x1"))  # saved, not taken in yet
            asked = []
            with mock.patch.object(web._harvest(), "discover", side_effect=lambda **kw: asked.append(kw) or 0):
                web.search()
                self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(asked[0].get("collect_dois"), False)  # the search fetches no DOI itself
        self.assertIn("2 saved DOIs", web.activity.contents())

    def test_search_says_so_when_no_doi_is_saved(self):
        web = self.app.panel
        self.assertEqual(web.dois_note.get(), "no DOI saved yet")
        self.answer = False  # "Search with the keywords only?" — no
        with mock.patch("WebScraping.averageScrap.gui.panel._dois_csv", lambda: os.path.join(self.root_folder, "none.csv")):
            web.search()
        self.assertFalse(web.running())
        self.assertTrue(any("1 · Fetch DOIs" in text for kind, text in self.asked if kind == "askyesno"))

    def test_stop_ends_a_download_in_the_middle_of_a_slow_paper(self):
        """A site that sends a PDF a few bytes at a time: Stop ends the download within moments, and the
        paper is not marked failed (it is tried again next time)."""
        import http.server
        import threading
        import time
        from WebScraping.averageScrap.ledger import APPROVED

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/robots.txt":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.end_headers()
                try:
                    for _ in range(600):  # a minute of trickle
                        self.wfile.write(b"%PDF-1.4 " if _ == 0 else b"x")
                        self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        web = self.app.panel
        harvest = web._harvest()
        harvest.ledger.update("10.1000/wanted", oa_urls=[f"http://127.0.0.1:{server.server_port}/paper.pdf"])
        web.then_extract.set(False)
        web.download()
        self.assertTrue(self.pump(until=lambda: "Downloading" in web.status.get() or web.running(), limit=5))
        self.pump(1.5)  # the download is under way, a byte at a time
        self.assertTrue(web.running())
        pressed = time.monotonic()
        web.stop()
        self.assertTrue(self.pump(until=lambda: not web.running(), limit=10))
        self.assertLess(time.monotonic() - pressed, 4)
        candidate = web._harvest().ledger.get("10.1000/wanted")
        self.assertEqual((candidate.status, candidate.attempts), (APPROVED, 0))  # not failed: tried again next time


    # ------------------------------------------------------------------
    # Stop, Pause / Resume, and going on with the same button
    # ------------------------------------------------------------------
    def _slow_steps(self):
        """The spinning bar off: Tk's update() does not return while it turns, so the test could not press
        Pause or Stop while a step runs."""
        self.app.panel.progress.start = lambda *a: None

    # ------------------------------------------------------------------
    # Search, then download, then extract — with the real extraction
    # ------------------------------------------------------------------
    _TITLE = "Ionic conductivity and activation energy of the argyrodite Li6PS5Cl solid electrolyte"

    def _extracted(self):
        from LocalExtraction.exporter import read_table
        path = os.path.join(self.web_output, "papers.csv")
        return set(read_table(path)["filename"]) if os.path.exists(path) else set()

    def _download_as_pdf(self):
        from WebScraping.tests.test_web import make_pdf

        def fetch(downloader, candidate):
            name = candidate.key.replace("/", "_") + ".pdf"
            with open(os.path.join(downloader.folder, name), "wb") as f:
                f.write(make_pdf(self._TITLE))
            return Outcome(candidate.key, DOWNLOADED, file=name, sha256="x", service="pmc", url="u")
        return mock.patch("WebScraping.averageScrap.harvest.Downloader.fetch", fetch)

    def test_search_goes_on_into_download_then_extraction_when_asked(self):
        web = self.app.panel
        self._slow_steps()
        web.search_then_download.set(True)
        web.then_extract.set(True)
        harvest = web._harvest()

        def discover(**kwargs):
            harvest.ledger.add(Candidate(key="10.1000/chained", doi="10.1000/chained", title=self._TITLE, year=2024,
                                         score=6.0, access="open", decision="yes", status=SCREENED))
            return 1
        with mock.patch.object(harvest, "discover", side_effect=discover), \
                mock.patch.object(harvest, "screen", return_value=1), self._download_as_pdf():
            web.search()
            self.assertTrue(self.pump(until=lambda: "10.1000_chained.pdf" in self._extracted(), limit=120))
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(harvest.ledger.get("10.1000/chained").status, "extracted")

    def test_search_alone_when_the_box_is_not_ticked_or_when_stopped(self):
        from LocalExtraction import runcontrol
        web = self.app.panel
        self._slow_steps()
        harvest = web._harvest()
        with mock.patch.object(harvest, "discover", return_value=0), mock.patch.object(harvest, "screen", return_value=0), \
                mock.patch.object(harvest, "fetch") as fetch:
            web.search_then_download.set(False)
            web.search()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
            self.pump(0.3)
            self.assertFalse(fetch.called)  # the box not ticked: the search only

            def stopped(**kwargs):
                while not runcontrol.stopped():
                    time.sleep(0.01)
                raise runcontrol.StepStopped()
            web.search_then_download.set(True)
            with mock.patch.object(harvest, "discover", side_effect=stopped):
                web.search()
                self.pump(0.1)
                web.stop()
                self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
            self.pump(0.3)
            self.assertFalse(fetch.called)  # stopped: no download starts by itself

    def test_then_extract_also_extracts_the_pdfs_downloaded_before(self):
        """Nothing new downloaded, but a PDF downloaded earlier and never extracted: "then extract them"
        extracts it (it extracted only what the same download brought)."""
        from WebScraping.tests.test_web import make_pdf
        web = self.app.panel
        self._slow_steps()
        web.then_extract.set(True)
        with open(os.path.join(self.web_folder, "10.1000_earlier.pdf"), "wb") as f:
            f.write(make_pdf(self._TITLE))
        with mock.patch("WebScraping.averageScrap.harvest.Downloader.fetch",
                        lambda downloader, c: Outcome(c.key, "closed", error="no copy")):
            web.download()
            self.assertTrue(self.pump(until=lambda: "10.1000_earlier.pdf" in self._extracted(), limit=120))
            self.assertTrue(self.pump(until=lambda: not web.running() and web.download_button.instate(["!disabled"])))

    def test_after_stop_every_button_comes_back_and_the_status_says_where_things_are(self):
        """Stop, then anything: the buttons are back as soon as the step has ended (also when its thread
        is still alive a moment after saying so), and the status no longer says "Stopping"."""
        from LocalExtraction import runcontrol
        web = self.app.panel
        self._slow_steps()
        harvest = web._harvest()

        def discover(**kwargs):
            while not runcontrol.stopped():
                time.sleep(0.01)
            raise runcontrol.StepStopped()
        with mock.patch.object(harvest, "discover", side_effect=discover):
            for _ in range(5):
                web.search()
                self.pump(0.1)
                self.assertTrue(web.running())
                web.stop()
                self.assertIn("Stopping", web.status.get())
                self.assertTrue(self.pump(until=lambda: web.search_button.instate(["!disabled"]), limit=10))
                self.assertFalse(web.running())
                self.assertNotIn("Stopping", web.status.get())
                for button in web._steps():
                    self.assertTrue(button.instate(["!disabled"]), button.cget("text"))

    def test_clear_the_log_empties_the_activity_and_the_log_strip(self):
        panel = self.app.panel
        panel.activity.write("a line of the step")
        self.app.log.write("a line of the engine")
        self.pump(0.2)
        panel.activity.clear_button.invoke()
        self.pump(0.2)
        self.assertEqual((panel.activity.contents().strip(), self.app.log.contents().strip()), ("", ""))
        panel.activity.write("after")  # what comes next is shown as before
        self.pump(0.2)
        self.assertIn("after", panel.activity.contents())

    def test_the_log_keeps_up_with_a_flood_of_lines(self):
        """A long search writes thousands of lines: the log takes them in batches, so the window (and Stop)
        never waits behind them."""
        from LocalExtraction.gui.widgets import _MAX_LOG_LINES
        log = self.app.panel.activity
        started = time.time()
        for n in range(20000):
            log.write(f"line {n}")
        self.pump(0.3)
        self.assertLess(time.time() - started, 3)
        text = log.contents()
        self.assertIn("line 19999", text)
        self.assertLessEqual(text.count("\n"), _MAX_LOG_LINES + 2)

    def test_a_stopped_download_goes_on_where_it_stopped(self):
        from LocalExtraction import runcontrol

        def slow_fetch(downloader, candidate):
            runcontrol.sleep(0.4)
            return Outcome(candidate.key, DOWNLOADED, file=candidate.key.replace("/", "_") + ".pdf", sha256="x",
                           service="pmc", url="u")
        web = self.app.panel
        web.then_extract.set(False)
        harvest = web._harvest()
        harvest.ledger.add_new([Candidate(key=f"10.9/p{i}", doi=f"10.9/p{i}", title=f"P{i}", decision="yes",
                                          status=SCREENED) for i in range(8)])
        harvest.ledger.write_review(harvest.review_path)
        downloaded = lambda: harvest.ledger.counts().get(DOWNLOADED, 0)  # noqa: E731
        with mock.patch("WebScraping.averageScrap.harvest.Downloader.fetch", slow_fetch):
            web.download()
            self.assertTrue(self.pump(until=lambda: downloaded() >= 3))
            web.toggle_pause()
            self.pump(0.6)  # what was under way finishes
            held = downloaded()
            self.pump(1.2)
            self.assertEqual(downloaded(), held)  # nothing new while paused
            web.toggle_pause()
            self.assertTrue(self.pump(until=lambda: downloaded() > held, limit=5))  # Resume goes on
            web.stop()
            self.assertTrue(self.pump(until=lambda: not web.running(), limit=5))
            self.assertLess(downloaded(), 10)
            web.download()  # the same button goes on with the papers left
            self.assertTrue(self.pump(until=lambda: not web.running() and downloaded() == 10, limit=15),
                            harvest.ledger.counts())

    def test_a_stopped_search_goes_on_where_it_stopped(self):
        from LocalExtraction import runcontrol
        asked = []

        class Source:
            def available(self):
                return True

            def search(self, query, years, limit, preprints):
                asked.append(query)
                for i in range(3):
                    runcontrol.sleep(0.2)
                    yield Candidate(key=f"10.2/{query[-1]}{i}", doi=f"10.2/{query[-1]}{i}", title=f"{query} {i}")
        web = self.app.panel
        self._slow_steps()
        web.job.search.queries = [f"query {i}" for i in range(5)]
        with mock.patch("WebScraping.averageScrap.harvest.sources.make", lambda *a, **k: Source()), \
                mock.patch("WebScraping.averageScrap.abstracts.complete", lambda *a, **k: None):
            web.search()
            self.assertTrue(self.pump(until=lambda: len(asked) >= 2))
            web.toggle_pause()
            held = len(asked)
            self.pump(1.5)
            self.assertEqual(len(asked), held)  # no new search while paused
            web.toggle_pause()
            web.stop()
            self.assertTrue(self.pump(until=lambda: not web.running(), limit=5))
            self.assertTrue(self.pump(until=lambda: web.card.outcome is not None, limit=5))
            self.assertEqual(web.card.outcome.title, "Search stopped")
            first = list(asked)
            asked.clear()
            web.search()
            self.assertTrue(self.pump(until=lambda: not web.running(), limit=15))
        self.assertTrue(set(first[:-1]).isdisjoint(asked))  # a search answered in full is not asked again
        self.assertEqual(asked[0], first[-1])  # the one cut short is
        self.assertIn("query 4", asked)

    def test_a_stopped_doi_fetch_goes_on_with_the_next_keywords(self):
        from LocalExtraction import runcontrol
        from WebScraping.Fetch_DOIs import get_dois
        out = os.path.join(self.root_folder, "dois.csv")
        asked = []

        def source(keyword, limit, years):
            asked.append(keyword)
            runcontrol.sleep(0.3)
            return [get_dois.record(f"10.5555/{keyword.replace(' ', '')}.{i}", title=keyword) for i in range(2)]
        self.job.search.queries = [f"keyword {i}" for i in range(8)]
        with open(self.job_path, "w", encoding="utf-8") as f:
            f.write(dump_job(self.job))
        web = self.app.panel
        self._slow_steps()
        with mock.patch.object(get_dois, "SOURCES", [("Fake", "openalex", source)]), \
                mock.patch.object(get_dois, "OUTPUT", Path(out)), \
                mock.patch.object(get_dois, "fill_details", lambda *a, **k: None), \
                mock.patch("WebScraping.averageScrap.gui.panel._dois_csv", lambda: out), \
                mock.patch("WebScraping.averageScrap.gui.panel._dois_txt", lambda: out[:-4] + ".txt"), \
                mock.patch("tkinter.simpledialog.askstring", lambda *a, **k: ""):  # no limit: until Stop
            web.fetch_dois()
            self.assertTrue(self.pump(until=lambda: len(asked) >= 3))
            web.toggle_pause()
            held = len(asked)
            self.pump(1.2)
            self.assertLessEqual(len(asked), held + 1)  # at most the keyword under way
            web.toggle_pause()
            web.stop()
            self.assertTrue(self.pump(until=lambda: not web.running(), limit=5))
            first = list(asked)
            self.assertEqual(_count_dois(out), 2 * (len(first) - 1))  # every keyword finished is saved
            asked.clear()
            web.fetch_dois()
            self.assertTrue(self.pump(until=lambda: len(asked) >= 2))
            web.stop()
            self.assertTrue(self.pump(until=lambda: not web.running(), limit=5))
        self.assertTrue(set(first[:-1]).isdisjoint(asked))  # the keywords already done are skipped
        self.assertEqual(asked[0], first[-1])  # the one cut short is asked again


def _count_dois(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.DictReader(f))


if __name__ == "__main__":
    unittest.main()
