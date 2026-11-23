# LocalExtraction/tests/test_statistics.py
"""The statistics of every part: the charts read from what each part wrote (a database, a web job's ledger, a
ranking, a classification, an ML dataset, an evaluation), drawn, and saved as 300 dpi PNG and SVG in
~/MoukhlijMatExtract/Statistics/PNG and SVG; and the Statistics window. The window tests need a screen."""

import csv
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from LocalExtraction import charts as drawing
from LocalExtraction.stats import Chart, database_charts
from LocalExtraction.tests.test_gui import has_screen


def write(path: Path, rows, columns=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(rows[0])
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def database(folder: Path) -> Path:
    write(folder / "papers.csv", [{"paper_id": "p1", "publication_year": "2021", "source_service": "openalex"},
                                  {"paper_id": "p2", "publication_year": "2023", "source_service": "arxiv"},
                                  {"paper_id": "p3", "publication_year": "2023", "source_service": "openalex"}])
    ea = [("p1", "0.28", "bulk", "experimental", "this work", "arrhenius", "Li+", "no", "in range"),
          ("p1", "0.31", "total", "experimental", "cited", "arrhenius", "Li+", "yes: low confidence", "in range"),
          ("p2", "0.22", "bulk", "simulation", "this work", "migration_barrier", "Na+", "no", "in range"),
          ("p2", "3.0", "total", "experimental", "this work", "arrhenius", "Li+",
           "yes: out of range; unusual formula", "check: outside")]
    write(folder / "activation_energy.csv",
          [dict(zip(("paper_id", "activation_energy_eV", "transport_component", "data_origin", "attribution",
                     "energy_kind", "mobile_ion", "needs_check", "plausibility"), row)) for row in ea])
    write(folder / "ionic_conductivity.csv",
          [{"paper_id": "p3", "ionic_conductivity_S_cm": v, "plausibility": "in range"} for v in ("1e-3", "1e-4")])
    return folder


class DatabaseChartTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_database_gives_its_charts_with_their_findings(self):
        found = {c.key: c for c in database_charts(database(self.root / "db"), "the test database")}
        self.assertEqual(found["values-per-property"].values, [4, 2, 0, 0])
        self.assertIn("6 values from 3 papers, 4 of them activation energies", found["values-per-property"].title)
        self.assertEqual(dict(zip(found["ea-by-component"].labels, found["ea-by-component"].values)),
                         {"Bulk": 2, "Total": 2})
        self.assertEqual(found["ea-origin-attribution"].values, [2, 1, 1, 0])
        self.assertEqual(sorted(found["ea-distribution"].values), [0.22, 0.28, 0.31])  # 3.0 eV out of range: left out
        self.assertIn("Median activation energy 0.28 eV", found["ea-distribution"].title)
        self.assertEqual(dict(zip(found["ea-flagged"].labels, found["ea-flagged"].values)),
                         {"low confidence": 1, "out of range": 1, "unusual formula": 1})
        self.assertEqual(found["papers-by-year"].labels, ["2021", "2022", "2023"])  # the years between, at 0
        self.assertEqual(found["papers-by-year"].values, [1, 0, 2])
        self.assertTrue(all("the test database" in c.note for c in found.values()))

    def test_no_database_no_chart(self):
        self.assertEqual(database_charts(self.root / "nothing"), [])

    def test_a_chart_of_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            Chart("x", "x", "pie")


class SavingTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_every_chart_is_saved_as_a_300_dpi_png_and_an_svg(self):
        found = database_charts(database(self.home / "db"))
        files = drawing.save(found, "Web scraping · garnet_nasicon", home=self.home, when=datetime(2026, 11, 23, 9, 15))
        self.assertEqual(len(files), 2 * len(found))
        png = self.home / "Statistics" / "PNG" / "web-scraping-garnet_nasicon_corpus-funnel_2026-11-23_0915.png"
        names = sorted(p.name for p in (self.home / "Statistics" / "PNG").iterdir())
        self.assertIn("web-scraping-garnet_nasicon_values-per-property_2026-11-23_0915.png", names)
        self.assertFalse(png.exists())  # (no funnel in a database alone)
        self.assertEqual(sorted(p.name for p in (self.home / "Statistics" / "SVG").iterdir()),
                         [n[:-4] + ".svg" for n in names])
        from PIL import Image
        with Image.open(self.home / "Statistics" / "PNG" / names[0]) as image:
            self.assertAlmostEqual(image.info["dpi"][0], 300, delta=1)
            self.assertGreater(image.size[0], 2000)  # 7.6 in at 300 dpi
        svg = (self.home / "Statistics" / "SVG" / (names[0][:-4] + ".svg")).read_text(encoding="utf-8")
        self.assertIn("<svg", svg)

    def test_every_kind_is_drawn_light_and_dark(self):
        kinds = [Chart("a", "A bar", "bar", ["x", "y"], [3, 1], accent=0),
                 Chart("b", "Across", "barh", ["x", "y"], [3, 1]),
                 Chart("c", "Funnel", "funnel", ["found", "kept"], [100, 4], accent=1),
                 Chart("d", "Histogram", "hist", values=[1e-3, 1e-4, 1e-5], log10=True, bin_width=0.5,
                       marks=[(-3, "1 mS/cm")]),
                 Chart("e", "Grouped", "grouped", ["p", "q"], series={"A": [0.5, 0.7], "B": [0.6, 0.2]}, percent=True),
                 Chart("f", "Line", "line", ["1", "2", "3"], [1, 4, 2]),
                 Chart("g", "Empty", "bar")]
        for chart in kinds:
            for dark in (False, True):
                with self.subTest(chart.kind, dark=dark):
                    figure = drawing.figure(chart, dark=dark)
                    self.assertGreater(len(figure.axes), 0)
                    figure.clear()

    def test_a_name_for_a_file(self):
        self.assertEqual(drawing.slug("Web scraping · garnet_nasicon"), "web-scraping-garnet_nasicon")
        self.assertEqual(drawing.slug("///"), "statistics")


class PartChartTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_web_job(self):
        from WebScraping.averageScrap.ledger import Candidate, Ledger
        from WebScraping.averageScrap.stats import web_charts
        papers = self.root / "papers"
        ledger = Ledger(str(papers / "ledger.sqlite"))
        for n, (status, decision, publisher, found_by) in enumerate([
                ("extracted", "yes", "Elsevier", ["openalex: garnet", "crossref: garnet"]),
                ("failed", "yes", "Elsevier", ["openalex: garnet"]),
                ("rejected", "no", "Wiley", ["semanticscholar: garnet"])]):
            ledger.add(Candidate(key=f"10.1/{n}", doi=f"10.1/{n}", title=f"Paper {n}", year=2020 + n, publisher=publisher,
                                 found_by=found_by))
            ledger.update(f"10.1/{n}", status=status, decision=decision)
        ledger.mark_searched("openalex|garnet|None|True", 200)
        ledger.close()
        write(papers / "download_log.csv", [{"key": "10.1/1", "result": "failed", "why": "Site refuses programs"}])
        output = database(self.root / "out")
        found = {c.key: c for c in web_charts("garnet", str(papers), str(output))}
        self.assertEqual(found["corpus-funnel"].values, [3, 2, 1, 3, 2])
        self.assertEqual(dict(zip(found["found-per-source"].labels, found["found-per-source"].values)),
                         {"openalex": 2, "crossref": 1, "semanticscholar": 1})
        self.assertEqual(found["publishers"].series, {"Proposed": [2.0], "Downloaded": [1.0]})
        self.assertEqual(found["download-failures"].labels, ["Site refuses programs"])
        self.assertEqual(sum(found["searches-per-day"].values), 1)
        self.assertIn("values-per-property", found)  # and the charts of its database

    def test_a_ranking(self):
        from SelectingTopMaterial.stats import ranking_charts
        write(self.root / "bulk" / "all_materials.csv",
              [{"material": m, "class": c, "activation_energy_eV": e, "evidence": t}
               for m, c, e, t in (("A", "Superionic", "0.20", "A"), ("B", "Performant", "0.27", "C"),
                                  ("C", "Rejected", "0.55", "C"))])
        found = {c.key: c for c in ranking_charts(self.root)}
        self.assertEqual(found["classes-bulk"].labels, ["Superionic", "Performant", "Rejected"])  # lowest Ea first
        self.assertEqual(found["best-bulk"].labels[0], "A")
        self.assertEqual(found["evidence-bulk"].values, [1, 0, 2])
        self.assertNotIn("classes-total", found)

    def test_a_classification(self):
        from Classification.stats import classification_charts
        write(self.root / "all_materials.csv",
              [{"material": f"M{i}", "crystal_structure": "garnet" if i < 3 else "NASICON",
                "structure_family": "oxide", "Ea_median_eV": str(0.3 + i / 100)} for i in range(4)])
        found = {c.key: c for c in classification_charts(self.root)}
        self.assertEqual(found["crystal-structures"].labels, ["garnet", "NASICON"])
        self.assertEqual(found["family-energies"].labels, ["oxide (4)"])

    def test_an_ml_dataset(self):
        from MLDataset.stats import dataset_charts, latest_dataset
        folder = self.root / "garnet_Ea_bulk"
        write(folder / "dataset.csv", [{"material": f"M{i}", "target": str(0.2 + i / 10), "unit": "eV",
                                        "n_values": str(i + 1)} for i in range(6)])
        write(folder / "excluded.csv", [{"why": "flagged: out of range"}, {"why": "marked wrong by hand"}])
        found = {c.key: c for c in dataset_charts(folder)}
        self.assertEqual(found["values-per-material"].values, [1, 1, 1, 1, 2])
        self.assertEqual(sorted(found["excluded"].labels), ["flagged", "marked wrong by hand"])
        self.assertEqual(latest_dataset(self.root), folder)

    def test_an_evaluation(self):
        from Evaluation.stats import evaluation_charts
        scores = self.root / "scores"
        scores.mkdir()
        (scores / "metrics.json").write_text(json.dumps({"papers": 10, "levels": {
            "value": {"all": {"precision": 0.8, "recall": 0.6, "f1": 0.69},
                      "activation_energy": {"precision": 0.9, "recall": 0.7, "f1": 0.79}}}}), encoding="utf-8")
        write(self.root / "benchmark" / "benchmark.csv",
              [{"system": s, "property": "all", "level": "record", "f1": f} for s, f in (("baseline", "0.2"),
                                                                                       ("MME", "0.5"))])
        found = {c.key: c for c in evaluation_charts(scores, self.root / "benchmark")}
        self.assertEqual(found["scores-value"].series["F1"], [0.69, 0.79])
        self.assertIn("F1 69 %", found["scores-value"].title)
        self.assertEqual(found["benchmark"].labels, ["MME", "baseline"])
        self.assertEqual(evaluation_charts(self.root / "none"), [])


@unittest.skipUnless(has_screen(), "the window needs a screen")
class StatisticsWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.db = database(Path(tempfile.mkdtemp()) / "db")
        self.addCleanup(shutil.rmtree, self.db.parent, True)

    def settle(self, window, seconds=10):
        until = time.time() + seconds
        while window._busy and time.time() < until:
            self.root.update()
            time.sleep(0.02)
        self.root.update()

    def test_it_draws_the_charts_and_saves_them_in_the_statistics_folders(self):
        from LocalExtraction.gui import statistics
        source = lambda: ("local-db", lambda: database_charts(self.db))
        window = statistics.open_statistics(self.root, "1 · Local extraction", source)
        window.attributes("-alpha", 0.0)
        self.settle(window)
        self.assertEqual(len(window._canvases), len(database_charts(self.db)))
        self.assertIn("charts from the files of 1 · Local extraction", window.status.get())
        window.save()
        self.settle(window, 30)
        self.assertIn("charts saved", window.status.get())
        saved = drawing.folder()
        self.assertTrue(any(p.name.startswith("local-db_") for p in (saved / "PNG").iterdir()))
        self.assertTrue(any(p.suffix == ".svg" for p in (saved / "SVG").iterdir()))
        # One window per part: asked again, the open one comes back.
        from unittest import mock
        with mock.patch("tkinter.messagebox.showinfo"):
            again = statistics.open_statistics(self.root, "1 · Local extraction", source)
        self.assertIs(again, window)
        window.destroy()

    def test_nothing_to_show_is_said(self):
        from LocalExtraction.gui import statistics
        window = statistics.open_statistics(self.root, "3 · Ranking", lambda: ("ranking", lambda: []))
        window.attributes("-alpha", 0.0)
        self.settle(window)
        self.assertIn("No statistics yet", window.status.get())
        self.assertIn("disabled", window.save_button.state())
        window.destroy()

    def test_the_button_sits_beside_the_results_buttons(self):
        import tkinter as tk
        from tkinter import ttk
        from LocalExtraction.gui.csv_browser import results_buttons
        from LocalExtraction.gui.statistics import BUTTON_TEXT
        bar = ttk.Frame(self.root)
        bar.pack()
        results_buttons(bar, "1 · Local extraction", lambda: str(self.db), statistics=lambda: ("x", lambda: []))
        self.assertIn(BUTTON_TEXT, [w.cget("text") for w in bar.winfo_children()])
        plain = ttk.Frame(self.root)
        results_buttons(plain, "x", lambda: "")
        self.assertNotIn(BUTTON_TEXT, [w.cget("text") for w in plain.winfo_children()])
        _ = tk


if __name__ == "__main__":
    unittest.main()
