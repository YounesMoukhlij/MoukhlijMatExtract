# WebScraping/tests/test_update.py
"""Keeping a database current: a job searched again only for the papers published since its last search
(`mme-web run --update`), and every job run before brought up to date in turn (`mme-web update`). No network."""

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest import mock

from WebScraping.tests.test_web import candidate  # also: offline, sys.path
from WebScraping.averageScrap import cli
from WebScraping.averageScrap.job import FetchConfig, Job, SearchConfig, dump_job
from WebScraping.averageScrap.ledger import Ledger


def write_job(name: str, years=None) -> str:
    os.makedirs("configs", exist_ok=True)
    path = os.path.join("configs", f"{name}.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_job(Job(name=name, search=SearchConfig(queries=["garnet"], sources=["openalex"], years=years),
                             fetch=FetchConfig(folder=os.path.join("WebScraping", f"papers_{name}")))))
    return path


def searched_on(name: str, day: str, search: str = "openalex|garnet|None|True") -> None:
    ledger = Ledger(os.path.join("WebScraping", f"papers_{name}", "ledger.sqlite"))
    ledger.add(candidate())
    with ledger._db:
        ledger._db.execute("INSERT OR REPLACE INTO searches (search, depth, at) VALUES (?, ?, ?)",
                           (search, 200, f"{day}T10:00:00+00:00"))
    ledger.close()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.home)

    def test_the_last_search_is_the_latest_keyword_search_not_a_snowball(self):
        write_job("garnet")
        searched_on("garnet", "2025-03-02")
        searched_on("garnet", "2025-01-05", "openalex|nasicon|None|True")
        searched_on("garnet", "2026-01-01", "snowball|W1|None|True")
        ledger = Ledger(os.path.join("WebScraping", "papers_garnet", "ledger.sqlite"))
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.last_search(), "2025-03-02")
        self.assertIsNone(Ledger(os.path.join(self.home, "empty.sqlite")).last_search())

    def years_of_an_update(self, path: str):
        seen = []
        with mock.patch.object(cli, "_run_stages", side_effect=lambda args, job, harvest, control: (
                seen.append(job.search.years), harvest.ledger.close(), 0)[-1]):
            args = cli.parse_args(["run", "--job", path, "--output", "out", "--update"])
            self.assertEqual(cli.run_web(args), 0)
        return seen[0]

    def test_an_update_searches_from_the_year_of_the_last_search(self):
        path = write_job("garnet")
        searched_on("garnet", "2025-03-02")
        self.assertEqual(self.years_of_an_update(path), (2025, date.today().year))

    def test_an_update_keeps_within_the_years_of_the_job(self):
        path = write_job("garnet", years=(2010, 2024))
        searched_on("garnet", "2021-06-01")
        self.assertEqual(self.years_of_an_update(path), (2021, 2024))

    def test_a_job_never_searched_is_searched_in_full(self):
        path = write_job("garnet", years=(2014, 2026))
        self.assertEqual(self.years_of_an_update(path), (2014, 2026))

    def test_update_brings_up_to_date_every_job_run_before(self):
        write_job("garnet")
        write_job("halide")  # never run: left alone
        searched_on("garnet", "2025-03-02")
        runs = []
        with mock.patch.object(cli, "run_web", side_effect=lambda args: runs.append(
                (args.job, args.output, args.update)) or 0), mock.patch.object(cli, "enter_project_home"), \
                mock.patch.object(cli, "print_banner"), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["update"]), 0)
        self.assertEqual(runs, [(os.path.join("configs", "garnet.yaml"),
                                 os.path.join("WebScraping", "web_output_garnet"), True)])
        self.assertIn("halide: never run — left alone", out.getvalue())


if __name__ == "__main__":
    unittest.main()
