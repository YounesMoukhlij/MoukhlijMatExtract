# WebScraping/tests/test_gui.py
"""Tests of the second gate of Project 2, the window — built transparent on a small made-up database
and ledger, and driven through its panel. No network: the engine's long steps are replaced by stand-ins.

The window tests need a screen; without one (a server, a CI runner) they are skipped. Set
MME_NO_WINDOW_TESTS=1 to skip them anyway.

    python -m unittest discover -s WebScraping/tests -t . -v   (or: pytest WebScraping)
"""

import csv
import logging
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

from LocalExtraction.exporter import StrictExporter
from LocalExtraction.tests.test_gui import WEB, WindowTest, has_screen, paper, tk
from WebScraping.averageScrap.fetch import Outcome
from WebScraping.averageScrap.job import ExtractConfig, FetchConfig, Job, ScreenConfig, SearchConfig, dump_job, load_job
from WebScraping.averageScrap.ledger import DOWNLOADED, FAILED, SCREENED, Candidate, Ledger


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
    def test_the_search_shows_how_far_it_is(self):
        from LocalExtraction.gui.progress_text import Pace
        web = self.app.panel
        web._working, web._pace = True, Pace()
        web.stop_event.clear()
        web._search_progress("keywords", 148, 2128, "OpenAlex: “LLZO garnet”", 312)
        self.assertEqual(str(web.progress.cget("mode")), "determinate")
        self.assertEqual((float(web.progress.cget("value")), float(web.progress.cget("maximum"))), (148, 2128))
        self.assertEqual(web.status.get(), "Searching the keywords — 148 of 2,128 searches (each keyword in each "
                                           "source) · OpenAlex: “LLZO garnet” · 312 new papers so far")
        web._search_progress("abstracts", 40, 900, "12 found", 0)
        self.assertIn("Looking for the abstracts the records lack — 40 of 900 papers · 12 found", web.status.get())
        # after the step, or once Stop is pressed, a late report does not hide what is said then
        web.status.set("Stopping …")
        web.stop_event.set()
        web._search_progress("keywords", 149, 2128, "", 312)
        self.assertEqual(web.status.get(), "Stopping …")
        web.stop_event.clear()
        web._working = False

    def test_a_step_starts_with_its_estimate_in_dark_yellow_and_is_followed(self):
        from LocalExtraction.gui import progress
        web = self.app.panel
        tracker = web._track("2 · Search", [("keywords", "Searching the keywords", "searches"),
                                            ("screen", "Scoring the papers against the topic", "papers")],
                             {"keywords": 40}, "Searching with 10 saved DOIs and 20 saved keywords",
                             "the papers found so far are saved and scored")
        self.assertIn("Searching with 10 saved DOIs and 20 saved keywords · estimated", web.status.get())
        self.assertIn("done around", web.status.get())
        self.assertEqual(str(web.status_label.cget("foreground")), progress.gold(self.root))
        self.assertTrue(web.stop_note.winfo_manager())  # what stopping keeps, under the line
        self.assertIn("If you stop now, the papers found so far are saved and scored", web.stop_note.cget("text"))
        web._working = True
        web.stop_event.clear()
        web._search_progress("keywords", 3, 40, "OpenAlex: “garnet”", 7)
        self.assertTrue(web.status.get().startswith("Searching the keywords — 3 of 40 searches · OpenAlex: “garnet”"))
        self.assertIn("new papers: 7", web.status.get())
        self.assertEqual(tracker.phases["keywords"].done, 3)
        web._working = False
        web._finished([])
        self.assertEqual(tracker.outcome, "done")
        self.assertFalse(web.stop_note.winfo_manager())  # ended: the note goes
        self.assertNotEqual(str(web.status_label.cget("foreground")), progress.gold(self.root))

    def test_fetch_dois_shows_how_far_it_is(self):
        from LocalExtraction.gui.progress_text import Pace
        web = self.app.panel
        web._working, web._pace = True, Pace()
        web.stop_event.clear()
        web._doi_line("=== [12/48] LLZO garnet   (new DOIs so far: 230 of 500)")  # as Fetch DOIs prints it
        self.pump(0.3)
        self.assertEqual((float(web.progress.cget("value")), float(web.progress.cget("maximum"))), (12, 48))
        self.assertEqual(web.status.get(), "Fetch DOIs — search 12 of 48 · new DOIs so far: 230 of 500")
        web._working = False

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
            logging.info("[1/1] downloaded: 10.1000/wanted via osti")  # as Harvest.fetch logs each paper
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
            self.assertTrue(web._step_labels["screen"].cget("text").startswith("✓ ④"))
            self.assertNotIn("dois", web._step_labels)
            self.assertEqual(harvest.ledger.get("10.1000/new").decision, "yes")  # screened, proposed, still to review
            self.assertIn("10.1000/new", web.table.tree.get_children())

            web.limit_var.set("5")
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(done, [("fetch", 5), ("extract", 2, self.web_output)])  # the extraction follows, into the web folder
        self.assertEqual(web.table.tree.item("10.1000/wanted", "values")[4], "downloaded (osti)")  # after score and model
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

    def test_a_paper_not_downloaded_opens_the_window_of_the_papers_to_get_by_hand(self):
        from WebScraping.averageScrap import by_hand
        from WebScraping.averageScrap.gui.dialogs import MissedDialog
        self.assertEqual(self.download_with(""), [])  # a window of its own, not a message box
        dialog, = [w for w in self.app.panel.winfo_children() if isinstance(w, MissedDialog)]
        self.addCleanup(dialog.destroy)
        self.assertEqual(dialog.title(), "Papers not downloaded automatically")
        self.assertEqual(dialog.table.tree.get_children(), ("10.1000/wanted",))
        title, _, _, _, reason = dialog.table.tree.item("10.1000/wanted", "values")
        self.assertEqual((title, reason), ("Argyrodite conductors", by_hand.NO_COPY))
        with mock.patch("webbrowser.open") as opened:
            dialog._open(["10.1000/wanted"])  # what a double-click does
        opened.assert_called_once_with("https://doi.org/10.1000/wanted")
        card = self.app.panel.card.outcome
        self.assertIn(("1", "to get by hand"), [(stat.value, stat.label) for stat in card.stats])
        self.assertTrue(any(label == "Papers not downloaded (1)…" for label, _ in card.actions))

    def test_the_browser_helper_opens_the_papers_left_and_takes_in_the_pdfs_that_arrive(self):
        """“Get the rest with my browser…”: the pages of the papers left open in the browser; a PDF saved into the
        Downloads folder is moved into by_hand and taken in, and its line says so. Nothing else there is touched."""
        import tempfile
        import pymupdf
        from WebScraping.averageScrap.gui import browser_helper as module
        from WebScraping.tests.test_web import make_pdf
        self.download_with("")  # 10.1000/wanted: no copy found, on the hand list
        for window in [w for w in self.app.panel.winfo_children() if isinstance(w, tk.Toplevel)]:
            window.destroy()
        web = self.app.panel
        self.assertEqual(web.browser_button.cget("text"), "Get the rest with my browser…")
        downloads = Path(tempfile.mkdtemp())
        (downloads / "holiday.pdf").write_bytes(make_pdf("Holiday photos"))  # not a paper of the list
        rows = web._hand_rows()
        helper = module.BrowserHelperDialog(web, web, rows, downloads=str(downloads))
        self.addCleanup(lambda: helper.winfo_exists() and helper.close())
        self.assertEqual(helper.table.tree.item("10.1000/wanted", "values")[0], module.TO_OPEN)
        with mock.patch("webbrowser.open") as opened:
            self.assertEqual(helper.open_next(), ["10.1000/wanted"])
            self.pump(1.0)
        opened.assert_called_once_with("https://doi.org/10.1000/wanted")
        self.assertEqual(helper.table.tree.item("10.1000/wanted", "values")[0], module.OPENED)
        document = pymupdf.open(stream=make_pdf("Argyrodite conductors"), filetype="pdf")
        document[0].insert_text((50, 30), "https://doi.org/10.1000/wanted", fontsize=8)
        (downloads / "download (3).pdf").write_bytes(document.tobytes())
        with mock.patch.object(module, "_LOOK_MS", 100):
            helper._look()
            self.assertTrue(self.pump(until=lambda: helper.table.tree.item("10.1000/wanted", "values")[0] == module.TAKEN,
                                      limit=15))
        self.assertEqual(web._harvest().ledger.get("10.1000/wanted").status, DOWNLOADED)
        self.assertEqual(sorted(p.name for p in downloads.iterdir()), ["holiday.pdf"])  # only the paper was moved
        self.assertIn("1 taken in", helper.status.get())

    def test_the_browser_helper_opens_the_next_batch_by_itself_once_this_one_is_done(self):
        """A batch done — every paper taken in, left in by_hand or skipped — opens the next one by itself, unless
        “open the next batch by itself” is unticked. Skip marks the papers a person will not get."""
        import tempfile
        from WebScraping.averageScrap.gui import browser_helper as module
        self.download_with("")
        for window in [w for w in self.app.panel.winfo_children() if isinstance(w, tk.Toplevel)]:
            window.destroy()
        web = self.app.panel
        first = web._hand_rows()[0]
        rows = [first] + [dict(first, key=f"10.1000/next{n}", doi=f"10.1000/next{n}", link=f"https://doi.org/10.1000/next{n}",
                               title=f"Next {n}") for n in (1, 2)]
        helper = module.BrowserHelperDialog(web, web, rows, downloads=tempfile.mkdtemp())
        self.addCleanup(lambda: helper.winfo_exists() and helper.close())
        self.assertEqual(helper.batch.get(), 5)  # a person's pace by default
        self.assertEqual(helper.tip.cget("text"), module.TIP)  # the setting that makes it one click a paper
        self.assertIn("PDF documents → Download PDFs", module.TIP)
        helper.batch.set(1)
        with mock.patch("webbrowser.open") as opened, mock.patch.object(module, "_NEXT_MS", 50):
            self.assertEqual(helper.open_next(), ["10.1000/wanted"])
            self.pump(0.3)
            self.assertFalse(helper.batch_done())
            helper.skip(["10.1000/wanted"])
            self.assertTrue(self.pump(until=lambda: helper.current == ["10.1000/next1"], limit=5))
            self.pump(0.3)
            self.assertEqual([c.args[0] for c in opened.call_args_list],
                             ["https://doi.org/10.1000/wanted", "https://doi.org/10.1000/next1"])
            self.assertEqual(helper.table.tree.item("10.1000/wanted", "values")[0], module.SKIPPED)
            self.assertIn("1 skipped", helper.status.get())
            helper.auto_next.set(False)  # unticked: the done batch waits for the button
            helper.skip(["10.1000/next1"])
            self.pump(0.5)
            self.assertEqual(helper.current, ["10.1000/next1"])
            self.assertEqual(opened.call_count, 2)

    def test_the_downloads_tab_shows_every_paper_of_the_last_download_in_plain_words(self):
        from WebScraping.averageScrap import by_hand, download_log
        from WebScraping.averageScrap.gui.panel import _state
        web = self.app.panel
        self.assertIn("Downloads", [web.book.tab(t, "text") for t in web.book.tabs()])
        folder = web.job.fetch.folder
        got = Candidate(key="10.1000/a", doi="10.1000/a", title="Garnet A", status=DOWNLOADED, source_used="osti",
                        file="10.1000_a.pdf")
        shut = Candidate(key="10.1000/b", doi="10.1000/b", title="NASICON B", status=FAILED, attempts=1,
                         error="publisher: HTTP 403")
        for c in (got, shut):
            download_log.add(folder, download_log.entry(c, "2026-11-19 10:00:00"))
        web.downloads.show(force=True)
        self.assertEqual(sorted(web.downloads.selected_results()), ["✓ downloaded", "✗ not downloaded"])
        summary = web.downloads.summary.get()
        for words in ("2 paper(s) tried", "✓ 1 downloaded", "✗ 1 not downloaded", "⏳ 0 waiting"):
            self.assertIn(words, summary)
        values = web.downloads.table.tree.item("10.1000/b", "values")
        self.assertEqual((values[3], values[4]), (by_hand.BLOCKED, by_hand.REASONS[by_hand.BLOCKED]))
        self.assertEqual(web.downloads.table.tree.item("10.1000/a", "values")[3], "from osti")
        web.downloads.filter_var.set("Not downloaded")
        web.downloads._fill()
        self.assertEqual(web.downloads.selected_results(), ["✗ not downloaded"])
        self.assertEqual(_state(shut), "not downloaded (1/3 tries) — site refuses programs")  # the Candidates tab
        from WebScraping.averageScrap.gui.downloads_view import EVERY
        harvest = web._harvest()
        harvest.ledger.update("10.1000/wanted", status=DOWNLOADED, source_used="osti", retrieved_at="2026-11-01T09:00:00")
        web.downloads.filter_var.set("All")
        web.downloads.range_var.set(EVERY)
        web.downloads.show(force=True)
        self.assertTrue(web.downloads.summary.get().startswith("Every paper tried so far"))
        self.assertIn("10.1000/wanted", web.downloads.rows)  # from the ledger, before any log existed
        self.assertEqual(web.downloads.table.tree.item("10.1000/wanted", "values")[0], "2026-11-01 09:00")

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

    # ------------------------------------------------------------------
    # The papers got by hand, and the folders of a job
    # ------------------------------------------------------------------
    def test_a_pdf_saved_by_hand_is_taken_in_even_when_nothing_else_is_to_download(self):
        """The papers left to get by hand are closed or out of tries: no paper is marked yes. “3 · Download” must
        still run, since it is what takes in the PDFs of the by_hand folder."""
        from WebScraping.averageScrap import by_hand
        from WebScraping.averageScrap.ledger import CLOSED
        web = self.app.panel
        harvest = web._harvest()
        harvest.ledger.update("10.1000/wanted", status=CLOSED, error="no legal copy found")
        web.show_candidates()
        Path(by_hand.inbox(self.web_folder), "saved from the browser.pdf").write_bytes(b"%PDF-1.4 a paper")
        fetched = []

        def fetch(limit=None, stop_event=None, progress_callback=None):
            fetched.append(limit)
            harvest.taken_in = 1
            return {DOWNLOADED: 0, CLOSED: 0, "failed": 0, "waiting": 0}
        web.then_extract.set(False)
        with mock.patch.object(harvest, "fetch", side_effect=fetch):
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.assertEqual(fetched, [None])
        self.assertFalse(any("nothing to download" in text for _, text in self.asked))
        self.assertIn(("1", "taken in by hand"), [(s.value, s.label) for s in web.card.outcome.stats])

    def test_with_nothing_to_download_and_no_pdf_by_hand_it_says_so(self):
        from WebScraping.averageScrap.ledger import CLOSED
        web = self.app.panel
        web._harvest().ledger.update("10.1000/wanted", status=CLOSED)
        web.show_candidates()
        web.download()
        self.assertFalse(web.running())
        self.assertTrue(any("nothing to download" in text for kind, text in self.asked if kind == "showinfo"))

    def test_no_message_when_every_paper_missed_was_got_on_a_later_round(self):
        web = self.app.panel
        web._harvest()
        web._missed = [("10.1000/found", "failed")]  # failed first, downloaded by the watcher's next round
        web._tell_missed({DOWNLOADED: 1}, "")
        self.pump(0.1)
        self.assertEqual(self.asked, [])

    def test_the_hand_list_is_among_the_files_of_the_window(self):
        from WebScraping.averageScrap.fetch import HAND_LIST
        files = dict(self.app.panel.results_extra())
        self.assertEqual(files["Papers to download by hand"], os.path.join(self.web_folder, HAND_LIST))

    def test_the_results_folder_follows_the_job(self):
        """Each job its own database: the papers of a job extracted into another job's database would mix two
        corpora. A folder chosen by hand (here, or with --output) is kept."""
        from WebScraping.averageScrap.about import output_for
        from WebScraping.averageScrap.gui.app import App
        garnet_folder = os.path.join(self.root_folder, "WebScraping", "papers_garnet")
        garnet = os.path.join(self.root_folder, "garnet.yaml")
        with open(garnet, "w", encoding="utf-8") as f:
            f.write(dump_job(Job(name="garnet", search=self.job.search, screen=self.job.screen,
                                 fetch=FetchConfig(folder=garnet_folder, sources=["openalex"]), extract=self.job.extract)))
        self.assertEqual(output_for(load_job(garnet)), os.path.join(self.root_folder, "WebScraping", "web_output_garnet"))
        self.assertEqual(output_for(Job()), os.path.join("WebScraping", "web_output"))

        window = tk.Toplevel(self.root)
        app = App(window, job_path=garnet, output_dir="", workers=2)  # no folder named: the job's
        self.addCleanup(app.close)
        self.pump(0.2)
        web = app.panel
        self.assertEqual(web.output.get(), output_for(load_job(garnet)))
        web.job_file.set(self.job_path)
        web.load_job()
        self.assertEqual(web.output.get(), output_for(self.job))  # another job: its own database
        web.output.var.set(self.web_output)  # chosen by hand: typed in, then Return
        web.output._changed()
        web.job_file.set(garnet)
        web.load_job()
        self.assertEqual(web.output.get(), self.web_output)
        self.assertEqual(self.app.panel.output.get(), self.web_output)  # named when the window was opened: kept

    def test_reset_to_defaults_keeps_what_the_form_says_is_fixed(self):
        """Reset puts back the shipped search settings, never the job's name, its PDF folder or its DOI list: those
        would make the job read and write another job's DOIs and papers."""
        import dataclasses
        from WebScraping.averageScrap.gui.dialogs import JobDialog
        job = dataclasses.replace(self.job, name="garnet", contact_email="",
                                  search=dataclasses.replace(self.job.search, doi_list="Fetch_DOIs/dois_garnet.csv"))
        form = JobDialog(self.app.panel, job, self.job_path, lambda path: None)
        self.addCleanup(form.destroy)
        self.pump(0.1)
        self.assertIn(self.web_folder, form.fixed_folder.cget("text"))  # the job's own folder, not the default one
        form._reset()
        reset = form._read()
        self.assertEqual((reset.name, reset.fetch.folder, reset.search.doi_list),
                         ("garnet", self.web_folder, "Fetch_DOIs/dois_garnet.csv"))

    def test_what_the_engine_logs_during_a_step_is_in_the_activity_tab(self):
        """Every line of a step is in its Activity tab (the strip at the bottom keeps every line too)."""
        web = self.app.panel
        harvest = web._harvest()

        def fetch(limit=None, stop_event=None, progress_callback=None):
            logging.getLogger("WebScraping.averageScrap.harvest").info("Watcher: 2 DOI(s) refused by a busy site")
            return {DOWNLOADED: 0}
        logging.info("said while no step runs")
        web.then_extract.set(False)
        with mock.patch.object(harvest, "fetch", side_effect=fetch):
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.pump(0.2)
        self.assertIn("Watcher: 2 DOI(s) refused by a busy site", web.activity.contents())
        self.assertNotIn("said while no step runs", web.activity.contents())
        self.assertIn("said while no step runs", self.app.log.contents())

    def test_papers_refused_for_too_many_requests_are_told_in_a_line_of_the_window(self):
        web = self.app.panel
        harvest = web._harvest()
        said = ("2 paper(s) not downloaded yet: Semantic Scholar refused them (too many requests, or busy). They are "
                "tried again at the end of this download, one after another, 30 s apart — round 1 of 4, in 2 min.")

        def fetch(limit=None, stop_event=None, progress_callback=None):
            harvest.notice(said)
            return {DOWNLOADED: 0, "waiting": 2}
        web.then_extract.set(False)
        with mock.patch.object(harvest, "fetch", side_effect=fetch):
            web.download()
            self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.pump(0.2)
        self.assertEqual(web.notice.get(), "⏳ " + said)
        self.assertTrue(web._notice_label.winfo_ismapped())
        self.assertIn(said, web.card.outcome.highlights)
        web._run(lambda: None)  # the next step starts with no line
        self.assertTrue(self.pump(until=lambda: not web.running()))
        self.assertEqual(web.notice.get(), "")
        self.assertFalse(web._notice_label.winfo_ismapped())

    def test_the_papers_already_screened_can_be_screened_again_with_the_settings_of_now(self):
        """“Also keep papers no free copy is known for” ticked after the search: “Re-screen with the settings…”
        proposes the papers it had left out, and the download takes them."""
        import dataclasses
        from WebScraping.averageScrap.ledger import REJECTED
        web = self.app.panel
        ledger = web._harvest().ledger
        ledger.add(Candidate(key="10.1000/shut", doi="10.1000/shut", title="Solid electrolyte activation energy",
                             abstract="", year=2024, access="closed", oa_status="closed", status=REJECTED,
                             decision="no", flags=["no-open-copy-known"]))
        with open(self.job_path, "w", encoding="utf-8") as f:
            f.write(dump_job(dataclasses.replace(self.job, screen=dataclasses.replace(self.job.screen, propose_closed=True))))
        web.load_job()
        self.assertTrue(self.pump(until=lambda: "10.1000/shut" in web._candidates))
        web.rescreen()
        self.assertTrue(self.pump(until=lambda: not web.running() and web.search_button.instate(["!disabled"])))
        self.pump(0.2)
        self.assertTrue(any("are kept" in text for kind, text in self.asked if kind == "askyesno"))
        self.assertEqual(web._harvest().ledger.get("10.1000/shut").decision, "yes")
        self.assertIn("10.1000/shut", web.table.tree.get_children())  # among the proposed
        card = web.card.outcome
        self.assertEqual(card.title, "Re-screened")
        self.assertIn(("1", "newly proposed"), [(s.value, s.label) for s in card.stats])
        self.assertTrue(any(label.startswith("Download the") for label, _ in card.actions))

    def test_a_folder_deleted_while_the_window_is_open_is_said_and_made_again(self):
        """~/MoukhlijMatExtract deleted while the Web scraping window is open: the next step says so, makes it again
        (with its job files) and goes on in it — not a failure deep in the step, nor a ledger written into a deleted file."""
        import shutil
        from LocalExtraction import about
        home = Path(self.root_folder, "home", "MoukhlijMatExtract")
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        with mock.patch.object(about, "PROJECT_HOME", home):
            about.enter_project_home("web", "dois")
            window = tk.Toplevel(self.root)
            from WebScraping.averageScrap.gui.app import App
            app = App(window, job_path=os.path.join("configs", "sse.yaml"), output_dir="", workers=2)
            self.addCleanup(app.close)
            self.pump(0.3)
            web = app.panel
            web._harvest()
            shutil.rmtree(home)  # deleted in the Finder, the window still open
            asked = []
            with mock.patch("tkinter.messagebox.askyesno", side_effect=lambda *a, **k: asked.append(a[1]) or True), \
                    mock.patch.object(web.harvest.__class__, "discover", return_value=0), \
                    mock.patch.object(web.harvest.__class__, "screen", return_value=0):
                web.search()
                self.assertTrue(self.pump(until=lambda: not web.running(), limit=10))
        self.assertTrue(asked and "was deleted" in asked[0], asked)
        self.assertTrue((home / "configs" / "sse.yaml").is_file())
        self.assertTrue((home / "WebScraping" / "papers" / "ledger.sqlite").is_file())  # a new ledger, in the new folder
        self.assertEqual(Path(os.getcwd()).resolve(), home.resolve())

    def test_delete_outputs_offers_the_jobs_own_folders(self):
        from LocalExtraction.gui.delete_outputs import DeleteOutputsDialog
        web = self.app.panel
        web.job = load_job(self.job_path)
        groups = {group.key: group for group in web.output_groups()}
        self.assertEqual(Path(groups["papers"].folder), Path(self.web_folder))
        self.assertEqual(Path(groups["database"].folder), Path(self.web_output))
        self.assertEqual(groups["dois"].names[:2], ("dois.csv", "dois.txt"))
        web.delete_button.invoke()
        dialog, = [w for w in web.delete_button.master.winfo_children() if isinstance(w, DeleteOutputsDialog)]
        self.addCleanup(dialog.close)
        self.assertEqual([g.folder for g in dialog.groups], [g.folder for g in web.output_groups()])


def _count_dois(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.DictReader(f))


@unittest.skipUnless(has_screen(), "the window needs a screen")
class SmallestWindowTests(WindowTest):
    """The window on the job file a new user starts with (configs/sse.yaml), at its minimum size."""

    def prepare(self):
        import shutil
        import mme_home
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.root_folder)  # the job's folders are relative: made here, never in the repository
        os.makedirs("configs")
        shutil.copy(os.path.join(mme_home.folder("configs"), "sse.yaml"), "configs/sse.yaml")

    def make_app(self, root):
        from WebScraping.averageScrap.gui.app import App
        return App(root, job_path="configs/sse.yaml", output_dir="", workers=2)

    def test_the_values_to_check_and_their_buttons_stay_in_view(self):
        width, height = self.root.minsize()
        self.root.geometry(f"{width}x{height}")
        self.app.panel.book.select(self.app.panel.verify)
        self.pump(0.5)
        view = self.app.panel.verify
        self.assertGreater(view.table.tree.winfo_height(), 100)  # five rows of the list or more
        for button in view.buttons:
            self.assertTrue(button.winfo_ismapped() and button.winfo_height() > 10, button.cget("text"))
        from LocalExtraction.tests.test_layout import seen
        panel = self.app.panel
        for widget in (panel.search_button, panel.download_button, panel.book, view.table.tree, *view.buttons):
            self.assertTrue(seen(widget), widget)  # drawn in view, not merely laid out behind another widget
        for button in view.buttons:  # whole: not cut at the bottom of the tab
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), view.winfo_rooty() + view.winfo_height(),
                                 button.cget("text"))


if __name__ == "__main__":
    unittest.main()
