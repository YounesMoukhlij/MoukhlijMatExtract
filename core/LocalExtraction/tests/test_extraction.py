# LocalExtraction/tests/test_extraction.py
"""Tests of what is extracted from a paper's text: which numbers are values of which quantity,
which material each is for, and where the rest of its context comes from.

They run on sentences, not PDFs, so they are instant and need no file. Run them with:
    python -m unittest discover -s LocalExtraction/tests -t . -v   (or: pytest LocalExtraction)
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["MME_OFFLINE"] = "1"  # the tests never go on the network

import pandas as pd

from LocalExtraction import quantities
from LocalExtraction.chemistry import Abbreviations, ChemistryEngine
from LocalExtraction.config import SchemaConfig
from LocalExtraction.context import temperature_range
from LocalExtraction.exporter import StrictExporter
from LocalExtraction.extractor import ExtractorEngine
from LocalExtraction.models import ExtractedField, PaperData
from LocalExtraction.normalizer import DataNormalizer, normalize_scientific_text, repair_hyphenation
from LocalExtraction.parser import repair_blocks
from LocalExtraction.ranking import Ranker
from LocalExtraction.study import Study, is_quoted

# A paper has to say enough about how it worked to be called computational or experimental.
COMPUTATIONAL = ("Density functional theory (DFT) calculations were performed with VASP using the PBE functional. "
                 "AIMD simulations in the NVT ensemble were run at 600, 800 and 1000 K to obtain the Li diffusivity "
                 "of Li6PS5Cl. The supercell of Li6PS5Cl contains 52 atoms.")
EXPERIMENTAL = ("Li6PS5Cl was synthesized by ball milling the precursors and the pellets were sintered. "
                "Impedance spectroscopy (EIS) was measured from 25 to 100 °C on Li6PS5Cl pellets with blocking electrodes. "
                "XRD patterns of Li6PS5Cl were collected on a diffractometer.")


def extract(*paragraphs, section="Results", title=""):
    blocks = [{"text": text, "page": 1, "section": section, "type": "Text"} for text in paragraphs]
    return ExtractorEngine.extract_all(blocks, title=title)


def values(results, prop="Activation_Energy"):
    return [(f.normalized_value, f.material_formula) for f in results["ELECTROCHEMICAL"][prop]]


def found(text):
    """(property, value, the paper's word for it) of every transport value in a sentence."""
    return [(q.prop, DataNormalizer.normalize(q.raw, q.kind), q.term) for q in quantities.find(text)]


def materials(text, abbreviations=None):
    return [m["formula"] for m in ChemistryEngine.find_materials(text, abbreviations)]


class OneActivationEnergyTests(unittest.TestCase):
    """Whatever a paper calls the energy barrier of an ion hop, it is one property, in eV."""

    def test_every_name_is_the_same_property(self):
        for wording, term in (("an activation energy of 0.30 eV", "activation energy"),
                              ("a migration barrier of 0.30 eV", "migration barrier"),
                              ("an energy barrier of 0.30 eV", "energy barrier"),
                              ("a hopping barrier of 0.30 eV", "hopping barrier"),
                              ("a diffusion energy barrier of 0.30 eV", "diffusion energy barrier"),
                              ("a barrier of only 0.30 eV", "barrier"),
                              ("a migration energy of 0.30 eV", "migration energy"),
                              ("Ea = 0.30 eV", "Ea"), ("E_a of 0.30 eV", "Ea"), ("an Em of 0.30 eV", "Em")):
            with self.subTest(wording=wording):
                self.assertEqual(found(f"The sample shows {wording}."), [("Activation_Energy", "0.3 eV", term)])

    def test_there_is_no_second_property(self):
        self.assertNotIn("Migration_Barrier", SchemaConfig.SCHEMA["ELECTROCHEMICAL"])

    def test_the_papers_word_is_kept_with_the_value(self):
        barrier, = extract("LiBiO2 has a low migration barrier of 0.27 eV.")["ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual((barrier.normalized_value, barrier.material_formula, barrier.reported_as),
                         ("0.27 eV", "LiBiO2", "migration barrier"))

    def test_named_after_the_value(self):
        self.assertEqual(found("with a low 0.25 eV migration barrier along c"),
                         [("Activation_Energy", "0.25 eV", "migration barrier")])
        self.assertEqual(found("a 5.1 eV band gap"), [])

    def test_always_in_ev(self):
        self.assertEqual(found("the lowest activation energy (31.2 kJ mol-1)")[0][1], "0.3234 eV")
        self.assertEqual(found("an activation energy of 250 meV")[0][1], "0.25 eV")

    def test_other_energies_are_not_activation_energies(self):
        for text in ("The activation energy was fitted and the band gap is 5.1 eV.",
                     "The migration barrier (MAE = 0.21 eV) was predicted by the model.",
                     "For the barrier calculations a Hubbard U value of 3.9 eV was used.",
                     "The barrier calculation was converged within 0.01 eV/Å.",
                     "The barrier lies 25 meV/atom above the hull.",
                     "A Schottky barrier of 0.5 eV forms at the contact."):
            with self.subTest(text=text):
                self.assertEqual(found(text), [])

    def test_a_far_value_still_belongs_to_its_name(self):
        text = ("The activation energy for the ionic transport was derived from the temperature-dependent Nyquist plots "
                "measured in the temperature range 25 to 60 °C and is found to be 0.22 eV.")
        self.assertEqual(found(text), [("Activation_Energy", "0.22 eV", "activation energy")])

    def test_changes_bounds_and_inputs_are_not_results(self):
        for text, kept in (("In LiBiO2 the activation energy decreases by 0.1 eV to 0.25 eV.", ["0.25 eV"]),
                           ("LiBiO2 has an activation energy of 0.3 eV, which is 0.2 eV lower than in LiBiS2.", ["0.3 eV"]),
                           ("For LiBiO2 an activation energy below 0.3 eV is needed.", []),
                           ("The difference between the lowest and the highest migration barriers of LiBiO2 is 662 meV.", []),
                           ("The upper limit of the migration barrier of LiBiO2 is 750 meV.", []),
                           ("An ionic conductivity above 1 mS/cm is required for LiBiO2.", [])):
            with self.subTest(text=text):
                results = extract(text)
                got = [v for v, _ in values(results) + values(results, "Ionic_Conductivity")]
                self.assertEqual(got, kept)

    def test_two_quantities_for_two_numbers(self):
        text = "The formation energy and the migration energy are 2.4 and 2.6 eV, respectively."
        self.assertEqual(found(text), [("Activation_Energy", "2.6 eV", "migration energy")])

    def test_a_rotation_is_marked_as_one(self):
        barrier, = extract("In Li3PS4 the activation energy for the reorientation of the PS4 groups is 0.40 eV.")[
            "ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual(barrier.reported_as, "activation energy (of a rotation)")

    def test_an_old_job_file_still_loads(self):
        from WebScraping.averageScrap.job import load_job
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "job.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("search:\n  queries: [x]\nextract:\n  properties: [Activation_Energy, Migration_Barrier]\n")
        self.assertEqual(load_job(path).extract.properties, ["Activation_Energy"])


class ValueFirstTests(unittest.TestCase):
    """A number with the unit of a conductivity is one, with or without the word."""

    def test_a_conductivity_needs_no_keyword(self):
        text = "Halide electrolytes such as Li3InCl6 (1.5 mS cm−1 at 25 °C) and Li3YCl6 (0.5 mS cm−1 at 25 °C) followed."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"),
                         [("0.0015 S/cm", "Li3InCl6"), ("0.0005 S/cm", "Li3YCl6")])

    def test_each_value_goes_to_the_material_beside_it(self):
        text = "The activation energies were 0.38 eV for Li6PS5Cl, 0.36 eV for Li6PS5Br and 0.31 eV for Li6PS5I."
        self.assertEqual(values(extract(text)), [("0.38 eV", "Li6PS5Cl"), ("0.36 eV", "Li6PS5Br"), ("0.31 eV", "Li6PS5I")])
        text = "The reduced activation energy (Ea) of 0.281 eV (0.8Li2O–ZrCl4) and 0.317 eV (0.8Li2S–ZrCl4) is notable."
        self.assertEqual(values(extract(text)), [("0.281 eV", "0.8Li2O-ZrCl4"), ("0.317 eV", "0.8Li2S-ZrCl4")])

    def test_a_condition_may_stand_between_value_and_material(self):
        text = "Hong found a poor ionic conductivity (10−7 S cm−1 at ambient temperature) in Li14ZnGe4O16 and in Li4GeO4."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("1e-07 S/cm", "Li14Zn(GeO4)4")])

    def test_lists_are_paired_off_only_on_request(self):
        paired = "Li6PS5Cl, Li6PS5Br and Li6PS5I show activation energies of 0.6, 1.2 and 1.5 eV, respectively."
        self.assertEqual(values(extract(paired)), [("0.6 eV", "Li6PS5Cl"), ("1.2 eV", "Li6PS5Br"), ("1.5 eV", "Li6PS5I")])
        unpaired = "The energy barriers are 0.6, 1.2 and 1.5 eV for Li6PS5Cl, Li6PS5Br and Li6PS5I."
        self.assertEqual({formula for _, formula in values(extract(unpaired))}, {"NONE"})

    def test_named_with_the_quantity(self):
        text = "The activation energy of Li6PS5Cl is 0.30 eV, lower than that of Li6PS5I."
        self.assertEqual(values(extract(text)), [("0.3 eV", "Li6PS5Cl")])

    def test_what_a_comparison_names_is_the_other_party(self):
        text = "Similar to the Li3PS4 results, the activation energy (0.67 eV) was higher than expected."
        self.assertEqual(values(extract(text)), [("0.67 eV", "NONE")])

    def test_a_value_inside_a_comparison_is_the_compared_materials(self):
        text = ("The conductivity of Li2SrSiS4 (with an NEB activation energy of 0.34 eV) is lower than that of "
                "Li2BaSnS4 (with an NEB activation energy of 0.56 eV).")
        self.assertEqual(values(extract(text)), [("0.34 eV", "SrLi2SiS4"), ("0.56 eV", "BaLi2SnS4")])
        text = "For the polymer the activation energy was only 0.48 eV, lower than in the oxide ceramics (Ea = 0.55 eV for LiPON)."
        self.assertEqual(values(extract(text)), [("0.48 eV", "NONE"), ("0.55 eV", "Li2.9PN0.46O3.3")])

    def test_materials_named_together_take_their_values_in_order(self):
        text = "We found Li6PS5Cl and Li6PS5Br, with σRT = 82 mS/cm (Ea = 0.166 eV) and σRT = 17 mS/cm (Ea = 0.208 eV)."
        results = extract(text)
        self.assertEqual(values(results), [("0.166 eV", "Li6PS5Cl"), ("0.208 eV", "Li6PS5Br")])
        self.assertEqual(values(results, "Ionic_Conductivity"), [("0.082 S/cm", "Li6PS5Cl"), ("0.017 S/cm", "Li6PS5Br")])

    def test_a_value_with_a_subject_of_its_own_takes_no_other_material(self):
        for text in ("The activation energy of PL is higher (0.26 eV) than that of PLL (0.13 eV), the electrolyte without LLZO.",
                     "For the MgF2-doped samples the energy barrier decreases to 0.40 eV.",
                     "The barrier was calculated to be only 0.25 eV, very close to Li10GeP2S12 (LGPS)."):
            with self.subTest(text=text):
                self.assertEqual({formula for _, formula in values(extract(text))}, {"NONE"})

    def test_a_sentence_end_hidden_by_a_unit_or_a_citation(self):
        value, = extract(COMPUTATIONAL.replace("Li6PS5Cl", "Li2GeS3"),
                         "The impedance of Li2GeS3 pellets gives an activation energy of 0.37 eV. Bond-valence calculations of Li2GeS3 show three pathways.")[
            "ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual(value.data_origin, "experimental")
        text = "LiBiO2 reaches a conductivity as high as 10 mS cm−1.86 The screened phase of LiBH4 is disordered."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.01 S/cm", "LiBiO2")])

    def test_each_clause_has_its_own_subject(self):
        text = "Li6PS5Cl shows an activation energy of 0.30 eV, whereas Li6PS5I shows 0.45 eV."
        self.assertEqual(values(extract(text)), [("0.3 eV", "Li6PS5Cl"), ("0.45 eV", "Li6PS5I")])
        text = ("The activation barrier of LiTiPO5 exceeds 1 eV, as measured experimentally,[64] whereas its analogue "
                "Li2HfSiO5(II), which has a higher Li ratio, exhibits a much lower barrier of 0.38 eV.")
        self.assertEqual(values(extract(text)), [("0.38 eV", "Li2HfSiO5")])

    def test_a_value_of_an_unnamed_class_takes_no_material(self):
        text = "The activation barrier of amorphous LiPO2F2 (Ea = 0.40 eV) exceeds that of typical superionic conductors (0.1–0.3 eV)."
        self.assertEqual(values(extract(text)), [("0.4 eV", "LiPO2F2"), ("0.1 eV", "NONE"), ("0.3 eV", "NONE")])

    def test_ionic_or_electronic(self):
        self.assertEqual([(p, v) for p, v, _ in found("an ionic conductivity of 1.2 mS/cm and an electronic conductivity of 4 × 10−9 S/cm")],
                         [("Ionic_Conductivity", "0.0012 S/cm"), ("Electronic_Conductivity", "4e-09 S/cm")])
        self.assertEqual([(p, v) for p, v, _ in found("the electronic and ionic conductivities are 1.2 × 10−9 and 3.4 × 10−3 S cm−1, respectively")],
                         [("Electronic_Conductivity", "1.2e-09 S/cm"), ("Ionic_Conductivity", "0.0034 S/cm")])
        self.assertEqual([(p, v) for p, v, _ in found("NZSP with 5.03 × 10−6 S cm−1 electronic conductivity")],
                         [("Electronic_Conductivity", "5.03e-06 S/cm")])

    def test_numbers_as_printed(self):
        self.assertEqual(found("D = 3.1 ± 0.3 × 10−6 cm2/s")[0][1], "3.1e-06 cm**2/s")
        self.assertEqual(found("a conductivity of 10−4 S.cm-1")[0][1], "0.0001 S/cm")
        self.assertEqual([v for _, v, _ in found("MgSc2Se4 (10- 4 S.cm-1 at 25°C)")], ["0.0001 S/cm"])
        self.assertEqual([v for _, v, _ in found("an ionic conductivity of 5–10 mS/cm")], ["0.005 S/cm", "0.01 S/cm"])
        # A bare "10−13" is a power of ten in S/cm and the upper end of a range in mS/cm.
        self.assertEqual([v for _, v, _ in found("a conductivity of only 10−13 S cm−1")], ["1e-13 S/cm"])
        self.assertEqual([v for _, v, _ in found("an ionic conductivity of 10–20 mS/cm")], ["0.02 S/cm"])
        self.assertEqual([v for _, v, _ in found("conductivities of only 10−9[45] and 10−13 S cm−1[46]")], ["1e-09 S/cm", "1e-13 S/cm"])
        # The power of ten of a conductivity, the ways a PDF prints it.
        for text, value in (("a conductivity of 5.10-9 S cm-1", "5e-09 S/cm"), ("a conductivity of 2.6·10-5 S cm-1", "2.6e-05 S/cm"),
                            ("a conductivity of 1.06×10 –4 S/cm", "0.000106 S/cm"), ("a conductivity of 2.9 × 10− 4 S cm− 1", "0.00029 S/cm"),
                            ("the electronic conductivity of LiF (10−31 S·cm−1)", "1e-31 S/cm"),
                            ("a conductivity of 3.8 × 10–10 ± 1.1×10–10 S cm−1", "3.8e-10 S/cm")):
            with self.subTest(text=text):
                self.assertEqual([v for _, v, _ in found(text)], [value])
        # One power of ten for a whole range or list; a minus sign between two conductivities is a dash.
        self.assertEqual([v for _, v, _ in found("a conductivity in the range of 1–2 × 10−4 S/cm")], ["0.0001 S/cm", "0.0002 S/cm"])
        self.assertEqual([v for _, v, _ in found("conductivities of only 10−9−10−8 S cm−1")], ["1e-09 S/cm", "1e-08 S/cm"])
        self.assertEqual([v for _, v, _ in found("a conductivity of 0.3−0.5 mS cm−1")], ["0.0003 S/cm", "0.0005 S/cm"])
        # What is left of an exponent, or a page number in front of a value, is no value.
        self.assertEqual(found("the total conductivity was the highest –4 S/cm"), [])
        self.assertEqual([v for _, v, _ in found("Article 778057 5 and 2.9 × 10–6 S·cm−1, respectively")], ["2.9e-06 S/cm"])
        # The value of a composition variable is not a conductivity that lost its unit.
        self.assertEqual([v for _, v, _ in found("a conductivity of 3.9 mS cm-1 for x = 0.25 and 7.5 mS cm-1 for x = 0.6")],
                         ["0.0039 S/cm", "0.0075 S/cm"])

    def test_additives_and_electrodes_take_no_conductivity(self):
        for text in ("With 1 wt% MgF2 additive the ionic conductivity reaches 2.03 mS cm−1 and is stable against lithium metal.",
                     "With a Li+ conductivity of 2.03 mS cm−1, these halide SEs are compatible with the 4 V LiCoO2 cathode7."):
            with self.subTest(text=text):
                self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.00203 S/cm", "NONE")])

    def test_composites_and_polymer_electrolytes_are_not_their_filler_or_salt(self):
        for text in ("The ionic conductivity of LLZTO@PEO reached 1.4 × 10−4 S cm−1.",
                     "Cui et al. observed a conductivity of 1.4 × 10−4 S cm−1 for the electrolyte containing "
                     "polyacrylonitrile-LiClO4 and 15 wt% Li0.33La0.557TiO3.",
                     "The PEO-LiClO4 electrolyte shows a conductivity of 1.4 × 10−4 S cm−1.",
                     # The ceramic is what the bound is given for, not what was measured.
                     "A conductivity of 1.4 × 10−4 S cm−1 was observed for the electrolyte containing 15 wt% "
                     "Li0.33La0.557TiO3, not higher than ≈10−3 S cm−1 for the Li0.33La0.557TiO3 ceramic."):
            with self.subTest(text=text):
                self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.00014 S/cm", "NONE")])
        self.assertEqual(values(extract("The LiClO4 pellet shows a conductivity of 2 × 10−9 S cm−1."), "Ionic_Conductivity"),
                         [("2e-09 S/cm", "LiClO4")])

    def test_each_value_follows_the_material_named_before_it(self):
        text = ("Na2(CB9H10)(CB11H12) with an ionic conductivity of 7·10-2 S cm-1 at 300 K and 0.7Li(CB9H10)–0.3Li(CB11H12) "
                "with an ionic conductivity of 6.7·10−3 S cm−1 at 298 K are examples.")
        self.assertEqual(values(extract(text), "Ionic_Conductivity"),
                         [("0.07 S/cm", "Na2B20H22C2"), ("0.0067 S/cm", "0.7LiB9H10C-0.3LiB11H12C")])
        # Two values of one material stay with it.
        text = "Li7La3Zr2O12 has a conductivity of 0.5 mS/cm at room temperature and 1.2 mS/cm at 60 °C."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.0005 S/cm", "Li7La3Zr2O12"), ("0.0012 S/cm", "Li7La3Zr2O12")])

    def test_a_variant_named_before_a_value_takes_it(self):
        text = "Li6PS5Cl shows a conductivity of 3 mS/cm, whereas the Br-substituted sample shows 5 mS/cm."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.003 S/cm", "Li6PS5Cl"), ("0.005 S/cm", "NONE")])
        text = ("Whereas Li3PO4 and Li2S have a room temperature conductivity of only 10−9[45] and 10−13 S cm−1[46] "
                "respectively, the composite glasses above have a conductivity of 1.5 × 10−3 and 8 × 10−5 mS cm−1, respectively.")
        self.assertEqual(values(extract(text), "Ionic_Conductivity"),
                         [("1e-09 S/cm", "Li3PO4"), ("1e-13 S/cm", "Li2S"), ("1.5e-06 S/cm", "NONE"), ("8e-08 S/cm", "NONE")])
        # The same subject goes on after "but": nothing new is named.
        text = "Li7La3Zr2O12 has a conductivity of 0.5 mS/cm, but the activation energy is 0.31 eV."
        self.assertEqual(values(extract(text)), [("0.31 eV", "Li7La3Zr2O12")])

    def test_what_a_value_is_comparable_to_is_not_its_material(self):
        text = ("An ionic conductivity of 4.3·10-4 S cm-1 is reached at 423 K, comparable to the ionic conductivity of the "
                "previously reported ball-milled KB11H14.")
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.00043 S/cm", "NONE")])

    def test_what_is_said_of_the_compared_material_is_its_value(self):
        results = extract("The activation energies for Li7TaO6 are slightly higher than the experimental activation barrier for "
                          "Li10GeP2S12, which ranges from 0.22 to 0.25 eV [31, 80] and much lower than the activation barrier "
                          "of 0.55 eV found in LiPON [36].")
        self.assertEqual(values(results), [("0.22 eV", "Li10GeP2S12"), ("0.25 eV", "Li10GeP2S12"), ("0.55 eV", "Li2.9PN0.46O3.3")])
        self.assertEqual({f.attribution for f in results["ELECTROCHEMICAL"]["Activation_Energy"]}, {"cited"})
        # ... while what the sentence goes on to say of its own subject is not.
        text = "The conductivity of Li6PS5Cl exceeds the conductivity of Li3PS4, reaching 5 mS/cm."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.005 S/cm", "Li6PS5Cl")])

    def test_two_forms_of_one_compound_can_be_compared(self):
        results = extract("Li2ZrCl6 (LZC) was studied. The β-LZC polymorph exhibits lower activation energy (Ea = 0.68 eV) than "
                          "α-LZC (Ea = 0.97 eV) when Zr is fully ordered.")
        self.assertEqual([(f.normalized_value, f.material_formula, f.structure) for f in results["ELECTROCHEMICAL"]["Activation_Energy"]],
                         [("0.68 eV", "Li2ZrCl6", "β-phase"), ("0.97 eV", "Li2ZrCl6", "α-phase")])

    def test_materials_compared_with_together(self):
        text = ("At room temperature, the diffusion coefficients for Li6PTeS4Cl and Li6.25PTeS4.25Cl0.75 are 0.7×10-6 and 1×10-6 "
                "cm2 s-1 respectively, almost two orders higher than that for LGPS or Li6.25PS5.25Cl0.75.")
        self.assertEqual(values(extract(text), "Diffusion_Coefficient"),
                         [("7e-07 cm**2/s", "Li6TePS4Cl"), ("1e-06 cm**2/s", "Li6.25TePS4.25Cl0.75")])

    def test_a_material_another_value_stands_next_to_is_not_the_next_values(self):
        text = ("NaLaCl4 (NLC) was prepared. The migration of Na+ ions requires a lower barrier compared to NLC "
                "(0.04 eV in NLC vs. 0.26 eV in NLZC, Fig. 3d).")
        self.assertEqual(values(extract(text)), [("0.04 eV", "NaLaCl4"), ("0.26 eV", "NONE")])

    def test_what_a_value_surpasses_is_not_its_material(self):
        text = ("Li2.5Yb0.5Zr0.5Cl6 was then prepared by ball milling. This material achieved an even higher ionic conductivity "
                "of 2.3 × 10−3 S cm−1, surpassing that of the Hf4+-substituted Li2.6Yb0.6Hf0.4Cl6.")
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.0023 S/cm", "Li2.5Yb0.5Zr0.5Cl6")])

    def test_one_member_of_a_series_for_each_value(self):
        expected = [("0.0039 S/cm", "Li6.25Ge0.25P0.75S5I"), ("0.0075 S/cm", "Li6.6Ge0.6P0.4S5I")]
        for text in ("A conductivity of 3.9 mS cm-1 can be estimated for x = 0.25 and 7.5  mS cm-1 for x = 0.6  in Li6+xP1-xGexS5I.",
                     "The conductivities of Li6+xP1-xGexS5I are 3.9 and 7.5 mS cm-1 for x = 0.25 and 0.6, respectively."):
            with self.subTest(text=text):
                self.assertEqual(values(extract(text), "Ionic_Conductivity"), expected)
        # Two values of x for one conductivity: it is a value of the series, not of one member.
        text = "The conductivity of Li6+xP1-xGexS5I (x = 0.25, 0.6) is about 5 mS cm-1."
        self.assertEqual(values(extract(text), "Ionic_Conductivity"), [("0.005 S/cm", "Li6+xGexP1-xS5I")])

    def test_a_clause_that_refers_back_keeps_the_materials_before_it(self):
        text = ("Na3-xEr1-xZrxCl6 and Na3-xY1-xZrxCl6 were also developed, but their conductivities were as low as "
                "0.040 mS cm−1 at 25 °C and 0.066 mS cm−1 at 20 °C, respectively (vs. 0.018 mS cm−1 of Na2ZrCl6 at 30 °C).")
        self.assertEqual(values(extract(text), "Ionic_Conductivity"),
                         [("4e-05 S/cm", "Na3-xEr1-xZrxCl6"), ("6.6e-05 S/cm", "Na3-xY1-xZrxCl6"), ("1.8e-05 S/cm", "Na2ZrCl6")])


class FormulaTests(unittest.TestCase):
    def test_names_that_are_not_formulas(self):
        self.assertEqual(materials("LiTFSI in PVDF-HFP, the DLi values, UIOSLi and Na-SICs"), [])
        self.assertEqual(materials("PS43− anions, SiO4 and PO4 units, LiS4 tetrahedra, ZrO6 octahedra, the Li6S unit, B12H122− anions"), [])
        self.assertEqual(materials("a potential of 3.80 V vs. Na2Sn"), [])
        self.assertEqual(materials("what a table left of a formula: CaSiS and SbS"), [])

    def test_real_compounds_survive_those_checks(self):
        text = "Li2S8, FeS2, Li2O2, SiO2, P2S5, LiOH, LiH, Li4P2S6, LiMn2O4 and LiNiO2"
        self.assertEqual(materials(text), ["Li2S8", "FeS2", "Li2O2", "SiO2", "P2S5", "LiOH", "LiH", "Li4P2S6", "LiMn2O4", "LiNiO2"])

    def test_a_citation_number_run_into_a_formula(self):
        self.assertEqual(materials("Li6PS5Cl8 and LiCoO223 and Li7La3Zr2O1212 were compared"), ["Li6PS5Cl", "LiCoO2", "Li7La3Zr2O12"])

    def test_one_spelling_per_composition(self):
        self.assertEqual(materials("Li10GeP2S12, Li5PS4Cl2, Na3V2(PO4)3, Li1.3Al0.3Ti1.7(PO4)3 and Li2Sc2/3Cl4"),
                         ["Li10GeP2S12", "Li5PS4Cl2", "Na3V2(PO4)3", "Li1.3Ti1.7Al0.3(PO4)3", "Li2Sc0.6667Cl4"])

    def test_fractions_with_two_digit_denominators(self):
        self.assertEqual(materials("a perovskite Li3/8Sr7/16Ta3/4Hf1/4O3 was made"), ["Sr0.4375Li0.375Hf0.25Ta0.75O3"])

    def test_a_series_is_kept_whole(self):
        self.assertEqual(materials("Li3−xY1−xZrxCl6 was prepared"), ["Li3-xY1-xZrxCl6"])
        self.assertEqual(materials("Li3−xY1−xZrxCl6 (x = 0.5) was prepared"), ["Li2.5Y0.5Zr0.5Cl6"])
        self.assertEqual(materials("LixSr2Co2O5 for x = 0.25 and 0.75"), materials("LixSr2Co2O5"))  # two values of x: none is taken
        self.assertEqual(ChemistryEngine.stated_values("for x = 0.25 and 7.5 mS cm-1 for x = 0.6, or y = 0–1"),
                         [("x", 0.25), ("x", 0.6)])
        self.assertEqual(materials("the Li6−yPS5−yX1+y family (X = Cl, Br)"), [])  # never cut down to "Li6PS5"

    def test_mixtures(self):
        self.assertEqual(materials("0.8Li2O–ZrCl4, 70Li2S-30P2S5, (Li2S)70(P2S5)30, Li2S–P2S5–LiI and Li3InCl6·2H2O"),
                         ["0.8Li2O-ZrCl4", "70Li2S-30P2S5", "70Li2S-30P2S5", "Li2S-P2S5-LiI", "Li3InCl6·2H2O"])
        glass, = ChemistryEngine.find_materials("70Li2S-30P2S5")
        self.assertEqual(glass["elements"], {"Li": 1.4, "S": 2.2, "P": 0.6})
        self.assertEqual(materials("(1-x)Li3PS4-xLiI glasses"), ["(1-x)Li3PS4-xLiI"])

    def test_sample_labels(self):
        names = Abbreviations.from_texts(["Li3YCl6 (LYC) and Na3Zr2Si2PO12 (NZSP) and NaLaCl4 (NLC-HT) were made."])
        self.assertEqual(materials("BM-LYC, LYC32 and NLC", names), ["Li3YCl6", "Li3YCl6", "NaLaCl4"])
        self.assertEqual(materials("XYZ-NZSP and NZSP-Mg0.1", names), [])

    def test_a_doped_sample_named_after_its_parent_is_its_own_material(self):
        # The dopants before the name make another sample: never the parent compound, whose values it would take.
        for text, formula in (("Ta-LLZO", "Ta-doped Li7La3Zr2O12"), ("the Ga–LLZO pellet", "Ga-doped Li7La3Zr2O12"),
                              ("Al,Ga-LLZO", "Al-Ga-doped Li7La3Zr2O12"), ("Ta-doped LLZO", "Ta-doped Li7La3Zr2O12"),
                              ("Ga and Al co-doped LLZO", "Ga-Al-doped Li7La3Zr2O12"),
                              ("Al-substituted Li7La3Zr2O12", "Al-doped Li7La3Zr2O12"),
                              ("Nb-doped LATP", "Nb-doped Li1.3Ti1.7Al0.3(PO4)3")):
            with self.subTest(text):
                found, = ChemistryEngine.find_materials(text)
                self.assertEqual(found["formula"], formula)
                self.assertTrue(found["dopants"])
                self.assertEqual(found["elements"], ChemistryEngine.find_materials(found["parent"])[0]["elements"])
        # A prefix that is no dopant: the compound itself, a polymorph, a way of making it, or no sample at all.
        self.assertEqual(materials("Ta-LLZTO and c-LLZO"), ["Li7La3Zr2O12"])  # Ta is in LLZTO already: a label
        self.assertEqual(materials("the Ta-doped Li6.4La3Zr1.4Ta0.6O12"), ["Li6.4La3Zr1.4Ta0.6O12"])
        self.assertEqual(materials("Li-LLZO, In-situ LLZO and PEO-LLZO"), ["Li7La3Zr2O12"])
        from LocalExtraction.scope import material_scope  # its own material is not flagged as under its parent
        sentence = "The Ta-doped LLZO shows 0.35 eV."
        self.assertEqual(material_scope("Ta-doped Li7La3Zr2O12", None, sentence, sentence.find("0.35")), "")
        self.assertEqual(materials("c-LLZO and LLZO-based films"), ["Li7La3Zr2O12", "Li7La3Zr2O12"])
        self.assertEqual(materials("LLZO@PEO and PEO@LLZO membranes"), [])  # one thing on or in another

    def test_the_family_a_composition_belongs_to(self):
        for formula, family in (("Li7La3Zr2O12", "garnet"), ("Li6.4La3Zr1.4Ta0.6O12", "garnet"), ("Li6PS5Cl", "argyrodite"),
                                ("Li5.5PS4.5Cl1.5", "argyrodite"), ("Li10GeP2S12", "LGPS-type"), ("Na3Zr2Si2PO12", "NASICON"),
                                ("Li1.3Al0.3Ti1.7(PO4)3", "NASICON"), ("Li0.33La0.557TiO3", "perovskite"), ("Li3OCl", "anti-perovskite"),
                                ("LiFePO4", "olivine"), ("LiMn2O4", "spinel"), ("Li4Ti5O12", "spinel"), ("LiCoO2", "layered"),
                                ("LiCl", "rock-salt"), ("Li2S", "anti-fluorite"),
                                ("Li3PS4", None), ("Li3YCl6", None), ("Li7P3S11", None), ("LiTa2PO8", None), ("Li3.25Ge0.25P0.75S4", None)):
            with self.subTest(formula=formula):
                material, = ChemistryEngine.find_materials(formula)
                self.assertEqual(ChemistryEngine.structure_family(material["elements"]), family)


class ContextTests(unittest.TestCase):
    """What a value's own sentence leaves out is looked for further away, and says where it was found."""

    def one(self, *paragraphs, prop="Activation_Energy", **kw):
        value, = extract(*paragraphs, **kw)["ELECTROCHEMICAL"][prop]
        return value

    def test_every_value_says_where_each_answer_comes_from(self):
        value = self.one("Li6PS5Cl has an activation energy of 0.30 eV.")
        self.assertEqual(sorted(value.basis), ["component", "ion", "kind", "origin", "pressure", "structure", "temperature"])
        self.assertEqual(value.mobile_ion, "Li+")
        self.assertTrue(value.basis["ion"].startswith("assumed (the only conducting-ion element of Li6PS5Cl"))
        self.assertEqual(value.structure, "argyrodite")
        self.assertEqual(value.basis["structure"], "known for this composition")
        self.assertEqual((value.pressure, value.basis["pressure"]), ("ambient pressure", "assumed (no pressure is stated)"))

    def test_an_activation_energy_is_left_no_open_answer(self):
        # A bare sentence says nothing of the method, the sample or the temperature: each answer is
        # the likeliest one, and says that it is assumed.
        value = self.one("Li6PS5Cl has an activation energy of 0.30 eV.")
        self.assertEqual((value.data_origin, value.transport_component, value.temperature, value.pressure),
                         ("experimental", "total", "room temperature", "ambient pressure"))
        for answer in ("origin", "component", "temperature", "pressure"):
            self.assertTrue(value.basis[answer].startswith("assumed ("), value.basis[answer])
        self.assertNotIn("not stated", " | ".join(value.basis.values()))
        # What it is called tells a computed barrier from a measured activation energy ...
        barrier = self.one("Li6PS5Cl has a migration barrier of 0.30 eV.")
        self.assertEqual((barrier.data_origin, barrier.transport_component, barrier.temperature), ("simulation", "bulk", "0 K"))
        self.assertIn("“migration barrier”", barrier.basis["origin"])
        # ... and a material no structure is known for is at least named by the kind of compound it is.
        unknown = self.one("Li7P3S11 has an activation energy of 0.18 eV.")
        self.assertEqual(unknown.structure, "thiophosphate")
        self.assertIn("kind of compound", unknown.basis["structure"])
        # Every other value of a material is completed the same way: a conductivity ...
        conductivity = self.one("Li6PS5Cl has an ionic conductivity of 3 mS/cm.", prop="Ionic_Conductivity")
        self.assertEqual((conductivity.data_origin, conductivity.transport_component, conductivity.temperature,
                          conductivity.pressure), ("experimental", "total", "room temperature", "ambient pressure"))
        self.assertNotIn("not stated", " | ".join(conductivity.basis.values()))
        # ... and a value no paper of the field measures without saying so is a computed one.
        gap, = extract("Li6PS5Cl has a band gap of 2.1 eV.")["ELECTRONIC"]["Band_Gap"]
        self.assertEqual((gap.data_origin, gap.temperature, gap.pressure), ("simulation", "0 K", "ambient pressure"))
        self.assertTrue(gap.basis["origin"].startswith("assumed (a band gap"), gap.basis["origin"])

    def test_a_barrier_is_a_static_value_unless_its_own_sentence_speaks_of_dynamics(self):
        computational = COMPUTATIONAL.replace(" at 600, 800 and 1000 K", "")  # a paper that gives no range for its runs
        barrier = self.one(computational, "The energy barriers are calculated with the adiabatic trajectory method. "
                                          "The energy barrier along the c axis is 0.6 eV for Li6PS5Cl.")
        self.assertEqual(barrier.temperature, "0 K")
        fitted = self.one(computational, "The energy barrier from the Arrhenius fit of the AIMD diffusivities is 0.6 eV for Li6PS5Cl.")
        self.assertEqual(fitted.temperature, "600-1200 K")
        self.assertTrue(fitted.basis["temperature"].startswith("assumed (the usual range of molecular-dynamics"))

    def test_what_the_paper_says_is_not_replaced_by_an_assumption(self):
        value = self.one(COMPUTATIONAL, "For Li6PS5Cl an activation energy of 0.30 eV is obtained.")
        self.assertEqual((value.data_origin, value.temperature), ("simulation", "600-1000 K"))
        self.assertTrue(value.basis["origin"].startswith("paper ("))
        self.assertTrue(value.basis["temperature"].startswith("paper ("))

    def test_what_the_sentence_states_comes_first(self):
        value = self.one(COMPUTATIONAL, "The impedance of cubic Li6PS5Cl pellets gives an activation energy of 0.30 eV between 300 and 400 K.")
        self.assertEqual((value.data_origin, value.temperature), ("experimental", "300-400 K"))
        self.assertTrue(value.basis["origin"].startswith("stated"))
        self.assertEqual(value.basis["temperature"], "stated")

    def test_a_computational_paper(self):
        value = self.one(COMPUTATIONAL, "For Li6PS5Cl an activation energy of 0.30 eV is obtained.")
        self.assertEqual((value.data_origin, value.transport_component, value.temperature), ("simulation", "bulk", "600-1000 K"))
        self.assertTrue(value.basis["origin"].startswith("paper"))
        self.assertTrue(value.basis["temperature"].startswith("paper"))
        self.assertEqual(value.basis["component"], "assumed (simulated in a bulk cell)")

    def test_an_experimental_paper(self):
        value = self.one(EXPERIMENTAL, "For Li6PS5Cl an activation energy of 0.30 eV is obtained.")
        self.assertEqual((value.data_origin, value.transport_component, value.temperature), ("experimental", "total", "298.1-373.1 K"))

    def test_a_barrier_in_an_experimental_paper_is_not_called_measured(self):
        value = self.one(EXPERIMENTAL, "For Li6PS5Cl an effective migration barrier of 0.75 eV is obtained.")
        self.assertEqual(value.data_origin, "simulation")
        self.assertTrue(value.basis["origin"].startswith("assumed ("))  # not "paper": the paper measures

    def test_a_static_barrier_has_no_temperature(self):
        value = self.one(COMPUTATIONAL, "NEB calculations give a migration barrier of 0.25 eV for Li6PS5Cl.")
        self.assertEqual((value.temperature, value.basis["temperature"]), ("0 K", "assumed (a static calculation: no thermal motion)"))

    def test_what_the_paper_says_of_itself_is_not_said_of_a_quoted_value(self):
        value = self.one(COMPUTATIONAL, "Kamaya et al. reported an activation energy of 0.25 eV for Li10GeP2S12 [5].")
        # Neither "simulation" nor the range of this paper's own runs: what is assumed of a quoted value.
        self.assertEqual((value.attribution, value.data_origin, value.temperature), ("cited", "experimental", "room temperature"))
        self.assertTrue(value.basis["origin"].startswith("assumed (") and value.basis["temperature"].startswith("assumed ("))
        own = self.one(COMPUTATIONAL, "For Li6PS5Cl an activation energy of 0.30 eV is obtained.")
        self.assertEqual(own.attribution, "this work")

    def test_a_quoted_conductivity_is_a_measured_one(self):
        value = self.one(COMPUTATIONAL, "Li10GeP2S12 exhibits an ionic conductivity of 12 mS/cm [5].", prop="Ionic_Conductivity")
        self.assertEqual(value.data_origin, "experimental")
        self.assertTrue(value.basis["origin"].startswith("assumed"))

    def test_a_grain_boundary_value_is_not_made_a_bulk_one(self):
        value = self.one(COMPUTATIONAL, "At the grain boundary of Li6PS5Cl the barrier obtained is 0.45 eV.")
        self.assertNotEqual(value.transport_component, "bulk")

    def test_components_named_together_go_to_their_values_in_order(self):
        results = extract("The impedance diagram of the LiTa2PO8 sample consists of two semicircles, corresponding to the bulk "
                          "and grain boundary responses. The total and bulk conductivities of the LiTa2PO8 sample are "
                          "3.9 × 10−4 S cm−1 and 2.5 × 10−3 S cm−1, respectively.")
        self.assertEqual([(f.normalized_value, f.transport_component) for f in results["ELECTROCHEMICAL"]["Ionic_Conductivity"]],
                         [("0.00039 S/cm", "total"), ("0.0025 S/cm", "bulk")])
        results = extract("The bulk and grain-boundary activation energies of Li7La3Zr2O12 are 0.30 and 0.45 eV, respectively.")
        self.assertEqual([(f.normalized_value, f.transport_component) for f in results["ELECTROCHEMICAL"]["Activation_Energy"]],
                         [("0.3 eV", "bulk"), ("0.45 eV", "grain_boundary")])
        # A sentence nearby that names two components says nothing about which one a value is.
        value = self.one("The spectrum shows two semicircles, corresponding to the bulk and grain boundary responses. "
                         "The conductivity of Li7La3Zr2O12 is 1.2 × 10−3 S cm−1.", prop="Ionic_Conductivity")
        self.assertNotIn(value.transport_component, ("bulk", "grain_boundary"))

    def test_the_temperature_of_another_quantity_is_not_the_activation_energys(self):
        value = self.one("Li6PS5CN exhibits an activation barrier of 471 ± 25 meV and a room-temperature ionic conductivity of 6(2)")
        self.assertNotEqual(value.basis["temperature"], "stated")  # the sentence states none for the barrier
        value = self.one("Li6PS5Cl shows an activation energy of 0.30 eV at room temperature.")
        self.assertEqual((value.temperature, value.basis["temperature"]), ("room temperature", "stated"))

    def test_a_value_quoted_for_one_form_keeps_to_it(self):
        value = self.one("Glassy Li3PS4 was studied. The glassy Li3PS4 is soft. In glassy Li3PS4 ions move fast.",
                         "The room-temperature conductivity of γ-Li3PS4 is 3 × 10−7 S/cm.", prop="Ionic_Conductivity")
        self.assertEqual(value.structure, "γ-phase")

    def test_a_review_quotes_everything(self):
        value = self.one(EXPERIMENTAL, "Li6PS5Cl has an activation energy of 0.30 eV.", title="Recent progress in sulfide electrolytes")
        self.assertEqual(value.attribution, "cited")
        self.assertTrue(value.basis["origin"].startswith("assumed ("))  # not what this paper does: it is a review

    def test_is_quoted(self):
        self.assertTrue(is_quoted("e.g., LLZO (σRT = 1 mS/cm, Ea = 0.3 eV)3, and others"))
        self.assertTrue(is_quoted("NMR studies determined the activation energy of Li3PS4 to be 0.40 eV40."))
        self.assertTrue(is_quoted("Their study proposed that vacancies reduce the activation energy to 0.11 eV"))
        self.assertFalse(is_quoted("LATP with (PO4)3 units shows 0.3 eV."))
        text = "The measured activation energy (0.41 eV) is in good agreement with published values from Asano et al.10"
        self.assertFalse(is_quoted(text, "", (31, 38)))
        # The citation that closes a comparison is the comparison's.
        text = ("Li4Hf2Si3O12 shows an ionic conductivity of 14.09 mS cm−1, which is comparable to the highest values "
                "reported for SSEs, such as LiNbOCl4 and LiTaOCl4.[57]")
        self.assertFalse(is_quoted(text, "", (44, 57)))
        self.assertTrue(is_quoted("The conductivity of Li10GeP2S12 is 12 mS cm−1.[57]", "", (35, 45)))

    def test_the_kind_of_paper(self):
        self.assertEqual(Study([{"text": COMPUTATIONAL, "type": "Text", "section": "Methods"}]).kind, "simulation")
        self.assertEqual(Study([{"text": EXPERIMENTAL, "type": "Text", "section": "Methods"}]).kind, "experimental")
        self.assertEqual(Study([{"text": COMPUTATIONAL + " " + EXPERIMENTAL, "type": "Text", "section": "Methods"}]).kind, "both")

    def test_a_range_that_starts_at_room_temperature(self):
        self.assertEqual(temperature_range("The impedance was measured from room temperature to 100 °C."), "298-373.1 K")


class UnreadableFileTests(unittest.TestCase):
    def test_a_file_that_is_not_a_pdf_says_so_in_words(self):
        from LocalExtraction.parser import DocumentParser
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "empty.pdf")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a pdf at all")
        with self.assertRaisesRegex(ValueError, "it does not open as a PDF"):
            DocumentParser(path).parse()


class TextRepairTests(unittest.TestCase):
    def test_words_split_by_a_line_break(self):
        texts = ["The activation energy of the ion depends on temperature in Li and Na conducting solids.",
                 "The activa- tion barrier and the temperature- dependent ion- conducting Li- ion data; Li- and Na-ion cells."]
        self.assertEqual(repair_hyphenation(texts)[1],
                         "The activation barrier and the temperature-dependent ion-conducting Li-ion data; Li- and Na-ion cells.")

    def test_a_split_word_no_longer_hides_a_value(self):
        blocks = [{"text": "The activation energy matters.", "type": "Text"}, {"text": "LiBiO2 has an activa- tion barrier of 0.28 eV.", "type": "Text"}]
        repair_blocks(blocks)
        self.assertEqual(found(blocks[1]["text"]), [("Activation_Energy", "0.28 eV", "activation barrier")])

    def test_glyphs_a_font_lost(self):
        self.assertEqual(normalize_scientific_text("1.6 9 10–3 S cm-1, P¯3m1 and tetragonal ­Li7La3Zr2O12"),
                         "1.6 × 10–3 S cm-1, P-3m1 and tetragonal Li7La3Zr2O12")

    def test_a_multiplication_sign_a_font_lost(self):
        # as a control character (the minus too), or as nothing at all: the value is 1.15 × 10−4, not 10−4
        self.assertEqual(normalize_scientific_text("of 1.15 \x03 10\x024 S cm\x021"), "of 1.15 × 10−4 S cm−1")
        self.assertEqual(normalize_scientific_text("of 7.0  10−9 S cm−1 and D = 3 10−12 cm2 s−1"),
                         "of 7.0 × 10−9 S cm−1 and D = 3 × 10−12 cm2 s−1")
        self.assertEqual(found(normalize_scientific_text("The conductivity of Li3InCl6 is 1.15 \x03 10\x024 S cm\x021.")),
                         [("Ionic_Conductivity", "0.000115 S/cm", "conductivity")])
        # a formula before a power of ten is no product, nor a number without a unit after it
        for text in ("Li7La3Zr2O12 10−4 S cm−1", "between 25 10−3 and 40"):
            self.assertEqual(normalize_scientific_text(text), text)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def paper(self, *paragraphs):
        ranked = Ranker.process(extract(*paragraphs))
        return PaperData(
            filename="paper.pdf", metadata={"title": ExtractedField.empty()}, materials=ranked["materials"],
            electrochemical=ranked["ELECTROCHEMICAL"], thermodynamic=ranked["THERMODYNAMIC"], mechanical=ranked["MECHANICAL"],
            structural=ranked["STRUCTURAL"], electronic=ranked["ELECTRONIC"], thermal=ranked["THERMAL"],
            spectroscopy=ranked["SPECTROSCOPY"], dft=ranked["DFT"], aimd=ranked["AIMD"], ml=ranked["ML"],
            synthesis=ranked["SYNTHESIS"], characterization=ranked["CHARACTERIZATION"], battery_perf={}, interfaces={},
            relations=ranked["relations"], workflow=ranked["workflow"], figures=ranked["figures"], tables=ranked["tables"],
            equations=ranked["equations"], references=[])

    def table(self, name):
        return pd.read_csv(os.path.join(self.folder, f"{name}.csv"), dtype=str, keep_default_na=False)

    @unittest.skipIf(__import__("LocalExtraction.extractor", fromlist=["NLP_MODEL"]).NLP_MODEL.startswith(
        "no language model"), "the expected values are those read with a spaCy language model (python -m spacy download en_core_web_sm); without one, sentences are split by punctuation only and the extraction warns that it reads less")
    def test_each_table_holds_what_its_columns_apply_to(self):
        paper = self.paper(COMPUTATIONAL, "Li6PS5Cl has a migration barrier of 0.30 eV and an ionic conductivity of 3 mS/cm (Fig. 2b). "
                                          "A band gap of 4 eV was computed.")
        StrictExporter(self.folder).export([paper])
        energies, properties, methods, unassigned = (self.table(n) for n in ("activation_energy", "properties", "methods", "unassigned_values"))
        row = energies.iloc[0]
        self.assertEqual((row.material_formula, row.activation_energy_eV, row.reported_as), ("Li6PS5Cl", "0.3", "migration barrier"))
        self.assertEqual(row.source, "Text, citing Figure 2b")
        self.assertIn("origin: ", row.basis)
        self.assertEqual(set(properties.property_name), {"Activation_Energy", "Ionic_Conductivity"})
        self.assertTrue((properties.material_formula == "Li6PS5Cl").all())
        self.assertEqual(list(unassigned.property_name), ["Band_Gap"])  # no material could be established for it
        self.assertIn("Software", set(methods.property_name))
        # Nothing is left empty in the activation-energy table; a conductivity may lack its temperature.
        self.assertFalse(energies.isin(["NONE", ""]).any().any(), energies.to_dict("records"))
        self.assertFalse(properties.drop(columns="temperature").isin(["NONE", ""]).any().any())

    def test_every_value_says_which_part_of_the_paper_it_was_read_from_and_the_page(self):
        blocks = [{"text": "Li6PS5Cl has an activation energy of 0.30 eV.", "page": 4, "section": "Results", "type": "Text"},
                  {"text": "Figure 3. Arrhenius plot of Li6PS5Br, with an activation energy of 0.35 eV.", "page": 5,
                   "section": "Results", "type": "Caption", "ref_kind": "Figure", "ref_number": "3"},
                  {"type": "Table", "page": 6, "section": "Results", "caption": "Table 2. Activation energies.",
                   "table_number": "2", "headers": ["Material", "Ea (eV)"], "material_column": "Material",
                   "rows": [{"Material": "Li7La3Zr2O12", "Ea (eV)": "0.41"}], "text": "Material Ea (eV) Li7La3Zr2O12 0.41"}]
        ranked = Ranker.process(ExtractorEngine.extract_all(blocks))
        paper = self.paper("x")
        paper.materials, paper.electrochemical, paper.relations = ranked["materials"], ranked["ELECTROCHEMICAL"], ranked["relations"]
        StrictExporter(self.folder).export([paper])
        energies = self.table("activation_energy")
        self.assertEqual(sorted(zip(energies.material_formula, energies.extracted_from, energies.page)),
                         [("Li6PS5Br", "Figure", "5"), ("Li6PS5Cl", "Text", "4"), ("Li7La3Zr2O12", "Table", "6")])
        # ... right after the value itself, in every table of values.
        # The article's title follows its id in every table.
        self.assertEqual(list(energies.columns[:7]),
                         ["paper_id", "title", "material_formula", "activation_energy_eV", "reported_as", "extracted_from",
                          "page"])
        properties = self.table("properties")
        at = list(properties.columns).index("unit")
        self.assertEqual(list(properties.columns[at + 1:at + 3]), ["extracted_from", "page"])
        self.assertFalse(energies.isin(["NONE", "", "unspecified", "n/a"]).any().any(), energies.to_dict("records"))
        # How many of a row's answers are defaults is a column of its own.
        self.assertTrue(energies.n_assumed.astype(int).between(0, 6).all())
        # structure, temperature, pressure, component and the ion (from the composition) are defaults here
        self.assertEqual(int(energies.n_assumed[energies.material_formula == "Li6PS5Cl"].iloc[0]), 5)

    def test_adding_papers_keeps_what_is_already_there_as_written(self):
        first = self.paper("Li6PS5Cl has an electronic conductivity of 4 × 10−9 S/cm.")
        second = self.paper("Li3PS4 has an ionic conductivity of 3 mS/cm.")
        second.filename = "second.pdf"
        StrictExporter(self.folder).export([first])
        before = self.table("properties")
        StrictExporter(self.folder).export([second])  # merged into the files of the first
        after = self.table("properties")
        # The transport component is a column of the tables of the transport quantities only: it
        # applies to every row there, and every row of properties.csv has every column answered.
        self.assertNotIn("transport_component", before.columns)
        self.assertEqual(list(self.table("electronic_conductivity").transport_component), ["total"])
        self.assertEqual(after.iloc[:1].to_dict("records"), before.to_dict("records"))
        self.assertEqual(len(after), 2)
        for name in ("properties", "electronic_conductivity", "ionic_conductivity", "materials"):
            table = self.table(name)
            self.assertFalse(table.isin(["NONE", "", "unspecified", "n/a", "not stated"]).any().any(), (name, table.to_dict("records")))
        sheet = pd.read_excel(os.path.join(self.folder, "database.xlsx"), sheet_name="ionic_conductivity", dtype=str,
                              keep_default_na=False)
        self.assertEqual(list(sheet.ionic_conductivity_S_cm), ["0.003"])
        # A table with no row yet is written with its header.
        self.assertEqual(list(self.table("methods").columns)[:3], ["paper_id", "title", "category"])

    def test_a_cell_too_long_for_a_workbook_is_cut_there_and_kept_in_the_csv(self):
        StrictExporter(self.folder).export([self.paper("Li6PS5Cl has an ionic conductivity of 3 mS/cm.")], excel=False)
        long_caption = "Table 1. " + "conductivities of the samples " * 1500  # 45 000 characters
        pd.DataFrame([{"paper_id": "paper.pdf", "caption": long_caption}]).to_csv(
            os.path.join(self.folder, "tables.csv"), index=False, encoding="utf-8-sig")
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # openpyxl would warn that it truncates the cell
            StrictExporter(self.folder).export_excel()
        sheet = pd.read_excel(os.path.join(self.folder, "database.xlsx"), sheet_name="tables", dtype=str, keep_default_na=False)
        self.assertEqual((len(sheet.caption[0]), sheet.caption[0][-1]), (32767, "…"))
        self.assertEqual(self.table("tables").caption[0], long_caption)

    def test_an_older_database_is_not_mixed_with_the_new_columns(self):
        self.assertFalse(StrictExporter.is_outdated(self.folder))
        pd.DataFrame([{"paper_id": "a.pdf", "filename": "a.pdf", "title": "An older one"}]).to_csv(
            os.path.join(self.folder, "papers.csv"), index=False)  # no metadata_basis: an earlier version
        self.assertTrue(StrictExporter.is_outdated(self.folder))
        kept = StrictExporter.archive(self.folder)
        self.assertTrue(os.path.exists(os.path.join(kept, "papers.csv")))
        self.assertFalse(StrictExporter.is_outdated(self.folder))
        StrictExporter(self.folder).export([self.paper("Li6PS5Cl has a migration barrier of 0.30 eV.")])
        self.assertFalse(StrictExporter.is_outdated(self.folder))



class PipelineTests(unittest.TestCase):
    """A PDF through the whole of Project 1: every table of the database it writes is complete."""

    def test_no_table_has_an_open_cell(self):
        import pymupdf
        from LocalExtraction.cli import run_extraction
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        pdfs, out = os.path.join(folder, "papers"), os.path.join(folder, "out")
        os.makedirs(pdfs)
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), (
            "Fast lithium conduction in argyrodite electrolytes\n\n"
            "Abstract. We synthesized Li6PS5Cl by ball milling. Li6PS5Cl has an activation energy of 0.30 eV "
            # (ASCII only: the built-in font of a PDF made here has no "−" or "σ")
            "and an ionic conductivity of 3 mS/cm at 25 °C. Its electronic conductivity is 4 x 10-9 S/cm. "
            "The lithium diffusion coefficient of Li6PS5Cl is 2 x 10-8 cm2/s. A band gap of 2.1 eV was computed "
            "for Li6PS5Cl. The conductivity follows sT = A exp(-Ea/kBT). x = 0.\n"), fontsize=10)
        doc.save(os.path.join(pdfs, "argyrodite.pdf"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run_extraction(pdfs, out, max_workers=1, lookup=False), 0)
        open_cells = {"NONE", "", "unspecified", "n/a", "unknown", "not stated", "unclassified", "Unclassified"}
        for name in os.listdir(out):
            if not name.endswith(".csv"):
                continue
            table = pd.read_csv(os.path.join(out, name), dtype=str, keep_default_na=False)
            self.assertFalse(table.isin(open_cells).any().any(), (name, table.to_dict("records")))
        papers = pd.read_csv(os.path.join(out, "papers.csv"), dtype=str, keep_default_na=False)
        self.assertEqual((papers.source_service[0], papers.metadata_basis[0]),
                         ("a file of this computer", "the PDF itself (OpenAlex was not asked)"))
        for name in ("activation_energy", "ionic_conductivity", "electronic_conductivity", "diffusion_coefficient"):
            self.assertEqual(len(pd.read_csv(os.path.join(out, f"{name}.csv"))), 1, name)
        equations = pd.read_csv(os.path.join(out, "equations.csv"), dtype=str, keep_default_na=False)
        self.assertNotIn("x = 0", " ".join(equations.equation_text))  # a value, not an equation


class EnergyKindTests(unittest.TestCase):
    """An "activation energy" says what kind of energy it is (energy.py), and why."""

    def kind(self, *paragraphs):
        return {float(f.normalized_value.split()[0]): (f.energy_kind, f.basis.get("kind", ""))
                for f in extract(*paragraphs)["ELECTROCHEMICAL"]["Activation_Energy"]}

    def test_each_kind_from_the_wording(self):
        for sentence, value, kind in (
                ("The activation energy of Li6PS5Cl obtained from the Arrhenius plot of the impedance data is 0.29 eV.",
                 "0.29 eV", "arrhenius"),
                ("NEB calculations give a migration barrier of 0.31 eV for Li7P3S11.", "0.31 eV", "migration_barrier"),
                ("BVSE calculations give a migration barrier of 0.28 eV for Li3YCl6.", "0.28 eV", "bvse"),
                ("NMR spin-lattice relaxation rates of Li7La3Zr2O12 give an activation energy of 0.18 eV.", "0.18 eV", "local_hop"),
                ("A VTF fit of the PEO-LiTFSI conductivity gives a pseudo-activation energy of 0.08 eV.", "0.08 eV", "vtf"),
                ("AIMD simulations of Li10GeP2S12 give an activation energy of 0.21 eV.", "0.21 eV", "arrhenius"),
                ("The activation energy of the anion reorientation in LiCB11H12 is 0.40 eV.", "0.40 eV", "rotation")):
            with self.subTest(sentence=sentence):
                found, why = self.kind(sentence)[float(value.split()[0])]
                self.assertEqual(found, kind, why)
                self.assertTrue(why.startswith("stated ("), why)

    def test_each_value_of_a_sentence_reads_its_own_clause(self):
        found = self.kind("Long-range transport in Li6.5La3Zr1.5Ta0.5O12 is described by an activation energy of 0.45 eV "
                          "from impedance, whereas localized ion dynamics seen by NMR have a barrier of 0.22 eV.")
        self.assertEqual(found[0.45][0], "arrhenius")
        self.assertEqual(found[0.22][0], "local_hop")
        # ... and a clause that names no method takes nothing from the other side of a "whereas".
        found = self.kind(EXPERIMENTAL, "Long-range transport in Li6.5La3Zr1.5Ta0.5O12 is consistently described by activation "
                                        "energies of 0.41 eV, whereas localized ion dynamics are associated with much lower "
                                        "barriers of approximately 0.22 eV.")
        self.assertEqual(found[0.41][0], "arrhenius")
        self.assertEqual(found[0.22][0], "local_hop")

    def test_a_kind_no_wording_names_is_assumed_and_says_so(self):
        measured, why = self.kind(EXPERIMENTAL, "The activation energy of Li6PS5Cl is 0.30 eV.")[0.3]
        self.assertEqual(measured, "arrhenius")
        self.assertTrue(why.startswith("assumed ("), why)
        computed, why = self.kind(COMPUTATIONAL, "The migration barrier of Li6PS5Cl is 0.25 eV.")[0.25]
        self.assertEqual(computed, "migration_barrier")

    def test_the_kind_is_a_column_of_the_activation_energy_table_only(self):
        from LocalExtraction.exporter import COLUMNS
        self.assertIn("energy_kind", COLUMNS["activation_energy"])
        self.assertEqual(COLUMNS["activation_energy"].index("energy_kind"), COLUMNS["activation_energy"].index("needs_check") + 1)
        self.assertNotIn("energy_kind", COLUMNS["ionic_conductivity"])


class ScopeTests(unittest.TestCase):
    """A transport value of something that is no candidate electrolyte is kept, but flagged (scope.py)."""

    def test_what_is_no_candidate_electrolyte(self):
        from LocalExtraction.scope import material_scope
        for formula in ("LiF", "Li2CO3", "CaO", "LiCoO2", "Li0.81CoO2", "LiFePO4", "Li3V2(PO4)3", "NaFeO2", "Li4Ti5O12",
                        "Li15Si4", "H2O"):
            with self.subTest(formula=formula):
                self.assertNotEqual(material_scope(formula), "")
        for formula in ("Li7La3Zr2O12", "Li6.25Fe0.25La3Zr2O12", "Li6PS5Cl", "Li3InCl6", "Li1.3Al0.3Ti1.7(PO4)3",
                        "Na3Zr2Si2PO12", "Li3N", "LiI", "LiBH4", "Cu2Se", "LiNbCl6", "Li10GeP2S12"):
            with self.subTest(formula=formula):
                self.assertEqual(material_scope(formula), "")

    def test_a_composite_in_the_value_s_own_clause(self):
        from LocalExtraction.scope import material_scope
        sentence = ("As the NZSP content increases in the composites, the activation energy rises to 0.29 eV for the "
                    "70–30 sample and 0.27 eV for the 50–50 sample.")
        self.assertIn("composite", material_scope("Na3Zr2Si2PO12", None, sentence, sentence.find("0.27")))
        both = "The activation energies are 0.53 eV for PEO-LiTFSI and 0.28 eV for LGPS."
        self.assertEqual(material_scope("Li10GeP2S12", None, both, both.find("0.28")), "")
        glued = "The activation energies are as low as 0.19 eV for CaI2@TB-MOF."
        self.assertIn("composite", material_scope("CaI2", None, glued, glued.find("0.19")))

    def test_a_doped_sample_stored_under_its_parent_formula(self):
        from LocalExtraction.scope import material_scope
        doped = "yielding 0.20 and 0.17 eV for the Al-doped LLZO and Al─N co-doped LLZO, respectively."
        self.assertEqual(material_scope("Li7La3Zr2O12", None, doped, doped.find("0.17")),
                         "an Al-doped sample stored under a formula without Al")
        for formula, sentence in (("Li6.4La3Zr1.4Ta0.6O12", "Ta-doped LLZO (Li6.4La3Zr1.4Ta0.6O12) shows 0.35 eV."),
                                  ("Li7La3Zr2O12", "Ta-doped LLZO shows 0.35 eV, whereas undoped Li7La3Zr2O12 shows 0.5 eV.")):
            with self.subTest(sentence=sentence):
                self.assertEqual(material_scope(formula, None, sentence, sentence.rfind("0.")), "")

    def test_lithiated_carbon_and_a_single_value_composite(self):
        from LocalExtraction.scope import material_scope
        self.assertIn("carbon", material_scope("LiC6"))
        single = "The membrane containing 26 wt% and milled 2 h LATP exhibits the lowest activation energy (0.138 eV)."
        self.assertIn("composite", material_scope("Li1.3Ti1.7Al0.3(PO4)3", None, single, single.find("0.138")))

    def test_a_cathode_or_an_anode_database_keeps_its_own_materials(self):
        from LocalExtraction.scope import material_scope
        for formula, cathode, anode in (("LiCoO2", "", ""), ("LiFePO4", "", ""), ("Na3V2(PO4)3", "", ""),
                                        ("Li4Ti5O12", "", ""), ("LiC6", "anode", ""), ("Li15Si4", "anode", ""),
                                        ("Li7La3Zr2O12", "solid electrolyte", "solid electrolyte"),
                                        ("Li6PS5Cl", "solid electrolyte", "solid electrolyte"),
                                        ("LiF", "interphase", "interphase")):
            with self.subTest(formula=formula):
                for domain, expected in (("cathode", cathode), ("anode", anode)):
                    found = material_scope(formula, domain=domain)
                    self.assertEqual(found, "") if not expected else self.assertIn(expected, found)
        self.assertIn("electrode", material_scope("LiCoO2"))  # the electrolyte database, by default
        with self.assertRaises(ValueError):
            material_scope("LiCoO2", domain="catalyst")

    def test_the_flag_reaches_the_table(self):
        from LocalExtraction.species import plausibility
        self.assertTrue(plausibility("Activation_Energy", "0.22 eV", "Li+", "activation energy",
                                     "an electrode material (a transition-metal compound), not an electrolyte")
                        .startswith("check: it is an electrode material"))


class NotAResultTests(unittest.TestCase):
    """Numbers that stand next to an activation energy without being one."""

    def ea(self, *paragraphs):
        return [f.normalized_value for f in extract(*paragraphs)["ELECTROCHEMICAL"]["Activation_Energy"]]

    def test_a_spread_a_discrepancy_and_a_prior(self):
        self.assertNotIn("0.69 eV", self.ea("Li3N shows a broad barrier distribution, with μ ≈ 0.93 eV and σ ≈ 0.69 eV."))
        self.assertEqual(self.ea("CI-NEB gives an Ea of 0.7 eV for γ-Li3PS4, compared to the experimental value of 0.22 eV, "
                                 "showing a discrepancy of 0.48 eV."), ["0.7 eV", "0.22 eV"])
        self.assertEqual(self.ea("Parameter priors were uniform: p(Ea) ∼ U(0, 0.5 eV) for Li7La3Zr2O12."), [])

    def test_energies_of_interfaces_and_reactions_are_not_of_migration(self):
        for sentence, what in (
                ("The activation energy for interfacial Li+ transfer between Li1.3Al0.3Ti1.7(PO4)3 and the gel was 0.40 eV.",
                 "an interfacial charge transfer"),
                ("NEB calculations reveal 0.4 eV migration barriers for Li-ion transfer through the interface of Li3AlN2.",
                 "an interfacial charge transfer"),
                ("In contrast, the PEO-LiTFSI|Li1.5Al0.5Ti1.5(PO4)3 (LATP) interface exhibited an activation energy of 0.67 eV.",
                 "an interfacial charge transfer"),
                ("The nucleation activation energy of Gd2Ti2O7 is 0.34 eV.", "a reaction"),
                ("The activation energy of crystallization of the Li3PS4 glass is 1.3 eV.", "a reaction")):
            with self.subTest(sentence=sentence):
                value, = extract(sentence)["ELECTROCHEMICAL"]["Activation_Energy"]
                self.assertTrue(value.reported_as.endswith(f"(of {what})"), value.reported_as)


    def test_a_reaction_word_elsewhere_in_the_sentence_says_nothing_of_the_energy(self):
        value, = extract("Mg3(BH4)4(NH2)2 has a decomposition temperature above 190 °C and a low activation energy "
                         "(0.84 eV).")["ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual(value.reported_as, "activation energy")


class FormulaFragmentTests(unittest.TestCase):
    def test_a_formula_split_by_a_space(self):
        for text in ("the Li1.3 Ga0.3Ti1.7(PO4)3 electrolyte", "the Li1.3Ga0.3Ti1.7 (PO4)3 electrolyte"):
            with self.subTest(text=text):
                self.assertEqual(materials(text), ["Li1.3Ti1.7Ga0.3(PO4)3"])
        self.assertEqual(materials("a Li2S P2S5 glass"), ["Li2S", "P2S5"])

    def test_more_mobile_ions_and_measurements(self):
        from LocalExtraction.species import mobile_species
        self.assertEqual(mobile_species("Activation_Energy", "transport dominated by the motion of the Cs+ cations",
                                        "CsYP2O7")[0], "Cs+")
        value, = extract("The slope of the SLR rates of Li6PS5Cl gives an activation energy of 0.16 eV.")[
            "ELECTROCHEMICAL"]["Activation_Energy"]
        self.assertEqual(value.data_origin, "experimental")

    def test_square_brackets_and_placeholders(self):
        self.assertEqual(materials("for Li6.5[P0.25Si0.25Ge0.25Sb0.25]S5I"), ["Li6.5Si0.25Ge0.25Sb0.25P0.25S5I"])
        self.assertEqual(materials("Li1.5[Al0.5Ge1.5](PO4)3"), ["Li1.5Al0.5Ge1.5(PO4)3"])
        self.assertEqual(materials("Li diffusion in LiM(SeO3)2 (M = Al, Ga, In)"), [])
        self.assertEqual(materials("the [BH4]− anion of Li3Y(NH2)6"), ["Li3YH12N6"])

    def test_more_comparisons(self):
        from LocalExtraction.context import is_compared_with
        for sentence in ("The Arrhenius fit yields 0.184 eV, lower than typical values reported for undoped LLZO.",
                         "It compares favourably with mature systems such as the LLZO garnet."):
            with self.subTest(sentence=sentence):
                self.assertTrue(is_compared_with(sentence, sentence.find("LLZO")))


class SampledMistakeTests(unittest.TestCase):
    """Mistakes found by checking a random sample of extracted activation energies against their sentences
    (November 2026): each sentence below is written after one of them."""

    def ea(self, *paragraphs, **kw):
        return {f.normalized_value: f for f in extract(*paragraphs, **kw)["ELECTROCHEMICAL"]["Activation_Energy"]}

    def test_a_measured_value_a_calculated_one_is_compared_with(self):
        found = self.ea("The calculated activation energy of 0.27 eV for Na3PS4 agrees well with the value of 0.28 eV "
                        "derived from impedance measurements [26].")
        self.assertEqual(found["0.27 eV"].data_origin, "simulation")
        self.assertEqual((found["0.28 eV"].data_origin, found["0.28 eV"].attribution), ("experimental", "cited"))

    def test_calculated_to_be_names_no_computation(self):
        found = self.ea("The Arrhenius plots of the Li6PS5Cl discs show similar slopes, with activation energies "
                        "calculated to be 0.29 eV.")
        self.assertEqual(found["0.29 eV"].data_origin, "experimental")
        computed = self.ea("The migration barrier of Li7P3S11 is calculated to be 0.31 eV by NEB.")
        self.assertEqual(computed["0.31 eV"].data_origin, "simulation")

    def test_a_value_of_previous_work_is_cited(self):
        for sentence in ("The diffusion barrier of glassy Li3PS4 was estimated as 0.25 eV in previous AIMD simulations.",
                         "These results agree with the previous predictions of Ea = 0.201 eV for vacancy-rich Li2S."):
            with self.subTest(sentence=sentence):
                value, = self.ea(sentence).values()
                self.assertEqual(value.attribution, "cited")

    def test_the_material_a_comparison_names_does_not_take_the_value_outside_it(self):
        found = self.ea("Li7P3S11 glass-ceramics were prepared. The activation energy was about 0.325 eV, a low value "
                        "compared with the result of Li10SnP2S12 (0.31 eV) reported by Bron [24].")
        self.assertNotEqual(found["0.325 eV"].material_formula, "Li10SnP2S12")
        self.assertEqual(found["0.31 eV"].material_formula, "Li10SnP2S12")

    def test_a_citation_after_a_value_closes_its_statement(self):
        # A table run into the text: each row is a material, its conductivity, its E_a and its source.
        found = self.ea("Li6.4La3Zr1.4Ta0.6O12 1.0 × 10−3 S cm−1, Ea ~ 0.35 eV [17] "
                        "Li6.5La3Zr1.75Te0.25O12 1.02 × 10−3 S cm−1, Ea ~ 0.38 eV [18]")
        self.assertEqual(found["0.35 eV"].material_formula, "Li6.4La3Zr1.4Ta0.6O12")
        self.assertEqual(found["0.38 eV"].material_formula, "Li6.5La3Zr1.75Te0.25O12")

    def test_a_vacancy_is_no_formula(self):
        self.assertEqual(materials("a Frenkel defect with decreasing Lii–VLi distance"), [])
        self.assertEqual(materials("the VNa and VLi sites"), [])
        self.assertEqual(materials("VO2 and LiV3O8 cathodes"), ["VO2", "LiV3O8"])

    def test_an_energy_of_something_else_than_ion_migration_is_flagged(self):
        from LocalExtraction.species import plausibility
        for sentence, what in (
                ("Between 60 and 80 °C, the activation energy of the exchange current density at the Li/LLZO interface "
                 "is 0.70 eV.", "an interfacial charge transfer"),
                ("The charge-transfer activation energy of the Li/Li6PS5Cl interface is 0.62 eV.", "an interfacial charge transfer"),
                ("The activation energy of the anion reorientation in LiCB11H12 is 0.40 eV.", "a rotation")):
            with self.subTest(sentence=sentence):
                value, = self.ea(sentence).values()
                self.assertTrue(value.reported_as.endswith(f"(of {what})"), value.reported_as)
                self.assertTrue(plausibility("Activation_Energy", value.normalized_value, "Li+", value.reported_as)
                                .startswith("check: it is the activation energy of"))
        value, = self.ea("Li6PS5Cl has an activation energy of 0.30 eV, and its interface with Li is stable.").values()
        self.assertEqual(plausibility("Activation_Energy", value.normalized_value, "Li+", value.reported_as), "in range")

    def test_a_computed_barrier_at_a_surface(self):
        value, = self.ea(COMPUTATIONAL, "For intraoctahedral migration at the surface, Li3OCl exhibits a barrier of "
                                        "0.301 eV.").values()
        self.assertEqual(value.transport_component, "surface")
        bulk, = self.ea(COMPUTATIONAL, "In the bulk of Li3OCl the barrier is 0.37 eV, lower than at the surface.").values()
        self.assertNotEqual(bulk.transport_component, "surface")


if __name__ == "__main__":
    unittest.main()
