# SelectingTopMaterial/tests/test_selection.py
"""Tests of the selection, each on a small made-up database written to a temporary folder: the
rule (which energy is which class), the reading (what a results folder can hold and what is done
with it), the ranking, the files, and the command line from end to end. Nothing here reads or
writes the databases of the project.

    python -m unittest discover -s SelectingTopMaterial/tests -t .   (or: pytest SelectingTopMaterial)
"""

import contextlib
import csv
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from SelectingTopMaterial import Criteria, CriteriaError, Filters, cli, console, exporters, html_report, loader, select
from SelectingTopMaterial.about import NAME
from SelectingTopMaterial.models import NOT_REPORTED, Measurement
from SelectingTopMaterial.selection import representative, select_from, weighted_median

try:
    import openpyxl
except ImportError:  # the workbook is the only file that needs it
    openpyxl = None

COLUMNS = ["paper_id", "material_formula", "activation_energy_eV", "reported_as", "extracted_from", "page",
           "composition", "structure", "ionic_radii", "temperature", "pressure", "data_origin",
           "transport_component", "attribution", "n_assumed", "basis", "confidence", "source", "section",
           "sentence", "raw_value", "material_id", "material_link"]
COMPOSITIONS = {
    "Li6PS5Cl": {"Li": 6.0, "P": 1.0, "S": 5.0, "Cl": 1.0},
    "Li7La3Zr2O12": {"Li": 7.0, "La": 3.0, "Zr": 2.0, "O": 12.0},
    "Na3Zr2Si2PO12": {"Na": 3.0, "Zr": 2.0, "Si": 2.0, "P": 1.0, "O": 12.0},
    "LiFePO4": {"Li": 1.0, "Fe": 1.0, "P": 1.0, "O": 4.0},
}


def row(formula: str, energy, paper: str = "A.pdf", **answers) -> dict:
    """A row of activation_energy.csv as the extraction writes it; what is not given is answered
    the way the extraction would."""
    answered = {
        "paper_id": paper, "material_formula": formula, "activation_energy_eV": energy,
        "reported_as": "activation energy", "extracted_from": "Text", "page": "3",
        "composition": json.dumps(COMPOSITIONS.get(formula, {})) if formula in COMPOSITIONS else "NONE",
        "structure": "argyrodite", "ionic_radii": "NONE", "temperature": "room temperature",
        "pressure": "ambient pressure", "data_origin": "experimental", "transport_component": "total",
        "attribution": "this work", "n_assumed": "2", "basis": "structure: stated", "confidence": 0.8,
        "source": "Text", "section": "Results", "sentence": f"{formula} shows an activation energy of {energy} eV.",
        "raw_value": f"('{energy}', 'eV')", "material_id": "MAT_1", "material_link": "apposition",
    }
    answered.update(answers)
    return answered


def write_database(folder: Path, rows: list[dict], papers: list[dict] | None = None,
                   columns: list[str] | None = None) -> Path:
    """A results folder holding these rows (and this papers.csv, when given)."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "activation_energy.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    if papers is not None:
        with (folder / "papers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["paper_id", "title", "doi", "publication_year"])
            writer.writeheader()
            writer.writerows(papers)
    return folder


def value(formula: str, energy: float, **answers) -> Measurement:
    """A value as the loader gives it, without going through a file."""
    key, elements = loader.material_key(formula, json.dumps(COMPOSITIONS[formula]) if formula in COMPOSITIONS else "")
    answered = dict(
        material=formula, material_key=key, elements=elements, energy_eV=energy, reported_as="activation energy",
        structure="argyrodite", polymorph="", temperature="room temperature", pressure="ambient pressure",
        data_origin="experimental", transport_component="total", attribution="this work", confidence=0.8,
        paper_id="A.pdf", paper_key="A.pdf", paper_title="A paper", doi=NOT_REPORTED, year="2024",
        database="local_output", extracted_from="Text", page="3", source="Text", section="Results",
        sentence=f"{formula}: {energy} eV")
    answered.update(answers)
    return Measurement(**answered)


class TemporaryFolder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)


class CriteriaTests(unittest.TestCase):
    def setUp(self):
        self.criteria = Criteria.load()

    def test_the_four_classes_and_their_limits(self):
        expected = {0.04: "Superionic", 0.2499: "Superionic", 0.25: "Performant", 0.2999: "Performant",
                    0.30: "Acceptable", 0.3999: "Acceptable", 0.40: "Rejected", 0.41: "Rejected", 3.6: "Rejected"}
        for energy, name in expected.items():
            self.assertEqual(self.criteria.classify(energy).name, name, f"{energy} eV")
        self.assertEqual([c.accepted for c in self.criteria.classes], [True, True, True, False])

    def test_the_arithmetic_of_floats_does_not_move_a_value_across_a_limit(self):
        self.assertNotEqual(0.1 + 0.2, 0.3)  # 0.30000000000000004
        self.assertEqual(self.criteria.classify(0.1 + 0.2).name, "Acceptable")
        self.assertEqual(self.criteria.classify(0.15 + 0.1).name, "Performant")
        self.assertEqual(self.criteria.classify(0.7 - 0.3).name, "Rejected")  # 0.39999999999999997

    def test_the_rules_in_words(self):
        self.assertEqual([c.rule for c in self.criteria.classes],
                         ["Ea < 0.25 eV", "0.25 ≤ Ea < 0.30 eV", "0.30 ≤ Ea < 0.40 eV", "Ea ≥ 0.40 eV"])

    def test_an_energy_near_a_limit_is_borderline(self):
        self.assertEqual(self.criteria.nearest_limit(0.249), 0.25)
        self.assertEqual(self.criteria.nearest_limit(0.31), 0.30)
        self.assertEqual(self.criteria.nearest_limit(0.25), 0.25)
        self.assertIsNone(self.criteria.nearest_limit(0.20))
        self.assertIsNone(self.criteria.nearest_limit(0.35))

    def test_other_classes_can_be_asked_for(self):
        criteria = Criteria.from_mapping({"class": [{"name": "Fast", "below": 0.2}, {"name": "Slow", "below": 0.5}],
                                          "rejected": {"name": "Out"}, "material": {"policy": "optimistic"}})
        self.assertEqual([criteria.classify(e).name for e in (0.1, 0.2, 0.49, 0.5)], ["Fast", "Slow", "Slow", "Out"])
        self.assertEqual(criteria.policy, "optimistic")

    def test_each_domain_has_its_criteria(self):
        from SelectingTopMaterial.criteria import DOMAIN_CRITERIA
        names = {domain: [c.name for c in Criteria.load(path).classes] for domain, path in DOMAIN_CRITERIA.items()}
        self.assertEqual(names["electrolyte"][0], "Superionic")
        self.assertEqual(names["cathode"], ["Low barrier", "Moderate barrier", "High barrier"])
        self.assertEqual(names["anode"], names["cathode"])

    def test_a_wrong_criteria_file_is_refused_with_the_reason(self):
        wrong = {
            "at least one": {},
            "must be above": {"class": [{"name": "A", "below": 0.3}, {"name": "B", "below": 0.25}]},
            "needs a name": {"class": [{"below": 0.3}]},
            "needs a number": {"class": [{"name": "A", "below": "0.3"}]},
            "share a name": {"class": [{"name": "A", "below": 0.3}, {"name": "a", "below": 0.4}]},
            "unknown policy": {"class": [{"name": "A", "below": 0.3}], "material": {"policy": "lucky"}},
            "borderline_margin": {"class": [{"name": "A", "below": 0.3}], "checks": {"borderline_margin": -1}},
        }
        for reason, data in wrong.items():
            with self.assertRaisesRegex(CriteriaError, reason):
                Criteria.from_mapping(data)

    def test_a_decimal_comma_in_the_file_is_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "criteria.toml"
            path.write_text('[[class]]\nname = "Superionic"\nbelow = 0,25\n', encoding="utf-8")
            with self.assertRaisesRegex(CriteriaError, "point"):
                Criteria.load(path)
            with self.assertRaisesRegex(CriteriaError, "not found"):
                Criteria.load(Path(folder) / "missing.toml")


class LoaderTests(TemporaryFolder):
    def test_reads_what_the_extraction_writes(self):
        database = write_database(self.tmp / "local_output", [row("Li6PS5Cl", 0.31, structure="cubic | argyrodite")],
                                  papers=[{"paper_id": "A.pdf", "title": "Argyrodites", "doi": "10.1000/XYZ",
                                           "publication_year": "2021"}])
        values, reports = loader.load([database])
        self.assertEqual(len(values), 1)
        read = values[0]
        self.assertEqual((read.material, read.energy_eV, read.polymorph), ("Li6PS5Cl", 0.31, "cubic"))
        self.assertEqual((read.paper_title, read.doi, read.year), ("Argyrodites", "10.1000/xyz", "2021"))
        self.assertEqual(read.elements, ("Cl", "Li", "P", "S"))
        self.assertEqual((reports[0].name, reports[0].values, reports[0].papers), ("local_output", 1, 1))

    def test_the_species_and_the_flag_are_read(self):
        database = write_database(self.tmp / "web_output", [row("Li7La3Zr2O12", 1.65, mobile_ion="Co",
                                                                plausibility="check: it is the transport of Co")],
                                  columns=COLUMNS + ["mobile_ion", "plausibility"])
        read, = loader.load([database])[0]
        self.assertEqual((read.mobile_ion, read.plausibility[:6]), ("Co", "check:"))

    def test_a_database_of_an_earlier_version_is_read_too(self):
        legacy = [c for c in COLUMNS if c not in ("extracted_from", "n_assumed")] + ["source_type"]
        database = write_database(self.tmp / "output", [row("Li6PS5Cl", 0.31, temperature="NONE", structure="NONE",
                                                            source_type="Figure")], columns=legacy)
        read = loader.load([database])[0][0]
        self.assertEqual((read.temperature, read.structure, read.extracted_from), (NOT_REPORTED, NOT_REPORTED, "Figure"))
        # No papers.csv: the file name stands, said so.
        self.assertEqual((read.paper_title, read.doi), ("A (file name: no title found in the paper)", NOT_REPORTED))

    def test_rows_that_cannot_be_ranked_are_left_aside_and_counted(self):
        database = write_database(self.tmp / "db", [
            row("Li6PS5Cl", 0.31), row("NONE", 0.2), row("LiFePO4", "n/a"), row("LiFePO4", 0), row("LiFePO4", -0.3),
            row("LiFePO4", "nan"), row("Na3Zr2Si2PO12", "0,35")])
        values, reports = loader.load([database])
        self.assertEqual(sorted(v.energy_eV for v in values), [0.31, 0.35])  # 0,35 is a decimal comma
        self.assertEqual((reports[0].rows, reports[0].unreadable), (7, 5))

    def test_a_paper_held_by_two_folders_counts_once(self):
        first = write_database(self.tmp / "local_output", [row("Li6PS5Cl", 0.31)])
        copy = write_database(self.tmp / "output", [row("Li6PS5Cl", 0.31), row("Li6PS5Cl", 0.99),
                                                    row("LiFePO4", 0.6, paper="B.pdf")])
        values, reports = loader.load([first, copy])
        self.assertEqual(sorted((v.material, v.energy_eV, v.database) for v in values),
                         [("Li6PS5Cl", 0.31, "local_output"), ("LiFePO4", 0.6, "output")])
        self.assertEqual((reports[1].values, reports[1].already_read), (1, 2))

    def test_one_paper_under_two_file_names_is_known_by_its_doi(self):
        local = write_database(self.tmp / "local_output", [row("Li6PS5Cl", 0.31, paper="Article 1.pdf")],
                               papers=[{"paper_id": "Article 1.pdf", "title": "T", "doi": "10.1000/abc"}])
        web = write_database(self.tmp / "web_output", [row("Li6PS5Cl", 0.31, paper="10.1000_abc.pdf")],
                             papers=[{"paper_id": "10.1000_abc.pdf", "title": "T", "doi": "https://doi.org/10.1000/ABC"}])
        values, reports = loader.load([local, web])
        self.assertEqual([v.paper_id for v in values], ["Article 1.pdf"])
        self.assertIn("nothing new", loader.describe(reports[1]))

    def test_a_paper_read_again_without_its_old_values_does_not_get_them_back(self):
        """local_output read the paper again and found no activation energy in it any more; the
        copy an earlier version left in output/ must not bring the old one back."""
        local = write_database(self.tmp / "local_output", [row("LiFePO4", 0.6, paper="B.pdf")],
                               papers=[{"paper_id": "A.pdf", "title": "A"}, {"paper_id": "B.pdf", "title": "B"}])
        stale = write_database(self.tmp / "output", [row("Li6PS5Cl", 0.05, paper="A.pdf")])
        values, _ = loader.load([local, stale])
        self.assertEqual([v.material for v in values], ["LiFePO4"])

    def test_a_value_a_paper_repeats_counts_once(self):
        database = write_database(self.tmp / "db", [
            row("Li6PS5Cl", 0.31, confidence=0.4, section="Abstract"), row("Li6PS5Cl", 0.31, confidence=0.9),
            row("Li6PS5Cl", 0.31, data_origin="simulation"), row("Li6PS5Cl", 0.31, paper="B.pdf")])
        values, reports = loader.load([database])
        self.assertEqual(len(values), 3)  # measured in A, computed in A, measured in B
        self.assertEqual(reports[0].repeated, 1)
        self.assertEqual(max(v.confidence for v in values if v.paper_id == "A.pdf" and v.data_origin == "experimental"), 0.9)

    def test_what_cannot_be_read_is_said_not_raised(self):
        (self.tmp / "empty").mkdir()
        (self.tmp / "blank").mkdir()
        (self.tmp / "blank" / "activation_energy.csv").write_text("\n", encoding="utf-8")
        other = write_database(self.tmp / "other", [{"paper_id": "A.pdf", "sentence": "x"}], columns=["paper_id", "sentence"])
        values, reports = loader.load([self.tmp / "missing", self.tmp / "empty", self.tmp / "blank", other])
        self.assertEqual(values, [])
        self.assertIn("not found", reports[0].problem)
        self.assertIn("run the extraction", reports[1].problem)
        self.assertIn("no activation energy yet", loader.describe(reports[2]))
        self.assertIn("column", reports[3].problem)

    def test_the_activation_energies_tied_to_no_material_are_counted(self):
        database = write_database(self.tmp / "db", [row("Li6PS5Cl", 0.31)])
        with (database / "unassigned_values.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows([["paper_id", "property_name"], ["A.pdf", "Activation_Energy"],
                              ["A.pdf", "Ionic_Conductivity"], ["C.pdf", "Activation_Energy"]])
        reports = loader.load([database])[1]
        self.assertEqual(reports[0].unassigned, 2)
        self.assertIn("2 activation energies", loader.unassigned_note(reports))
        self.assertEqual(loader.unassigned_note([]), "")

    def test_two_spellings_of_a_composition_are_one_material(self):
        one = loader.material_key("Li1.3Al0.3Ti1.7(PO4)3", '{"Li": 1.3, "Al": 0.3, "Ti": 1.7, "P": 3.0, "O": 12.0}')
        other = loader.material_key("Li1.3Ti1.7Al0.3(PO4)3", '{"Al": 0.3, "Li": 1.3, "O": 12, "P": 3, "Ti": 1.7}')
        self.assertEqual(one, other)
        self.assertNotEqual(one[0], loader.material_key("Li1.5Al0.5Ti1.5(PO4)3",
                                                        '{"Li": 1.5, "Al": 0.5, "Ti": 1.5, "P": 3.0, "O": 12.0}')[0])
        variable = loader.material_key("Na1-xLa1-xZrxCl4", '{"Cl": 4.0, "La": "1-x", "Na": "1-x", "Zr": "x"}')
        self.assertEqual(variable[1], ("Cl", "La", "Na", "Zr"))
        self.assertNotEqual(variable[0], loader.material_key("NaLaCl4", '{"Cl": 4.0, "La": 1.0, "Na": 1.0}')[0])
        # No composition in the database: the formula as spelled, subscripts and spaces aside.
        self.assertEqual(loader.material_key("Li₃PS₄"), loader.material_key("Li3 PS4", "NONE"))
        self.assertEqual(loader.material_key("Li3PS4")[1], ("Li", "P", "S"))

    def test_the_phase_a_structure_names(self):
        phases = {"cubic | garnet": "cubic", "garnet | Ia3": "", "tetragonal | garnet": "tetragonal",
                  "β-phase": "β-phase", "ꞵ−phase": "β-phase", "gamma phase": "γ-phase", "NASICON": "",
                  "Glass-ceramic": "glass-ceramic", NOT_REPORTED: "", "": ""}
        for structure, phase in phases.items():
            self.assertEqual(loader.polymorph(structure), phase, structure)

    def test_the_project_folders_are_found_in_the_order_they_are_trusted(self):
        for name in ("WebScraping/web_output", "LocalExtraction/local_output", "output", "elsewhere"):
            write_database(self.tmp / name, [row("Li6PS5Cl", 0.31)])
        self.assertEqual([p.relative_to(self.tmp).as_posix() for p in loader.discover(self.tmp)],
                         ["LocalExtraction/local_output", "WebScraping/web_output"])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.criteria = Criteria.load()

    def test_the_weighted_median(self):
        self.assertEqual(weighted_median([(0.3, 0.5)]), 0.3)
        self.assertAlmostEqual(weighted_median([(0.23, 0.65), (0.39, 0.65)]), 0.31)  # two equals: their mean
        self.assertEqual(weighted_median([(0.2, 0.9), (0.6, 0.1), (0.7, 0.1)]), 0.2)  # the trusted one decides
        self.assertEqual(weighted_median([(0.6, 0.5), (3.6, 0.5), (0.51, 0.5)]), 0.6)  # an outlier does not
        self.assertEqual(weighted_median([(0.2, 0.0), (0.4, 0.0), (0.9, 0.0)]), 0.4)  # no weight at all: a plain median
        self.assertAlmostEqual(weighted_median([(0.2, 1.0), (0.3, 0.0), (0.4, 1.0)]), 0.3)  # a weightless value does not count
        with self.assertRaises(ValueError):
            weighted_median([])

    def test_the_three_policies(self):
        values = [value("Li7La3Zr2O12", e, confidence=c) for e, c in ((0.23, 0.9), (0.30, 0.4), (0.50, 0.9), (0.54, 0.2))]
        self.assertEqual(representative(values, "optimistic"), 0.23)
        self.assertEqual(representative(values, "conservative"), 0.54)
        self.assertEqual(representative(values, "consensus"), 0.3)
        with self.assertRaises(ValueError):
            representative(values, "lucky")

    def test_lowest_energy_first_and_each_material_in_its_class(self):
        values = [value("LiFePO4", 0.6), value("Li6PS5Cl", 0.28), value("Na3Zr2Si2PO12", 0.35),
                  value("Li7La3Zr2O12", 0.2), value("Li6PS5Cl", 0.26, paper_id="B.pdf", paper_key="B.pdf")]
        ranking = select(values, self.criteria)
        self.assertEqual([(m.rank, m.material, m.energy_class.name) for m in ranking.materials],
                         [(1, "Li7La3Zr2O12", "Superionic"), (2, "Li6PS5Cl", "Performant"),
                          (3, "Na3Zr2Si2PO12", "Acceptable"), (4, "LiFePO4", "Rejected")])
        self.assertEqual([m.material for m in ranking.top], ["Li7La3Zr2O12", "Li6PS5Cl", "Na3Zr2Si2PO12"])
        self.assertEqual([m.material for m in ranking.rejected], ["LiFePO4"])
        argyrodite = ranking.materials[1]
        self.assertEqual((argyrodite.energy_eV, argyrodite.energy_min_eV, argyrodite.energy_max_eV), (0.27, 0.26, 0.28))
        self.assertEqual((len(argyrodite.values), len(argyrodite.papers)), (2, 2))
        self.assertEqual((ranking.values_used, ranking.papers_used), (5, 2))
        self.assertEqual([ranking.count(c) for c in self.criteria.classes], [1, 1, 1, 1])

    def test_the_same_values_give_the_same_ranking_in_any_order(self):
        values = [value(formula, energy, confidence=confidence)
                  for formula in COMPOSITIONS for energy, confidence in ((0.27, 0.5), (0.27, 0.9), (0.33, 0.7))]
        values += [value("Li3PS4", 0.27, confidence=0.9), value("Li3PO4", 0.27, confidence=0.9)]
        expected = [(m.rank, m.material, m.energy_eV) for m in select(values, self.criteria).materials]
        for seed in range(5):
            shuffled = values[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual([(m.rank, m.material, m.energy_eV) for m in select(shuffled, self.criteria).materials], expected)

    def test_equal_energies_the_better_supported_material_first(self):
        ranking = select([value("LiFePO4", 0.3, confidence=0.4), value("Li6PS5Cl", 0.3, confidence=0.9),
                          value("Na3Zr2Si2PO12", 0.3, confidence=0.9)], self.criteria)
        self.assertEqual([m.material for m in ranking.materials], ["Li6PS5Cl", "Na3Zr2Si2PO12", "LiFePO4"])

    def test_what_makes_a_class_less_sure_is_written_beside_it(self):
        ranking = select([
            value("Li7La3Zr2O12", 0.23, confidence=0.9), value("Li7La3Zr2O12", 0.5, confidence=0.4),
            value("Li6PS5Cl", 0.249), value("Na3Zr2Si2PO12", 0.35, confidence=0.3), value("LiFePO4", 0.6)], self.criteria)
        checks = {m.material: m.checks for m in ranking.materials}
        self.assertEqual(checks["Li7La3Zr2O12"], ("values disagree (Superionic to Rejected)",))
        self.assertEqual(checks["Li6PS5Cl"], ("borderline (0.25 eV limit)",))
        self.assertEqual(checks["Na3Zr2Si2PO12"], ("low confidence",))
        self.assertEqual(checks["LiFePO4"], ())
        garnet = ranking.materials[0]
        self.assertEqual(garnet.votes, (("Superionic", 1), ("Rejected", 1)))
        self.assertEqual(garnet.energy_class.name, "Superionic")  # a check never moves the material
        self.assertEqual(garnet.evidence.energy_eV, 0.23)

    def test_the_filters(self):
        values = [value("Li6PS5Cl", 0.2, data_origin="simulation", transport_component="bulk", attribution="cited", confidence=0.3),
                  value("Li6PS5Cl", 0.35), value("Na3Zr2Si2PO12", 0.33)]
        energy = lambda **filters: {m.material: m.energy_eV for m in select(values, self.criteria, filters=Filters(**filters)).materials}
        self.assertEqual(energy(), {"Li6PS5Cl": 0.35, "Na3Zr2Si2PO12": 0.33})
        self.assertEqual(energy(origin="simulation"), {"Li6PS5Cl": 0.2})
        self.assertEqual(energy(origin="experimental"), {"Li6PS5Cl": 0.35, "Na3Zr2Si2PO12": 0.33})
        self.assertEqual(energy(attribution="cited"), {"Li6PS5Cl": 0.2})
        self.assertEqual(energy(component="BULK"), {"Li6PS5Cl": 0.2})
        self.assertEqual(energy(elements=("Na",)), {"Na3Zr2Si2PO12": 0.33})
        self.assertEqual(energy(elements=("Li", "Cl")), {"Li6PS5Cl": 0.35})
        self.assertEqual(energy(min_confidence=0.5), {"Li6PS5Cl": 0.35, "Na3Zr2Si2PO12": 0.33})
        self.assertEqual(energy(min_confidence=0.9), {})
        self.assertEqual(energy(origin="simulation", attribution="this work"), {})
        self.assertEqual(Filters().describe(), "all values in range")
        self.assertEqual(Filters(origin="experimental", min_confidence=0.5, elements=("Na",)).describe(),
                         "experimental values · materials with Na · confidence ≥ 0.5")

    def test_one_kind_of_energy_only(self):
        # A static NEB barrier is lower than the Arrhenius activation energy of the same material: not to be pooled.
        values = [value("Li6PS5Cl", 0.18, data_origin="simulation", energy_kind="migration_barrier"),
                  value("Li6PS5Cl", 0.35, energy_kind="arrhenius"), value("Na3Zr2Si2PO12", 0.33, energy_kind="arrhenius")]
        energy = lambda **filters: {m.material: m.energy_eV for m in select(values, self.criteria, filters=Filters(**filters)).materials}
        self.assertEqual(energy(kind="arrhenius"), {"Li6PS5Cl": 0.35, "Na3Zr2Si2PO12": 0.33})
        self.assertEqual(energy(kind="migration_barrier"), {"Li6PS5Cl": 0.18})
        self.assertEqual(energy(kind="bvse"), {})
        self.assertIn("arrhenius energies", Filters(kind="arrhenius").describe())

    def test_flagged_values_are_left_out_unless_asked_for(self):
        values = [value("Li6PS5Cl", 0.01, plausibility="check: 0.01 eV is outside the 0.05–1.5 eV known for ion conductors"),
                  value("Li7La3Zr2O12", 0.3, mobile_ion="Co", plausibility="check: it is the transport of Co, not of a "
                                                                          "conducting ion"),
                  value("Na3Zr2Si2PO12", 0.33)]
        energy = lambda **filters: {m.material: m.energy_eV for m in select(values, self.criteria, filters=Filters(**filters)).materials}
        self.assertEqual(energy(), {"Na3Zr2Si2PO12": 0.33})
        self.assertEqual(set(energy(include_flagged=True)), {"Li6PS5Cl", "Li7La3Zr2O12", "Na3Zr2Si2PO12"})
        self.assertIn("flagged values included", Filters(include_flagged=True).describe())

    def test_the_phases_of_a_composition_apart_when_asked(self):
        values = [value("Li7La3Zr2O12", 0.23, structure="cubic | garnet", polymorph="cubic"),
                  value("Li7La3Zr2O12", 0.5, structure="tetragonal | garnet", polymorph="tetragonal"),
                  value("Li7La3Zr2O12", 0.3, structure="garnet")]
        together = select(values, self.criteria)
        self.assertEqual([(m.material, m.energy_eV) for m in together.materials], [("Li7La3Zr2O12", 0.3)])
        apart = select(values, self.criteria, by_phase=True)
        self.assertEqual([(m.material, m.energy_class.name) for m in apart.materials],
                         [("Li7La3Zr2O12 (cubic)", "Superionic"), ("Li7La3Zr2O12", "Acceptable"),
                          ("Li7La3Zr2O12 (tetragonal)", "Rejected")])

    def test_a_material_goes_by_its_most_frequent_spelling(self):
        latp = '{"Li": 1.3, "Al": 0.3, "Ti": 1.7, "P": 3.0, "O": 12.0}'
        key, elements = loader.material_key("LATP", latp)
        values = [value("Li6PS5Cl", 0.3, material=name, material_key=key, elements=elements)
                  for name in ("Li1.3Ti1.7Al0.3(PO4)3", "Li1.3Al0.3Ti1.7(PO4)3", "Li1.3Al0.3Ti1.7(PO4)3")]
        ranking = select(values, self.criteria)
        self.assertEqual([(m.material, len(m.values)) for m in ranking.materials], [("Li1.3Al0.3Ti1.7(PO4)3", 3)])

    def test_nothing_to_rank_is_an_empty_ranking(self):
        ranking = select([], self.criteria)
        self.assertEqual((ranking.materials, ranking.top, ranking.values_used, ranking.papers_used), ((), (), 0, 0))


class ComponentTests(TemporaryFolder):
    """Bulk, grain boundary and total: each component ranked on its own, never mixed."""

    def setUp(self):
        super().setUp()
        self.criteria = Criteria.load()
        self.values = [value("Li6PS5Cl", 0.18, transport_component="bulk"),
                       value("Li6PS5Cl", 0.45, transport_component="total"),
                       value("Li7La3Zr2O12", 0.32, transport_component="grain_boundary"),
                       value("LiFePO4", 0.6, transport_component="bulk")]

    def test_each_component_has_its_own_ranks(self):
        from SelectingTopMaterial.selection import select_each
        rankings = select_each(self.values, self.criteria)
        self.assertEqual(list(rankings), ["bulk", "grain_boundary", "total"])
        ranked = {c: [(m.rank, m.material, m.energy_eV) for m in s.materials] for c, s in rankings.items()}
        self.assertEqual(ranked["bulk"], [(1, "Li6PS5Cl", 0.18), (2, "LiFePO4", 0.6)])
        self.assertEqual(ranked["grain_boundary"], [(1, "Li7La3Zr2O12", 0.32)])
        self.assertEqual(ranked["total"], [(1, "Li6PS5Cl", 0.45)])  # its total Ea, not a mix with its bulk one
        self.assertEqual(rankings["bulk"].materials[0].energy_class.name, "Superionic")
        self.assertEqual(rankings["total"].materials[0].energy_class.name, "Rejected")

    def test_one_component_when_asked_and_any_spelling_of_it(self):
        from SelectingTopMaterial.selection import select_each
        for spelling in ("grain boundary", "Grain-Boundary", "grain_boundary"):
            rankings = select_each(self.values, self.criteria, filters=Filters(component=spelling))
            self.assertEqual({c: len(s.materials) for c, s in rankings.items()}, {"grain_boundary": 1}, spelling)

    def test_another_component_gets_a_ranking_too(self):
        from SelectingTopMaterial.selection import select_each
        rankings = select_each(self.values + [value("Li3PS4", 0.2, transport_component="surface")], self.criteria)
        self.assertEqual(list(rankings), ["bulk", "grain_boundary", "total", "surface"])

    def test_the_files_of_each_component_and_what_an_earlier_version_left(self):
        from SelectingTopMaterial.selection import select_each
        out = self.tmp / "results"
        (out / "grain_boundary").mkdir(parents=True)
        (out / "grain_boundary" / "values.csv").write_text("stale")  # a component that has no value any more
        (out / "top_materials.csv").write_text("the mixed ranking of an earlier version")
        (out / "my notes.txt").write_text("kept")
        rankings = select_each([v for v in self.values if v.transport_component != "grain_boundary"], self.criteria)
        written = cli.write_rankings(rankings, out, ("csv", "html"), None)
        self.assertEqual(sorted(written), ["bulk", "summary", "total"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["bulk", "my notes.txt", "summary.csv", "total"])
        self.assertIn("Top materials by bulk activation energy", (out / "bulk" / "report.html").read_text(encoding="utf-8"))


class WritingTests(TemporaryFolder):
    def setUp(self):
        super().setUp()
        database = write_database(self.tmp / "local_output", [
            row("Li6PS5Cl", 0.22), row("Li6PS5Cl", 0.26, paper="B.pdf", temperature="NONE", structure="NONE"),
            row("Li7La3Zr2O12", 0.33, sentence='=SUM(A1) </script><script>alert("x")</script> & \x0b more'),
            row("Na3Zr2Si2PO12", 0.29), row("LiFePO4", 0.6)],
            papers=[{"paper_id": "A.pdf", "title": "A <b>title</b>", "doi": "10.1000/a", "publication_year": "2020"}])
        self.selection = select_from([database], Criteria.load(), root=self.tmp)
        self.out = self.tmp / "results"

    def test_the_tables_answer_every_cell(self):
        written = exporters.write_csv(self.selection, self.out)
        self.assertEqual([p.name for p in written], ["top_materials.csv", "all_materials.csv", "values.csv"])
        sizes = {}
        for path in written:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            sizes[path.name] = len(rows)
            for line in rows:
                for column, answer in line.items():
                    self.assertNotIn(answer.strip().upper(), ("", "NONE", "NAN"), f"{path.name}: {column}")
        self.assertEqual(sizes, {"top_materials.csv": 3, "all_materials.csv": 4, "values.csv": 5})
        with (self.out / "top_materials.csv").open(encoding="utf-8-sig", newline="") as handle:
            best = next(csv.DictReader(handle))
        self.assertEqual((best["rank"], best["material"], best["class"], best["activation_energy_eV"]),
                         ("1", "Li6PS5Cl", "Superionic", "0.24"))
        self.assertEqual((best["Ea_min_eV"], best["Ea_max_eV"], best["n_values"], best["n_papers"]), ("0.22", "0.26", "2", "2"))
        self.assertEqual(best["class_of_values"], "Superionic 1 | Performant 1")
        self.assertEqual(best["checks"], "borderline (0.25 eV limit) | values disagree (Superionic to Performant)")
        self.assertEqual((best["structure"], best["temperature"]), ("argyrodite", "room temperature"))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted(p.name for p in written))  # no draft left

    def test_only_the_first_materials_when_asked(self):
        exporters.write_csv(self.selection, self.out, top=2)
        with (self.out / "top_materials.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual([line["material"] for line in csv.DictReader(handle)], ["Li6PS5Cl", "Na3Zr2Si2PO12"])
        with (self.out / "all_materials.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 4)

    def test_the_whole_ranking_as_data(self):
        data = json.loads(exporters.write_json(self.selection, self.out).read_text(encoding="utf-8"))
        self.assertEqual(data["summary"], {"materials": 4, "top_materials": 3, "rejected": 1, "values_read": 5,
                                           "values_used": 5, "papers": 2})
        self.assertEqual([(c["name"], c["below_eV"], c["materials"]) for c in data["criteria"]["classes"]],
                         [("Superionic", 0.25, 1), ("Performant", 0.3, 1), ("Acceptable", 0.4, 1), ("Rejected", None, 1)])
        best = data["materials"][0]
        self.assertEqual((best["material"], best["accepted"], best["class_of_values"], best["papers"]),
                         ("Li6PS5Cl", True, {"Superionic": 1, "Performant": 1}, ["A.pdf", "B.pdf"]))
        self.assertEqual([v["activation_energy_eV"] for v in best["values"]], [0.22, 0.26])
        self.assertEqual(data["databases"][0]["path"], "local_output")

    @unittest.skipIf(openpyxl is None, "openpyxl is not installed")
    def test_the_workbook(self):
        workbook = openpyxl.load_workbook(exporters.write_xlsx(self.selection, self.out))
        self.assertEqual(workbook.sheetnames, ["Top materials", "All materials", "Values", "Rule"])
        top = workbook["Top materials"]
        self.assertEqual([cell.value for cell in top[1]][:4], ["rank", "material", "class", "activation_energy_eV"])
        self.assertEqual([top.cell(row=2, column=i).value for i in (1, 2, 3, 4)], [1, "Li6PS5Cl", "Superionic", 0.24])
        self.assertEqual((top.max_row, workbook["All materials"].max_row, workbook["Values"].max_row), (4, 5, 6))
        self.assertEqual(top.freeze_panes, "C2")
        sentences = [cell.value for cell in workbook["Values"]["X"] if isinstance(cell.value, str)]
        formula = next(s for s in sentences if s.startswith("=SUM"))
        self.assertNotIn("\x0b", formula)  # a character a workbook refuses
        cell = next(c for c in workbook["Values"]["X"] if c.value == formula)
        self.assertEqual(cell.data_type, "s")  # text, not a formula
        self.assertEqual(workbook["Rule"]["A3"].value, "Superionic")

    def test_the_page_carries_the_ranking_and_nothing_of_it_is_markup(self):
        page = html_report.write_html(self.selection, self.out).read_text(encoding="utf-8")
        template = html_report.TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("__SELECTION_DATA__", page)
        self.assertEqual(page.count("</script>"), template.count("</script>"))  # the sentence did not close the block
        self.assertNotIn("<b>title</b>", page)
        self.assertNotIn("http", page.replace("http://www.w3.org/2000/svg", "").replace("https://doi.org/", ""))  # loads nothing
        block = page.split('<script id="selection-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(block)
        self.assertEqual([m["material"] for m in data["materials"]], ["Li6PS5Cl", "Na3Zr2Si2PO12", "Li7La3Zr2O12", "LiFePO4"])
        self.assertIn('</script><script>alert("x")</script>', data["materials"][2]["values"][0]["sentence"])
        self.assertEqual(data["materials"][0]["values"][0]["title"], "A <b>title</b>")
        self.assertEqual([c["colour"] for c in data["criteria"]["classes"]], ["#184f95", "#2a78d6", "#86b6ef", "#898781"])
        self.assertEqual(data["about"][0], ["Superionic", "Ea < 0.25 eV — 1 material"])

    def test_a_file_is_written_whole_or_not_at_all(self):
        target = self.out / "table.csv"
        exporters.write_file(target, lambda path: path.write_text("first", encoding="utf-8"))

        def interrupted(path: Path) -> None:
            path.write_text("half", encoding="utf-8")
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            exporters.write_file(target, interrupted)
        self.assertEqual(target.read_text(encoding="utf-8"), "first")
        self.assertEqual([p.name for p in self.out.iterdir()], ["table.csv"])


class ConsoleTests(TemporaryFolder):
    def setUp(self):
        super().setUp()
        # Li6PS5Cl: 0.22 measured and 0.50 computed, equally trusted — 0.36 stands for it.
        self.selection = select([value("Li6PS5Cl", 0.22), value("Li6PS5Cl", 0.5, data_origin="simulation"),
                                 value("Na3Zr2Si2PO12", 0.29), value("LiFePO4", 0.6)], Criteria.load())

    def test_what_the_terminal_shows(self):
        text = console.render(self.selection)
        self.assertNotIn("\033", text)
        for expected in ("Top materials (2)", "◆ Superionic", "Ea < 0.25 eV", "0 materials\n", "1 material\n",
                         "● Performant    0.290  single value", "○ Acceptable    0.360  0.220 – 0.500",
                         "exp 1 · sim 1", "values disagree (Superionic to Rejected)", "× Rejected (1): LiFePO4 0.600"):
            self.assertIn(expected, text)
        self.assertLess(text.index("Na3Zr2Si2PO12"), text.index("Li6PS5Cl"))  # 0.290 before 0.360

    def test_colours_are_an_extra(self):
        coloured = console.render(self.selection, colour=True)
        self.assertIn("\033[", coloured)
        plain = console.render(self.selection)
        self.assertEqual("".join(part.split("m", 1)[1] if i else part for i, part in enumerate(coloured.split("\033["))), plain)
        self.assertFalse(console.use_colour(io.StringIO()))
        self.assertTrue(console.use_colour(io.StringIO(), wanted=True))

    def test_a_narrow_terminal_cuts_the_checks_short_not_the_table(self):
        for line in console.render(self.selection, width=110).splitlines():
            if "Li6PS5Cl" in line:
                self.assertEqual(len(line), 110)
                self.assertTrue(line.endswith("…"))

    def test_the_first_materials_only_and_an_empty_ranking(self):
        self.assertIn("the first 1 of 2", console.render(self.selection, top=1))
        self.assertIn("No activation energy to rank.", console.render(select([], Criteria.load())))
        none_left = select([value("Li6PS5Cl", 0.22)], Criteria.load(), filters=Filters(origin="simulation"))
        self.assertIn("none of the 1 values read passes the filters (simulation values)", console.render(none_left))
        self.assertIn("No material passes", console.render(select([value("LiFePO4", 0.6)], Criteria.load())))


class CommandLineTests(TemporaryFolder):
    def setUp(self):
        super().setUp()
        self.database = write_database(self.tmp / "local_output", [
            row("Li6PS5Cl", 0.22), row("Na3Zr2Si2PO12", 0.29, data_origin="simulation"), row("LiFePO4", 0.6)])
        self.out = self.tmp / "results"

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        said, complained = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(complained):
            try:
                code = cli.main(list(arguments))
            except SystemExit as stop:  # argparse refusing an option
                code = stop.code
        return code, said.getvalue(), complained.getvalue()

    def fingerprint(self) -> dict[str, str]:
        return {str(path.relative_to(self.database)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.database.rglob("*")) if path.is_file()}

    def test_from_a_database_to_the_files(self):
        before = self.fingerprint()
        code, said, complained = self.run_cli("--source", str(self.database), "--out", str(self.out))
        self.assertEqual((code, complained), (0, ""))
        self.assertIn("Top materials (2)", said)
        # One ranking per transport component, each in its folder (the test values are all of total
        # transport), and the components side by side in summary.csv.
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if not p.name.startswith(".")),
                         ["run_manifest.json", "summary.csv", "total"])  # the manifest: how it was ranked
        expected = ["all_materials.csv", "report.html", "selection.json", "top_materials.csv", "values.csv"]
        total = self.out / "total"
        self.assertEqual(sorted(p.name for p in total.iterdir() if p.suffix != ".xlsx"), expected)
        self.assertEqual((total / "selection.xlsx").exists(), openpyxl is not None)
        with (self.out / "summary.csv").open(encoding="utf-8-sig", newline="") as handle:
            summary = {line["component"]: line for line in csv.DictReader(handle)}
        self.assertEqual([summary[c]["materials"] for c in ("bulk", "grain boundary", "total")], ["0", "0", "3"])
        self.assertIn("No bulk activation energy in the databases.", said)
        self.assertEqual(self.fingerprint(), before)  # the database is as it was: only read

    def test_the_same_ranking_is_not_done_twice(self):
        arguments = ("--source", str(self.database), "--out", str(self.out))
        self.assertEqual(self.run_cli(*arguments)[0], 0)
        code, said, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        self.assertIn("Already ranked", said)
        self.assertNotIn("Already ranked", self.run_cli(*arguments, "--force")[1])
        self.assertNotIn("Already ranked", self.run_cli(*arguments, "--top", "1")[1])  # another option: ranked

    def test_options(self):
        code, said, _ = self.run_cli("--source", str(self.database), "--no-files", "--origin", "simulation")
        self.assertEqual(code, 0)
        self.assertIn("simulation values · total transport (1 of 3)", said)
        self.assertFalse(self.out.exists())

        code, said, _ = self.run_cli("--source", str(self.database), "--out", str(self.out), "--format", "csv",
                                     "--top", "1", "--element", "li", "--quiet")
        self.assertEqual((code, said), (0, ""))
        self.assertEqual(sorted(p.name for p in (self.out / "total").iterdir()), ["all_materials.csv", "top_materials.csv", "values.csv"])
        with (self.out / "total" / "all_materials.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual([line["material"] for line in csv.DictReader(handle)], ["Li6PS5Cl", "LiFePO4"])

    def test_nothing_to_rank_writes_nothing_and_says_why(self):
        code, said, complained = self.run_cli("--source", str(self.database), "--out", str(self.out), "--min-confidence", "0.99")
        self.assertEqual((code, said), (1, ""))
        self.assertIn("No total activation energy in the databases with these filters", complained)
        self.assertIn("none of the 3 values read passes the filters", complained)
        self.assertFalse(self.out.exists())

        code, _, complained = self.run_cli("--source", str(self.tmp / "nowhere"), "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("folder not found", complained)

    def test_what_it_cannot_do_it_refuses(self):
        wrong = self.tmp / "criteria.toml"
        wrong.write_text('[[class]]\nname = "A"\nbelow = 0.3\n[[class]]\nname = "B"\nbelow = 0.2\n', encoding="utf-8")
        code, _, complained = self.run_cli("--source", str(self.database), "--criteria", str(wrong), "--out", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("must be above", complained)

        code, _, complained = self.run_cli("--source", str(self.database), "--out", str(self.database))
        self.assertEqual(code, 2)
        self.assertIn("is a database of MoukhlijMatExtract", complained)

        for arguments in (("--top", "0"), ("--min-confidence", "2"), ("--element", "Xx"), ("--policy", "lucky")):
            self.assertEqual(self.run_cli("--source", str(self.database), *arguments)[0], 2, arguments)
        self.assertFalse(self.out.exists())

    def test_other_criteria(self):
        strict = self.tmp / "strict.toml"
        strict.write_text('[[class]]\nname = "Elite"\nbelow = 0.25\n[rejected]\nname = "Out"\n', encoding="utf-8")
        code, said, _ = self.run_cli("--source", str(self.database), "--criteria", str(strict), "--no-files")
        self.assertEqual(code, 0)
        self.assertIn("◆ Elite", said)
        self.assertIn("× Out (2): Na3Zr2Si2PO12 0.290 · LiFePO4 0.600", said)

    def test_both_ways_of_starting_it(self):
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        for command in (["-m", NAME], [NAME]):  # from the folder that holds the code
            done = subprocess.run([sys.executable, *command, "--source", str(self.database), "--no-files"],
                                  cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True,
                                  text=True, encoding="utf-8")
            self.assertEqual((done.returncode, done.stderr), (0, ""), command)
            self.assertIn("Top materials (2)", done.stdout)


if __name__ == "__main__":
    unittest.main()
