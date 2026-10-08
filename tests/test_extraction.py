# tests/test_extraction.py
"""Tests of what is extracted from a paper's text: which numbers are values of which quantity,
which material each is for, and where the rest of its context comes from.

They run on sentences, not PDFs, so they are instant and need no file. Run them with:
    python -m unittest discover -s tests -v   (or: pytest tests)
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import quantities
from chemistry import Abbreviations, ChemistryEngine
from config import SchemaConfig
from context import temperature_range
from exporter import StrictExporter
from extractor import ExtractorEngine
from models import ExtractedField, PaperData
from normalizer import DataNormalizer, normalize_scientific_text, repair_hyphenation
from parser import repair_blocks
from ranking import Ranker
from study import Study, is_quoted

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
        from web.job import load_job
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
        self.assertEqual(materials("XYZ-NZSP and NZSP-Mg0.1 and Ta-LLZO", names), [])
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
        self.assertEqual(sorted(value.basis), ["component", "origin", "pressure", "structure", "temperature"])
        self.assertEqual(value.structure, "argyrodite")
        self.assertEqual(value.basis["structure"], "known for this composition")
        self.assertEqual((value.data_origin, value.basis["origin"]), ("unspecified", "not stated"))
        self.assertEqual((value.pressure, value.basis["pressure"]), ("ambient pressure", "assumed (no pressure is stated)"))

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
        self.assertEqual(value.data_origin, "unspecified")

    def test_a_static_barrier_has_no_temperature(self):
        value = self.one(COMPUTATIONAL, "NEB calculations give a migration barrier of 0.25 eV for Li6PS5Cl.")
        self.assertEqual((value.temperature, value.basis["temperature"]), ("0 K", "assumed (a static calculation: no thermal motion)"))

    def test_what_the_paper_says_of_itself_is_not_said_of_a_quoted_value(self):
        value = self.one(COMPUTATIONAL, "Kamaya et al. reported an activation energy of 0.25 eV for Li10GeP2S12 [5].")
        self.assertEqual((value.attribution, value.data_origin, value.temperature), ("cited", "unspecified", "NONE"))
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
        self.assertEqual(value.temperature, "NONE")
        value = self.one("Li6PS5Cl shows an activation energy of 0.30 eV at room temperature.")
        self.assertEqual((value.temperature, value.basis["temperature"]), ("room temperature", "stated"))

    def test_a_value_quoted_for_one_form_keeps_to_it(self):
        value = self.one("Glassy Li3PS4 was studied. The glassy Li3PS4 is soft. In glassy Li3PS4 ions move fast.",
                         "The room-temperature conductivity of γ-Li3PS4 is 3 × 10−7 S/cm.", prop="Ionic_Conductivity")
        self.assertEqual(value.structure, "γ-phase")

    def test_a_review_quotes_everything(self):
        value = self.one(EXPERIMENTAL, "Li6PS5Cl has an activation energy of 0.30 eV.", title="Recent progress in sulfide electrolytes")
        self.assertEqual((value.attribution, value.data_origin), ("cited", "unspecified"))

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

    def test_adding_papers_keeps_what_is_already_there_as_written(self):
        first = self.paper("Li6PS5Cl has an electronic conductivity of 4 × 10−9 S/cm.")
        second = self.paper("Li3PS4 has an ionic conductivity of 3 mS/cm.")
        second.filename = "second.pdf"
        StrictExporter(self.folder).export([first])
        before = self.table("properties")
        StrictExporter(self.folder).export([second])  # merged into the files of the first
        after = self.table("properties")
        self.assertEqual(list(before.transport_component), ["n/a"])  # does not apply to an electronic conductivity
        self.assertEqual(after.iloc[:1].to_dict("records"), before.to_dict("records"))
        self.assertEqual(len(after), 2)
        sheet = pd.read_excel(os.path.join(self.folder, "database.xlsx"), sheet_name="properties", dtype=str, keep_default_na=False)
        self.assertEqual(list(sheet.transport_component)[0], "n/a")

    def test_an_older_database_is_not_mixed_with_the_new_columns(self):
        self.assertFalse(StrictExporter.is_outdated(self.folder))
        pd.DataFrame([{"paper_id": "a.pdf", "property_name": "Migration_Barrier", "data_origin_evidence": "NONE"}]).to_csv(
            os.path.join(self.folder, "properties.csv"), index=False)
        self.assertTrue(StrictExporter.is_outdated(self.folder))
        kept = StrictExporter.archive(self.folder)
        self.assertTrue(os.path.exists(os.path.join(kept, "properties.csv")))
        self.assertFalse(StrictExporter.is_outdated(self.folder))
        StrictExporter(self.folder).export([self.paper("Li6PS5Cl has a migration barrier of 0.30 eV.")])
        self.assertFalse(StrictExporter.is_outdated(self.folder))


if __name__ == "__main__":
    unittest.main()
