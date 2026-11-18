# WebScraping/tests/test_learn.py
"""Screening that learns from a person's decisions: a model trained on the papers decided by hand gives each paper
still waiting its chance of a yes, and the review list puts the most uncertain first. It never decides. No network."""

import csv
import os
import shutil
import tempfile
import unittest

from WebScraping.tests.test_web import candidate  # also: offline, sys.path
from WebScraping.averageScrap import learn
from WebScraping.averageScrap.ledger import APPROVED, REJECTED, SCREENED, Ledger

ON = ["Garnet {} solid electrolyte: lithium conduction and activation energy",
      "Ta-doped Li7La3Zr2O12 {} garnet electrolyte with high ionic conductivity",
      "NASICON {} sodium solid electrolyte, grain boundary conduction",
      "Lithium-ion transport in {} garnet ceramics measured by impedance"]
OFF = ["Graphite {} anode for sodium batteries and its capacity fading",
       "Garnet {} gemstones from metamorphic rocks: a geological survey",
       "Photocatalytic {} water splitting on doped titania",
       "Silicon {} anodes with binder for high capacity"]


class LearnTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ledger = Ledger(os.path.join(self.root, "ledger.sqlite"))
        self.addCleanup(self.ledger.close)

    def add(self, key, title, decision, status=SCREENED, by_hand=False):
        self.ledger.add(candidate(key=key, doi=key, title=title, abstract=""))
        self.ledger.update(key, decision=decision, status=status, decided_by="hand" if by_hand else "")

    def labelled(self, n=4):
        for i in range(n):
            for j, title in enumerate(ON):
                self.add(f"10.1/on{i}{j}", title.format(i), "yes", APPROVED, by_hand=True)
            for j, title in enumerate(OFF):
                self.add(f"10.1/off{i}{j}", title.format(i), "no", REJECTED, by_hand=True)

    def test_a_decision_changed_in_the_review_list_is_a_decision_by_hand(self):
        self.add("10.1/a", "Garnet electrolyte", "yes")
        self.add("10.1/b", "Graphite anode", "yes")
        path = os.path.join(self.root, "candidates.csv")
        self.ledger.write_review(path)
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        for row in rows:
            row["decision"] = "no" if row["key"] == "10.1/b" else row["decision"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.ledger.apply_decisions(path)
        self.assertEqual(self.ledger.get("10.1/b").decided_by, "hand")  # changed from the proposal
        self.assertEqual(self.ledger.get("10.1/a").decided_by, "")      # left as proposed: the rules' decision

    def test_too_few_decisions_by_hand_no_model(self):
        self.add("10.1/a", "Garnet electrolyte", "yes", APPROVED, by_hand=True)
        self.add("10.1/w", "Garnet something", "yes")
        report = learn.refresh(self.ledger)
        self.assertFalse(report.trained)
        self.assertIn("10 decisions by hand", report.text)
        self.assertEqual(self.ledger.get("10.1/w").model_yes, -1.0)

    def test_the_model_guesses_the_waiting_papers_and_decides_nothing(self):
        self.labelled()
        self.add("10.1/w-on", "Ga-doped garnet solid electrolyte: lithium activation energy", "no")
        self.add("10.1/w-off", "Graphite anode capacity for sodium batteries", "yes")
        self.add("10.1/w-mid", "Garnet anode", "yes")
        report = learn.refresh(self.ledger)
        self.assertTrue(report.trained)
        self.assertEqual((report.labels, report.scored), (32, 3))
        self.assertGreaterEqual(report.accuracy, 0.75)  # 5-fold, on the decisions by hand
        on, off = self.ledger.get("10.1/w-on"), self.ledger.get("10.1/w-off")
        self.assertGreater(on.model_yes, 0.5)
        self.assertLess(off.model_yes, 0.5)
        self.assertEqual((on.decision, off.decision), ("no", "yes"))  # the rules' proposals stay as they were
        self.assertEqual(self.ledger.get("10.1/on00").model_yes, -1.0)  # a paper decided is not guessed

    def test_the_review_list_puts_the_most_uncertain_first(self):
        self.labelled()
        self.add("10.1/w-on", "Ga-doped garnet solid electrolyte: lithium activation energy", "yes")
        self.add("10.1/w-mid", "Garnet anode", "yes")
        self.add("10.1/w-off", "Graphite anode capacity for sodium batteries", "no")
        learn.refresh(self.ledger)
        path = os.path.join(self.root, "candidates.csv")
        self.ledger.write_review(path)
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        waiting = [r for r in rows if r["state"] == SCREENED]
        guesses = [abs(float(r["model_yes"]) - 0.5) for r in waiting]
        self.assertEqual(guesses, sorted(guesses))
        self.assertEqual(rows[-1]["model_yes"], "")  # decided: no guess


if __name__ == "__main__":
    unittest.main()
