# WebScraping/tests/test_get_dois.py
"""Fetch_DOIs (web method 2, step 1), offline: how many DOIs a run adds, where they come from, and
what is kept when a run is stopped. The sources are stand-ins; nothing goes on the network."""

import argparse
import csv
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(used, {"base": 1, "extra": 1})

    def test_without_a_count_every_keyword_is_used(self):
        rows, used = {}, {}
        added = run(rows, ["k1", "k2"], {"k1": ["a"], "k2": ["b"], "e1": ["c"], "e2": ["d"]},
                    extra=["e1", "e2"], used=used)
        self.assertEqual(added, 4)
        self.assertEqual(used, {"base": 2, "extra": 2})

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


class WindowTests(unittest.TestCase):
    def test_the_window_takes_a_whole_number_from_one_up(self):
        from WebScraping.moukhlij4scraping.gui import parse_count
        self.assertEqual((parse_count("1"), parse_count("2500")), (1, 2500))
        for wrong in ("0", "-5", "ten", "1.5"):
            with self.assertRaises(ValueError):
                parse_count(wrong)


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


if __name__ == "__main__":
    unittest.main()
