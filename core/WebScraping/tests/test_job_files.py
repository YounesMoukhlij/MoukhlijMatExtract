# WebScraping/tests/test_job_files.py
"""Every job file shipped (configs/*.yaml) is a job the program can run: it loads, it has its own folders and DOI
list, it names words to screen with, and it carries no one's e-mail. CI runs it on each change of a job file."""

import os
import unittest
from collections import Counter

import mme_home
from WebScraping.averageScrap.about import FAMILY_JOBS, output_for
from WebScraping.averageScrap.job import load_job

CONFIGS = mme_home.folder(mme_home.CONFIGS)
FILES = sorted(name for name in os.listdir(CONFIGS) if name.endswith(".yaml"))


class ShippedJobFileTests(unittest.TestCase):
    def setUp(self):
        self.jobs = {name: load_job(os.path.join(CONFIGS, name)) for name in FILES}

    def test_every_family_and_domain_job_is_shipped(self):
        names = {os.path.splitext(name)[0] for name in FILES}
        self.assertTrue(set(FAMILY_JOBS) | {"sse", "cathode", "anode"} <= names, sorted(names))

    def test_each_loads_with_queries_and_words_to_screen_with(self):
        for name, job in self.jobs.items():
            with self.subTest(name):
                self.assertTrue(job.search.queries, "no query")
                self.assertTrue(job.screen.topic_words, "no topic word")
                self.assertTrue(job.screen.property_words, "no property word")
                self.assertFalse(set(map(str.lower, job.screen.topic_words)) & set(map(str.lower, job.screen.exclude_words)),
                                 "a word both wanted and excluded")
                self.assertFalse(job.contact_email, "a personal e-mail in a shipped file")

    def test_no_two_jobs_share_a_folder_or_a_doi_list(self):
        for what, value in (("PDF folder", lambda j: os.path.normpath(j.fetch.folder)),
                            ("results folder", lambda j: os.path.normpath(output_for(j))),
                            ("DOI list", lambda j: os.path.normpath(j.search.doi_list))):
            counts = Counter(value(job) for job in self.jobs.values())
            with self.subTest(what):
                self.assertEqual([v for v, n in counts.items() if n > 1], [], f"a {what} shared by two jobs")

    def test_each_has_no_query_twice(self):
        for name, job in self.jobs.items():
            with self.subTest(name):
                repeated = [q for q, n in Counter(q.strip().lower() for q in job.search.queries).items() if n > 1]
                self.assertEqual(repeated, [])


if __name__ == "__main__":
    unittest.main()
