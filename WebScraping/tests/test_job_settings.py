# WebScraping/tests/test_job_settings.py
"""The "Search settings…" form of the web search (configs/sse.yaml): it saves what a person may
change, within bounds, keeps the comments and the "# headings" of the file, never offers what is
fixed (the folder of the PDFs), and can put back the shipped settings. Offline, in a folder made here."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from WebScraping.averageScrap.job import LIMITS, dump_job, load_job, read_comments

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

SHIPPED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "configs",
                       "sse.yaml")


def comment_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip().startswith("#")]


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "sse.yaml")
        shutil.copyfile(SHIPPED, self.path)

    def write(self, text: str) -> str:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        return self.path

    def read(self) -> str:
        with open(self.path, encoding="utf-8") as f:
            return f.read()


class FileTests(Folder):
    def test_the_shipped_job_is_written_again_with_every_comment(self):
        job = load_job(self.path)
        headings, notes = read_comments(self.path)
        text = dump_job(job, headings, notes)
        self.assertEqual(set(comment_lines(self.read())) - set(comment_lines(text)), set())
        self.assertEqual(load_job(self.write(text)), job)
        self.assertEqual(dump_job(load_job(self.path), *read_comments(self.path)), text)  # saved again: the same

    def test_a_heading_stays_before_its_words_and_goes_with_them(self):
        self.write("search:\n  queries:\n    # Oxides\n    - garnet\n    - perovskite\n    # Sulfides\n    - argyrodite\n")
        job = load_job(self.path)
        headings, _ = read_comments(self.path)
        job.search.queries = ["perovskite", "argyrodite", "halide"]  # "garnet" removed, "halide" added
        text = dump_job(job, headings)
        self.assertIn('# Sulfides\n    - "argyrodite"\n    - "halide"', text)
        self.assertNotIn("# Oxides", text)  # its first word is gone: the heading too
        job.search.queries = ["perovskite"]
        self.assertNotIn("# Sulfides", dump_job(job, headings))

    def test_the_numbers_are_held_within_their_bounds(self):
        for setting, value in (("fetch: {workers: 20}", "fetch.workers"), ("search: {queries: [a], max_per_query: 0}",
                                                                           "search.max_per_query"),
                               ("screen: {min_score: -1}", "screen.min_score"), ("fetch: {max_pdf_mb: 9000}", "fetch.max_pdf_mb")):
            text = setting if setting.startswith("search") else "search: {queries: [a]}\n" + setting
            with self.subTest(value), self.assertRaisesRegex(ValueError, value):
                load_job(self.write(text + "\n"))
        with self.assertRaisesRegex(ValueError, "search.years"):
            load_job(self.write("search: {queries: [a], years: [1800, 2020]}\n"))
        self.assertEqual(LIMITS["workers"], (1, 8))


from LocalExtraction.tests.test_gui import has_screen  # noqa: E402  (one check, made safely)


@unittest.skipUnless(has_screen(), "the window needs a screen")
class FormTests(Folder):
    def setUp(self):
        super().setUp()
        self.asked = []
        for name, answer in (("showerror", None), ("showinfo", None), ("askyesno", True)):
            patcher = mock.patch(f"tkinter.messagebox.{name}",
                                 side_effect=lambda title, text, *a, _n=name, _r=answer, **k: self.asked.append((_n, text)) or _r)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def form(self):
        from WebScraping.averageScrap.gui.job_dialog import open_job_settings
        form = open_job_settings(self.root, self.path, self.saved.append)
        self.root.update()
        return form

    saved: list

    def test_saving_without_a_change_keeps_the_file_and_its_comments(self):
        self.saved = []
        before = load_job(self.path)
        form = self.form()
        self.assertEqual(form._read(), before)
        form._save(self.path)
        self.assertEqual(self.saved, [self.path])
        self.assertEqual(load_job(self.path), before)
        with open(SHIPPED, encoding="utf-8") as f:
            shipped = len(comment_lines(f.read()))
        self.assertEqual(len(comment_lines(self.read())), shipped + 1)  # every comment of the shipped file + the first line
        self.assertEqual([a for a in self.asked if a[0] != "askyesno"], [])

    def test_a_change_is_saved_with_the_heading_typed_for_it(self):
        self.saved = []
        form = self.form()
        form.queries.insert("end", "\n# Mine\nLi3YCl6 halide conductor")
        form.fetch_sources["elsevier"].set(False)
        form.fetch_workers.set("5")
        form._tick(("Activation_Energy",))
        form._save(self.path)
        job = load_job(self.path)
        self.assertEqual(job.search.queries[-1], "Li3YCl6 halide conductor")
        self.assertIn('    # Mine\n    - "Li3YCl6 halide conductor"', self.read())
        self.assertNotIn("elsevier", job.fetch.sources)
        self.assertEqual((job.fetch.workers, job.extract.properties), (5, ["Activation_Energy"]))

    def test_what_is_out_of_bounds_or_empty_is_not_saved(self):
        self.saved = []
        before = self.read()
        form = self.form()
        for change, message in (
                (lambda: form.fetch_workers.set("20"), "Downloads at once: a number from 1 to 8 is expected"),
                (lambda: form.max_per_query.set("abc"), "Results per source: a number from 1 to 1000 is expected"),
                (lambda: [v.set(False) for v in form.search_sources.values()], "Where to search: tick at least one source"),
                (lambda: form._tick(()), "Data to extract: tick at least one property"),
                (lambda: form.queries.delete("1.0", "end"), "Searches: give at least one search"),
                (lambda: form.year_to.set(""), "Years: give both the first and the last year, or neither")):
            form._fill(load_job(self.path), read_comments(self.path)[0])
            change()
            self.asked.clear()
            form._save(self.path)
            with self.subTest(message):
                self.assertTrue(self.asked and self.asked[0][0] == "showerror" and self.asked[0][1].startswith(message),
                                self.asked)
        self.assertEqual(self.read(), before)
        self.assertEqual(self.saved, [])

    def test_the_folder_of_the_pdfs_is_not_offered_and_stays(self):
        self.saved = []
        form = self.form()
        self.assertFalse(hasattr(form, "folder"))
        entries = []

        def walk(widget):
            if isinstance(widget, tk.Entry) or widget.winfo_class() in ("TEntry", "TSpinbox"):
                entries.append(widget.get())
            for child in widget.winfo_children():
                walk(child)
        walk(form)
        self.assertNotIn("WebScraping/papers", entries)
        form._save(self.path)
        self.assertEqual(load_job(self.path).fetch.folder, "WebScraping/papers")

    def test_reset_puts_back_the_shipped_settings(self):
        self.saved = []
        self.write(dump_job(load_job(SHIPPED).__class__(search=load_job(SHIPPED).search.__class__(queries=["only this"]))))
        form = self.form()
        form._reset()
        form._save(self.path)
        self.assertEqual(load_job(self.path).search.queries, load_job(SHIPPED).search.queries)

    def test_a_broken_file_opens_the_default_settings_and_is_kept_until_saved(self):
        self.saved = []
        self.write("search: {queries: [a], sources: [google]}\n")
        form = self.form()
        self.assertTrue(self.asked and "cannot be read" in self.asked[0][1])
        self.assertEqual(self.read(), "search: {queries: [a], sources: [google]}\n")
        form._save(self.path)
        self.assertEqual(load_job(self.path).search.queries, load_job(SHIPPED).search.queries)

    def test_an_open_window_hears_that_the_settings_were_saved(self):
        from WebScraping.averageScrap.gui.job_dialog import when_saved

        class Window:
            def __init__(self):
                self.heard = []

            def saved(self, path):
                self.heard.append(path)
        self.saved = []
        window = Window()
        when_saved(window.saved)
        self.form()._save(self.path)
        self.assertEqual(window.heard, [self.path])


class DomainJobTests(unittest.TestCase):
    """Electrolytes, cathodes and anodes: one job file each, shipped with the package."""

    def test_each_shipped_job_names_its_domain_and_its_own_folders(self):
        here = os.path.dirname(SHIPPED)
        seen = {}
        for name, domain in (("sse.yaml", "electrolyte"), ("cathode.yaml", "cathode"), ("anode.yaml", "anode")):
            with self.subTest(name=name):
                job = load_job(os.path.join(here, name))
                self.assertEqual(job.extract.domain, domain)
                self.assertGreater(len(job.search.queries), 40)
                seen[domain] = (job.fetch.folder, job.search.doi_list)
        self.assertEqual(len({folder for folder, _ in seen.values()}), 3)  # no two jobs share a folder of PDFs
        self.assertEqual(len({dois for _, dois in seen.values()}), 3)

    def test_an_unknown_domain_is_refused(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("name: x\nsearch:\n  queries: [a]\nextract:\n  domain: separator\n")
        with self.assertRaisesRegex(ValueError, "extract.domain"):
            load_job(path)

    def test_the_starter_jobs_of_every_domain_are_made_next_to_sse_yaml(self):
        from WebScraping.averageScrap.about import ensure_default_job
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ensure_default_job(os.path.join(folder, "configs", "sse.yaml"))
        from WebScraping.averageScrap.about import FAMILY_JOBS
        self.assertEqual(sorted(os.listdir(os.path.join(folder, "configs"))),
                         sorted(["anode.yaml", "cathode.yaml", "sse.yaml", *(f"{f}.yaml" for f in FAMILY_JOBS)]))
        self.assertEqual(load_job(os.path.join(folder, "configs", "cathode.yaml")).extract.domain, "cathode")

    def test_a_shipped_job_named_before_it_exists_is_made_from_the_package(self):
        """A fresh install: `mme-web run --job configs/halide.yaml` (or Fetch DOIs, or the window) finds the job the
        package ships, copied into configs/ with all the others; a job that is not shipped is not invented."""
        from WebScraping.averageScrap.about import starter_job
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "configs", "halide.yaml")
        self.assertEqual(starter_job(path), path)
        self.assertEqual(load_job(path).name, "halide")
        self.assertTrue(os.path.exists(os.path.join(folder, "configs", "sse.yaml")))  # the others with it
        from WebScraping.averageScrap import cli
        fresh = os.path.join(folder, "fresh")
        seen = []
        with mock.patch.object(cli, "enter_project_home", side_effect=lambda *parts: os.makedirs(fresh, exist_ok=True)
                               or os.chdir(fresh)), mock.patch.object(cli, "run_web", side_effect=lambda a: seen.append(
                                   (a.job, a.output)) or 0), mock.patch.object(cli, "rebuild_if_asked"), \
                mock.patch.object(cli, "print_banner"):
            here = os.getcwd()
            self.addCleanup(os.chdir, here)
            elsewhere = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, elsewhere, True)
            os.chdir(elsewhere)  # started from a folder with no configs/ of its own, as a fresh user is
            cli.main(["run", "--job", os.path.join("configs", "lgps.yaml")])
        self.assertEqual(seen, [(os.path.join("configs", "lgps.yaml"), os.path.join("WebScraping", "web_output_lgps"))])
        mine = os.path.join(folder, "configs", "my_own.yaml")
        self.assertEqual(starter_job(mine), mine)
        self.assertFalse(os.path.exists(mine))

    def test_making_the_main_results_folder_makes_the_job_files_too(self):
        from mme_gui import hub
        from LocalExtraction import about
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        home = os.path.join(folder, "MoukhlijMatExtract")
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        with mock.patch.object(about, "PROJECT_HOME", __import__("pathlib").Path(home)):
            hub.home_ready()
        self.assertIn("garnet_nasicon.yaml", os.listdir(os.path.join(home, "configs")))

    def test_each_family_of_electrolytes_has_its_own_job(self):
        """One job per family (garnet, NASICON, LISICON, …), each with its own DOI list, PDF folder and database, its
        own topic words, and no excluded word among them."""
        from WebScraping.averageScrap.about import FAMILY_JOBS, output_for
        shipped = os.path.dirname(SHIPPED)
        folders, lists = set(), set()
        for family in FAMILY_JOBS:
            job = load_job(os.path.join(shipped, f"{family}.yaml"))
            self.assertEqual(job.name, family)
            self.assertEqual(os.path.normpath(job.fetch.folder), os.path.join("WebScraping", f"papers_{family}"))
            self.assertEqual(output_for(job), os.path.join("WebScraping", f"web_output_{family}"))
            self.assertTrue(job.search.doi_list.endswith(f"dois_{family}.csv"))
            self.assertTrue(job.screen.propose_closed)
            self.assertGreaterEqual(len(job.search.queries), 80, family)
            self.assertGreaterEqual(len(job.screen.topic_words), 15, family)  # oxide_structure: few names exist
            self.assertFalse({w.lower() for w in job.screen.topic_words} & {w.lower() for w in job.screen.exclude_words})
            self.assertEqual(len({q.lower() for q in job.search.queries}), len(job.search.queries), family)
            folders.add(job.fetch.folder)
            lists.add(job.search.doi_list)
        self.assertEqual((len(folders), len(lists)), (len(FAMILY_JOBS), len(FAMILY_JOBS)))  # never shared

    def test_saving_a_job_keeps_its_domain(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "cathode.yaml")
        shutil.copyfile(os.path.join(os.path.dirname(SHIPPED), "cathode.yaml"), path)
        headings, notes = read_comments(path)
        text = dump_job(load_job(path), headings, notes)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertEqual(load_job(path).extract.domain, "cathode")


if __name__ == "__main__":
    unittest.main()
