# WebScraping/tests/test_get_dois.py
"""Fetch_DOIs (web method 2, step 1), offline: how many DOIs a run adds, where they come from, and
what is kept when a run is stopped. The sources are stand-ins; nothing goes on the network."""

import argparse
import io
import csv
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from WebScraping.Fetch_DOIs import get_dois as gd


def paper(name, details=True):
    """A record a source returns for DOI 10.1234/<name>, with or without its details."""
    if details:
        return gd.record(f"10.1234/{name}", f"Paper {name}", "2024", ["A. Author"], "J. Test", "stand-in")
    return gd.record(f"10.1234/{name}", basis="stand-in")


def source(table, details=True):
    """A stand-in source: `table` maps a keyword to the names of the DOIs it finds."""
    def search(keyword, limit, years):
        return [paper(name, details) for name in table.get(keyword, [])][:limit]
    return search


def run(rows, keywords, table, count=None, extra=(), used=None):
    return gd.collect(rows, keywords, [("Stand-in", source(table))], limit=100, years=None,
                      count=count, extra=extra, used=used)


def new_dois(rows, before):
    return [doi for doi in rows if doi not in before]


class AlreadyFetchedTests(unittest.TestCase):
    def test_a_second_run_adds_no_doi_twice(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("builtins.print") as said:
            out = Path(folder, "dois.csv")
            rows = gd.load(out)
            run(rows, ["k1"], {"k1": ["a", "b"]})
            gd.save(rows, out)
            rows = gd.load(out)
            self.assertEqual(run(rows, ["k1"], {"k1": ["a", "b", "c"]}), 1)  # only c is new
            gd.save(rows, out)
            lines = out.with_suffix(".txt").read_text(encoding="utf-8").split()
        self.assertEqual(sorted(lines), ["10.1234/a", "10.1234/b", "10.1234/c"])
        self.assertTrue(any("2 already in the list — skipped" in str(c) for c in said.call_args_list))

    def test_a_doi_only_in_the_text_file_is_known_and_kept(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("builtins.print"):
            out = Path(folder, "dois.csv")
            rows = gd.load(out)
            run(rows, ["k1"], {"k1": ["a"]})
            gd.save(rows, out)
            with out.with_suffix(".txt").open("a", encoding="utf-8") as f:
                f.write("10.1234/BY-HAND\n")  # added by hand, in another case
            rows = gd.load(out)
            self.assertIn("10.1234/by-hand", rows)
            self.assertEqual(run(rows, ["k2"], {"k2": ["by-hand", "a"]}), 0)  # both known: nothing added
            gd.save(rows, out)
            lines = out.with_suffix(".txt").read_text(encoding="utf-8").split()
        self.assertEqual(sorted(lines), ["10.1234/a", "10.1234/by-hand"])  # not dropped by the save

    def test_book_chapters_are_their_own_dois(self):
        rows = {}
        with mock.patch("builtins.print"):
            run(rows, ["k"], {"k": ["978-3-031-30477-4", "978-3-031-30477-4_3"]})
        self.assertEqual(len(rows), 2)  # a book and its chapter 3: two publications

    def test_a_keyword_a_source_already_answered_is_skipped(self):
        asked = []

        def search(keyword, limit, years):
            asked.append(keyword)
            return [paper(f"{keyword}-1"), paper(f"{keyword}-2")]
        searched, rows = {}, {}
        with mock.patch("builtins.print"):
            gd.collect(rows, ["k1", "k2"], [("Stand-in", search)], 100, None, searched=searched)
            self.assertEqual(asked, ["k1", "k2"])
            used = {}
            with mock.patch("builtins.print") as said:
                gd.collect(rows, ["k1", "k2", "k3"], [("Stand-in", search)], 100, None, used=used, searched=searched)
        self.assertEqual(asked, ["k1", "k2", "k3"])  # k1 and k2 were not asked again
        self.assertEqual(used["skipped"], 2)
        self.assertTrue(any("already fetched" in str(c) for c in said.call_args_list))
        with mock.patch("builtins.print"):
            gd.collect(rows, ["k1"], [("Stand-in", search)], 100, None, searched=searched, refresh=True)
        self.assertEqual(asked[-1], "k1")  # --refresh asks again

    def test_a_search_cut_short_by_the_count_is_not_remembered(self):
        def search(keyword, limit, years):
            return [paper("a"), paper("b"), paper("c")]
        searched = {}
        with mock.patch("builtins.print"):
            gd.collect({}, ["k1"], [("Stand-in", search)], 100, None, count=1, searched=searched)
        self.assertEqual(searched, {})  # two of its DOIs were left out: asked again next time


class CountTests(unittest.TestCase):
    def setUp(self):
        gd._STOP.clear()

    def test_a_count_adds_exactly_that_many_new_dois_to_the_old_ones(self):
        rows = {}
        gd.add_all(rows, [paper("old1"), paper("old2")], "earlier run", "kw")
        before = set(rows)
        added = run(rows, ["k1", "k2"], {"k1": ["old1", "old2", "a", "b", "c"], "k2": ["d", "e", "f"]}, count=4)
        self.assertEqual(added, 4)
        self.assertEqual(len(new_dois(rows, before)), 4)
        self.assertTrue(before <= set(rows))  # the old DOIs are kept
        self.assertIn("k1", rows["10.1234/old1"]["keywords"])  # an old DOI found again gains the keyword

    def test_the_new_dois_are_shared_out_over_the_keywords(self):
        rows = {}
        table = {f"k{i}": [f"{i}-{n}" for n in range(10)] for i in range(4)}
        run(rows, list(table), table, count=4)
        # one new DOI from each keyword, not four from the first one
        self.assertEqual(sorted(rows), ["10.1234/0-0", "10.1234/1-0", "10.1234/2-0", "10.1234/3-0"])

    def test_a_keyword_that_adds_less_leaves_more_for_the_next(self):
        rows = {}
        table = {"k1": [], "k2": ["a", "b", "c", "d"]}
        self.assertEqual(run(rows, ["k1", "k2"], table, count=4), 4)

    def test_extra_keywords_are_used_when_the_base_ones_run_dry(self):
        rows = {}
        gd.add_all(rows, [paper("old")], "earlier run", "kw")
        used = {}
        added = run(rows, ["k1"], {"k1": ["old"], "e1": ["x", "y", "z"], "e2": ["w"]},
                    count=3, extra=["e1", "e2"], used=used)
        self.assertEqual(added, 3)
        self.assertEqual({k: used[k] for k in ("base", "extra") if k in used}, {"base": 1, "extra": 1})

    def test_without_a_count_every_keyword_is_used(self):
        rows, used = {}, {}
        added = run(rows, ["k1", "k2"], {"k1": ["a"], "k2": ["b"], "e1": ["c"], "e2": ["d"]},
                    extra=["e1", "e2"], used=used)
        self.assertEqual(added, 4)
        self.assertEqual({k: used[k] for k in ("base", "extra") if k in used}, {"base": 2, "extra": 2})

    def test_when_every_keyword_is_used_it_says_how_many_it_found(self):
        rows = {}
        self.assertEqual(run(rows, ["k1"], {"k1": ["a"], "e1": ["b"]}, count=10, extra=["e1"]), 2)

    def test_the_count_is_a_whole_number_from_one_up(self):
        self.assertEqual((gd.positive_count("1"), gd.positive_count("500")), (1, 500))
        for wrong in ("0", "-3", "abc", "2.5"):
            with self.assertRaises(argparse.ArgumentTypeError):
                gd.positive_count(wrong)


class StopTests(unittest.TestCase):
    def setUp(self):
        gd._STOP.clear()
        gd._CRITICAL.clear()

    tearDown = setUp

    def test_a_stop_during_a_change_waits_until_the_list_is_whole(self):
        rows = {}
        gd._STOP.set()  # the stop comes while the records are being added
        with self.assertRaises(gd.StopRequested):
            gd.add_all(rows, [paper("a"), paper("b")], "Stand-in", "k")
        self.assertEqual(sorted(rows), ["10.1234/a", "10.1234/b"])
        self.assertTrue(all(row["found_by"] and row["keywords"] for row in rows.values()))

    def test_a_stop_signal_raises_only_outside_a_change(self):
        gd._CRITICAL.set()
        gd._on_stop(None, None)  # no exception: the change is finished first
        gd._CRITICAL.clear()
        with self.assertRaises(gd.StopRequested):
            gd._check_stop()

    def test_what_was_found_before_a_stop_is_kept(self):
        rows = {}
        found = []

        def stops_on_the_second_keyword(keyword, limit, years):
            if found:
                raise gd.StopRequested()
            found.append(keyword)
            return [paper("a"), paper("b")]
        with self.assertRaises(gd.StopRequested):
            gd.collect(rows, ["k1", "k2"], [("Stand-in", stops_on_the_second_keyword)], 100, None)
        self.assertEqual(sorted(rows), ["10.1234/a", "10.1234/b"])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.csv = self.folder / "dois.csv"

    def test_the_list_and_the_bare_dois_are_saved_and_details_not_looked_up_say_so(self):
        rows = {}
        # ("whole", not "full": a DOI ending in /full is read as a publisher's link and trimmed)
        gd.add_all(rows, [paper("whole"), paper("bare", details=False)], "Stand-in", "k")
        gd.save(rows, self.csv, unlooked={"10.1234/bare"})
        with self.csv.open(encoding="utf-8-sig") as f:
            saved = {row["doi"]: row for row in csv.DictReader(f)}
        self.assertEqual(saved["10.1234/whole"]["title"], "Paper whole")
        self.assertEqual(saved["10.1234/bare"]["title"], gd.NOT_LOOKED_UP)
        self.assertEqual((self.folder / "dois.txt").read_text(encoding="utf-8").split(), ["10.1234/whole", "10.1234/bare"])
        # The next run looks the details up again: the mark is emptied and the DOI listed as unlooked.
        unlooked = set()
        loaded = gd.load(self.csv, unlooked)
        self.assertEqual((loaded["10.1234/bare"]["title"], unlooked), ("", {"10.1234/bare"}))

    def test_a_detail_looked_up_and_not_found_says_not_listed(self):
        rows = {}
        gd.add_all(rows, [paper("bare", details=False)], "Stand-in", "k")
        gd.save(rows, self.csv)  # its look-up ran: it is not in unlooked
        with self.csv.open(encoding="utf-8-sig") as f:
            self.assertEqual(next(csv.DictReader(f))["title"], gd.NOT_LISTED)


class OpenSourcesTests(unittest.TestCase):
    def test_only_open_indexes_are_asked(self):
        self.assertEqual([name for name, _, _ in gd.SOURCES], ["OpenAlex", "Crossref", "Semantic Scholar", "arXiv"])


class KeywordTests(unittest.TestCase):
    def test_extra_keywords_mix_topics_and_properties_without_repeats(self):
        base = ["argyrodite ionic conductivity"]
        extra = gd.extra_keywords(base, ["argyrodite", "garnet", "ion transport"],
                                  ["ionic conductivity", "activation energy", "ion transport"])
        self.assertNotIn("argyrodite ionic conductivity", extra)  # a base keyword is not asked twice
        self.assertNotIn("ion transport ion transport", extra)    # nor a pair that repeats itself
        self.assertEqual(len(extra), len(set(extra)))
        # from one keyword to the next, the topic or the property changes
        self.assertTrue(all(a.split()[0] != b.split()[0] or a.split()[-1] != b.split()[-1]
                            for a, b in zip(extra, extra[1:])))
        self.assertIn("garnet activation energy", extra)

    def test_a_topic_off_the_main_one_is_kept_on_it(self):
        extra = gd.extra_keywords([], ["solid electrolyte", "solid-state electrolyte", "graph neural network"],
                                  ["shear modulus"], anchor="solid electrolyte")
        self.assertIn("graph neural network shear modulus solid electrolyte", extra)
        self.assertIn("solid electrolyte shear modulus", extra)         # already on the topic: no anchor
        self.assertIn("solid-state electrolyte shear modulus", extra)   # shares "electrolyte": no anchor


class OpenAlexTests(unittest.TestCase):
    def test_pages_past_the_first_only_with_a_key(self):
        pages = [{"results": [{"doi": "https://doi.org/10.1234/a"}], "meta": {"next_cursor": "page-2"}},
                 {"results": [{"doi": "https://doi.org/10.1234/b"}], "meta": {"next_cursor": None}}]
        for key, wanted in (("", 1), ("key", 2)):  # OpenAlex refuses (HTTP 401) a second page without a key
            answers = iter(pages)
            with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": key}), \
                    mock.patch.object(gd, "get", side_effect=lambda url, params: mock.Mock(json=lambda: next(answers))) as get:
                self.assertEqual(len(gd.from_openalex("garnet", 200, None)), wanted, key)
            self.assertEqual(get.call_count, wanted)



class WatcherTests(unittest.TestCase):
    def test_a_keyword_search_a_source_refused_is_asked_again_after_a_pause_and_counted(self):
        import requests
        answers = {"garnet": [429, None], "argyrodite": [None]}  # garnet: "too many requests", then an answer

        def search(keyword, limit, years):
            code = answers[keyword].pop(0)
            if code:
                response = requests.Response()
                response.status_code = code
                raise requests.HTTPError(f"{code} Too Many Requests", response=response)
            return [paper(f"{keyword}-1"), paper(f"{keyword}-2")]
        rows, used, searched, pauses = {}, {}, {}, []
        with mock.patch.object(gd.runcontrol, "sleep", pauses.append), redirect_stdout(io.StringIO()):
            added = gd.collect(rows, ["garnet", "argyrodite"], [("Stand-in", search)], limit=100, years=None,
                               used=used, searched=searched)
            self.assertEqual((added, len(used["refused"])), (2, 1))  # argyrodite answered; garnet kept
            later = gd.recheck(rows, used, searched, None, added=added)
        self.assertEqual((later, pauses), (2, [120]))  # one round, after two minutes, brought garnet's two DOIs
        self.assertEqual(sorted(rows), ["10.1234/argyrodite-1", "10.1234/argyrodite-2", "10.1234/garnet-1", "10.1234/garnet-2"])
        self.assertIn(gd.search_key("Stand-in", "garnet", None), searched)  # answered: not asked again next run
        report = gd.watch_report(used, 0, len(rows))
        self.assertIn("keywords checked: 2", report)
        self.assertIn("3 asked, 2 answered, 1 of them on a later try, 0 still refused", report)
        self.assertIn("4 new, 4 in the list", report)

    def test_a_failure_that_is_an_answer_is_not_asked_again(self):
        import requests

        def search(keyword, limit, years):
            response = requests.Response()
            response.status_code = 400
            raise requests.HTTPError("400 Bad Request", response=response)
        used = {}
        with redirect_stdout(io.StringIO()):
            gd.collect({}, ["garnet"], [("Stand-in", search)], limit=100, years=None, used=used)
        self.assertEqual(used.get("refused") or [], [])


if __name__ == "__main__":
    unittest.main()
