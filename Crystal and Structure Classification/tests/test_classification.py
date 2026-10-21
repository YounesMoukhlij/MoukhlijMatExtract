# Crystal and Structure Classification/tests/test_classification.py
"""Tests of the classification, on small made-up databases in a temporary folder: which class each
material gets and why, and the databases written for each class. The project's own databases are
never read or written.

    python -m pytest "Crystal and Structure Classification"
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from Classification import cli
from Classification.classify import Material, chemical_family, material_key, structure_labels, type_from_composition
from Classification.database import classify, read, write

MATERIAL_COLUMNS = ["paper_id", "material_id", "raw_formula", "normalized_formula", "elements", "structure",
                    "structure_basis"]
ENERGY_COLUMNS = ["paper_id", "material_formula", "activation_energy_eV", "composition", "structure", "material_id",
                  "sentence"]
PROPERTY_COLUMNS = ["paper_id", "material_id", "material_formula", "property_name", "normalized_value", "unit"]

COMPOSITIONS = {
    "Li7La3Zr2O12": {"La": 3.0, "Li": 7.0, "O": 12.0, "Zr": 2.0},
    "Li6PS5Cl": {"Cl": 1.0, "Li": 6.0, "P": 1.0, "S": 5.0},
    "Li1+xTi2-xAlx(PO4)3": {"Al": "x", "Li": "1+x", "O": 12.0, "P": 3.0, "Ti": "2-x"},
    "MgSc2Se4": {"Mg": 1.0, "Sc": 2.0, "Se": 4.0},
    "Li3YCl6": {"Cl": 6.0, "Li": 3.0, "Y": 1.0},
    "Li3OCl": {"Cl": 1.0, "Li": 3.0, "O": 1.0},
    "Li3P": {"Li": 3.0, "P": 1.0},
    "LiBH4": {"B": 1.0, "H": 4.0, "Li": 1.0},
}


def write_table(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_database(folder: Path, materials: list[tuple[str, str, str]], energies: list[tuple[str, str, float]]) -> Path:
    """materials: (paper, formula, structure); energies: (paper, formula, Ea)."""
    folder.mkdir(parents=True)
    ids = {}
    rows = []
    for paper, formula, structure in materials:
        ids[(paper, formula)] = f"MAT_{len(ids) + 1}"
        rows.append({"paper_id": paper, "material_id": ids[(paper, formula)], "raw_formula": formula,
                     "normalized_formula": formula, "elements": json.dumps(COMPOSITIONS.get(formula, {})),
                     "structure": structure, "structure_basis": "stated" if structure != "NONE" else "not stated"})
    write_table(folder / "materials.csv", MATERIAL_COLUMNS, rows)
    write_table(folder / "activation_energy.csv", ENERGY_COLUMNS, [
        {"paper_id": paper, "material_formula": formula, "activation_energy_eV": energy, "material_id": ids[(paper, formula)],
         "composition": json.dumps(COMPOSITIONS.get(formula, {})), "structure": "NONE",
         "sentence": f"{formula} has an activation energy of {energy} eV."} for paper, formula, energy in energies])
    write_table(folder / "properties.csv", PROPERTY_COLUMNS, [
        {"paper_id": paper, "material_id": ids[(paper, formula)], "material_formula": formula,
         "property_name": "Activation_Energy", "normalized_value": f"{energy} eV", "unit": "eV"}
        for paper, formula, energy in energies])
    papers = sorted({paper for paper, _, _ in materials})
    write_table(folder / "papers.csv", ["paper_id", "title", "doi"],
                [{"paper_id": paper, "title": f"Title of {paper}", "doi": "NONE"} for paper in papers])
    return folder


def checksum(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


class LabelTests(unittest.TestCase):
    def test_the_kinds_of_a_structure_cell(self):
        labels = structure_labels("β-phase | glass | cubic | garnet | Ia-3d")
        self.assertEqual((labels.types, labels.systems, labels.polymorphs, labels.space_groups, labels.states),
                         (("garnet",), ("cubic",), ("β-phase",), ("Ia-3d",), ("amorphous",)))
        self.assertEqual(structure_labels("tetragonal | LGPS").types, ("LGPS-type",))
        self.assertEqual(structure_labels("P2-type").types, ("layered",))  # the stacking of a layered oxide
        self.assertEqual(structure_labels("Li3YCl6-type").types, ("Li3YCl6-type",))
        self.assertEqual(structure_labels("chloride"), structure_labels("NONE"))  # the kind of compound is no structure

    def test_the_type_a_composition_settles(self):
        self.assertEqual(type_from_composition(COMPOSITIONS["Li7La3Zr2O12"]), ("garnet", "known for this composition"))
        self.assertEqual(type_from_composition(COMPOSITIONS["Li1+xTi2-xAlx(PO4)3"])[0], "NASICON")
        self.assertEqual(type_from_composition(COMPOSITIONS["Li3YCl6"]), (None, ""))  # its polymorphs differ

    def test_the_family_of_a_composition(self):
        families = {formula: chemical_family(amounts, formula)[0] for formula, amounts in COMPOSITIONS.items()}
        self.assertEqual(families, {"Li7La3Zr2O12": "oxide", "Li6PS5Cl": "sulfide", "Li1+xTi2-xAlx(PO4)3": "oxide",
                                    "MgSc2Se4": "selenide", "Li3YCl6": "halide", "Li3OCl": "oxyhalide",
                                    "Li3P": "phosphide", "LiBH4": "hydride"})
        self.assertEqual(chemical_family(COMPOSITIONS["Li6PS5Cl"], "Li6PS5Cl")[1], "thiophosphate")

    def test_one_composition_is_one_material(self):
        self.assertEqual(material_key({"Li": 1.3, "Al": 0.3, "Ti": 1.7}, "a"), material_key({"Ti": 1.7, "Li": 1.3, "Al": 0.3}, "b"))


class ClassifyTests(unittest.TestCase):
    def material(self, formula: str, structures: list[str]) -> Material:
        material = Material(material_key(COMPOSITIONS[formula], formula), COMPOSITIONS[formula])
        for index, structure in enumerate(structures):
            material.add("web_output", f"P{index}.pdf", formula, structure)
        material.classify()
        return material

    def test_the_composition_comes_first_and_what_the_papers_say_is_kept(self):
        garnet = self.material("Li7La3Zr2O12", ["cubic | garnet", "perovskite"])
        self.assertEqual(garnet.structure_type, "garnet")
        self.assertEqual(garnet.structure_type_basis, "known for this composition; the papers also state perovskite")
        self.assertEqual(garnet.row([0.31], [])["crystal_systems"], "cubic")

    def test_a_stated_type_classifies_when_enough_papers_state_it(self):
        spinel = self.material("MgSc2Se4", ["spinel", "NONE", "NONE"])
        self.assertEqual((spinel.structure_type, spinel.structure_type_basis),
                         ("spinel", "stated by 1 of the 3 paper(s) of this material"))

    def test_a_glassy_sample_in_one_paper_does_not_make_a_glass(self):
        self.assertEqual(self.material("Li3YCl6", ["glass", "amorphous", "NONE"]).structure_type, "amorphous")
        # One glass-ceramic sample among three papers that state nothing does not outweigh the
        # prototype its composition and its symmetry give.
        halide = self.material("Li3YCl6", ["glass-ceramic", "trigonal", "NONE"])
        self.assertEqual(halide.structure_type, "Li3YCl6-type")

    def test_a_prototype_from_the_composition_type_and_the_stated_symmetry(self):
        trigonal = self.material("Li3YCl6", ["trigonal | P-3m1"])
        self.assertEqual((trigonal.structure_type, trigonal.structure_type_basis),
                         ("Li3YCl6-type", "inferred: the prototype of its composition type (A3MX6 halide) with the "
                                          "symmetry its papers state (P-3m1, trigonal)"))
        self.assertEqual(self.material("Li3YCl6", ["monoclinic | C2/m"]).structure_type, "Li3InCl6-type")

    def test_a_type_few_papers_state_is_taken_and_says_so(self):
        selenide = self.material("MgSc2Se4", ["spinel", "NONE", "NONE", "NONE"])
        self.assertEqual((selenide.structure_type, selenide.structure_type_basis),
                         ("spinel", "stated by only 1 of the 4 paper(s) of this material"))
        self.assertEqual(selenide.family, "selenide")

    def test_what_nothing_settles_takes_its_analogues_type_or_its_composition_type(self):
        from Classification.classify import classify_the_rest
        extra = {"Li3Y0.9Er0.1Cl6": {"Cl": 6.0, "Er": 0.1, "Li": 3.0, "Y": 0.9}, "Li3ScCl6": {"Cl": 6.0, "Li": 3.0, "Sc": 1.0},
                 "Li2CO3": {"C": 1.0, "Li": 2.0, "O": 3.0}, "ZrO2": {"O": 2.0, "Zr": 1.0},
                 "NaZr2(PO4)3": {"Na": 1.0, "O": 12.0, "P": 3.0, "Zr": 2.0}}
        COMPOSITIONS.update(extra)
        for name in extra:
            self.addCleanup(COMPOSITIONS.pop, name)
        known = [self.material("Li3YCl6", ["trigonal"]), self.material("Li3YCl6", ["P-3m1"]), self.material("NaZr2(PO4)3", ["NONE"])]
        doped, other_m, alone, oxide = (self.material(name, ["NONE"]) for name in ("Li3Y0.9Er0.1Cl6", "Li3ScCl6", "Li2CO3", "ZrO2"))
        classify_the_rest([*known, doped, other_m, alone, oxide])
        # A doped variant of an established material takes its type ...
        self.assertEqual(doped.structure_type, "Li3YCl6-type")
        self.assertTrue(doped.structure_type_basis.startswith("inferred: the type of its analogues"), doped.structure_type_basis)
        # ... but another M is no analogue: the Li3MX6 halides change structure with the size of M.
        self.assertEqual(other_m.structure_type, "A3MX6 halide")
        # ZrO2 shares the cation of a zirconium phosphate, not its PO4 framework.
        self.assertEqual(known[2].structure_type, "NASICON")
        self.assertEqual(oxide.structure_type, "MX2 oxide")
        self.assertEqual((alone.structure_type, alone.family), ("A2MX3 oxide", "oxide"))
        self.assertTrue(alone.structure_type_basis.startswith("inferred: its composition type"))

    def test_a_state_is_not_handed_on_to_an_analogue(self):
        from Classification.classify import classify_the_rest
        COMPOSITIONS["Li3Y0.9Er0.1Cl6"] = {"Cl": 6.0, "Er": 0.1, "Li": 3.0, "Y": 0.9}
        self.addCleanup(COMPOSITIONS.pop, "Li3Y0.9Er0.1Cl6")
        glassy = self.material("Li3YCl6", ["glass", "amorphous"])
        doped = self.material("Li3Y0.9Er0.1Cl6", ["NONE"])
        classify_the_rest([glassy, doped])
        self.assertEqual((glassy.structure_type, doped.structure_type), ("amorphous", "A3MX6 halide"))

    def test_sodium_phases_and_halide_layers(self):
        COMPOSITIONS["Na3SbS4"] = {"Na": 3.0, "S": 4.0, "Sb": 1.0}
        self.addCleanup(COMPOSITIONS.pop, "Na3SbS4")
        self.assertEqual(self.material("Na3SbS4", ["NONE"]).structure_type, "Na3PS4-type")  # not thio-LISICON
        # "layered" said of a Li3MX6 halide is not a structure type: its symmetry decides.
        self.assertEqual(self.material("Li3YCl6", ["layered | trigonal"]).structure_type, "Li3YCl6-type")

    def test_elements_and_open_mixtures_have_their_own_classes(self):
        from Classification.classify import classify_the_rest
        COMPOSITIONS["Na"] = {"Na": 1.0}
        COMPOSITIONS["xLi2S-(100-x)SiS2"] = {"Li": "open", "S": "open", "Si": "open"}
        self.addCleanup(COMPOSITIONS.pop, "Na")
        self.addCleanup(COMPOSITIONS.pop, "xLi2S-(100-x)SiS2")
        sodium, mixture = self.material("Na", ["NONE"]), self.material("xLi2S-(100-x)SiS2", ["NONE"])
        classify_the_rest([sodium, mixture])
        self.assertEqual((sodium.structure_type, mixture.structure_type), ("elemental", "sulfide mixture (shares open)"))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = make_database(self.tmp / "local_output",
                                   [("A.pdf", "Li7La3Zr2O12", "cubic | garnet"), ("A.pdf", "Li6PS5Cl", "NONE")],
                                   [("A.pdf", "Li7La3Zr2O12", 0.32), ("A.pdf", "Li6PS5Cl", 0.21)])
        self.web = make_database(self.tmp / "web_output",
                                 [("10.1_b.pdf", "Li7La3Zr2O12", "NONE"), ("10.1_b.pdf", "Li3YCl6", "NONE"),
                                  ("10.1_b.pdf", "Li1+xTi2-xAlx(PO4)3", "NONE")],
                                 [("10.1_b.pdf", "Li7La3Zr2O12", 0.45), ("10.1_b.pdf", "Li3YCl6", 0.28),
                                  ("10.1_b.pdf", "Li1+xTi2-xAlx(PO4)3", 0.35)])
        self.before = {name: checksum(folder) for name, folder in (("local", self.local), ("web", self.web))}
        self.out = self.tmp / "classes"
        self.summaries = write(classify([read(self.local), read(self.web)]), self.out)

    def read_csv(self, *parts: str) -> list[dict]:
        with self.out.joinpath(*parts).open(encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def test_one_database_per_class_on_each_axis(self):
        # Li3YCl6, of which nothing is stated, is of no named type: its composition type is its class.
        self.assertEqual(sorted(p.name for p in (self.out / "crystal_structure").iterdir() if p.is_dir()),
                         ["NASICON", "argyrodite", "composition_types", "garnet"])
        self.assertEqual([p.name for p in (self.out / "crystal_structure" / "composition_types").iterdir()],
                         ["A3MX6 halide"])
        self.assertEqual(sorted(p.name for p in (self.out / "structure_families").iterdir() if p.is_dir()),
                         ["halide", "oxide", "sulfide"])
        for axis in ("crystal_structure", "structure_families"):
            self.assertTrue((self.out / axis / "summary.csv").is_file())
            self.assertTrue((self.out / axis / f"{axis}.xlsx").is_file())
        garnet = self.out / "crystal_structure" / "garnet"
        self.assertEqual(sorted(p.name for p in garnet.iterdir()),
                         ["activation_energy.csv", "diffusion_coefficient.csv", "electronic_conductivity.csv",
                          "ionic_conductivity.csv", "materials.csv", "papers.csv", "properties.csv"])
        everything = self.read_csv("all_materials.csv")
        self.assertFalse(any("unclassified" in str(v) for row in everything for v in row.values()))

    def test_a_material_of_both_databases_is_one_material_with_all_its_values(self):
        materials = self.read_csv("crystal_structure", "garnet", "materials.csv")
        self.assertEqual([(m["material"], m["n_papers"], m["databases"], m["Ea_min_eV"], m["Ea_max_eV"]) for m in materials],
                         [("Li7La3Zr2O12", "2", "local_output | web_output", "0.32", "0.45")])
        energies = self.read_csv("crystal_structure", "garnet", "activation_energy.csv")
        self.assertEqual(sorted((e["database"], e["activation_energy_eV"], e["crystal_structure"], e["structure_family"])
                                for e in energies),
                         [("local_output", "0.32", "garnet", "oxide"), ("web_output", "0.45", "garnet", "oxide")])
        self.assertEqual({p["paper_id"] for p in self.read_csv("crystal_structure", "garnet", "papers.csv")},
                         {"A.pdf", "10.1_b.pdf"})

    def test_every_value_is_in_one_class_of_each_axis(self):
        for axis in ("crystal_structure", "structure_families"):
            counted = sum(int(row["n_activation_energies"]) for row in self.read_csv(axis, "summary.csv"))
            self.assertEqual(counted, 5)
        everything = self.read_csv("all_materials.csv")
        self.assertEqual(len(everything), 4)
        self.assertEqual({m["material"]: m["crystal_structure_basis"] for m in everything}["Li1+xTi2-xAlx(PO4)3"],
                         "known for this composition series (taken at x = 0.25)")

    def test_the_databases_it_reads_are_left_as_they_were(self):
        self.assertEqual(self.before, {"local": checksum(self.local), "web": checksum(self.web)})

    def test_a_class_with_no_material_left_does_not_linger(self):
        shutil.rmtree(self.web)
        write(classify([read(self.local)]), self.out)
        self.assertEqual(sorted(p.name for p in (self.out / "crystal_structure").iterdir() if p.is_dir()),
                         ["argyrodite", "garnet"])

    def test_the_command(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--source", str(self.local), str(self.tmp / "nothing"), "--out", str(self.out)]), 0)
        self.assertIn("2 materials classified", out.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--source", str(self.tmp / "nothing"), "--out", str(self.out)]), 1)
            self.assertEqual(cli.main(["--source", str(self.local), "--out", str(self.local)]), 2)


if __name__ == "__main__":
    unittest.main()
