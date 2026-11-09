# LocalExtraction/tests/test_data_quality.py
"""What the evaluation of the extraction found, kept fixed: values written as the paper writes them
(not as Python text), formulas whose subscripts the PDF set apart, the equations table holding an
equation in every row, the species that moves, and the values flagged as implausible — which the
ranking leaves out."""

import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from LocalExtraction.exporter import StrictExporter, _equation_rows, equation_columns
from LocalExtraction.extractor import ExtractorEngine
from LocalExtraction.models import PaperData, as_written
from LocalExtraction.normalizer import join_spaced_formulas, normalize_scientific_text
from LocalExtraction.ranking import Ranker
from LocalExtraction.species import mobile_species, plausibility, stated_species


def extract(*paragraphs):
    blocks = [{"text": normalize_scientific_text(t), "page": 1, "section": "Results", "type": "Text"} for t in paragraphs]
    return ExtractorEngine.extract_all(blocks)


class RawValueTests(unittest.TestCase):
    def test_a_value_as_the_paper_writes_it(self):
        self.assertEqual(as_written(("1.65", "eV")), "1.65 eV")
        self.assertEqual(as_written(("1", None)), "1")
        self.assertEqual(as_written("('1.16', 'mS cm −1')"), "1.16 mS cm −1")  # stored by earlier versions
        self.assertEqual(as_written("('dos',)"), "dos")
        for text in ("3.50 x 10-4", "(see Table 2)", "NONE"):
            self.assertEqual(as_written(text), text)

    def test_extracted_values_are_not_python_text(self):
        value, = extract("Li6PS5Cl has an activation energy of 0.30 eV.")["ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual(value.raw_value, "0.30 eV")


class SpacedFormulaTests(unittest.TestCase):
    def test_subscripts_set_apart_are_joined(self):
        for spaced, joined in [("the Na 3 PSe 4 phase", "the Na3PSe4 phase"),
                               ("Li 6.4 La 3 Zr 1.4 Ta 0.6 O 12 garnet", "Li6.4La3Zr1.4Ta0.6O12 garnet"),
                               ("Li 6 PS 5 Cl is", "Li6PS5Cl is"), ("Li 10 GeP 2 S 12.", "Li10GeP2S12."),
                               ("Li 1.3 Al 0.3 Ti 1.7 (PO 4 ) 3 (LATP)", "Li1.3Al0.3Ti1.7(PO4)3 (LATP)"),
                               ("a LiNbO 3 coating", "a LiNbO3 coating"), ("Table 2 Li 3 YCl 6", "Table 2 Li3YCl6")]:
            self.assertEqual(join_spaced_formulas(spaced), joined)

    def test_prose_and_quantities_stay_as_they_are(self):
        for text in ("heated at 300 K for 2 h", "Fig. 3 S 2 and", "The XPS Ni 2 p and O 1 s", "Fig. SI 2 shows",
                     "CO 2 gas", "a LiPON 2 µm film", "SnO 2 wt% and", "section 2 C 3",
                     "Li(Ni 0.8 Co 0.1 Mn 0.1 )O 2", "between 2 and 3 V vs Li"):
            self.assertEqual(join_spaced_formulas(text), text)
        self.assertEqual(join_spaced_formulas("Li 3 PS 4 In this work"), "Li3PS4 In this work")  # "In": a word

    def test_the_material_is_the_whole_formula(self):
        value, = extract("The ionic conductivity of Na 3 PSe 4 is σ = 1.16 mS cm−1 at room temperature.")[
            "ELECTROCHEMICAL"]["Ionic_Conductivity"]
        self.assertEqual(value.material_formula, "Na3PSe4")


class EquationTests(unittest.TestCase):
    def test_a_sentence_naming_a_law_gets_its_standard_form(self):
        text, basis = equation_columns("Arrhenius", "Arrhenius plot of the ionic conductivity values for the samples.")
        self.assertIn("exp(−Ea", text)
        self.assertTrue(basis.startswith("the standard form of the Arrhenius law"))
        self.assertIn("method", equation_columns("NEB", "The barrier was computed by the NEB method in VASP.")[1])

    def test_a_written_equation_stays_as_written(self):
        self.assertEqual(equation_columns("Arrhenius", "σT = A exp(−Ea/kBT)"), ("σT = A exp(−Ea/kBT)", "written in the paper"))

    def test_rows_of_earlier_versions_are_answered_the_same_way(self):
        old = pd.DataFrame([{"paper_id": "a", "equation_type": "Arrhenius", "context_sentence": "NONE",
                             "equation_text": "The Arrhenius plots of all samples are linear over the range."}])
        new = _equation_rows(old)
        self.assertEqual(new.loc[0, "context_sentence"], old.loc[0, "equation_text"])  # the sentence is kept
        self.assertIn("exp(", new.loc[0, "equation_text"])


class SpeciesTests(unittest.TestCase):
    def test_the_species_a_sentence_says_moves(self):
        cases = [
            ("the temperature-dependent Co diffusion coefficient is determined and an activation energy Ea = 1.65 eV",
             "Li7La3Zr2O12", "Co"),
            ("transferring electrons from the Li/PEGDME interface to bulk PEGDME would need an energy barrier of 2.07 eV",
             "Li6PS5Cl", "electron"),
            ("The Li+ migration barrier in Li3InCl6 is 0.33 eV.", "Li3InCl6", "Li+"),
            ("Sodium diffusion in the bulk has a barrier of 0.25 eV.", "Na3SbS4", "Na+"),
            ("The oxide-ion diffusion coefficient is 1e-9 cm2/s.", "La2Mo2O9", "O2-"),
        ]
        for sentence, formula, species in cases:
            found, basis = mobile_species("Activation_Energy", sentence, formula)
            self.assertEqual(found, species, sentence)
            self.assertTrue(basis.startswith("stated"), basis)

    def test_words_that_are_no_species(self):
        self.assertEqual(stated_species("at 300 K conductivity was 1e-3 S/cm"), [])
        self.assertEqual(stated_species("In conductivity measurements, the value was 0.5 mS/cm."), [])
        self.assertEqual(stated_species("Electron microscopy shows dense grains."), [])

    def test_without_a_statement_the_composition_and_the_paper_answer(self):
        self.assertEqual(mobile_species("Activation_Energy", "Ea is 0.3 eV.", "Na3PSe4")[0], "Na+")
        species, basis = mobile_species("Ionic_Conductivity", "It is 1e-4 S/cm.", "LiNaSO4", "Na+", 5)
        self.assertEqual(species, "Na+")
        self.assertIn("the one this paper is about", basis)
        self.assertEqual(mobile_species("Electronic_Conductivity", "It is 1e-9 S/cm.", "Li7La3Zr2O12")[0], "electron")
        species, basis = mobile_species("Ionic_Conductivity", "It is 1e-4 S/cm.", "")
        self.assertEqual(species, "Li+")
        self.assertTrue(basis.startswith("assumed"))

    def test_plausibility(self):
        self.assertEqual(plausibility("Activation_Energy", "0.30 eV", "Li+"), "in range")
        self.assertIn("outside", plausibility("Activation_Energy", "0.01 eV", "Li+"))
        self.assertIn("transport of Co", plausibility("Activation_Energy", "0.4 eV", "Co"))
        self.assertIn("outside", plausibility("Ionic_Conductivity", "2 S/cm", "Li+"))
        self.assertEqual(plausibility("Electronic_Conductivity", "1e-9 S/cm", "electron"), "in range")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_the_value_tables_say_which_species_moves_and_flag_the_doubtful(self):
        ranked = Ranker.process(extract(
            "Li7La3Zr2O12 has an activation energy of 0.41 eV.",
            "In Li7La3Zr2O12, the Co diffusion coefficient gives an activation energy of 1.65 eV."))
        paper = PaperData(paper_id="x.pdf", filename="x.pdf", metadata={})
        paper.materials, paper.electrochemical, paper.relations = (ranked["materials"], ranked["ELECTROCHEMICAL"],
                                                                   ranked["relations"])
        StrictExporter(self.folder).export([paper])
        table = pd.read_csv(Path(self.folder) / "activation_energy.csv", dtype=str)
        rows = dict(zip(table.activation_energy_eV.astype(float), zip(table.mobile_ion, table.plausibility)))
        self.assertEqual(rows[0.41], ("Li+", "in range"))
        self.assertEqual(rows[1.65][0], "Co")
        self.assertTrue(rows[1.65][1].startswith("check:"))
        self.assertTrue(table.basis.str.contains("ion: ").all())
        self.assertNotIn("('", " ".join(table.raw_value))


if __name__ == "__main__":
    unittest.main()


class UnitTests(unittest.TestCase):
    def test_a_symbol_font_read_as_other_letters(self):
        text = normalize_scientific_text("a specific conductivity of 2.9Õ10¢9 W¢1cm¢1 at 323 K")
        self.assertIn("2.9 × 10−9 S cm−1", text)

    def test_inverse_ohms_are_siemens(self):
        for written in ("2.9 × 10−9 Ω−1 cm−1", "2.9 × 10−9 Ω−1cm−1", "2.9 × 10−9 (Ω cm)−1", "2.9 × 10−9 ohm-1 cm-1",
                        "2.9 × 10−9 mho/cm"):
            self.assertIn("S cm−1", normalize_scientific_text(written), written)
        value, = extract("Li3InCl6 has an ionic conductivity of 1.49 × 10−3 Ω−1 cm−1 at 298 K.")[
            "ELECTROCHEMICAL"]["Ionic_Conductivity"]
        self.assertEqual(value.normalized_value, "0.00149 S/cm")

    def test_siemens_per_metre(self):
        for written, expected in (("0.12 S m−1", "0.0012 S/cm"), ("0.12 S/m", "0.0012 S/cm"),
                                  ("3.5 × 10−2 S m−1", "0.00035 S/cm"), ("2 mS m-1", "2e-05 S/cm")):
            value, = extract(f"Li6PS5Cl has an ionic conductivity of {written} at 298 K.")[
                "ELECTROCHEMICAL"]["Ionic_Conductivity"]
            self.assertEqual(value.normalized_value, expected, written)
        found = extract("The ionic conductivity of Li3PS4 was measured for 5 S min after cooling.")
        self.assertFalse(found.get("ELECTROCHEMICAL", {}).get("Ionic_Conductivity"))  # seconds, minutes: no unit

    def test_other_ohms_stay(self):
        for text in ("a resistance of 120 Ω cm2", "R = 50 Ω and C = 3 nF", "José Õliveira"):
            self.assertEqual(normalize_scientific_text(text), text)


class FileTests(unittest.TestCase):
    def test_the_doi_a_file_name_gives(self):
        from LocalExtraction.pipeline import doi_of_name
        self.assertEqual(doi_of_name("/x/10.1002_inf2.12487.pdf"), "10.1002/inf2.12487")
        self.assertEqual(doi_of_name("10.1016_j.jcis.2025.02.188.pdf"), "10.1016/j.jcis.2025.02.188")
        self.assertEqual(doi_of_name("Li6PS5Cl review.pdf"), "")

    def test_a_pdf_without_a_readable_page_is_refused_with_its_reason(self):
        from unittest import mock

        from LocalExtraction import parser
        empty = mock.MagicMock(page_count=0)
        with mock.patch.object(parser.fitz, "open", return_value=empty):
            with self.assertRaisesRegex(ValueError, "damaged or incomplete"):
                parser.DocumentParser("cut.pdf").parse()


class PartlyRebuiltTests(unittest.TestCase):
    """A rebuild stopped part-way leaves rebuild_pending.json: the parts that read the database say so."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / "web_output"
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder.parent, True)
        (self.folder / "rebuild_pending.json").write_text('{"from": ["previous_x"]}', encoding="utf-8")

    def test_ranking_says_it(self):
        from SelectingTopMaterial import loader
        _, (report,) = loader.load([self.folder])
        self.assertIn("rebuild is not finished", loader.describe(report))  # nothing written yet
        pd.DataFrame([{"paper_id": "a.pdf", "material_formula": "Li3PS4", "activation_energy_eV": "0.3"}]).to_csv(
            self.folder / "activation_energy.csv", index=False)
        _, (report,) = loader.load([self.folder])
        self.assertIn("only partly rebuilt", loader.describe(report))

    def test_classification_says_it(self):
        from Classification.database import partly_rebuilt
        self.assertTrue(partly_rebuilt(self.folder))
        (self.folder / "rebuild_pending.json").unlink()
        self.assertFalse(partly_rebuilt(self.folder))


def _conductivities(results):
    return sorted((f.material_formula, f.normalized_value) for f in results["ELECTROCHEMICAL"]["Ionic_Conductivity"])


class SeriesTests(unittest.TestCase):
    """A value given for one member of a series ("x = 0.1") is the value of that compound."""

    def test_a_label_of_the_series_at_a_stated_x(self):
        found = extract("We prepared Li6.5+xLa3-xBaxZr1.5Ta0.5O12 (LLBZT) garnets.",
                        "The highest σ = 8.34 × 10−4 S cm−1 was obtained in LLBZT with x = 0.1 at 27 °C.")
        self.assertEqual(_conductivities(found), [("Ba0.1Li6.6La2.9Zr1.5Ta0.5O12", "0.000834 S/cm")])

    def test_the_series_of_the_sentence_before(self):
        found = extract("We studied the Ge-substituted Li6+xP1-xGexS5I argyrodites. For x = 0.25, the ionic "
                        "conductivity reaches 5.4 mS cm-1 at 25 °C.")
        self.assertEqual(_conductivities(found), [("Li6.25Ge0.25P0.75S5I", "0.0054 S/cm")])

    def test_without_x_the_series_stays_as_written(self):
        found = extract("We studied Li6+xP1-xGexS5I. The conductivity reaches 5.4 mS cm-1 at 25 °C.")
        self.assertNotIn("Li6.25Ge0.25P0.75S5I", [m for m, _ in _conductivities(found)])

    def test_a_mixture_with_a_mixture_inside_it(self):
        from LocalExtraction.chemistry import ChemistryEngine
        open_series = ChemistryEngine.find_materials("The (100 −x)(0.75Li2S· 0.25P2S5)·xLiBH4 electrolytes were milled.")
        self.assertEqual([(m["formula"], m.get("open_series")) for m in open_series],
                         [("(100-x)(0.75Li2S·0.25P2S5)·xLiBH4", True)])  # one material, not its parts
        member = ChemistryEngine.find_materials("The (100−x)(0.75Li2S·0.25P2S5)·xLiBH4 sample with x = 50 was hot.")[0]
        self.assertEqual(member["formula"], "50(0.75Li2S-0.25P2S5)-50LiBH4")
        self.assertEqual(member["elements"], {"Li": 1.25, "S": 1.0, "P": 0.25, "B": 0.5, "H": 2.0})
        other_way = ChemistryEngine.find_materials("xLiI·(100−x)(0.75Li2S·0.25P2S5) glass with x = 30")[0]
        self.assertEqual(other_way["formula"], "30LiI-70(0.75Li2S-0.25P2S5)")
        # a lone "xLiBH4", the rest of its mixture not read, is no series
        self.assertFalse(ChemistryEngine.find_materials("added xLiBH4 to it")[0].get("open_series"))

    def test_a_value_of_x_pages_after_the_series(self):
        found = extract("Samples with compositions of (100 −x)(0.75Li2S·0.25P2S5)·xLiBH4 (mol %) were prepared.",
                        "The XRD patterns show a new phase.", "The LiBH4 crystal is shown for comparison.",
                        "The x = 50 samples exhibited a high conductivity of 1.8 × 10−3 S cm−1 at 25 °C.")
        self.assertEqual(_conductivities(found), [("50(0.75Li2S-0.25P2S5)-50LiBH4", "0.0018 S/cm")])

    def test_x_is_given_only_to_a_series_it_fits(self):
        # x = 50 is a share of the mixture, not the x of Li7−xPS6−x(BH4)x (it would give Li−43)
        found = extract("Samples of (100 −x)(0.75Li2S·0.25P2S5)·xLiBH4 (mol %) were prepared.",
                        "The new phase is the argyrodite Li7−xPS6−x(BH4)x.",
                        "The x = 50 samples exhibited a high conductivity of 1.8 × 10−3 S cm−1 at 25 °C.")
        self.assertEqual(_conductivities(found), [("50(0.75Li2S-0.25P2S5)-50LiBH4", "0.0018 S/cm")])

    def test_a_group_times_x_is_written_as_a_chemist_writes_it(self):
        from LocalExtraction.chemistry import ChemistryEngine
        self.assertEqual(ChemistryEngine.find_materials("Li7−xPS6−x(BH4)x was made.")[0]["formula"], "Li7-xBxPH4xS6-x")

    def test_a_table_with_one_row_per_x(self):
        table = {"type": "Table", "page": 3, "section": "Results", "table_number": "2",
                 "caption": "Table 2. Ionic conductivities of the Li1+xAlxGe2-x(PO4)3 samples at 25 °C.",
                 "headers": ["x", "σ tot (S cm-1)"], "material_column": "NONE",
                 "rows": [{"x": "0.2", "σ tot (S cm-1)": "1.1 × 10-4"}, {"x": "0.4", "σ tot (S cm-1)": "3.2 × 10-4"}],
                 "text": "x σ tot (S cm-1) 0.2 1.1 × 10-4 0.4 3.2 × 10-4"}
        found = ExtractorEngine.extract_all([table])
        self.assertEqual(_conductivities(found), [("Li1.2Al0.2Ge1.8(PO4)3", "0.00011 S/cm"),
                                                  ("Li1.4Al0.4Ge1.6(PO4)3", "0.00032 S/cm")])
        self.assertEqual({f.transport_component for f in found["ELECTROCHEMICAL"]["Ionic_Conductivity"]}, {"total"})

    def test_a_column_that_names_the_variable_in_brackets(self):
        # Table 1 of doi:10.1007/s11581-025-06639-w: "Content of Sr (x)" gives each row its member of the series.
        table = {"type": "Table", "page": 13, "section": "Results", "table_number": "1",
                 "caption": "Table 1: Values of Ionic conductivity and activation energy of Li6.75+xLa3-xSrxZr1.75Ta0.25O12",
                 "headers": ["Content of Sr (x)", "Ionic conductivity (S/cm)"], "material_column": "NONE",
                 "rows": [{"Content of Sr (x)": "0", "Ionic conductivity (S/cm)": "3.02 x 10-5"},
                          {"Content of Sr (x)": "0.05", "Ionic conductivity (S/cm)": "3.50 x 10-4"}],
                 "text": "Content of Sr (x) Ionic conductivity (S/cm) 0 3.02 x 10-5 0.05 3.50 x 10-4"}
        found = ExtractorEngine.extract_all([table])
        self.assertEqual(_conductivities(found), [("Li6.75La3Zr1.75Ta0.25O12", "3.02e-05 S/cm"),
                                                  ("Sr0.05Li6.8La2.95Zr1.75Ta0.25O12", "0.00035 S/cm")])


class SigmaSubscriptTests(unittest.TestCase):
    def test_the_component_of_a_conductivity_column(self):
        from LocalExtraction.transport import classify_transport_contexts
        for header, component in (("σ tot (S cm-1)", "total"), ("σ g (S·cm-1)", "bulk"), ("σ gb (S·cm-1)", "grain_boundary"),
                                  ("σbulk", "bulk"), ("σ_GB (S/cm)", "grain_boundary"), ("σT (S K cm-1)", "unspecified"),
                                  ("σ (S cm-1)", "unspecified")):
            self.assertEqual(classify_transport_contexts((header,)).component, component, header)
